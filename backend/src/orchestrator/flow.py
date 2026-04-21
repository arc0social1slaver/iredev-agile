"""
flow.py – Workflow phase and step definitions.

Artifact chain
──────────────
Phase 1 — Sprint Zero (sprint_zero_planning):
  Step 1 – conduct_requirements_interview   → interview_record
  Step 2 – review_interview_record          → reviewed_interview_record   (HITL)
  Step 3 – build_product_backlog            → product_backlog
  Step 4 – review_product_backlog           → product_backlog_approved    (HITL)

Phase 2 — Backlog Refinement (backlog_refinement):
  Step 1 – groom_backlog                    → validated_product_backlog
  Step 2 – review_validated_backlog         → analyst_review_done         (HITL)

Phase 3 — Sprint Execution (sprint_execution):
  Placeholder — steps added incrementally when Sprint N is implemented.

Phase 4 — Sprint Review (sprint_review):
  Placeholder.

Supervisor routing
──────────────────
get_next_action() scans WORKFLOW_PHASES in order, returning the first step
whose prerequisites are met (all requires_artifacts present) but whose
output is absent (produces_artifact not yet in artifacts).
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

    # ── Phase 1: Sprint Zero ───────────────────────────────────────────────────
    PhaseDefinition(
        phase_name="sprint_zero_planning",
        display_name="Sprint Zero — Discovery & Planning",
        description=(
            "Gather software requirements via stakeholder interviews, submit the "
            "interview record for human review, translate approved requirements "
            "into an initial product backlog of user stories, then obtain Product "
            "Owner sign-off on the backlog before refinement begins."
        ),
        steps=[
            ArtifactStep(
                step_name="conduct_requirements_interview",
                node_name="interviewer_turn",
                requires_artifacts=[],
                produces_artifact="interview_record",
                agent_name="interviewer",
                description=(
                    "InterviewerAgent conducts a multi-turn dialogue with EndUserAgent. "
                    "After EACH stakeholder reply, calls update_requirements to extract, "
                    "merge, and conflict-check requirements incrementally. "
                    "Stops when interview_complete=True or max_turns reached."
                ),
            ),
            ArtifactStep(
                step_name="review_interview_record",
                node_name="review_interview_record_turn",
                requires_artifacts=["interview_record"],
                produces_artifact="reviewed_interview_record",
                agent_name="human_reviewer",
                description=(
                    "Human reviewer inspects the interview record: requirements, "
                    "rationale, and change history. "
                    "• Approved → reviewed_interview_record written. "
                    "• Rejected → interview_record removed, review_feedback injected, "
                    "  interview restarts."
                ),
            ),
            ArtifactStep(
                step_name="build_product_backlog",
                node_name="sprint_agent_turn",
                requires_artifacts=["reviewed_interview_record"],
                produces_artifact="product_backlog",
                agent_name="sprint_agent",
                description=(
                    "SprintAgent converts each approved requirement into a user story "
                    "('As a <role>, I can <capability>, so that <benefit>.') and "
                    "generates the initial product backlog with Fibonacci estimation, "
                    "INVEST validation, and WSJF prioritisation."
                ),
            ),
            ArtifactStep(
                step_name="review_product_backlog",
                node_name="review_product_backlog_turn",
                requires_artifacts=["product_backlog"],
                produces_artifact="product_backlog_approved",
                agent_name="human_reviewer",
                description=(
                    "Product Owner reviews the raw product backlog (user stories, "
                    "story points, WSJF scores, INVEST flags) before refinement. "
                    "• Approved → product_backlog_approved sentinel written; "
                    "  flow advances to Backlog Refinement. "
                    "• Rejected → product_backlog removed, product_backlog_feedback "
                    "  injected; SprintAgent rebuilds the backlog."
                ),
            ),
        ],
        next_phase="backlog_refinement",
    ),

    # ── Phase 2: Backlog Refinement ────────────────────────────────────────────
    PhaseDefinition(
        phase_name="backlog_refinement",
        display_name="Backlog Refinement — Analyst as Advisor",
        description=(
            "In a single pass, the AnalystAgent validates every PBI against INVEST "
            "and synthesizes Given-When-Then Acceptance Criteria derived from each "
            "user story and its Sprint 0 reasoning traces. "
            "Output: validated_product_backlog — every PBI enriched with quality "
            "notes and AC, ready for a single HITL approval gate."
        ),
        steps=[
            ArtifactStep(
                step_name="groom_backlog",
                node_name="analyst_turn",
                requires_artifacts=["product_backlog_approved"],
                produces_artifact="validated_product_backlog",
                agent_name="analyst",
                description=(
                    "AnalystAgent runs check_invest_quality → write_acceptance_criteria "
                    "→ publish_validated_backlog in one ReAct turn. "
                    "Output: validated_product_backlog with every PBI enriched "
                    "(invest_validation + acceptance_criteria + status='ready')."
                ),
            ),
            ArtifactStep(
                step_name="review_validated_backlog",
                node_name="review_validated_product_backlog_turn",
                requires_artifacts=["validated_product_backlog"],
                produces_artifact="validated_product_backlog_approved",
                agent_name="human_reviewer",
                description=(
                    "Product Owner reviews the validated_product_backlog in one gate. "
                    "• Approved → validated_product_backlog_approved sentinel; Sprint N can begin. "
                    "• Rejected → validated_product_backlog removed; analyst_feedback "
                    "  injected; flow returns to groom_backlog (full re-groom)."
                ),
            ),
        ],
        next_phase="sprint_execution",
    ),

    # ── Phase 3: Sprint Execution ──────────────────────────────────────────────
    PhaseDefinition(
        phase_name="sprint_execution",
        display_name="Sprint N — Execution",
        description=(
            "Iterative sprint cycles. Not yet implemented — placeholder."
        ),
        steps=[],
        next_phase="sprint_review",
    ),

    # ── Phase 4: Sprint Review ─────────────────────────────────────────────────
    PhaseDefinition(
        phase_name="sprint_review",
        display_name="Sprint Review & Retrospective",
        description=(
            "Human evaluates sprint output. Not yet implemented — placeholder."
        ),
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
    Scan phases from current_phase onward.
    Return (phase_name, step_name, node_name) for the first executable step,
    or None if all phases are complete.

    A step is executable when:
      • All requires_artifacts are present in artifacts.
      • produces_artifact is NOT yet present in artifacts.
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