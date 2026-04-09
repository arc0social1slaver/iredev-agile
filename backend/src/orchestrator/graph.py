"""
graph.py – LangGraph orchestration.

Graph topology
──────────────
  supervisor
    ├─► interviewer_turn ◄──► enduser_turn         (step 1 — interview)
    │       └─► supervisor
    ├─► review_turn                                 (step 2 — review interview)
    │       └─► supervisor
    ├─► sprint_agent_turn                           (step 3 — build backlog)
    │       └─► supervisor
    ├─► review_product_backlog_turn                 (step 4 — review backlog)  [NEW]
    │       └─► supervisor
    ├─► sprint_feedback_turn                        (step 5a — collect sprint inputs) [NEW]
    │       └─► sprint_agent_turn (Pipeline B)      (step 5b — plan sprint)
    │               └─► supervisor
    ├─► review_sprint_backlog_turn                  (step 6 — review sprint backlog) [NEW]
    │       └─► supervisor
    └─► END

Interrupt nodes
───────────────
All four review / feedback nodes use LangGraph's interrupt() to pause
execution for human input.  A SqliteSaver (or similar) checkpointer is
REQUIRED in production for these to work correctly.

review_turn                  — approves / rejects the interview record
review_product_backlog_turn  — approves / rejects the product backlog
sprint_feedback_turn         — collects sprint goal + capacity from the planner
review_sprint_backlog_turn   — approves / rejects the sprint backlog

Sentinel pattern for Pipeline B
─────────────────────────────────
sprint_feedback_turn writes artifacts["_sprint_feedback_ready"] = True.
SprintAgent.process() detects this sentinel to run Pipeline B instead of A.
After Pipeline B writes sprint_backlog_<N>, the sentinel is removed by
_tool_write_sprint_backlog so the supervisor re-evaluates correctly.

Multi-sprint loop
──────────────────
After review_sprint_backlog_turn approves a sprint backlog with plan_another=True:
  1. reviewed_sprint_backlog_N is written to artifacts.
  2. current_sprint_number is incremented in state.
  3. Supervisor calls get_next_action() — sprint_backlog_(N+1) doesn't exist yet,
     so it routes back to sprint_feedback_turn for the next sprint.

After rejection:
  1. sprint_backlog_N is removed from artifacts.
  2. _sprint_feedback_ready sentinel is re-added (so supervisor routes to
     sprint_agent_turn, not sprint_feedback_turn — the planner already gave
     their inputs; we just need a replan).
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
from langgraph.types import interrupt

from .state import WorkflowState
from .supervisor import supervisor_node, supervisor_router

logger = logging.getLogger(__name__)

_INTERVIEW_SAFETY_MAX_TURNS = 20
_DEFAULT_SPRINT_CAPACITY    = 20


# ── Lazy singletons ───────────────────────────────────────────────────────────

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


# ── Core agent nodes ──────────────────────────────────────────────────────────

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


# ── Review node: interview record (step 2) ────────────────────────────────────

def review_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """Human review of the interview record via interrupt()."""
    artifacts = dict(state.get("artifacts") or {})
    record    = artifacts.get("interview_record", {})

    requirements    = record.get("requirements_identified", [])
    review_payload  = _format_interview_review_payload(record, requirements)

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
        logger.info("[Review/Interview] APPROVED — %d requirements.", len(requirements))
        return {
            "artifacts":       artifacts,
            "review_approved": True,
            "review_feedback": None,
        }

    artifacts.pop("interview_record", None)
    logger.info("[Review/Interview] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":         artifacts,
        "interview_complete": False,
        "review_approved":    False,
        "review_feedback":    feedback or "The reviewer did not provide specific feedback.",
    }


# ── Review node: product backlog (step 4 — NEW) ───────────────────────────────

def review_product_backlog_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """
    Human review of the product backlog via interrupt().

    Presents the full ranked backlog with WSJF scores, story points, INVEST
    criteria results, and the methodology used.

    Approval  → reviewed_product_backlog written; flow advances to step 5.
    Rejection → product_backlog removed; product_backlog_feedback set;
                SprintAgent will rebuild when supervisor routes back to step 3.
    """
    artifacts = dict(state.get("artifacts") or {})
    backlog   = artifacts.get("product_backlog", {})
    items     = backlog.get("items") or []

    review_payload = _format_backlog_review_payload(backlog, items)

    reviewer_response: Dict[str, Any] = interrupt(review_payload)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        reviewed_backlog = {
            **backlog,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        artifacts["reviewed_product_backlog"] = reviewed_backlog
        logger.info(
            "[Review/Backlog] APPROVED — %d items.", len(items)
        )
        return {
            "artifacts":                      artifacts,
            "product_backlog_review_approved": True,
            "product_backlog_feedback":        None,
        }

    # Rejection: remove product_backlog so the supervisor re-routes to
    # sprint_agent_turn (step 3) for a rebuild.
    artifacts.pop("product_backlog", None)
    logger.info("[Review/Backlog] REJECTED. Feedback: %s", feedback or "(none)")
    return {
        "artifacts":                      artifacts,
        "product_backlog_review_approved": False,
        "product_backlog_feedback":        feedback or "The reviewer did not provide specific feedback.",
        # Reset backlog_draft so SprintAgent starts fresh (avoids duplicate IDs)
        "backlog_draft": [],
    }


# ── Sprint feedback node (step 5a — NEW) ──────────────────────────────────────

def sprint_feedback_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """
    Collect sprint planning inputs from the human planner via interrupt().

    The planner supplies:
      sprint_goal        — one-sentence goal for the sprint
      capacity_points    — team velocity in story points
      completed_pbi_ids  — PBIs already done (for first sprint, usually [])
      plan_another       — whether to plan another sprint after this one
      notes              — optional context for the SprintAgent

    After this node, the graph routes directly to sprint_agent_turn where
    SprintAgent.process() detects the _sprint_feedback_ready sentinel and
    runs Pipeline B (analyse_dependencies + write_sprint_backlog).
    """
    artifacts             = dict(state.get("artifacts") or {})
    current_sprint_number = state.get("current_sprint_number", 1)
    backlog               = (
        artifacts.get("reviewed_product_backlog")
        or artifacts.get("product_backlog")
        or {}
    )
    items = backlog.get("items") or []

    # Build a readable backlog summary for the planner
    summary_lines = []
    for item in items:
        rank  = item.get("priority_rank", "?")
        sid   = item.get("id", "?")
        pts   = item.get("story_points", "?")
        wsjf  = item.get("wsjf_score")
        wsjf_str = f"WSJF={wsjf:.2f}" if wsjf else "WSJF=N/A"
        dep_on = item.get("depends_on") or []
        dep_str = f" deps={dep_on}" if dep_on else ""
        summary_lines.append(
            f"#{rank} [{sid}] pts={pts} {wsjf_str}{dep_str} "
            f"({item.get('type','?')}) — {item.get('title','')[:70]}"
        )

    # Collect previously planned sprint numbers to inform the planner
    completed_sprints = [
        k for k in artifacts
        if k.startswith("reviewed_sprint_backlog_")
    ]

    payload = {
        "prompt": (
            f"Sprint {current_sprint_number} Planning — please provide:\n"
            f"  sprint_goal       : <one-sentence goal for sprint {current_sprint_number}>\n"
            f"  capacity_points   : <team velocity in story points (e.g. 20)>\n"
            f"  completed_pbi_ids : <list of PBI IDs already completed, or []>\n"
            f"  plan_another      : <true if you want to plan another sprint after this>\n"
            f"  notes             : <optional context for the SprintAgent>\n\n"
            "Respond with a dict containing these keys."
        ),
        "sprint_number":     current_sprint_number,
        "product_backlog_summary": summary_lines,
        "completed_sprints": completed_sprints,
        "project_description": state.get("project_description", ""),
        # Pass previous sprint backlog feedback so the planner knows what was
        # rejected if this is a replan
        "sprint_backlog_feedback": state.get("sprint_backlog_feedback"),
    }

    planner_response: Dict[str, Any] = interrupt(payload)

    sprint_feedback = {
        "sprint_goal":       (planner_response.get("sprint_goal") or "").strip(),
        "capacity_points":   int(planner_response.get("capacity_points") or _DEFAULT_SPRINT_CAPACITY),
        "completed_pbi_ids": list(planner_response.get("completed_pbi_ids") or []),
        "plan_another":      bool(planner_response.get("plan_another", False)),
        "notes":             (planner_response.get("notes") or "").strip(),
    }

    # Write the _sprint_feedback_ready sentinel so SprintAgent.process()
    # knows to run Pipeline B on its next call.
    artifacts["_sprint_feedback_ready"] = True

    logger.info(
        "[SprintFeedback] Sprint %d — goal='%s', capacity=%d, plan_another=%s.",
        current_sprint_number,
        sprint_feedback["sprint_goal"],
        sprint_feedback["capacity_points"],
        sprint_feedback["plan_another"],
    )

    return {
        "artifacts":             artifacts,
        "sprint_feedback":       sprint_feedback,
        "current_sprint_number": current_sprint_number,
        # Clear any previous rejection feedback now that the planner has re-confirmed inputs
        "sprint_backlog_feedback": None,
    }


# ── Review node: sprint backlog (step 6 — NEW) ────────────────────────────────

def review_sprint_backlog_turn_fn(state: WorkflowState) -> Dict[str, Any]:
    """
    Human review of the sprint backlog via interrupt().

    Presents selected PBIs with capacity usage, dependency info, sprint goal,
    and methodology.

    Approval  → reviewed_sprint_backlog_N written.
                If plan_another=True: current_sprint_number incremented;
                supervisor routes back to sprint_feedback_turn for next sprint.
                If plan_another=False: workflow ends.
    Rejection → sprint_backlog_N removed from artifacts;
                _sprint_feedback_ready sentinel re-added so supervisor routes
                to sprint_agent_turn for a replan (not sprint_feedback_turn,
                since the planner already provided their inputs).
    """
    artifacts             = dict(state.get("artifacts") or {})
    current_sprint_number = state.get("current_sprint_number", 1)
    artifact_key          = f"sprint_backlog_{current_sprint_number}"
    sprint_backlog        = artifacts.get(artifact_key, {})
    items                 = sprint_backlog.get("items") or []

    review_payload = _format_sprint_review_payload(sprint_backlog, items, current_sprint_number)

    reviewer_response: Dict[str, Any] = interrupt(review_payload)

    approved = bool(reviewer_response.get("approved", False))
    feedback = (reviewer_response.get("feedback") or "").strip()

    if approved:
        reviewed_key = f"reviewed_sprint_backlog_{current_sprint_number}"
        reviewed_sprint = {
            **sprint_backlog,
            "status":       "approved",
            "reviewed_at":  datetime.now().isoformat(),
            "review_notes": feedback or None,
        }
        artifacts[reviewed_key] = reviewed_sprint

        plan_another          = sprint_backlog.get("plan_another", False)
        next_sprint_number    = current_sprint_number + 1 if plan_another else current_sprint_number

        logger.info(
            "[Review/Sprint] Sprint %d APPROVED — %d items, plan_another=%s.",
            current_sprint_number, len(items), plan_another,
        )

        updates: Dict[str, Any] = {
            "artifacts":                      artifacts,
            "sprint_backlog_review_approved": True,
            "sprint_backlog_feedback":        None,
            "current_sprint_number":          next_sprint_number,
        }
        return updates

    # Rejection: remove sprint_backlog_N and re-add the sentinel so the
    # supervisor routes to sprint_agent_turn (Pipeline B replan).
    artifacts.pop(artifact_key, None)
    artifacts["_sprint_feedback_ready"] = True   # trigger replan without re-asking planner

    logger.info(
        "[Review/Sprint] Sprint %d REJECTED. Feedback: %s",
        current_sprint_number, feedback or "(none)",
    )
    return {
        "artifacts":                      artifacts,
        "sprint_backlog_review_approved": False,
        "sprint_backlog_feedback":        feedback or "The reviewer did not provide specific feedback.",
    }


# ── Review payload formatters ─────────────────────────────────────────────────

def _format_interview_review_payload(
    record: Dict[str, Any],
    requirements: list,
) -> Dict[str, Any]:
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


def _format_backlog_review_payload(
    backlog: Dict[str, Any],
    items: list,
) -> Dict[str, Any]:
    """Build the review payload presented to the product backlog reviewer."""
    item_summaries = []
    for item in items:
        invest = item.get("invest") or {}
        failed_invest = [k for k, v in invest.items() if not v]
        item_summaries.append({
            "id":              item.get("id"),
            "source_req_id":   item.get("source_req_id"),
            "title":           item.get("title"),
            "type":            item.get("type"),
            "priority_rank":   item.get("priority_rank"),
            "story_points":    item.get("story_points"),
            "wsjf_score":      item.get("wsjf_score"),
            "business_value":  item.get("business_value"),
            "time_criticality":item.get("time_criticality"),
            "risk_reduction":  item.get("risk_reduction"),
            "complexity":      item.get("complexity"),
            "effort":          item.get("effort"),
            "uncertainty":     item.get("uncertainty"),
            "invest_passed":   not bool(failed_invest),
            "invest_failed":   failed_invest,
            "description":     item.get("description", "")[:200],
        })

    methodology = backlog.get("methodology") or {}
    return {
        "review_prompt": (
            "Please review the product backlog below.\n"
            "For each item you can see:\n"
            "  • priority_rank   — WSJF-based ranking (1 = highest priority)\n"
            "  • story_points    — Fibonacci estimate\n"
            "  • wsjf_score      — (BV + TC + RR) / StoryPoints\n"
            "  • invest_failed   — INVEST criteria not met (if any)\n"
            "  • description     — the user story\n\n"
            "Respond with:\n"
            "  {\"approved\": true}                              to approve\n"
            "  {\"approved\": false, \"feedback\": \"<text>\"}  to request changes"
        ),
        "total_items":   len(items),
        "methodology":   methodology,
        "notes":         backlog.get("notes", ""),
        "created_at":    backlog.get("created_at"),
        "items":         item_summaries,
    }


def _format_sprint_review_payload(
    sprint_backlog: Dict[str, Any],
    items: list,
    sprint_number: int,
) -> Dict[str, Any]:
    """Build the review payload presented to the sprint backlog reviewer."""
    item_summaries = []
    for item in items:
        dep_on  = item.get("depends_on") or []
        enables = item.get("enables") or []
        item_summaries.append({
            "id":               item.get("id"),
            "title":            item.get("title"),
            "type":             item.get("type"),
            "priority_rank":    item.get("priority_rank"),
            "story_points":     item.get("story_points"),
            "wsjf_score":       item.get("wsjf_score"),
            "dep_type":         item.get("dep_type", "none"),
            "depends_on":       dep_on,
            "enables":          enables,
            "inclusion_reason": item.get("inclusion_reason", ""),
            "description":      item.get("description", "")[:200],
        })

    return {
        "review_prompt": (
            f"Please review Sprint {sprint_number} Backlog below.\n"
            "For each selected item you can see:\n"
            "  • priority_rank    — original WSJF-based rank\n"
            "  • story_points     — Fibonacci estimate\n"
            "  • dep_type         — dependency type (hard / soft / none)\n"
            "  • depends_on       — prerequisite PBI IDs\n"
            "  • inclusion_reason — why this item was selected\n\n"
            "Respond with:\n"
            "  {\"approved\": true}                              to approve\n"
            "  {\"approved\": false, \"feedback\": \"<text>\"}  to request changes"
        ),
        "sprint_number":      sprint_number,
        "sprint_goal":        sprint_backlog.get("sprint_goal", ""),
        "capacity_points":    sprint_backlog.get("capacity_points"),
        "allocated_points":   sprint_backlog.get("allocated_points"),
        "remaining_points":   sprint_backlog.get("remaining_points"),
        "plan_another":       sprint_backlog.get("plan_another", False),
        "total_items":        len(items),
        "items":              item_summaries,
        "notes":              sprint_backlog.get("notes", ""),
        "created_at":         sprint_backlog.get("created_at"),
    }


# ── Conditional edges ─────────────────────────────────────────────────────────

def after_interviewer(state: WorkflowState) -> str:
    """Two-tier stopping: semantic (interview_complete) or structural (max_turns)."""
    if state.get("interview_complete", False):
        logger.info("Tier-1 stop: interview_complete=True → supervisor.")
        return "supervisor"

    turn_count = state.get("turn_count", 0)
    max_turns  = state.get("max_turns", _INTERVIEW_SAFETY_MAX_TURNS)

    if turn_count >= max_turns:
        logger.warning(
            "Tier-2 safety net: turn_count=%d >= max_turns=%d → supervisor.",
            turn_count, max_turns,
        )
        return "supervisor"

    return "enduser_turn"


def after_sprint_feedback(state: WorkflowState) -> str:
    """
    After sprint_feedback_turn, always route to sprint_agent_turn (Pipeline B).
    The _sprint_feedback_ready sentinel has been written; SprintAgent will
    detect it and run analyse_dependencies + write_sprint_backlog.
    """
    return "sprint_agent_turn"


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
        if name.startswith("_"):
            continue   # skip internal sentinels (e.g. _sprint_feedback_ready)

        is_new_or_updated = (
            name not in existing_items or existing_items[name] != content
        )

        if is_new_or_updated:
            store.put(namespace, name, {"content": content})
            logger.info("Store: persisted '%s' for session '%s'.", name, session_id)

            file_name        = f"{name}_{session_id}.json"
            latest_file_path = latest_dir / file_name

            if latest_file_path.exists():
                timestamp         = datetime.now().strftime("%Y%m%d_%H%M%S")
                version_file_name = f"{name}_{session_id}_v{timestamp}.json"
                shutil.move(str(latest_file_path), str(versions_dir / version_file_name))
                logger.info("File: Moved older version of '%s' to versions.", name)

            try:
                with open(latest_file_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
                logger.info("File: Saved '%s' to %s", name, latest_file_path)
            except Exception as e:
                logger.error("File: Failed to save '%s': %s", name, e)


def get_artifact_from_store(session_id: str, artifact_name: str) -> Optional[Any]:
    store = _default_store()
    item  = store.get(("artifacts", session_id), artifact_name)
    return item.value.get("content") if item else None


# ── Build graph ───────────────────────────────────────────────────────────────

def build_graph(store=None, checkpointer=None):
    """
    Compile the LangGraph workflow.

    Sprint Zero chain:
      interviewer_turn ↔ enduser_turn       → supervisor
      review_turn                            → supervisor
      sprint_agent_turn (Pipeline A)         → supervisor
      review_product_backlog_turn            → supervisor
      sprint_feedback_turn                   → sprint_agent_turn (Pipeline B)
      sprint_agent_turn (Pipeline B)         → supervisor
      review_sprint_backlog_turn             → supervisor
      supervisor                             → END (or loops)

    Note: interrupt() nodes require a persistent checkpointer in production.
    """
    if store is None:
        store = _default_store()

    if checkpointer is None:
        logger.warning(
            "build_graph: no checkpointer provided. "
            "review_turn, review_product_backlog_turn, sprint_feedback_turn, "
            "and review_sprint_backlog_turn use interrupt() which requires "
            "persistent checkpoint storage in production."
        )

    g = StateGraph(WorkflowState)

    # ── Nodes ──────────────────────────────────────────────────────────────
    g.add_node("supervisor",                     supervisor_node_fn)
    g.add_node("interviewer_turn",               interviewer_turn_fn)
    g.add_node("enduser_turn",                   enduser_turn_fn)
    g.add_node("review_turn",                    review_turn_fn)
    g.add_node("sprint_agent_turn",              sprint_agent_turn_fn)
    g.add_node("review_product_backlog_turn",    review_product_backlog_turn_fn)    # NEW
    g.add_node("sprint_feedback_turn",           sprint_feedback_turn_fn)           # NEW
    g.add_node("review_sprint_backlog_turn",     review_sprint_backlog_turn_fn)     # NEW

    g.set_entry_point("supervisor")

    # ── Supervisor → next node ─────────────────────────────────────────────
    g.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "interviewer_turn":            "interviewer_turn",
            "review_turn":                 "review_turn",
            "sprint_agent_turn":           "sprint_agent_turn",
            "review_product_backlog_turn": "review_product_backlog_turn",   # NEW
            "sprint_feedback_turn":        "sprint_feedback_turn",          # NEW
            "review_sprint_backlog_turn":  "review_sprint_backlog_turn",    # NEW
            "__end__":                     END,
        },
    )

    # ── Interview loop ─────────────────────────────────────────────────────
    g.add_conditional_edges(
        "interviewer_turn",
        after_interviewer,
        {
            "supervisor":   "supervisor",
            "enduser_turn": "enduser_turn",
        },
    )
    g.add_edge("enduser_turn", "interviewer_turn")

    # ── Review nodes → supervisor ──────────────────────────────────────────
    g.add_edge("review_turn",                 "supervisor")
    g.add_edge("review_product_backlog_turn", "supervisor")   # NEW
    g.add_edge("review_sprint_backlog_turn",  "supervisor")   # NEW

    # ── Sprint: feedback → Pipeline B → supervisor ─────────────────────────
    g.add_conditional_edges(
        "sprint_feedback_turn",
        after_sprint_feedback,
        {"sprint_agent_turn": "sprint_agent_turn"},
    )
    g.add_edge("sprint_agent_turn", "supervisor")

    # ── Compile ────────────────────────────────────────────────────────────
    compile_kwargs: Dict[str, Any] = {"store": store}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)