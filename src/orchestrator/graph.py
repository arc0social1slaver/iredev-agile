"""
graph.py – LangGraph orchestration.

Graph topology
──────────────
  supervisor
    ├─► interviewer_turn ◄──► enduser_turn   (interview loop, Sprint Zero step 1)
    │       └─► supervisor  (when interview_complete or max_turns reached)
    ├─► sprint_agent_turn → supervisor        (Sprint Zero step 2)
    └─► END                                   (all phases complete)

Future phases (Sprint Execution, Sprint Review) plug in here:
    supervisor ─► <new_node> → supervisor

Artifact persistence
────────────────────
Artifacts flow through WorkflowState["artifacts"] for in-process communication.
New artifacts are also written to a LangGraph InMemoryStore (swap for
PostgresStore in production) keyed by (session_id, artifact_name).

Entry point
───────────
  graph = build_graph()
  result = graph.invoke(initial_state)   # or .stream() for streaming output

Production usage
────────────────
  from langgraph.store.postgres import PostgresStore
  from langgraph.checkpoint.postgres import PostgresSaver
  store      = PostgresStore.from_conn_string("postgresql://...")
  checkpoint = PostgresSaver.from_conn_string("postgresql://...")
  graph = build_graph(store=store, checkpointer=checkpoint)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore

from .state import WorkflowState
from .supervisor import supervisor_node, supervisor_router

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared in-process store (development default)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _default_store() -> InMemoryStore:
    return InMemoryStore()


# ---------------------------------------------------------------------------
# Lazy agent singletons – constructed once per process
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_interviewer():
    from ..agent.interviewer import InterviewerAgent
    return InterviewerAgent()


@lru_cache(maxsize=1)
def _get_enduser():
    from ..agent.enduser import EndUserAgent
    return EndUserAgent()


@lru_cache(maxsize=1)
def _get_sprint_agent():
    from ..agent.sprint import SprintAgent
    return SprintAgent()


# ---------------------------------------------------------------------------
# Node functions
# Each function is a thin wrapper that calls an agent and optionally syncs
# new artifacts to the persistent store.
# ---------------------------------------------------------------------------

def supervisor_node_fn(state: WorkflowState) -> Dict[str, Any]:
    """Routing node – decides which step to run next."""
    return supervisor_node(state)


def interviewer_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """One ReAct turn of the InterviewerAgent (Sprint Zero, step 1)."""
    updates = _get_interviewer().process(state)
    logger.debug("interviewer_turn produced updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


def enduser_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """One ReAct turn of the EndUserAgent (stakeholder simulator)."""
    updates = _get_enduser().process(state)
    logger.debug("enduser_turn produced updates: %s", list(updates.keys()))
    return updates


def sprint_agent_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """
    One turn of the SprintAgent (Sprint Zero, step 2).

    Triggered automatically by the supervisor once interview_record exists
    but product_backlog does not yet.
    """
    updates = _get_sprint_agent().process(state)
    logger.debug("sprint_agent_turn produced updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


# ---------------------------------------------------------------------------
# Store sync helper
# ---------------------------------------------------------------------------

def _sync_artifacts_to_store(
    state: WorkflowState,
    updates: Dict[str, Any],
) -> None:
    """
    Write newly produced artifacts from *updates* to the LangGraph store.

    Namespace : ("artifacts", session_id)
    Key       : artifact name  (e.g. "interview_record")
    Value     : {"content": <artifact dict>}
    """
    new_artifacts: Dict[str, Any] = updates.get("artifacts") or {}
    if not new_artifacts:
        return

    session_id = state.get("session_id", "default")
    store      = _default_store()
    namespace  = ("artifacts", session_id)

    existing_keys = {item.key for item in store.search(namespace)}

    for artifact_name, content in new_artifacts.items():
        if artifact_name not in existing_keys:
            store.put(namespace, artifact_name, {"content": content})
            logger.info(
                "Store: persisted artifact '%s' for session '%s'.",
                artifact_name, session_id,
            )


# ---------------------------------------------------------------------------
# Convenience: retrieve an artifact from the store
# ---------------------------------------------------------------------------

def get_artifact_from_store(
    session_id: str,
    artifact_name: str,
) -> Optional[Any]:
    """
    Retrieve a persisted artifact by session and name.

    Usage (e.g. from a notebook or API handler):
        record = get_artifact_from_store("session_1", "interview_record")
        backlog = get_artifact_from_store("session_1", "product_backlog")
    """
    store     = _default_store()
    namespace = ("artifacts", session_id)
    item      = store.get(namespace, artifact_name)
    return item.value.get("content") if item else None


# ---------------------------------------------------------------------------
# Conditional edge: after each interviewer turn
# ---------------------------------------------------------------------------

def after_interviewer(state: WorkflowState) -> str:
    """
    Decide what happens after the InterviewerAgent finishes a turn.

    Returns
    ───────
    "supervisor"   – interview is done (interview_complete=True or max turns hit)
    "enduser_turn" – interview is still in progress; pass the baton to EndUser
    """
    if state.get("interview_complete", False):
        logger.info("Interview complete – returning to supervisor.")
        return "supervisor"

    turn_count = state.get("turn_count", 0)
    max_turns  = state.get("max_turns", 2)
    if turn_count >= max_turns:
        logger.warning(
            "Max interview turns (%d) reached – forcing return to supervisor.",
            max_turns,
        )
        return "supervisor"

    return "enduser_turn"


# ---------------------------------------------------------------------------
# Build the compiled graph
# ---------------------------------------------------------------------------

def build_graph(store=None, checkpointer=None):
    """
    Construct and compile the full LangGraph workflow.

    Parameters
    ──────────
    store        : LangGraph BaseStore (default: in-process InMemoryStore).
                   Swap for PostgresStore in production.
    checkpointer : LangGraph BaseCheckpointSaver (optional).
                   Enables conversation resumption across process restarts.

    Returns
    ───────
    CompiledStateGraph ready for .invoke() / .stream().
    """
    if store is None:
        store = _default_store()

    g = StateGraph(WorkflowState)

    # ── Node registration ─────────────────────────────────────────────────
    g.add_node("supervisor",        supervisor_node_fn)
    g.add_node("interviewer_turn",  interviewer_turn_fn)
    g.add_node("enduser_turn",      enduser_turn_fn)
    g.add_node("sprint_agent_turn", sprint_agent_turn_fn)

    # Future phase nodes (register here as implemented):
    # g.add_node("sprint_planner_turn", sprint_planner_turn_fn)
    # g.add_node("developer_turn",      developer_turn_fn)
    # g.add_node("reviewer_turn",       reviewer_turn_fn)

    # ── Entry point ───────────────────────────────────────────────────────
    g.set_entry_point("supervisor")

    # ── Supervisor routing ────────────────────────────────────────────────
    # supervisor_router reads state["next_node"] set by supervisor_node.
    # Keys here must match the node_name values in flow.py ArtifactStep defs.
    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "interviewer_turn":  "interviewer_turn",
            "sprint_agent_turn": "sprint_agent_turn",
            "__end__":           END,
            # Future phases (add entries as steps are implemented):
            # "sprint_planner_turn": "sprint_planner_turn",
            # "developer_turn":      "developer_turn",
            # "reviewer_turn":       "reviewer_turn",
        },
    )

    # ── Interview loop (Sprint Zero, step 1) ──────────────────────────────
    g.add_conditional_edges(
        "interviewer_turn",
        after_interviewer,
        {
            "supervisor":   "supervisor",
            "enduser_turn": "enduser_turn",
        },
    )
    # EndUser always hands control back to the Interviewer
    g.add_edge("enduser_turn", "interviewer_turn")

    # ── Sprint Agent → Supervisor (Sprint Zero, step 2) ───────────────────
    # After producing the product_backlog, hand control back so the supervisor
    # can decide whether to advance to the next phase or END.
    g.add_edge("sprint_agent_turn", "supervisor")

    # ── Compile ───────────────────────────────────────────────────────────
    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)