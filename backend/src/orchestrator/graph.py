"""
graph.py – LangGraph orchestration.

Graph topology
──────────────
  supervisor
    ├─► interviewer_turn ◄──► enduser_turn   (Sprint Zero step 1)
    │       └─► supervisor  (interview_complete=True OR safety max_turns)
    ├─► review_turn                           (Sprint Zero step 2)
    │       ├─► supervisor  (approved → reviewed_interview_record written)
    │       └─► supervisor  (rejected → interview_record cleared, feedback set)
    ├─► sprint_agent_turn → supervisor        (Sprint Zero steps 3 & 5)
    │       step 3: produces product_backlog_draft   (Pipeline A-Draft)
    │       step 5: produces product_backlog          (Pipeline A-Refine)
    ├─► analyst_turn → supervisor             (Sprint Zero step 4)
    │       produces analyst_feedback
    └─► END

Stopping design (two-tier, Interviewer-only)
─────────────────────────────────────────────
INTERVIEWER IS THE SOLE AUTHORITY on stopping.  EndUserAgent has no mechanism
to set interview_complete or to call FINISH.

TIER 2 — Marginal IG per domain: ig_score degrades to 0.0 after 3 dry calls.
TIER 3 — Metacognitive Coherence Check: lives in Interviewer's [STRATEGY] block.

SAFETY NET (graph-layer): after_interviewer checks turn_count >= max_turns.

Review node design
──────────────────
review_turn uses LangGraph's interrupt() to pause execution.
Reviewer response dict:
  {"approved": True}                          → approval
  {"approved": False, "feedback": "<text>"}   → rejection

Analyst loop
────────────
analyst_turn is a pure read-then-write pass:
  1. Reads product_backlog_draft + requirement rationale from state.
  2. Calls AnalystAgent.process() — uses BaseAgent.react() infrastructure.
  3. Writes analyst_feedback artifact.
  4. Routes back to supervisor → sprint_agent_turn (Pipeline A-Refine).

Memory format safety
────────────────────
BaseAgent.react() now calls _ensure_lc_messages() before passing memory to
ThinkModule.  This normalises any dict/serialised-dict format that MemoryModule
may return into proper LangChain BaseMessage objects.  All agent singletons
benefit automatically.
"""

from __future__ import annotations

import json
import shutil
import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore
from langgraph.types import interrupt

from .state import WorkflowState
from .supervisor import supervisor_node, supervisor_router

logger = logging.getLogger(__name__)

_INTERVIEW_SAFETY_MAX_TURNS = 20


# ── Lazy agent singletons ─────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _default_store() -> InMemoryStore:
    return InMemoryStore()


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


@lru_cache(maxsize=1)
def _get_analyst():
    from ..agent.analyst import AnalystAgent
    return AnalystAgent()


# ── Node functions ────────────────────────────────────────────────────────────

def supervisor_node_fn(state: WorkflowState) -> Dict[str, Any]:
    return supervisor_node(state)


def interviewer_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    updates = _get_interviewer().process(state)
    logger.debug("interviewer_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


_ENDUSER_MAX_ATTEMPTS = 3


def enduser_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run EndUserAgent, retrying if the agent exits without calling 'respond'.

    EndUserAgent.respond sets should_return=True inside ITS OWN ReAct loop only.
    It does NOT set interview_complete.  The edge from enduser_turn always returns
    to interviewer_turn — the enduser can never terminate the interview.
    """
    for attempt in range(1, _ENDUSER_MAX_ATTEMPTS + 1):
        augmented_state = dict(state)
        if attempt > 1:
            augmented_state["_enduser_retry_hint"] = (
                f"[Attempt {attempt}/{_ENDUSER_MAX_ATTEMPTS}] "
                "You MUST call the 'respond' tool right now.  "
                "Do not generate plain text — use the tool."
            )

        updates = _get_enduser().process(augmented_state)
        logger.debug(
            "enduser_turn attempt %d/%d — updates: %s",
            attempt, _ENDUSER_MAX_ATTEMPTS, list(updates.keys()),
        )

        new_conversation = updates.get("conversation") or state.get("conversation") or []
        if new_conversation and new_conversation[-1].get("role") == "enduser":
            return updates

        logger.warning(
            "enduser_turn attempt %d/%d: 'respond' not called. Retrying...",
            attempt, _ENDUSER_MAX_ATTEMPTS,
        )

    logger.error(
        "enduser_turn: EndUserAgent failed to call 'respond' after %d attempts.",
        _ENDUSER_MAX_ATTEMPTS,
    )
    return {}


def sprint_agent_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """SprintAgent node — handles both Pipeline A-Draft and Pipeline A-Refine.

    process() auto-detects which pipeline to run:
      • product_backlog_draft absent → A-Draft  (produces product_backlog_draft)
      • analyst_feedback present, product_backlog absent → A-Refine (produces product_backlog)
    """
    updates = _get_sprint_agent().process(state)
    logger.debug("sprint_agent_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


def analyst_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """AnalystAgent node — INVEST + NLP review of product_backlog_draft.

    Produces analyst_feedback artifact.  Routes back to supervisor which then
    routes to sprint_agent_turn (Pipeline A-Refine).
    """
    updates = _get_analyst().process(state)
    logger.debug("analyst_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


# ── Review node ───────────────────────────────────────────────────────────────

def review_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Human-in-the-loop review of the interview record.

    Presents every requirement with its structured rationale (4-section mini-LLM
    synthesis) and full history (HITL edits tagged hitl_modified / hitl_added /
    hitl_deleted).  The rationale chain is:
      stakeholder words → mini-LLM synthesis → rationale field →
      HITL review payload → recorded in history on every edit.
    """
    artifacts    = dict(state.get("artifacts") or {})
    record       = artifacts.get("interview_record", {})
    requirements = record.get("requirements_identified", [])

    review_payload    = _format_review_payload(record, requirements)
    reviewer_response: Dict[str, Any] = interrupt(review_payload)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        reviewed_record = {
            **record,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        artifacts["reviewed_interview_record"] = reviewed_record
        logger.info("[Review] APPROVED — %d requirements.", len(requirements))
        return {
            "artifacts":       artifacts,
            "review_approved": True,
            "review_feedback": None,
        }

    artifacts.pop("interview_record", None)
    logger.info("[Review] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":         artifacts,
        "interview_complete": False,
        "review_approved":    False,
        "review_feedback":    feedback or "The reviewer did not provide specific feedback.",
    }


def _format_review_payload(
    record: Dict[str, Any],
    requirements: list,
) -> Dict[str, Any]:
    """Build the structured payload presented to the human reviewer.

    Each requirement is shown with:
      • description  — the testable statement
      • rationale    — structured 4-section synthesis (STAKEHOLDER EVIDENCE /
                       INFERENCE / REQUIREMENT BASIS / CONFIDENCE)
      • history      — every edit with its reason, including prior HITL changes
    """
    req_summaries = []
    for r in requirements:
        history_lines = []
        for h in r.get("history") or []:
            action = h.get("action", "?")
            turn   = h.get("turn", "?")
            reason = h.get("reason", "")
            line   = f"    [{action}] turn {turn}: {reason}"
            if h.get("old_value"):
                line += f"  (was: {str(h['old_value'])[:120]})"
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
            "Please review the interview record.\n"
            "For each requirement you will see:\n"
            "  • description — the testable requirement statement\n"
            "  • rationale   — 4-section synthesis: STAKEHOLDER EVIDENCE / INFERENCE / "
            "REQUIREMENT BASIS / CONFIDENCE\n"
            "  • history     — how it evolved; HITL edits tagged [hitl_modified] etc.\n\n"
            "Respond with:\n"
            "  {\"approved\": true}                              to approve\n"
            "  {\"approved\": false, \"feedback\": \"<text>\"}  to request changes"
        ),
        "project_description": record.get("project_description", ""),
        "completeness_score":  record.get("completeness_score"),
        "ig_summary":          record.get("ig_summary", {}),
        "gaps":                record.get("gaps_identified", []),
        "notes":               record.get("notes", ""),
        "total_turns":         record.get("total_turns"),
        "requirements":        req_summaries,
    }


# ── Artifact persistence ──────────────────────────────────────────────────────

def _sync_artifacts_to_store(
    state:   WorkflowState,
    updates: Dict[str, Any],
) -> None:
    new_artifacts = updates.get("artifacts") or {}
    if not new_artifacts:
        return

    session_id   = state.get("session_id", "default")
    store        = _default_store()
    namespace    = ("artifacts", session_id)
    existing     = {
        item.key: item.value.get("content")
        for item in store.search(namespace)
    }

    base_dir     = Path("../artifacts")
    latest_dir   = base_dir / "artifact"
    versions_dir = base_dir / "versions"
    latest_dir.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)

    for name, content in new_artifacts.items():
        if name not in existing or existing[name] != content:
            store.put(namespace, name, {"content": content})
            file_name   = f"{name}_{session_id}.json"
            latest_path = latest_dir / file_name

            if latest_path.exists():
                ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
                version_path = versions_dir / f"{name}_{session_id}_v{ts}.json"
                shutil.move(str(latest_path), str(version_path))
                logger.info("File: versioned '%s'.", name)

            try:
                with open(latest_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
                logger.info("File: saved artifact '%s' → %s", name, latest_path)
            except Exception as exc:
                logger.error("File: failed to save '%s': %s", name, exc)


def get_artifact_from_store(session_id: str, artifact_name: str) -> Optional[Any]:
    store = _default_store()
    item  = store.get(("artifacts", session_id), artifact_name)
    return item.value.get("content") if item else None


# ── Conditional edge: after interviewer ──────────────────────────────────────

def after_interviewer(state: WorkflowState) -> str:
    """Route after each interviewer turn.

    Primary path  – interview_complete=True  → supervisor.
    Safety net    – turn_count >= max_turns  → supervisor.
    Guard         – no message posted        → interviewer_turn (retry).
    Normal        – routes to enduser_turn.
    """
    if state.get("interview_complete", False):
        logger.info("Tier-2/3 stop: interview_complete=True → supervisor.")
        return "supervisor"

    turn_count = state.get("turn_count", 0)
    max_turns  = state.get("max_turns", _INTERVIEW_SAFETY_MAX_TURNS)
    if turn_count >= max_turns:
        logger.warning(
            "Safety net: turn_count=%d >= max_turns=%d → supervisor (incomplete record).",
            turn_count, max_turns,
        )
        return "supervisor"

    conversation = state.get("conversation") or []
    last_role = conversation[-1].get("role") if conversation else None

    if last_role != "interviewer":
        logger.warning(
            "after_interviewer: no new message posted (last_role=%r) — retrying.",
            last_role,
        )
        return "interviewer_turn"

    logger.debug("Interview continues: %d/%d turns.", turn_count, max_turns)
    return "enduser_turn"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_graph(store=None, checkpointer=None):
    """Compile the LangGraph workflow.

    Sprint Zero chain:
      interviewer_turn ↔ enduser_turn  (until interview_complete or max_turns)
      → supervisor → review_turn
      → supervisor → sprint_agent_turn  (Pipeline A-Draft → product_backlog_draft)
      → supervisor → analyst_turn       (AnalystAgent review → analyst_feedback)
      → supervisor → sprint_agent_turn  (Pipeline A-Refine → product_backlog)
      → supervisor → END

    review_turn uses interrupt() — a checkpointer is required in production.

    Note on sprint_agent_turn reuse
    ────────────────────────────────
    The same node (sprint_agent_turn) handles both A-Draft and A-Refine.
    SprintAgent.process() inspects artifact state to determine which pipeline to run.
    This keeps the graph topology simple and avoids a separate node for each pipeline.
    """
    if store is None:
        store = _default_store()

    if checkpointer is None:
        logger.warning(
            "build_graph: no checkpointer. review_turn uses interrupt() which "
            "requires persistent storage in production."
        )

    g = StateGraph(WorkflowState)

    # ── Nodes ─────────────────────────────────────────────────────────────
    g.add_node("supervisor",        supervisor_node_fn)
    g.add_node("interviewer_turn",  interviewer_turn_fn)
    g.add_node("enduser_turn",      enduser_turn_fn)
    g.add_node("review_turn",       review_turn_fn)
    g.add_node("sprint_agent_turn", sprint_agent_turn_fn)
    g.add_node("analyst_turn",      analyst_turn_fn)      # ← NEW

    g.set_entry_point("supervisor")

    # ── Edges ─────────────────────────────────────────────────────────────
    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "interviewer_turn":  "interviewer_turn",
            "review_turn":       "review_turn",
            "sprint_agent_turn": "sprint_agent_turn",
            "analyst_turn":      "analyst_turn",           # ← NEW
            "__end__":           END,
        },
    )
    g.add_conditional_edges(
        "interviewer_turn",
        after_interviewer,
        {
            "supervisor":       "supervisor",
            "enduser_turn":     "enduser_turn",
            "interviewer_turn": "interviewer_turn",
        },
    )
    g.add_edge("enduser_turn",      "interviewer_turn")
    g.add_edge("review_turn",       "supervisor")
    g.add_edge("sprint_agent_turn", "supervisor")
    g.add_edge("analyst_turn",      "supervisor")          # ← NEW

    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)