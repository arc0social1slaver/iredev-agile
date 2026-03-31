"""
flow.py – Workflow phase and step definitions.

Sprint Zero artifact chain
──────────────────────────
  Step 1 – conduct_requirements_interview
    Agent : InterviewerAgent ↔ EndUserAgent
    Input : (none)
    Output: interview_record

    InterviewerAgent calls update_requirements after EVERY stakeholder turn.
    Conflicts are resolved INLINE via Socratic follow-up — not post-hoc.
    Stops when interview_complete=True (completeness ≥ threshold, LLM-driven)
    or max_turns (safety net).

  Step 2 – build_product_backlog
    Agent : SprintAgent
    Input : interview_record
    Output: product_backlog

Design rationale (no separate extraction step)
───────────────────────────────────────────────
Extraction is now incremental and conflict-aware. The interview_record
already contains a clean requirements_identified list built turn-by-turn.
A separate extraction pass would duplicate work and lose conflict context.
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
            "Gather software requirements via stakeholder interviews "
            "(with live, conflict-aware incremental extraction) and "
            "translate them into an initial product backlog."
        ),
        steps=[
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
                    "Conflicts trigger inline Socratic clarification. "
                    "Stops when completeness ≥ threshold (interview_complete=True) "
                    "or max_turns safety net is reached."
                ),
            ),
            ArtifactStep(
                step_name="build_product_backlog",
                node_name="sprint_agent_turn",
                requires_artifacts=["interview_record"],
                produces_artifact="product_backlog",
                agent_name="sprint_agent",
                description=(
                    "SprintAgent reads interview_record and generates "
                    "the initial product backlog."
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