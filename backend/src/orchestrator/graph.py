"""
graph.py – LangGraph orchestration.

Graph topology
──────────────
  supervisor
    ├─► interviewer_turn ◄──► enduser_turn   (Sprint Zero step 1)
    │       └─► supervisor  (interview_complete=True OR safety max_turns)
    ├─► review_turn                           (Sprint Zero step 2 — NEW)
    │       ├─► supervisor  (approved → reviewed_interview_record written)
    │       └─► supervisor  (rejected → interview_record cleared, feedback set)
    ├─► sprint_agent_turn → supervisor        (Sprint Zero step 3)
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

Review node design
──────────────────
review_turn uses LangGraph's interrupt() to pause execution and present the
interview record (requirements + rationale + history) to a human reviewer.

The reviewer supplies a dict:
  {"approved": True}                          → approval
  {"approved": False, "feedback": "<text>"}   → rejection

On approval:
  • reviewed_interview_record artifact is written (copy of interview_record
    with status="approved" and reviewer metadata).
  • Flow advances to sprint_agent_turn (build_product_backlog).

On rejection:
  • interview_record is removed from artifacts (so the flow loops back to
    conduct_requirements_interview).
  • review_feedback is set in state so InterviewerAgent's task prompt shows
    exactly what needs improving.
  • interview_complete is reset to False so the interview restarts cleanly.
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
from langgraph.types import interrupt   # human-in-the-loop pause

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


# ── Review node ───────────────────────────────────────────────────────────────

def review_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """
    Human-in-the-loop review of the interview record.

    Pauses execution via interrupt() and presents the requirements (with
    rationale and history) to the reviewer.  Resumes when the reviewer
    supplies a response dict.

    Expected reviewer response
    ──────────────────────────
    Approval:  {"approved": True}
    Rejection: {"approved": False, "feedback": "<what to improve>"}

    State mutations
    ───────────────
    Approval  → artifacts["reviewed_interview_record"] written;
                review_approved = True; review_feedback = None.
    Rejection → artifacts["interview_record"] removed;
                interview_complete = False;
                review_approved = False;
                review_feedback = <feedback text>.
    """
    artifacts = dict(state.get("artifacts") or {})
    record    = artifacts.get("interview_record", {})

    # ── Build a human-readable review payload ─────────────────────────────
    requirements = record.get("requirements_identified", [])
    review_payload = _format_review_payload(record, requirements)

    # ── Pause and wait for human decision ─────────────────────────────────
    reviewer_response: Dict[str, Any] = interrupt(review_payload)

    approved  = bool(reviewer_response.get("approved", False))
    feedback  = (reviewer_response.get("feedback") or "").strip()

    # ── Approval path ──────────────────────────────────────────────────────
    if approved:
        reviewed_record = {
            **record,
            "status":        "approved",
            "reviewed_at":   datetime.now().isoformat(),
            "review_notes":  feedback or None,   # optional approval notes
        }
        artifacts["reviewed_interview_record"] = reviewed_record

        logger.info(
            "[Review] Interview record APPROVED — %d requirements.",
            len(requirements),
        )
        return {
            "artifacts":      artifacts,
            "review_approved": True,
            "review_feedback": None,
        }

    # ── Rejection path ─────────────────────────────────────────────────────
    # Remove interview_record so the supervisor re-routes to
    # conduct_requirements_interview in the next cycle.
    artifacts.pop("interview_record", None)

    logger.info(
        "[Review] Interview record REJECTED. Feedback: %s",
        feedback or "(none provided)",
    )
    return {
        "artifacts":         artifacts,
        "interview_complete": False,   # reset so the interview loop restarts
        "review_approved":    False,
        "review_feedback":    feedback or "The reviewer did not provide specific feedback.",
    }


def _format_review_payload(
    record: Dict[str, Any],
    requirements: list,
) -> Dict[str, Any]:
    """
    Build the structured payload shown to the human reviewer.

    The payload contains:
      • Project description
      • Interview summary (completeness score, gap count, notes)
      • Requirements table: id · type · priority · status · description
                            · rationale · history
    """
    req_summaries = []
    for r in requirements:
        history_lines = []
        for h in r.get("history") or []:
            line = (
                f"    [{h.get('action', '?')}] turn {h.get('turn', '?')}: "
                f"{h.get('reason', '')}"
            )
            if h.get("old_value"):
                line += f" (was: {h['old_value'][:120]})"
            history_lines.append(line)

        req_summaries.append({
            "id":          r.get("id"),
            "type":        r.get("type"),
            "priority":    r.get("priority"),
            "status":      r.get("status"),
            "description": r.get("description"),
            "rationale":   r.get("rationale", "(not provided)"),
            "history":     history_lines or ["(no history)"],
        })

    return {
        "review_prompt": (
            "Please review the interview record below.\n"
            "For each requirement you can see:\n"
            "  • description  — the testable requirement statement\n"
            "  • rationale    — why the interviewer identified this requirement\n"
            "  • history      — how (and why) the requirement evolved\n\n"
            "Respond with:\n"
            "  {\"approved\": true}                              to approve\n"
            "  {\"approved\": false, \"feedback\": \"<text>\"}  to request changes"
        ),
        "project_description": record.get("project_description", ""),
        "completeness_score":  record.get("completeness_score"),
        "gaps":                record.get("gaps_identified", []),
        "notes":               record.get("notes", ""),
        "total_turns":         record.get("total_turns"),
        "requirements":        req_summaries,
    }


# ── Store sync ────────────────────────────────────────────────────────────────

def _sync_artifacts_to_store(
        state: WorkflowState,
        updates: Dict[str, Any],
) -> None:
    new_artifacts: Dict[str, Any] = updates.get("artifacts") or {}
    if not new_artifacts:
        return

    session_id = state.get("session_id", "default")
    store      = _default_store()
    namespace  = ("artifacts", session_id)

    existing_items = {
        item.key: item.value.get("content")
        for item in store.search(namespace)
    }

    base_dir     = Path("../artifacts")
    latest_dir   = base_dir / "artifact"
    versions_dir = base_dir / "versions"

    latest_dir.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)

    for name, content in new_artifacts.items():
        is_new_or_updated = (
            name not in existing_items or existing_items[name] != content
        )

        if is_new_or_updated:
            store.put(namespace, name, {"content": content})
            logger.info("Store: persisted '%s' for session '%s'.", name, session_id)

            file_name       = f"{name}_{session_id}.json"
            latest_file_path = latest_dir / file_name

            if latest_file_path.exists():
                timestamp         = datetime.now().strftime("%Y%m%d_%H%M%S")
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
                logger.error(
                    "File: Failed to save artifact '%s': %s", name, e
                )


def get_artifact_from_store(session_id: str, artifact_name: str) -> Optional[Any]:
    store = _default_store()
    item  = store.get(("artifacts", session_id), artifact_name)
    return item.value.get("content") if item else None


# ── Conditional edge: after interviewer ──────────────────────────────────────

def after_interviewer(state: WorkflowState) -> str:
    """
    Two-tier stopping logic.

    TIER 1 (primary)    – interview_complete=True  set by the agent.
    TIER 2 (safety net) – turn_count >= max_turns  structural guard.

    max_turns defaults to _INTERVIEW_SAFETY_MAX_TURNS (20), NOT 2.
    """
    if state.get("interview_complete", False):
        logger.info("Tier-1 stop: interview_complete=True → supervisor.")
        return "supervisor"

    turn_count = state.get("turn_count", 0)
    max_turns  = state.get("max_turns", _INTERVIEW_SAFETY_MAX_TURNS)

    if turn_count >= max_turns:
        logger.warning(
            "Tier-2 safety net: turn_count=%d >= max_turns=%d → forcing supervisor. "
            "Consider reviewing completeness_threshold or raising max_turns.",
            turn_count, max_turns,
        )
        return "supervisor"

    logger.debug("Interview continues: %d / %d turns.", turn_count, max_turns)
    return "enduser_turn"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_graph(store=None, checkpointer=None):
    """
    Compile the LangGraph workflow.

    Sprint Zero chain:
      interviewer_turn → (loop with enduser_turn) → supervisor
                       → review_turn → supervisor
                       → sprint_agent_turn → supervisor → END

    Note: review_turn uses interrupt() so a checkpointer is REQUIRED for
    production use (e.g. SqliteSaver or PostgresSaver).  Pass one in via
    the ``checkpointer`` argument.  In-memory runs without a checkpointer
    will work in unit tests that mock interrupt().
    """
    if store is None:
        store = _default_store()

    if checkpointer is None:
        logger.warning(
            "build_graph: no checkpointer provided.  review_turn uses "
            "interrupt() which requires persistent checkpoint storage in "
            "production.  Pass a checkpointer (e.g. SqliteSaver) to "
            "build_graph() to enable durable human-in-the-loop review."
        )

    g = StateGraph(WorkflowState)

    g.add_node("supervisor",        supervisor_node_fn)
    g.add_node("interviewer_turn",  interviewer_turn_fn)
    g.add_node("enduser_turn",      enduser_turn_fn)
    g.add_node("review_turn",       review_turn_fn)       # NEW
    g.add_node("sprint_agent_turn", sprint_agent_turn_fn)

    g.set_entry_point("supervisor")

    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "interviewer_turn":  "interviewer_turn",
            "review_turn":       "review_turn",           # NEW
            "sprint_agent_turn": "sprint_agent_turn",
            "__end__":           END,
        },
    )

    g.add_conditional_edges(
        "interviewer_turn",
        after_interviewer,
        {
            "supervisor":   "supervisor",
            "enduser_turn": "enduser_turn",
        },
    )
    g.add_edge("enduser_turn",      "interviewer_turn")
    g.add_edge("review_turn",       "supervisor")         # NEW (both approval and rejection go back to supervisor)
    g.add_edge("sprint_agent_turn", "supervisor")

    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)