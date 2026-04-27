"""
sprint.py – SprintAgent  (Product Owner)

Role
────
SprintAgent runs in two distinct steps within Phase 1:

Step 9a — create_user_stories (sprint_agent_turn):
  Reads requirement_list_approved and converts each confirmed requirement
  into a user story. No estimation occurs here — story points are assigned
  exclusively by AnalystAgent in Step 9c.
  Output: user_story_draft artifact.

Step 9b — build_product_backlog (sprint_agent_turn):
  Reads both user_story_draft and analyst_estimation (from Step 9c), runs
  dependency-aware WSJF prioritization, and assembles the final product_backlog
  using the consolidated PBI schema.
  Output: product_backlog artifact.

Split loop handling (between Steps 9a and 9b)
─────────────────────────────────────────────
When AnalystAgent returns analyst_estimation with has_pending_splits=True:
  1. SprintAgent reads split_proposals from each flagged story.
  2. Creates sub-stories (inheriting domain, type, source_req_id + suffix).
  3. Replaces user_story_draft with sub-stories only (not already-valid stories).
  4. Increments state["split_round"].
  5. Supervisor routes back to analyst_estimation_turn for re-estimation.
  Hard limit: split_round ≤ 2. After 2 rounds, oversized stories are flagged
  in quality_warnings and included as-is.

Source artifacts
────────────────
Step 9a reads: artifacts["requirement_list_approved"]
               artifacts["requirement_list"] (fallback on PO rejection rebuild)
Step 9b reads: artifacts["user_story_draft"]
               artifacts["analyst_estimation"]

Fallback on PO rejection
────────────────────────
When product_backlog_feedback is set (PO rejected the backlog):
  • product_backlog, user_story_draft, and analyst_estimation are removed
    by review_product_backlog_turn_fn in graph.py.
  • SprintAgent re-runs Step 9a (create_user_stories) from scratch with
    the feedback injected into the story generation prompt.
  • AnalystAgent re-runs Step 9c (estimate_and_validate_stories).
  • split_round is reset to 0.

Profile + Addendum pattern
──────────────────────────
  self.profile.prompt         → who the agent is (sprint_agent_react.txt)
  _PASS1_ADDENDUM             → story creation rules
  _PASS2_ADDENDUM             → WSJF prioritization rules

PBI schema (consolidated)
──────────────────────────
The product_backlog uses a consolidated schema. enrichment block and top-level
INVEST booleans are NOT included in the output — they live in analyst_estimation
and are referenced via source_req_id when needed.

  {
    "id":             "PBI-001",
    "source_req_id":  "FR-012",
    "type":           "functional" | "non_functional" | "constraint",
    "domain":         "<Epic label>",
    "title":          "<short card title>",
    "description":    "As a <role>, I can <capability>, so that <benefit>.",

    "estimation": {
      "story_points": <int Fibonacci>,
      "complexity":   <int 1–5>,
      "effort":       <int 1–5>,
      "uncertainty":  <int 1–5>
    },

    "prioritization": {
      "priority_rank":    <int, 1=highest>,
      "wsjf_score":       <float>,
      "business_value":   <int 1–10>,
      "time_criticality": <int 1–10>,
      "risk_reduction":   <int 1–10>
    },

    "dependencies": {
      "blocked_by": ["PBI-NNN", ...],
      "blocks":     ["PBI-NNN", ...]
    },

    "planning": {
      "status":        "ready" | "needs_refinement" | "invest_failed" | "oversized",
      "target_sprint": null,
      "tags":          []
    },

    "quality": {
      "invest_pass":          <bool>,
      "invest_flags":         ["small", ...],
      "acceptance_criteria":  []   ← populated by AnalystAgent in Phase 2
    }
  }

State fields used
─────────────────
  artifacts["requirement_list_approved"] — source for Step 9a
  artifacts["requirement_list"]          — fallback source for Step 9a
  artifacts["user_story_draft"]          — Step 9a output / Step 9b input
  artifacts["analyst_estimation"]        — Step 9c output / Step 9b input
  artifacts["product_backlog"]           — Step 9b output
  project_description                    — injected into story generation prompt
  product_backlog_feedback               — injected on PO rejection; cleared on approval
  session_id                             — stamped on artifact
  split_round                            — tracks split loop depth; reset on new cycle
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

_FIBONACCI       = {1, 2, 3, 5, 8, 13, 21}
_INVEST_CRITERIA = ["independent", "negotiable", "valuable", "estimable", "small", "testable"]
_MAX_SPLIT_ROUND = 2   # hard limit on split loop depth


# ─────────────────────────────────────────────────────────────────────────────
# Per-pass addendums
# ─────────────────────────────────────────────────────────────────────────────

_PASS1_ADDENDUM = """\
TASK: PASS 1 — USER STORY CREATION

Convert each active requirement into exactly one user story.
The mandatory format is: "As a <role>, I can <capability>, so that <benefit>."

Do NOT estimate story points. Do NOT assess INVEST. That is AnalystAgent's job.
Your only task is to produce clear, well-formed user stories with correct traceability.

─────────────────────────────────────────────────────
ROLE
─────────────────────────────────────────────────────
Read the stakeholder field and use its value as the role.
If the value is plural, convert to singular: "Students" → "a Student".
If already singular (e.g. "First-year Student"), use without modification.

─────────────────────────────────────────────────────
CAPABILITY
─────────────────────────────────────────────────────
Strip the SHALL or SHALL NOT modal from the statement and rephrase as a
present-tense action verb phrase. Then narrow using the context field to
make the scene specific and concrete.

Example: statement "SHALL provide guidance on responsible AI use" + context
"On the Responsible AI Use guidance page, when a student views the rules"
→ capability: "view clear responsible-AI rules on a dedicated guidance page"

When priority is "high", the capability must be precise and scene-specific.
When priority is "low", keep the capability concise; open thought with "low-urgency:".

─────────────────────────────────────────────────────
BENEFIT
─────────────────────────────────────────────────────
Extract the "So that" clause from the rationale field and rephrase as a
measurable outcome for the named actor.
When rationale has no "So that" clause, derive the benefit from
acceptance_criteria conditions instead.

─────────────────────────────────────────────────────
STATUS
─────────────────────────────────────────────────────
When status is "excluded" → skip entirely, produce no story.
When status is "inferred" → include the story, open thought with "inferred:".

─────────────────────────────────────────────────────
TRACEABILITY
─────────────────────────────────────────────────────
Copy req_id verbatim into source_req_id.
Copy epic verbatim into domain.
Copy source_elicitation_id into the thought field as a traceability note.
Output stories in the same order as the input requirements.

─────────────────────────────────────────────────────
ENRICHMENT (required for AnalystAgent)
─────────────────────────────────────────────────────
Each story must carry an "enrichment" sub-dict with the following requirement
fields copied verbatim. This allows AnalystAgent to perform feasibility
assessment and AC generation without re-reading the requirement list.

  enrichment = {
    "statement":             <req.statement>,
    "context":               <req.context or "">,
    "rationale":             <req.rationale>,
    "acceptance_criteria":   <req.acceptance_criteria as list of strings>,
    "priority":              <req.priority>,
    "source_elicitation_id": <req.source_elicitation_id>,
    "stakeholder":           <req.stakeholder>,
    "req_type":              <req.req_type>
  }
"""

_PASS2_ADDENDUM = """\
TASK: PASS 2 — WSJF PRIORITIZATION

Assign BusinessValue, TimeCriticality, and RiskReduction scores to every story,
compute WSJF, and assign unique priority ranks.

You receive:
  • The user stories with their descriptions and domains.
  • Analyst estimation data: story_points, invest results, dependency mapping.

Do NOT re-estimate story_points. Use the values from analyst_estimation exactly.

─────────────────────────────────────────────────────
WSJF FORMULA
─────────────────────────────────────────────────────
WSJF = (BusinessValue + TimeCriticality + RiskReduction) / StoryPoints
Round to 2 decimal places. Higher WSJF = higher priority = lower rank number.

─────────────────────────────────────────────────────
SCORING DIMENSIONS (1–10 each)
─────────────────────────────────────────────────────
BusinessValue (BV):    Economic or user benefit if delivered now vs. delayed.
TimeCriticality (TC):  Cost of delay — how much the project suffers if this slips.
RiskReduction (RR):    Degree to which delivering this removes a technical or
                       business blocker.

─────────────────────────────────────────────────────
CALIBRATION RULES
─────────────────────────────────────────────────────
• priority="high"   → BV ≥ 7, TC ≥ 6.
• priority="medium" → BV between 4 and 7.
• priority="low"    → BV ≤ 4.

• Stories in the same domain must have internally consistent BV scores.
  The foundational domain delivering core user-facing content ranks above
  supporting domains (educator resources, administration).

• context "Across all system interactions" → raise RR (deferring blocks multiple epics).
• context narrow and scene-specific → lower RR unless stakeholder-critical.

• stakeholder = "Project Team" on a constraint → raise RR (compliance exposure).
• Rich, specific "So that" clause in rationale → raise BV.
• source_elicitation_id = "PD" → lower TC by 1 (inferred, lower confidence).
• acceptance_criteria empty → lower TC (harder to demo).
• status = "inferred" → do not inflate BV.
• req_type = "non_functional" → weight TC on what degrades if deferred.
• req_type = "constraint" → weight BV on compliance exposure avoided.

─────────────────────────────────────────────────────
RANKING RULES
─────────────────────────────────────────────────────
Assign priority_rank as unique integers starting at 1 (1 = highest priority).
Tie-breaking: lower rank number goes to the story with higher BusinessValue.
Output stories ordered by priority_rank ascending (rank 1 first).

NOTE: Dependency-aware rank adjustment is performed by SprintAgent after you
return scores. You do not need to reorder for dependencies — just score correctly.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Enrichment typed model
# ─────────────────────────────────────────────────────────────────────────────

class EnrichmentData(BaseModel):
    """
    Typed enrichment sub-model carrying original requirement fields.

    Replaces Dict[str, Any] to satisfy OpenAI strict JSON schema requirement
    that all objects have additionalProperties=false.

    All fields are Optional with defaults so the LLM can omit fields
    that are not available for a given requirement (e.g. null context).
    """
    statement:             str            = Field(
        default="",
        description="Verbatim requirement statement (The system SHALL …)."
    )
    context:               Optional[str]  = Field(
        default=None,
        description="Where/when the requirement applies. Null if universal."
    )
    rationale:             str            = Field(
        default="",
        description="Business justification including pain and 'So that' outcome."
    )
    acceptance_criteria:   List[str]      = Field(
        default_factory=list,
        description="Original Given-When-Then criteria strings from elicitation."
    )
    priority:              str            = Field(
        default="medium",
        description="high | medium | low — inherited from elicitation."
    )
    source_elicitation_id: str            = Field(
        default="",
        description="EL-NNN traceability key, or 'PD' if inferred from project description."
    )
    stakeholder:           str            = Field(
        default="",
        description="Primary stakeholder role who expressed this requirement."
    )
    req_type:              str            = Field(
        default="functional",
        description="functional | non_functional | constraint | out_of_scope"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pass 1 schemas — Story Creation
# ─────────────────────────────────────────────────────────────────────────────

class UserStoryItem(BaseModel):
    source_req_id: str = Field(
        description="Copied verbatim from the requirement's req_id field (e.g. 'FR-001')."
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
        description="Epic area — copied verbatim from the requirement's epic field."
    )
    # ── FIX: replaced Dict[str, Any] with typed EnrichmentData model ─────────
    # OpenAI strict JSON schema requires all object types to declare
    # additionalProperties=false, which Dict[str, Any] cannot satisfy.
    # EnrichmentData is a fully-typed Pydantic model with explicit fields.
    enrichment: EnrichmentData = Field(
        description=(
            "Original requirement fields for AnalystAgent traceability: "
            "statement, context, rationale, acceptance_criteria, priority, "
            "source_elicitation_id, stakeholder, req_type."
        )
    )
    thought: str = Field(
        description=(
            "1–2 sentence rationale: why this role was chosen, how capability maps "
            "to statement+context, what benefit captures from rationale."
        )
    )


class UserStoryList(BaseModel):
    stories: List[UserStoryItem] = Field(
        description=(
            "One user story per confirmed requirement, in the same order as input. "
            "Requirements with status='excluded' are absent."
        )
    )
    pass_notes: str = Field(
        description=(
            "2–3 sentence summary: total stories generated, excluded items skipped, "
            "any formulation decisions made."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pass 2 schemas — WSJF Prioritization
# ─────────────────────────────────────────────────────────────────────────────

class PrioritizedStoryItem(BaseModel):
    source_req_id:    str
    business_value:   int = Field(ge=1, le=10)
    time_criticality: int = Field(ge=1, le=10)
    risk_reduction:   int = Field(ge=1, le=10)
    wsjf_score:       float = Field(
        description="(BV + TC + RR) / StoryPoints — rounded to 2 decimal places."
    )
    priority_rank: int = Field(
        description="Unique rank. 1 = highest priority. Ties broken by BV."
    )
    thought: str = Field(
        description=(
            "Rationale for BV/TC/RR: which requirement fields drove each score "
            "and why this story ranks where it does relative to peers in the same domain."
        )
    )


class PrioritizedBacklog(BaseModel):
    stories: List[PrioritizedStoryItem] = Field(
        description="All stories ordered by priority_rank ascending (rank 1 first)."
    )
    pass_notes: str = Field(
        description=(
            "Summary: ranking rationale, high-priority clusters by domain, "
            "any tied WSJF scores and how ties were broken."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# SprintAgent
# ─────────────────────────────────────────────────────────────────────────────

class SprintAgent(BaseAgent):
    """
    Product Owner agent — two-step pipeline collaborating with AnalystAgent.

    Step 9a — create_user_stories:
      Pass 1: requirement_list_approved → user_story_draft.
      Called via process_stories().

    Step 9b — build_product_backlog:
      Pass 2: WSJF prioritization using analyst_estimation story_points.
      Pass 3: Dependency-aware rank adjustment + quality gate + assembly.
      Called via process_backlog().

    Split loop:
      When analyst_estimation.has_pending_splits=True, SprintAgent creates
      sub-stories from split_proposals and rebuilds user_story_draft.
      Called via process_splits().
    """

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="sprint_agent")

    def _register_tools(self) -> None:
        # Pipeline is pure extract_structured — no ReAct tools.
        pass

    # =========================================================================
    # LangGraph node entry points
    # =========================================================================
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        pass

    def process_stories(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Step 9a entry point — called by sprint_agent_turn_fn when
        user_story_draft is absent (initial run or after PO rejection rebuild).
        """
        artifacts = state.get("artifacts") or {}
        feedback  = (state.get("product_backlog_feedback") or "").strip()

        if "user_story_draft" in artifacts and not feedback:
            logger.warning(
                "[SprintAgent] process_stories() called but user_story_draft exists "
                "and no feedback pending. Supervisor should not have routed here."
            )
            return {}

        return self._create_user_stories(state)

    def process_splits(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Split loop entry point — called by sprint_agent_turn_fn when
        analyst_estimation.has_pending_splits=True and split_round < MAX.

        Reads split_proposals from analyst_estimation, creates sub-stories,
        replaces user_story_draft with the sub-stories only, increments
        split_round, and clears analyst_estimation so the supervisor routes
        back to analyst_estimation_turn for re-estimation.
        """
        artifacts   = state.get("artifacts") or {}
        estimation  = artifacts.get("analyst_estimation") or {}
        split_round = state.get("split_round", 0)

        if split_round >= _MAX_SPLIT_ROUND:
            logger.warning(
                "[SprintAgent] split_round=%d reached max (%d). "
                "Flagging oversized stories and proceeding to assembly.",
                split_round, _MAX_SPLIT_ROUND,
            )
            # Do not split further — assembly will flag oversized items.
            return {"split_round": split_round}

        stories       = estimation.get("stories") or []
        new_stories:  List[Dict[str, Any]] = []
        replaced_ids: List[str] = []

        for story_est in stories:
            if not story_est.get("needs_split"):
                continue
            split_props = story_est.get("split_proposals") or []
            if not split_props:
                logger.warning(
                    "[SprintAgent] Story %s needs_split=True but no split_proposals. Skipping.",
                    story_est.get("source_req_id", "?"),
                )
                continue

            parent_id = story_est.get("source_req_id", "")
            replaced_ids.append(parent_id)

            # Find original story data from user_story_draft to inherit enrichment
            draft        = artifacts.get("user_story_draft") or {}
            draft_lookup = {s.get("source_req_id"): s for s in (draft.get("stories") or [])}
            parent_story = draft_lookup.get(parent_id, {})

            for idx, proposal in enumerate(split_props):
                suffix   = chr(ord("a") + idx)   # a, b, c, …
                sub_id   = f"{parent_id}{suffix}"

                new_stories.append({
                    "source_req_id": sub_id,
                    "source_parent_req_id": parent_id,   # traceability to original
                    "is_split_child": True,
                    "split_suffix":   suffix,
                    "source_type":    parent_story.get("source_type", "functional"),
                    "title":          proposal.get("title", f"{parent_story.get('title', '')} ({suffix})"),
                    "description":    (
                        f"As a {self._extract_role(parent_story.get('description', ''))}, "
                        f"I can {proposal.get('capability', '')}, "
                        f"so that {self._extract_benefit(parent_story.get('description', ''))}."
                    ),
                    "domain":      parent_story.get("domain", ""),
                    # Carry enrichment forward — already a dict at this point
                    # (serialised from EnrichmentData when stored in artifact)
                    "enrichment":  parent_story.get("enrichment", {}),
                    "thought":     f"Split child {suffix} of {parent_id}: {proposal.get('reasoning', '')}",
                })

        if not new_stories:
            logger.info(
                "[SprintAgent] No split sub-stories created (needs_split=True but "
                "split_proposals empty). Forcing split_round to MAX to proceed to assembly."
            )
            # Force split_round to MAX so sprint_agent_turn_fn routes to
            # process_backlog() instead of re-entering process_splits().
            return {"split_round": _MAX_SPLIT_ROUND}

        # Rebuild user_story_draft: keep non-split stories, replace split ones with children
        existing_stories = [
            s for s in ((artifacts.get("user_story_draft") or {}).get("stories") or [])
            if s.get("source_req_id") not in replaced_ids
        ]

        updated_draft = {
            **(artifacts.get("user_story_draft") or {}),
            "stories":    existing_stories + new_stories,
            "split_round": split_round + 1,
        }

        # Clear analyst_estimation so supervisor routes back to analyst_estimation_turn
        updated_artifacts = {**artifacts, "user_story_draft": updated_draft}
        updated_artifacts.pop("analyst_estimation", None)

        logger.info(
            "[SprintAgent] Split round %d → %d: created %d sub-stories from %d parent(s).",
            split_round, split_round + 1, len(new_stories), len(replaced_ids),
        )

        return {
            "artifacts":   updated_artifacts,
            "split_round": split_round + 1,
        }

    def process_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Step 9b entry point — called by sprint_agent_turn_fn when both
        user_story_draft and analyst_estimation are present and
        has_pending_splits is False (or split_round has reached the limit).
        """
        artifacts = state.get("artifacts") or {}
        feedback  = (state.get("product_backlog_feedback") or "").strip()

        if "product_backlog" in artifacts and not feedback:
            logger.warning(
                "[SprintAgent] process_backlog() called but product_backlog exists "
                "and no feedback pending. Supervisor should not have routed here."
            )
            return {}

        return self._build_product_backlog(state)

    # =========================================================================
    # Step 9a — User Story Creation
    # =========================================================================

    def _create_user_stories(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts    = state.get("artifacts") or {}
        project_desc = state.get("project_description", "")
        feedback     = (state.get("product_backlog_feedback") or "").strip()

        req_list = (
            artifacts.get("requirement_list_approved")
            or artifacts.get("requirement_list")
            or {}
        )
        all_requirements    = self._extract_all_requirements(req_list)
        active_requirements = [
            r for r in all_requirements
            if r.get("status", "confirmed") != "excluded"
            and r.get("req_type", r.get("type", "")) != "out_of_scope"
        ]

        if not active_requirements:
            logger.error("[SprintAgent] No active requirements found.")
            return {"errors": ["SprintAgent: no confirmed/inferred requirements found."]}

        logger.info(
            "[SprintAgent] Creating user stories — %d active requirements "
            "(%d total, %d excluded/OOS).",
            len(active_requirements),
            len(all_requirements),
            len(all_requirements) - len(active_requirements),
        )

        try:
            story_list = self._pass1_create_stories(
                active_requirements, project_desc, feedback
            )
            logger.info(
                "[SprintAgent] Pass 1 complete — %d stories created.", len(story_list.stories)
            )

            # Serialise stories: convert EnrichmentData to dict for artifact storage
            serialised_stories = []
            for s in story_list.stories:
                story_dict = s.model_dump()
                # enrichment is already serialised to dict by model_dump()
                serialised_stories.append(story_dict)

            artifacts["user_story_draft"] = {
                "id":          str(uuid.uuid4()),
                "session_id":  state.get("session_id", ""),
                "created_at":  datetime.now().isoformat(),
                "stories":     serialised_stories,
                "total_stories": len(story_list.stories),
                "pass_notes":  story_list.pass_notes,
                **({"rebuild_feedback": feedback} if feedback else {}),
            }

            # Reset split_round when starting a fresh story creation cycle.
            return {
                "artifacts":   artifacts,
                "split_round": 0,
            }

        except Exception as exc:
            logger.error("[SprintAgent] Story creation failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent story creation error: {exc}"]}

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 1 — Story Generation (LLM call)
    # ─────────────────────────────────────────────────────────────────────────

    def _pass1_create_stories(
        self,
        requirements: List[Dict],
        project_desc: str,
        feedback:     str = "",
    ) -> UserStoryList:

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS1_ADDENDUM
            + self._feedback_block(feedback, "user story creation")
        )

        user_prompt = (
            f"PROJECT CONTEXT:\n{project_desc or '(not provided)'}\n\n"
            f"REQUIREMENTS TO CONVERT ({len(requirements)} items):\n\n"
            f"{self._format_requirements_block(requirements)}\n\n"
            "Generate exactly ONE User Story for EVERY requirement listed above.\n"
            "Preserve input order. Include the enrichment sub-object for each story.\n"
            "Requirements with status='excluded' have already been removed.\n\n"
            "ENRICHMENT FIELD INSTRUCTIONS:\n"
            "  The enrichment field is a structured object with these exact fields:\n"
            "    statement, context, rationale, acceptance_criteria (list of strings),\n"
            "    priority, source_elicitation_id, stakeholder, req_type.\n"
            "  Copy each field verbatim from the source requirement.\n"
            "  If context is null/missing, set it to null.\n"
            "  If acceptance_criteria is empty, set it to []."
        )

        return self.extract_structured(
            schema=UserStoryList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # =========================================================================
    # Step 9b — WSJF Prioritization + Assembly
    # =========================================================================

    def _build_product_backlog(self, state: Dict[str, Any]) -> Dict[str, Any]:
        artifacts    = state.get("artifacts") or {}
        project_desc = state.get("project_description", "")
        feedback     = (state.get("product_backlog_feedback") or "").strip()
        split_round  = state.get("split_round", 0)

        draft      = artifacts.get("user_story_draft") or {}
        estimation = artifacts.get("analyst_estimation") or {}

        stories    = draft.get("stories") or []
        est_stories = estimation.get("stories") or []

        if not stories:
            logger.error("[SprintAgent] user_story_draft has no stories for assembly.")
            return {"errors": ["SprintAgent: user_story_draft is empty."]}

        if not est_stories:
            logger.error("[SprintAgent] analyst_estimation has no stories for assembly.")
            return {"errors": ["SprintAgent: analyst_estimation is empty."]}

        logger.info(
            "[SprintAgent] Building product backlog — %d stories, split_round=%d.",
            len(stories), split_round,
        )

        try:
            # ── Pass 2: WSJF Prioritization ─────────────────────────────────
            prioritized = self._pass2_wsjf(stories, est_stories, project_desc, feedback)
            logger.info("[SprintAgent] Pass 2 complete — %d stories ranked.", len(prioritized.stories))

            # ── Pass 3: Dependency-aware adjustment + quality gate + assembly ─
            return self._pass3_assembly(
                prioritized, stories, est_stories, state, feedback, split_round
            )

        except Exception as exc:
            logger.error("[SprintAgent] Backlog assembly failed: %s", exc, exc_info=True)
            return {"errors": [f"SprintAgent assembly error: {exc}"]}

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 2 — WSJF Prioritization (LLM call)
    # ─────────────────────────────────────────────────────────────────────────

    def _pass2_wsjf(
        self,
        stories:     List[Dict],
        est_stories: List[Dict],
        project_desc: str,
        feedback:    str = "",
    ) -> PrioritizedBacklog:

        system_prompt = (
            self.profile.prompt
            + "\n\n"
            + _PASS2_ADDENDUM
            + self._feedback_block(feedback, "WSJF prioritization")
        )

        # Build estimation lookup by source_req_id
        est_lookup: Dict[str, Dict] = {
            s.get("source_req_id", ""): s for s in est_stories
        }

        stories_block  = self._format_stories_with_estimation(stories, est_lookup)
        priority_block = self._format_priority_signals(stories, est_lookup)

        user_prompt = (
            f"PROJECT CONTEXT:\n{project_desc or '(not provided)'}\n\n"
            f"STORIES WITH ANALYST ESTIMATION ({len(stories)} items):\n\n"
            f"{stories_block}\n\n"
            f"PRIORITY SIGNALS (from requirement fields):\n{priority_block}\n\n"
            "Assign WSJF scores and unique ranks for ALL stories.\n"
            "Use story_points from analyst_estimation exactly — do NOT re-estimate.\n"
            "Output stories ordered by priority_rank ascending (rank 1 first)."
        )

        return self.extract_structured(
            schema=PrioritizedBacklog,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 3 — Dependency-Aware Adjustment + Quality Gate + Assembly
    # (deterministic — no LLM call)
    # ─────────────────────────────────────────────────────────────────────────

    def _pass3_assembly(
        self,
        prioritized:  PrioritizedBacklog,
        stories:      List[Dict],
        est_stories:  List[Dict],
        state:        Dict[str, Any],
        feedback:     str = "",
        split_round:  int = 0,
    ) -> Dict[str, Any]:
        """
        Deterministic assembly pass — no LLM call.

        Steps:
          1. Build lookups (story data, estimation, WSJF scores).
          2. Dependency-aware rank adjustment: if Story A is blocked_by Story B
             and rank(A) < rank(B), promote Story B above Story A.
          3. Assign sequential PBI IDs. Split children inherit parent seq + suffix.
          4. Snap non-Fibonacci story_points.
          5. Recompute WSJF from raw scores.
          6. Validate user story format.
          7. Build consolidated PBI schema (no enrichment block, no top-level INVEST booleans).
          8. Write product_backlog artifact.
        """
        # ── 1. Build lookups ──────────────────────────────────────────────
        story_lookup: Dict[str, Dict] = {
            s.get("source_req_id", ""): s for s in stories
        }
        est_lookup: Dict[str, Dict] = {
            s.get("source_req_id", ""): s for s in est_stories
        }
        wsjf_lookup: Dict[str, PrioritizedStoryItem] = {
            p.source_req_id: p for p in prioritized.stories
        }

        # Ordered by LLM-assigned rank
        ordered = sorted(prioritized.stories, key=lambda s: s.priority_rank)

        # ── 2. Dependency-aware rank adjustment ───────────────────────────
        # Build req_id → pbi index map (pre-adjustment)
        rank_map: Dict[str, int] = {p.source_req_id: p.priority_rank for p in ordered}

        # Build dependency map from analyst_estimation
        dep_map: Dict[str, List[str]] = {}   # req_id → list of req_ids it is blocked_by
        for est in est_stories:
            rid = est.get("source_req_id", "")
            deps = est.get("dependencies", {})
            blocked_by = deps.get("blocked_by") or []
            if blocked_by:
                dep_map[rid] = blocked_by

        # Promote blockers: if A is blocked_by B and rank(A) < rank(B),
        # swap B's rank to rank(A) - 0.5 (resolved to int after sort).
        adjusted_ranks: Dict[str, float] = {p.source_req_id: float(p.priority_rank) for p in ordered}

        for req_id, blockers in dep_map.items():
            for blocker_id in blockers:
                if blocker_id not in adjusted_ranks:
                    continue
                story_rank   = adjusted_ranks.get(req_id, 9999.0)
                blocker_rank = adjusted_ranks.get(blocker_id, 9999.0)
                if story_rank < blocker_rank:
                    # Blocker must come before the story — promote it
                    adjusted_ranks[blocker_id] = story_rank - 0.5
                    logger.info(
                        "[SprintAgent] Dependency-aware promotion: '%s' (was rank %.1f) "
                        "promoted before '%s' (rank %.1f).",
                        blocker_id, blocker_rank, req_id, story_rank,
                    )

        # Re-sort with adjusted ranks and re-assign integer ranks
        ordered_ids   = sorted(adjusted_ranks.keys(), key=lambda k: adjusted_ranks[k])
        rank_reassign: Dict[str, int] = {rid: i + 1 for i, rid in enumerate(ordered_ids)}

        # ── 3–7. Build PBI items ──────────────────────────────────────────
        items:           List[Dict[str, Any]] = []
        format_warnings: List[str]            = []
        fib_warnings:    List[str]            = []
        invest_warnings: List[str]            = []
        oversized:       List[str]            = []
        seen_req_ids:    Dict[str, int]        = {}
        seq              = 1
        # Track parent seq for split children: parent_req_id → seq_number
        parent_seq_map:  Dict[str, int]        = {}

        for req_id in ordered_ids:
            story = story_lookup.get(req_id)
            est   = est_lookup.get(req_id)
            wsjf  = wsjf_lookup.get(req_id)

            if not story or not wsjf:
                logger.warning("[SprintAgent] Missing story or WSJF data for '%s'. Skipping.", req_id)
                continue

            # ── Duplicate detection ────────────────────────────────────────
            if req_id in seen_req_ids:
                format_warnings.append(
                    f"Duplicate source_req_id '{req_id}' (first at PBI-{seen_req_ids[req_id]:03d})."
                )
            seen_req_ids[req_id] = seq

            # ── Assign PBI ID ──────────────────────────────────────────────
            is_split_child = story.get("is_split_child", False)
            split_suffix   = story.get("split_suffix", "")
            parent_req_id  = story.get("source_parent_req_id", "")

            if is_split_child and parent_req_id in parent_seq_map:
                pbi_id = f"PBI-{parent_seq_map[parent_req_id]:03d}{split_suffix}"
            else:
                pbi_id = f"PBI-{seq:03d}"
                if not is_split_child:
                    parent_seq_map[req_id] = seq
                seq += 1

            # ── Fibonacci snap ─────────────────────────────────────────────
            sp = (est or {}).get("estimation", {}).get("story_points", 3) if est else 3
            if isinstance(sp, dict):
                sp = sp.get("story_points", 3)
            if sp not in _FIBONACCI:
                snapped = min(_FIBONACCI, key=lambda f: abs(f - sp))
                fib_warnings.append(f"{pbi_id} [{req_id}]: story_points {sp} → snapped to {snapped}.")
                sp = snapped

            # ── WSJF recompute (guard against LLM rounding drift) ─────────
            bv   = wsjf.business_value
            tc   = wsjf.time_criticality
            rr   = wsjf.risk_reduction
            wsjf_score = round((bv + tc + rr) / sp, 2)

            # ── INVEST from analyst_estimation ─────────────────────────────
            invest_data  = (est or {}).get("invest", {}) if est else {}
            invest_flags = invest_data.get("invest_flags", [])
            invest_pass  = invest_data.get("invest_pass", True)
            if invest_flags:
                invest_warnings.append(f"{pbi_id} [{req_id}]: invest_flags={invest_flags}.")

            # ── Oversized flag (after max split rounds) ───────────────────
            est_data = (est or {}).get("estimation", {}) if est else {}
            is_oversized = bool(est_data.get("needs_split") if est else False) and split_round >= _MAX_SPLIT_ROUND

            if is_oversized:
                oversized.append(req_id)

            # ── Status ────────────────────────────────────────────────────
            if is_oversized:
                status = "oversized"
            elif len(invest_flags) >= 3:
                status = "invest_failed"
            elif not invest_pass:
                status = "needs_refinement"
            else:
                status = "ready"

            # ── User story format check ────────────────────────────────────
            desc     = (story.get("description") or "").strip()
            desc_low = desc.lower()
            format_ok = (
                (desc_low.startswith("as a ") or desc_low.startswith("as an "))
                and ", i can " in desc_low
                and ", so that " in desc_low
            )
            if not format_ok:
                format_warnings.append(
                    f"{pbi_id} [{req_id}]: description does not match format — got: '{desc[:80]}'"
                )
                if status == "ready":
                    status = "needs_refinement"

            # ── Resolve PBI-level dependency IDs ─────────────────────────
            # Analyst uses source_req_ids; we store PBI IDs in the artifact.
            # Full resolution happens after all items are built (post-loop).
            raw_blocked_by = (est or {}).get("dependencies", {}).get("blocked_by", []) if est else []
            raw_blocks     = (est or {}).get("dependencies", {}).get("blocks", [])     if est else []

            # ── Tags (derived from type and domain) ───────────────────────
            tags: List[str] = [story.get("domain", "").lower().replace(" ", "_")]
            if story.get("source_type") == "non_functional":
                tags.append("non_functional")
            elif story.get("source_type") == "constraint":
                tags.append("constraint")

            items.append({
                "id":             pbi_id,
                "source_req_id":  req_id,
                "type":           story.get("source_type", "functional"),
                "domain":         story.get("domain", ""),
                "title":          story.get("title", ""),
                "description":    desc,

                "estimation": {
                    "story_points": sp,
                    "complexity":   est_data.get("complexity", 2) if est else 2,
                    "effort":       est_data.get("effort", 2)      if est else 2,
                    "uncertainty":  est_data.get("uncertainty", 2) if est else 2,
                },

                "prioritization": {
                    "priority_rank":    rank_reassign.get(req_id, seq),
                    "wsjf_score":       wsjf_score,
                    "business_value":   bv,
                    "time_criticality": tc,
                    "risk_reduction":   rr,
                },

                # Stored as source_req_id references; resolved to PBI IDs below
                "_raw_blocked_by": raw_blocked_by,
                "_raw_blocks":     raw_blocks,

                "planning": {
                    "status":        status,
                    "target_sprint": None,
                    "tags":          tags,
                },

                "quality": {
                    "invest_pass":         invest_pass,
                    "invest_flags":        invest_flags,
                    "acceptance_criteria": [],   # populated by AnalystAgent in Phase 2
                },
            })

        # ── Resolve dependency source_req_id → PBI IDs ────────────────────
        # Build reverse map: source_req_id → pbi_id
        req_to_pbi: Dict[str, str] = {item["source_req_id"]: item["id"] for item in items}

        for item in items:
            item["dependencies"] = {
                "blocked_by": [
                    req_to_pbi.get(rid, rid) for rid in item.pop("_raw_blocked_by", [])
                ],
                "blocks": [
                    req_to_pbi.get(rid, rid) for rid in item.pop("_raw_blocks", [])
                ],
            }

        # ── Build artifact ─────────────────────────────────────────────────
        total_pts    = sum(i["estimation"]["story_points"] for i in items)
        ready_count  = sum(1 for i in items if i["planning"]["status"] == "ready")
        refine_count = sum(1 for i in items if i["planning"]["status"] == "needs_refinement")
        failed_count = sum(1 for i in items if i["planning"]["status"] == "invest_failed")
        over_count   = sum(1 for i in items if i["planning"]["status"] == "oversized")

        session_id = state.get("session_id", str(uuid.uuid4()))
        artifacts  = dict(state.get("artifacts") or {})

        product_backlog: Dict[str, Any] = {
            "id":                     str(uuid.uuid4()),
            "session_id":             session_id,
            "source_artifact":        "requirement_list_approved",
            "status":                 "draft",
            "total_items":            len(items),
            "total_story_points":     total_pts,
            "ready_count":            ready_count,
            "needs_refinement_count": refine_count,
            "invest_failed_count":    failed_count,
            "oversized_count":        over_count,
            "split_round":            split_round,
            "items":                  items,
            "methodology": {
                "story_format":     "As a <role>, I can <capability>, so that <benefit>.",
                "estimation":       "Fibonacci via AnalystAgent (Complexity + Effort + Uncertainty)",
                "prioritization":   "WSJF = (BV + TC + RR) / StoryPoints with dependency-aware ranking",
                "quality_gate":     "INVEST flags from AnalystAgent; format validation by SprintAgent",
            },
            "pass_notes":      prioritized.pass_notes,
            "quality_warnings": {
                "invest":    invest_warnings,
                "format":    format_warnings,
                "fibonacci": fib_warnings,
                "oversized": [
                    f"{rid}: exceeded 8 points after {_MAX_SPLIT_ROUND} split rounds."
                    for rid in oversized
                ],
            },
            "created_at": datetime.now().isoformat(),
            **({"rebuild_feedback": feedback} if feedback else {}),
        }

        artifacts["product_backlog"] = product_backlog

        logger.info(
            "[SprintAgent] Assembly complete — %d items | %d pts | "
            "ready=%d refinement=%d invest_failed=%d oversized=%d",
            len(items), total_pts, ready_count, refine_count, failed_count, over_count,
        )
        if invest_warnings:
            logger.warning("[SprintAgent] INVEST warnings (%d).", len(invest_warnings))
        if format_warnings:
            logger.warning("[SprintAgent] Format warnings (%d).", len(format_warnings))
        if fib_warnings:
            logger.warning("[SprintAgent] Fibonacci snaps (%d).", len(fib_warnings))
        if oversized:
            logger.warning("[SprintAgent] Oversized stories (%d): %s", len(oversized), oversized)

        return {"artifacts": artifacts}

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _extract_role(description: str) -> str:
        """Extract the role from 'As a <role>, I can ...' format."""
        desc_lower = description.lower()
        if desc_lower.startswith("as a "):
            part = description[5:]
        elif desc_lower.startswith("as an "):
            part = description[6:]
        else:
            return "User"
        return part.split(",")[0].strip()

    @staticmethod
    def _extract_benefit(description: str) -> str:
        """Extract the benefit clause from '..., so that <benefit>' format."""
        lower = description.lower()
        idx   = lower.find(", so that ")
        if idx == -1:
            return "achieve the intended outcome"
        return description[idx + len(", so that "):].rstrip(".")

    @staticmethod
    def _format_stories_with_estimation(
        stories:    List[Dict],
        est_lookup: Dict[str, Dict],
    ) -> str:
        """Render stories alongside estimation data for Pass 2 WSJF prompt."""
        lines: List[str] = []
        for i, story in enumerate(stories, start=1):
            req_id = story.get("source_req_id", "?")
            est    = est_lookup.get(req_id, {})
            est_d  = est.get("estimation", {})
            invest = est.get("invest", {})

            block = (
                f"[{i}] source_req_id={req_id}  "
                f"pts={est_d.get('story_points', '?')}  "
                f"type={story.get('source_type', '?')}  "
                f"domain={story.get('domain', '?')}\n"
                f"       title:        {story.get('title', '')}\n"
                f"       description:  {story.get('description', '')}\n"
                f"       invest_flags: {invest.get('invest_flags') or 'none'}\n"
                f"       blocked_by:   {est.get('dependencies', {}).get('blocked_by') or 'none'}\n"
            )
            lines.append(block)
        return "\n".join(lines)

    @staticmethod
    def _format_priority_signals(
        stories:    List[Dict],
        est_lookup: Dict[str, Dict],
    ) -> str:
        """Render priority signals from enrichment fields for Pass 2 WSJF prompt."""
        lines: List[str] = []
        for story in stories:
            req_id  = story.get("source_req_id", "?")
            # enrichment may be a dict (serialised from artifact) or EnrichmentData
            raw_enr = story.get("enrichment") or {}
            enr     = raw_enr if isinstance(raw_enr, dict) else raw_enr.model_dump()
            est     = est_lookup.get(req_id, {})
            rat     = enr.get("rationale", "")
            so_that = ""
            if "so that" in rat.lower():
                so_that = rat[rat.lower().index("so that"):][:120]
            context     = (enr.get("context") or "").lower()
            ctx_breadth = (
                "broad (cross-cutting)"
                if "across all system interactions" in context or not context
                else "narrow (scoped)"
            )
            lines.append(
                f"  {req_id}: "
                f"priority={enr.get('priority', '?')}  "
                f"stakeholder={enr.get('stakeholder', '?')}  "
                f"elicit_id={enr.get('source_elicitation_id', '?')}  "
                f"status={enr.get('status', 'confirmed')}  "
                f"context_breadth={ctx_breadth}  "
                + (f'so_that="{so_that}"' if so_that else "so_that=(absent)")
            )
        return "\n".join(lines)

    @staticmethod
    def _extract_all_requirements(req_list: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Flatten requirements from the requirement_list artifact.
        Handles both schema variants (req_id/req_type and id/type).
        Returns ALL items — status filtering is done by the caller.
        """
        if not req_list:
            return []
        for key in ("requirements", "items", "requirement_items", "all_requirements"):
            if key in req_list and isinstance(req_list[key], list):
                return list(req_list[key])
        merged: List[Dict] = []
        for key in ("functional_requirements", "non_functional_requirements", "constraints"):
            sub = req_list.get(key, [])
            if isinstance(sub, list):
                merged.extend(sub)
        return merged

    @staticmethod
    def _format_requirements_block(requirements: List[Dict]) -> str:
        """
        Render requirements as a rich, readable block for Pass 1 LLM prompt.
        Handles both old schema (id/type/domain) and new schema (req_id/req_type/epic).
        """
        lines: List[str] = []
        for r in requirements:
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
                rat_short = rationale[:240] + ("…" if len(rationale) > 240 else "")
                block += f"  rationale:   {rat_short}\n"
            if isinstance(acs, list) and acs:
                for idx, ac in enumerate(acs, 1):
                    block += f"  AC[{idx}]:      {ac}\n"
            else:
                block += "  AC:          (none)\n"
            if elicit_id:
                block += f"  elicit_id:  {elicit_id}\n"
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