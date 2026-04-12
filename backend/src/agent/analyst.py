"""
analyst.py – AnalystAgent

Role
────
AnalystAgent reviews the product_backlog_draft produced by SprintAgent (Pipeline A-Draft)
and generates structured per-PBI feedback stored in artifacts["analyst_feedback"].

It acts as the INVEST quality gate, NLP vagueness detector, duplicate risk assessor,
and requirement rationale cross-checker.  It does NOT modify the backlog directly —
it only writes feedback that SprintAgent reads in Pipeline A-Refine.

Design
──────
• Fully uses BaseAgent infrastructure: self.think, self.memory, self.react().
• Memory format fix from base.py applies — no manual message construction here.
• ONE ReAct pipeline:
    1. review_backlog_items — iterate over every PBI; run INVEST checks,
                              vagueness detection, duplicate risk scan,
                              rationale cross-check; produce per-item reviews.
    2. write_analyst_feedback — persist artifacts["analyst_feedback"].

INVEST cross-check against rationale
─────────────────────────────────────
The task prompt provides the full requirement rationale for each PBI's source
requirement.  The agent uses this to:
  • Verify the description matches the original stakeholder intent (valuable check).
  • Assess whether the scope implied by rationale makes it estimable and small.
  • Flag any testability gap between rationale language and acceptance criteria.

Vagueness detection (NLP)
──────────────────────────
A curated vague-term list is checked at the tool level.  The LLM supplements
this with semantic vagueness detection inside the INVEST 'testable' evaluation.

Duplicate risk
──────────────
Jaccard similarity is computed between all PBI description pairs at the tool level.
Pairs above threshold are flagged as duplicate_risk="high".

Output artifact schema (see state.py for full spec)
────────────────────────────────────────────────────
artifacts["analyst_feedback"] = {
    "session_id":             str,
    "reviewed_artifact":      "product_backlog_draft",
    "overall_quality_score":  float,
    "critical_issues":        int,
    "pbi_reviews":            [...],
    "recommendations_summary": str,
    "notes":                  str,
    "created_at":             str,
}
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

# ── Vague-term list (extends interviewer's set with estimation-specific terms) ─
_VAGUE_TERMS: Set[str] = {
    "quickly", "fast", "slow", "easy", "simple", "complex", "good", "bad",
    "nice", "better", "best", "some", "many", "few", "appropriate", "sufficient",
    "reasonable", "efficient", "robust", "scalable", "secure", "intuitive",
    "user-friendly", "seamlessly", "seamless", "smooth", "optimal", "optimized",
    "modern", "flexible", "powerful", "lightweight", "minimal",
}

# ── Duplicate risk thresholds ─────────────────────────────────────────────────
_DUP_HIGH  = 0.55   # Jaccard ≥ 0.55 → high duplicate risk
_DUP_MED   = 0.35   # Jaccard ≥ 0.35 → medium duplicate risk


def _jaccard(a: str, b: str) -> float:
    """Simple Jaccard word-overlap similarity, ignoring common stop words."""
    stop = {
        "the", "a", "an", "is", "are", "be", "to", "of", "and", "or",
        "that", "it", "for", "in", "on", "with", "as", "should", "must",
        "shall", "will", "can", "user", "system", "able",
    }
    wa = set(a.lower().split()) - stop
    wb = set(b.lower().split()) - stop
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _find_vague_terms(text: str) -> List[str]:
    """Return list of vague terms found in text."""
    words = set(re.sub(r"[^\w\s-]", "", text.lower()).split())
    found = []
    for term in _VAGUE_TERMS:
        if term in words or term.replace("-", "") in words:
            found.append(term)
    return found


class AnalystAgent(BaseAgent):
    """Reviews product_backlog_draft with INVEST checks, vagueness detection,
    duplicate risk assessment, and rationale cross-checking.

    Writes artifacts["analyst_feedback"] — consumed by SprintAgent Pipeline A-Refine.
    """

    # ── Tool docstrings ───────────────────────────────────────────────────────

    _DOC_REVIEW_BACKLOG_ITEMS = (
        "Review a batch of PBIs against INVEST criteria, vagueness, and duplicate risk.\n"
        "For EACH PBI, provide a structured review.\n\n"
        "The 'thought' field is mandatory — explain your reasoning for the severity\n"
        "and every INVEST sub-criterion result.\n\n"
        "Input: {\n"
        "  \"reviews\": [\n"
        "    {\n"
        "      \"pbi_id\":    \"PBI-001\",\n"
        "      \"severity\":  \"high\" | \"medium\" | \"low\" | \"pass\",\n"
        "      \"invest_check\": {\n"
        "        \"independent\": {\"pass\": bool, \"note\": \"<explanation>\"},\n"
        "        \"negotiable\":  {\"pass\": bool, \"note\": \"<explanation>\"},\n"
        "        \"valuable\":    {\"pass\": bool, \"note\": \"<explanation>\"},\n"
        "        \"estimable\":   {\"pass\": bool, \"note\": \"<explanation>\"},\n"
        "        \"small\":       {\"pass\": bool, \"note\": \"<explanation>\"},\n"
        "        \"testable\":    {\"pass\": bool, \"note\": \"<explanation>\"}\n"
        "      },\n"
        "      \"recommendations\": [\"<actionable fix>\", ...],\n"
        "      \"thought\": \"<analyst reasoning citing rationale and stakeholder intent>\"\n"
        "    }, ...\n"
        "  ]\n"
        "}\n"
        "Does NOT end the turn — call 'write_analyst_feedback' next."
    )

    _DOC_WRITE_ANALYST_FEEDBACK = (
        "Persist the analyst_feedback artifact and signal the workflow to continue.\n\n"
        "Input: {\n"
        "  \"overall_quality_score\": <float 0.0–1.0>,\n"
        "  \"recommendations_summary\": \"<3-5 sentence overall assessment>\",\n"
        "  \"notes\": \"<analyst conclusion: is backlog ready for refinement?>\"\n"
        "}\n"
        "This tool ENDS the analyst turn."
    )

    # ── Init ──────────────────────────────────────────────────────────────────

    def __init__(self, config_path=None):
        super().__init__(name="analyst")

    # ── Tool registration ─────────────────────────────────────────────────────

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="review_backlog_items",
            description=self._DOC_REVIEW_BACKLOG_ITEMS,
            func=self._tool_review_backlog_items,
        ))
        self.register_tool(Tool(
            name="write_analyst_feedback",
            description=self._DOC_WRITE_ANALYST_FEEDBACK,
            func=self._tool_write_analyst_feedback,
        ))

    # ── Tool implementations ──────────────────────────────────────────────────

    def _tool_review_backlog_items(
        self,
        reviews: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Validate LLM INVEST reviews, run tool-level vagueness + duplicate checks,
        and merge everything into accumulated_reviews in state.
        """
        reviews = reviews or []
        if not reviews:
            return ToolResult(
                observation="No reviews provided. Supply a 'reviews' list with all PBI assessments."
            )

        artifacts = state.get("artifacts") or {}
        pb_draft  = artifacts.get("product_backlog_draft") or {}
        items     = pb_draft.get("items") or []
        req_rationale_map = self._build_rationale_map(state)

        # Index backlog items for quick lookup
        items_by_id: Dict[str, Dict] = {item.get("id", ""): item for item in items}

        # ── Pre-compute all pairwise duplicate risks ───────────────────────
        dup_risk_map: Dict[str, str] = {}
        desc_list = [(item.get("id",""), item.get("description","") or item.get("title",""))
                     for item in items]
        for i in range(len(desc_list)):
            for j in range(i + 1, len(desc_list)):
                sid_a, text_a = desc_list[i]
                sid_b, text_b = desc_list[j]
                sim = _jaccard(text_a, text_b)
                if sim >= _DUP_HIGH:
                    dup_risk_map[sid_a] = "high"
                    dup_risk_map[sid_b] = "high"
                elif sim >= _DUP_MED:
                    dup_risk_map.setdefault(sid_a, "medium")
                    dup_risk_map.setdefault(sid_b, "medium")

        # ── Accumulate processed reviews ───────────────────────────────────
        accumulated = list(state.get("_analyst_reviews_draft") or [])
        accumulated_ids = {r["pbi_id"] for r in accumulated}

        processed:       List[Dict] = []
        critical_count   = 0
        warnings:        List[str] = []

        for rev in reviews:
            pid = rev.get("pbi_id", "")
            if not pid:
                warnings.append("Review skipped: missing pbi_id.")
                continue
            if pid in accumulated_ids:
                warnings.append(f"{pid} already reviewed — skipping duplicate entry.")
                continue

            item        = items_by_id.get(pid, {})
            description = item.get("description", "") or item.get("title", "")

            # ── Tool-level vagueness detection ─────────────────────────────
            vague = _find_vague_terms(description)

            # ── Augment testable check if vague terms found ────────────────
            invest_check = rev.get("invest_check") or {}
            testable = invest_check.get("testable", {})
            if vague and testable.get("pass", True):
                testable["pass"] = False
                existing_note = testable.get("note", "")
                testable["note"] = (
                    f"Vague terms detected: {vague}. {existing_note}"
                ).strip()
                invest_check["testable"] = testable

            # ── Rationale cross-check for 'valuable' ──────────────────────
            source_req_id = item.get("source_req_id", "")
            rationale     = req_rationale_map.get(source_req_id, "")
            valuable      = invest_check.get("valuable", {})
            if rationale and valuable.get("pass", True):
                # Check for significant word mismatch between rationale and description
                sim_to_rationale = _jaccard(description, rationale)
                if sim_to_rationale < 0.10:
                    valuable["pass"] = False
                    valuable["note"] = (
                        f"Description has low alignment (Jaccard={sim_to_rationale:.2f}) "
                        f"with source rationale for {source_req_id}. "
                        f"Verify stakeholder intent is preserved. "
                        + (valuable.get("note") or "")
                    ).strip()
                    invest_check["valuable"] = valuable

            # ── Compute severity (tool-level escalation logic) ─────────────
            invest_failures = [
                crit for crit, res in invest_check.items()
                if not res.get("pass", True)
            ]
            has_critical_criteria = any(
                c in invest_failures for c in ("testable", "estimable", "valuable")
            )

            llm_severity = rev.get("severity", "pass")
            if invest_failures and has_critical_criteria:
                severity = "high"
            elif invest_failures:
                severity = max(llm_severity, "medium",
                               key=lambda s: {"pass": 0, "low": 1, "medium": 2, "high": 3}.get(s, 0))
            else:
                severity = llm_severity

            if severity == "high":
                critical_count += 1

            # ── Build INVEST summary for observation ───────────────────────
            invest_summary = ", ".join(
                f"{c}={'✓' if r.get('pass', True) else '✗'}"
                for c, r in invest_check.items()
            )

            processed_review = {
                "pbi_id":         pid,
                "source_req_id":  source_req_id,
                "severity":       severity,
                "vague_terms":    vague,
                "invest_check":   invest_check,
                "duplicate_risk": dup_risk_map.get(pid, "low"),
                "recommendations": rev.get("recommendations") or [],
                "thought":        rev.get("thought", ""),
            }
            processed.append(processed_review)
            accumulated.append(processed_review)
            accumulated_ids.add(pid)

        obs_parts = [
            f"Reviewed {len(processed)} PBIs (accumulated total: {len(accumulated)}).",
            f"Critical issues this batch: {critical_count}.",
            "",
            "Batch summary:",
        ]
        for r in processed:
            invest_check = r.get("invest_check") or {}
            fails = [c for c, v in invest_check.items() if not v.get("pass", True)]
            obs_parts.append(
                f"  [{r['pbi_id']}] severity={r['severity']}  "
                f"INVEST fails={fails or '—'}  "
                f"vague={r['vague_terms'] or '—'}  "
                f"dup_risk={r['duplicate_risk']}"
            )
        if warnings:
            obs_parts.append("\nWarnings:\n" + "\n".join(f"  {w}" for w in warnings))

        remaining = [i.get("id") for i in items if i.get("id") not in accumulated_ids]
        if remaining:
            obs_parts.append(
                f"\n{len(remaining)} PBIs not yet reviewed: {remaining[:10]}"
                + (" ..." if len(remaining) > 10 else "")
                + "\nCall 'review_backlog_items' again for the remaining PBIs."
            )
        else:
            obs_parts.append(
                f"\nAll {len(accumulated)} PBIs reviewed."
                "\nNEXT: Call 'write_analyst_feedback' to persist results."
            )

        logger.info(
            "[AnalystAgent] review_backlog_items: %d reviewed, %d critical, "
            "%d accumulated / %d total.",
            len(processed), critical_count, len(accumulated), len(items),
        )

        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={
                "_analyst_reviews_draft": accumulated,
            },
        )

    # ------------------------------------------------------------------

    def _tool_write_analyst_feedback(
        self,
        overall_quality_score: float = 0.5,
        recommendations_summary: str = "",
        notes: str = "",
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Persist the analyst_feedback artifact and clear the draft accumulator."""
        accumulated = list(state.get("_analyst_reviews_draft") or [])
        artifacts   = state.get("artifacts") or {}
        session_id  = state.get("session_id", str(uuid.uuid4()))

        critical_issues = sum(1 for r in accumulated if r.get("severity") == "high")

        # Cap quality score
        overall_quality_score = round(max(0.0, min(float(overall_quality_score), 1.0)), 3)

        analyst_feedback = {
            "session_id":             session_id,
            "reviewed_artifact":      "product_backlog_draft",
            "overall_quality_score":  overall_quality_score,
            "critical_issues":        critical_issues,
            "pbi_reviews":            accumulated,
            "recommendations_summary": recommendations_summary,
            "notes":                  notes,
            "created_at":             datetime.now().isoformat(),
        }

        artifacts["analyst_feedback"] = analyst_feedback

        logger.info(
            "[AnalystAgent] analyst_feedback written — %d PBIs reviewed, "
            "%d critical, quality_score=%.2f.",
            len(accumulated), critical_issues, overall_quality_score,
        )

        obs = (
            f"analyst_feedback artifact written.\n"
            f"  Total PBIs reviewed : {len(accumulated)}\n"
            f"  Critical issues      : {critical_issues}\n"
            f"  Quality score        : {overall_quality_score:.2f}\n"
            f"  Analyst conclusion   : {notes[:200]}\n\n"
            f"SprintAgent will now apply this feedback in Pipeline A-Refine."
        )

        return ToolResult(
            observation=obs,
            state_updates={
                "artifacts":              artifacts,
                "_analyst_reviews_draft": [],   # clear working accumulator
            },
            should_return=True,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_rationale_map(state: Dict) -> Dict[str, str]:
        """Build a mapping from requirement id → rationale string.

        Sources checked in order: reviewed_interview_record, interview_record.
        Used by review_backlog_items to cross-check PBI descriptions.
        """
        artifacts = state.get("artifacts") or {}
        record = (
            artifacts.get("reviewed_interview_record")
            or artifacts.get("interview_record")
            or {}
        )
        requirements = record.get("requirements_identified") or []
        return {
            r.get("id", ""): r.get("rationale", "")
            for r in requirements
            if r.get("id")
        }

    # ── process() ─────────────────────────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph node entry — called by graph.py's analyst_turn_fn.

        Builds a task prompt that includes:
          • Full product_backlog_draft items
          • Requirement rationale table (for valuable/testable cross-checks)
          • Instructions to review ALL PBIs and write analyst_feedback
        """
        artifacts = state.get("artifacts") or {}
        pb_draft  = artifacts.get("product_backlog_draft") or {}
        items     = pb_draft.get("items") or []

        if not items:
            logger.warning("[AnalystAgent] No items in product_backlog_draft — skipping.")
            return {}

        # Requirement rationale table
        req_rationale_map = self._build_rationale_map(state)
        rationale_lines = []
        for req_id, rat in req_rationale_map.items():
            rationale_lines.append(f"  [{req_id}]: {rat[:250]}")
        rationale_table = "\n".join(rationale_lines) or "  (no rationale available)"

        # Backlog items summary with descriptions
        item_lines = []
        for item in items:
            item_lines.append(
                f"  [{item.get('id','?')}] source={item.get('source_req_id','?')}\n"
                f"    Title      : {item.get('title','')}\n"
                f"    Description: {item.get('description','')[:200]}\n"
                f"    Type       : {item.get('type','?')} | "
                f"Points={item.get('story_points','?')} | "
                f"WSJF={item.get('wsjf_score','?')} | "
                f"Rank=#{item.get('priority_rank','?')}"
            )
        items_block = "\n\n".join(item_lines)

        task = (
            f"{'━'*16}  ANALYST REVIEW TASK  {'━'*16}\n\n"
            "You are reviewing the product_backlog_draft produced by SprintAgent.\n"
            "Your goal is to evaluate EVERY PBI using INVEST criteria, detect vague "
            "terms, assess duplicate risk, and cross-check against requirement rationale.\n\n"
            "INVEST criteria:\n"
            "  Independent — can be developed/delivered independently from other stories\n"
            "  Negotiable  — not a rigid contract; scope can be discussed\n"
            "  Valuable    — delivers clear value to the stakeholder (check rationale)\n"
            "  Estimable   — team can size the effort (no black-boxes)\n"
            "  Small       — completable in one sprint (≤ 8 story points is a guideline)\n"
            "  Testable    — has clear acceptance criteria or at least testable conditions\n\n"
            "SEVERITY RULES:\n"
            "  high   — any of: testable/estimable/valuable fails, or story_points ≥ 13\n"
            "  medium — independent or small fails, or vague terms present\n"
            "  low    — negotiable fails or minor wording issue\n"
            "  pass   — all 6 INVEST criteria pass and no vague terms\n\n"
            f"{'━'*16}  REQUIREMENT RATIONALE TABLE  {'━'*16}\n"
            "(Cross-check PBI descriptions against the original stakeholder reasoning.)\n"
            f"{rationale_table}\n\n"
            f"{'━'*16}  BACKLOG ITEMS TO REVIEW ({len(items)})  {'━'*16}\n"
            f"{items_block}\n\n"
            f"{'━'*16}  YOUR PIPELINE  {'━'*16}\n"
            "STEP 1 — Call 'review_backlog_items':\n"
            "  • Provide a 'reviews' list covering ALL PBIs in one call if possible.\n"
            "  • For large backlogs (>15 items), split into batches and call multiple times.\n"
            "  • For each PBI: severity, full invest_check (all 6 criteria with notes),\n"
            "    recommendations (actionable fixes), and thought (your reasoning).\n"
            "  • In 'thought': explicitly reference the requirement rationale when\n"
            "    assessing 'valuable' and 'testable'.\n\n"
            "STEP 2 — Call 'write_analyst_feedback':\n"
            "  • overall_quality_score: float 0.0–1.0 (proportion of PBIs passing INVEST).\n"
            "  • recommendations_summary: 3-5 sentences covering the main patterns.\n"
            "  • notes: your conclusion — is the backlog ready for refinement?\n\n"
            "RULES:\n"
            "• ONE tool per ReAct step.\n"
            "• Review EVERY PBI — do not skip any.\n"
            "• Your feedback drives SprintAgent's Pipeline A-Refine — be specific.\n"
            "• Always provide 'thought' citing the rationale or description text.\n"
        )

        logger.info("[AnalystAgent] Starting review of %d PBIs.", len(items))
        return self.react(state, task)