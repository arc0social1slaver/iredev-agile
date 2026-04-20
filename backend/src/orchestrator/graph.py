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
    ├─► sprint_agent_turn → supervisor        (Sprint Zero step 3)
    └─► END

Stopping design (two-tier, Interviewer-only)
─────────────────────────────────────────────
INTERVIEWER IS THE SOLE AUTHORITY on stopping.  EndUserAgent has no mechanism
to set interview_complete or to call FINISH.  Its 'respond' tool exits only
the enduser's own ReAct loop; the LangGraph edge always routes back to
interviewer_turn after enduser_turn completes.

TIER 2 — Marginal IG per domain (primary semantic gate):
  InterviewerAgent._tool_update_requirements tracks consecutive_dry_calls per
  zone in goal_tracker.  ig_score degrades to 0.0 after 3 dry calls.
  check_coverage surfaces these scores so the [STRATEGY] block can reason
  whether further probing would yield new information.

TIER 3 — Metacognitive Coherence Check (secondary gate):
  Enforced entirely in the Interviewer's [STRATEGY] block:
  "Could an engineer begin designing from this requirements list?"
  If YES and Tier-2 confirms saturation → write_interview_record is called,
  setting interview_complete=True.  after_interviewer then routes to supervisor.

SAFETY NET (graph-layer):
  after_interviewer checks turn_count >= max_turns.
  Default = _INTERVIEW_SAFETY_MAX_TURNS = 20.
  This guard fires only when the agent fails to self-terminate.

Review node design
──────────────────
review_turn uses LangGraph's interrupt() to pause execution.
The reviewer supplies a dict:
  {"approved": True}                          → approval
  {"approved": False, "feedback": "<text>"}   → rejection

On approval:
  • reviewed_interview_record artifact written (interview_record + metadata).
  • Flow advances to sprint_agent_turn.

On rejection:
  • interview_record removed from artifacts.
  • review_feedback injected into state.
  • interview_complete reset to False.
  • Flow returns to conduct_requirements_interview.
  • On the next Interviewer turn, process() detects review_feedback and
    instructs the agent to apply all feedback via update_requirements.
  • Every HITL-driven change is recorded with action "hitl_modified" /
    "hitl_added" / "hitl_deleted" in requirement history — permanently
    traceable in the next review cycle.
"""

from __future__ import annotations

import json
import shutil
import logging
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt

from .state import WorkflowState
from .supervisor import supervisor_node, supervisor_router

logger = logging.getLogger(__name__)

_INTERVIEW_SAFETY_MAX_TURNS = 3


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

    EndUserAgent.respond sets should_return=True inside ITS OWN ReAct loop
    only.  It does NOT set interview_complete.  The edge from enduser_turn
    always returns to interviewer_turn — the enduser can never terminate the
    interview.
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
    updates = _get_sprint_agent().process(state)
    logger.debug("sprint_agent_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


# ── Review node ───────────────────────────────────────────────────────────────

def review_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Human-in-the-loop review gate.

    The interrupt() value contains the full interview_record so that
    ws_handler can extract it from __interrupt__ and emit a WebSocket
    artifact event to the frontend without reading graph state directly.

    Structure of interrupt value:
    {
        "review_type":   "interview_record",
        "artifact_key":  "interview_record",
        "artifact_data": <full interview_record dict>,
        "review_payload": <human-readable summary>,
    }

    After resume:
      approved=True  → write reviewed_interview_record, flow → sprint_agent
      approved=False → remove interview_record, inject feedback, flow → interviewer
    """
    artifacts = dict(state.get("artifacts") or {})
    record = artifacts.get("interview_record", {})
    requirements = record.get("requirements_identified", [])

    review_payload = _format_review_payload(record, requirements)

    # ── Pause — ws_handler will emit artifact event on __interrupt__ ──────
    # We embed the full record so ws_handler has everything it needs.
    interrupt_value = {
        "review_type":   "interview_record",
        "artifact_key":  "interview_record",
        "artifact_data": record,
        "review_payload": review_payload,
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

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

    # Rejection: remove record so supervisor re-routes to conduct_requirements_interview
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
    req_summaries = []
    for r in requirements:
        history_lines = []
        for h in r.get("history") or []:
            action = h.get("action", "?")
            turn = h.get("turn", "?")
            reason = h.get("reason", "")
            line = f"    [{action}] turn {turn}: {reason}"
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
            "  • description — the testable requirement\n"
            "  • rationale   — why identified (includes interviewer strategy reasoning)\n"
            "  • history     — how it evolved; HITL edits are tagged [hitl_modified] etc.\n\n"
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

def analyst_turn_fn(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run AnalystAgent.process().
 
    The agent performs INVEST quality check + AC synthesis + publish in a
    single ReAct turn, emitting validated_product_backlog into artifacts.
    """
    updates = _get_analyst().process(state)
    logger.debug("analyst_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates

def analyst_review_turn_fn(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    HITL gate: Product Owner reviews the validated_product_backlog.
 
    Approval  → writes analyst_review_done sentinel.
                Supervisor will route to sprint_agent_turn (Sprint N).
    Rejection → removes validated_product_backlog from artifacts;
                injects analyst_feedback into state;
                supervisor re-routes to analyst_turn (full re-groom).
    """
    artifacts = dict(state.get("artifacts") or {})
    validated = artifacts.get("validated_product_backlog") or {}
 
    payload = _build_review_payload(validated)
    interrupt_value = {
        "review_type": "validated_product_backlog",
        "artifact_key": "validated_product_backlog",
        "artifact_data": validated,
        "review_payload": payload,
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)
 
    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()
 
    if approved:
        sentinel = {
            "id":          str(uuid.uuid4()),
            "session_id":  state.get("session_id", ""),
            "approved_at": datetime.now().isoformat(),
            "review_notes": feedback or None,
            "ready_pbis":  [
                item["id"]
                for item in (validated.get("items") or [])
                if item.get("status") == "ready"
            ],
        }
        artifacts["analyst_review_done"] = sentinel
 
        logger.info(
            "[AnalystReview] APPROVED — %d ready PBIs, %d total AC.",
            len(sentinel["ready_pbis"]),
            validated.get("refinement_stats", {}).get("total_ac", 0),
        )
        return {
            "artifacts":       artifacts,
            "analyst_feedback": None,
        }
 
    # Rejection: remove validated backlog so supervisor re-routes to analyst_turn
    artifacts.pop("validated_product_backlog", None)
    logger.info("[AnalystReview] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":       artifacts,
        "analyst_feedback": feedback or "The reviewer did not provide specific feedback.",
    }
 
 
# ── Review payload ────────────────────────────────────────────────────────────
 
def _build_review_payload(validated: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the structured payload presented to the Product Owner.
 
    For each PBI the reviewer sees:
      • description + type + story points + priority rank
      • invest_validation — per-criterion results and any flagged issues
      • acceptance_criteria — all Given-When-Then criteria
    """
    items = validated.get("items") or []
 
    pbi_summaries = []
    for item in items:
        iv      = item.get("invest_validation") or {}
        ac      = item.get("acceptance_criteria") or []
        issues  = iv.get("issues") or []
 
        pbi_summaries.append({
            "id":           item.get("id"),
            "title":        item.get("title"),
            "type":         item.get("type"),
            "description":  item.get("description"),
            "story_points": item.get("story_points"),
            "priority_rank": item.get("priority_rank"),
            "status":       item.get("status"),
            "invest_validation": {
                "failed_criteria": iv.get("failed_criteria", []),
                "issues": [
                    {
                        "criterion":  iss.get("criterion"),
                        "severity":   iss.get("severity"),
                        "message":    iss.get("message"),
                        "suggestion": iss.get("suggestion"),
                    }
                    for iss in issues
                ],
            },
            "acceptance_criteria": [
                {
                    "id":    c.get("id"),
                    "type":  c.get("type"),
                    "given": c.get("given"),
                    "when":  c.get("when"),
                    "then":  c.get("then"),
                }
                for c in ac
            ],
        })
 
    return {
        "refinement_summary": validated.get("refinement_summary", ""),
        "refinement_stats":   validated.get("refinement_stats", {}),
        "pbis":               pbi_summaries,
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
    if state.get("interview_complete", False):
        logger.info("Tier-2/3 stop: interview_complete=True → supervisor.")
        return "supervisor"

    turn_count = state.get("turn_count", 0)
    max_turns  = state.get("max_turns", _INTERVIEW_SAFETY_MAX_TURNS)
    if turn_count >= max_turns:
        logger.warning(
            "Safety net: turn_count=%d >= max_turns=%d → supervisor.",
            turn_count, max_turns,
        )
        return "supervisor"

    conversation = state.get("conversation") or []
    last_role = conversation[-1].get("role") if conversation else None

    if last_role != "interviewer":
        logger.warning(
            "after_interviewer: no new message (last_role=%r) — retrying.",
            last_role,
        )
        return "interviewer_turn"

    logger.debug("Interview continues: %d/%d turns.", turn_count, max_turns)
    return "enduser_turn"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_graph(store=None, checkpointer=None):
    """Compile the LangGraph workflow."""
    if store is None:
        store = _default_store()

    if checkpointer is None:
        logger.warning(
            "build_graph: no checkpointer. review_turn uses interrupt() which "
            "requires persistent storage in production."
        )
        checkpointer = InMemorySaver()

    g = StateGraph(WorkflowState)

    g.add_node("supervisor",        supervisor_node_fn)
    g.add_node("interviewer_turn",  interviewer_turn_fn)
    g.add_node("enduser_turn",      enduser_turn_fn)
    g.add_node("review_turn",       review_turn_fn)
    g.add_node("sprint_agent_turn", sprint_agent_turn_fn)
    g.add_node("analyst_turn",        analyst_turn_fn)
    g.add_node("analyst_review_turn", analyst_review_turn_fn)

    g.set_entry_point("supervisor")

    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "interviewer_turn":  "interviewer_turn",
            "review_turn":       "review_turn",
            "sprint_agent_turn": "sprint_agent_turn",
            "analyst_turn":        "analyst_turn",
            "analyst_review_turn": "analyst_review_turn",
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
    g.add_edge("analyst_turn",        "supervisor")
    g.add_edge("analyst_review_turn", "supervisor")
 

    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)