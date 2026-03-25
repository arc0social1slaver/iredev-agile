"""
flow.py – Workflow phase and step definitions.

Architecture
────────────
Phases are executed in strict sequential order (hard flow):
    Sprint Zero Planning → Sprint Execution → Sprint Review

Within each phase, routing is artifact-driven (soft flow):
    The supervisor scans the phase's steps in order and activates the first
    step whose required artifacts exist but whose output artifact is absent.

Adding a new step to a phase
─────────────────────────────
    1. Define an ArtifactStep with the correct node_name and artifact keys.
    2. Append it to the relevant PhaseDefinition.steps list.
    3. Register the corresponding graph node in graph.py.
    No other file needs to change.

Adding a new phase
──────────────────
    1. Append a PhaseDefinition to WORKFLOW_PHASES.
    2. Set next_phase on the preceding phase to point to it.
    3. Register graph nodes for all steps in graph.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# ArtifactStep – one artifact-producing unit of work within a phase
# ---------------------------------------------------------------------------

@dataclass
class ArtifactStep:
    """
    Describes a single work unit inside a phase.

    The supervisor selects a step when:
      - all entries in requires_artifacts exist in WorkflowState["artifacts"]
      - produces_artifact is NOT yet in WorkflowState["artifacts"]

    node_name maps directly to a LangGraph node registered in graph.py.
    """
    step_name:          str         # logical label for logging / debugging
    node_name:          str         # graph node to activate for this step
    requires_artifacts: List[str]   # artifact keys that must exist first
    produces_artifact:  str         # artifact key this step is responsible for
    agent_name:         str         # agent that drives this step (informational)
    description:        str = ""    # human-readable explanation


# ---------------------------------------------------------------------------
# PhaseDefinition – one top-level phase
# ---------------------------------------------------------------------------

@dataclass
class PhaseDefinition:
    """
    A top-level workflow phase.

    Phases advance sequentially (hard flow).
    Within each phase, steps are selected by artifact-driven logic.
    """
    phase_name:   str                    # matches a SystemPhase enum value
    display_name: str                    # human-readable label
    description:  str                    # what this phase accomplishes
    steps:        List[ArtifactStep]     # ordered list of intra-phase steps
    next_phase:   Optional[str] = None   # next phase name (None = terminal)


# ---------------------------------------------------------------------------
# WORKFLOW DEFINITION
# ─────────────────────────────────────────────────────────────────────────
# Three phases, each with a list of artifact steps.
# Phases without steps are stubs reserved for future implementation.
# ---------------------------------------------------------------------------

WORKFLOW_PHASES: List[PhaseDefinition] = [

    # ── Phase 0: Sprint Zero Planning ─────────────────────────────────────
    PhaseDefinition(
        phase_name="sprint_zero_planning",
        display_name="Sprint Zero — Discovery & Planning",
        description=(
            "Gather software requirements via stakeholder interviews and "
            "translate them into an initial product backlog."
        ),
        steps=[
            ArtifactStep(
                step_name="conduct_requirements_interview",
                node_name="interviewer_turn",
                requires_artifacts=[],              # nothing needed to start
                produces_artifact="interview_record",
                agent_name="interviewer",
                description=(
                    "InterviewerAgent conducts a multi-turn dialogue with "
                    "EndUserAgent to elicit requirements and writes the "
                    "interview_record artifact."
                ),
            ),
            ArtifactStep(
                step_name="build_product_backlog",
                node_name="sprint_agent_turn",
                requires_artifacts=["interview_record"],
                produces_artifact="product_backlog",
                agent_name="sprint_agent",
                description=(
                    "SprintAgent reads the interview_record and generates "
                    "the initial product backlog."
                ),
            ),
        ],
        next_phase="sprint_execution",
    ),

    # ── Phase 1: Sprint N Execution ────────────────────────────────────────
    PhaseDefinition(
        phase_name="sprint_execution",
        display_name="Sprint N — Execution",
        description=(
            "Iterative sprint cycles: plan a sprint from the backlog, "
            "implement user stories, and integrate deliverables."
        ),
        steps=[
            # Future steps (uncomment and implement as needed):
            # ArtifactStep(
            #     step_name="plan_sprint",
            #     node_name="sprint_planner_turn",
            #     requires_artifacts=["product_backlog"],
            #     produces_artifact="sprint_plan",
            #     agent_name="sprint_planner",
            # ),
            # ArtifactStep(
            #     step_name="implement_sprint",
            #     node_name="developer_turn",
            #     requires_artifacts=["sprint_plan"],
            #     produces_artifact="sprint_increment",
            #     agent_name="developer",
            # ),
        ],
        next_phase="sprint_review",
    ),

    # ── Phase 2: Sprint Review & Retrospective ─────────────────────────────
    PhaseDefinition(
        phase_name="sprint_review",
        display_name="Sprint Review & Retrospective",
        description=(
            "Evaluate sprint outcomes, collect stakeholder feedback, "
            "and conduct a team retrospective."
        ),
        steps=[
            # Future steps (uncomment and implement as needed):
            # ArtifactStep(
            #     step_name="conduct_sprint_review",
            #     node_name="reviewer_turn",
            #     requires_artifacts=["sprint_increment"],
            #     produces_artifact="sprint_review_report",
            #     agent_name="reviewer",
            # ),
        ],
        next_phase=None,   # terminal phase
    ),
]


# ---------------------------------------------------------------------------
# Indices and helpers
# ---------------------------------------------------------------------------

# Fast lookup by phase name
PHASE_INDEX: Dict[str, PhaseDefinition] = {p.phase_name: p for p in WORKFLOW_PHASES}

# Ordered list of phase names (used for index-based scanning)
PHASE_ORDER: List[str] = [p.phase_name for p in WORKFLOW_PHASES]


def get_next_action(
    artifacts: Dict,
    current_phase: Optional[str] = None,
) -> Optional[Tuple[str, str, str]]:
    """
    Determine what to do next given the current artifacts and phase.

    Scans phases starting from *current_phase* (defaults to the first phase).
    Within each phase, returns the first step whose prerequisites are met
    but whose output artifact is absent.

    Returns
    ───────
    (phase_name, step_name, node_name)  – the next action to take, or
    None                                – the entire workflow is complete.
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

    return None   # all work is done