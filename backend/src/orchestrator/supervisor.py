"""
supervisor.py – Deterministic, artifact-driven supervisor.

Routing logic
─────────────
1. Read system_phase, artifacts, and current_sprint_number from state.
2. Apply routing overrides (in priority order):
     Override 1 — _sprint_feedback_ready sentinel present → sprint_agent_turn (Pipeline B)
     Override 2 — sprint_backlog_N present but NOT reviewed_sprint_backlog_N → review
     Override 3 — multi-sprint loop: plan_another=True, sprint_backlog_N+1 absent → sprint_feedback_turn
3. Fall through to get_next_action() for standard artifact-driven routing.
4. If get_next_action() returns None → END.

Override details
─────────────────
Override 1 (_sprint_feedback_ready)
  Written by sprint_feedback_turn after collecting planner inputs.
  Re-written by review_sprint_backlog_turn on rejection (to trigger replan).
  Routes to sprint_agent_turn so Pipeline B runs without re-collecting inputs.
  Removed by SprintAgent._tool_write_sprint_backlog after writing the artifact.

Override 2 (sprint_backlog_N exists, reviewed_sprint_backlog_N does not)
  Needed for sprints 2+ because flow.py only has static step entries for
  sprint_backlog_1 / reviewed_sprint_backlog_1.  Dynamic sprint numbers
  require explicit supervisor logic.
  Routes to review_sprint_backlog_turn.

Override 3 (plan_another=True, next sprint not started)
  After reviewed_sprint_backlog_N is written and plan_another=True,
  sprint_backlog_(N+1) does not exist yet.  Routes to sprint_feedback_turn
  for the next sprint.  The sprint_number is incremented in state by
  review_sprint_backlog_turn_fn before this override fires.

No LLM is required: routing is fully determined by phase + artifact state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .flow import PHASE_INDEX, PHASE_ORDER, get_next_action
from .state import WorkflowState

logger = logging.getLogger(__name__)


def supervisor_node(state: WorkflowState) -> Dict[str, Any]:
    """
    Inspect state and emit routing signals.

    Returns a partial WorkflowState dict:
      next_node    – name of the next graph node (or "__end__")
      system_phase – current (or newly advanced) phase name
    """
    artifacts             = state.get("artifacts") or {}
    current_phase         = state.get("system_phase") or PHASE_ORDER[0]
    current_sprint_number = state.get("current_sprint_number", 1)

    # ── Override 1: _sprint_feedback_ready → Pipeline B replan / first run ─
    # This fires when:
    #   (a) sprint_feedback_turn just collected planner inputs, OR
    #   (b) review_sprint_backlog_turn re-added the sentinel after rejection.
    # In both cases: run SprintAgent Pipeline B.
    if "_sprint_feedback_ready" in artifacts:
        logger.info(
            "Supervisor: _sprint_feedback_ready sentinel → sprint_agent_turn "
            "(sprint=%d).", current_sprint_number,
        )
        return {
            "next_node":    "sprint_agent_turn",
            "system_phase": current_phase,
        }

    # ── Override 2: sprint_backlog_N exists but not reviewed → review it ───
    # Needed for sprints 2+ where the flow.py static steps only cover sprint 1.
    sprint_key    = f"sprint_backlog_{current_sprint_number}"
    reviewed_key  = f"reviewed_sprint_backlog_{current_sprint_number}"
    if sprint_key in artifacts and reviewed_key not in artifacts:
        logger.info(
            "Supervisor: %s present but not reviewed → review_sprint_backlog_turn.",
            sprint_key,
        )
        return {
            "next_node":    "review_sprint_backlog_turn",
            "system_phase": current_phase,
        }

    # ── Override 3: multi-sprint loop (plan_another=True) ─────────────────
    # After reviewed_sprint_backlog_(N-1) is approved with plan_another=True,
    # current_sprint_number has been incremented to N.
    # Sprint N artifacts don't exist yet → route to sprint_feedback_turn.
    if current_sprint_number > 1:
        prev_reviewed = f"reviewed_sprint_backlog_{current_sprint_number - 1}"
        next_sprint   = f"sprint_backlog_{current_sprint_number}"
        if prev_reviewed in artifacts and next_sprint not in artifacts:
            prev = artifacts[prev_reviewed]
            if prev.get("plan_another", False):
                logger.info(
                    "Supervisor: plan_another=True, sprint %d not started "
                    "→ sprint_feedback_turn.",
                    current_sprint_number,
                )
                return {
                    "next_node":    "sprint_feedback_turn",
                    "system_phase": current_phase,
                }

    # ── Standard artifact-driven routing ──────────────────────────────────
    result = get_next_action(artifacts, current_phase)

    if result is None:
        logger.info(
            "Supervisor: all phases complete (artifacts=%s) → __end__",
            list(artifacts.keys()),
        )
        return {
            "next_node":    "__end__",
            "system_phase": current_phase,
        }

    phase_name, step_name, node_name = result

    if phase_name != current_phase:
        phase_def = PHASE_INDEX.get(phase_name)
        display   = phase_def.display_name if phase_def else phase_name
        logger.info(
            "Supervisor: phase transition '%s' → '%s' (%s)",
            current_phase, phase_name, display,
        )

    logger.info(
        "Supervisor: phase='%s'  step='%s'  → node='%s'  (artifacts=%s)",
        phase_name, step_name, node_name, list(artifacts.keys()),
    )

    return {
        "next_node":    node_name,
        "system_phase": phase_name,
    }


def supervisor_router(state: WorkflowState) -> str:
    return state.get("next_node", "__end__")