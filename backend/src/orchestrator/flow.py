"""
flow.py – Workflow phase and step definitions.

Artifact chain
──────────────
Phase 1 — Sprint Zero (sprint_zero_planning):
  Step 1  – extract_product_vision         → product_vision
  Step 2  – review_product_vision          → reviewed_product_vision      (HITL)
  Step 3  – build_elicitation_agenda       → elicitation_agenda_artifact
  Step 4  – review_elicitation_agenda      → reviewed_elicitation_agenda  (HITL)
  Step 5  – conduct_requirements_interview → interview_record
  Step 6  – review_interview_record        → reviewed_interview_record    (HITL — approve-only)
  Step 7  – synthesise_requirement_list    → requirement_list
  Step 8  – review_requirement_list        → requirement_list_approved    (HITL)
  Step 9a – create_user_stories            → user_story_draft
  Step 9c – estimate_and_validate_stories  → analyst_estimation
  Step 9b – build_product_backlog          → product_backlog
  Step 10 – review_product_backlog         → product_backlog_approved     (HITL)

Phase 2 — Backlog Refinement (backlog_refinement):
  Step 1 – generate_acceptance_criteria   → validated_product_backlog
  Step 2 – review_validated_backlog       → validated_product_backlog_approved  (HITL)

Phase 3 — Sprint Execution (sprint_execution):
  Placeholder — steps added incrementally when Sprint N is implemented.

Phase 4 — Sprint Review (sprint_review):
  Placeholder.

SprintAgent pipeline (Steps 9a → 9c → 9b)
──────────────────────────────────────────
The product backlog is now built through a three-step collaboration between
SprintAgent (Product Owner) and AnalystAgent (Technical Lead):

  Step 9a — Story Creation (sprint_agent_turn):
    SprintAgent reads requirement_list_approved and converts each requirement
    into a user story ("As a … I can … so that …"). No estimation at this stage.
    Output: user_story_draft artifact.

  Step 9c — Technical Estimation & Validation (analyst_estimation_turn):
    AnalystAgent reads user_story_draft and performs:
      Pass 1 — Feasibility + INVEST assessment + dependency mapping.
               Stories > 8 points are flagged with split_proposals.
      Pass 2 — Fibonacci estimation (sole source of story_points in pipeline).
    If split_proposals exist, SprintAgent creates sub-stories and calls
    AnalystAgent again (max split_round = 2, tracked in state).
    Output: analyst_estimation artifact.

  Step 9b — WSJF Prioritization + Assembly (sprint_agent_turn):
    SprintAgent reads both user_story_draft and analyst_estimation, runs
    dependency-aware WSJF ranking, and assembles the final product_backlog.
    Output: product_backlog artifact with new consolidated schema.

AnalystAgent pipeline (Step 1, Phase 2)
────────────────────────────────────────
After product_backlog_approved, AnalystAgent runs a single AC-generation pass:
  Pass 3 — Given-When-Then Acceptance Criteria per PBI (2–5 per story).
  INVEST and estimation are already complete from Phase 1 — not repeated here.
  Output: validated_product_backlog artifact.

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
            "interview record for human review, synthesise and approve a structured "
            "Requirement List, then convert the approved list into an initial "
            "Product Backlog of user stories ready for Product Owner sign-off."
        ),
        steps=[
            # 1. Extract the initial vision (Node: interviewer_turn)
            ArtifactStep(
                step_name="extract_product_vision",
                node_name="interviewer_turn",
                requires_artifacts=[],
                produces_artifact="product_vision",
                agent_name="interviewer",
                description=(
                    "InterviewerAgent reads project_description and extracts a "
                    "ProductVision (stakeholders, core problem, value proposition, "
                    "epics, constraints, assumptions) via structured extraction."
                ),
            ),
            # 2. Human reviews the vision (Node: review_product_vision_turn)
            ArtifactStep(
                step_name="review_product_vision",
                node_name="review_product_vision_turn",
                requires_artifacts=["product_vision"],
                produces_artifact="reviewed_product_vision",
                agent_name="human_reviewer",
                description=(
                    "Human reviewer inspects the ProductVision. "
                    "• Approved → reviewed_product_vision written. "
                    "• Rejected → product_vision removed, product_vision_feedback injected; "
                    "  InterviewerAgent re-extracts vision with feedback."
                ),
            ),
            # 3. Build elicitation agenda (Node: interviewer_turn)
            ArtifactStep(
                step_name="build_elicitation_agenda",
                node_name="interviewer_turn",
                requires_artifacts=["reviewed_product_vision"],
                produces_artifact="elicitation_agenda_artifact",
                agent_name="interviewer",
                description=(
                    "InterviewerAgent reads reviewed_product_vision and builds the "
                    "ElicitationAgenda: an ordered list of elicitation items derived "
                    "from epics, assumptions, constraints, and stakeholder concerns. "
                    "Any elicitation_agenda_feedback from a prior HITL rejection is "
                    "injected so the agent rebuilds with reviewer comments."
                ),
            ),
            # 4. Human reviews the elicitation agenda (Node: review_elicitation_agenda_turn)
            ArtifactStep(
                step_name="review_elicitation_agenda",
                node_name="review_elicitation_agenda_turn",
                requires_artifacts=["elicitation_agenda_artifact"],
                produces_artifact="reviewed_elicitation_agenda",
                agent_name="human_reviewer",
                description=(
                    "Human reviewer inspects the ElicitationAgenda before the interview "
                    "begins — verifying coverage, priority, and scope. "
                    "• Approved → reviewed_elicitation_agenda written; interview starts. "
                    "• Rejected → elicitation_agenda_artifact removed, "
                    "  elicitation_agenda_feedback injected; InterviewerAgent rebuilds "
                    "  the agenda using reviewed_product_vision + feedback."
                ),
            ),
            # 5. Conduct the interview loop (Node: interviewer_turn)
            ArtifactStep(
                step_name="conduct_requirements_interview",
                node_name="interviewer_turn",
                requires_artifacts=["reviewed_elicitation_agenda"],
                produces_artifact="interview_record",
                agent_name="interviewer",
                description=(
                    "InterviewerAgent conducts a multi-turn agenda-driven dialogue "
                    "with EndUserAgent using reviewed_elicitation_agenda as the "
                    "canonical question list. On conclusion, writes the interview_record "
                    "artifact containing all elicitation Q&A pairs and raw requirement evidence."
                ),
            ),
            # 6. Human reviews interview record — approve-only (Node: review_interview_record_turn)
            ArtifactStep(
                step_name="review_interview_record",
                node_name="review_interview_record_turn",
                requires_artifacts=["reviewed_elicitation_agenda", "interview_record"],
                produces_artifact="reviewed_interview_record",
                agent_name="human_reviewer",
                description=(
                    "Human reviewer reads the interview record (view-only). "
                    "This gate is approve-only: the record cannot be rejected here. "
                    "Feedback on content quality should be provided at the "
                    "review_requirement_list gate, where synthesis can be re-run. "
                    "• Approved → reviewed_interview_record written; synthesis begins."
                ),
            ),
            # 7. Synthesise requirement list (Node: interviewer_turn)
            ArtifactStep(
                step_name="synthesise_requirement_list",
                node_name="interviewer_turn",
                requires_artifacts=["reviewed_interview_record"],
                produces_artifact="requirement_list",
                agent_name="interviewer",
                description=(
                    "InterviewerAgent runs the 4-pass SRS synthesis pipeline: "
                    "Pass 1 FR extraction → Pass 2 NFR/CON/OOS extraction → "
                    "Pass 3 coverage check → Pass 4 quality gate + assembly. "
                    "Output: structured requirement_list (FR, NFR, CON, OOS). "
                    "Any requirement_list_feedback from a prior HITL rejection is "
                    "injected into all four passes."
                ),
            ),
            # 8. Human reviews requirement list (Node: review_requirement_list_turn)
            ArtifactStep(
                step_name="review_requirement_list",
                node_name="review_requirement_list_turn",
                requires_artifacts=["requirement_list"],
                produces_artifact="requirement_list_approved",
                agent_name="human_reviewer",
                description=(
                    "Human reviewer inspects the synthesised Requirement List: "
                    "FR / NFR / CON / OOS items, acceptance criteria, traceability links. "
                    "• Approved → requirement_list_approved sentinel written. "
                    "• Rejected → requirement_list removed, requirement_list_feedback injected; "
                    "  synthesis pipeline re-runs with reviewer comments. "
                    "  Note: interview_record is NOT removed — only synthesis re-runs."
                ),
            ),
            # 9a. SprintAgent converts requirements to user stories (Node: sprint_agent_turn)
            ArtifactStep(
                step_name="create_user_stories",
                node_name="sprint_agent_turn",
                requires_artifacts=["requirement_list_approved"],
                produces_artifact="user_story_draft",
                agent_name="sprint_agent",
                description=(
                    "SprintAgent (Product Owner) reads requirement_list_approved and "
                    "converts each confirmed requirement into a user story using the "
                    "mandatory format: 'As a <role>, I can <capability>, so that <benefit>.' "
                    "No estimation occurs at this stage — story points are assigned by "
                    "AnalystAgent in the next step. Any product_backlog_feedback from a "
                    "prior PO rejection is injected so stories are rewritten accordingly."
                ),
            ),
            # 9c. AnalystAgent performs technical estimation and validation (Node: analyst_estimation_turn)
            ArtifactStep(
                step_name="estimate_and_validate_stories",
                node_name="analyst_estimation_turn",
                requires_artifacts=["user_story_draft"],
                produces_artifact="analyst_estimation",
                agent_name="analyst",
                description=(
                    "AnalystAgent (Technical Lead) reads user_story_draft and runs two passes:\n"
                    "  Pass 1 — Feasibility + INVEST + Dependency Mapping:\n"
                    "    Each story is assessed for technical feasibility, INVEST compliance,\n"
                    "    and hidden dependencies. Stories > 8 points after estimation are\n"
                    "    flagged with split_proposals containing concrete sub-story breakdowns.\n"
                    "  Pass 2 — Fibonacci Estimation:\n"
                    "    Complexity (1–5) + Effort (1–5) + Uncertainty (1–5) → mapped to\n"
                    "    nearest Fibonacci number. This is the sole source of story_points\n"
                    "    in the entire pipeline — SprintAgent does not re-estimate.\n"
                    "If split_proposals exist (has_pending_splits=True), SprintAgent creates\n"
                    "sub-stories and calls analyst_estimation_turn again (state.split_round\n"
                    "is incremented; hard limit = 2 rounds to prevent infinite loops).\n"
                    "Output: analyst_estimation artifact with per-story points, INVEST flags,\n"
                    "dependency mapping, risk notes, and any split proposals."
                ),
            ),
            # 9b. SprintAgent runs WSJF + assembly using estimation from Analyst (Node: sprint_agent_turn)
            ArtifactStep(
                step_name="build_product_backlog",
                node_name="sprint_agent_turn",
                requires_artifacts=["user_story_draft", "analyst_estimation"],
                produces_artifact="product_backlog",
                agent_name="sprint_agent",
                description=(
                    "SprintAgent reads both user_story_draft and analyst_estimation, then:\n"
                    "  Pass 2 (WSJF Prioritization):\n"
                    "    Assigns BusinessValue, TimeCriticality, RiskReduction per story.\n"
                    "    Computes WSJF = (BV + TC + RR) / StoryPoints.\n"
                    "    Dependency-aware ranking: if Story A has higher WSJF than Story B\n"
                    "    but A is blocked_by B, Story B is promoted above A in the final rank.\n"
                    "  Pass 3 (Quality Gate + Assembly):\n"
                    "    Validates user story format, snaps non-Fibonacci points, recomputes\n"
                    "    WSJF, and assembles product_backlog using the consolidated PBI schema:\n"
                    "      estimation { story_points, complexity, effort, uncertainty }\n"
                    "      prioritization { priority_rank, wsjf_score, business_value, ... }\n"
                    "      dependencies { blocked_by, blocks }\n"
                    "      planning { status, target_sprint, tags }\n"
                    "      quality { invest_pass, invest_flags, acceptance_criteria: [] }\n"
                    "    enrichment block and top-level INVEST booleans are NOT included.\n"
                    "Any product_backlog_feedback from a prior PO rejection is injected "
                    "into all passes so the backlog is rebuilt with reviewer comments."
                ),
            ),
            # 10. Human reviews product backlog (Node: review_product_backlog_turn)
            ArtifactStep(
                step_name="review_product_backlog",
                node_name="review_product_backlog_turn",
                requires_artifacts=["product_backlog"],
                produces_artifact="product_backlog_approved",
                agent_name="human_reviewer",
                description=(
                    "Product Owner reviews the product backlog (user stories, "
                    "story points, WSJF scores, INVEST flags, dependency map) "
                    "before refinement. "
                    "• Approved → product_backlog_approved sentinel written; "
                    "  flow advances to Backlog Refinement (AC generation). "
                    "• Rejected → product_backlog, user_story_draft, and analyst_estimation "
                    "  removed; product_backlog_feedback injected; SprintAgent re-runs "
                    "  create_user_stories → estimate_and_validate_stories → build_product_backlog."
                ),
            ),
        ],
        next_phase="backlog_refinement",
    ),

    # ── Phase 2: Backlog Refinement ────────────────────────────────────────────
    PhaseDefinition(
        phase_name="backlog_refinement",
        display_name="Backlog Refinement — Acceptance Criteria Generation",
        description=(
            "AnalystAgent writes 2–5 Given-When-Then Acceptance Criteria per PBI, "
            "derived from the user story capability clause and the original requirement "
            "fields (statement, context, rationale, original AC) carried in analyst_estimation. "
            "INVEST validation and story point estimation are already complete from Phase 1 "
            "and are NOT repeated here. "
            "Output: validated_product_backlog — every PBI enriched with AC, status='ready'."
        ),
        steps=[
            ArtifactStep(
                step_name="generate_acceptance_criteria",
                node_name="analyst_turn",
                requires_artifacts=["product_backlog_approved"],
                produces_artifact="validated_product_backlog",
                agent_name="analyst",
                description=(
                    "AnalystAgent runs a single AC-generation pass (Pass 3) against the "
                    "approved product_backlog. For every PBI:\n"
                    "  • Writes 2–5 Given-When-Then criteria (happy_path, edge_case, error_case).\n"
                    "  • Sources: analyst_estimation enrichment data (original statement,\n"
                    "    context, rationale, original AC from elicitation) + user story text.\n"
                    "  • Sets status='ready' for every PBI with AC written.\n"
                    "INVEST and estimation from Phase 1 are preserved unchanged.\n"
                    "Any analyst_feedback from a prior HITL rejection is injected so\n"
                    "AC are rewritten addressing the reviewer's specific comments."
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
                    "  injected; flow returns to generate_acceptance_criteria (AC re-written)."
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