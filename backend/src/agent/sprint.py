"""
sprint.py – SprintAgent  (Sprint Zero step 3 + Sprint Execution step B)

Role
────
The SprintAgent has ONE entry point — process() — which detects its current
task from state and runs the appropriate ReAct pipeline:

  Pipeline A — Build Product Backlog
  ────────────────────────────────────
  Triggered when: product_backlog is NOT yet in artifacts.
  Input : reviewed_interview_record
  Output: product_backlog

  Steps (prompt-driven, one ReAct tool per step):
    1. triage_and_estimate   — Fibonacci scoring + INVEST validation
    2. prioritize_backlog    — WSJF scoring + rank
    3. write_product_backlog — persist artifact

  Pipeline B — Plan Sprint Backlog
  ──────────────────────────────────
  Triggered when: product_backlog IS in artifacts AND
                  _sprint_feedback_ready sentinel IS in artifacts.
  Input : product_backlog + sprint_feedback (from state)
  Output: sprint_backlog_<N>  (e.g. sprint_backlog_1, sprint_backlog_2)

  Steps (prompt-driven, one ReAct tool per step):
    1. analyse_dependencies  — map hard/soft dependency links between PBIs
    2. write_sprint_backlog  — capacity-aware, dependency-respecting selection;
                               persists artifact and removes _sprint_feedback_ready

Both pipelines share the same ReAct loop infrastructure from BaseAgent.

Artifact naming
───────────────
Sprint backlogs are named sprint_backlog_<sprint_number> so multiple sprints
coexist in the artifact store without collision:
  sprint_backlog_1, sprint_backlog_2, sprint_backlog_3, ...

The current sprint number is read from state["current_sprint_number"]
(default 1 if absent).

State fields used
─────────────────
  backlog_draft         — Pipeline A working list (PBI items being triaged)
  sprint_draft          — Pipeline B working list (PBIs + dependency info)
  sprint_feedback       — dict supplied by sprint_feedback_turn interrupt:
                          { sprint_goal, capacity_points, completed_pbi_ids,
                            plan_another }
  current_sprint_number — which sprint is being planned (int, default 1)
  artifacts             — shared artifact store (read + write)
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

# ── Default sprint capacity if caller does not specify ────────────────────────
_DEFAULT_SPRINT_CAPACITY = 20


class SprintAgent(BaseAgent):
    """
    Unified agent for product backlog creation (Pipeline A) and sprint
    backlog planning (Pipeline B).

    process() auto-detects which pipeline to run based on artifacts in state.
    """

    # ── Profiles ──────────────────────────────────────────────────────────────

    _PROFILE_A = """You are an expert Agile Product Backlog Manager.

Mission:
Transform validated requirements into a well-structured, prioritised Product
Backlog using industry-standard estimation, quality-gating, and ranking
techniques.

You MUST follow this pipeline IN ORDER:
1. TRIAGE     — Call 'triage_and_estimate' with ALL requirements scored.
2. PRIORITIZE — Call 'prioritize_backlog' to compute WSJF and rank.
3. FINALIZE   — Call 'write_product_backlog' with summary notes.

Key principles:
• Fibonacci estimation: 1, 2, 3, 5, 8, 13, 21 only.
• Three scoring dimensions: Complexity (1-5), Effort (1-5), Uncertainty (1-5).
• INVEST: Independent, Negotiable, Valuable, Estimable, Small, Testable.
• WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints."""

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
  its dependencies are also selected in the same sprint or already completed.
• Do not exceed the sprint capacity (story points).
• Record your reasoning for every include / exclude decision."""

    # ── Init ──────────────────────────────────────────────────────────────────

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="sprint_agent")

    # ── Tool registration ─────────────────────────────────────────────────────

    def _register_tools(self) -> None:

        # ── Pipeline A ────────────────────────────────────────────────────
        self.register_tool(Tool(
            name="triage_and_estimate",
            description=(
                "Pipeline A — Step 1: Score each requirement using Fibonacci "
                "story points and validate INVEST quality criteria.\n"
                "Assess Complexity (1-5), Effort (1-5), Uncertainty (1-5) for "
                "each requirement; map the sum to the nearest Fibonacci number.\n"
                "Evaluate all 6 INVEST criteria (true/false) for each story.\n\n"
                "Input: {\n"
                "  \"stories\": [\n"
                "    {\n"
                "      \"source_req_id\": \"FR-001\",\n"
                "      \"title\":         \"<story title>\",\n"
                "      \"description\":   \"<story description>\",\n"
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
                "      \"thought\":       \"<reasoning>\"\n"
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
                "Pipeline A — Step 2: Calculate WSJF scores and rank all stories.\n"
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
                "Does NOT end the turn."
            ),
            func=self._tool_prioritize_backlog,
        ))

        self.register_tool(Tool(
            name="write_product_backlog",
            description=(
                "Pipeline A — Step 3: Finalize and persist the product_backlog artifact.\n"
                "Reads backlog_draft from state automatically. Only provide notes.\n\n"
                "Input: {\"notes\": \"<2-3 sentence summary>\"}\n"
                "This tool ENDS the turn."
            ),
            func=self._tool_write_product_backlog,
        ))

        # ── Pipeline B ────────────────────────────────────────────────────
        # self.register_tool(Tool(
        #     name="analyse_dependencies",
        #     description=(
        #         "Pipeline B — Step 1: Identify dependency links between PBIs.\n\n"
        #         "For each PBI declare:\n"
        #         "  depends_on — list of PBI IDs that MUST finish before this one\n"
        #         "               (hard dep: blocks selection if unmet)\n"
        #         "  enables    — list of PBI IDs this item unlocks (informational)\n"
        #         "  dep_type   — 'hard' | 'soft' | 'none'\n"
        #         "  thought    — your reasoning\n\n"
        #         "Input: {\n"
        #         "  \"dependencies\": [\n"
        #         "    {\n"
        #         "      \"story_id\":   \"PBI-001\",\n"
        #         "      \"depends_on\": [\"PBI-005\"],\n"
        #         "      \"enables\":    [\"PBI-002\"],\n"
        #         "      \"dep_type\":   \"hard\",\n"
        #         "      \"thought\":    \"<why>\"\n"
        #         "    }, ...\n"
        #         "  ]\n"
        #         "}\n"
        #         "Does NOT end the turn.\n"
        #         "NEXT: Call 'write_sprint_backlog'."
        #     ),
        #     func=self._tool_analyse_dependencies,
        # ))

        # self.register_tool(Tool(
        #     name="write_sprint_backlog",
        #     description=(
        #         "Pipeline B — Step 2: Select PBIs for a sprint and persist the artifact.\n\n"
        #         "Selection rules (enforced by the tool):\n"
        #         "  1. Work through PBIs by priority_rank ascending (1 = highest priority).\n"
        #         "  2. Skip any PBI whose hard dependencies are not completed or selected.\n"
        #         "  3. Stop when adding the next item would exceed capacity_points.\n\n"
        #         "Input: {\n"
        #         "  \"sprint_number\":      <int>,\n"
        #         "  \"sprint_goal\":        \"<one-sentence goal>\",\n"
        #         "  \"capacity_points\":    <int>,\n"
        #         "  \"completed_pbi_ids\": [\"PBI-xxx\", ...],\n"
        #         "  \"selections\": [\n"
        #         "    {\n"
        #         "      \"story_id\": \"PBI-001\",\n"
        #         "      \"included\": true|false,\n"
        #         "      \"reason\":   \"<why included or excluded>\"\n"
        #         "    }, ...\n"
        #         "  ],\n"
        #         "  \"notes\": \"<brief sprint summary>\"\n"
        #         "}\n"
        #         "This tool ENDS the turn."
        #     ),
        #     func=self._tool_write_sprint_backlog,
        # ))

    # =========================================================================
    # Pipeline A — Product Backlog tools
    # =========================================================================

    def _tool_triage_and_estimate(
        self,
        stories: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Step 1 (Pipeline A): Score requirements, validate INVEST, populate backlog_draft."""
        stories = stories or []
        if not stories:
            return ToolResult(
                observation=(
                    "No stories provided. You must provide a 'stories' list "
                    "with all requirements scored."
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

            # Snap to nearest Fibonacci if not valid
            if points not in _FIBONACCI:
                nearest = min(_FIBONACCI, key=lambda f: abs(f - points))
                thought += f" (snapped {points} -> {nearest})"
                points = nearest

            invest_results = {c: story.get(c, True) for c in _INVEST_CRITERIA}
            failed_criteria = [c for c, v in invest_results.items() if not v]
            if failed_criteria:
                invest_warnings.append(
                    f"{story_id} failed INVEST: {failed_criteria}."
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
                "priority":       None,
                "wsjf_score":     None,
                "priority_rank":  None,
                "acceptance_criteria": [],
                # dependency fields — populated by Pipeline B
                "depends_on": [],
                "enables":    [],
                "dep_type":   "none",
                "history": [{
                    "action": "created",
                    "step":   "triage",
                    "reason": thought or f"Estimated from {story.get('source_req_id', '?')}.",
                    "invest_results": invest_results,
                }],
            }

            draft.append(item)
            created_ids.append(story_id)

        obs_parts = [f"Backlog draft: {len(draft)} stories created."]
        if invest_warnings:
            obs_parts.append("INVEST warnings:\n" + "\n".join(f"  {w}" for w in invest_warnings))
        obs_parts.append("\nNEXT: Call 'prioritize_backlog' to compute WSJF scores.")

        logger.info("[SprintAgent/A] triage: %d stories, %d INVEST warnings.",
                    len(created_ids), len(invest_warnings))

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
        """Step 2 (Pipeline A): WSJF scoring and ranking."""
        scores = scores or []
        react_thought = (state.get("_last_react_thought") or "").strip()

        if not scores:
            return ToolResult(
                observation="No WSJF scores provided. Supply scores for all stories."
            )

        draft: List[Dict] = list(state.get("backlog_draft") or [])
        draft_by_id = {s.get("id", ""): s for s in draft}
        scored_ids: List[str] = []
        warnings: List[str] = []

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
        obs_parts.append("\nNEXT: Call 'write_product_backlog' with summary notes.")

        logger.info("[SprintAgent/A] prioritize: %d stories ranked.", len(scored_ids))

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
        """Step 3 (Pipeline A): Finalize the product_backlog artifact."""
        draft: List[Dict] = list(state.get("backlog_draft") or [])
        final_stories = sorted(
            [s for s in draft if s.get("status") != "invest_failed"],
            key=lambda s: s.get("priority_rank") or 999,
        )

        artifacts  = dict(state.get("artifacts") or {})
        session_id = state.get("session_id", str(uuid.uuid4()))

        product_backlog = {
            "id":               str(uuid.uuid4()),
            "session_id":      session_id,
            "source_artifact": "reviewed_interview_record",
            "status":          "draft",
            "total_items":     len(final_stories),
            "items":           final_stories,
            "methodology": {
                "estimation":    "Fibonacci (Complexity + Effort + Uncertainty)",
                "quality_gate":  "INVEST",
                "prioritization": "WSJF = (BV + TC + RR) / StoryPoints",
            },
            "notes":      notes,
            "created_at": datetime.now().isoformat(),
        }
        artifacts["product_backlog"] = product_backlog

        logger.info("[SprintAgent/A] product_backlog written — %d items.", len(final_stories))

        return ToolResult(
            observation=(
                f"Product backlog written. "
                f"{len(final_stories)} stories ranked by WSJF descending.\n"
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
        """Step 1 (Pipeline B): Map dependency links between PBIs into sprint_draft."""
        dependencies = dependencies or []
        react_thought = (state.get("_last_react_thought") or "").strip()

        # Load sprint_draft, seeding from product_backlog if first time
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
        warnings: List[str] = []

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
                f"depends_on={dep_on or '—'}  "
                f"enables={enables or '—'}"
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

        # Load sprint_draft
        sprint_draft: List[Dict] = list(state.get("sprint_draft") or [])
        if not sprint_draft:
            artifacts = state.get("artifacts") or {}
            pb = artifacts.get("product_backlog") or {}
            sprint_draft = [dict(item) for item in (pb.get("items") or [])]

        draft_by_id = {s.get("id", ""): s for s in sprint_draft}

        # Build include/exclude sets from LLM selections
        included_ids: set = set()
        selection_reasons: Dict[str, str] = {}
        for sel in selections:
            sid = sel.get("story_id", "")
            selection_reasons[sid] = sel.get("reason", "")
            if sel.get("included", False):
                included_ids.add(sid)

        # Process PBIs in priority order
        sorted_draft = sorted(
            sprint_draft,
            key=lambda s: s.get("priority_rank") or 999,
        )

        final_selected: List[Dict] = []
        total_points   = 0
        enforcement_log: List[str] = []
        satisfied_ids   = set(completed_pbi_ids)  # grows as items are selected

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

            # Hard dependency check
            if dtype == "hard":
                unmet = [d for d in dep_on if d not in satisfied_ids]
                if unmet:
                    enforcement_log.append(
                        f"  BLOCK #{rank} [{sid}] '{title}'"
                        f" — hard dep unmet: {unmet}"
                    )
                    continue

            # Capacity check
            if total_points + pts > capacity_points:
                enforcement_log.append(
                    f"  OVER  #{rank} [{sid}] '{title}'"
                    f" — exceeds capacity ({total_points}+{pts}>{capacity_points})"
                )
                continue

            sprint_item = {
                **story,
                "sprint_number":     sprint_number,
                "sprint_status":     "planned",
                "inclusion_reason":  selection_reasons.get(sid, "Selected by priority."),
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

        # Persist artifact
        artifact_key = f"sprint_backlog_{sprint_number}"
        artifacts    = dict(state.get("artifacts") or {})
        session_id   = state.get("session_id", str(uuid.uuid4()))

        # Read plan_another from sprint_feedback
        sprint_feedback = state.get("sprint_feedback") or {}
        plan_another    = bool(sprint_feedback.get("plan_another", False))

        sprint_backlog = {
            "session_id":         session_id,
            "source_artifact":    "product_backlog",
            "sprint_number":      sprint_number,
            "sprint_goal":        sprint_goal,
            "status":             "planned",
            "capacity_points":    capacity_points,
            "allocated_points":   total_points,
            "remaining_points":   capacity_points - total_points,
            "total_items":        len(final_selected),
            "completed_pbi_ids":  list(completed_pbi_ids),
            "plan_another":       plan_another,
            "items":              final_selected,
            "methodology": {
                "selection":     "Priority rank (WSJF) + dependency analysis + capacity fit",
                "dependency":    "Hard deps block selection; soft deps inform order",
                "capacity_unit": "Story points (Fibonacci)",
            },
            "notes":      notes,
            "created_at": datetime.now().isoformat(),
        }

        artifacts[artifact_key] = sprint_backlog

        # Remove the _sprint_feedback_ready sentinel so the supervisor
        # knows this sprint has been consumed and re-evaluates the loop.
        artifacts.pop("_sprint_feedback_ready", None)

        # Build observation summary
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
    # Unified process() — auto-detects Pipeline A vs Pipeline B
    # =========================================================================

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        LangGraph node entry point — called by graph.py's sprint_agent_turn_fn.

        Detection logic
        ───────────────
        • product_backlog NOT in artifacts  → run Pipeline A (build backlog)
        • product_backlog IN artifacts AND
          _sprint_feedback_ready IN artifacts → run Pipeline B (plan sprint)
        • Otherwise: log a warning and return empty (supervisor will re-route).
        """
        artifacts = state.get("artifacts") or {}

        has_backlog          = "product_backlog" in artifacts
        has_sprint_feedback  = "_sprint_feedback_ready" in artifacts

        if not has_backlog:
            return self._run_pipeline_a(state)

        if has_sprint_feedback:
            return self._run_pipeline_b(state)

        logger.warning(
            "[SprintAgent] process() called but no pipeline applies: "
            "has_backlog=%s, has_sprint_feedback=%s. Returning empty.",
            has_backlog, has_sprint_feedback,
        )
        return {}

    # ── Pipeline A entry ──────────────────────────────────────────────────────

    def _run_pipeline_a(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Build the product backlog from reviewed_interview_record."""
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
                f"\n{'━'*44}  EXISTING BACKLOG DRAFT  {'━'*16}\n"
                f"There are {len(existing_draft)} items already in the draft. "
                f"Continue from where you left off.\n"
            )

        # Inject reviewer feedback if this is a rebuild after rejection
        product_backlog_feedback = (state.get("product_backlog_feedback") or "").strip()
        feedback_block = ""
        if product_backlog_feedback:
            feedback_block = (
                f"{'━'*16}  REVIEWER FEEDBACK (previous backlog was REJECTED)  {'━'*16}\n"
                f"{product_backlog_feedback}\n\n"
                "You MUST address ALL points above when re-building the backlog.\n"
                "Pay special attention to story points, WSJF scores, INVEST "
                "criteria, and priority rankings.\n\n"
            )

        task = (
            # f"{self._PROFILE_A}\n\n"
            f"{'━'*16}  PROJECT  {'━'*16}\n"
            f"{project_desc}\n\n"
            + feedback_block
            + f"{'━'*16}  REQUIREMENTS ({len(requirements)})  {'━'*16}\n"
            f"{req_summary}\n\n"
            + draft_info
            + f"{'━'*16}  YOUR PIPELINE  {'━'*16}\n"
            "Execute these steps IN ORDER:\n\n"
            "STEP 1 — Call 'triage_and_estimate':\n"
            "  • Create a user story for each requirement.\n"
            "  • Assess Complexity (1-5), Effort (1-5), Uncertainty (1-5).\n"
            "  • Map to nearest Fibonacci story points (1,2,3,5,8,13,21).\n"
            "  • Evaluate INVEST criteria (true/false) for each story.\n"
            "  • Provide 'thought' explaining your scoring rationale.\n\n"
            "STEP 2 — Call 'prioritize_backlog':\n"
            "  • Score each story: business_value, time_criticality, "
            "risk_reduction (all 1-10).\n"
            "  • WSJF is computed automatically.\n"
            "  • Provide 'thought' for each score.\n\n"
            "STEP 3 — Call 'write_product_backlog':\n"
            "  • Provide a brief summary in 'notes'.\n\n"
            "RULES:\n"
            "• ONE tool per ReAct step.\n"
            "• Always provide 'thought' explaining your reasoning.\n"
            "• Fibonacci values only: 1, 2, 3, 5, 8, 13, 21.\n"
        )

        logger.info("[SprintAgent] Running Pipeline A — build product backlog.")
        return self.react(state, task, tool_choice="required")

    # ── Pipeline B entry ──────────────────────────────────────────────────────

    def _run_pipeline_b(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Plan a sprint backlog from the product_backlog and sprint_feedback."""
        artifacts       = state.get("artifacts") or {}
        pb              = artifacts.get("product_backlog") or {}
        items           = pb.get("items") or []
        sprint_feedback = state.get("sprint_feedback") or {}

        sprint_number      = state.get("current_sprint_number", 1)
        capacity_points    = sprint_feedback.get("capacity_points", _DEFAULT_SPRINT_CAPACITY)
        sprint_goal        = sprint_feedback.get("sprint_goal", "")
        completed_pbi_ids  = sprint_feedback.get("completed_pbi_ids") or []
        plan_another       = sprint_feedback.get("plan_another", False)
        planner_notes      = sprint_feedback.get("notes", "")
        done_str = ", ".join(completed_pbi_ids) if completed_pbi_ids else "(none)"

        # Build a readable backlog summary
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

        # Inject sprint backlog feedback if this is a replan after rejection
        sprint_backlog_feedback = (state.get("sprint_backlog_feedback") or "").strip()
        sprint_feedback_block = ""
        if sprint_backlog_feedback:
            sprint_feedback_block = (
                f"{'━'*16}  REVIEWER FEEDBACK (previous sprint backlog was REJECTED)  {'━'*16}\n"
                f"{sprint_backlog_feedback}\n\n"
                "You MUST address ALL points above in this replan.\n"
                "Adjust item selection, capacity allocation, or dependency "
                "handling as required by the feedback.\n\n"
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
            "Execute these steps IN ORDER:\n\n"
            "STEP 1 — Call 'analyse_dependencies':\n"
            "  • For EVERY PBI, declare depends_on, enables, and dep_type.\n"
            "  • Hard dependency = cannot start without the prerequisite.\n"
            "  • Soft dependency = preferred order, not a blocker.\n"
            "  • Provide 'thought' explaining each dependency relationship.\n\n"
            "STEP 2 — Call 'write_sprint_backlog':\n"
            f"  • sprint_number      = {sprint_number}\n"
            f"  • capacity_points    = {capacity_points}\n"
            f"  • completed_pbi_ids  = {completed_pbi_ids!r}\n"
            "  • For EACH PBI: story_id, included (true/false), reason.\n"
            "  • Select highest-priority items fitting within capacity.\n"
            "  • Exclude items with unmet hard dependencies.\n"
            f"  • sprint_goal: \"{sprint_goal or 'propose a concise sprint goal'}\"\n"
            "  • Provide a 'notes' summary of the sprint backlog.\n\n"
            "RULES:\n"
            "• ONE tool per ReAct step.\n"
            "• Always provide 'thought' and 'reason' for every decision.\n"
            "• Do NOT exceed the capacity.\n"
            "• The 'plan_another' field in write_sprint_backlog must reflect "
            f"the planner's intent: {plan_another}.\n"
        )

        logger.info(
            "[SprintAgent] Running Pipeline B — plan sprint %d "
            "(capacity=%d, plan_another=%s).",
            sprint_number, capacity_points, plan_another,
        )
        return self.react(state, task)