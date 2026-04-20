"""
analyst.py – AnalystAgent  (Backlog Refinement)

Role
────
The AnalystAgent runs once after the product backlog is approved in Sprint 0.
It acts as a grooming advisor that enriches every PBI in a single pass:
  1. Validate INVEST quality criteria → embed warnings into each PBI
  2. Synthesize Given-When-Then Acceptance Criteria → store in PBI.acceptance_criteria
  3. Publish the enriched backlog as a new artifact: validated_product_backlog

The output artifact (validated_product_backlog) is the product backlog with
every PBI fully specified — INVEST validation notes and AC already populated.
Sprint N draws from this artifact, not the raw product_backlog.

Tool sequence (single ReAct turn)
──────────────────────────────────
  check_invest_quality      — assess all 6 INVEST criteria for every PBI
  write_acceptance_criteria — generate Given-When-Then for every PBI
  publish_validated_backlog — merge validation + AC into product_backlog,
                              emit validated_product_backlog, END turn

State fields
────────────
  artifacts["product_backlog"]           — source backlog (read-only)
  artifacts["validated_product_backlog"] — enriched output (supervisor gate)
  analyst_feedback                       — HITL rejection text; triggers re-run
  _invest_scratch                        — transient: INVEST results between tools
  _ac_scratch                            — transient: AC results between tools
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

_INVEST_CRITERIA = ("independent", "negotiable", "valuable", "estimable", "small", "testable")
_MAX_AC_PER_PBI  = 5


class AnalystAgent(BaseAgent):
    """
    Backlog grooming agent — single step, one ReAct turn.

    Reads:  artifacts["product_backlog"]
    Writes: artifacts["validated_product_backlog"]
    """

    _PROFILE = """You are an expert Agile Business Analyst performing backlog grooming.

Your job is to enrich every PBI in the product backlog in one coherent pass:

PART 1 — Quality gate (INVEST):
  Assess each PBI against the 6 INVEST criteria:
    I — Independent : deliverable without blocking another PBI
    N — Negotiable  : scope is flexible, not a fixed specification
    V — Valuable    : observable value for a real user or stakeholder
    E — Estimable   : team can confidently assign story points
    S — Small       : fits in a single sprint (rule of thumb: ≤ 8 pts for a 20-pt sprint)
    T — Testable    : concrete, verifiable conditions can be written

  For failing criteria: produce actionable warnings with a concrete suggestion.
  Bad warning: "may not be small enough."
  Good warning: "PBI-002 at 13 pts will not fit a standard 20-pt sprint.
    Suggested split: (a) Privacy & Bias page  (b) Hallucinations & Academic Integrity page."

PART 2 — Acceptance Criteria (Given-When-Then):
  For every PBI write 2–5 criteria that are:
    • Concrete and independently testable (one assertion per 'then')
    • Derived from the PBI description and its reasoning traces
    • Free of implementation details (WHAT, not HOW)
    • Covering at least one happy path AND one edge/error case
    • Non-functional PBIs: 'then' must be quantified (e.g. "< 2 s on 4G")
    • Constraint PBIs: 'then' must describe process/compliance adherence

RULES:
• ONE tool per ReAct step — never batch calls.
• Every Thought must start with [STRATEGY]...[/STRATEGY].
• check_invest_quality must cover ALL PBIs in one call.
• write_acceptance_criteria must cover ALL PBIs in one call.
• publish_validated_backlog finalises the work and ends the turn."""

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="analyst")

    # ── Tool registration ─────────────────────────────────────────────────────

    def _register_tools(self) -> None:

        self.register_tool(Tool(
            name="check_invest_quality",
            description=(
                "Step 1 — Assess every PBI against all 6 INVEST criteria.\n"
                "Include ALL PBIs in a single call; omitting any PBI is an error.\n\n"
                "Input: {\n"
                "  \"assessments\": [\n"
                "    {\n"
                "      \"pbi_id\":      \"PBI-001\",\n"
                "      \"independent\": {\"pass\": true|false, \"note\": \"<specific reason>\"},\n"
                "      \"negotiable\":  {\"pass\": true|false, \"note\": \"<specific reason>\"},\n"
                "      \"valuable\":    {\"pass\": true|false, \"note\": \"<specific reason>\"},\n"
                "      \"estimable\":   {\"pass\": true|false, \"note\": \"<specific reason>\"},\n"
                "      \"small\":       {\"pass\": true|false, \"note\": \"<specific reason>\"},\n"
                "      \"testable\":    {\"pass\": true|false, \"note\": \"<specific reason>\"},\n"
                "      \"issues\": [\n"
                "        {\n"
                "          \"criterion\":  \"small\",\n"
                "          \"severity\":   \"warning\" | \"blocker\",\n"
                "          \"message\":    \"<actionable detail>\",\n"
                "          \"suggestion\": \"<how to fix: split, rewrite, clarify>\"\n"
                "        }\n"
                "      ],\n"
                "      \"thought\": \"<overall assessment of this PBI>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n\n"
                "Does NOT end the turn. NEXT: call write_acceptance_criteria."
            ),
            func=self._tool_check_invest_quality,
        ))

        self.register_tool(Tool(
            name="write_acceptance_criteria",
            description=(
                "Step 2 — Generate Given-When-Then Acceptance Criteria for every PBI.\n"
                "Include ALL PBIs in a single call. 2–5 criteria per PBI.\n\n"
                "Input: {\n"
                "  \"pbi_criteria\": [\n"
                "    {\n"
                "      \"pbi_id\": \"PBI-001\",\n"
                "      \"criteria\": [\n"
                "        {\n"
                "          \"id\":    \"AC-PBI001-01\",\n"
                "          \"given\": \"<precondition>\",\n"
                "          \"when\":  \"<action or event>\",\n"
                "          \"then\":  \"<single observable outcome>\",\n"
                "          \"type\":  \"happy_path\" | \"edge_case\" | \"error_case\"\n"
                "        }, ...\n"
                "      ],\n"
                "      \"thought\": \"<which traces/description informed this AC>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n\n"
                "Does NOT end the turn. NEXT: call publish_validated_backlog."
            ),
            func=self._tool_write_acceptance_criteria,
        ))

        self.register_tool(Tool(
            name="publish_validated_backlog",
            description=(
                "Step 3 — Merge INVEST validation and AC into the product backlog,\n"
                "then emit 'validated_product_backlog' as the developer-ready artifact.\n\n"
                "Input: {\"summary\": \"<2-3 sentence summary of refinement outcomes>\"}\n\n"
                "This tool ENDS the turn."
            ),
            func=self._tool_publish_validated_backlog,
        ))

    # =========================================================================
    # Tool implementations
    # =========================================================================

    def _tool_check_invest_quality(
        self,
        assessments: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """
        Collect per-PBI INVEST assessments into _invest_scratch.
        Issues are embedded directly inside each assessment entry.
        """
        assessments = assessments or []
        if not assessments:
            return ToolResult(
                observation=(
                    "No assessments provided. "
                    "Supply 'assessments' covering ALL PBIs."
                )
            )

        artifacts = state.get("artifacts") or {}
        pb        = artifacts.get("product_backlog") or {}
        known_ids = {item["id"] for item in (pb.get("items") or [])}

        scratch:      List[Dict] = []
        processed:    List[str]  = []
        skipped:      List[str]  = []
        total_issues  = 0
        blockers      = 0

        for a in assessments:
            pbi_id = (a.get("pbi_id") or "").strip()
            if not pbi_id or pbi_id not in known_ids:
                skipped.append(pbi_id or "(empty)")
                continue

            criteria_result: Dict[str, Any] = {}
            failed: List[str] = []

            for crit in _INVEST_CRITERIA:
                entry  = a.get(crit) or {}
                passed = bool(entry.get("pass", True))
                note   = (entry.get("note") or "").strip()
                criteria_result[crit] = {"pass": passed, "note": note}
                if not passed:
                    failed.append(crit)

            issues: List[Dict] = []
            for iss in (a.get("issues") or []):
                crit       = (iss.get("criterion") or "").strip()
                sev        = (iss.get("severity") or "warning").strip()
                message    = (iss.get("message") or "").strip()
                suggestion = (iss.get("suggestion") or "").strip()
                if not message:
                    continue
                issues.append({
                    "criterion":  crit,
                    "severity":   sev,
                    "message":    message,
                    "suggestion": suggestion,
                })
                total_issues += 1
                if sev == "blocker":
                    blockers += 1

            scratch.append({
                "pbi_id":          pbi_id,
                "criteria":        criteria_result,
                "failed_criteria": failed,
                "issues":          issues,
                "thought":         (a.get("thought") or "").strip(),
                "assessed_at":     datetime.now().isoformat(),
            })
            processed.append(pbi_id)

        missing = known_ids - set(processed)

        obs_parts = [
            f"INVEST quality check done: {len(processed)} PBIs assessed, "
            f"{total_issues} issues ({blockers} blockers)."
        ]
        if missing:
            obs_parts.append(
                f"⚠ PBIs not yet assessed (must fix before publishing): {sorted(missing)}."
            )
        if skipped:
            obs_parts.append(f"Skipped (not found in backlog): {skipped}.")

        failing = [s for s in scratch if s["failed_criteria"]]
        if failing:
            obs_parts.append(
                "Criteria failures: "
                + ", ".join(
                    f"{s['pbi_id']} → {s['failed_criteria']}" for s in failing
                )
            )

        obs_parts.append("NEXT: call write_acceptance_criteria for ALL PBIs.")

        logger.info(
            "[AnalystAgent] check_invest_quality: %d PBIs, %d issues, %d blockers.",
            len(processed), total_issues, blockers,
        )

        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={"_invest_scratch": scratch},
        )

    # -------------------------------------------------------------------------

    def _tool_write_acceptance_criteria(
        self,
        pbi_criteria: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """
        Collect Given-When-Then AC for all PBIs into _ac_scratch.
        Validates completeness of each GWT triple and enforces the per-PBI cap.
        """
        pbi_criteria = pbi_criteria or []
        if not pbi_criteria:
            return ToolResult(
                observation=(
                    "No criteria provided. "
                    "Supply 'pbi_criteria' covering ALL PBIs."
                )
            )

        artifacts = state.get("artifacts") or {}
        pb        = artifacts.get("product_backlog") or {}
        known_ids = {item["id"] for item in (pb.get("items") or [])}

        scratch:   List[Dict] = []
        processed: List[str]  = []
        skipped:   List[str]  = []
        total_ac   = 0
        incomplete = 0

        for entry in pbi_criteria:
            pbi_id    = (entry.get("pbi_id") or "").strip()
            raw_crits = entry.get("criteria") or []
            thought   = (entry.get("thought") or "").strip()

            if not pbi_id or pbi_id not in known_ids:
                skipped.append(pbi_id or "(empty)")
                continue

            validated: List[Dict] = []
            for i, c in enumerate(raw_crits[:_MAX_AC_PER_PBI], start=1):
                ac_id  = (c.get("id") or f"AC-{pbi_id}-{i:02d}").strip()
                given  = (c.get("given") or "").strip()
                when   = (c.get("when") or "").strip()
                then   = (c.get("then") or "").strip()
                ctype  = (c.get("type") or "happy_path").strip()

                if not (given and when and then):
                    incomplete += 1
                    logger.warning(
                        "[AnalystAgent] Incomplete GWT for %s criterion %d — skipped.",
                        pbi_id, i,
                    )
                    continue

                validated.append({
                    "id":    ac_id,
                    "given": given,
                    "when":  when,
                    "then":  then,
                    "type":  ctype,
                })

            scratch.append({
                "pbi_id":   pbi_id,
                "criteria": validated,
                "thought":  thought,
                "count":    len(validated),
            })
            processed.append(pbi_id)
            total_ac += len(validated)

        missing = known_ids - set(processed)

        obs_parts = [
            f"Acceptance criteria written: {len(processed)} PBIs, {total_ac} total criteria."
        ]
        if incomplete:
            obs_parts.append(
                f"⚠ {incomplete} criterion skipped due to missing given/when/then."
            )
        if missing:
            obs_parts.append(
                f"⚠ PBIs without AC (should fix): {sorted(missing)}."
            )
        if skipped:
            obs_parts.append(f"Skipped (not in backlog): {skipped}.")

        obs_parts.append("NEXT: call publish_validated_backlog with a summary.")

        logger.info(
            "[AnalystAgent] write_acceptance_criteria: %d PBIs, %d AC total.",
            len(processed), total_ac,
        )

        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={"_ac_scratch": scratch},
        )

    # -------------------------------------------------------------------------

    def _tool_publish_validated_backlog(
        self,
        summary: str = "",
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """
        Merge INVEST validation notes and AC into a deep copy of product_backlog,
        then emit it as 'validated_product_backlog'.

        Each PBI in the output gains:
          invest_validation   — per-criterion results + actionable issues
          acceptance_criteria — GWT criteria (given/when/then/type)
          status              — set to 'ready' when AC is present
        """
        invest_scratch:  List[Dict] = state.get("_invest_scratch") or []
        ac_scratch:      List[Dict] = state.get("_ac_scratch") or []
        analyst_feedback = (state.get("analyst_feedback") or "").strip()

        invest_by_pbi = {d["pbi_id"]: d for d in invest_scratch}
        ac_by_pbi     = {d["pbi_id"]: d for d in ac_scratch}

        artifacts = dict(state.get("artifacts") or {})
        source_pb = artifacts.get("product_backlog") or {}

        # Deep-copy items — never mutate the source artifact
        items: List[Dict] = [dict(item) for item in (source_pb.get("items") or [])]

        total_ac      = 0
        ready_pbis:   List[str] = []
        invest_issues = 0
        blockers      = 0

        for item in items:
            pbi_id = item["id"]

            # ── Embed INVEST validation ───────────────────────────────────────
            iv = invest_by_pbi.get(pbi_id)
            if iv:
                item["invest_validation"] = {
                    "criteria":        iv.get("criteria", {}),
                    "failed_criteria": iv.get("failed_criteria", []),
                    "issues":          iv.get("issues", []),
                    "assessed_at":     iv.get("assessed_at", datetime.now().isoformat()),
                }
                invest_issues += len(iv.get("issues", []))
                blockers      += sum(
                    1 for iss in iv.get("issues", []) if iss.get("severity") == "blocker"
                )
                item.setdefault("history", []).append({
                    "action": "invest_validated",
                    "step":   "backlog_refinement",
                    "reason": iv.get("thought", "INVEST quality check by AnalystAgent."),
                })

            # ── Embed Acceptance Criteria ─────────────────────────────────────
            ac = ac_by_pbi.get(pbi_id)
            if ac and ac.get("criteria"):
                item["acceptance_criteria"] = ac["criteria"]
                total_ac += len(ac["criteria"])
                item.setdefault("history", []).append({
                    "action":  "ac_written",
                    "step":    "backlog_refinement",
                    "reason":  ac.get("thought", "AC synthesized by AnalystAgent."),
                    **({"hitl_feedback": analyst_feedback} if analyst_feedback else {}),
                })

            # ── Mark ready ────────────────────────────────────────────────────
            if item.get("acceptance_criteria"):
                item["status"] = "ready"
                ready_pbis.append(pbi_id)

        # ── Build validated_product_backlog ───────────────────────────────────
        validated_backlog: Dict[str, Any] = {
            "id":              str(uuid.uuid4()),
            **source_pb,                          # inherit session_id, notes, etc.
            "items":           items,
            "source_artifact": "product_backlog",
            "status":          "validated",
            "refinement_summary": summary,
            "refinement_stats": {
                "total_pbis":    len(items),
                "ready_pbis":    len(ready_pbis),
                "total_ac":      total_ac,
                "invest_issues": invest_issues,
                "blockers":      blockers,
            },
            "validated_at": datetime.now().isoformat(),
        }

        artifacts["validated_product_backlog"] = validated_backlog

        obs = (
            f"validated_product_backlog published.\n"
            f"  PBIs ready   : {len(ready_pbis)}/{len(items)}\n"
            f"  Total AC     : {total_ac}\n"
            f"  INVEST issues: {invest_issues} ({blockers} blockers)\n"
            f"Workflow will now route to HITL review of the validated backlog."
        )

        logger.info(
            "[AnalystAgent] publish_validated_backlog: %d ready PBIs, "
            "%d AC, %d invest issues (%d blockers).",
            len(ready_pbis), total_ac, invest_issues, blockers,
        )

        return ToolResult(
            observation=obs,
            state_updates={"artifacts": artifacts},
            should_return=True,
        )

    # =========================================================================
    # LangGraph node entry point
    # =========================================================================

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        LangGraph node entry point — called by analyst_turn_fn in graph.py.

        The supervisor routes here only when validated_product_backlog is absent
        (enforced by the ArtifactStep prerequisites in flow.py).
        """
        artifacts = state.get("artifacts") or {}
        if "validated_product_backlog" in artifacts:
            logger.warning(
                "[AnalystAgent] process() called but validated_product_backlog "
                "already exists. Supervisor should not have routed here."
            )
            return {}

        return self._run_grooming(state)

    # ── Grooming entry ────────────────────────────────────────────────────────

    def _run_grooming(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Build the task prompt and launch the ReAct loop."""
        artifacts    = state.get("artifacts") or {}
        pb           = artifacts.get("product_backlog") or {}
        items        = pb.get("items") or []
        project_desc = state.get("project_description", "not provided")
        n            = len(items)

        analyst_feedback = (state.get("analyst_feedback") or "").strip()
        feedback_block   = ""
        if analyst_feedback:
            feedback_block = (
                f"{'━'*16}  REVIEWER FEEDBACK (previous refinement rejected)  {'━'*16}\n"
                f"{analyst_feedback}\n\n"
                "You MUST address every point above in this revised pass.\n"
                "Pay special attention to AC quality and any INVEST issues flagged.\n\n"
            )

        pbi_lines = []
        for item in items:
            # Sprint 0 reasoning traces (rationale behind each requirement)
            traces = [
                h.get("reason", "")
                for h in (item.get("history") or [])
                if h.get("reason") and h.get("action") in ("created", "prioritized")
            ]
            trace_str = (" | ".join(traces[:2])[:200]) if traces else "(none)"

            # Pre-existing INVEST failures from Sprint 0 triage
            invest     = item.get("invest", {})
            pre_failed = [k for k, v in invest.items() if not v]
            invest_note = (
                f"\n    Sprint-0 INVEST failures already known: {pre_failed}"
                if pre_failed else ""
            )

            # Show existing AC only when re-running after rejection
            existing_ac = item.get("acceptance_criteria") or []
            ac_note = (
                f"\n    Existing AC to revise: {len(existing_ac)} criteria"
                if existing_ac and analyst_feedback else ""
            )

            pbi_lines.append(
                f"  [{item['id']}] rank={item.get('priority_rank','?')} "
                f"pts={item.get('story_points','?')} type={item.get('type','?')}\n"
                f"    Title  : {item.get('title','')}\n"
                f"    Desc   : {item.get('description','')[:200]}\n"
                f"    Traces : {trace_str}"
                + invest_note
                + ac_note
            )

        task = (
            f"{self._PROFILE}\n\n"
            f"{'━'*16}  PROJECT  {'━'*16}\n"
            f"{project_desc}\n\n"
            + feedback_block
            + f"{'━'*16}  PRODUCT BACKLOG TO GROOM ({n} PBIs)  {'━'*16}\n"
            + "\n".join(pbi_lines)
            + f"\n\n{'━'*16}  YOUR GROOMING SEQUENCE  {'━'*16}\n"
            f"STEP 1 — Call 'check_invest_quality':\n"
            f"  • Assess ALL {n} PBIs in one call — do not omit any.\n"
            f"  • 'small' fails when story_points > 8 (20-pt sprint rule of thumb).\n"
            f"  • Every issue needs a concrete 'message' and actionable 'suggestion'.\n"
            f"  • Include an issues[] entry even for borderline-passing PBIs if risk exists.\n\n"
            f"STEP 2 — Call 'write_acceptance_criteria':\n"
            f"  • Write criteria for ALL {n} PBIs in one call.\n"
            f"  • 2 criteria minimum per PBI; 5 maximum.\n"
            f"  • At least 1 happy_path AND 1 edge_case or error_case per PBI.\n"
            f"  • Non-functional PBIs: 'then' must contain a measurable threshold.\n"
            f"  • Constraint PBIs: 'then' must describe process/compliance adherence.\n"
            f"  • ID pattern: AC-PBI001-01, AC-PBI001-02, AC-PBI002-01, …\n\n"
            f"STEP 3 — Call 'publish_validated_backlog':\n"
            f"  • Provide a 2-3 sentence 'summary' covering: PBIs ready, key INVEST\n"
            f"    issues found, and total AC written.\n"
            f"  • This creates the validated_product_backlog artifact.\n\n"
            f"MANDATORY RULES:\n"
            f"• ONE tool per ReAct step.\n"
            f"• Every Thought must start with [STRATEGY]...[/STRATEGY].\n"
            f"• publish_validated_backlog is the only tool that ends the turn.\n"
        )

        logger.info("[AnalystAgent] Starting backlog grooming — %d PBIs.", n)
        return self.react(state, task)