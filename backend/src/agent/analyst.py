"""
analyst.py – AnalystAgent  (Backlog Refinement)

Role
────
The AnalystAgent runs once after the product backlog is approved in Sprint 0.
It enriches AND repairs every PBI (Product Backlog Item) in a deterministic
3-pass extract_structured() pipeline — no ReAct loop, no tool routing.

Pass 1 — INVEST Assessment
  Reads each PBI (including its enrichment block from SprintAgent) and produces
  a per-criterion pass/fail assessment with actionable issues and repair
  instructions.  Stories that fail Small are flagged for splitting; stories
  that fail Testable or Negotiable are flagged for rewriting.

Pass 2 — PBI Repair + AC Generation
  For every PBI that has INVEST failures, rewrites the offending fields
  (description, title, story_points) and/or splits it into sub-stories.
  Also writes 2–5 Given-When-Then Acceptance Criteria for every PBI —
  original or repaired — using the enrichment block (original statement,
  context, rationale, acceptance_criteria) as primary source.

Pass 3 — Assembly (deterministic — no LLM)
  Merges Pass 1 and Pass 2 output back into a deep copy of product_backlog,
  re-assigns PBI IDs for any split stories, recomputes summary counters, and
  emits validated_product_backlog.

Profile + Addendum pattern (same as SprintAgent)
─────────────────────────────────────────────────
  self.profile.prompt           → who the agent is (analyst_react.txt persona block)
  _PASS1_ADDENDUM, _PASS2_ADDENDUM → per-pass task rules (injected as addendum)

  system_prompt = self.profile.prompt + "\\n\\n" + _PASSn_ADDENDUM [+ feedback]

State fields
────────────
  artifacts["product_backlog"]           — source backlog (read-only); each PBI
                                           carries an "enrichment" sub-dict from
                                           SprintAgent with the original requirement
                                           fields (statement, context, rationale,
                                           acceptance_criteria, priority, etc.)
  artifacts["validated_product_backlog"] — repaired + enriched output
  analyst_feedback                       — HITL rejection text; triggers re-run
  _invest_scratch                        — transient: Pass 1 INVEST results
  _ac_scratch                            — transient: Pass 2 repair + AC results
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


# ─────────────────────────────────────────────────────────────────────────────
# Per-pass addendums
# ─────────────────────────────────────────────────────────────────────────────

_PASS1_ADDENDUM = """\
TASK: PASS 1 — INVEST ASSESSMENT

Assess every PBI against all 6 INVEST criteria. Each PBI entry below
contains two sections:

USER STORY — the title and description (As a … / I can … / so that …)
already written by SprintAgent.

ENRICHMENT — the original requirement fields: statement, context, rationale,
original acceptance criteria, priority, and elicitation ID.

Use BOTH sections together. The enrichment block is your ground truth for
scope, rationale, and testability.

INVEST CRITERIA

I — Independent
A PBI is Independent if it can be delivered without a hard dependency on another specific PBI.

N — Negotiable
A PBI is Negotiable if its scope or implementation approach can be refined and is not a fixed technical specification.

V — Valuable
A PBI is Valuable if the benefit clause delivers a clear, observable outcome for the named actor.
A well-formed user story is always considered Valuable unless the benefit clause is entirely absent.

E — Estimable
A PBI is Estimable if the team can form a credible, bounded effort estimate.

S — Small
A PBI is Small if it fits in a single sprint.
Rule: if story_points is greater than 8, then Small fails.
Cross-cutting context such as "Across all system interactions" is a strong risk signal for failing Small.

T — Testable
A PBI is Testable if the capability clause can be independently verified.
If there are zero original acceptance criteria conditions, then Testable likely fails.

REPAIR INSTRUCTIONS (embed in each failing issue)

If Small fails:
Provide a concrete split into two or more sub-stories, each with story points less than or equal to 8.
Name the sub-stories explicitly, including title and a one-line capability.

If Testable fails:
Rewrite the description so that the capability clause is binary and pass/fail verifiable.
Provide the rewritten description verbatim.

If Negotiable fails:
Remove implementation detail from the description.
Provide the rewritten description verbatim.

If Estimable fails:
Identify what unknown must be resolved, such as creating a spike.

OUTPUT RULES

Assess all PBIs. Do not omit any.

Set severity to "blocker" when the PBI cannot enter a sprint as-is.
This includes cases where Small fails due to story points greater than 8,
Testable fails with zero acceptance criteria, or Estimable fails with no resolution path.

Set severity to "warning" for advisory improvements.

repair_action must be one of the following values:
"split", "rewrite_description", "rewrite_title", "add_spike", or "none".

When repair_action is "split", populate sub_stories with the proposed children.

When repair_action is "rewrite_description" or "rewrite_title",
provide repaired_value with the exact replacement text.
"""

_PASS2_ADDENDUM = """\
TASK: PASS 2 — PBI REPAIR AND ACCEPTANCE CRITERIA

You receive:
- The original PBI list, including user story and enrichment block.
- The INVEST assessment from Pass 1, including per-criterion results and repair instructions.

Your job has two parts:

PART A — APPLY REPAIRS

For every PBI that has at least one issue where repair_action is not "none":

If repair_action is "split":
Replace the PBI with the sub-stories listed in Pass 1.
Each sub-story inherits source_req_id, domain, and type.
Assign story_points individually using Fibonacci values less than or equal to 8.
Recalculate complexity, effort, and uncertainty for each sub-story.
Recalculate INVEST flags, ensuring all sub-stories pass the Small criterion.
Set is_split_child to true and assign split_suffix values such as "a", "b", "c", and so on.

If repair_action is "rewrite_description":
Replace the description with the repaired_value from Pass 1.
Keep all other fields unchanged.

If repair_action is "rewrite_title":
Replace the title with the repaired_value from Pass 1.

If repair_action is "add_spike":
Append a spike entry alongside the PBI.
The spike must have type equal to "spike", a title in the format "Spike: <topic>",
and story_points equal to 2 or 3.

If repair_action is "none":
Copy the PBI through unchanged.

PART B — WRITE ACCEPTANCE CRITERIA

For every output PBI, including original, repaired, or split children:

Write between 2 and 5 Given-When-Then acceptance criteria.

Use the following sources in priority order:

First, use enrichment.acceptance_criteria as the primary starting point.
Rewrite each original acceptance criterion into a formal Given-When-Then structure.

Second, use enrichment.context and enrichment.rationale to derive additional
happy path, edge case, and error case criteria.

Third, use the user story capability and benefit clause to confirm coverage.

TYPE RULES:

happy_path:
At least one is required. This represents the normal success scenario.

edge_case:
At least one is required. This represents boundary or unusual input.

error_case:
Represents system failure or invalid input scenarios.

For non-functional PBIs:
The 'then' clause must contain a measurable threshold, such as a response time less than 2 seconds.

For constraint PBIs:
The 'then' clause must describe process or compliance adherence.

Acceptance Criteria ID pattern examples:
AC-PBI001-01, AC-PBI001-02, AC-PBI001a-01 for split children.

OUTPUT RULES

Output one entry per final PBI after splits are applied.

Carry forward source_req_id, domain, type, WSJF scores, and priority_rank
from the original PBI unless the repair explicitly changes them.

story_points must use Fibonacci values.

Each 'then' clause must be independently verifiable and contain exactly one assertion.

Do not include implementation details. Focus on what the system does, not how it is implemented.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 schemas — INVEST Assessment
# ─────────────────────────────────────────────────────────────────────────────

class InvestIssue(BaseModel):
    criterion:      str = Field(description="Which INVEST criterion failed (e.g. 'small').")
    severity:       Literal["warning", "blocker"]
    message:        str = Field(description="Specific, actionable description of the problem.")
    suggestion:     str = Field(description="Concrete fix recommendation.")
    repair_action:  Literal["split", "rewrite_description", "rewrite_title", "add_spike", "none"]
    repaired_value: Optional[str] = Field(
        default=None,
        description="Exact replacement text when repair_action is rewrite_description or rewrite_title.",
    )
    sub_stories: Optional[List[SubStoryProposal]] = Field(
        default=None,
        description=(
            "When repair_action='split': list of proposed sub-stories. "
            "Each must have: title (str), capability (str), story_points (int Fibonacci ≤ 8)."
        ),
    )


class InvestCriterionResult(BaseModel):
    passed: bool
    note:   str = Field(description="1-sentence rationale citing enrichment fields used.")


class PbiInvestAssessment(BaseModel):
    pbi_id:      str
    independent: InvestCriterionResult
    negotiable:  InvestCriterionResult
    valuable:    InvestCriterionResult
    estimable:   InvestCriterionResult
    small:       InvestCriterionResult
    testable:    InvestCriterionResult
    issues:      List[InvestIssue] = Field(default_factory=list)
    thought:     str = Field(description="Overall assessment: what is good, what needs repair.")


class InvestAssessmentList(BaseModel):
    assessments: List[PbiInvestAssessment] = Field(
        description="One entry per PBI, in the same order as the input."
    )
    pass_notes: str = Field(
        description=(
            "2–3 sentence summary: total PBIs assessed, breakdown by severity, "
            "dominant failure patterns observed."
        )
    )

class SubStoryProposal(BaseModel):
    title:        str  = Field(description="Short title for the sub-story.")
    capability:   str  = Field(description="One-line capability of the sub-story.")
    story_points: int  = Field(
        ge=1, le=8,
        description="Fibonacci story points — must be ≤ 8."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 schemas — PBI Repair + AC Generation
# ─────────────────────────────────────────────────────────────────────────────

class AcceptanceCriterion(BaseModel):
    id:    str
    given: str
    when:  str
    then:  str
    type:  Literal["happy_path", "edge_case", "error_case"]


class RepairedPbi(BaseModel):
    # ── Identity ──────────────────────────────────────────────────────────
    source_pbi_id:  str  = Field(description="Original PBI-NNN this entry came from (or is a child of).")
    source_req_id:  str
    is_split_child: bool = Field(default=False, description="True when this PBI is a split child.")
    split_suffix:   Optional[str] = Field(
        default=None,
        description="Suffix appended to source_pbi_id for split children: 'a', 'b', 'c', …",
    )

    # ── Story fields (may be repaired) ────────────────────────────────────
    title:        str
    description:  str = Field(description="Final user story after any rewrite repair.")
    domain:       str
    type:         Literal["functional", "non_functional", "constraint", "spike"]
    story_points: int  = Field(description="Fibonacci — must be one of 1,2,3,5,8,13,21.")
    complexity:   int  = Field(ge=1, le=5)
    effort:       int  = Field(ge=1, le=5)
    uncertainty:  int  = Field(ge=1, le=5)

    # ── INVEST flags after repair ─────────────────────────────────────────
    independent: bool
    negotiable:  bool
    valuable:    bool
    estimable:   bool
    small:       bool
    testable:    bool

    # ── WSJF (carry forward from original; spike inherits parent's scores) ─
    business_value:   int = Field(ge=1, le=10)
    time_criticality: int = Field(ge=1, le=10)
    risk_reduction:   int = Field(ge=1, le=10)
    priority_rank:    int = Field(description="Carry forward from original PBI (ties allowed for split siblings).")

    # ── Acceptance Criteria ───────────────────────────────────────────────
    acceptance_criteria: List[AcceptanceCriterion] = Field(
        description="2–5 GWT criteria derived from enrichment + user story."
    )

    repair_applied: str = Field(
        description="Brief note: 'none', 'rewrite_description', 'split (child a/b/…)', 'add_spike'."
    )
    thought: str = Field(
        description="How enrichment fields drove the AC and what repair was applied."
    )


class RepairedBacklog(BaseModel):
    pbis: List[RepairedPbi] = Field(
        description=(
            "Final list of all PBIs after repairs.  Split children appear consecutively "
            "immediately after their parent's position.  Spikes follow their parent PBI."
        )
    )
    pass_notes: str = Field(
        description=(
            "2–3 sentence summary: how many PBIs were repaired, how many split, "
            "total AC written, any residual issues."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# AnalystAgent
# ─────────────────────────────────────────────────────────────────────────────

class AnalystAgent(BaseAgent):
    """
    Backlog grooming agent — deterministic 3-pass extract_structured() pipeline.

    Pass 1 (LLM): INVEST assessment with repair instructions per PBI.
    Pass 2 (LLM): PBI repair + Given-When-Then AC generation.
    Pass 3 (deterministic): Assembly → validated_product_backlog artifact.

    Architecture mirrors SprintAgent:
      • Profile   : analyst_react.txt — agent identity / persona only.
      • Addendums : _PASS1_ADDENDUM, _PASS2_ADDENDUM — per-pass task rules.
      • No ReAct tools registered; tools dict is empty.
    """

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="analyst")

    def _register_tools(self) -> None:
        # Pipeline is pure extract_structured — no ReAct tools needed.
        pass

    # =========================================================================
    # LangGraph node entry point
    # =========================================================================

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        if "validated_product_backlog" in artifacts:
            logger.warning(
                "[AnalystAgent] process() called but validated_product_backlog "
                "already exists. Supervisor should not have routed here."
            )
            return {}
        return self._run_grooming(state)

    # =========================================================================
    # 3-Pass Pipeline
    # =========================================================================

    def _run_grooming(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = state.get("artifacts") or {}
        pb        = artifacts.get("product_backlog") or {}
        items     = pb.get("items") or []
        feedback  = (state.get("analyst_feedback") or "").strip()

        if not items:
            logger.error("[AnalystAgent] product_backlog has no items.")
            return {"errors": ["AnalystAgent: product_backlog has no items."]}

        logger.info("[AnalystAgent] Starting 3-pass grooming — %d PBIs.", len(items))

        try:
            # ── Pass 1: INVEST Assessment ───────────────────────────────────
            invest_result = self._pass1_invest_assessment(items, feedback)
            logger.info(
                "[AnalystAgent] Pass 1 complete — %d assessments, %d with issues.",
                len(invest_result.assessments),
                sum(1 for a in invest_result.assessments if a.issues),
            )

            # ── Pass 2: Repair + AC Generation ─────────────────────────────
            repaired = self._pass2_repair_and_ac(items, invest_result, feedback)
            logger.info(
                "[AnalystAgent] Pass 2 complete — %d final PBIs.",
                len(repaired.pbis),
            )

            # ── Pass 3: Assembly ────────────────────────────────────────────
            return self._pass3_assembly(repaired, invest_result, pb, state, feedback)

        except Exception as exc:
            logger.error("[AnalystAgent] Pipeline failed: %s", exc, exc_info=True)
            return {"errors": [f"AnalystAgent pipeline error: {exc}"]}

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 1 — INVEST Assessment
    # ─────────────────────────────────────────────────────────────────────────

    def _pass1_invest_assessment(
        self,
        items:    List[Dict],
        feedback: str = "",
    ) -> InvestAssessmentList:
        """Assess every PBI against INVEST using the user story + enrichment block."""

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS1_ADDENDUM
            + self._feedback_block(feedback, "INVEST assessment")
        )

        pbi_block = self._format_pbi_block(items, include_enrichment=True)

        user_prompt = (
            f"PRODUCT BACKLOG TO ASSESS ({len(items)} PBIs):\n\n"
            f"{pbi_block}\n\n"
            "Assess EVERY PBI.  Provide repair instructions for every failure.\n"
            "Output assessments in the same order as the input."
        )

        return self.extract_structured(
            schema=InvestAssessmentList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 2 — Repair + AC Generation
    # ─────────────────────────────────────────────────────────────────────────

    def _pass2_repair_and_ac(
        self,
        items:         List[Dict],
        invest_result: InvestAssessmentList,
        feedback:      str = "",
    ) -> RepairedBacklog:
        """Apply INVEST repairs and write Given-When-Then AC for every PBI."""

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS2_ADDENDUM
            + self._feedback_block(feedback, "PBI repair and AC generation")
        )

        pbi_block    = self._format_pbi_block(items, include_enrichment=True)
        invest_block = self._format_invest_block(invest_result)

        user_prompt = (
            f"ORIGINAL PBIs WITH ENRICHMENT ({len(items)} items):\n\n"
            f"{pbi_block}\n\n"
            f"PASS 1 INVEST ASSESSMENT:\n\n"
            f"{invest_block}\n\n"
            f"Pass 1 notes: {invest_result.pass_notes}\n\n"
            "Apply ALL repairs and write AC for EVERY PBI.\n"
            "Output one entry per final PBI (original, repaired, or split child)."
        )

        return self.extract_structured(
            schema=RepairedBacklog,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 3 — Assembly  (no LLM call)
    # ─────────────────────────────────────────────────────────────────────────

    def _pass3_assembly(
        self,
        repaired:      RepairedBacklog,
        invest_result: InvestAssessmentList,
        source_pb:     Dict[str, Any],
        state:         Dict[str, Any],
        feedback:      str = "",
    ) -> Dict[str, Any]:
        """
        Merge repaired PBIs, assign final sequential IDs, recompute WSJF +
        summary counters, and emit validated_product_backlog.
        """
        invest_by_pbi = {a.pbi_id: a for a in invest_result.assessments}

        final_items:  List[Dict[str, Any]] = []
        total_ac      = 0
        invest_issues = 0
        blockers      = 0
        split_count   = 0

        # Assign final sequential IDs.
        # Non-split PBIs get PBI-001, PBI-002, …
        # Split children inherit their parent seq number plus a letter suffix:
        #   PBI-003 splits → PBI-003a, PBI-003b (parent row replaced by children)
        # Spikes that are not split children get their own seq number.
        seq                = 1
        current_parent_seq = 0   # seq number of the most-recent non-split PBI
        for rpbi in repaired.pbis:
            if rpbi.is_split_child:
                suffix   = rpbi.split_suffix or ""
                final_id = f"PBI-{current_parent_seq:03d}{suffix}"
            else:
                current_parent_seq = seq
                final_id           = f"PBI-{seq:03d}"
                seq               += 1

            # Snap story_points to nearest Fibonacci
            sp = rpbi.story_points
            if sp not in _FIBONACCI:
                sp = min(_FIBONACCI, key=lambda f: abs(f - sp))

            # Recompute WSJF deterministically
            wsjf = round(
                (rpbi.business_value + rpbi.time_criticality + rpbi.risk_reduction) / sp, 2
            )

            # Failed INVEST criteria after repair
            failed_criteria = [
                c for c in _INVEST_CRITERIA if not getattr(rpbi, c, True)
            ]
            invest_pass = len(failed_criteria) == 0

            # Status
            if len(failed_criteria) >= 3:
                status = "invest_failed"
            elif not invest_pass:
                status = "needs_refinement"
            elif rpbi.acceptance_criteria:
                status = "ready"
            else:
                status = "needs_refinement"

            # INVEST validation block (from Pass 1; keyed on source_pbi_id)
            invest_validation: Optional[Dict] = None
            iv = invest_by_pbi.get(rpbi.source_pbi_id)
            if iv:
                raw_issues = [i.model_dump() for i in iv.issues]
                invest_validation = {
                    "criteria": {
                        c: {
                            "pass": getattr(getattr(iv, c), "passed", True),
                            "note": getattr(getattr(iv, c), "note", ""),
                        }
                        for c in _INVEST_CRITERIA
                    },
                    "failed_criteria": [
                        c for c in _INVEST_CRITERIA
                        if not getattr(getattr(iv, c), "passed", True)
                    ],
                    "issues":      raw_issues,
                    "assessed_at": datetime.now().isoformat(),
                }
                invest_issues += len(raw_issues)
                blockers      += sum(
                    1 for iss in raw_issues if iss.get("severity") == "blocker"
                )

            if rpbi.is_split_child:
                split_count += 1

            # Serialise AC
            ac_list = [
                {
                    "id":    ac.id,
                    "given": ac.given,
                    "when":  ac.when,
                    "then":  ac.then,
                    "type":  ac.type,
                }
                for ac in (rpbi.acceptance_criteria or [])
            ]
            total_ac += len(ac_list)

            # History trail
            history: List[Dict] = []
            if invest_validation:
                history.append({
                    "action": "invest_validated",
                    "step":   "backlog_refinement",
                    "reason": iv.thought if iv else "INVEST quality check by AnalystAgent.",
                })
            if rpbi.repair_applied and rpbi.repair_applied != "none":
                history.append({
                    "action": "repaired",
                    "step":   "backlog_refinement",
                    "reason": rpbi.repair_applied,
                })
            if ac_list:
                history.append({
                    "action": "ac_written",
                    "step":   "backlog_refinement",
                    "reason": rpbi.thought,
                    **( {"hitl_feedback": feedback} if feedback else {} ),
                })

            final_items.append({
                "id":                  final_id,
                "source_pbi_id":       rpbi.source_pbi_id,
                "source_req_id":       rpbi.source_req_id,
                "is_split_child":      rpbi.is_split_child,
                "type":                rpbi.type,
                "title":               rpbi.title,
                "description":         rpbi.description,
                "domain":              rpbi.domain,
                "story_points":        sp,
                "complexity":          rpbi.complexity,
                "effort":              rpbi.effort,
                "uncertainty":         rpbi.uncertainty,
                "business_value":      rpbi.business_value,
                "time_criticality":    rpbi.time_criticality,
                "risk_reduction":      rpbi.risk_reduction,
                "wsjf_score":          wsjf,
                "priority_rank":       rpbi.priority_rank,
                "invest_pass":         invest_pass,
                "invest_flags":        failed_criteria,
                "invest_validation":   invest_validation,
                "status":              status,
                "independent":         rpbi.independent,
                "negotiable":          rpbi.negotiable,
                "valuable":            rpbi.valuable,
                "estimable":           rpbi.estimable,
                "small":               rpbi.small,
                "testable":            rpbi.testable,
                "acceptance_criteria": ac_list,
                "repair_applied":      rpbi.repair_applied,
                "thought":             rpbi.thought,
                "history":             history,
            })

        # ── Summary counters ───────────────────────────────────────────────
        total_pts    = sum(i["story_points"] for i in final_items)
        ready_count  = sum(1 for i in final_items if i["status"] == "ready")
        refine_count = sum(1 for i in final_items if i["status"] == "needs_refinement")
        failed_count = sum(1 for i in final_items if i["status"] == "invest_failed")

        # ── Build artifact ─────────────────────────────────────────────────
        analyst_feedback = (state.get("analyst_feedback") or "").strip()
        validated_backlog: Dict[str, Any] = {
            "id":              str(uuid.uuid4()),
            **source_pb,
            "items":                  final_items,
            "source_artifact":        "product_backlog",
            "status":                 "validated",
            "total_items":            len(final_items),
            "total_story_points":     total_pts,
            "ready_count":            ready_count,
            "needs_refinement_count": refine_count,
            "invest_failed_count":    failed_count,
            "refinement_stats": {
                "original_pbi_count": len(source_pb.get("items") or []),
                "final_pbi_count":    len(final_items),
                "split_children":     split_count,
                "total_ac":           total_ac,
                "invest_issues":      invest_issues,
                "blockers":           blockers,
            },
            "refinement_summary": repaired.pass_notes,
            "validated_at":       datetime.now().isoformat(),
            **( {"rebuild_feedback": analyst_feedback} if analyst_feedback else {} ),
        }

        artifacts = dict(state.get("artifacts") or {})
        artifacts["validated_product_backlog"] = validated_backlog

        logger.info(
            "[AnalystAgent] Pass 3 complete — %d final PBIs (%d splits) | "
            "%d pts | ready=%d refinement=%d invest_failed=%d | %d AC | %d issues (%d blockers)",
            len(final_items), split_count, total_pts,
            ready_count, refine_count, failed_count,
            total_ac, invest_issues, blockers,
        )

        return {"artifacts": artifacts}

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _format_pbi_block(items: List[Dict], include_enrichment: bool = True) -> str:
        """Render PBIs as a rich, readable block for LLM prompts."""
        lines: List[str] = []
        for item in items:
            pbi_id = item.get("id", "?")
            block = (
                f"[{pbi_id}]  rank={item.get('priority_rank','?')}  "
                f"pts={item.get('story_points','?')}  type={item.get('type','?')}\n"
                f"  Title      : {item.get('title','')}\n"
                f"  User Story : {item.get('description','')}\n"
                f"  INVEST flags (Sprint 0): {item.get('invest_flags') or 'none'}\n"
            )

            if include_enrichment:
                enr = item.get("enrichment") or {}
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
    def _format_invest_block(invest_result: InvestAssessmentList) -> str:
        """Render Pass 1 INVEST assessments compactly for the Pass 2 prompt."""
        lines: List[str] = []
        for a in invest_result.assessments:
            failed = [
                c for c in _INVEST_CRITERIA
                if not getattr(getattr(a, c), "passed", True)
            ]
            block = (
                f"[{a.pbi_id}]  failed={failed or 'none'}\n"
                f"  thought: {a.thought}\n"
            )
            for iss in a.issues:
                block += (
                    f"  ISSUE [{iss.criterion}] {iss.severity}: {iss.message}\n"
                    f"    → suggestion    : {iss.suggestion}\n"
                    f"    → repair_action : {iss.repair_action}"
                )
                if iss.repaired_value:
                    block += f"\n    → repaired_value: {iss.repaired_value}"
                if iss.sub_stories:
                    for ss in iss.sub_stories:
                        block += (
                            f"\n      sub: title={ss.title}  "
                            f"capability={ss.capability}  "
                            f"pts={ss.story_points}"
                        )
                block += "\n"
            lines.append(block)
        return "\n".join(lines)

    @staticmethod
    def _feedback_block(feedback: str, context: str) -> str:
        """Render a reviewer feedback constraint block for injection into system prompts."""
        if not feedback:
            return ""
        return (
            f"\n\n{'━'*12} REVIEWER FEEDBACK — previous refinement was REJECTED {'━'*12}\n"
            f"{feedback}\n"
            f"You MUST address ALL points above when performing {context}.\n"
            f"{'━'*70}\n"
        )