"""
sprint.py – SprintAgent  (Sprint Zero step 3: Build Product Backlog)

Role
────
The SprintAgent runs once after the interview record is approved by the human
reviewer.  It converts every approved requirement into a User Story and
assembles the initial Product Backlog.

User Story format (mandatory)
─────────────────────────────
Every PBI description MUST follow the standard user story template:
  "As a <role>, I can <capability>, so that <benefit>."

This mirrors the product backlog example format and gives developers
unambiguous, role-centred acceptance anchors.

Build sequence (one ReAct tool per step)
─────────────────────────────────────────
  1. triage_and_estimate   — Convert requirements to user stories;
                             score with Fibonacci estimation + INVEST.
  2. prioritize_backlog    — Compute WSJF scores and assign rank order.
  3. write_product_backlog — Persist the product_backlog artifact.

State fields used
─────────────────
  backlog_draft         — Working list during triage / prioritisation.
  artifacts             — Shared artifact store (read + write).
  reviewed_interview_record — Source of requirements (read-only).
  product_backlog_feedback  — Injected on rejection; triggers a rebuild.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

_FIBONACCI = {1, 2, 3, 5, 8, 13, 21}

_INVEST_CRITERIA = [
    "independent", "negotiable", "valuable",
    "estimable", "small", "testable",
]

_DEFAULT_SPRINT_CAPACITY = 20


class SprintAgent(BaseAgent):
    """
    Builds the initial product backlog from approved requirements.

    process() is the single LangGraph node entry point.
    If product_backlog already exists, it logs a warning and returns empty
    (supervisor should not have routed here again).
    """

    _AGENT_PROFILE = """You are an expert Agile Product Backlog Manager.

Mission:
Transform validated requirements into a well-structured, prioritised Product
Backlog using industry-standard estimation, quality-gating, and ranking
techniques.

You MUST follow this sequence IN ORDER:
1. TRIAGE     — Call 'triage_and_estimate' with ALL requirements converted to user stories.
2. PRIORITIZE — Call 'prioritize_backlog' to compute WSJF and rank.
3. FINALIZE   — Call 'write_product_backlog' with summary notes.

Key principles:
• Every PBI description is a USER STORY:
  "As a <role>, I can <capability>, so that <benefit>."
  — Role       : concrete actor (site visitor, admin, trainer, student, …)
  — Capability : what they CAN DO (present tense, action verb)
  — Benefit    : the value / outcome ("so that …")
• Fibonacci estimation: 1, 2, 3, 5, 8, 13, 21 only.
• Three scoring dimensions: Complexity (1-5), Effort (1-5), Uncertainty (1-5).
• INVEST: Independent, Negotiable, Valuable, Estimable, Small, Testable.
• WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints."""

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="sprint_agent")

    # ── Tool registration ─────────────────────────────────────────────────────

    def _register_tools(self) -> None:

        self.register_tool(Tool(
            name="triage_and_estimate",
            description=(
                "Step 1 — Convert each requirement into a User Story and score it.\n\n"
                "CRITICAL: The 'description' field of every story MUST be a user story:\n"
                "  'As a <role>, I can <capability>, so that <benefit>.'\n\n"
                "Score each story using Complexity (1-5), Effort (1-5), Uncertainty (1-5);\n"
                "map the total to the nearest Fibonacci number.\n"
                "Evaluate all 6 INVEST criteria (true/false) for each story.\n\n"
                "Input: {\n"
                "  \"stories\": [\n"
                "    {\n"
                "      \"source_req_id\": \"FR-001\",\n"
                "      \"title\":         \"<short story title (5-8 words)>\",\n"
                "      \"description\":   \"As a <role>, I can <capability>, so that <benefit>.\",\n"
                "      \"type\":          \"functional\" | \"non_functional\" | \"constraint\",\n"
                "      \"complexity\":    <1-5>,\n"
                "      \"effort\":        <1-5>,\n"
                "      \"uncertainty\":   <1-5>,\n"
                "      \"story_points\":  <Fibonacci>,\n"
                "      \"independent\":   true|false,\n"
                "      \"negotiable\":    true|false,\n"
                "      \"valuable\":      true|false,\n"
                "      \"estimable\":     true|false,\n"
                "      \"small\":         true|false,\n"
                "      \"testable\":      true|false,\n"
                "      \"thought\":       \"<reasoning for estimation and story formulation>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n"
                "Does NOT end the turn. NEXT: call 'prioritize_backlog'."
            ),
            func=self._tool_triage_and_estimate,
        ))

        self.register_tool(Tool(
            name="prioritize_backlog",
            description=(
                "Step 2 — Calculate WSJF scores and rank all stories.\n"
                "WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints\n"
                "All component scores are 1-10.\n\n"
                "Input: {\n"
                "  \"scores\": [\n"
                "    {\n"
                "      \"story_id\":         \"PBI-001\",\n"
                "      \"business_value\":   <1-10>,\n"
                "      \"time_criticality\": <1-10>,\n"
                "      \"risk_reduction\":   <1-10>,\n"
                "      \"thought\":          \"<reasoning>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n"
                "Does NOT end the turn. NEXT: call 'write_product_backlog'."
            ),
            func=self._tool_prioritize_backlog,
        ))

        self.register_tool(Tool(
            name="write_product_backlog",
            description=(
                "Step 3 — Finalise and persist the product_backlog artifact.\n"
                "Reads backlog_draft from state automatically. Only provide notes.\n\n"
                "Input: {\"notes\": \"<2-3 sentence summary>\"}\n"
                "This tool ENDS the turn."
            ),
            func=self._tool_write_product_backlog,
        ))

    # =========================================================================
    # Tool implementations
    # =========================================================================

    def _tool_triage_and_estimate(
        self,
        stories: List[Dict] = None,
        state:   Dict = None,
        **_,
    ) -> ToolResult:
        """Convert requirements to user stories, score, populate backlog_draft."""
        stories = stories or []
        if not stories:
            return ToolResult(
                observation=(
                    "No stories provided. Supply a 'stories' list with all "
                    "requirements converted to user stories and scored."
                ),
            )

        react_thought    = (state.get("_last_react_thought") or "").strip()
        draft: List[Dict] = list(state.get("backlog_draft") or [])
        created_ids:     List[str] = []
        invest_warnings: List[str] = []
        format_warnings: List[str] = []

        for i, story in enumerate(stories, start=len(draft) + 1):
            story_id    = f"PBI-{i:03d}"
            points      = story.get("story_points", 5)
            thought     = story.get("thought", "").strip() or react_thought
            description = story.get("description", "").strip()

            # Validate user story format
            desc_lower = description.lower()
            if not (desc_lower.startswith("as a") or desc_lower.startswith("as an")):
                format_warnings.append(
                    f"{story_id}: description must start with 'As a <role>, …' "
                    f"(got: '{description[:60]}'). Provide a proper user story."
                )

            # Snap to nearest Fibonacci if not valid
            if points not in _FIBONACCI:
                nearest = min(_FIBONACCI, key=lambda f: abs(f - points))
                thought += f" (snapped {points} → {nearest})"
                points   = nearest

            invest_results  = {c: story.get(c, True) for c in _INVEST_CRITERIA}
            failed_criteria = [c for c, v in invest_results.items() if not v]
            if failed_criteria:
                invest_warnings.append(f"{story_id} failed INVEST: {failed_criteria}.")

            item = {
                "id":             story_id,
                "source_req_id":  story.get("source_req_id"),
                "title":          story.get("title", f"Story {i}"),
                "description":    description,
                "type":           story.get("type", "functional"),
                "complexity":     story.get("complexity", 3),
                "effort":         story.get("effort", 3),
                "uncertainty":    story.get("uncertainty", 3),
                "story_points":   points,
                "invest":         invest_results,
                "status":         "estimated",
                "priority":       None,
                "wsjf_score":     None,
                "priority_rank":  None,
                "acceptance_criteria": [],
                "history": [{
                    "action": "created",
                    "step":   "triage",
                    "reason": thought or f"Converted from {story.get('source_req_id', '?')}.",
                    "invest_results": invest_results,
                }],
            }
            draft.append(item)
            created_ids.append(story_id)

        obs_parts = [f"Backlog draft: {len(draft)} user stories created."]
        if format_warnings:
            obs_parts.append(
                "⚠ User story format warnings:\n"
                + "\n".join(f"  {w}" for w in format_warnings)
            )
        if invest_warnings:
            obs_parts.append(
                "INVEST warnings:\n" + "\n".join(f"  {w}" for w in invest_warnings)
            )
        obs_parts.append("\nNEXT: Call 'prioritize_backlog' to compute WSJF scores.")

        logger.info(
            "[SprintAgent] triage: %d stories, %d INVEST warnings, %d format warnings.",
            len(created_ids), len(invest_warnings), len(format_warnings),
        )
        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={"backlog_draft": draft},
        )

    # ------------------------------------------------------------------

    def _tool_prioritize_backlog(
        self,
        scores: List[Dict] = None,
        state:  Dict = None,
        **_,
    ) -> ToolResult:
        """Compute WSJF scores and rank all stories."""
        scores        = scores or []
        react_thought = (state.get("_last_react_thought") or "").strip()

        if not scores:
            return ToolResult(
                observation="No WSJF scores provided. Supply scores for all stories."
            )

        draft: List[Dict] = list(state.get("backlog_draft") or [])
        draft_by_id       = {s.get("id", ""): s for s in draft}
        scored_ids:  List[str] = []
        warnings:    List[str] = []

        for score in scores:
            sid    = score.get("story_id", "")
            thought = score.get("thought", "").strip() or react_thought

            if sid not in draft_by_id:
                warnings.append(f"{sid} not found — skipped.")
                continue

            story  = draft_by_id[sid]
            points = story.get("story_points") or 5
            bv  = score.get("business_value", 5)
            tc  = score.get("time_criticality", 5)
            rr  = score.get("risk_reduction", 5)
            wsjf = round((bv + tc + rr) / points, 2)

            story.update({
                "business_value":   bv,
                "time_criticality": tc,
                "risk_reduction":   rr,
                "wsjf_score":       wsjf,
                "status":           "prioritized",
            })
            story.setdefault("history", []).append({
                "action": "prioritized", "step": "prioritize",
                "reason": thought, "wsjf": wsjf,
                "bv": bv, "tc": tc, "rr": rr,
            })
            scored_ids.append(sid)

        # Sort by WSJF descending and assign rank
        prioritized = sorted(
            [s for s in draft if s.get("wsjf_score") is not None],
            key=lambda s: s["wsjf_score"], reverse=True,
        )
        for rank, story in enumerate(prioritized, start=1):
            story["priority_rank"] = rank

        obs_parts = [
            f"WSJF scores calculated for {len(scored_ids)} stories.",
            "",
            "Ranked backlog (top 10):",
        ]
        for story in prioritized[:10]:
            obs_parts.append(
                f"  #{story.get('priority_rank','?')} [{story['id']}] "
                f"WSJF={story['wsjf_score']:.2f} "
                f"(BV={story.get('business_value')}, "
                f"TC={story.get('time_criticality')}, "
                f"RR={story.get('risk_reduction')}) "
                f"pts={story.get('story_points')} "
                f"— {story.get('title','')[:60]}"
            )
        if warnings:
            obs_parts.append("\nWarnings:\n" + "\n".join(f"  {w}" for w in warnings))
        obs_parts.append("\nNEXT: Call 'write_product_backlog' with summary notes.")

        logger.info("[SprintAgent] prioritize: %d stories ranked.", len(scored_ids))
        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={"backlog_draft": draft},
        )

    # ------------------------------------------------------------------

    def _tool_write_product_backlog(
        self,
        notes: str = "",
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Persist the product_backlog artifact."""
        draft: List[Dict] = list(state.get("backlog_draft") or [])
        final_stories = sorted(
            [s for s in draft if s.get("status") != "invest_failed"],
            key=lambda s: s.get("priority_rank") or 999,
        )

        artifacts  = dict(state.get("artifacts") or {})
        session_id = state.get("session_id", str(uuid.uuid4()))

        product_backlog = {
            "id":               str(uuid.uuid4()),
            "session_id":       session_id,
            "source_artifact":  "reviewed_interview_record",
            "status":           "draft",
            "total_items":      len(final_stories),
            "items":            final_stories,
            "methodology": {
                "story_format":   "As a <role>, I can <capability>, so that <benefit>.",
                "estimation":     "Fibonacci (Complexity + Effort + Uncertainty)",
                "quality_gate":   "INVEST",
                "prioritization": "WSJF = (BV + TC + RR) / StoryPoints",
            },
            "notes":      notes,
            "created_at": datetime.now().isoformat(),
        }
        artifacts["product_backlog"] = product_backlog

        logger.info("[SprintAgent] product_backlog written — %d items.", len(final_stories))
        return ToolResult(
            observation=(
                f"Product backlog written — {len(final_stories)} user stories "
                f"ranked by WSJF descending.\n"
                f"The workflow will now route to Product Owner review."
            ),
            state_updates={"artifacts": artifacts},
            should_return=True,
        )

    # =========================================================================
    # LangGraph node entry point
    # =========================================================================

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        LangGraph node entry point — called by sprint_agent_turn_fn in graph.py.

        Runs only when product_backlog is absent from artifacts.
        If already present, logs a warning and returns empty.
        """
        artifacts = state.get("artifacts") or {}
        if "product_backlog" in artifacts:
            logger.warning(
                "[SprintAgent] process() called but product_backlog already exists. "
                "Supervisor should not have routed here."
            )
            return {}

        return self._build_product_backlog(state)

    # ── Backlog build entry ───────────────────────────────────────────────────

    def _build_product_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Build the product backlog from the reviewed interview record."""
        artifacts    = state.get("artifacts") or {}
        record = (
            artifacts.get("reviewed_interview_record")
            or artifacts.get("interview_record")
            or {}
        )
        requirements = record.get("requirements_identified") or []
        project_desc = state.get("project_description", "not provided")

        req_lines = []
        for r in requirements:
            req_lines.append(
                f"  [{r.get('id','?')}] ({r.get('type','?')}, "
                f"prio={r.get('priority','?')}) "
                f"{r.get('description','')[:120]}\n"
                f"    rationale: {r.get('rationale','(none)')[:100]}"
            )
        req_summary = "\n".join(req_lines) or "  (no requirements found)"

        existing_draft = state.get("backlog_draft") or []
        draft_info = ""
        if existing_draft:
            draft_info = (
                f"\n{'━'*44}  EXISTING BACKLOG DRAFT ({len(existing_draft)} items)  {'━'*16}\n"
                "Continue from where you left off.\n"
            )

        # Inject PO feedback when rebuilding after rejection
        po_feedback = (state.get("product_backlog_feedback") or "").strip()
        feedback_block = ""
        if po_feedback:
            feedback_block = (
                f"{'━'*16}  PRODUCT OWNER FEEDBACK (previous backlog was REJECTED)  {'━'*16}\n"
                f"{po_feedback}\n\n"
                "You MUST address ALL points above when rebuilding the backlog.\n\n"
            )

        task = (
            f"{'━'*16}  PROJECT  {'━'*16}\n"
            f"{project_desc}\n\n"
            + feedback_block
            + f"{'━'*16}  REQUIREMENTS ({len(requirements)})  {'━'*16}\n"
            f"{req_summary}\n\n"
            + draft_info
            + f"{'━'*16}  YOUR TASK  {'━'*16}\n"
            "Execute these steps IN ORDER:\n\n"
            "STEP 1 — Call 'triage_and_estimate':\n"
            "  • Convert EACH requirement into a User Story.\n"
            "  • USER STORY FORMAT (mandatory):\n"
            "      'As a <role>, I can <capability>, so that <benefit>.'\n"
            "    Examples:\n"
            "      'As a site visitor, I can see a list of upcoming courses and page\n"
            "       through them, so that I can choose the best course for me.'\n"
            "      'As a trainer, I can create a new course with full details, so that\n"
            "       site visitors can discover and register for it.'\n"
            "  • Role must be a CONCRETE actor (student, admin, trainer, visitor…).\n"
            "  • Capability must use an ACTION verb in present tense.\n"
            "  • Benefit ('so that…') must state the user's goal / value.\n"
            "  • Assess Complexity (1-5), Effort (1-5), Uncertainty (1-5).\n"
            "  • Map to nearest Fibonacci story points (1, 2, 3, 5, 8, 13, 21).\n"
            "  • Evaluate INVEST criteria (true/false) for each story.\n"
            "  • Provide 'thought' explaining your estimation and story formulation.\n\n"
            "STEP 2 — Call 'prioritize_backlog':\n"
            "  • Score each story: business_value, time_criticality, "
            "risk_reduction (all 1-10).\n"
            "  • WSJF is computed automatically.\n"
            "  • Provide 'thought' for each score.\n\n"
            "STEP 3 — Call 'write_product_backlog':\n"
            "  • Provide a brief 'notes' summary (2-3 sentences).\n\n"
            "RULES:\n"
            "• ONE tool per ReAct step.\n"
            "• Every Thought must start with [STRATEGY]...[/STRATEGY].\n"
            "• EVERY description MUST be a user story — 'As a …, I can …, so that …'.\n"
            "• Fibonacci values only: 1, 2, 3, 5, 8, 13, 21.\n"
        )

        logger.info(
            "[SprintAgent] Building product backlog from %d requirements.", len(requirements)
        )
        return self.react(state, task, tool_choice="required")