"""
supervisor.py – Deterministic, artifact-driven supervisor.

Routing logic
─────────────
1. Read system_phase and artifacts from state.
2. Call get_next_action() to find the next step to execute:
     - Scans phases from the current one onward.
     - Picks the first step whose prerequisites are met but output is absent.
3. Route to that step's graph node and record the (possibly updated) phase.
4. If get_next_action() returns None (all phases complete), route to END.

No LLM is required: routing is fully determined by phase + artifact state.
This keeps the supervisor fast, deterministic, and easy to test.

Output contract
───────────────
supervisor_node returns a partial WorkflowState dict:
  {
    "next_node":    "<graph node name or '__end__'>",
    "system_phase": "<SystemPhase value>",   # updated if phase advanced
  }

supervisor_router translates state["next_node"] into a LangGraph edge target.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .flow import PHASE_INDEX, PHASE_ORDER, get_next_action
from .state import WorkflowState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supervisor node
# ---------------------------------------------------------------------------

def supervisor_node(state: WorkflowState) -> Dict[str, Any]:
    """
    Inspect state and emit routing signals.

    Returns
    ───────
    Partial WorkflowState dict with at least:
      next_node    – name of the next graph node (or "__end__")
      system_phase – current (or newly advanced) phase name
    """
    artifacts     = state.get("artifacts") or {}
    current_phase = state.get("system_phase") or PHASE_ORDER[0]

    result = get_next_action(artifacts, current_phase)

    # ── Workflow complete ─────────────────────────────────────────────────
    if result is None:
        logger.info(
            "Supervisor: all phases complete (artifacts=%s) → __end__",
            list(artifacts.keys()),
        )
        return {
            "next_node":    "__end__",
            "system_phase": current_phase,
        }

    # ── Next step found ───────────────────────────────────────────────────
    phase_name, step_name, node_name = result

    # Log a phase transition when the phase actually changes
    if phase_name != current_phase:
        phase_def = PHASE_INDEX.get(phase_name)
        display   = phase_def.display_name if phase_def else phase_name
        logger.info(
            "Supervisor: phase transition  '%s' → '%s'  (%s)",
            current_phase, phase_name, display,
        )

    logger.info(
        "Supervisor: phase='%s'  step='%s'  → node='%s'  "
        "(artifacts present=%s)",
        phase_name, step_name, node_name, list(artifacts.keys()),
    )

    return {
        "next_node":    node_name,
        "system_phase": phase_name,
    }


# ---------------------------------------------------------------------------
# LangGraph conditional-edge router
# ---------------------------------------------------------------------------

def supervisor_router(state: WorkflowState) -> str:
    """
    Translate state["next_node"] into a LangGraph destination node name.

    This function is passed as the condition to add_conditional_edges().
    The return value must match a key in the edges mapping dict.
    """
    return state.get("next_node", "__end__")