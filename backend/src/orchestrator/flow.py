"""
flow.py – Workflow phase and step definitions.

Sprint Zero artifact chain (6 steps)
──────────────────────────────────────
  Step 1 – conduct_requirements_interview
    Agent : InterviewerAgent ↔ EndUserAgent
    Input : (none)
    Output: interview_record

  Step 2 – review_interview_record          ← human-in-the-loop gate
    Agent : human reviewer (LangGraph interrupt)
    Input : interview_record
    Output: reviewed_interview_record
    • Approved  → advance to step 3
    • Rejected  → interview_record removed; review_feedback injected; back to step 1

  Step 3 – build_product_backlog
    Agent : SprintAgent (Pipeline A)
    Input : reviewed_interview_record
    Output: product_backlog

  Step 4 – review_product_backlog           ← human-in-the-loop gate  [NEW]
    Agent : human reviewer (LangGraph interrupt)
    Input : product_backlog
    Output: reviewed_product_backlog
    • Approved  → advance to step 5
    • Rejected  → product_backlog removed; product_backlog_feedback injected;
                  back to step 3 (SprintAgent rebuilds)

  Step 5 – plan_sprint_backlog              ← sprint feedback + Pipeline B  [NEW]
    Agent : SprintAgent (Pipeline B), preceded by sprint_feedback_turn interrupt
    Input : reviewed_product_backlog  +  _sprint_feedback_ready sentinel
    Output: sprint_backlog_<N>

  Step 6 – review_sprint_backlog            ← human-in-the-loop gate  [NEW]
    Agent : human reviewer (LangGraph interrupt)
    Input : sprint_backlog_<N>
    Output: reviewed_sprint_backlog_<N>
    • Approved  → workflow ends (or loops to step 5 if plan_another=True)
    • Rejected  → sprint_backlog_N removed; _sprint_feedback_ready re-added;
                  SprintAgent replans

Routing notes
─────────────
Steps 5 and 6 loop for multiple sprints:
  - After review_sprint_backlog is approved:
      * If plan_another=True  → _sprint_feedback_ready removed from artifacts,
        reviewed_sprint_backlog_N written, current_sprint_number incremented,
        flow returns to step 5 (sprint_feedback_turn triggers the next sprint).
      * If plan_another=False → workflow ends (all artifacts complete).
  - After review_sprint_backlog is rejected:
      * reviewed_sprint_backlog_N NOT written.
      * sprint_backlog_N removed from artifacts.
      * _sprint_feedback_ready sentinel re-added so supervisor routes back
        to sprint_agent_turn for a replan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class ArtifactStep:
    step_name:          str
    node_name:          str
    requires_artifacts: List[str]
    produces_artifact:  str
    agent_name:         str
    description:        str = ""


@dataclass
class PhaseDefinition:
    phase_name:   str
    display_name: str
    description:  str
    steps:        List[ArtifactStep]
    next_phase:   Optional[str] = None


WORKFLOW_PHASES: List[PhaseDefinition] = [

    PhaseDefinition(
        phase_name="sprint_zero_planning",
        display_name="Sprint Zero — Discovery & Planning",
        description=(
            "Gather requirements via stakeholder interviews, review them, "
            "build a product backlog, review it, then plan and review sprint backlogs."
        ),
        steps=[
            # ── Step 1 ────────────────────────────────────────────────────
            ArtifactStep(
                step_name="conduct_requirements_interview",
                node_name="interviewer_turn",
                requires_artifacts=[],
                produces_artifact="interview_record",
                agent_name="interviewer",
                description=(
                    "InterviewerAgent conducts a multi-turn dialogue. "
                    "After EACH stakeholder reply, calls update_requirements "
                    "to extract, merge, and conflict-check incrementally. "
                    "Every requirement is stored with a 'rationale' and 'history'. "
                    "Stops when completeness ≥ threshold (interview_complete=True) "
                    "or max_turns safety net is reached."
                ),
            ),

            # ── Step 2 ────────────────────────────────────────────────────
            ArtifactStep(
                step_name="review_interview_record",
                node_name="review_turn",
                requires_artifacts=["interview_record"],
                produces_artifact="reviewed_interview_record",
                agent_name="human_reviewer",
                description=(
                    "Human reviewer inspects every requirement (with rationale and "
                    "history). Approved → reviewed_interview_record written. "
                    "Rejected → interview_record removed; review_feedback injected; "
                    "flow returns to step 1."
                ),
            ),

            # ── Step 3 ────────────────────────────────────────────────────
            ArtifactStep(
                step_name="build_product_backlog",
                node_name="sprint_agent_turn",
                requires_artifacts=["reviewed_interview_record"],
                produces_artifact="product_backlog",
                agent_name="sprint_agent",
                description=(
                    "SprintAgent (Pipeline A) reads reviewed_interview_record and "
                    "generates the initial product backlog using Fibonacci estimation, "
                    "INVEST validation, and WSJF prioritization."
                ),
            ),

            # ── Step 4 (NEW) ──────────────────────────────────────────────
            ArtifactStep(
                step_name="review_product_backlog",
                node_name="review_product_backlog_turn",
                requires_artifacts=["product_backlog"],
                produces_artifact="reviewed_product_backlog",
                agent_name="human_reviewer",
                description=(
                    "Human reviewer inspects the product backlog (story points, "
                    "WSJF scores, INVEST criteria, priority ranks). "
                    "Approved → reviewed_product_backlog written; flow advances "
                    "to sprint planning. "
                    "Rejected → product_backlog removed; product_backlog_feedback "
                    "injected; flow returns to step 3 (SprintAgent rebuilds)."
                ),
            ),

            # ── Step 5 (NEW) ──────────────────────────────────────────────
            # NOTE: The actual sprint planning uses TWO nodes in sequence:
            #   sprint_feedback_turn  — interrupt to collect human planner inputs
            #   sprint_agent_turn     — SprintAgent Pipeline B (uses _sprint_feedback_ready)
            # The flow.py step points to sprint_feedback_turn as the entry;
            # after the interrupt, the graph routes to sprint_agent_turn automatically.
            # The produces_artifact is dynamically named sprint_backlog_<N>;
            # we use "sprint_backlog_1" as the sentinel for the first sprint.
            ArtifactStep(
                step_name="plan_sprint_backlog",
                node_name="sprint_feedback_turn",
                requires_artifacts=["reviewed_product_backlog"],
                produces_artifact="sprint_backlog_1",
                agent_name="sprint_agent",
                description=(
                    "Human planner supplies sprint goal, capacity, and completed PBIs "
                    "via sprint_feedback_turn interrupt. SprintAgent (Pipeline B) then "
                    "runs analyse_dependencies + write_sprint_backlog to produce "
                    "sprint_backlog_<N>."
                ),
            ),

            # ── Step 6 (NEW) ──────────────────────────────────────────────
            ArtifactStep(
                step_name="review_sprint_backlog",
                node_name="review_sprint_backlog_turn",
                requires_artifacts=["sprint_backlog_1"],
                produces_artifact="reviewed_sprint_backlog_1",
                agent_name="human_reviewer",
                description=(
                    "Human reviewer inspects the sprint backlog (selected PBIs, "
                    "capacity usage, dependency enforcement, sprint goal). "
                    "Approved → reviewed_sprint_backlog_N written; if plan_another "
                    "is True the loop continues to the next sprint. "
                    "Rejected → sprint_backlog_N removed; _sprint_feedback_ready "
                    "re-added; SprintAgent replans."
                ),
            ),
        ],
        next_phase="sprint_execution",
    ),

    PhaseDefinition(
        phase_name="sprint_execution",
        display_name="Sprint N — Execution",
        description="Iterative sprint cycles.",
        steps=[],
        next_phase="sprint_review",
    ),

    PhaseDefinition(
        phase_name="sprint_review",
        display_name="Sprint Review & Retrospective",
        description="Evaluate sprint outcomes and retrospective.",
        steps=[],
        next_phase=None,
    ),
]

PHASE_INDEX: Dict[str, PhaseDefinition] = {p.phase_name: p for p in WORKFLOW_PHASES}
PHASE_ORDER: List[str] = [p.phase_name for p in WORKFLOW_PHASES]


def get_next_action(
    artifacts: Dict,
    current_phase: Optional[str] = None,
) -> Optional[Tuple[str, str, str]]:
    """
    Find the next step to execute, scanning from current_phase onward.

    Multi-sprint awareness
    ──────────────────────
    Steps 5 and 6 use dynamic artifact names (sprint_backlog_N,
    reviewed_sprint_backlog_N).  When the supervisor calls this function after
    a sprint review is approved and plan_another=True, neither sprint_backlog_N+1
    nor reviewed_sprint_backlog_N+1 exist yet — so get_next_action() would
    return step 5 again (sprint_feedback_turn), which is the correct behaviour.

    The static sentinel "sprint_backlog_1" in requires_artifacts / produces_artifact
    of step 5 & 6 means: "the first sprint has been attempted."  Subsequent
    sprints are handled by the graph's own loop logic (supervisor always re-routes
    to sprint_feedback_turn when plan_another=True and no new sprint artifact exists).
    """
    start_idx = 0
    if current_phase and current_phase in PHASE_INDEX:
        try:
            start_idx = PHASE_ORDER.index(current_phase)
        except ValueError:
            start_idx = 0

    for i in range(start_idx, len(WORKFLOW_PHASES)):
        phase = WORKFLOW_PHASES[i]
        for step in phase.steps:
            reqs_met = all(r in artifacts for r in step.requires_artifacts)
            not_done = step.produces_artifact not in artifacts
            if reqs_met and not_done:
                return phase.phase_name, step.step_name, step.node_name

    return None