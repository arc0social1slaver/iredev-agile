"""
sprint.py – SprintAgent  (Sprint Zero step 3a/3b/3c + Sprint Execution step B)

Role
────
The SprintAgent has ONE entry point — process() — which detects its current
task from state and runs the appropriate pipeline:

  Pipeline A-Draft — Build Product Backlog Draft
  ───────────────────────────────────────────────
  Triggered when: product_backlog_draft is NOT yet in artifacts.
  Input : reviewed_interview_record
  Output: product_backlog_draft

  Steps (one ReAct tool per step):
    1. triage_and_estimate   — Fibonacci scoring ONLY (INVEST delegated to Analyst)
    2. prioritize_backlog    — WSJF scoring + rank
    3. write_product_backlog_draft — persist draft artifact

  Pipeline A-Refine — Apply Analyst Feedback → Final Backlog
  ───────────────────────────────────────────────────────────
  Triggered when: product_backlog_draft IN artifacts AND
                  analyst_feedback      IN artifacts AND
                  product_backlog       NOT in artifacts.
  Input : product_backlog_draft + analyst_feedback + (optional) requirement rationale
  Output: product_backlog

  Steps:
    1. apply_analyst_feedback — apply per-PBI analyst recommendations;
                                may query requirement rationale from interview record
    2. write_product_backlog  — persist final product_backlog artifact

  Pipeline B — Plan Sprint Backlog
  ──────────────────────────────────
  Triggered when: product_backlog IS in artifacts AND
                  _sprint_feedback_ready IS in artifacts.
  Input : product_backlog + sprint_feedback
  Output: sprint_backlog_<N>

  Steps:
    1. analyse_dependencies  — map hard/soft dependency links
    2. write_sprint_backlog  — capacity-aware, dependency-respecting selection

Rationale access
────────────────
In Pipeline A-Refine, the task prompt embeds the full rationale of each
source requirement so the agent can cross-check analyst findings against
the original elicitation reasoning before modifying a PBI.

INVEST handoff
──────────────
INVEST quality criteria are fully delegated to AnalystAgent.
SprintAgent is responsible for Fibonacci estimation and WSJF prioritisation only.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

# ── Fibonacci sequence ────────────────────────────────────────────────────────
_FIBONACCI = {1, 2, 3, 5, 8, 13, 21}

# ── Default sprint capacity ───────────────────────────────────────────────────
_DEFAULT_SPRINT_CAPACITY = 20


class SprintAgent(BaseAgent):
    """Unified agent for product backlog creation and sprint backlog planning."""

    # ── Inline profile snippets ───────────────────────────────────────────────
    # NOTE: These are injected into the task string, not the system prompt.
    # The system prompt comes from sprint_agent_react.txt via ProfileModule.

    _PROFILE_A_DRAFT = """You are an expert Agile Product Backlog Manager.

Mission:
Transform validated requirements into a well-structured, prioritised Product
Backlog draft using Fibonacci estimation and WSJF ranking.

NOTE: INVEST quality-gate is handled by a dedicated Analyst Agent AFTER this
draft. Your job here is accurate estimation and WSJF prioritisation only.

You MUST follow this pipeline IN ORDER:
1. TRIAGE     — Call 'triage_and_estimate' with ALL requirements scored.
2. PRIORITIZE — Call 'prioritize_backlog' to compute WSJF and rank.
3. DRAFT      — Call 'write_product_backlog_draft' with summary notes.

Key principles:
• Fibonacci estimation: 1, 2, 3, 5, 8, 13, 21 only.
• Three scoring dimensions: Complexity (1-5), Effort (1-5), Uncertainty (1-5).
• You MAY consult the requirement rationale (provided below) to understand
  scope before estimating.
• WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints."""

    _PROFILE_A_REFINE = """You are an expert Agile Product Backlog Manager.

Mission:
Apply AnalystAgent feedback to improve a Product Backlog draft and produce
the final, publication-quality Product Backlog artifact.

You MUST follow this pipeline IN ORDER:
1. APPLY  — Call 'apply_analyst_feedback' with ALL revisions to address
             analyst recommendations. You MAY use the requirement rationale
             (provided below) to validate or override analyst suggestions.
2. WRITE  — Call 'write_product_backlog' to persist the final artifact.

Key principles:
• You have full authority to disagree with analyst suggestions IF the
  original requirement rationale supports the current description.
• When splitting stories, preserve WSJF ordering for sub-stories.
• All revisions must cite the analyst recommendation being addressed."""

    _PROFILE_B = """You are an expert Agile Sprint Planner.

Mission:
Select the right Product Backlog Items (PBIs) for a sprint from a prioritised
Product Backlog. Your selection must respect story-point capacity, item
priority (priority_rank), and inter-item dependencies.

You MUST follow this pipeline IN ORDER:
1. ANALYSE — Call 'analyse_dependencies' to map dependency links between PBIs.
2. PLAN    — Call 'write_sprint_backlog' to select items and write the artifact.

Key principles:
• Highest-priority items (lowest priority_rank number) go first.
• A PBI with unsatisfied HARD dependencies MUST NOT be selected unless all
  its dependencies are also selected or already completed.
• Do not exceed the sprint capacity (story points).
• Record your reasoning for every include / exclude decision."""

    # ── Init ──────────────────────────────────────────────────────────────────

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="sprint_agent")

    # ── Tool registration ─────────────────────────────────────────────────────

    def _register_tools(self) -> None:

        # ── Pipeline A-Draft ──────────────────────────────────────────────
        self.register_tool(Tool(
            name="triage_and_estimate",
            description=(
                "Pipeline A-Draft — Step 1: Score each requirement using Fibonacci "
                "story points.\n"
                "Assess Complexity (1-5), Effort (1-5), Uncertainty (1-5) for each "
                "requirement; map the sum to the nearest Fibonacci number.\n"
                "NOTE: INVEST criteria are NOT evaluated here — they are handled by "
                "the dedicated Analyst Agent in the next workflow step.\n\n"
                "Input: {\n"
                "  \"stories\": [\n"
                "    {\n"
                "      \"source_req_id\": \"FR-001\",\n"
                "      \"title\":         \"<story title>\",\n"
                "      \"description\":   \"<user story: As a ... I want ... So that ...>\",\n"
                "      \"type\":          \"functional\" | \"non_functional\" | \"constraint\",\n"
                "      \"complexity\":    <1-5>,\n"
                "      \"effort\":        <1-5>,\n"
                "      \"uncertainty\":   <1-5>,\n"
                "      \"story_points\":  <Fibonacci: 1|2|3|5|8|13|21>,\n"
                "      \"thought\":       \"<estimation reasoning>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n"
                "Does NOT end the turn — call 'prioritize_backlog' next."
            ),
            func=self._tool_triage_and_estimate,
        ))

        self.register_tool(Tool(
            name="prioritize_backlog",
            description=(
                "Pipeline A-Draft — Step 2: Calculate WSJF scores and rank all stories.\n"
                "WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints.\n"
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
                "Does NOT end the turn — call 'write_product_backlog_draft' next."
            ),
            func=self._tool_prioritize_backlog,
        ))

        self.register_tool(Tool(
            name="write_product_backlog_draft",
            description=(
                "Pipeline A-Draft — Step 3: Persist the initial product_backlog_draft artifact.\n"
                "This is the PRE-analyst version. After this, the Analyst Agent will review\n"
                "and return feedback, then you will refine it into the final product_backlog.\n\n"
                "Input: {\"notes\": \"<2-3 sentence summary>\"}\n"
                "This tool ENDS the draft turn."
            ),
            func=self._tool_write_product_backlog_draft,
        ))

        # ── Pipeline A-Refine ─────────────────────────────────────────────
        self.register_tool(Tool(
            name="apply_analyst_feedback",
            description=(
                "Pipeline A-Refine — Step 1: Apply AnalystAgent recommendations to "
                "the backlog draft.\n"
                "For each PBI with analyst findings, you may:\n"
                "  • Rewrite the title or description\n"
                "  • Add acceptance criteria (Given-When-Then format preferred)\n"
                "  • Adjust story points\n"
                "  • Split a large story into sub-stories\n"
                "  • Override analyst suggestion (cite requirement rationale as basis)\n\n"
                "You MAY consult the requirement rationale table in the task prompt to\n"
                "validate or override analyst suggestions before applying them.\n\n"
                "Input: {\n"
                "  \"revisions\": [\n"
                "    {\n"
                "      \"pbi_id\":              \"PBI-001\",\n"
                "      \"title\":               \"<new title or omit to keep>\",\n"
                "      \"description\":         \"<new description or omit to keep>\",\n"
                "      \"acceptance_criteria\": [\"Given ... When ... Then ...\", ...],\n"
                "      \"story_points\":        <Fibonacci or omit>,\n"
                "      \"split_into\": [\n"
                "        {\"title\": \"...\", \"description\": \"...\",\n"
                "         \"complexity\": 2, \"effort\": 2, \"uncertainty\": 1,\n"
                "         \"story_points\": 3,\n"
                "         \"acceptance_criteria\": [\"...\"]},\n"
                "        ...\n"
                "      ],\n"
                "      \"analyst_recommendation_addressed\": \"<which finding this resolves>\",\n"
                "      \"thought\": \"<your reasoning>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n"
                "Does NOT end the turn — call 'write_product_backlog' next."
            ),
            func=self._tool_apply_analyst_feedback,
        ))

        self.register_tool(Tool(
            name="write_product_backlog",
            description=(
                "Pipeline A-Refine — Step 2: Persist the FINAL product_backlog artifact.\n"
                "This is the post-analyst, publication-quality backlog.\n\n"
                "Input: {\"notes\": \"<2-3 sentence summary of changes from draft>\"}\n"
                "This tool ENDS the refine turn."
            ),
            func=self._tool_write_product_backlog,
        ))

        # ── Pipeline B ────────────────────────────────────────────────────
        self.register_tool(Tool(
            name="analyse_dependencies",
            description=(
                "Pipeline B — Step 1: Identify dependency links between PBIs.\n\n"
                "For each PBI declare:\n"
                "  depends_on — list of PBI IDs that MUST finish before this one\n"
                "               (hard dep: blocks selection if unmet)\n"
                "  enables    — list of PBI IDs this item unlocks (informational)\n"
                "  dep_type   — 'hard' | 'soft' | 'none'\n"
                "  thought    — your reasoning\n\n"
                "Input: {\n"
                "  \"dependencies\": [\n"
                "    {\n"
                "      \"story_id\":   \"PBI-001\",\n"
                "      \"depends_on\": [\"PBI-005\"],\n"
                "      \"enables\":    [\"PBI-002\"],\n"
                "      \"dep_type\":   \"hard\",\n"
                "      \"thought\":    \"<why>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n"
                "Does NOT end the turn — call 'write_sprint_backlog' next."
            ),
            func=self._tool_analyse_dependencies,
        ))

        self.register_tool(Tool(
            name="write_sprint_backlog",
            description=(
                "Pipeline B — Step 2: Select PBIs for a sprint and persist the artifact.\n\n"
                "Selection rules (enforced by the tool):\n"
                "  1. Work through PBIs by priority_rank ascending (1 = highest).\n"
                "  2. Skip any PBI whose hard dependencies are not completed or selected.\n"
                "  3. Stop when adding the next item would exceed capacity_points.\n\n"
                "Input: {\n"
                "  \"sprint_number\":      <int>,\n"
                "  \"sprint_goal\":        \"<one-sentence goal>\",\n"
                "  \"capacity_points\":    <int>,\n"
                "  \"completed_pbi_ids\": [\"PBI-xxx\", ...],\n"
                "  \"selections\": [\n"
                "    {\n"
                "      \"story_id\": \"PBI-001\",\n"
                "      \"included\": true|false,\n"
                "      \"reason\":   \"<why included or excluded>\"\n"
                "    }, ...\n"
                "  ],\n"
                "  \"notes\": \"<brief sprint summary>\"\n"
                "}\n"
                "This tool ENDS the turn."
            ),
            func=self._tool_write_sprint_backlog,
        ))

    # =========================================================================
    # Pipeline A-Draft — tools
    # =========================================================================

    def _tool_triage_and_estimate(
        self,
        stories: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 1 (Pipeline A-Draft): Fibonacci estimation only — no INVEST."""
        stories = stories or []
        if not stories:
            return ToolResult(
                observation=(
                    "No stories provided. Supply a 'stories' list with all "
                    "requirements scored."
                ),
            )

        react_thought = (state.get("_last_react_thought") or "").strip()
        draft: List[Dict] = list(state.get("backlog_draft") or [])
        created_ids: List[str] = []

        for i, story in enumerate(stories, start=len(draft) + 1):
            story_id = f"PBI-{i:03d}"
            points   = story.get("story_points", 5)
            thought  = story.get("thought", "").strip() or react_thought

            # Snap to nearest Fibonacci
            if points not in _FIBONACCI:
                nearest = min(_FIBONACCI, key=lambda f: abs(f - points))
                thought += f" (snapped {points}→{nearest})"
                points   = nearest

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
                "acceptance_criteria": [],
                # INVEST + WSJF filled by Analyst + prioritize_backlog respectively
                "invest":         None,   # filled by AnalystAgent
                "status":         "estimated",
                "priority":       None,
                "wsjf_score":     None,
                "priority_rank":  None,
                # dependency fields — populated by Pipeline B
                "depends_on": [],
                "enables":    [],
                "dep_type":   "none",
                "history": [{
                    "action": "created",
                    "step":   "triage",
                    "reason": thought or f"Estimated from {story.get('source_req_id', '?')}.",
                }],
            }
            draft.append(item)
            created_ids.append(story_id)

        logger.info("[SprintAgent/A-Draft] triage: %d stories.", len(created_ids))

        return ToolResult(
            observation=(
                f"Backlog draft: {len(draft)} stories created.\n"
                f"Note: INVEST evaluation is delegated to the Analyst Agent.\n"
                f"\nNEXT: Call 'prioritize_backlog' to compute WSJF scores."
            ),
            state_updates={"backlog_draft": draft},
        )

    # ------------------------------------------------------------------

    def _tool_prioritize_backlog(
        self,
        scores: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 2 (Pipeline A-Draft): WSJF scoring and ranking."""
        scores = scores or []
        react_thought = (state.get("_last_react_thought") or "").strip()

        if not scores:
            return ToolResult(
                observation="No WSJF scores provided. Supply scores for all stories."
            )

        draft: List[Dict] = list(state.get("backlog_draft") or [])
        draft_by_id = {s.get("id", ""): s for s in draft}
        scored_ids: List[str] = []
        warnings:   List[str] = []

        for score in scores:
            sid    = score.get("story_id", "")
            thought = score.get("thought", "").strip() or react_thought

            if sid not in draft_by_id:
                warnings.append(f"{sid} not found — skipped.")
                continue

            story  = draft_by_id[sid]
            points = story.get("story_points") or 5
            bv = score.get("business_value", 5)
            tc = score.get("time_criticality", 5)
            rr = score.get("risk_reduction", 5)
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

        # Sort and assign ranks
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
        obs_parts.append("\nNEXT: Call 'write_product_backlog_draft' with summary notes.")

        logger.info("[SprintAgent/A-Draft] prioritize: %d stories ranked.", len(scored_ids))

        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={"backlog_draft": draft},
        )

    # ------------------------------------------------------------------

    def _tool_write_product_backlog_draft(
        self,
        notes: str = "",
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 3 (Pipeline A-Draft): Persist product_backlog_draft artifact.

        This is the PRE-analyst version. The Analyst Agent will review it and
        return per-PBI feedback. The final product_backlog is written in Pipeline A-Refine.
        """
        draft: List[Dict] = list(state.get("backlog_draft") or [])
        final_stories = sorted(
            draft,
            key=lambda s: s.get("priority_rank") or 999,
        )

        artifacts  = dict(state.get("artifacts") or {})
        session_id = state.get("session_id", str(uuid.uuid4()))

        product_backlog_draft = {
            "session_id":      session_id,
            "source_artifact": "reviewed_interview_record",
            "status":          "draft_pending_analyst_review",
            "total_items":     len(final_stories),
            "items":           final_stories,
            "methodology": {
                "estimation":     "Fibonacci (Complexity + Effort + Uncertainty)",
                "quality_gate":   "Pending — AnalystAgent INVEST review",
                "prioritization": "WSJF = (BV + TC + RR) / StoryPoints",
            },
            "notes":      notes,
            "created_at": datetime.now().isoformat(),
        }
        artifacts["product_backlog_draft"] = product_backlog_draft

        logger.info(
            "[SprintAgent/A-Draft] product_backlog_draft written — %d items. "
            "Awaiting Analyst review.", len(final_stories)
        )

        return ToolResult(
            observation=(
                f"product_backlog_draft written with {len(final_stories)} stories "
                f"ranked by WSJF descending.\n"
                f"The Analyst Agent will now review this draft and return per-PBI feedback."
            ),
            state_updates={"artifacts": artifacts},
            should_return=True,
        )

    # =========================================================================
    # Pipeline A-Refine — tools
    # =========================================================================

    def _tool_apply_analyst_feedback(
        self,
        revisions: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 1 (Pipeline A-Refine): Apply analyst feedback revisions to backlog_draft.

        Seeds backlog_draft from product_backlog_draft if working list is empty.
        Supports: title/description rewrite, acceptance_criteria addition,
        story_points adjustment, and splitting into sub-stories.
        """
        revisions = revisions or []

        # Seed backlog_draft from product_backlog_draft if first refine call
        draft: List[Dict] = list(state.get("backlog_draft") or [])
        if not draft:
            artifacts  = state.get("artifacts") or {}
            pb_draft   = artifacts.get("product_backlog_draft") or {}
            draft      = [dict(item) for item in (pb_draft.get("items") or [])]

        if not draft:
            return ToolResult(
                observation=(
                    "No backlog_draft found and product_backlog_draft artifact is empty. "
                    "Cannot apply analyst feedback."
                ),
            )

        draft_by_id     = {s.get("id", ""): s for s in draft}
        updated_ids:    List[str] = []
        split_children: List[Dict] = []
        split_parents:  set       = set()

        for rev in revisions:
            pid    = rev.get("pbi_id", "")
            thought = rev.get("thought", "").strip()
            addressed = rev.get("analyst_recommendation_addressed", "")

            if pid not in draft_by_id:
                logger.warning("[SprintAgent/A-Refine] revision PBI '%s' not found — skipped.", pid)
                continue

            story = draft_by_id[pid]
            hist_entry_base = {
                "action":     "analyst_revised",
                "step":       "apply_analyst_feedback",
                "addressed":  addressed,
                "reason":     thought,
            }

            # Title rewrite
            if rev.get("title"):
                story.setdefault("history", []).append({
                    **hist_entry_base, "field": "title",
                    "old_value": story.get("title"),
                })
                story["title"] = rev["title"]

            # Description rewrite
            if rev.get("description"):
                story.setdefault("history", []).append({
                    **hist_entry_base, "field": "description",
                    "old_value": story.get("description"),
                })
                story["description"] = rev["description"]

            # Story point adjustment
            if rev.get("story_points") is not None:
                pts = int(rev["story_points"])
                if pts not in _FIBONACCI:
                    pts = min(_FIBONACCI, key=lambda f: abs(f - pts))
                story.setdefault("history", []).append({
                    **hist_entry_base, "field": "story_points",
                    "old_value": story.get("story_points"),
                })
                story["story_points"] = pts

            # Acceptance criteria
            if rev.get("acceptance_criteria"):
                story["acceptance_criteria"] = list(rev["acceptance_criteria"])
                story.setdefault("history", []).append({
                    **hist_entry_base, "field": "acceptance_criteria",
                    "new_value": story["acceptance_criteria"],
                })

            # Story split
            if rev.get("split_into"):
                split_parents.add(pid)
                story.setdefault("history", []).append({
                    **hist_entry_base, "action": "analyst_split",
                    "sub_count": len(rev["split_into"]),
                })
                base_rank  = story.get("priority_rank") or 999
                base_wsjf  = story.get("wsjf_score")
                for sub_idx, sub in enumerate(rev["split_into"], start=1):
                    sub_id   = f"{pid}-S{sub_idx}"
                    sub_pts  = int(sub.get("story_points", 3))
                    if sub_pts not in _FIBONACCI:
                        sub_pts = min(_FIBONACCI, key=lambda f: abs(f - sub_pts))
                    sub_story = {
                        "id":                  sub_id,
                        "source_req_id":       story.get("source_req_id"),
                        "title":               sub.get("title", f"Sub-story {sub_idx} of {pid}"),
                        "description":         sub.get("description", ""),
                        "type":                story.get("type", "functional"),
                        "complexity":          sub.get("complexity", 2),
                        "effort":              sub.get("effort", 2),
                        "uncertainty":         sub.get("uncertainty", 1),
                        "story_points":        sub_pts,
                        "acceptance_criteria": sub.get("acceptance_criteria", []),
                        "invest":              None,   # analyst already reviewed parent
                        "status":              "estimated",
                        "wsjf_score":          base_wsjf,
                        "priority_rank":       base_rank + (sub_idx * 0.1),  # keep near parent
                        "business_value":      story.get("business_value"),
                        "time_criticality":    story.get("time_criticality"),
                        "risk_reduction":      story.get("risk_reduction"),
                        "depends_on":          [],
                        "enables":             [],
                        "dep_type":            "none",
                        "history": [{
                            "action":  "analyst_split_from",
                            "source":  pid,
                            "reason":  thought,
                            "step":    "apply_analyst_feedback",
                        }],
                    }
                    split_children.append(sub_story)

            updated_ids.append(pid)

        # Remove split parent stories; add sub-stories
        draft = [s for s in draft if s.get("id") not in split_parents]
        draft.extend(split_children)

        # Re-rank preserving WSJF order
        with_wsjf    = sorted(
            [s for s in draft if s.get("wsjf_score") is not None],
            key=lambda s: (s.get("priority_rank") or 999, -(s.get("wsjf_score") or 0)),
        )
        without_wsjf = [s for s in draft if s.get("wsjf_score") is None]
        for rank, story in enumerate(with_wsjf, start=1):
            story["priority_rank"] = rank
        draft = with_wsjf + without_wsjf

        logger.info(
            "[SprintAgent/A-Refine] apply_analyst_feedback: %d revised, "
            "%d split (→%d sub-stories). Draft now %d items.",
            len(updated_ids), len(split_parents), len(split_children), len(draft),
        )

        return ToolResult(
            observation=(
                f"Analyst feedback applied:\n"
                f"  {len(updated_ids)} PBIs revised\n"
                f"  {len(split_parents)} stories split into {len(split_children)} sub-stories\n"
                f"  Final backlog draft: {len(draft)} items\n\n"
                f"NEXT: Call 'write_product_backlog' with notes summarising the changes."
            ),
            state_updates={"backlog_draft": draft},
        )

    # ------------------------------------------------------------------

    def _tool_write_product_backlog(
        self,
        notes: str = "",
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 2 (Pipeline A-Refine): Persist the FINAL product_backlog artifact."""
        draft: List[Dict] = list(state.get("backlog_draft") or [])

        # Seed from draft artifact if working list not yet loaded
        if not draft:
            artifacts = state.get("artifacts") or {}
            pb_draft  = artifacts.get("product_backlog_draft") or {}
            draft     = [dict(item) for item in (pb_draft.get("items") or [])]

        final_stories = sorted(
            draft,
            key=lambda s: s.get("priority_rank") or 999,
        )

        artifacts  = dict(state.get("artifacts") or {})
        session_id = state.get("session_id", str(uuid.uuid4()))

        # Compute INVEST pass rate from analyst-populated invest fields
        invest_passed = sum(
            1 for s in final_stories
            if isinstance(s.get("invest"), dict)
            and all(v.get("pass", True) for v in s["invest"].values())
        )
        invest_total  = sum(1 for s in final_stories if isinstance(s.get("invest"), dict))

        product_backlog = {
            "session_id":      session_id,
            "source_artifact": "product_backlog_draft",
            "analyst_reviewed": True,
            "status":          "approved",
            "total_items":     len(final_stories),
            "invest_summary":  {
                "evaluated": invest_total,
                "passed":    invest_passed,
                "pass_rate": round(invest_passed / invest_total, 2) if invest_total else None,
            },
            "items":           final_stories,
            "methodology": {
                "estimation":     "Fibonacci (Complexity + Effort + Uncertainty)",
                "quality_gate":   "INVEST (by AnalystAgent)",
                "prioritization": "WSJF = (BV + TC + RR) / StoryPoints",
            },
            "notes":      notes,
            "created_at": datetime.now().isoformat(),
        }
        artifacts["product_backlog"] = product_backlog

        logger.info(
            "[SprintAgent/A-Refine] product_backlog (final) written — %d items, "
            "INVEST %d/%d passed.",
            len(final_stories), invest_passed, invest_total,
        )

        return ToolResult(
            observation=(
                f"Final product_backlog written: {len(final_stories)} stories.\n"
                f"INVEST coverage: {invest_passed}/{invest_total} items evaluated by Analyst.\n"
                f"The workflow will now advance to sprint planning."
            ),
            state_updates={"artifacts": artifacts},
            should_return=True,
        )

    # =========================================================================
    # Pipeline B — Sprint Backlog tools
    # =========================================================================

    def _tool_analyse_dependencies(
        self,
        dependencies: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 1 (Pipeline B): Map dependency links between PBIs."""
        dependencies = dependencies or []
        react_thought = (state.get("_last_react_thought") or "").strip()

        sprint_draft: List[Dict] = list(state.get("sprint_draft") or [])
        if not sprint_draft:
            artifacts = state.get("artifacts") or {}
            pb = artifacts.get("product_backlog") or {}
            sprint_draft = [dict(item) for item in (pb.get("items") or [])]

        if not sprint_draft:
            return ToolResult(
                observation=(
                    "No product_backlog items found. "
                    "Ensure product_backlog artifact exists before sprint planning."
                ),
            )

        draft_by_id = {s.get("id", ""): s for s in sprint_draft}
        updated_ids: List[str] = []
        warnings:    List[str] = []

        for dep in dependencies:
            sid    = dep.get("story_id", "")
            thought = dep.get("thought", "").strip() or react_thought

            if sid not in draft_by_id:
                warnings.append(f"{sid} not found — skipped.")
                continue

            story      = draft_by_id[sid]
            depends_on = dep.get("depends_on") or []
            enables    = dep.get("enables") or []
            dep_type   = dep.get("dep_type", "none")

            for ref in depends_on + enables:
                if ref not in draft_by_id:
                    warnings.append(f"{sid}: referenced '{ref}' not in backlog.")

            story["depends_on"] = depends_on
            story["enables"]    = enables
            story["dep_type"]   = dep_type
            story.setdefault("history", []).append({
                "action":     "dependency_analysed",
                "step":       "analyse_dependencies",
                "reason":     thought,
                "depends_on": depends_on,
                "enables":    enables,
                "dep_type":   dep_type,
            })
            updated_ids.append(sid)

        obs_parts = [
            f"Dependency analysis complete — {len(updated_ids)} PBIs updated.",
            "",
            "Dependency map:",
        ]
        for story in sprint_draft:
            sid     = story.get("id", "?")
            dep_on  = story.get("depends_on") or []
            enables = story.get("enables") or []
            dtype   = story.get("dep_type", "none")
            obs_parts.append(
                f"  [{sid}] ({dtype})  "
                f"depends_on={dep_on or '—'}  enables={enables or '—'}"
                f"  — {story.get('title','')[:55]}"
            )

        if warnings:
            obs_parts.append("\nWarnings:\n" + "\n".join(f"  {w}" for w in warnings))
        obs_parts.append(
            "\nNEXT: Call 'write_sprint_backlog' with sprint_number, "
            "capacity_points, completed_pbi_ids, and selections."
        )

        logger.info("[SprintAgent/B] analyse_dependencies: %d PBIs updated.", len(updated_ids))

        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={"sprint_draft": sprint_draft},
        )

    # ------------------------------------------------------------------

    def _tool_write_sprint_backlog(
        self,
        sprint_number: int = 1,
        sprint_goal: str = "",
        capacity_points: int = _DEFAULT_SPRINT_CAPACITY,
        completed_pbi_ids: List[str] = None,
        selections: List[Dict] = None,
        notes: str = "",
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 2 (Pipeline B): Enforce capacity + deps, persist sprint_backlog_<N>."""
        completed_pbi_ids = set(completed_pbi_ids or [])
        selections        = selections or []

        sprint_draft: List[Dict] = list(state.get("sprint_draft") or [])
        if not sprint_draft:
            artifacts = state.get("artifacts") or {}
            pb = artifacts.get("product_backlog") or {}
            sprint_draft = [dict(item) for item in (pb.get("items") or [])]

        draft_by_id      = {s.get("id", ""): s for s in sprint_draft}
        included_ids:    set = set()
        selection_reasons: Dict[str, str] = {}
        for sel in selections:
            sid = sel.get("story_id", "")
            selection_reasons[sid] = sel.get("reason", "")
            if sel.get("included", False):
                included_ids.add(sid)

        sorted_draft = sorted(
            sprint_draft,
            key=lambda s: s.get("priority_rank") or 999,
        )

        final_selected: List[Dict] = []
        total_points   = 0
        enforcement_log: List[str] = []
        satisfied_ids   = set(completed_pbi_ids)

        for story in sorted_draft:
            sid   = story.get("id", "")
            pts   = story.get("story_points") or 0
            rank  = story.get("priority_rank", 999)
            title = story.get("title", "")[:55]
            dep_on = story.get("depends_on") or []
            dtype  = story.get("dep_type", "none")

            if sid not in included_ids:
                enforcement_log.append(
                    f"  SKIP  #{rank} [{sid}] '{title}'"
                    f" — excluded: {selection_reasons.get(sid, 'no reason')}"
                )
                continue

            if dtype == "hard":
                unmet = [d for d in dep_on if d not in satisfied_ids]
                if unmet:
                    enforcement_log.append(
                        f"  BLOCK #{rank} [{sid}] '{title}'"
                        f" — hard dep unmet: {unmet}"
                    )
                    continue

            if total_points + pts > capacity_points:
                enforcement_log.append(
                    f"  OVER  #{rank} [{sid}] '{title}'"
                    f" — exceeds capacity ({total_points}+{pts}>{capacity_points})"
                )
                continue

            sprint_item = {
                **story,
                "sprint_number":    sprint_number,
                "sprint_status":    "planned",
                "inclusion_reason": selection_reasons.get(sid, "Selected by priority."),
            }
            sprint_item.setdefault("history", []).append({
                "action":        "sprint_planned",
                "step":          "write_sprint_backlog",
                "sprint_number": sprint_number,
                "reason":        selection_reasons.get(sid, ""),
            })

            final_selected.append(sprint_item)
            satisfied_ids.add(sid)
            total_points += pts
            enforcement_log.append(
                f"  ADD   #{rank} [{sid}] pts={pts} "
                f"(total={total_points}/{capacity_points}) '{title}'"
            )

        artifact_key = f"sprint_backlog_{sprint_number}"
        artifacts    = dict(state.get("artifacts") or {})
        session_id   = state.get("session_id", str(uuid.uuid4()))

        sprint_feedback = state.get("sprint_feedback") or {}
        plan_another    = bool(sprint_feedback.get("plan_another", False))

        sprint_backlog = {
            "session_id":       session_id,
            "source_artifact":  "product_backlog",
            "sprint_number":    sprint_number,
            "sprint_goal":      sprint_goal,
            "status":           "planned",
            "capacity_points":  capacity_points,
            "allocated_points": total_points,
            "remaining_points": capacity_points - total_points,
            "total_items":      len(final_selected),
            "completed_pbi_ids": list(completed_pbi_ids),
            "plan_another":     plan_another,
            "items":            final_selected,
            "methodology": {
                "selection":     "Priority rank (WSJF) + dependency analysis + capacity fit",
                "dependency":    "Hard deps block selection; soft deps inform order",
                "capacity_unit": "Story points (Fibonacci)",
            },
            "notes":      notes,
            "created_at": datetime.now().isoformat(),
        }

        artifacts[artifact_key] = sprint_backlog
        artifacts.pop("_sprint_feedback_ready", None)

        obs_parts = [
            f"━━━  Sprint Backlog {sprint_number} written  ━━━",
            f"  Artifact key   : {artifact_key}",
            f"  Sprint goal    : {sprint_goal or '(not set)'}",
            f"  Capacity       : {capacity_points} pts",
            f"  Allocated      : {total_points} pts",
            f"  Remaining      : {capacity_points - total_points} pts",
            f"  Items selected : {len(final_selected)}",
            f"  Plan another   : {plan_another}",
            "",
            "Selected items (by priority):",
        ]
        for item in final_selected:
            rank  = item.get("priority_rank", "?")
            sid   = item.get("id", "?")
            pts   = item.get("story_points", "?")
            wsjf  = item.get("wsjf_score")
            wsjf_str = f"WSJF={wsjf:.2f}" if wsjf else "WSJF=N/A"
            dep_on = item.get("depends_on") or []
            dep_str = f" deps={dep_on}" if dep_on else ""
            obs_parts.append(
                f"  #{rank} [{sid}] pts={pts} {wsjf_str}{dep_str}"
                f" — {item.get('title','')[:55]}"
            )

        obs_parts += ["", "Enforcement log:"] + enforcement_log

        if capacity_points - total_points > 0:
            obs_parts.append(
                f"\n  i  {capacity_points - total_points} pts unused."
            )

        logger.info(
            "[SprintAgent/B] sprint_backlog_%d written — %d items, %d/%d pts, plan_another=%s.",
            sprint_number, len(final_selected), total_points, capacity_points, plan_another,
        )

        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={
                "artifacts":    artifacts,
                "sprint_draft": sprint_draft,
            },
            should_return=True,
        )

    # =========================================================================
    # Unified process() — auto-detects pipeline
    # =========================================================================

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph node entry point — called by graph.py's sprint_agent_turn_fn.

        Detection logic
        ───────────────
        • product_backlog_draft NOT in artifacts            → Pipeline A-Draft
        • product_backlog_draft IN artifacts AND
          analyst_feedback      IN artifacts AND
          product_backlog       NOT in artifacts             → Pipeline A-Refine
        • product_backlog IN artifacts AND
          _sprint_feedback_ready IN artifacts               → Pipeline B
        • Otherwise: log warning, return empty.
        """
        artifacts = state.get("artifacts") or {}

        has_draft            = "product_backlog_draft" in artifacts
        has_analyst_feedback = "analyst_feedback" in artifacts
        has_backlog          = "product_backlog" in artifacts
        has_sprint_feedback  = "_sprint_feedback_ready" in artifacts

        if not has_draft:
            return self._run_pipeline_a_draft(state)

        if has_analyst_feedback and not has_backlog:
            return self._run_pipeline_a_refine(state)

        if has_sprint_feedback:
            return self._run_pipeline_b(state)

        logger.warning(
            "[SprintAgent] process() called but no pipeline applies: "
            "has_draft=%s, has_analyst_feedback=%s, has_backlog=%s, "
            "has_sprint_feedback=%s. Returning empty.",
            has_draft, has_analyst_feedback, has_backlog, has_sprint_feedback,
        )
        return {}

    # ── Pipeline A-Draft entry ─────────────────────────────────────────────────

    def _run_pipeline_a_draft(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Build the initial product_backlog_draft from reviewed_interview_record."""
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
                f"    rationale: {r.get('rationale','(none)')[:120]}"
            )
        req_summary = "\n".join(req_lines) or "  (no requirements found)"

        existing_draft = state.get("backlog_draft") or []
        draft_info = ""
        if existing_draft:
            draft_info = (
                f"\n{'━'*44}  EXISTING BACKLOG DRAFT  {'━'*16}\n"
                f"There are {len(existing_draft)} items already in the draft. "
                f"Continue from where you left off.\n"
            )

        task = (
            f"{self._PROFILE_A_DRAFT}\n\n"
            f"{'━'*16}  PROJECT  {'━'*16}\n"
            f"{project_desc}\n\n"
            f"{'━'*16}  REQUIREMENTS ({len(requirements)}) WITH RATIONALE  {'━'*16}\n"
            f"{req_summary}\n\n"
            + draft_info
            + f"{'━'*16}  YOUR PIPELINE  {'━'*16}\n"
            "Execute these steps IN ORDER:\n\n"
            "STEP 1 — Call 'triage_and_estimate':\n"
            "  • Create a user story for each requirement.\n"
            "  • Assess Complexity (1-5), Effort (1-5), Uncertainty (1-5).\n"
            "  • Map to nearest Fibonacci story points (1,2,3,5,8,13,21).\n"
            "  • You MAY use the requirement rationale above to gauge scope.\n"
            "  • Provide 'thought' explaining your scoring rationale.\n\n"
            "STEP 2 — Call 'prioritize_backlog':\n"
            "  • Score each story: business_value, time_criticality, "
            "risk_reduction (all 1-10).\n"
            "  • WSJF is computed automatically.\n"
            "  • Provide 'thought' for each score.\n\n"
            "STEP 3 — Call 'write_product_backlog_draft':\n"
            "  • Provide a brief summary in 'notes'.\n\n"
            "RULES:\n"
            "• ONE tool per ReAct step.\n"
            "• Always provide 'thought' explaining your reasoning.\n"
            "• Fibonacci values only: 1, 2, 3, 5, 8, 13, 21.\n"
            "• Do NOT evaluate INVEST — this is handled by the Analyst Agent next.\n"
        )

        logger.info("[SprintAgent] Running Pipeline A-Draft — build product_backlog_draft.")
        return self.react(state, task)

    # ── Pipeline A-Refine entry ────────────────────────────────────────────────

    def _run_pipeline_a_refine(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Apply AnalystAgent feedback and write the final product_backlog."""
        artifacts       = state.get("artifacts") or {}
        analyst_feedback = artifacts.get("analyst_feedback") or {}
        pb_draft         = artifacts.get("product_backlog_draft") or {}
        record = (
            artifacts.get("reviewed_interview_record")
            or artifacts.get("interview_record")
            or {}
        )

        # Build per-PBI analyst feedback summary
        pbi_reviews = analyst_feedback.get("pbi_reviews") or []
        feedback_lines = []
        for review in pbi_reviews:
            if review.get("severity", "pass") == "pass":
                continue
            invest_issues = []
            for crit, result in (review.get("invest_check") or {}).items():
                if not result.get("pass", True):
                    invest_issues.append(f"{crit}: {result.get('note', '')}")
            line = (
                f"  [{review['pbi_id']}] severity={review['severity']}\n"
                f"    vague_terms: {review.get('vague_terms', [])}\n"
                f"    INVEST issues: {invest_issues or '(none)'}\n"
                f"    duplicate_risk: {review.get('duplicate_risk', 'low')}\n"
                f"    recommendations: {review.get('recommendations', [])}"
            )
            feedback_lines.append(line)

        feedback_block = "\n".join(feedback_lines) or "  (no critical issues — minor fixes only)"

        # Build requirement rationale table for context
        requirements = record.get("requirements_identified") or []
        rationale_lines = []
        for r in requirements:
            rationale_lines.append(
                f"  [{r.get('id','?')}] → {r.get('rationale','(none)')[:200]}"
            )
        rationale_table = "\n".join(rationale_lines) or "  (no rationale available)"

        # Draft summary
        draft_items = pb_draft.get("items") or []
        draft_lines = []
        for item in draft_items:
            draft_lines.append(
                f"  #{item.get('priority_rank','?')} [{item['id']}] "
                f"pts={item.get('story_points','?')} WSJF={item.get('wsjf_score','?')}"
                f" — {item.get('title','')[:60]}"
            )
        draft_summary = "\n".join(draft_lines) or "  (empty draft)"

        task = (
            f"{self._PROFILE_A_REFINE}\n\n"
            f"{'━'*16}  ANALYST FEEDBACK SUMMARY  {'━'*16}\n"
            f"Overall quality score : {analyst_feedback.get('overall_quality_score', 'N/A')}\n"
            f"Critical issues       : {analyst_feedback.get('critical_issues', 0)}\n"
            f"Analyst conclusion    : {analyst_feedback.get('notes', '(none)')}\n\n"
            f"Per-PBI issues (only items with severity != pass shown):\n"
            f"{feedback_block}\n\n"
            f"{'━'*16}  CURRENT BACKLOG DRAFT ({len(draft_items)} items)  {'━'*16}\n"
            f"{draft_summary}\n\n"
            f"{'━'*16}  REQUIREMENT RATIONALE TABLE  {'━'*16}\n"
            f"(Use these to validate or override analyst suggestions)\n"
            f"{rationale_table}\n\n"
            f"{'━'*16}  YOUR PIPELINE  {'━'*16}\n"
            "Execute these steps IN ORDER:\n\n"
            "STEP 1 — Call 'apply_analyst_feedback':\n"
            "  • Provide a 'revisions' list for EVERY PBI that has analyst issues.\n"
            "  • For each revision: address the specific recommendation.\n"
            "  • You MAY override analyst suggestions — cite the requirement rationale.\n"
            "  • Use split_into for stories flagged as too large (INVEST 'small' fail).\n"
            "  • Add acceptance_criteria for stories flagged as not testable.\n\n"
            "STEP 2 — Call 'write_product_backlog':\n"
            "  • Summarise what changed from draft to final in 'notes'.\n\n"
            "RULES:\n"
            "• ONE tool per ReAct step.\n"
            "• Address EVERY high-severity analyst finding.\n"
            "• Fibonacci values only: 1, 2, 3, 5, 8, 13, 21.\n"
        )

        logger.info("[SprintAgent] Running Pipeline A-Refine — apply analyst feedback.")
        return self.react(state, task)

    # ── Pipeline B entry ──────────────────────────────────────────────────────

    def _run_pipeline_b(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Plan a sprint backlog from the product_backlog and sprint_feedback."""
        artifacts       = state.get("artifacts") or {}
        pb              = artifacts.get("product_backlog") or {}
        items           = pb.get("items") or []
        sprint_feedback = state.get("sprint_feedback") or {}

        sprint_number     = state.get("current_sprint_number", 1)
        capacity_points   = sprint_feedback.get("capacity_points", _DEFAULT_SPRINT_CAPACITY)
        sprint_goal       = sprint_feedback.get("sprint_goal", "")
        completed_pbi_ids = sprint_feedback.get("completed_pbi_ids") or []
        plan_another      = sprint_feedback.get("plan_another", False)
        planner_notes     = sprint_feedback.get("notes", "")
        done_str = ", ".join(completed_pbi_ids) if completed_pbi_ids else "(none)"

        backlog_lines = []
        for item in items:
            rank  = item.get("priority_rank", "?")
            sid   = item.get("id", "?")
            pts   = item.get("story_points", "?")
            wsjf  = item.get("wsjf_score")
            wsjf_str = f"WSJF={wsjf:.2f}" if wsjf else "WSJF=N/A"
            backlog_lines.append(
                f"  #{rank} [{sid}] pts={pts} {wsjf_str} "
                f"({item.get('type','?')}) — {item.get('title','')[:65]}"
            )
        backlog_summary = "\n".join(backlog_lines) or "  (empty backlog)"

        sprint_backlog_feedback = (state.get("sprint_backlog_feedback") or "").strip()
        sprint_feedback_block = ""
        if sprint_backlog_feedback:
            sprint_feedback_block = (
                f"{'━'*16}  REVIEWER FEEDBACK (previous sprint backlog REJECTED)  {'━'*16}\n"
                f"{sprint_backlog_feedback}\n\n"
                "You MUST address ALL points above in this replan.\n\n"
            )

        task = (
            f"{self._PROFILE_B}\n\n"
            + sprint_feedback_block
            + f"{'━'*16}  SPRINT PLANNING REQUEST  {'━'*16}\n"
            f"Sprint number       : {sprint_number}\n"
            f"Sprint goal         : {sprint_goal or '(not yet defined — you must propose one)'}\n"
            f"Capacity (pts)      : {capacity_points}\n"
            f"Completed PBIs      : {done_str}\n"
            f"Plan another sprint : {plan_another}\n"
            + (f"Planner notes       : {planner_notes}\n" if planner_notes else "")
            + f"\n{'━'*16}  PRODUCT BACKLOG ({len(items)} items)  {'━'*16}\n"
            f"{backlog_summary}\n\n"
            f"{'━'*16}  YOUR PIPELINE  {'━'*16}\n"
            "STEP 1 — Call 'analyse_dependencies':\n"
            "  • For EVERY PBI, declare depends_on, enables, and dep_type.\n"
            "  • Hard dependency = cannot start without the prerequisite.\n"
            "  • Provide 'thought' explaining each dependency relationship.\n\n"
            "STEP 2 — Call 'write_sprint_backlog':\n"
            f"  • sprint_number      = {sprint_number}\n"
            f"  • capacity_points    = {capacity_points}\n"
            f"  • completed_pbi_ids  = {completed_pbi_ids!r}\n"
            "  • For EACH PBI: story_id, included (true/false), reason.\n"
            f"  • sprint_goal: \"{sprint_goal or 'propose a concise sprint goal'}\"\n\n"
            "RULES:\n"
            "• ONE tool per ReAct step.\n"
            "• Always provide 'thought' and 'reason' for every decision.\n"
            "• Do NOT exceed the capacity.\n"
            f"• The 'plan_another' field must reflect: {plan_another}.\n"
        )

        logger.info(
            "[SprintAgent] Running Pipeline B — plan sprint %d "
            "(capacity=%d, plan_another=%s).",
            sprint_number, capacity_points, plan_another,
        )
        return self.react(state, task)