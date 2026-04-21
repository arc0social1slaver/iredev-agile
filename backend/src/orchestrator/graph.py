"""
graph.py – LangGraph orchestration.

Graph topology
──────────────
  supervisor
    ├─► interviewer_turn ◄──► enduser_turn         (Sprint Zero step 1)
    │       └─► supervisor  (interview_complete=True OR safety max_turns)
    ├─► review_interview_record_turn → supervisor  (Sprint Zero step 2 — HITL)
    ├─► sprint_agent_turn → supervisor             (Sprint Zero step 3)
    ├─► review_product_backlog_turn → supervisor   (Sprint Zero step 4 — HITL)
    ├─► analyst_turn → supervisor                  (Backlog Refinement step 1)
    ├─► analyst_review_turn → supervisor           (Backlog Refinement step 2 — HITL)
    └─► END

Stopping design (Interviewer-only)
────────────────────────────────────
INTERVIEWER IS THE SOLE AUTHORITY on stopping.  EndUserAgent has no mechanism
to set interview_complete.  The LangGraph edge always routes back to
interviewer_turn after enduser_turn completes.

Review node design (HITL pattern)
──────────────────────────────────
All four review nodes follow the same pattern:
  1. Build interrupt payload (artifact_data + review_payload + ui_summary).
  2. Call interrupt() — graph pauses; ws_handler emits an artifact card.
  3. Resume with {"approved": True|False, "feedback": "..."}.
  4. On approval  → write sentinel artifact, advance flow.
  5. On rejection → remove source artifact, inject feedback, restart step.

UI Summaries (ARTIFACT_SUMMARIES)
──────────────────────────────────
Pre-written markdown summaries keyed by review_type.  ws_handler picks up
the right summary from the interrupt payload's "ui_summary" field and sends
it to the frontend alongside the artifact card.  Each summary explains:
  • What the artifact is
  • What the user needs to do (Accept / Request Changes)
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


# ─────────────────────────────────────────────────────────────────────────────
# UI Summaries
# ─────────────────────────────────────────────────────────────────────────────

ARTIFACT_SUMMARIES: Dict[str, str] = {

    # Sent by interviewer_turn_fn on the very first turn — no artifact yet.
    "workflow_started": (
        "## 🚀 Requirements Interview Started\n\n"
        "The AI Interviewer has begun a structured requirements discovery session "
        "with the virtual stakeholder.\n\n"
        "**What's happening:** The interviewer will ask a series of targeted questions "
        "to surface functional requirements, non-functional requirements, and constraints "
        "for your project.\n\n"
        "You can follow the conversation in real time below. "
        "When the interview is complete, you will be asked to review and approve the "
        "extracted requirements before the process continues."
    ),

    # Sent inside review_interview_record_turn interrupt — alongside the artifact.
    "interview_record": (
        "## 📋 Requirements Interview Complete\n\n"
        "The AI Interviewer has finished the discovery session and compiled all extracted "
        "requirements into an **Interview Record**.\n\n"
        "**What's inside:**\n"
        "- All functional, non-functional, and constraint requirements\n"
        "- Rationale for each requirement (linked to stakeholder statements)\n"
        "- Change history and conflict log\n"
        "- Completeness score and coverage gaps\n\n"
        "**Your action:** Review the requirements below. "
        "If everything looks correct, click **Accept** to proceed to backlog creation. "
        "If you spot issues or missing requirements, click **Request Changes** and "
        "describe what needs to be fixed — the interviewer will re-run with your feedback."
    ),

    # Sent inside review_product_backlog_turn interrupt — alongside the artifact.
    "product_backlog": (
        "## 📦 Initial Product Backlog Ready\n\n"
        "The Sprint Agent has converted all approved requirements into **User Stories** "
        "and assembled the initial Product Backlog.\n\n"
        "**What's inside:**\n"
        "- Each item written as: *As a \\<role\\>, I can \\<capability\\>, so that \\<benefit\\>*\n"
        "- Fibonacci story point estimates (Complexity + Effort + Uncertainty)\n"
        "- WSJF priority scores and ranked order\n"
        "- INVEST quality flags per story\n\n"
        "**Your action:** Review the backlog below. "
        "Click **Accept** to hand it to the Analyst for INVEST validation and "
        "Acceptance Criteria synthesis. "
        "Click **Request Changes** to send it back for revision — describe what "
        "story points, priorities, or story descriptions need adjustment."
    ),

    # Sent inside analyst_review_turn interrupt — alongside the artifact.
    "validated_product_backlog": (
        "## ✅ Validated Product Backlog Ready\n\n"
        "The Analyst Agent has groomed the entire backlog in one pass:\n\n"
        "**What was done:**\n"
        "- **INVEST validation** — each user story checked against all 6 criteria; "
        "size warnings and split suggestions included where needed\n"
        "- **Acceptance Criteria** — 2–5 Given-When-Then criteria written per story, "
        "derived from the story's capability clause and Sprint 0 reasoning traces\n"
        "- **Status** — every story with AC is now marked `ready`\n\n"
        "**Your action:** Review the validated backlog below. "
        "Click **Accept** to mark all `ready` stories available for Sprint planning. "
        "Click **Request Changes** to send the entire backlog back for re-grooming — "
        "describe any AC quality issues, INVEST failures, or missing coverage."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Lazy agent singletons
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Node functions
# ─────────────────────────────────────────────────────────────────────────────

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
                "You MUST call the 'respond' tool right now. "
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
    """Run SprintAgent — builds the product_backlog from reviewed_interview_record."""
    updates = _get_sprint_agent().process(state)
    logger.debug("sprint_agent_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


def analyst_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Run AnalystAgent — INVEST validation + AC synthesis + publish."""
    updates = _get_analyst().process(state)
    logger.debug("analyst_turn updates: %s", list(updates.keys()))
    _sync_artifacts_to_store(state, updates)
    return updates


# ─────────────────────────────────────────────────────────────────────────────
# HITL review nodes
# ─────────────────────────────────────────────────────────────────────────────

def review_interview_record_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the interview_record.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":   "interview_record",
        "artifact_data": <full interview_record dict>,
        "review_payload": <structured review data>,
        "ui_summary":    ARTIFACT_SUMMARIES["interview_record"],
    }

    After resume:
      approved=True  → write reviewed_interview_record; flow → sprint_agent_turn.
      approved=False → remove interview_record, inject review_feedback;
                       flow returns to conduct_requirements_interview.
    """
    artifacts    = dict(state.get("artifacts") or {})
    record       = artifacts.get("interview_record", {})
    requirements = record.get("requirements_identified", [])

    interrupt_value = {
        "review_type":   "interview_record",
        "artifact_data": record,
        "review_payload": _build_interview_review_payload(record, requirements),
        "ui_summary":    ARTIFACT_SUMMARIES["interview_record"],
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
        logger.info("[ReviewInterviewRecord] APPROVED — %d requirements.", len(requirements))
        return {
            "artifacts":       artifacts,
            "review_feedback": None,
        }

    artifacts.pop("interview_record", None)
    logger.info("[ReviewInterviewRecord] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":          artifacts,
        "interview_complete": False,
        "review_feedback":    feedback or "The reviewer did not provide specific feedback.",
    }


def review_product_backlog_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — Product Owner reviews the raw product_backlog.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":   "product_backlog",
        "artifact_data": <full product_backlog dict>,
        "review_payload": <structured review data>,
        "ui_summary":    ARTIFACT_SUMMARIES["product_backlog"],
    }

    After resume:
      approved=True  → write product_backlog_approved sentinel;
                       flow → analyst_turn (Backlog Refinement).
      approved=False → remove product_backlog, inject product_backlog_feedback;
                       flow returns to build_product_backlog (SprintAgent rebuilds).
    """
    artifacts = dict(state.get("artifacts") or {})
    backlog   = artifacts.get("product_backlog", {})

    interrupt_value = {
        "review_type":   "product_backlog",
        "artifact_data": backlog,
        "review_payload": _build_product_backlog_review_payload(backlog),
        "ui_summary":    ARTIFACT_SUMMARIES["product_backlog"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    items = backlog.get("items") or []

    if approved:
        artifacts["product_backlog_approved"] = backlog
        logger.info(
            "[ReviewProductBacklog] APPROVED — %d user stories.", len(items)
        )
        return {
            "artifacts":               artifacts,
            "product_backlog_feedback": None,
        }

    artifacts.pop("product_backlog", None)
    logger.info("[ReviewProductBacklog] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":               artifacts,
        "product_backlog_feedback": feedback or "The reviewer did not provide specific feedback.",
    }


def review_validated_product_backlog_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — Product Owner reviews the validated_product_backlog.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":   "validated_product_backlog",
        "artifact_data": <full validated_product_backlog dict>,
        "review_payload": <structured review data>,
        "ui_summary":    ARTIFACT_SUMMARIES["validated_product_backlog"],
    }

    After resume:
      approved=True  → write validated_product_backlog_approved sentinel; Sprint N can begin.
      approved=False → remove validated_product_backlog, inject validated_product_backlog_feedback;
                       flow returns to groom_backlog (full re-groom).
    """
    artifacts = dict(state.get("artifacts") or {})
    validated = artifacts.get("validated_product_backlog") or {}

    interrupt_value = {
        "review_type":   "validated_product_backlog",
        "artifact_data": validated,
        "review_payload": _build_validated_product_backlog_review_payload(validated),
        "ui_summary":    ARTIFACT_SUMMARIES["validated_product_backlog"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        artifacts["validated_product_backlog_approved"] = validated
        logger.info(
            "[AnalystReview] APPROVED — %d ready PBIs, %d total AC.",
            len([
                item["id"]
                for item in (validated.get("items") or [])
                if item.get("status") == "ready"
            ]),
            validated.get("refinement_stats", {}).get("total_ac", 0),
        )
        return {
            "artifacts":       artifacts,
            "analyst_feedback": None,
        }

    artifacts.pop("validated_product_backlog", None)
    logger.info("[AnalystReview] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":       artifacts,
        "analyst_feedback": feedback or "The reviewer did not provide specific feedback.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Review payload builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_interview_review_payload(
    record: Dict[str, Any],
    requirements: list,
) -> Dict[str, Any]:
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
        "project_description": record.get("project_description", ""),
        "completeness_score":  record.get("completeness_score"),
        "gaps":                record.get("gaps_identified", []),
        "notes":               record.get("notes", ""),
        "total_turns":         record.get("total_turns"),
        "requirements":        req_summaries,
    }


def _build_product_backlog_review_payload(backlog: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown to the PO when reviewing the raw backlog."""
    items = backlog.get("items") or []

    story_summaries = []
    for item in items:
        invest = item.get("invest") or {}
        failed = [k for k, v in invest.items() if not v]
        story_summaries.append({
            "id":            item.get("id"),
            "title":         item.get("title"),
            "type":          item.get("type"),
            "description":   item.get("description"),   # user story text
            "story_points":  item.get("story_points"),
            "priority_rank": item.get("priority_rank"),
            "wsjf_score":    item.get("wsjf_score"),
            "invest_failures": failed,
            "status":        item.get("status"),
        })

    return {
        "total_stories":   len(items),
        "methodology":     backlog.get("methodology", {}),
        "notes":           backlog.get("notes", ""),
        "stories":         story_summaries,
    }


def _build_validated_product_backlog_review_payload(validated: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown to the PO when reviewing the validated backlog."""
    items = validated.get("items") or []

    pbi_summaries = []
    for item in items:
        iv     = item.get("invest_validation") or {}
        ac     = item.get("acceptance_criteria") or []
        issues = iv.get("issues") or []

        pbi_summaries.append({
            "id":            item.get("id"),
            "title":         item.get("title"),
            "type":          item.get("type"),
            "description":   item.get("description"),
            "story_points":  item.get("story_points"),
            "priority_rank": item.get("priority_rank"),
            "status":        item.get("status"),
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


# ─────────────────────────────────────────────────────────────────────────────
# Artifact persistence
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Conditional edge: after interviewer_turn
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Build graph
# ─────────────────────────────────────────────────────────────────────────────

def build_graph(store=None, checkpointer=None):
    """Compile the LangGraph workflow."""
    if store is None:
        store = _default_store()

    if checkpointer is None:
        logger.warning(
            "build_graph: no checkpointer. HITL review nodes use interrupt() "
            "which requires persistent storage in production."
        )
        checkpointer = InMemorySaver()

    g = StateGraph(WorkflowState)

    g.add_node("supervisor",                    supervisor_node_fn)
    g.add_node("interviewer_turn",              interviewer_turn_fn)
    g.add_node("enduser_turn",                  enduser_turn_fn)
    g.add_node("review_interview_record_turn",  review_interview_record_turn_fn)
    g.add_node("sprint_agent_turn",             sprint_agent_turn_fn)
    g.add_node("review_product_backlog_turn",   review_product_backlog_turn_fn)
    g.add_node("analyst_turn",                  analyst_turn_fn)
    g.add_node("review_validated_product_backlog_turn",   review_validated_product_backlog_turn_fn)

    g.set_entry_point("supervisor")

    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "interviewer_turn":             "interviewer_turn",
            "review_interview_record_turn": "review_interview_record_turn",
            "sprint_agent_turn":            "sprint_agent_turn",
            "review_product_backlog_turn":  "review_product_backlog_turn",
            "analyst_turn":                 "analyst_turn",
            "review_validated_product_backlog_turn":  "review_validated_product_backlog_turn",
            "__end__":                      END,
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

    g.add_edge("enduser_turn",                  "interviewer_turn")
    g.add_edge("review_interview_record_turn",  "supervisor")
    g.add_edge("sprint_agent_turn",             "supervisor")
    g.add_edge("review_product_backlog_turn",   "supervisor")
    g.add_edge("analyst_turn",                  "supervisor")
    g.add_edge("review_validated_product_backlog_turn",           "supervisor")

    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)