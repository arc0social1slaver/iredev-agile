"""
analyst.py – AnalystAgent  (Technical Lead)

Role
────
The AnalystAgent plays two distinct roles in the pipeline, activated at
different phases:

Phase 1 — analyst_estimation_turn (Steps 9c):
  Acts as Technical Lead / Architect Owner. Receives user_story_draft from
  SprintAgent and runs two passes:

  Pass 1 — Technical Feasibility + INVEST + Dependency Mapping:
    Each story is assessed for technical feasibility, INVEST compliance,
    hidden dependencies, and technical risks. Stories estimated to exceed
    8 story points are flagged with concrete split_proposals.

  Pass 2 — Fibonacci Estimation:
    Complexity (1–5) + Effort (1–5) + Uncertainty (1–5) → nearest Fibonacci.
    This is the SOLE source of story_points in the entire pipeline.
    SprintAgent does not estimate — it only reads these values for WSJF.

  Output: analyst_estimation artifact consumed by SprintAgent for WSJF
  prioritization and dependency-aware assembly.

Phase 2 — analyst_turn (Backlog Refinement Step 1):
  Acts as AC Specialist. Receives product_backlog_approved and writes
  2–5 Given-When-Then Acceptance Criteria per PBI (Pass 3).
  INVEST and estimation are NOT repeated — they were completed in Phase 1.

  Output: validated_product_backlog with every PBI enriched with AC.

Split mechanism
───────────────
When Pass 1 detects a story likely to exceed 8 points:
  • split_proposals lists concrete sub-story breakdowns (title + capability).
  • has_pending_splits=True signals SprintAgent to create sub-stories.
  • SprintAgent increments state["split_round"] and calls analyst_estimation_turn
    again with only the new sub-stories.
  • Hard limit: split_round ≤ 2. After 2 rounds any remaining oversized stories
    are flagged "oversized" in quality_warnings and included as-is.

PBI schema (consolidated — Phase 1 output drives Phase 2)
──────────────────────────────────────────────────────────
analyst_estimation items carry an "enrichment" sub-dict preserving the
original requirement fields (statement, context, rationale, acceptance_criteria,
priority, source_elicitation_id) so Phase 2 AC generation has full traceability
without re-reading the raw requirement list.

State fields
────────────
  artifacts["user_story_draft"]       — source for Phase 1 (read-only)
  artifacts["analyst_estimation"]     — Phase 1 output (consumed by SprintAgent)
  artifacts["product_backlog_approved"] — source for Phase 2 (read-only)
  artifacts["validated_product_backlog"] — Phase 2 output
  analyst_feedback                    — HITL rejection text; triggers Phase 2 re-run
  split_round                         — tracks split loop depth (max 2)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

_INVEST_CRITERIA = ("independent", "negotiable", "valuable", "estimable", "small", "testable")
_FIBONACCI       = {1, 2, 3, 5, 8, 13, 21}
_MAX_AC_PER_PBI  = 5
_SPLIT_THRESHOLD = 8   # story_points > this value triggers mandatory split proposal


# ─────────────────────────────────────────────────────────────────────────────
# Per-pass addendums
# ─────────────────────────────────────────────────────────────────────────────

_PASS1_ADDENDUM = """\
TASK: PASS 1 — TECHNICAL FEASIBILITY + INVEST ASSESSMENT + DEPENDENCY MAPPING

You are the Technical Lead reviewing a list of user stories produced by the
Product Owner. Your job is to assess each story before estimation occurs.

Each story entry contains:
  USER STORY — title, description (As a… / I can… / so that…), domain, type.
  ENRICHMENT — original requirement fields: statement, context, rationale,
               original acceptance criteria, priority, source_elicitation_id.

Use BOTH sections. The enrichment block is the ground truth for scope and intent.

─────────────────────────────────────────────────────
PART A — TECHNICAL FEASIBILITY
─────────────────────────────────────────────────────
For each story, answer:
  1. Is there enough context to implement this? (is_feasible)
  2. Does this conflict with known architectural constraints?
  3. Are there hidden dependencies on other stories or external systems?

is_feasible = false ONLY when the story lacks enough context to begin
implementation. Flag it with a clear feasibility_notes explanation.

─────────────────────────────────────────────────────
PART B — INVEST ASSESSMENT
─────────────────────────────────────────────────────
INVEST CRITERIA

I — Independent
  The story can be delivered without a hard dependency on another specific story.
  If a dependency exists, set independent=false AND record it in blocked_by.

N — Negotiable
  The story does not prescribe implementation detail (library names, frameworks).
  If the description contains implementation prescriptions, set negotiable=false.

V — Valuable
  The benefit clause delivers a clear, observable outcome for the named actor.
  A well-formed user story is always Valuable unless the benefit clause is absent.

E — Estimable
  The team can form a credible, bounded effort estimate from the description.

S — Small
  STRICT RULE: if the estimated story_points (from Pass 2) will exceed 8,
  then Small MUST be false and split_proposals MUST be populated.
  At this pass, use the enrichment context to predict whether the story
  will be large: cross-cutting context, many AC conditions, and broad scope
  are strong signals for large stories.

T — Testable
  The capability clause can be independently verified.
  If there are zero original acceptance_criteria conditions, Testable likely fails.

─────────────────────────────────────────────────────
PART C — DEPENDENCY MAPPING
─────────────────────────────────────────────────────
For each story, identify:
  blocked_by: list of source_req_ids this story cannot start without.
  blocks:     list of source_req_ids that cannot start until this story is done.

Use source_req_id values (e.g. "FR-012") as dependency references.
Only record hard technical dependencies — not soft preferences.

─────────────────────────────────────────────────────
PART D — SPLIT PROPOSALS (when story is predicted large)
─────────────────────────────────────────────────────
Generate split_proposals when ANY of these signals are present:
  • enrichment.context contains "Across all system interactions"
  • enrichment.acceptance_criteria has 4+ conditions
  • The capability clause covers multiple distinct user actions
  • The story spans multiple epics or actor roles

Each sub-story proposal must have:
  title       — short card title (5–8 words)
  capability  — one-line action verb phrase for the split scope
  reasoning   — why this slice is independently deliverable

IMPORTANT: Split proposals are SUGGESTIONS to the Product Owner (SprintAgent).
The actual sub-stories are created by SprintAgent, not by you.

─────────────────────────────────────────────────────
PART E — TECHNICAL RISKS
─────────────────────────────────────────────────────
Flag risks in these categories:
  performance    — keywords: "many", "all", "every", "large scale", "concurrent"
  security       — keywords: "login", "payment", "personal data", "auth"
  integration    — keywords: "external", "third-party", "API", "webhook"
  data           — keywords: "migration", "export", "import", "bulk"
  unknown        — any significant ambiguity in scope or implementation

OUTPUT RULES
  Assess all stories. Do not omit any.
  invest_flags lists only the criteria that FAILED.
  split_proposals is an empty list [] when no split is needed.
  blocked_by and blocks are empty lists [] when no dependency exists.
"""

_PASS2_ADDENDUM = """\
TASK: PASS 2 — FIBONACCI ESTIMATION

You are the Technical Lead assigning effort estimates to user stories.
You receive the Pass 1 assessment results alongside the original story data.

This is the ONLY place in the entire pipeline where story_points are assigned.
SprintAgent does not estimate — it reads your values directly for WSJF scoring.

─────────────────────────────────────────────────────
FIBONACCI ESTIMATION
─────────────────────────────────────────────────────
Assign three independent dimension scores (1–5), then map the sum to Fibonacci.

Complexity (1–5): structural difficulty — algorithms, interacting components.
Effort (1–5):     implementation work — number of files, endpoints, DB changes.
Uncertainty (1–5): unknown factors — ambiguity, external dependencies, newness.

SUM → FIBONACCI MAPPING:
  3–4  → 1    5–6  → 2    7–8  → 3    9–10 → 5
  11–12 → 8   13–14 → 13  15   → 21

─────────────────────────────────────────────────────
CALIBRATION RULES (apply all that match)
─────────────────────────────────────────────────────
• priority="high" → reduce Uncertainty by 1 (stakeholder-critical, well-scrutinised).
• acceptance_criteria count = 0 → raise Uncertainty by 1–2 (no test surface defined).
• acceptance_criteria count ≥ 4 → raise Complexity by 1 (wider test surface).
• context contains "Across all system interactions" → raise Complexity by 1;
  this is a cross-cutting story, Small is likely false.
• context is narrow and names a specific page/trigger → lower Complexity accordingly.
• status="inferred" → raise Uncertainty by at least 1.
• Detailed, specific rationale quote → lower Uncertainty by 1 (well understood need).
• req_type="constraint" → Small is usually true; Independent often false.
• req_type="non_functional" with cross-cutting context → Small is false; Effort ≥ 3.

─────────────────────────────────────────────────────
SPLIT ENFORCEMENT
─────────────────────────────────────────────────────
If story_points > 8 after mapping:
  • Set invest_flags to include "small" (Small MUST be false).
  • Confirm or expand the split_proposals from Pass 1.
  • Set needs_split=true for this story.

If story_points = 8:
  • Add a split_warning note but do NOT force a split.
  • Set needs_split=false.

─────────────────────────────────────────────────────
OUTPUT RULES
─────────────────────────────────────────────────────
Output one entry per story in the same order as the input.
story_points MUST be one of: 1, 2, 3, 5, 8, 13, 21.
Carry forward all Pass 1 fields (feasibility, invest, dependencies, risks).
"""

_PASS3_ADDENDUM = """\
TASK: PASS 3 — ACCEPTANCE CRITERIA GENERATION

You are writing Given-When-Then Acceptance Criteria for an approved Product Backlog.
INVEST assessment and story point estimation are already complete — do NOT redo them.

Each PBI entry contains:
  USER STORY — title, description, domain, type.
  ENRICHMENT — original requirement fields from analyst_estimation:
               statement, context, rationale, original acceptance criteria,
               priority, source_elicitation_id.
  ESTIMATION — story_points, complexity, effort, uncertainty (for context only).
  INVEST     — invest_pass, invest_flags (for context only).

─────────────────────────────────────────────────────
AC GENERATION RULES
─────────────────────────────────────────────────────
Write 2–5 Given-When-Then criteria per PBI.

Source priority order:
  1. enrichment.acceptance_criteria — rewrite each original condition as a
     formal Given-When-Then triple. Do NOT discard or replace them.
  2. enrichment.context and enrichment.rationale — derive additional criteria
     for happy path, edge case, and error scenarios.
  3. The user story capability and benefit clause — confirm coverage.

TYPE RULES:
  happy_path  — at least ONE required. Normal success scenario.
  edge_case   — at least ONE required. Boundary or unusual input.
  error_case  — system failure or invalid input scenario.

For non-functional PBIs:
  The 'then' clause MUST contain a measurable threshold
  (e.g. "response time < 2 seconds", "WCAG 2.1 Level AA").

For constraint PBIs:
  The 'then' clause MUST describe process or compliance adherence.

BANNED words in any AC field:
  easy, clean, intuitive, user-friendly, beautiful, simple, appropriate,
  fast, quickly, seamlessly, properly, correctly (without threshold),
  reasonable, adequate, sufficient.

Each 'then' clause must be independently verifiable with exactly ONE assertion.
Do not include implementation details. Focus on what the system does, not how.

AC ID pattern: AC-{PBI_ID}-01, AC-{PBI_ID}-02, etc.
Example: AC-PBI001-01, AC-PBI001a-01 for split children.

─────────────────────────────────────────────────────
OUTPUT RULES
─────────────────────────────────────────────────────
Output one entry per PBI in the same order as the input.
Preserve all existing fields — only ADD acceptance_criteria and update status.
Set status="ready" for every PBI that receives AC.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 schemas — Feasibility + INVEST + Dependencies
# ─────────────────────────────────────────────────────────────────────────────

class SplitProposal(BaseModel):
    title:      str = Field(description="Short card title for the proposed sub-story (5–8 words).")
    capability: str = Field(description="One-line action verb phrase scoping this sub-story.")
    reasoning:  str = Field(description="Why this slice is independently deliverable.")


class TechnicalRisk(BaseModel):
    category:    Literal["performance", "security", "integration", "data", "unknown"]
    description: str = Field(description="Specific risk identified in this story.")
    level:       Literal["low", "medium", "high", "critical"]
    mitigation:  str = Field(description="Recommended action to address this risk.")


class StoryFeasibilityAssessment(BaseModel):
    source_req_id: str

    # ── Feasibility ──────────────────────────────────────────────────────
    is_feasible:       bool = Field(description="False only when the story lacks enough context to begin implementation.")
    feasibility_notes: str  = Field(description="Why feasible or what is missing. Empty string if fully feasible.")

    # ── INVEST ───────────────────────────────────────────────────────────
    independent: bool
    negotiable:  bool
    valuable:    bool
    estimable:   bool
    small:       bool  # set to false when story is predicted to exceed 8 points
    testable:    bool
    invest_flags: List[str] = Field(
        description="List of INVEST criteria that FAILED (e.g. ['independent', 'small'])."
    )
    invest_notes: str = Field(description="Brief rationale for each failing criterion.")

    # ── Dependencies ─────────────────────────────────────────────────────
    blocked_by: List[str] = Field(
        default_factory=list,
        description="source_req_ids this story cannot start without.",
    )
    blocks: List[str] = Field(
        default_factory=list,
        description="source_req_ids that cannot start until this story is done.",
    )

    # ── Split proposals ───────────────────────────────────────────────────
    split_proposals: List[SplitProposal] = Field(
        default_factory=list,
        description="Proposed sub-story breakdowns when story is predicted large. Empty list if no split needed.",
    )

    # ── Risks ─────────────────────────────────────────────────────────────
    risks: List[TechnicalRisk] = Field(default_factory=list)

    thought: str = Field(description="Overall assessment: key findings and any concerns.")


class FeasibilityAssessmentList(BaseModel):
    assessments: List[StoryFeasibilityAssessment] = Field(
        description="One entry per story, in the same order as the input."
    )
    pass_notes: str = Field(
        description=(
            "2–3 sentence summary: total stories assessed, how many flagged "
            "infeasible, how many have split proposals, dominant dependency patterns."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 schemas — Fibonacci Estimation
# ─────────────────────────────────────────────────────────────────────────────

class StoryEstimation(BaseModel):
    source_req_id: str

    # ── Estimation dimensions ─────────────────────────────────────────────
    complexity:   int = Field(ge=1, le=5, description="Structural complexity (1=trivial, 5=very complex).")
    effort:       int = Field(ge=1, le=5, description="Implementation work (1=minimal, 5=extensive).")
    uncertainty:  int = Field(ge=1, le=5, description="Unknown factors and risk (1=fully understood, 5=highly uncertain).")
    story_points: int = Field(description="Fibonacci value — must be one of 1, 2, 3, 5, 8, 13, 21.")

    # ── Split enforcement ─────────────────────────────────────────────────
    needs_split:   bool = Field(description="True when story_points > 8. Signals SprintAgent to apply split_proposals.")
    split_warning: str  = Field(default="", description="Advisory note when story_points = 8.")

    reasoning: str = Field(description="Calibration signals used and how each dimension was scored.")


class EstimationList(BaseModel):
    estimations: List[StoryEstimation] = Field(
        description="One entry per story, in the same order as the input."
    )
    has_pending_splits: bool = Field(
        description="True if ANY story has needs_split=True. Signals SprintAgent to trigger split loop."
    )
    pass_notes: str = Field(
        description=(
            "2–3 sentence summary: total story points, stories needing splits, "
            "estimation outliers or inferred-status stories flagged."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3 schemas — Acceptance Criteria Generation
# ─────────────────────────────────────────────────────────────────────────────

class AcceptanceCriterion(BaseModel):
    id:    str
    given: str
    when:  str
    then:  str
    type:  Literal["happy_path", "edge_case", "error_case"]


class PbiWithAC(BaseModel):
    # ── Identity (carry forward unchanged) ───────────────────────────────
    pbi_id:        str
    source_req_id: str

    # ── AC written in this pass ───────────────────────────────────────────
    acceptance_criteria: List[AcceptanceCriterion] = Field(
        description="2–5 GWT criteria derived from enrichment + user story."
    )
    status: Literal["ready", "needs_refinement"] = Field(
        description="Set to 'ready' when AC are written. 'needs_refinement' if AC could not be completed."
    )
    thought: str = Field(
        description="How enrichment fields drove the AC — which original conditions were reused vs. inferred."
    )


class AcGenerationList(BaseModel):
    pbis: List[PbiWithAC] = Field(
        description="One entry per PBI, in the same order as the input."
    )
    pass_notes: str = Field(
        description=(
            "2–3 sentence summary: total AC written, any PBIs that could not "
            "receive full AC coverage and why."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# AnalystAgent
# ─────────────────────────────────────────────────────────────────────────────

class AnalystAgent(BaseAgent):
    """
    Technical Lead / AC Specialist agent — deterministic multi-pass pipeline.

    Phase 1 (analyst_estimation_turn — called by graph.py):
      Pass 1: Feasibility + INVEST + Dependency Mapping → FeasibilityAssessmentList
      Pass 2: Fibonacci Estimation → EstimationList
      Assembles analyst_estimation artifact consumed by SprintAgent.

    Phase 2 (analyst_turn — called by graph.py):
      Pass 3: Acceptance Criteria Generation → AcGenerationList
      Assembles validated_product_backlog artifact.

    Architecture mirrors SprintAgent:
      • Profile   : analyst_react.txt — agent identity / persona only.
      • Addendums : _PASS1_ADDENDUM, _PASS2_ADDENDUM, _PASS3_ADDENDUM.
      • No ReAct tools registered; pipeline is pure extract_structured().
    """

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="analyst")

    def _register_tools(self) -> None:
        # Pipeline is pure extract_structured — no ReAct tools needed.
        pass

    # =========================================================================
    # LangGraph node entry points
    # =========================================================================

    def process_estimation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase 1 entry point — called by analyst_estimation_turn_fn in graph.py.

        Runs Pass 1 (Feasibility + INVEST + Dependencies) and
        Pass 2 (Fibonacci Estimation) against user_story_draft.

        Handles both initial estimation and re-estimation of split sub-stories
        (when state["split_round"] > 0, only new sub-stories are estimated).
        """
        artifacts = state.get("artifacts") or {}

        if "analyst_estimation" in artifacts and not (state.get("split_round", 0) > 0):
            logger.warning(
                "[AnalystAgent] process_estimation() called but analyst_estimation "
                "already exists and split_round=0. Supervisor should not have routed here."
            )
            return {}

        return self._run_estimation(state)

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase 2 entry point — called by analyst_turn_fn in graph.py.

        Runs Pass 3 (AC Generation) against product_backlog_approved.
        """
        artifacts = state.get("artifacts") or {}

        if "validated_product_backlog" in artifacts:
            logger.warning(
                "[AnalystAgent] process() called but validated_product_backlog "
                "already exists. Supervisor should not have routed here."
            )
            return {}

        return self._run_ac_generation(state)

    # =========================================================================
    # Phase 1 Pipeline — Estimation
    # =========================================================================

    def _run_estimation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts   = state.get("artifacts") or {}
        draft       = artifacts.get("user_story_draft") or {}
        split_round = state.get("split_round", 0)

        # On split rounds, SprintAgent replaces user_story_draft with sub-stories only.
        stories = draft.get("stories") or []
        feedback = (state.get("product_backlog_feedback") or "").strip()

        if not stories:
            logger.error("[AnalystAgent] user_story_draft has no stories to estimate.")
            return {"errors": ["AnalystAgent: user_story_draft has no stories."]}

        logger.info(
            "[AnalystAgent] Starting estimation pipeline — %d stories (split_round=%d).",
            len(stories), split_round,
        )

        try:
            # ── Pass 1: Feasibility + INVEST + Dependencies ─────────────────
            feasibility = self._pass1_feasibility(stories, feedback)
            logger.info(
                "[AnalystAgent] Pass 1 complete — %d assessed, %d with split proposals.",
                len(feasibility.assessments),
                sum(1 for a in feasibility.assessments if a.split_proposals),
            )

            # ── Pass 2: Fibonacci Estimation ────────────────────────────────
            estimation = self._pass2_estimation(stories, feasibility, feedback)
            logger.info(
                "[AnalystAgent] Pass 2 complete — has_pending_splits=%s.",
                estimation.has_pending_splits,
            )

            # ── Assembly ────────────────────────────────────────────────────
            return self._assemble_estimation_artifact(
                stories, feasibility, estimation, state, feedback
            )

        except Exception as exc:
            logger.error("[AnalystAgent] Estimation pipeline failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent estimation error: {exc}"]}

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 1 — Feasibility + INVEST + Dependencies
    # ─────────────────────────────────────────────────────────────────────────

    def _pass1_feasibility(
        self,
        stories:  List[Dict],
        feedback: str = "",
    ) -> FeasibilityAssessmentList:

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS1_ADDENDUM
            + self._feedback_block(feedback, "feasibility and INVEST assessment")
        )

        story_block = self._format_story_block(stories)

        user_prompt = (
            f"USER STORIES TO ASSESS ({len(stories)} stories):\n\n"
            f"{story_block}\n\n"
            "Assess EVERY story. Provide split_proposals for any story predicted "
            "to exceed 8 story points. Map all dependencies using source_req_id values."
        )

        return self.extract_structured(
            schema=FeasibilityAssessmentList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 2 — Fibonacci Estimation
    # ─────────────────────────────────────────────────────────────────────────

    def _pass2_estimation(
        self,
        stories:     List[Dict],
        feasibility: FeasibilityAssessmentList,
        feedback:    str = "",
    ) -> EstimationList:

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS2_ADDENDUM
            + self._feedback_block(feedback, "Fibonacci estimation")
        )

        story_block       = self._format_story_block(stories)
        feasibility_block = self._format_feasibility_block(feasibility)

        user_prompt = (
            f"ORIGINAL STORIES ({len(stories)} items):\n\n"
            f"{story_block}\n\n"
            f"PASS 1 FEASIBILITY + INVEST RESULTS:\n\n"
            f"{feasibility_block}\n\n"
            f"Pass 1 notes: {feasibility.pass_notes}\n\n"
            "Estimate EVERY story. Output in the same order as the input."
        )

        return self.extract_structured(
            schema=EstimationList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Assembly — analyst_estimation artifact
    # ─────────────────────────────────────────────────────────────────────────

    def _assemble_estimation_artifact(
        self,
        stories:     List[Dict],
        feasibility: FeasibilityAssessmentList,
        estimation:  EstimationList,
        state:       Dict[str, Any],
        feedback:    str = "",
    ) -> Dict[str, Any]:
        """
        Merge Pass 1 and Pass 2 results into the analyst_estimation artifact.

        Each item in analyst_estimation["stories"] carries:
          - All original story fields (title, description, domain, type)
          - feasibility assessment (is_feasible, feasibility_notes)
          - invest results (invest_pass, invest_flags, invest_notes)
          - dependencies (blocked_by, blocks)
          - split_proposals (if any)
          - risks
          - estimation (complexity, effort, uncertainty, story_points)
          - needs_split flag
          - enrichment sub-dict (from original story, for Phase 2 AC generation)
        """
        feasibility_by_id = {a.source_req_id: a for a in feasibility.assessments}
        estimation_by_id  = {e.source_req_id: e for e in estimation.estimations}

        assembled_stories: List[Dict[str, Any]] = []
        total_points = 0
        split_count  = 0

        for story in stories:
            req_id = story.get("source_req_id", "")
            fa     = feasibility_by_id.get(req_id)
            est    = estimation_by_id.get(req_id)

            # Snap story_points to nearest Fibonacci if LLM drifted
            sp = est.story_points if est else 3
            if sp not in _FIBONACCI:
                sp = min(_FIBONACCI, key=lambda f: abs(f - sp))

            invest_flags = fa.invest_flags if fa else []
            invest_pass  = len(invest_flags) == 0

            # A split is only actionable when the story has actual proposals.
            # Without proposals, SprintAgent.process_splits() cannot create
            # sub-stories and would enter an infinite loop.
            has_proposals = bool(fa and fa.split_proposals)
            needs_split = (
                (bool(est and est.needs_split) or (sp > _SPLIT_THRESHOLD))
                and has_proposals
            )
            if needs_split:
                split_count += 1

            assembled_stories.append({
                # ── Identity ──────────────────────────────────────────────
                "source_req_id": req_id,
                "type":          story.get("type", "functional"),
                "domain":        story.get("domain", ""),
                "title":         story.get("title", ""),
                "description":   story.get("description", ""),

                # ── Feasibility ───────────────────────────────────────────
                "feasibility": {
                    "is_feasible":       fa.is_feasible if fa else True,
                    "feasibility_notes": fa.feasibility_notes if fa else "",
                },

                # ── INVEST ────────────────────────────────────────────────
                "invest": {
                    "invest_pass":  invest_pass,
                    "invest_flags": invest_flags,
                    "invest_notes": fa.invest_notes if fa else "",
                },

                # ── Dependencies ──────────────────────────────────────────
                "dependencies": {
                    "blocked_by": fa.blocked_by if fa else [],
                    "blocks":     fa.blocks     if fa else [],
                },

                # ── Split proposals ───────────────────────────────────────
                "split_proposals": [
                    sp_item.model_dump()
                    for sp_item in (fa.split_proposals if fa else [])
                ],
                "needs_split": needs_split,

                # ── Technical risks ───────────────────────────────────────
                "risks": [r.model_dump() for r in (fa.risks if fa else [])],

                # ── Estimation ────────────────────────────────────────────
                "estimation": {
                    "complexity":   est.complexity   if est else 2,
                    "effort":       est.effort       if est else 2,
                    "uncertainty":  est.uncertainty  if est else 2,
                    "story_points": sp,
                    "reasoning":    est.reasoning    if est else "",
                    "split_warning": est.split_warning if est else "",
                },

                # ── Enrichment (preserved for Phase 2 AC generation) ──────
                # Carries original requirement fields so AnalystAgent Pass 3
                # has full traceability without re-reading the requirement list.
                "enrichment": story.get("enrichment") or {},
            })

            total_points += sp

        artifacts = dict(state.get("artifacts") or {})
        split_round = state.get("split_round", 0)

        analyst_estimation: Dict[str, Any] = {
            "id":               str(uuid.uuid4()),
            "session_id":       state.get("session_id", ""),
            "estimated_at":     datetime.now().isoformat(),
            "split_round":      split_round,
            "stories":          assembled_stories,
            # has_pending_splits is only True when at least one story has
            # needs_split=True AND non-empty split_proposals (actionable splits).
            # Without this guard, the split loop may run forever when the LLM
            # estimates sp > 8 but provides no proposals.
            "has_pending_splits": split_count > 0,
            "total_story_points": total_points,
            "estimation_stats": {
                "total_stories":        len(assembled_stories),
                "stories_needing_split": split_count,
                "invest_failures":      sum(1 for s in assembled_stories if not s["invest"]["invest_pass"]),
            },
            "pass_notes": estimation.pass_notes,
            **({"rebuild_feedback": feedback} if feedback else {}),
        }

        artifacts["analyst_estimation"] = analyst_estimation

        logger.info(
            "[AnalystAgent] Estimation artifact assembled — %d stories | %d pts | "
            "has_pending_splits=%s | invest_failures=%d",
            len(assembled_stories),
            total_points,
            analyst_estimation["has_pending_splits"],
            analyst_estimation["estimation_stats"]["invest_failures"],
        )

        return {
            "artifacts":   artifacts,
            "split_round": split_round,
        }

    # =========================================================================
    # Phase 2 Pipeline — AC Generation
    # =========================================================================

    def _run_ac_generation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        backlog   = artifacts.get("product_backlog") or {}
        items     = backlog.get("items") or []
        feedback  = (state.get("analyst_feedback") or "").strip()

        if not items:
            logger.error("[AnalystAgent] product_backlog has no items for AC generation.")
            return {"errors": ["AnalystAgent: product_backlog has no items."]}

        logger.info("[AnalystAgent] Starting AC generation — %d PBIs.", len(items))

        try:
            ac_result = self._pass3_ac_generation(items, feedback)
            logger.info(
                "[AnalystAgent] Pass 3 complete — %d PBIs with AC written.",
                sum(1 for p in ac_result.pbis if p.acceptance_criteria),
            )
            return self._assemble_validated_backlog(ac_result, backlog, state, feedback)

        except Exception as exc:
            logger.error("[AnalystAgent] AC generation failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent AC generation error: {exc}"]}

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 3 — Acceptance Criteria Generation
    # ─────────────────────────────────────────────────────────────────────────

    def _pass3_ac_generation(
        self,
        items:    List[Dict],
        feedback: str = "",
    ) -> AcGenerationList:

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS3_ADDENDUM
            + self._feedback_block(feedback, "acceptance criteria generation")
        )

        pbi_block = self._format_pbi_block_for_ac(items)

        user_prompt = (
            f"PRODUCT BACKLOG TO ENRICH WITH AC ({len(items)} PBIs):\n\n"
            f"{pbi_block}\n\n"
            "Write 2–5 Given-When-Then criteria for EVERY PBI. "
            "Output in the same order as the input."
        )

        return self.extract_structured(
            schema=AcGenerationList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Assembly — validated_product_backlog artifact
    # ─────────────────────────────────────────────────────────────────────────

    def _assemble_validated_backlog(
        self,
        ac_result: AcGenerationList,
        source_pb: Dict[str, Any],
        state:     Dict[str, Any],
        feedback:  str = "",
    ) -> Dict[str, Any]:
        """
        Merge AC results back into a deep copy of product_backlog items.
        Updates status and acceptance_criteria in the quality block.
        All other fields (estimation, prioritization, dependencies, planning)
        are preserved unchanged from product_backlog_approved.
        """
        ac_by_pbi = {p.pbi_id: p for p in ac_result.pbis}

        final_items: List[Dict[str, Any]] = []
        total_ac    = 0
        ready_count = 0

        for item in (source_pb.get("items") or []):
            pbi_id   = item.get("id", "")
            ac_entry = ac_by_pbi.get(pbi_id)

            ac_list: List[Dict] = []
            if ac_entry and ac_entry.acceptance_criteria:
                ac_list = [
                    {
                        "id":    ac.id,
                        "given": ac.given,
                        "when":  ac.when,
                        "then":  ac.then,
                        "type":  ac.type,
                    }
                    for ac in ac_entry.acceptance_criteria
                ]
                total_ac += len(ac_list)

            status = (ac_entry.status if ac_entry else "needs_refinement")
            if status == "ready":
                ready_count += 1

            # Deep copy item and update quality block with AC
            updated_item = {
                **item,
                "quality": {
                    **item.get("quality", {}),
                    "acceptance_criteria": ac_list,
                },
                "planning": {
                    **item.get("planning", {}),
                    "status": status,
                },
            }
            final_items.append(updated_item)

        analyst_feedback = (state.get("analyst_feedback") or "").strip()
        validated_backlog: Dict[str, Any] = {
            **source_pb,
            "items":         final_items,
            "status":        "validated",
            "total_items":   len(final_items),
            "ready_count":   ready_count,
            "refinement_stats": {
                "total_pbis":  len(final_items),
                "ready_count": ready_count,
                "total_ac":    total_ac,
            },
            "refinement_summary": ac_result.pass_notes,
            "validated_at":       datetime.now().isoformat(),
            **({"rebuild_feedback": analyst_feedback} if analyst_feedback else {}),
        }

        artifacts = dict(state.get("artifacts") or {})
        artifacts["validated_product_backlog"] = validated_backlog

        logger.info(
            "[AnalystAgent] Validated backlog assembled — %d PBIs | ready=%d | total_ac=%d",
            len(final_items), ready_count, total_ac,
        )

        return {"artifacts": artifacts}

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _format_story_block(stories: List[Dict]) -> str:
        """Render user stories with enrichment for LLM prompts (Pass 1 + Pass 2)."""
        lines: List[str] = []
        for story in stories:
            req_id = story.get("source_req_id", "?")
            block  = (
                f"[{req_id}]  type={story.get('type', '?')}  domain={story.get('domain', '?')}\n"
                f"  Title      : {story.get('title', '')}\n"
                f"  User Story : {story.get('description', '')}\n"
            )
            enr = story.get("enrichment") or {}
            if enr.get("statement"):
                block += f"  Orig Statement : {enr['statement']}\n"
            if enr.get("context"):
                block += f"  Orig Context   : {enr['context']}\n"
            if enr.get("rationale"):
                rat = enr["rationale"]
                block += f"  Orig Rationale : {rat[:300]}{'…' if len(rat) > 300 else ''}\n"
            orig_acs = enr.get("acceptance_criteria") or []
            if orig_acs:
                for i, ac in enumerate(orig_acs, 1):
                    block += f"  Orig AC[{i}]     : {ac}\n"
            else:
                block += "  Orig AC        : (none)\n"
            if enr.get("priority"):
                block += f"  Priority       : {enr['priority']}\n"
            if enr.get("source_elicitation_id"):
                block += f"  Elicitation ID : {enr['source_elicitation_id']}\n"
            lines.append(block)
        return "\n".join(lines)

    @staticmethod
    def _format_feasibility_block(feasibility: FeasibilityAssessmentList) -> str:
        """Render Pass 1 feasibility results compactly for the Pass 2 prompt."""
        lines: List[str] = []
        for a in feasibility.assessments:
            block = (
                f"[{a.source_req_id}]  feasible={a.is_feasible}  "
                f"invest_flags={a.invest_flags or 'none'}\n"
                f"  thought: {a.thought}\n"
            )
            if not a.is_feasible:
                block += f"  feasibility_notes: {a.feasibility_notes}\n"
            if a.blocked_by:
                block += f"  blocked_by: {a.blocked_by}\n"
            if a.split_proposals:
                block += f"  split_proposals: {len(a.split_proposals)} proposed\n"
                for sp in a.split_proposals:
                    block += f"    → {sp.title}: {sp.capability}\n"
            lines.append(block)
        return "\n".join(lines)

    @staticmethod
    def _format_pbi_block_for_ac(items: List[Dict]) -> str:
        """Render PBIs with enrichment for Pass 3 AC generation."""
        lines: List[str] = []
        for item in items:
            pbi_id = item.get("id", "?")
            qual   = item.get("quality") or {}
            est    = item.get("estimation") or {}
            enr    = item.get("enrichment") or {}

            block = (
                f"[{pbi_id}]  source_req_id={item.get('source_req_id', '?')}  "
                f"type={item.get('type', '?')}  pts={est.get('story_points', '?')}\n"
                f"  Title      : {item.get('title', '')}\n"
                f"  User Story : {item.get('description', '')}\n"
                f"  INVEST     : pass={qual.get('invest_pass', True)}  "
                f"flags={qual.get('invest_flags') or 'none'}\n"
            )
            if enr.get("statement"):
                block += f"  Orig Statement : {enr['statement']}\n"
            if enr.get("context"):
                block += f"  Orig Context   : {enr['context']}\n"
            if enr.get("rationale"):
                rat = enr["rationale"]
                block += f"  Orig Rationale : {rat[:300]}{'…' if len(rat) > 300 else ''}\n"
            orig_acs = enr.get("acceptance_criteria") or []
            if orig_acs:
                for i, ac in enumerate(orig_acs, 1):
                    block += f"  Orig AC[{i}]     : {ac}\n"
            else:
                block += "  Orig AC        : (none)\n"
            lines.append(block)
        return "\n".join(lines)

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        """Render a reviewer feedback constraint block for injection into system prompts."""
        if not feedback:
            return ""
        return (
            f"\n\n{'━'*12} REVIEWER FEEDBACK — previous output was REJECTED {'━'*12}\n"
            f"{feedback}\n"
            f"You MUST address ALL points above when performing {context}.\n"
            f"{'━'*70}\n"
        )