"""
sprint.py – SprintAgent  (Sprint Zero, step 3)

Role
────
After the interview record is reviewed and approved, the SprintAgent
transforms validated requirements into a prioritised Product Backlog via a
prompt-driven ReAct pipeline.

Pipeline (3 steps + finalizer)
──────────────────────────────
  Step 1 — Triage & Estimate (triage_and_estimate)
    Score each requirement using Fibonacci story points based on three
    dimensions: Complexity, Effort, Uncertainty.
    Validate INVEST quality criteria for each story inline.

  Step 2 — Prioritization (prioritize_backlog)
    Calculate WSJF for every story in the final list:
      WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints
    Rank backlog by WSJF descending.

  Finalizer — write_product_backlog
    Persist the ranked backlog as the product_backlog artifact.

Design notes
────────────
• Each step is a ReAct tool.  The prompt guides the LLM through the
  pipeline order, but the LLM decides naturally when to call each tool.
• The agent maintains a `backlog_draft` in state (same pattern as
  the InterviewerAgent's `requirements_draft`) to accumulate work.
• All tool functions record the agent's `thought` in history entries
  so the reasoning chain is fully traceable.
• INVEST criteria are validated during triage — no separate split step.

ReAct tools
───────────
  triage_and_estimate   — score requirements, validate INVEST, populate backlog_draft
  prioritize_backlog    — WSJF scoring and ranking
  write_product_backlog — finalize artifact → should_return
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

# ── Fibonacci sequence for estimation ─────────────────────────────────────────
_FIBONACCI = {1, 2, 3, 5, 8, 13, 21}

# ── INVEST criteria names ─────────────────────────────────────────────────────
_INVEST_CRITERIA = [
    "independent", "negotiable", "valuable",
    "estimable", "small", "testable",
]


class SprintAgent(BaseAgent):
    """
    Transforms reviewed requirements into a prioritised Product Backlog.

    Pipeline: Triage (with INVEST) → Prioritize → Write.
    All steps are driven by prompt guidance through the ReAct loop.
    """

    PROFILE = """You are an expert Agile Product Backlog Manager.

Mission:
Transform validated requirements into a well-structured, prioritised Product
Backlog using industry-standard estimation, quality-gating, and ranking
techniques.

You MUST follow this pipeline IN ORDER:
1. TRIAGE   — Call 'triage_and_estimate' with ALL requirements scored and INVEST-validated.
2. PRIORITIZE — Call 'prioritize_backlog' to compute WSJF and rank.
3. FINALIZE — Call 'write_product_backlog' with summary notes.

Key principles:
• Fibonacci estimation: 1, 2, 3, 5, 8, 13, 21 only.
• Three scoring dimensions: Complexity, Effort, Uncertainty.
• INVEST: Independent, Negotiable, Valuable, Estimable, Small, Testable.
• WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints."""

    # ── Init ──────────────────────────────────────────────────────────────────

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="sprint_agent")

    # ── Tool registration ─────────────────────────────────────────────────────

    def _register_tools(self) -> None:

        self.register_tool(Tool(
            name="triage_and_estimate",
            description=(
                "Step 1: Score each requirement using Fibonacci story points "
                "and validate INVEST quality criteria.\n"
                "For each requirement, assess Complexity (1-5), Effort (1-5), "
                "and Uncertainty (1-5), then map the sum to the nearest Fibonacci "
                "number as the story point estimate.\n"
                "Also evaluate all 6 INVEST criteria (true/false) for each story.\n"
                "This tool populates the backlog_draft.\n\n"
                "Input: {\n"
                "  \"stories\": [\n"
                "    {\n"
                "      \"source_req_id\":   \"FR-001\",\n"
                "      \"title\":           \"<user story title>\",\n"
                "      \"description\":     \"<story description>\",\n"
                "      \"type\":            \"functional\" | \"non_functional\" | \"constraint\",\n"
                "      \"complexity\":      <1-5>,\n"
                "      \"effort\":          <1-5>,\n"
                "      \"uncertainty\":     <1-5>,\n"
                "      \"story_points\":    <Fibonacci number>,\n"
                "      \"independent\":     true | false,\n"
                "      \"negotiable\":      true | false,\n"
                "      \"valuable\":        true | false,\n"
                "      \"estimable\":       true | false,\n"
                "      \"small\":           true | false,\n"
                "      \"testable\":        true | false,\n"
                "      \"thought\":         \"<your reasoning for this estimate and INVEST assessment>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n"
                "Does NOT end the turn."
            ),
            func=self._tool_triage_and_estimate,
        ))

        self.register_tool(Tool(
            name="prioritize_backlog",
            description=(
                "Step 2: Calculate WSJF scores and rank all stories.\n"
                "WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints\n"
                "All component scores are 1–10.\n\n"
                "Input: {\n"
                "  \"scores\": [\n"
                "    {\n"
                "      \"story_id\":        \"PBI-001\",\n"
                "      \"business_value\":  <1-10>,\n"
                "      \"time_criticality\": <1-10>,\n"
                "      \"risk_reduction\":  <1-10>,\n"
                "      \"thought\":         \"<reasoning for these scores>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n"
                "Does NOT end the turn."
            ),
            func=self._tool_prioritize_backlog,
        ))

        self.register_tool(Tool(
            name="write_product_backlog",
            description=(
                "Step 3: Finalize and persist the product backlog artifact.\n"
                "Reads the backlog_draft from state — do NOT pass the items.\n"
                "Only provide summary notes.\n\n"
                "Input: {\n"
                "  \"notes\": \"<2-3 sentence summary of the backlog>\"\n"
                "}\n"
                "This tool ENDS the turn."
            ),
            func=self._tool_write_product_backlog,
        ))

    # ── Tool implementations ──────────────────────────────────────────────────

    def _tool_triage_and_estimate(
        self,
        stories: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 1: Score requirements, validate INVEST, populate backlog_draft."""
        stories = stories or []
        if not stories:
            return ToolResult(
                observation=(
                    "No stories provided. You must provide a 'stories' list with "
                    "all requirements scored using Fibonacci points and INVEST criteria."
                ),
            )

        react_thought = (state.get("_last_react_thought") or "").strip()
        draft: List[Dict] = list(state.get("backlog_draft") or [])
        created_ids: List[str] = []
        invest_warnings: List[str] = []

        for i, story in enumerate(stories, start=len(draft) + 1):
            story_id = f"PBI-{i:03d}"
            points = story.get("story_points", 5)
            thought = story.get("thought", "").strip() or react_thought

            # Snap to nearest Fibonacci if not already valid
            if points not in _FIBONACCI:
                nearest = min(_FIBONACCI, key=lambda f: abs(f - points))
                thought += f" (snapped {points} → {nearest})"
                points = nearest

            # INVEST validation
            invest_results = {c: story.get(c, True) for c in _INVEST_CRITERIA}
            failed_criteria = [c for c, v in invest_results.items() if not v]

            if failed_criteria:
                invest_warnings.append(
                    f"{story_id} failed INVEST: {failed_criteria}. "
                    "Consider improvements."
                )

            item = {
                "id":             story_id,
                "source_req_id":  story.get("source_req_id"),
                "title":          story.get("title", f"Story {i}"),
                "description":    story.get("description", ""),
                "type":           story.get("type", "functional"),
                "complexity":     story.get("complexity", 3),
                "effort":         story.get("effort", 3),
                "uncertainty":    story.get("uncertainty", 3),
                "story_points":   points,
                "invest":         invest_results,
                "status":         "estimated",
                "priority":       None,   # set in prioritize step
                "wsjf_score":     None,
                "acceptance_criteria": [],
                "history": [{
                    "action": "created",
                    "step":   "triage",
                    "reason": thought or f"Estimated from requirement {story.get('source_req_id', '?')}.",
                    "invest_results": invest_results,
                }],
            }

            draft.append(item)
            created_ids.append(story_id)

        # Build observation
        obs_parts = [
            f"Backlog draft: {len(draft)} stories created.",
            f"  Story IDs: {created_ids[:10]}",
        ]

        if invest_warnings:
            obs_parts.append(
                "INVEST warnings:\n" + "\n".join(f"  {w}" for w in invest_warnings)
            )

        obs_parts.append(
            "\nNEXT: Call 'prioritize_backlog' to compute WSJF scores."
        )

        logger.info(
            "[SprintAgent] triage: %d stories created, %d INVEST warnings.",
            len(created_ids), len(invest_warnings),
        )

        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={"backlog_draft": draft},
        )

    # ------------------------------------------------------------------

    def _tool_prioritize_backlog(
        self,
        scores: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 2: WSJF scoring and ranking."""
        scores = scores or []
        react_thought = (state.get("_last_react_thought") or "").strip()

        if not scores:
            return ToolResult(
                observation="No WSJF scores provided. Supply scores for all estimable stories."
            )

        draft: List[Dict] = list(state.get("backlog_draft") or [])
        draft_by_id = {s.get("id", ""): s for s in draft}

        scored_ids: List[str] = []
        warnings: List[str] = []

        for score in scores:
            sid = score.get("story_id", "")
            thought = score.get("thought", "").strip() or react_thought

            if sid not in draft_by_id:
                warnings.append(f"{sid} not found in draft — skipped.")
                continue

            story = draft_by_id[sid]
            points = story.get("story_points") or 5  # avoid division by zero

            bv = score.get("business_value", 5)
            tc = score.get("time_criticality", 5)
            rr = score.get("risk_reduction", 5)
            wsjf = round((bv + tc + rr) / points, 2)

            story["business_value"] = bv
            story["time_criticality"] = tc
            story["risk_reduction"] = rr
            story["wsjf_score"] = wsjf
            story["status"] = "prioritized"

            story.setdefault("history", []).append({
                "action": "prioritized",
                "step":   "prioritize",
                "reason": thought,
                "wsjf":   wsjf,
                "bv":     bv,
                "tc":     tc,
                "rr":     rr,
            })

            scored_ids.append(sid)

        # Sort all prioritized stories by WSJF descending
        prioritized = [s for s in draft if s.get("wsjf_score") is not None]
        prioritized.sort(key=lambda s: s["wsjf_score"], reverse=True)

        # Assign rank
        for rank, story in enumerate(prioritized, start=1):
            story["priority_rank"] = rank

        obs_parts = [
            f"WSJF scores calculated for {len(scored_ids)} stories.",
            "",
            "Ranked backlog (top 10):",
        ]
        for story in prioritized[:10]:
            obs_parts.append(
                f"  #{story.get('priority_rank', '?')} [{story['id']}] "
                f"WSJF={story['wsjf_score']:.2f} "
                f"(BV={story.get('business_value')}, "
                f"TC={story.get('time_criticality')}, "
                f"RR={story.get('risk_reduction')}) "
                f"pts={story.get('story_points')} "
                f"— {story.get('title', '')[:60]}"
            )

        if warnings:
            obs_parts.append("\nWarnings:\n" + "\n".join(f"  {w}" for w in warnings))

        obs_parts.append(
            "\nNEXT: Call 'write_product_backlog' with summary notes to finalize."
        )

        logger.info(
            "[SprintAgent] prioritize: %d stories scored and ranked by WSJF.",
            len(scored_ids),
        )

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
        """Step 3: Finalize the product_backlog artifact."""
        draft: List[Dict] = list(state.get("backlog_draft") or [])

        # Sort final stories by rank
        final_stories = [
            s for s in draft
            if s.get("status") not in ("invest_failed",)
        ]
        final_stories.sort(
            key=lambda s: s.get("priority_rank") or 999
        )

        artifacts = dict(state.get("artifacts") or {})
        session_id = state.get("session_id", str(uuid.uuid4()))

        product_backlog = {
            "session_id":        session_id,
            "source_artifact":   "reviewed_interview_record",
            "status":            "draft",
            "total_items":       len(final_stories),
            "items":             final_stories,
            "methodology": {
                "estimation":    "Fibonacci (Complexity + Effort + Uncertainty)",
                "quality_gate":  "INVEST",
                "prioritization": "WSJF = (BV + TC + RR) / StoryPoints",
            },
            "notes":             notes,
            "created_at":        datetime.now().isoformat(),
        }

        artifacts["product_backlog"] = product_backlog

        logger.info(
            "[SprintAgent] product_backlog written — %d items.",
            len(final_stories),
        )

        return ToolResult(
            observation=(
                f"Product backlog written. "
                f"{len(final_stories)} final stories. "
                f"Ranked by WSJF descending."
            ),
            state_updates={
                "artifacts": artifacts,
            },
            should_return=True,
        )

    # ── LangGraph node entry point ────────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Called by graph.py's sprint_agent_turn_fn.

        Reads requirements from reviewed_interview_record artifact,
        builds the task prompt, and runs the ReAct loop.
        """
        artifacts = state.get("artifacts") or {}

        # Read from reviewed_interview_record (post-review)
        record = (
            artifacts.get("reviewed_interview_record")
            or artifacts.get("interview_record")
            or {}
        )
        requirements = record.get("requirements_identified") or []
        session_id = state.get("session_id", "unknown")
        project_desc = state.get("project_description", "not provided")

        # Build requirements summary for the prompt
        req_lines = []
        for r in requirements:
            req_lines.append(
                f"  [{r.get('id', '?')}] ({r.get('type', '?')}, "
                f"prio={r.get('priority', '?')}) "
                f"{r.get('description', '')[:120]}\n"
                f"    rationale: {r.get('rationale', '(none)')[:100]}"
            )
        req_summary = "\n".join(req_lines) or "  (no requirements found)"

        # Check if backlog_draft already has items (re-run scenario)
        existing_draft = state.get("backlog_draft") or []
        draft_info = ""
        if existing_draft:
            draft_info = (
                f"\n━━━━━━━━━━━━━━  EXISTING BACKLOG DRAFT  ━━━━━━━━━━━━━━\n"
                f"There are {len(existing_draft)} items already in the draft. "
                f"Review and continue from where you left off.\n"
            )

        task = (
            f"{self.PROFILE}\n\n"
            "━━━━━━━━━━━━━━  PROJECT  ━━━━━━━━━━━━━━\n"
            f"{project_desc}\n\n"
            f"━━━━━━━━━━━━━━  REQUIREMENTS ({len(requirements)})  ━━━━━━━━━━━━━━\n"
            f"{req_summary}\n\n"
            + draft_info
            + "━━━━━━━━━━━━━━  YOUR PIPELINE  ━━━━━━━━━━━━━━\n"
            "Execute these steps IN ORDER:\n\n"
            "STEP 1 — Call 'triage_and_estimate':\n"
            "  • Create a user story for each requirement.\n"
            "  • Assess Complexity (1-5), Effort (1-5), Uncertainty (1-5).\n"
            "  • Map to nearest Fibonacci story points (1,2,3,5,8,13,21).\n"
            "  • Evaluate INVEST criteria (true/false) for each story.\n"
            "  • Provide your 'thought' explaining WHY you gave those scores.\n\n"
            "STEP 2 — Call 'prioritize_backlog':\n"
            "  • Score each story: business_value (1-10), "
            "time_criticality (1-10), risk_reduction (1-10).\n"
            "  • WSJF is computed automatically.\n"
            "  • Provide 'thought' for each score.\n\n"
            "STEP 3 — Call 'write_product_backlog':\n"
            "  • Provide a brief summary in 'notes'.\n\n"
            "RULES:\n"
            "• ONE tool per ReAct step.\n"
            "• Always provide 'thought' explaining your reasoning.\n"
            "• Fibonacci values only: 1, 2, 3, 5, 8, 13, 21.\n"
        )

        return self.react(state, task)