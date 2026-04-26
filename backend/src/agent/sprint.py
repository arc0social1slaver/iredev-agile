"""
sprint.py – SprintAgent  (Sprint Zero: Build Product Backlog)

Role
────
SprintAgent runs once after the Requirement List is approved by the human
reviewer.  It converts every approved, confirmed requirement into a User Story
and assembles the initial Product Backlog.

Source artifact
───────────────
Reads from: artifacts["requirement_list_approved"]
  The structured Requirement List produced by InterviewerAgent's 4-pass SRS
  synthesis and approved at the review_requirement_list_turn HITL gate.

Fallback:   artifacts["requirement_list"]
  Used when rebuilding after a Product Owner rejection (backlog deleted, but
  the requirement list is still approved).

Profile + Addendum pattern
──────────────────────────
Sprint Agent follows the same separation as InterviewerAgent:

  self.profile.prompt            → who the agent is (sprint_agent_react.txt)
  _PASS1_ADDENDUM … _PASS3_ADDENDUM  → what to do per pipeline pass

  Each extract_structured() call receives:
    system_prompt = self.profile.prompt + "\\n\\n" + _PASSN_ADDENDUM [+ feedback]
    user_prompt   = rich requirement/story block built from ALL available fields

  The profile never contains per-task rules.  Rules live here, in the addendums.

4-Pass Pipeline
────────────────────────────────────────────────────────────────────────────
Each pass is a deterministic extract_structured() call — no ReAct loop,
no LLM tool routing.  Passes run sequentially; each receives the prior
pass's output.

  Pass 1 — Story Generation (extract_structured → UserStoryList):
    Input:  confirmed requirements (all fields) + project_description
    Output: One user story per requirement.
    Rules:  Role ← stakeholder.  Capability ← statement + context.
            Benefit ← rationale "So that…" clause.
            status="excluded" items → skipped before this pass.

  Pass 2 — Estimation (extract_structured → EstimatedStoryList):
    Input:  UserStoryList from Pass 1 + rich requirement context
    Output: Each story enriched with Complexity/Effort/Uncertainty → Fibonacci
            story_points and per-criterion INVEST evaluation (true/false).
    Signals: priority, AC count, context breadth, status="inferred" → +1 uncertainty.

  Pass 3 — Prioritization (extract_structured → PrioritizedBacklog):
    Input:  EstimatedStoryList from Pass 2 + project_description
    Output: Each story enriched with BusinessValue/TimeCriticality/RiskReduction,
            computed WSJF score, and unique priority_rank (1 = highest).
    Signals: priority field, epic clustering, stakeholder, rationale richness.

  Pass 4 — Quality Gate + Assembly (deterministic — no LLM call):
    Input:  PrioritizedBacklog from Pass 3 + session metadata
    Output: product_backlog artifact written to state["artifacts"].
    Checks: user story format, Fibonacci validity (snaps if off),
            WSJF recompute, INVEST failure tagging, duplicate source_req_id.
            All failures → quality_warnings block — NEVER silently dropped.

Rejection handling
──────────────────
If product_backlog_feedback exists in state, it is injected as a constraint
block at the end of every pass's system_prompt.  All 4 passes re-run from
scratch on re-entry.

State fields used
─────────────────
  artifacts                 — source (requirement_list_approved) + output (product_backlog)
  project_description       — project context injected into Passes 1 and 3
  product_backlog_feedback  — injected on PO rejection; cleared on next approval
  session_id                — stamped on artifact
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

_FIBONACCI = {1, 2, 3, 5, 8, 13, 21}
_INVEST_CRITERIA = ["independent", "negotiable", "valuable", "estimable", "small", "testable"]

# Fibonacci snap table: dimension total (3-15) → nearest Fibonacci
_TOTAL_TO_FIB: Dict[int, int] = {
    3: 1, 4: 1,
    5: 2, 6: 2,
    7: 3, 8: 3,
    9: 5, 10: 5,
    11: 8, 12: 8,
    13: 13, 14: 13,
    15: 21,
}


# ─────────────────────────────────────────────────────────────────────────────
# Per-pass addendums  (injected after self.profile.prompt in every LLM call)
# ─────────────────────────────────────────────────────────────────────────────

_PASS1_ADDENDUM = """\
TASK: PASS 1 - USER STORY GENERATION

Convert each active requirement into exactly one user story.
The mandatory format is: "As a <role>, I can <capability>, so that <benefit>."

ROLE

Read the stakeholder field and use its value as the role.  If the value is
plural, convert it to singular: "Students" becomes "a Student", "Teachers"
becomes "a Teacher".  If the value is already singular such as "First-year
Student", use it without modification.

CAPABILITY

Strip the SHALL or SHALL NOT modal from the statement and rephrase the remainder
as a present-tense action verb phrase.  Then narrow it using the context field
to make the scene specific and concrete.  Never leave the capability as a plain
restatement of the statement.

Example: statement "SHALL provide guidance on responsible AI use" combined with
context "On the Responsible AI Use guidance page, when a student views the rules"
produces the capability "view clear responsible-AI rules on a dedicated guidance
page".

When priority is "high", the capability clause must be precise and scene-specific.
No vague verbs are acceptable.  When priority is "medium", apply standard
precision.  When priority is "low", keep the capability concise and open the
thought field with the prefix "low-urgency:".

BENEFIT

Extract the "So that" clause from the rationale field and rephrase it as a
measurable outcome for the named actor.  When the rationale field is absent or
contains no "So that" clause, derive the benefit from the acceptance_criteria
conditions instead.

STATUS

When status is "excluded", skip the item entirely.  Produce no story and leave
no placeholder in the output list.
When status is "inferred", include the story and open the thought field with the
prefix "inferred:".

TRACEABILITY

Copy req_id verbatim into source_req_id.
Copy epic verbatim into domain.
Record source_elicitation_id in the thought field as the traceability note.
Output stories in the same order as the input requirements.
"""

_PASS2_ADDENDUM = """\
TASK: PASS 2 - FIBONACCI ESTIMATION AND INVEST EVALUATION

Score every user story received from Pass 1.
Carry forward source_req_id, source_type, title, description, and domain
unchanged.

FIBONACCI ESTIMATION

Assign three independent dimension scores from 1 to 5, then sum them and map
the total to the nearest Fibonacci number.

Complexity measures structural difficulty: 1 is trivial, 5 is very complex
architecture with many interacting components.
Effort measures implementation work: 1 is minimal, 5 is extensive implementation
or integration work.
Uncertainty measures unknown factors and risk: 1 is fully understood, 5 is high
unknowns with no precedent.

Map the summed total to story points as follows.
A total of 3 or 4 maps to 1 point.
A total of 5 or 6 maps to 2 points.
A total of 7 or 8 maps to 3 points.
A total of 9 or 10 maps to 5 points.
A total of 11 or 12 maps to 8 points.
A total of 13 or 14 maps to 13 points.
A total of 15 maps to 21 points.

CALIBRATION RULES

Read the following requirement fields to set each score correctly.

When priority is "high", the need is stakeholder-critical and well-scrutinised.
Reduce Uncertainty by one point relative to a neutral baseline.

When the acceptance_criteria list is empty, set Testable to false and raise
Uncertainty by one to two points.  When there is one condition, apply a neutral
baseline.  When there are two or more conditions, raise Complexity by one point
to account for the wider test surface.

When context contains the phrase "Across all system interactions", the scope is
cross-cutting.  Raise Complexity by one point and treat Small as a risk rather
than a certainty.  When context is narrow and names a specific page or scene,
lower Complexity accordingly and treat Small as likely true.

When status is "inferred", raise Uncertainty by at least one point because the
requirement was not directly validated by a stakeholder.

When the rationale field contains a long, specific stakeholder quote, the need
is well understood.  Reduce Uncertainty by one point.

When req_type is "constraint", treat Small as true in most cases and treat
Independent as false if the story depends on the content pipeline.

When req_type is "non_functional" and context is "Across all system
interactions", set Small to false because the story is cross-cutting, and set
Effort to at least 3.

INVEST EVALUATION

Evaluate each criterion as true or false.  Never inflate a score.

Independent is true when the story has no hard dependency on another specific
story.
Negotiable is true when the scope or implementation approach can be refined
during sprint planning.
Valuable is true when the story delivers a clear, measurable benefit to the
named actor identified in the stakeholder and rationale fields.
Estimable is true when the team can form a credible, bounded effort estimate.
Small is true when the story can be completed within one sprint of one week or
less of team work.
Testable is true when the acceptance_criteria field contains clear binary
pass-or-fail conditions.
"""

_PASS3_ADDENDUM = """\
TASK: PASS 3 - WSJF PRIORITIZATION AND UNIQUE RANKING

Assign WSJF scores and unique priority ranks to all stories received from
Pass 2.  Carry forward all Pass 2 fields unchanged.  Do not re-estimate.

WSJF FORMULA

Compute WSJF as (BusinessValue + TimeCriticality + RiskReduction) divided by
StoryPoints.  Round the result to two decimal places.  A higher WSJF score
means higher priority, which means a lower rank number.

SCORING DIMENSIONS

Score each dimension as an integer from 1 to 10.

BusinessValue measures the economic or user benefit delivered now versus
delaying one sprint.
TimeCriticality measures the cost of delay: how much the project suffers if
this story slips one sprint.
RiskReduction measures the degree to which delivering this story removes a
technical or business blocker.

CALIBRATION RULES

Read the following requirement fields to set each score correctly.

When priority is "high", set BusinessValue to 7 or above and TimeCriticality
to 6 or above.
When priority is "medium", set BusinessValue between 4 and 7.
When priority is "low", set BusinessValue to 4 or below.

When stories share the same epic, their BusinessValue scores must be internally
consistent.  The foundational epic that delivers user-facing content ranks above
supporting epics such as educator resources or system administration.

When context contains the phrase "Across all system interactions", the story is
cross-cutting.  Raise RiskReduction because deferring a cross-cutting story
blocks or degrades multiple epics simultaneously.  When context is narrow and
names a specific page or scene, apply a lower RiskReduction unless the
stakeholder and priority fields identify the story as a user-critical path.

When the stakeholder is "Project Team" on a constraint item, weight
RiskReduction upward to account for compliance or academic-integrity exposure.

When the rationale field contains a rich, specific "So that" clause, raise
BusinessValue to reflect the well-articulated stakeholder benefit.

When source_elicitation_id is "PD", the item was inferred from the project
description rather than elicited directly from a stakeholder.  Apply a modest
reduction to TimeCriticality to reflect the lower confidence.

When the acceptance_criteria list is empty, the story is harder to demo.
Reduce TimeCriticality until the criteria are refined.

When status is "inferred", the higher Uncertainty is already reflected in
StoryPoints.  Do not inflate BusinessValue.

When req_type is "non_functional", weight TimeCriticality based on what breaks
or degrades if the quality attribute is deferred.

When req_type is "constraint", weight BusinessValue based on the compliance or
legal exposure avoided by delivering the story.

RANKING RULES

Assign priority_rank as unique integers starting at 1, where 1 is the highest
priority.  When two stories have the same WSJF score, break the tie by giving
the lower rank number to the story with the higher BusinessValue.  Output all
stories ordered by priority_rank ascending so that rank 1 appears first.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 schemas — Story Generation
# ─────────────────────────────────────────────────────────────────────────────

class UserStoryItem(BaseModel):
    source_req_id: str = Field(
        description="Copied verbatim from the requirement's req_id field (e.g. 'FR-001', 'NFR-003', 'CON-001')."
    )
    source_type: Literal["functional", "non_functional", "constraint"] = Field(
        description="Requirement type — copied verbatim from req_type."
    )
    title: str = Field(
        description=(
            "Short backlog card title (5–8 words). Names the core action, not the actor. "
            "Example: 'View Responsible AI Use Rules'."
        )
    )
    description: str = Field(
        description=(
            "MANDATORY USER STORY FORMAT: "
            "'As a <role>, I can <capability>, so that <benefit>.' "
            "Role = named actor from stakeholder field. "
            "Capability = action verb present tense, narrowed by context. "
            "Benefit = measurable outcome from rationale 'So that…' clause."
        )
    )
    domain: str = Field(
        description="Epic area this story belongs to — copied verbatim from the requirement's `epic` field."
    )
    thought: str = Field(
        description=(
            "1–2 sentence rationale: why this role was chosen (from stakeholder field), "
            "how the capability maps to statement+context, "
            "what 'so that' benefit captures from rationale."
        )
    )


class UserStoryList(BaseModel):
    stories: List[UserStoryItem] = Field(
        description=(
            "One user story per confirmed requirement, in the same order as the input list. "
            "Requirements with status='excluded' are absent — do not create a placeholder."
        )
    )
    pass_notes: str = Field(
        description=(
            "2–3 sentence summary: total stories generated, how many excluded items were "
            "skipped, any ambiguous requirements and the formulation decisions made."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 schemas — Estimation
# ─────────────────────────────────────────────────────────────────────────────

class EstimatedStoryItem(BaseModel):
    # ── Carry-forward from Pass 1 ──────────────────────────────────────────
    source_req_id: str
    source_type:   Literal["functional", "non_functional", "constraint"]
    title:         str
    description:   str  # user story text — carry forward unchanged
    domain:        str

    # ── Estimation ─────────────────────────────────────────────────────────
    complexity:   int = Field(ge=1, le=5, description="Structural complexity (1=trivial, 5=very complex).")
    effort:       int = Field(ge=1, le=5, description="Implementation work required (1=minimal, 5=extensive).")
    uncertainty:  int = Field(ge=1, le=5, description="Unknown factors and risk (1=fully understood, 5=highly uncertain).")
    story_points: int = Field(
        description=(
            "Fibonacci story points — MUST be one of: 1, 2, 3, 5, 8, 13, 21. "
            "Derived from (complexity + effort + uncertainty) mapped to nearest Fibonacci: "
            "3–4→1, 5–6→2, 7–8→3, 9–10→5, 11–12→8, 13–14→13, 15→21."
        )
    )

    # ── INVEST evaluation ──────────────────────────────────────────────────
    independent:  bool = Field(description="Deliverable without a hard dependency on another specific story.")
    negotiable:   bool = Field(description="Scope or implementation approach can be refined during sprint planning.")
    valuable:     bool = Field(description="Delivers clear, measurable value to a named actor.")
    estimable:    bool = Field(description="Team can form a credible, bounded effort estimate.")
    small:        bool = Field(description="Completable within one sprint (≤ 1 week of team work).")
    testable:     bool = Field(description="Has clear, binary pass/fail acceptance conditions.")

    thought: str = Field(
        description=(
            "1–2 sentence rationale: calibration signals used (priority, AC count, context breadth, "
            "status), and which INVEST criteria are false and why."
        )
    )


class EstimatedStoryList(BaseModel):
    stories:    List[EstimatedStoryItem]
    pass_notes: str = Field(
        description=(
            "Summary of Pass 2: total story points, how many stories have INVEST failures, "
            "any estimation challenges, outliers, or inferred-status stories flagged."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pass 3 schemas — Prioritization
# ─────────────────────────────────────────────────────────────────────────────

class PrioritizedStoryItem(BaseModel):
    # ── Carry-forward from Pass 2 ──────────────────────────────────────────
    source_req_id: str
    source_type:   Literal["functional", "non_functional", "constraint"]
    title:         str
    description:   str
    domain:        str
    complexity:    int
    effort:        int
    uncertainty:   int
    story_points:  int
    independent:   bool
    negotiable:    bool
    valuable:      bool
    estimable:     bool
    small:         bool
    testable:      bool

    # ── WSJF scoring ───────────────────────────────────────────────────────
    business_value:   int = Field(ge=1, le=10, description="Economic/user benefit if delivered now (1=low, 10=critical).")
    time_criticality: int = Field(ge=1, le=10, description="Penalty for delaying one sprint (1=anytime, 10=must-do-first).")
    risk_reduction:   int = Field(ge=1, le=10, description="Risk or blocker removed by delivering (1=none, 10=critical blocker).")
    wsjf_score:      float = Field(
        description=(
            "Computed as (business_value + time_criticality + risk_reduction) / story_points. "
            "Round to 2 decimal places."
        )
    )
    priority_rank: int = Field(
        description=(
            "Rank by WSJF descending. 1 = highest priority. "
            "Ranks MUST be unique — break ties using business_value."
        )
    )
    thought: str = Field(
        description=(
            "Rationale for BV/TC/RR scores: which requirement fields drove each score "
            "(priority, epic, rationale, AC count, stakeholder, source_elicitation_id) "
            "and why this story ranks where it does relative to peers in the same epic."
        )
    )


class PrioritizedBacklog(BaseModel):
    stories:    List[PrioritizedStoryItem] = Field(
        description="All stories ordered by priority_rank ascending (rank 1 = first story in list)."
    )
    pass_notes: str = Field(
        description=(
            "Summary of Pass 3: ranking rationale, high-priority clusters by epic, "
            "any tied WSJF scores and how ties were broken."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# SprintAgent
# ─────────────────────────────────────────────────────────────────────────────

class SprintAgent(BaseAgent):
    """
    Builds the initial product backlog from an approved Requirement List.

    Architecture
    ────────────
    • Profile   : sprint_agent_react.txt — agent identity and input-field contract.
    • Addendums : _PASS1_ADDENDUM … _PASS3_ADDENDUM — per-pass task instructions.
    • Each LLM call:  system_prompt = self.profile.prompt + "\\n\\n" + _PASSn_ADDENDUM
    • Pipeline   : 4 deterministic extract_structured() calls — no ReAct loop.
    • Tools dict : empty (no tool routing needed).
    """

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="sprint_agent")

    def _register_tools(self) -> None:
        # SprintAgent pipeline is pure extract_structured — no ReAct tools.
        pass

    # =========================================================================
    # LangGraph node entry point
    # =========================================================================

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        LangGraph node entry point — called by sprint_agent_turn_fn in graph.py.

        Guards against double-execution (supervisor should not re-route here if
        product_backlog already exists and no feedback is pending).
        """
        artifacts = state.get("artifacts") or {}
        feedback  = (state.get("product_backlog_feedback") or "").strip()

        if "product_backlog" in artifacts and not feedback:
            logger.warning(
                "[SprintAgent] process() called but product_backlog already exists "
                "and no feedback is pending. Supervisor should not have routed here."
            )
            return {}

        return self._build_product_backlog(state)

    # =========================================================================
    # 4-Pass Pipeline
    # =========================================================================

    def _build_product_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Run the 4-pass pipeline and return a state update with product_backlog."""
        artifacts    = state.get("artifacts") or {}
        project_desc = state.get("project_description", "")
        po_feedback  = (state.get("product_backlog_feedback") or "").strip()

        # ── Source artifact ─────────────────────────────────────────────────
        req_list = (
            artifacts.get("requirement_list_approved")
            or artifacts.get("requirement_list")
            or {}
        )
        all_requirements  = self._extract_all_requirements(req_list)
        active_requirements = [
            r for r in all_requirements
            if r.get("status", "confirmed") != "excluded"
            and r.get("req_type", r.get("type", "")) != "out_of_scope"
        ]

        if not active_requirements:
            logger.error("[SprintAgent] No active requirements found in requirement_list.")
            return {"errors": ["SprintAgent: requirement_list has no confirmed/inferred requirements."]}

        logger.info(
            "[SprintAgent] Starting 4-pass pipeline — %d active requirements "
            "(%d total, %d excluded/OOS)  feedback=%s",
            len(active_requirements),
            len(all_requirements),
            len(all_requirements) - len(active_requirements),
            bool(po_feedback),
        )

        try:
            # ── Pass 1: Story Generation ────────────────────────────────────
            story_list = self._pass1_story_generation(
                active_requirements, project_desc, po_feedback
            )
            logger.info(
                "[SprintAgent] Pass 1 complete — %d stories generated.",
                len(story_list.stories),
            )

            # ── Pass 2: Estimation ──────────────────────────────────────────
            estimated_list = self._pass2_estimation(
                story_list, active_requirements, po_feedback
            )
            logger.info("[SprintAgent] Pass 2 complete — estimation done.")

            # ── Pass 3: Prioritization ──────────────────────────────────────
            prioritized = self._pass3_prioritization(
                estimated_list, project_desc, active_requirements, po_feedback
            )
            logger.info(
                "[SprintAgent] Pass 3 complete — %d stories ranked.",
                len(prioritized.stories),
            )

            # ── Pass 4: Quality Gate + Assembly ─────────────────────────────
            return self._pass4_quality_gate(
                prioritized, state, po_feedback, active_requirements
            )

        except Exception as exc:
            logger.error("[SprintAgent] Pipeline failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent pipeline error: {exc}"]}

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 1 — Story Generation
    # ─────────────────────────────────────────────────────────────────────────

    def _pass1_story_generation(
        self,
        requirements: List[Dict],
        project_desc: str,
        feedback:     str = "",
    ) -> UserStoryList:
        """Convert confirmed requirements to user stories using all rich fields."""

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS1_ADDENDUM
            + self._feedback_block(feedback, "user story formulation")
        )

        user_prompt = (
            f"PROJECT CONTEXT:\n{project_desc or '(not provided)'}\n\n"
            f"REQUIREMENTS TO CONVERT ({len(requirements)} items):\n\n"
            f"{self._format_requirements_block(requirements)}\n\n"
            "Generate exactly ONE User Story for EVERY requirement listed above.\n"
            "Preserve input order.  Requirements with status='excluded' have already "
            "been removed — do not create empty slots."
        )

        return self.extract_structured(
            schema=UserStoryList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 2 — Estimation
    # ─────────────────────────────────────────────────────────────────────────

    def _pass2_estimation(
        self,
        story_list:   UserStoryList,
        requirements: List[Dict],
        feedback:     str = "",
    ) -> EstimatedStoryList:
        """Score each story with Fibonacci estimation + INVEST evaluation."""

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS2_ADDENDUM
            + self._feedback_block(feedback, "estimation and INVEST scoring")
        )

        # ── Stories block ────────────────────────────────────────────────────
        stories_block = "\n".join(
            f"[{i+1}] source_req_id={s.source_req_id}  type={s.source_type}  domain={s.domain}\n"
            f"       title:       {s.title}\n"
            f"       description: {s.description}\n"
            for i, s in enumerate(story_list.stories)
        )

        # ── Calibration signals block (built from requirement fields) ─────────
        req_lookup: Dict[str, Dict] = {
            (r.get("req_id") or r.get("id", "")): r for r in requirements
        }
        signal_lines: List[str] = []
        for s in story_list.stories:
            r       = req_lookup.get(s.source_req_id, {})
            acs     = r.get("acceptance_criteria") or []
            ac_cnt  = len(acs) if isinstance(acs, list) else 0
            context = (r.get("context") or "").lower()
            broad   = "across all system interactions" in context or not context
            signal_lines.append(
                f"  {s.source_req_id}: "
                f"priority={r.get('priority', '?')}  "
                f"status={r.get('status', 'confirmed')}  "
                f"ac_count={ac_cnt}  "
                f"context_breadth={'broad (cross-cutting)' if broad else 'narrow (scoped)'}  "
                f"elicit_id={r.get('source_elicitation_id', '?')}"
            )

        user_prompt = (
            f"USER STORIES TO ESTIMATE ({len(story_list.stories)} items):\n\n"
            f"{stories_block}\n"
            f"CALIBRATION SIGNALS (from requirement fields):\n"
            + "\n".join(signal_lines)
            + f"\n\nPass 1 notes: {story_list.pass_notes}\n\n"
            "Score EVERY story.  Output in the same order as the input."
        )

        return self.extract_structured(
            schema=EstimatedStoryList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 3 — Prioritization (WSJF)
    # ─────────────────────────────────────────────────────────────────────────

    def _pass3_prioritization(
        self,
        estimated_list: EstimatedStoryList,
        project_desc:   str,
        requirements:   List[Dict],
        feedback:       str = "",
    ) -> PrioritizedBacklog:
        """Compute WSJF scores and assign unique priority ranks."""

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS3_ADDENDUM
            + self._feedback_block(feedback, "WSJF prioritization and ranking")
        )

        # ── Stories block ────────────────────────────────────────────────────
        stories_block = "\n".join(
            f"[{i+1}] source_req_id={s.source_req_id}  pts={s.story_points}  "
            f"type={s.source_type}  domain={s.domain}\n"
            f"       title:       {s.title}\n"
            f"       description: {s.description}\n"
            f"       INVEST fails: {[c for c in _INVEST_CRITERIA if not getattr(s, c, True)] or 'none'}\n"
            for i, s in enumerate(estimated_list.stories)
        )

        # ── Priority signals block ────────────────────────────────────────────
        req_lookup: Dict[str, Dict] = {
            (r.get("req_id") or r.get("id", "")): r for r in requirements
        }
        signal_lines: List[str] = []
        for s in estimated_list.stories:
            r         = req_lookup.get(s.source_req_id, {})
            rationale = (r.get("rationale") or "")
            so_that   = ""
            if "so that" in rationale.lower():
                so_that = rationale[rationale.lower().index("so that"):][:120]
            context     = (r.get("context") or "").lower()
            ctx_breadth = (
                "broad (cross-cutting)"
                if "across all system interactions" in context or not context
                else "narrow (scoped)"
            )
            signal_lines.append(
                f"  {s.source_req_id}: "
                f"priority={r.get('priority', '?')}  "
                f"stakeholder={r.get('stakeholder', '?')}  "
                f"elicit_id={r.get('source_elicitation_id', '?')}  "
                f"status={r.get('status', 'confirmed')}  "
                f"context_breadth={ctx_breadth}  "
                + (f'so_that="{so_that}"' if so_that else "so_that=(absent)")
            )

        user_prompt = (
            f"PROJECT CONTEXT:\n{project_desc or '(not provided)'}\n\n"
            f"ESTIMATED STORIES ({len(estimated_list.stories)} items):\n\n"
            f"{stories_block}\n"
            f"PRIORITY SIGNALS (from requirement fields):\n"
            + "\n".join(signal_lines)
            + f"\n\nEstimation pass notes: {estimated_list.pass_notes}\n\n"
            "Assign WSJF scores and unique ranks for ALL stories.\n"
            "Output stories ordered by priority_rank ascending (rank 1 first)."
        )

        return self.extract_structured(
            schema=PrioritizedBacklog,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 4 — Quality Gate + Assembly  (no LLM call)
    # ─────────────────────────────────────────────────────────────────────────

    def _pass4_quality_gate(
        self,
        prioritized:        PrioritizedBacklog,
        state:              Dict[str, Any],
        feedback:           str = "",
        active_requirements: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Validate every story from Pass 3, snap any bad values, assemble the
        final product_backlog artifact, and write it to state["artifacts"].

        Quality checks (deterministic — no LLM):
          • User story format: must start with "As a/an" and contain ", I can" + ", so that".
          • story_points: must be Fibonacci. Invalid values are snapped and logged.
          • WSJF: recomputed from raw scores (guards against LLM rounding drift).
          • INVEST: failed criteria collected per story; ≥3 failures → invest_failed.
          • source_req_id uniqueness: duplicate IDs logged as warnings.

        Enrichment:
          Each PBI receives an 'enrichment' sub-dict with the key fields from the
          original requirement (statement, context, rationale, acceptance_criteria,
          priority, source_elicitation_id).  This lets AnalystAgent perform
          high-quality refinement without needing access to the raw requirement list.
        """
        items:           List[Dict[str, Any]] = []
        invest_warnings: List[str]            = []
        format_warnings: List[str]            = []
        fib_warnings:    List[str]            = []
        seen_req_ids:    Dict[str, int]        = {}

        # Build a lookup map from req_id → full requirement dict so Pass 4
        # can embed enrichment without another LLM call.
        req_map: Dict[str, Dict] = {}
        for r in (active_requirements or []):
            key = r.get("req_id") or r.get("id", "")
            if key:
                req_map[key] = r

        ordered = sorted(prioritized.stories, key=lambda s: s.priority_rank)

        for pbi_idx, story in enumerate(ordered, start=1):

            # ── Duplicate source_req_id detection ─────────────────────────
            rid = story.source_req_id
            if rid in seen_req_ids:
                format_warnings.append(
                    f"PBI-{pbi_idx:03d}: duplicate source_req_id '{rid}' "
                    f"(first seen at PBI-{seen_req_ids[rid]:03d})."
                )
            seen_req_ids[rid] = pbi_idx

            # ── User story format check ────────────────────────────────────
            # Role always comes from the stakeholder field, which is always a
            # named human actor.  Valid openings are "As a" and "As an" only.
            # "As the system" is never valid output from this pipeline.
            desc     = story.description.strip()
            desc_low = desc.lower()
            format_ok = (
                (desc_low.startswith("as a ") or desc_low.startswith("as an "))
                and ", i can " in desc_low
                and ", so that " in desc_low
            )
            if not format_ok:
                format_warnings.append(
                    f"PBI-{pbi_idx:03d} [{rid}]: description does not match "
                    f"'As a/an <stakeholder>, I can ..., so that ...' — got: '{desc[:80]}'"
                )

            # ── Fibonacci snap ─────────────────────────────────────────────
            sp = story.story_points
            if sp not in _FIBONACCI:
                snapped = min(_FIBONACCI, key=lambda f: abs(f - sp))
                fib_warnings.append(
                    f"PBI-{pbi_idx:03d} [{rid}]: story_points {sp} → snapped to {snapped}."
                )
                sp = snapped

            # ── WSJF recompute ─────────────────────────────────────────────
            wsjf = round(
                (story.business_value + story.time_criticality + story.risk_reduction) / sp,
                2,
            )

            # ── INVEST evaluation ──────────────────────────────────────────
            failed_criteria = [
                c for c in _INVEST_CRITERIA if not getattr(story, c, True)
            ]
            invest_pass = len(failed_criteria) == 0
            if failed_criteria:
                invest_warnings.append(
                    f"PBI-{pbi_idx:03d} [{rid}]: INVEST failures — {', '.join(failed_criteria)}."
                )

            # ── Status assignment ──────────────────────────────────────────
            if len(failed_criteria) >= 3:
                status = "invest_failed"
            elif not invest_pass or not format_ok:
                status = "needs_refinement"
            else:
                status = "ready"

            # ── Enrichment block from original requirement ─────────────────
            req = req_map.get(rid, {})
            raw_acs = req.get("acceptance_criteria") or []
            enrichment = {
                "statement":             req.get("statement", ""),
                "context":               req.get("context", ""),
                "rationale":             req.get("rationale", ""),
                "acceptance_criteria":   raw_acs if isinstance(raw_acs, list) else [],
                "priority":              req.get("priority", ""),
                "source_elicitation_id": req.get("source_elicitation_id", ""),
                "stakeholder":           req.get("stakeholder", ""),
                "req_type":              req.get("req_type") or req.get("type", ""),
            }

            items.append({
                "id":               f"PBI-{pbi_idx:03d}",
                "source_req_id":    rid,
                "type":             story.source_type,
                "title":            story.title,
                "description":      desc,
                "domain":           story.domain,
                "story_points":     sp,
                "complexity":       story.complexity,
                "effort":           story.effort,
                "uncertainty":      story.uncertainty,
                "business_value":   story.business_value,
                "time_criticality": story.time_criticality,
                "risk_reduction":   story.risk_reduction,
                "wsjf_score":       wsjf,
                "priority_rank":    story.priority_rank,
                "invest_pass":      invest_pass,
                "invest_flags":     failed_criteria,
                "status":           status,
                "independent":      story.independent,
                "negotiable":       story.negotiable,
                "valuable":         story.valuable,
                "estimable":        story.estimable,
                "small":            story.small,
                "testable":         story.testable,
                "thought":          getattr(story, "thought", ""),
                "enrichment":       enrichment,
            })

        # ── Build artifact ─────────────────────────────────────────────────
        total_pts    = sum(i["story_points"] for i in items)
        ready_count  = sum(1 for i in items if i["status"] == "ready")
        refine_count = sum(1 for i in items if i["status"] == "needs_refinement")
        failed_count = sum(1 for i in items if i["status"] == "invest_failed")

        session_id = state.get("session_id", str(uuid.uuid4()))
        artifacts  = dict(state.get("artifacts") or {})

        product_backlog = {
            "id":                     str(uuid.uuid4()),
            "session_id":             session_id,
            "source_artifact":        "requirement_list_approved",
            "status":                 "draft",
            "total_items":            len(items),
            "total_story_points":     total_pts,
            "ready_count":            ready_count,
            "needs_refinement_count": refine_count,
            "invest_failed_count":    failed_count,
            "items":                  items,
            "methodology": {
                "story_format":   "As a <role>, I can <capability>, so that <benefit>.",
                "estimation":     "Fibonacci — Complexity(1-5) + Effort(1-5) + Uncertainty(1-5)",
                "quality_gate":   "INVEST (Independent, Negotiable, Valuable, Estimable, Small, Testable)",
                "prioritization": "WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints",
            },
            "pass_notes":      prioritized.pass_notes,
            "quality_warnings": {
                "invest":    invest_warnings,
                "format":    format_warnings,
                "fibonacci": fib_warnings,
            },
            "created_at": datetime.now().isoformat(),
        }

        if feedback:
            product_backlog["rebuild_feedback"] = feedback

        artifacts["product_backlog"] = product_backlog

        logger.info(
            "[SprintAgent] Pass 4 complete — %d items | %d pts | "
            "ready=%d  refinement=%d  invest_failed=%d",
            len(items), total_pts, ready_count, refine_count, failed_count,
        )
        if invest_warnings:
            logger.warning("[SprintAgent] INVEST warnings (%d): %s", len(invest_warnings), invest_warnings[:3])
        if format_warnings:
            logger.warning("[SprintAgent] Format warnings (%d): %s", len(format_warnings), format_warnings[:3])
        if fib_warnings:
            logger.warning("[SprintAgent] Fibonacci snaps (%d): %s", len(fib_warnings), fib_warnings[:3])

        return {"artifacts": artifacts}

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _extract_all_requirements(req_list: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Flatten requirements from the SRS / requirement_list artifact.

        Handles both old schema (id, type, domain, who, why) and new schema
        (req_id, req_type, epic, stakeholder, statement, context, rationale,
        acceptance_criteria, source_elicitation_id, status).
        Returns ALL items — status filtering is done by the caller.
        """
        if not req_list:
            return []

        # ── Flat list under a known key ───────────────────────────────────
        for key in ("requirements", "items", "requirement_items", "all_requirements"):
            if key in req_list and isinstance(req_list[key], list):
                return list(req_list[key])

        # ── Typed sub-lists ───────────────────────────────────────────────
        merged: List[Dict] = []
        for key in (
            "functional_requirements",
            "non_functional_requirements",
            "constraints",
        ):
            sub = req_list.get(key, [])
            if isinstance(sub, list):
                merged.extend(sub)
        return merged

    @staticmethod
    def _format_requirements_block(requirements: List[Dict]) -> str:
        """
        Render requirements as a rich, readable block for LLM prompts.

        Handles both old schema (id/type/domain/who/why) and new schema
        (req_id/req_type/epic/stakeholder/statement/context/rationale/
        acceptance_criteria/source_elicitation_id/status).
        """
        lines: List[str] = []
        for r in requirements:
            # ── Field normalisation (new schema preferred) ─────────────────
            req_id      = r.get("req_id")     or r.get("id", "?")
            req_type    = r.get("req_type")   or r.get("type", "?")
            epic        = r.get("epic")       or r.get("domain", "")
            stakeholder = r.get("stakeholder") or r.get("who", "")
            statement   = r.get("statement")  or r.get("description", "")
            context     = r.get("context")    or ""
            rationale   = r.get("rationale")  or r.get("why", "")
            acs         = r.get("acceptance_criteria") or []
            priority    = r.get("priority", "?")
            elicit_id   = r.get("source_elicitation_id", "")
            status      = r.get("status", "confirmed")

            block = (
                f"[{req_id}]  type={req_type}  priority={priority}  status={status}\n"
                f"  epic:        {epic}\n"
                f"  stakeholder: {stakeholder}\n"
                f"  statement:   {statement}\n"
            )

            if context:
                block += f"  context:     {context}\n"

            if rationale:
                # Trim at a sentence boundary if long
                rat_short = rationale[:240] + ("…" if len(rationale) > 240 else "")
                block += f"  rationale:   {rat_short}\n"

            if isinstance(acs, list) and acs:
                for idx, ac in enumerate(acs, 1):
                    block += f"  AC[{idx}]:       {ac}\n"
            else:
                block += f"  AC:          (none)\n"

            if elicit_id:
                block += f"  elicit_id:   {elicit_id}\n"

            lines.append(block)

        return "\n".join(lines)

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        """Render a PO feedback constraint block for injection into system prompts."""
        if not feedback:
            return ""
        return (
            f"\n\n{'━'*12} PRODUCT OWNER FEEDBACK — previous backlog was REJECTED {'━'*12}\n"
            f"{feedback}\n"
            f"You MUST address ALL points above when performing {context}.\n"
            f"{'━'*70}\n"
        )