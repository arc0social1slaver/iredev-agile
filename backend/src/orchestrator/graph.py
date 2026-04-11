"""
graph.py – LangGraph orchestration.

Graph topology
──────────────
  supervisor
    ├─► interviewer_turn ◄──► enduser_turn   (Sprint Zero step 1)
    │       └─► supervisor  (interview_complete=True OR safety max_turns)
    ├─► sprint_agent_turn → supervisor        (Sprint Zero step 2)
    └─► END

Stopping / saturation design
─────────────────────────────
TIER 1 – semantic (PRIMARY):
  InterviewerAgent calls update_requirements after each stakeholder turn.
  When completeness ≥ threshold (default 0.8), it calls write_interview_record
  which sets interview_complete=True.  after_interviewer returns "supervisor".

TIER 2 – structural (SAFETY NET only):
  after_interviewer checks turn_count >= max_turns.
  Default = _INTERVIEW_SAFETY_MAX_TURNS = 20  ← single source of truth.
  Read from state["max_turns"] if explicitly set; falls back to this constant.
  Do NOT lower this to 2 or any small value for debugging — that bypasses the
  agent's own judgment and produces a trivially shallow interview record.
"""

from __future__ import annotations
import json
from pathlib import Path
import shutil
from datetime import datetime
import logging
from functools import lru_cache
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt


from .state import WorkflowState
from .supervisor import supervisor_node, supervisor_router

logger = logging.getLogger(__name__)

# ── Safety-net constant: single source of truth ───────────────────────────────
_INTERVIEW_SAFETY_MAX_TURNS = 20


@lru_cache(maxsize=1)
def _default_store() -> InMemoryStore:
    return InMemoryStore()


# ── Lazy agent singletons ─────────────────────────────────────────────────────


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


# ── Node functions ────────────────────────────────────────────────────────────


def review_node(state: WorkflowState):
    response = interrupt(
        {
            "type": "review",
            "content": state.get("artifacts"),
            "instruction": "Accept or reject. If reject, provide feedback. If accept, type 'y' only: ",
        }
    )
    state["review_approved"] = True if response["action"] == "accept" else False
    state["review_feedback"] = response.get("feedback")

    return state


def supervisor_node_fn(state: WorkflowState) -> Dict[str, Any]:
    return supervisor_node(state)


def interviewer_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    updates = _get_interviewer().process(state)
    logger.debug("interviewer_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


def enduser_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    updates = _get_enduser().process(state)
    logger.debug("enduser_turn updates: %s", list(updates.keys()))
    return updates


def sprint_agent_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    updates = _get_sprint_agent().process(state)
    logger.debug("sprint_agent_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


# ── Store sync ────────────────────────────────────────────────────────────────


def _sync_artifacts_to_store(
    state: WorkflowState,
    updates: Dict[str, Any],
) -> None:
    new_artifacts: Dict[str, Any] = updates.get("artifacts") or {}
    if not new_artifacts:
        return

    session_id = state.get("session_id", "default")
    store = _default_store()
    namespace = ("artifacts", session_id)

    existing_items = {
        item.key: item.value.get("content") for item in store.search(namespace)
    }

    base_dir = Path("../artifacts")
    latest_dir = base_dir / "artifact"
    versions_dir = base_dir / "versions"

    latest_dir.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)

    for name, content in new_artifacts.items():
        is_new_or_updated = False
        if name not in existing_items:
            is_new_or_updated = True
        elif existing_items[name] != content:
            is_new_or_updated = True

        if is_new_or_updated:
            store.put(namespace, name, {"content": content})
            logger.info("Store: persisted '%s' for session '%s'.", name, session_id)

            file_name = f"{name}_{session_id}.json"
            latest_file_path = latest_dir / file_name

            if latest_file_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                version_file_name = f"{name}_{session_id}_v{timestamp}.json"
                version_file_path = versions_dir / version_file_name

                shutil.move(str(latest_file_path), str(version_file_path))
                logger.info(
                    "File: Moved older version of '%s' to versions folder.", name
                )

            try:
                with open(latest_file_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
                logger.info(
                    "File: Saved latest artifact '%s' to %s", name, latest_file_path
                )
            except Exception as e:
                logger.error("File: Failed to save artifact '%s': %s", name, e)


def get_artifact_from_store(session_id: str, artifact_name: str) -> Optional[Any]:
    store = _default_store()
    item = store.get(("artifacts", session_id), artifact_name)
    return item.value.get("content") if item else None


# ── Conditional edge ──────────────────────────────────────────────────────────


def after_interviewer(state: WorkflowState) -> str:
    """
    Two-tier stopping logic.

    TIER 1 (primary)   – interview_complete=True  set by the agent.
    TIER 2 (safety net) – turn_count >= max_turns  structural guard.

    max_turns defaults to _INTERVIEW_SAFETY_MAX_TURNS (20), NOT 2.
    The old hardcoded default of 2 was a debug trap: it forced a shallow
    record before the agent had a chance to exercise its own judgment.
    """
    # ── Tier 1 ───────────────────────────────────────────────────────────
    if state.get("interview_complete", False):
        logger.info("Tier-1 stop: interview_complete=True → supervisor.")
        return "supervisor"

    # ── Tier 2 ───────────────────────────────────────────────────────────
    turn_count = state.get("turn_count", 0)
    max_turns = state.get("max_turns", _INTERVIEW_SAFETY_MAX_TURNS)

    if turn_count >= max_turns:
        logger.warning(
            "Tier-2 safety net: turn_count=%d >= max_turns=%d → forcing supervisor. "
            "Consider reviewing completeness_threshold or raising max_turns.",
            turn_count,
            max_turns,
        )
        return "supervisor"

    logger.debug("Interview continues: %d / %d turns.", turn_count, max_turns)
    return "enduser_turn"


def route_after_review(state: WorkflowState):
    if state.get("review_approved") == True:
        return "supervisor"  # forward
    return "review"  # go back


# ── Build graph ───────────────────────────────────────────────────────────────


def build_graph(store=None, checkpointer=None):
    """
    Compile the LangGraph workflow.

    Sprint Zero chain:
      interviewer_turn → (loop with enduser_turn) → supervisor
                       → sprint_agent_turn → supervisor → END
    """
    if store is None:
        store = _default_store()

    g = StateGraph(WorkflowState)

    g.add_node("supervisor", supervisor_node_fn)
    g.add_node("interviewer_turn", interviewer_turn_fn)
    g.add_node("enduser_turn", enduser_turn_fn)
    g.add_node("sprint_agent_turn", sprint_agent_turn_fn)
    g.add_node("review", review_node)

    g.set_entry_point("supervisor")

    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "interviewer_turn": "interviewer_turn",
            "sprint_agent_turn": "sprint_agent_turn",
            "__end__": END,
        },
    )

    g.add_conditional_edges(
        "interviewer_turn",
        after_interviewer,
        {
            "supervisor": "supervisor",
            "enduser_turn": "enduser_turn",
        },
    )
    g.add_edge("enduser_turn", "interviewer_turn")
    g.add_conditional_edges(
        "sprint_agent_turn",
        route_after_review,
        {
            "supervisor": "supervisor",
            "review": "review",
        },
    )
    g.add_edge("review", "sprint_agent_turn")

    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    else:
        compile_kwargs["checkpointer"] = InMemorySaver()

    return g.compile(**compile_kwargs)
