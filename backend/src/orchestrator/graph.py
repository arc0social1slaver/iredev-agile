"""
graph.py – LangGraph orchestration.

Graph topology
──────────────
  supervisor
    ├─► interviewer_turn ◄──► enduser_turn           (Sprint Zero steps 1, 3, 5, 7)
    │       └─► supervisor  (vision/agenda produced OR interview_complete OR safety cap)
    ├─► review_product_vision_turn → supervisor      (Sprint Zero step 2 — HITL)
    ├─► review_elicitation_agenda_turn → supervisor  (Sprint Zero step 4 — HITL)
    ├─► review_interview_record_turn → supervisor    (Sprint Zero step 6 — HITL, approve-only)
    ├─► review_requirement_list_turn → supervisor    (Sprint Zero step 8 — HITL)
    ├─► sprint_agent_turn → supervisor               (Sprint Zero step 9)
    ├─► review_product_backlog_turn → supervisor     (Sprint Zero step 10 — HITL)
    ├─► analyst_turn → supervisor                    (Backlog Refinement step 1)
    ├─► analyst_review_turn → supervisor             (Backlog Refinement step 2 — HITL)
    └─► END

HITL review order:
  1. review_product_vision_turn      — human reviews/edits the ProductVision
  2. review_elicitation_agenda_turn  — human reviews/edits the ElicitationAgenda
  3. review_interview_record_turn    — human reads raw Q&A (approve-only, no reject)
  4. review_requirement_list_turn    — human reviews the synthesised Requirement List
     • Reject here re-runs synthesis only; interview_record is NOT touched.
  On vision rejection: only product_vision is removed; agenda is NOT reset.
  On agenda rejection: elicitation_agenda_artifact removed; agent rebuilds
  using reviewed_product_vision + elicitation_agenda_feedback.

Stopping design (Interviewer-only)
────────────────────────────────────
INTERVIEWER IS THE SOLE AUTHORITY on stopping.  EndUserAgent has no mechanism
to set interview_complete.  The LangGraph edge always routes back to
interviewer_turn after enduser_turn completes.

Review node design (HITL pattern)
──────────────────────────────────
All review nodes follow the same pattern:
  1. Build interrupt payload (artifact_data + review_payload + ui_summary).
  2. Call interrupt() — graph pauses; ws_handler emits an artifact card.
  3. Resume with {"approved": True|False, "feedback": "..."}.
  4. On approval  → write sentinel artifact, advance flow.
  5. On rejection → remove source artifact, inject feedback, restart step.
  Exception: review_interview_record_turn is approve-only (no rejection path).

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

    # Sent inside review_elicitation_agenda_turn interrupt — alongside the artifact.
    "elicitation_agenda": (
        "## 📝 Elicitation Agenda Ready for Review\\n\\n"
        "The AI Interviewer has built an **Elicitation Agenda** from the approved "
        "Product Vision — the ordered list of topics and questions that will drive "
        "the requirements interview.\\n\\n"
        "**What's inside:**\\n"
        "- Ordered elicitation items derived from epics, assumptions, and constraints\\n"
        "- Priority and source reference for each item\\n"
        "- Elicitation goal per item (what information is being sought)\\n\\n"
        "**Your action:** Review the agenda below. "
        "If the coverage and order look correct, click **Accept** to start the interview. "
        "If items are missing, wrongly prioritised, or out of scope, click **Request Changes** "
        "and describe what needs adjusting — the agenda will be rebuilt with your feedback."
    ),

    # Sent inside review_product_vision_turn interrupt — alongside the artifact.
    "product_vision": (
        "## 🔭 Product Vision Ready for Review\n\n"
        "The AI Interviewer has analysed your project description and produced a "
        "**Product Vision** — the north-star artifact that guides all downstream "
        "requirement extraction and backlog creation.\n\n"
        "**What's inside:**\n"
        "- Target stakeholder groups with roles and key concerns\n"
        "- Core problem statement (specific, measurable)\n"
        "- Value proposition (outcome-focused, not a feature list)\n"
        "- Major Epics that bound the system scope\n"
        "- Hard constraints and key assumptions\n"
        "- Explicitly out-of-scope items\n\n"
        "**Your action:** Review the vision below. "
        "If it accurately represents your project, click **Accept** to proceed to the "
        "interview record review. "
        "If the problem statement, stakeholders, or scope are off, click **Request Changes** "
        "and describe what needs correcting — the vision will be regenerated with your feedback."
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
        "If everything looks correct, click **Accept** to proceed to the Requirement List. "
        "If you spot issues or missing requirements, click **Request Changes** and "
        "describe what needs to be fixed — the interviewer will re-run with your feedback."
    ),

    # Sent inside review_requirement_list_turn interrupt — alongside the artifact.
    "requirement_list": (
        "## 📄 Requirement List Ready for Review\n\n"
        "The AI has synthesised all elicitation answers into a structured "
        "**Requirement List** — the authoritative specification used to build the "
        "Product Backlog.\n\n"
        "**What's inside:**\n"
        "- Functional Requirements (FR) — what the system must do\n"
        "- Non-Functional Requirements (NFR) — quality and performance constraints\n"
        "- Constraints (CON) — non-negotiable limits\n"
        "- Out-of-Scope items (OOS) — anti-requirements that prevent scope creep\n"
        "- Acceptance criteria (Given-When-Then) for each FR/NFR\n"
        "- Traceability links back to elicitation evidence\n\n"
        "**Your action:** Review the requirement list below. "
        "Click **Accept** to hand it to the Sprint Agent for backlog creation. "
        "Click **Request Changes** to describe gaps, misclassifications, or quality issues — "
        "the synthesis pipeline will re-run with your feedback."
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
    logger.debug(
        "interviewer_turn updates: %s | vision=%s | agenda=%s | question=%r",
        list(updates.keys()),
        "present" if updates.get("product_vision") or state.get("product_vision") else "MISSING",
        "present" if updates.get("elicitation_agenda") or state.get("elicitation_agenda") else "MISSING",
        updates.get("current_question", ""),
    )
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

def review_product_vision_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the product_vision artifact.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":    "product_vision",
        "artifact_data":  <full product_vision dict>,
        "review_payload": <structured review data>,
        "ui_summary":     ARTIFACT_SUMMARIES["product_vision"],
    }

    After resume:
      approved=True  → write reviewed_product_vision sentinel; flow →
                       review_interview_record_turn.
      approved=False → remove product_vision artifact, inject
                       product_vision_feedback; flow returns to
                       interviewer_turn so vision is re-extracted with
                       the reviewer's comments.
    """
    artifacts   = dict(state.get("artifacts") or {})
    vision      = artifacts.get("product_vision", {})

    interrupt_value = {
        "review_type":    "product_vision",
        "artifact_data":  vision,
        "review_payload": _build_product_vision_review_payload(vision),
        "ui_summary":     ARTIFACT_SUMMARIES["product_vision"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        artifacts["reviewed_product_vision"] = {
            **vision,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        logger.info("[ReviewProductVision] APPROVED.")
        return {
            "artifacts":              artifacts,
            "product_vision_feedback": None,
        }

    artifacts.pop("product_vision", None)
    # Do NOT reset elicitation_agenda here — agenda is built AFTER vision is approved
    # (step 3), so it cannot exist yet at this rejection point.
    logger.info("[ReviewProductVision] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":               artifacts,
        "interview_complete":      False,
        "product_vision_feedback": feedback or "The reviewer did not provide specific feedback.",
    }



def review_elicitation_agenda_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the elicitation_agenda_artifact.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":    "elicitation_agenda",
        "artifact_data":  <full elicitation_agenda_artifact dict>,
        "review_payload": <structured review data>,
        "ui_summary":     ARTIFACT_SUMMARIES["elicitation_agenda"],
    }

    After resume:
      approved=True  → write reviewed_elicitation_agenda sentinel;
                       flow → conduct_requirements_interview.
      approved=False → remove elicitation_agenda_artifact, inject
                       elicitation_agenda_feedback; flow returns to
                       interviewer_turn so agenda is rebuilt using
                       reviewed_product_vision + feedback.
    """
    artifacts = dict(state.get("artifacts") or {})
    agenda    = artifacts.get("elicitation_agenda_artifact", {})

    interrupt_value = {
        "review_type":    "elicitation_agenda",
        "artifact_data":  agenda,
        "review_payload": _build_elicitation_agenda_review_payload(agenda),
        "ui_summary":     ARTIFACT_SUMMARIES["elicitation_agenda"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        artifacts["reviewed_elicitation_agenda"] = {
            **agenda,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        logger.info("[ReviewElicitationAgenda] APPROVED.")
        return {
            "artifacts":                  artifacts,
            "elicitation_agenda_feedback": None,
        }

    artifacts.pop("elicitation_agenda_artifact", None)
    logger.info("[ReviewElicitationAgenda] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":                  artifacts,
        "elicitation_agenda_feedback": feedback or "The reviewer did not provide specific feedback.",
        # Reset agenda state keys so interviewer rebuilds from scratch with feedback
        "elicitation_agenda":         None,
    }


def review_requirement_list_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the requirement_list artifact.

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":    "requirement_list",
        "artifact_data":  <full requirement_list dict>,
        "review_payload": <structured review data>,
        "ui_summary":     ARTIFACT_SUMMARIES["requirement_list"],
    }

    After resume:
      approved=True  → write requirement_list_approved sentinel;
                       flow → sprint_agent_turn.
      approved=False → remove ONLY requirement_list artifact, inject
                       requirement_list_feedback; flow returns to
                       interviewer_turn so synthesis re-runs with feedback.
                       interview_record and reviewed_interview_record are
                       NOT removed — synthesis re-runs against the same record.
    """
    artifacts        = dict(state.get("artifacts") or {})
    req_list         = artifacts.get("requirement_list", {})
    requirements     = req_list.get("requirements", [])

    interrupt_value = {
        "review_type":    "requirement_list",
        "artifact_data":  req_list,
        "review_payload": _build_requirement_list_review_payload(req_list, requirements),
        "ui_summary":     ARTIFACT_SUMMARIES["requirement_list"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        artifacts["requirement_list_approved"] = {
            **req_list,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        logger.info(
            "[ReviewRequirementList] APPROVED — %d requirement(s).", len(requirements)
        )
        return {
            "artifacts":                artifacts,
            "requirement_list_feedback": None,
        }

    # Remove only the requirement_list — interview_record stays intact.
    artifacts.pop("requirement_list", None)
    logger.info("[ReviewRequirementList] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":                artifacts,
        # Re-trigger synthesis on next interviewer_turn call
        "_needs_srs_synthesis":     True,
        "interview_complete":       False,
        "requirement_list_feedback": feedback or "The reviewer did not provide specific feedback.",
    }


def review_interview_record_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """HITL gate — human reviews the interview_record (view-only / approve-only).

    Interrupt payload (consumed by ws_handler):
    {
        "review_type":    "interview_record",
        "artifact_data":  <full interview_record dict>,
        "review_payload": <structured review data>,
        "ui_summary":     ARTIFACT_SUMMARIES["interview_record"],
    }

    This gate is APPROVE-ONLY. There is no reject path.
    The interview_record cannot be sent back for re-interviewing here.
    If the reviewer has concerns about content quality, they should note them
    and provide feedback at the review_requirement_list gate instead, where
    synthesis can be re-run incorporating their comments.

    After resume:
      approved=True  → write reviewed_interview_record; flow → synthesise_requirement_list.
      approved=False → treated identically to approved=True (approve-only gate);
                       any feedback text is stored as review_notes on the artifact.
    """
    artifacts    = dict(state.get("artifacts") or {})
    record       = artifacts.get("interview_record", {})
    elicitation_items = record.get("requirements_identified", [])

    interrupt_value = {
        "review_type":    "interview_record",
        "artifact_data":  record,
        "review_payload": _build_interview_review_payload(record, elicitation_items),
        "ui_summary":     ARTIFACT_SUMMARIES["interview_record"],
    }
    reviewer_response: Dict[str, Any] = interrupt(interrupt_value)

    # Approve-only: ignore the approved flag, always proceed.
    feedback = (reviewer_response.get("feedback") or "").strip()

    reviewed_record = {
        **record,
        "status":       "approved",
        "reviewed_at":  datetime.now().isoformat(),
        "review_notes": feedback or None,
    }
    artifacts["reviewed_interview_record"] = reviewed_record
    logger.info(
        "[ReviewInterviewRecord] APPROVED (approve-only gate) — %d elicitation item(s).",
        len(elicitation_items),
    )
    return {
        "artifacts":       artifacts,
        "review_feedback": None,
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

def _build_product_vision_review_payload(vision: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing product_vision."""
    stakeholders = vision.get("target_audiences") or []
    assumptions  = vision.get("assumptions") or []

    return {
        "core_problem":      vision.get("core_problem", ""),
        "value_proposition": vision.get("value_proposition", ""),
        "core_workflows":    vision.get("core_workflows", []),
        "hard_constraints":  vision.get("hard_constraints", []),
        "out_of_scope":      vision.get("out_of_scope", []),
        "stakeholders": [
            {
                "role":            s.get("role"),
                "type":            s.get("type"),
                "key_concern":     s.get("key_concern"),
                "influence_level": s.get("influence_level"),
            }
            for s in stakeholders
        ],
        "assumptions": [
            {
                "statement":        a.get("statement"),
                "risk_if_wrong":    a.get("risk_if_wrong"),
                "needs_validation": a.get("needs_validation"),
            }
            for a in assumptions
        ],
    }


def _build_elicitation_agenda_review_payload(agenda: Dict[str, Any]) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing elicitation_agenda_artifact."""
    items = agenda.get("items") or []
    return {
        "session_id":   agenda.get("session_id", ""),
        "created_at":   agenda.get("created_at", ""),
        "total_items":  len(items),
        "items": [
            {
                "item_id":          item.get("item_id"),
                "source_field":     item.get("source_field"),
                "source_ref":       item.get("source_ref"),
                "elicitation_goal": item.get("elicitation_goal"),
                "priority":         item.get("priority"),
                "status":           item.get("status"),
            }
            for item in items
        ],
    }


def _build_requirement_list_review_payload(
    req_list: Dict[str, Any],
    requirements: list,
) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing requirement_list."""
    by_type: Dict[str, int] = {}
    req_summaries = []
    for r in requirements:
        rtype = r.get("req_type", "unknown")
        by_type[rtype] = by_type.get(rtype, 0) + 1
        req_summaries.append({
            "req_id":      r.get("req_id"),
            "req_type":    rtype,
            "epic":        r.get("epic"),
            "priority":    r.get("priority"),
            "status":      r.get("status"),
            "stakeholder": r.get("stakeholder"),
            "statement":   r.get("statement"),
            "rationale":   r.get("rationale", "(not provided)"),
            "acceptance_criteria": r.get("acceptance_criteria", []),
        })

    return {
        "session_id":        req_list.get("session_id", ""),
        "synthesised_at":    req_list.get("synthesised_at", ""),
        "total_requirements": len(requirements),
        "by_type":           by_type,
        "requirements":      req_summaries,
    }


def _build_interview_review_payload(
    record: Dict[str, Any],
    elicitation_items: list,
) -> Dict[str, Any]:
    """Build the structured payload shown when reviewing interview_record.

    Schema matches _tool_conclude output:
      Each item has: id, source_field, source_ref, question, answer, priority
    No 'type', 'description', 'status', or 'history' fields exist at this stage —
    those belong to the requirement_list artifact produced in synthesis (Pass 4).
    """
    item_summaries = []
    for item in elicitation_items:
        # Truncate long answers for display but keep enough context
        answer = item.get("answer", "") or ""
        answer_preview = answer[:200] + "…" if len(answer) > 200 else answer

        item_summaries.append({
            "id":           item.get("id"),           # EL-NNN
            "source_field": item.get("source_field"),  # assumption | initial_requirement | …
            "source_ref":   item.get("source_ref"),    # verbatim vision/PD text
            "priority":     item.get("priority"),      # high | medium | low
            "question":     item.get("question", "(not recorded)"),
            "answer":       answer_preview,
        })

    return {
        "project_description": record.get("project_description", ""),
        # interview_record from _tool_conclude does not carry completeness_score,
        # gaps_identified, total_turns, or notes — omit to avoid misleading None values.
        "total_items":         len(elicitation_items),
        "elicitation_items":   item_summaries,
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
    """Route after interviewer_turn completes.

    Bootstrap Phase:
      Turn 1 (vision produced, no reviewed_product_vision yet):
        product_vision in state, reviewed_product_vision NOT in artifacts
        → supervisor (for HITL review_product_vision_turn).
      Turn 2 (agenda produced, no reviewed_elicitation_agenda yet):
        elicitation_agenda_artifact in artifacts, reviewed_elicitation_agenda NOT in artifacts
        → supervisor (for HITL review_elicitation_agenda_turn).

    Synthesis Phase (Step 7):
      reviewed_interview_record exists → synthesis in progress or done
      → supervisor if done, else retry interviewer_turn.

    Elicitation Phase (Steps 3+):
      Question ready → enduser_turn.
      Answer needs processing → interviewer_turn (to call record_answer then ask_question).
    """
    artifacts = state.get("artifacts") or {}

    # 1. SYNTHESIS PHASE
    if "reviewed_interview_record" in artifacts:
        if "requirement_list" in artifacts or state.get("interview_complete"):
            logger.info("after_interviewer: Synthesis complete → supervisor.")
            return "supervisor"
        else:
            logger.info("after_interviewer: Synthesis pending → interviewer_turn.")
            return "interviewer_turn"

    # 2. AGENDA BOOTSTRAP PHASE DETECTOR
    # elicitation_agenda_artifact was just produced (Turn 2) but not yet HITL-reviewed.
    if (
        "elicitation_agenda_artifact" in artifacts
        and "reviewed_elicitation_agenda" not in artifacts
    ):
        logger.info(
            "after_interviewer: Agenda artifact produced, needs HITL review → supervisor."
        )
        return "supervisor"

    # 3. VISION BOOTSTRAP PHASE DETECTOR
    # product_vision just produced (Turn 1) but not yet HITL-reviewed.
    if state.get("product_vision") and "reviewed_product_vision" not in artifacts:
        logger.info("after_interviewer: Vision produced, needs HITL review → supervisor.")
        return "supervisor"

    # 4. ELICITATION CONCLUDED DETECTOR
    # 'conclude' tool sets _needs_srs_synthesis=True when all agenda items are done.
    if state.get("_needs_srs_synthesis"):
        logger.info("after_interviewer: Elicitation concluded, record needs review → supervisor.")
        return "supervisor"

    # 5. SAFETY CAP
    turn_count = state.get("turn_count", 0)
    max_turns  = state.get("max_turns", _INTERVIEW_SAFETY_MAX_TURNS)
    if turn_count >= max_turns:
        logger.warning(
            "after_interviewer: safety cap reached (%d/%d) → supervisor.",
            turn_count, max_turns,
        )
        return "supervisor"

    # 6. ELICITATION LOOP — NEXT QUESTION NEEDED
    if state.get("_agenda_needs_question") or state.get("_agenda_needs_followup"):
        logger.debug("after_interviewer: answer recorded, need next question → interviewer_turn.")
        return "interviewer_turn"

    # 7. ELICITATION LOOP — QUESTION READY
    if state.get("current_question"):
        logger.debug(
            "after_interviewer: question ready → enduser_turn (%d/%d turns).",
            turn_count, max_turns,
        )
        return "enduser_turn"

    # 8. FALLBACK
    logger.warning("after_interviewer: no routing condition met — retrying interviewer_turn.")
    return "interviewer_turn"


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

    g.add_node("supervisor",                             supervisor_node_fn)
    g.add_node("interviewer_turn",                       interviewer_turn_fn)
    g.add_node("enduser_turn",                           enduser_turn_fn)
    g.add_node("review_product_vision_turn",             review_product_vision_turn_fn)
    g.add_node("review_elicitation_agenda_turn",         review_elicitation_agenda_turn_fn)
    g.add_node("review_interview_record_turn",           review_interview_record_turn_fn)
    g.add_node("review_requirement_list_turn",           review_requirement_list_turn_fn)
    g.add_node("sprint_agent_turn",                      sprint_agent_turn_fn)
    g.add_node("review_product_backlog_turn",            review_product_backlog_turn_fn)
    g.add_node("analyst_turn",                           analyst_turn_fn)
    g.add_node("review_validated_product_backlog_turn",  review_validated_product_backlog_turn_fn)

    g.set_entry_point("supervisor")

    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "interviewer_turn":                      "interviewer_turn",
            "review_product_vision_turn":            "review_product_vision_turn",
            "review_elicitation_agenda_turn":        "review_elicitation_agenda_turn",
            "review_interview_record_turn":          "review_interview_record_turn",
            "review_requirement_list_turn":          "review_requirement_list_turn",
            "sprint_agent_turn":                     "sprint_agent_turn",
            "review_product_backlog_turn":           "review_product_backlog_turn",
            "analyst_turn":                          "analyst_turn",
            "review_validated_product_backlog_turn": "review_validated_product_backlog_turn",
            "__end__":                               END,
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

    g.add_edge("enduser_turn",                           "interviewer_turn")
    g.add_edge("review_product_vision_turn",             "supervisor")
    g.add_edge("review_elicitation_agenda_turn",         "supervisor")
    g.add_edge("review_interview_record_turn",           "supervisor")
    g.add_edge("review_requirement_list_turn",           "supervisor")
    g.add_edge("sprint_agent_turn",                      "supervisor")
    g.add_edge("review_product_backlog_turn",            "supervisor")
    g.add_edge("analyst_turn",                           "supervisor")
    g.add_edge("review_validated_product_backlog_turn",  "supervisor")

    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)