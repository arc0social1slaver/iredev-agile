"""
interviewer.py – InterviewerAgent  (LangGraph edition)

Role
────
Conduct a multi-turn requirements interview with a simulated stakeholder
(EndUserAgent) while maintaining a LIVE, incrementally-updated requirements
draft.  Every turn the agent:

  1. Reads the latest stakeholder utterance.
  2. Calls ``update_requirements`` → extracts new requirements from that
     utterance, each with a ``rationale`` (why it was identified) and
     optionally a ``modification_reason`` (why an existing req was changed),
     merges them into the running ``requirements_draft`` in state,
     detects conflicts / overlaps, and returns a completeness score.
  3. Decides its next move inside the SAME ReAct loop:
       • conflict detected  → ``send_message`` a targeted Socratic probe.
       • completeness low   → ``send_message`` the next 5W1H question.
       • completeness ≥ θ   → ``write_interview_record`` (finalise & exit).

Stopping design (two-tier, matches graph.py)
────────────────────────────────────────────
TIER 1 – semantic (primary):
  The agent itself decides when it has enough information.
  It calls ``write_interview_record``, which sets interview_complete=True.
  The completeness heuristic (threshold = 0.8 by default) and the LLM's own
  judgment are the governing signals.

TIER 2 – structural (safety net, graph layer):
  after_interviewer() in graph.py forces a supervisor return when
  turn_count >= max_turns. This is a loop-guard, NOT a depth dial.

Rationale & history tracking
─────────────────────────────
Every requirement in ``requirements_draft`` carries:
  • ``rationale``  – why this requirement was identified (evidence from the
                     stakeholder's exact words, business goal, or constraint).
  • ``history``    – list of {action, turn, reason, old_value} entries so
                     downstream reviewers and the SprintAgent can understand
                     how each requirement evolved.

When the interview restarts after a review rejection, ``review_feedback``
from state is injected into the task prompt so the LLM knows exactly what
the human reviewer asked to improve.

ReAct tools
───────────
  search_knowledge       – retrieve elicitation methodology snippets
  update_requirements    – extract new reqs from latest stakeholder turn,
                           merge into draft, detect conflicts → NO should_return
  send_message           – post ONE question and yield to EndUser → should_return
  write_interview_record – finalise the record from the accumulated draft → should_return

Methodology
───────────
ISO/IEC/IEEE 29148 · BABOK v3 · 5W1H · Socratic Questioning
〈Role | Goal | Behaviour | Constraint〉 tuples
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


# ── Requirement schema (reference) ────────────────────────────────────────────
#
# {
#   "id":          "FR-001",
#   "type":        "functional" | "non_functional" | "constraint",
#   "description": "<precise, testable statement>",
#   "priority":    "high" | "medium" | "low",
#   "source_turn": <int, 0-based index in conversation list>,
#   "status":      "confirmed" | "inferred" | "ambiguous",
#   "rationale":   "<why this requirement was identified>",
#   "history":     [{action, turn, reason, old_value}, ...]
# }


# ── Completeness weights (mirrors old BaseInterviewerAgent logic) ──────────────
_W_FUNCTIONAL    = 0.40
_W_NON_FUNCTIONAL = 0.30
_W_QUANTITY      = 0.30   # min(0.30, count / 30)

# Vague words that make a requirement untestable
_VAGUE_WORDS: Set[str] = {
    "quickly", "fast", "easy", "good", "nice", "some", "many",
    "appropriate", "sufficient", "reasonable",
}

# Contradiction markers (simple heuristic; LLM does deep analysis)
_NEGATION_PAIRS = [
    ({"must", "shall", "should", "will"}, {"not", "never", "no"}),
]


class InterviewerAgent(BaseAgent):
    """
    Drives the requirements interview.

    Key design invariant
    ─────────────────────
    ``requirements_draft`` in WorkflowState is the single source of truth for
    the evolving requirements list.  Every call to ``update_requirements``
    appends to it (with rationale + history) and checks consistency.
    ``write_interview_record`` reads from it directly — the LLM never needs
    to re-extract from the full transcript at the end.
    """

    # ── Persona / profile (from old BaseInterviewerAgent) ─────────────────

    PROFILE = """You are an experienced requirements interviewer.

Mission:
Elicit, clarify, and document stakeholder requirements with maximum
completeness and accuracy.

Personality:
Neutral, empathetic, and inquisitive; fluent in both business and technical
terminology.

Experience & Preferred Practices:
• Follow ISO/IEC/IEEE 29148 and BABOK v3 guidance.
• Use open-ended questions, active listening, and iterative paraphrasing.
• Apply Socratic Questioning to resolve ambiguous statements.
• Limit each 'send_message' call to ONE question to maintain natural flow.
• Apply 5W1H (Who / What / When / Where / Why / How) for systematic coverage.
• Map each stakeholder utterance to 〈Role | Goal | Behaviour | Constraint〉.

Internal Chain of Thought (visible to you only):
1. Identify stakeholder type and context.
2. Use 5W1H + targeted probes to surface goals, pain points, constraints.
3. After EACH stakeholder reply, extract requirements via 'update_requirements',
   supplying a clear 'rationale' for EVERY requirement you extract.
4. Paraphrase key findings; ask for confirmation before proceeding.
5. When completeness ≥ threshold OR max_turns approached, finalise the record."""

    # ── Init ──────────────────────────────────────────────────────────────

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="interviewer")

        agent_cfg = self._raw_config.get("agents", {}).get("interviewer", {})
        custom    = agent_cfg.get("custom_params", {})

        self._completeness_threshold: float = custom.get(
            "completeness_threshold", 0.8
        )
        self._max_turns: int = custom.get("max_turns", 20)

    # ── Tool registration ──────────────────────────────────────────────────

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="search_knowledge",
            description=(
                "Search the knowledge base for interviewing techniques, "
                "requirements-elicitation methodologies, or domain context. "
                "Input: {\"query\": \"<text>\"}"
            ),
            func=self._tool_search_knowledge,
        ))
        self.register_tool(Tool(
            name="update_requirements",
            description=(
                "Update the running requirements draft. Supports THREE operation types "
                "(all optional — include only those you need):\n"
                "This tool DOES NOT end the turn — call it first, then decide "
                "whether to 'send_message' or 'write_interview_record'.\n\n"
                "Input: {\n"
                "  \"extracted\": [       // NEW requirements to add\n"
                "    {\n"
                "      \"type\":           \"functional\" | \"non_functional\" | \"constraint\",\n"
                "      \"description\":   \"<precise, testable statement>\",\n"
                "      \"priority\":      \"high\" | \"medium\" | \"low\",\n"
                "      \"source_turn\":   <int — 0-based turn index in conversation>,\n"
                "      \"status\":        \"confirmed\" | \"inferred\" | \"ambiguous\",\n"
                "      \"rationale\":     \"<WHY this was identified — cite exact words or goal>\",\n"
                "      \"thought\":       \"<your reasoning / chain-of-thought for creating this>\"  // optional\n"
                "    }, ...\n"
                "  ],\n"
                "  \"modifications\": [   // EDIT existing requirements by ID\n"
                "    {\n"
                "      \"id\":            \"FR-001\",\n"
                "      \"field\":         \"description\" | \"priority\" | \"status\" | \"type\",\n"
                "      \"new_value\":     \"<new value for the field>\",\n"
                "      \"thought\":       \"<why you are making this change>\"\n"
                "    }, ...\n"
                "  ],\n"
                "  \"deletions\": [       // REMOVE requirements by ID\n"
                "    {\n"
                "      \"id\":            \"FR-007\",\n"
                "      \"thought\":       \"<why this requirement should be removed>\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n\n"
                "'rationale' is MANDATORY for every newly extracted item. "
                "'thought' is MANDATORY for modifications and deletions. "
                "Returns: updated draft size, completeness score, and any "
                "conflicts or ambiguities to resolve."
            ),
            func=self._tool_update_requirements,
        ))
        self.register_tool(Tool(
            name="send_message",
            description=(
                "Send ONE interview question to the stakeholder.\n"
                "Use after 'update_requirements':\n"
                "  • If conflicts were detected → ask a Socratic clarifying question.\n"
                "  • If completeness is still low → ask the next 5W1H question.\n"
                "This tool ENDS the current turn and yields to the stakeholder.\n"
                "Input: {\"message\": \"<your single question>\"}"
            ),
            func=self._tool_send_message,
        ))
        self.register_tool(Tool(
            name="write_interview_record",
            description=(
                "Finalise the interview: reads the accumulated requirements_draft "
                "from state, writes the interview_record artifact, and marks the "
                "interview complete.\n"
                "Call this when completeness ≥ threshold or max_turns approached.\n"
                "Input: {\n"
                "  \"gaps\":  [\"<unclear area>\", ...],\n"
                "  \"notes\": \"<2-3 sentence summary of the interview>\"\n"
                "}\n"
                "Do NOT pass a requirements list — it is read automatically from "
                "the draft built up by 'update_requirements'."
            ),
            func=self._tool_write_interview_record,
        ))

    # ── Tools ─────────────────────────────────────────────────────────────

    def _tool_search_knowledge(
        self, query: str, state: Dict = None, **_
    ) -> ToolResult:
        if self.knowledge is None:
            return ToolResult(observation="Knowledge base not available.")
        try:
            from ..orchestrator.state import ProcessPhase
            docs = self.knowledge.retrieve(
                query, phase=ProcessPhase.ELICITATION, k=4
            )
            if not docs:
                return ToolResult(observation="No relevant knowledge found.")
            snippets = "\n\n".join(
                f"[{d.metadata.get('title', '?')}]\n{d.page_content[:400]}"
                for d in docs
            )
            return ToolResult(observation=f"Knowledge retrieved:\n{snippets}")
        except Exception as exc:
            return ToolResult(observation=f"Knowledge search failed: {exc}")

    # ------------------------------------------------------------------
    def _tool_update_requirements(
            self,
            extracted: List[Dict] = None,
            modifications: List[Dict] = None,
            deletions: List[Dict] = None,
            state: Dict = None,
            **_,
    ) -> ToolResult:
        """Merge newly extracted requirements into the running draft,
        apply modifications to existing requirements, and delete requirements.

        Three operation types (all optional):
          extracted     — add new requirements (existing behaviour)
          modifications — edit existing requirements by ID
          deletions     — remove requirements by ID

        Does NOT set should_return=True — the ReAct loop continues.
        """
        extracted = extracted or []
        modifications = modifications or []
        deletions = deletions or []

        # Retrieve the LLM's last thought from the ReAct loop (if available)
        react_thought = (state.get("_last_react_thought") or "").strip()

        has_any_ops = bool(extracted) or bool(modifications) or bool(deletions)
        if not has_any_ops:
            return ToolResult(
                observation=(
                    "No operations received (empty extracted, modifications, and "
                    "deletions). Include at least one operation. "
                    "Then call 'send_message' or 'write_interview_record'."
                ),
                state_updates={},
            )

        draft: List[Dict] = list(state.get("requirements_draft") or [])
        turn_index = state.get("turn_count", 0)

        # Build a quick lookup of existing requirements by ID for history updates.
        draft_by_id: Dict[str, Dict] = {r.get("id", ""): r for r in draft}

        newly_added:  List[str] = []
        modified_ids: List[str] = []
        deleted_ids:  List[str] = []
        skipped:      List[str] = []
        conflicts:    List[str] = []
        warnings:     List[str] = []

        # ══════════════════════════════════════════════════════════════════
        # Phase 1: DELETIONS
        # ══════════════════════════════════════════════════════════════════
        for deletion in deletions:
            did = deletion.get("id", "").strip()
            thought = deletion.get("thought", "").strip() or react_thought
            if not did:
                warnings.append("Deletion skipped: missing 'id'.")
                continue
            if did not in draft_by_id:
                warnings.append(f"Deletion skipped: {did} not found in draft.")
                continue

            draft = [r for r in draft if r.get("id") != did]
            draft_by_id.pop(did, None)
            deleted_ids.append(did)
            logger.info(
                "[Interviewer] Deleted %s. Thought: %s", did, thought[:100]
            )

        # ══════════════════════════════════════════════════════════════════
        # Phase 2: MODIFICATIONS
        # ══════════════════════════════════════════════════════════════════
        allowed_fields = {"description", "priority", "status", "type"}
        for mod in modifications:
            mid = mod.get("id", "").strip()
            field = mod.get("field", "").strip()
            new_value = mod.get("new_value", "").strip() if isinstance(mod.get("new_value"), str) else mod.get("new_value")
            thought = mod.get("thought", "").strip() or react_thought

            if not mid or not field:
                warnings.append(f"Modification skipped: missing 'id' or 'field'. Got: {mod}")
                continue
            if field not in allowed_fields:
                warnings.append(
                    f"Modification skipped for {mid}: field '{field}' not allowed. "
                    f"Allowed: {sorted(allowed_fields)}."
                )
                continue
            if mid not in draft_by_id:
                warnings.append(f"Modification skipped: {mid} not found in draft.")
                continue

            existing_req = draft_by_id[mid]
            old_value = existing_req.get(field)
            existing_req[field] = new_value

            # Record the modification in history with the agent's thought
            existing_req.setdefault("history", []).append({
                "action":    "modified",
                "turn":      turn_index,
                "reason":    thought or f"Modified '{field}' per review feedback.",
                "old_value": str(old_value) if old_value is not None else None,
            })

            # Also update rationale to reflect the change
            if thought:
                existing_req["rationale"] = (
                    existing_req.get("rationale", "") +
                    f" [Modified: {thought}]"
                )

            modified_ids.append(mid)
            logger.info(
                "[Interviewer] Modified %s.%s: '%s' → '%s'. Thought: %s",
                mid, field, old_value, new_value, thought[:100],
            )

        # ══════════════════════════════════════════════════════════════════
        # Phase 3: EXTRACTED (new requirements — existing logic)
        # ══════════════════════════════════════════════════════════════════

        # ── ID counters ────────────────────────────────────────────────────
        fr_count  = sum(1 for r in draft if r.get("id", "").startswith("FR-"))
        nfr_count = sum(1 for r in draft if r.get("id", "").startswith("NFR-"))
        con_count = sum(1 for r in draft if r.get("id", "").startswith("CON-"))

        for req in extracted:
            rtype     = req.get("type", "functional")
            rationale = req.get("rationale", "").strip()
            thought   = req.get("thought", "").strip() or react_thought

            # ── Warn if rationale is missing (but don't block) ────────────
            if not rationale:
                warnings.append(
                    f"Requirement '{req.get('description', '')[:60]}' is missing "
                    "'rationale'. Please supply reasoning in the next call."
                )
                rationale = "(rationale not provided)"

            # ── Assign ID ─────────────────────────────────────────────────
            if not req.get("id"):
                if rtype == "non_functional":
                    nfr_count += 1
                    req["id"] = f"NFR-{nfr_count:03d}"
                elif rtype == "constraint":
                    con_count += 1
                    req["id"] = f"CON-{con_count:03d}"
                else:
                    fr_count += 1
                    req["id"] = f"FR-{fr_count:03d}"

            rid  = req["id"]
            desc = req.get("description", "").strip()

            # ── Conflict / duplicate check ─────────────────────────────────
            duplicate_of, conflict_with = self._check_conflicts(req, draft)

            if conflict_with:
                if conflict_with in draft_by_id:
                    existing_req = draft_by_id[conflict_with]
                    existing_req.setdefault("history", []).append({
                        "action":    "conflict_flagged",
                        "turn":      turn_index,
                        "reason":    (
                            f"New requirement {rid} contradicts this one. "
                            f"Rationale: {rationale}. Thought: {thought}"
                        ),
                        "old_value": None,
                    })
                conflicts.append(
                    f"⚠ CONFLICT: {rid} contradicts {conflict_with}. "
                    "Ask the stakeholder to resolve this."
                )
                req["status"] = "ambiguous"

            elif duplicate_of:
                skipped.append(rid)
                warnings.append(
                    f"{rid} is a probable duplicate of {duplicate_of} — skipped. "
                    "Consider merging or clarifying scope instead of re-asking."
                )
                continue   # do NOT append to draft

            # ── Vague language check ───────────────────────────────────────
            vague_found = _VAGUE_WORDS & set(desc.lower().split())
            if vague_found:
                warnings.append(
                    f"{rid} uses vague language "
                    f"({', '.join(sorted(vague_found))}). "
                    "Add measurable criteria in a follow-up question."
                )

            # ── Attach rationale & initialise history ─────────────────────
            req["rationale"] = rationale
            # Use the LLM's thought as the history reason if available;
            # fall back to the rationale itself rather than a generic string.
            history_reason = thought or rationale or f"Identified from stakeholder turn {req.get('source_turn', turn_index)}."
            req.setdefault("history", []).append({
                "action":    "created",
                "turn":      turn_index,
                "reason":    history_reason,
                "old_value": None,
            })

            # ── Remove transient key before persisting ─────────────────────
            req.pop("thought", None)

            # ── Append to draft ────────────────────────────────────────────
            draft.append(req)
            draft_by_id[rid] = req
            newly_added.append(rid)

        # ── Completeness ──────────────────────────────────────────────────
        completeness = self._assess_completeness(draft)
        enough       = completeness >= self._completeness_threshold

        # ── Gap analysis ──────────────────────────────────────────────────
        fr_in_draft  = sum(1 for r in draft if r.get("type") == "functional")
        nfr_in_draft = sum(1 for r in draft if r.get("type") == "non_functional")
        con_in_draft = sum(1 for r in draft if r.get("type") == "constraint")

        gap_hints: List[str] = []
        if nfr_in_draft == 0:
            gap_hints.append(
                "NO non-functional requirements captured yet — this alone prevents "
                "reaching the completeness threshold (NFR weight = 0.30). "
                "Ask about: response time / concurrent users (performance), "
                "authentication / data privacy (security), uptime / recovery "
                "(reliability), or cross-device support (usability)."
            )
        if con_in_draft == 0:
            gap_hints.append(
                "NO constraints captured yet. "
                "Ask about: technology stack, budget, regulatory requirements, "
                "delivery deadlines, or integration with existing systems."
            )

        # ── Build observation ──────────────────────────────────────────────
        parts = [
            f"Requirements draft: {len(draft)} total "
            f"(+{len(newly_added)} added: {newly_added or 'none'}"
            + (f", {len(modified_ids)} modified: {modified_ids}" if modified_ids else "")
            + (f", {len(deleted_ids)} deleted: {deleted_ids}" if deleted_ids else "")
            + (f", {len(skipped)} duplicates skipped: {skipped}" if skipped else "")
            + f"). Breakdown: {fr_in_draft} FR / {nfr_in_draft} NFR / {con_in_draft} CON.",

            f"Completeness: {completeness:.2f} / {self._completeness_threshold:.2f} "
            f"→ {'✓ SUFFICIENT — consider calling write_interview_record' if enough else 'continue gathering'}.",
        ]

        if conflicts:
            parts.append("CONFLICTS TO RESOLVE:\n" + "\n".join(f"  {c}" for c in conflicts))
        if warnings:
            parts.append("Warnings:\n" + "\n".join(f"  {w}" for w in warnings))
        if gap_hints:
            parts.append("GAPS TO ADDRESS (required to reach threshold):\n"
                         + "\n".join(f"  • {g}" for g in gap_hints))

        if not conflicts and not enough:
            parts.append(
                "Next: use 'send_message' to ask a question targeting the gaps "
                "listed above, or 'search_knowledge' for technique guidance."
            )
        elif not conflicts and enough:
            parts.append(
                "Next: call 'write_interview_record' with gaps and notes, OR "
                "ask ONE final clarifying question if critical ambiguity remains."
            )

        logger.info(
            "[Interviewer] update_requirements: +%d new, %d modified, %d deleted, "
            "%d skipped, %d total, completeness=%.2f, conflicts=%d",
            len(newly_added), len(modified_ids), len(deleted_ids),
            len(skipped), len(draft), completeness, len(conflicts),
        )

        return ToolResult(
            observation="\n".join(parts),
            state_updates={"requirements_draft": draft},
        )

    # ------------------------------------------------------------------
    def _tool_send_message(
        self,
        message: str,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Post ONE question to the stakeholder and yield the turn."""
        if not message:
            logger.warning(
                "send_message called with empty message; defaulting."
            )
            message = "Could you tell me more about that?"

        conversation = list(state.get("conversation") or [])
        conversation.append({
            "role":      "interviewer",
            "content":   message,
            "timestamp": datetime.now().isoformat(),
        })
        logger.info("[Interviewer → Stakeholder] %s", message)

        return ToolResult(
            observation=f"Question sent: {message}",
            state_updates={"conversation": conversation},
            should_return=True,   # yield to EndUser
        )

    # ------------------------------------------------------------------
    def _tool_write_interview_record(
        self,
        gaps:  List[str] = None,
        notes: str       = "",
        state: Dict      = None,
        **_,
    ) -> ToolResult:
        """
        Finalise the interview record using the accumulated requirements_draft.

        The LLM supplies only ``gaps`` and ``notes``; requirements (including
        their rationale and history) are read directly from state so no
        re-extraction is needed.
        """
        conversation: List[Dict] = state.get("conversation") or []
        requirements: List[Dict] = list(state.get("requirements_draft") or [])
        gaps = gaps or []

        record: Dict[str, Any] = {
            "session_id":              state.get("session_id", str(uuid.uuid4())),
            "project_description":     state.get("project_description", ""),
            "conversation":            conversation,
            "total_turns":             state.get("turn_count", len(conversation) // 2),
            "requirements_identified": requirements,   # includes rationale + history
            "gaps_identified":         gaps,
            "notes":                   notes,
            "completeness_score":      self._assess_completeness(requirements),
            "created_at":              datetime.now().isoformat(),
            "status":                  "pending_review",   # updated to "approved" by review_turn
        }

        artifacts = dict(state.get("artifacts") or {})
        artifacts["interview_record"] = record

        logger.info(
            "[Interviewer] Interview finalised — %d requirements, "
            "%d gaps, completeness=%.2f.",
            len(requirements), len(gaps),
            record["completeness_score"],
        )

        return ToolResult(
            observation=(
                f"Interview record written. "
                f"{len(requirements)} requirements "
                f"({sum(1 for r in requirements if r.get('type') == 'functional')} FR, "
                f"{sum(1 for r in requirements if r.get('type') == 'non_functional')} NFR, "
                f"{sum(1 for r in requirements if r.get('type') == 'constraint')} CON), "
                f"{len(gaps)} gaps."
            ),
            state_updates={
                "artifacts":          artifacts,
                "interview_complete": True,
            },
            should_return=True,
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _assess_completeness(requirements: List[Dict]) -> float:
        """
        Heuristic completeness score in [0.0, 1.0].

        Mirrors the old BaseInterviewerAgent logic (threshold = 0.8).
          0.40 — at least one functional requirement
          0.30 — at least one non-functional requirement
          0.30 — quantity coverage (capped at count / 30)
        """
        if not requirements:
            return 0.0
        has_functional     = any(r.get("type") == "functional"     for r in requirements)
        has_non_functional = any(r.get("type") == "non_functional"  for r in requirements)
        score = (
            _W_FUNCTIONAL     * has_functional
            + _W_NON_FUNCTIONAL * has_non_functional
            + min(_W_QUANTITY, len(requirements) / 30)
        )
        return round(score, 3)

    @staticmethod
    def _word_overlap(a: str, b: str) -> float:
        """Jaccard similarity of non-trivial word sets."""
        stop = {"the", "a", "an", "is", "are", "be", "to", "of", "and",
                "or", "that", "it", "for", "in", "on", "with", "as"}
        wa = set(a.lower().split()) - stop
        wb = set(b.lower().split()) - stop
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

    def _check_conflicts(
        self,
        new_req: Dict,
        draft: List[Dict],
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Return (duplicate_of_id, conflict_with_id) for the first match found.

        Heuristics (fast; LLM does deep analysis via observation text):
          • Jaccard overlap > 0.55 → probable duplicate
          • Same high-overlap pair where one has strong negation → conflict
        """
        new_desc = new_req.get("description", "")
        duplicate_of  = None
        conflict_with = None

        for existing in draft:
            ex_desc  = existing.get("description", "")
            ex_id    = existing.get("id", "?")
            overlap  = InterviewerAgent._word_overlap(new_desc, ex_desc)

            if overlap > 0.55:
                new_tokens = set(new_desc.lower().split())
                ex_tokens  = set(ex_desc.lower().split())
                new_has_neg = bool({"not", "never", "no", "without"} & new_tokens)
                ex_has_neg  = bool({"not", "never", "no", "without"} & ex_tokens)

                if new_has_neg != ex_has_neg:
                    conflict_with = conflict_with or ex_id
                else:
                    duplicate_of = duplicate_of or ex_id

            if duplicate_of and conflict_with:
                break

        return duplicate_of, conflict_with

    # ── LangGraph node entry point ────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Called by LangGraph on every interviewer turn.

        Turn structure
        ──────────────
        [First turn]  → no stakeholder reply yet → send opening question.
        [Subsequent]  → MUST call update_requirements first, then decide:
                         conflict   → Socratic clarifier via send_message
                         incomplete → next 5W1H question via send_message
                         complete   → write_interview_record

        Review-restart handling
        ───────────────────────
        If ``review_feedback`` is present in state the interview record was
        previously rejected.  The feedback is injected prominently so the LLM
        knows exactly what to improve in this run.
        """
        conversation  = state.get("conversation") or []
        turn_count    = state.get("turn_count", 0)
        max_turns     = state.get("max_turns", self._max_turns)
        draft         = state.get("requirements_draft") or []
        completeness  = self._assess_completeness(draft)
        enough        = completeness >= self._completeness_threshold
        review_feedback = (state.get("review_feedback") or "").strip()

        # ── Build transcript ───────────────────────────────────────────────
        transcript = "\n".join(
            f"[{i}] {'Interviewer' if t['role'] == 'interviewer' else 'Stakeholder'}: "
            f"{t['content']}"
            for i, t in enumerate(conversation)
        ) or "(interview has not started yet)"

        # ── Last stakeholder utterance ─────────────────────────────────────
        last_stakeholder = next(
            (t["content"] for t in reversed(conversation)
             if t["role"] == "enduser"),
            None,
        )
        last_turn_index = len(conversation) - 1

        # ── Draft summary (include rationale excerpt) ──────────────────────
        draft_summary = (
            "\n".join(
                f"  [{r.get('id', '?')}] ({r.get('type', '?')}, "
                f"{r.get('status', '?')}) {r.get('description', '')[:80]}\n"
                f"    ↳ rationale: {r.get('rationale', '(none)')[:100]}"
                for r in draft[-10:]
            ) or "  (no requirements captured yet)"
        )

        # ── Stopping hint ──────────────────────────────────────────────────
        approaching_limit = turn_count >= max(4, max_turns - 3)
        if approaching_limit:
            stop_hint = (
                f"⚠ APPROACHING LIMIT: {turn_count}/{max_turns} turns used. "
                "If you have reasonable coverage, call 'write_interview_record' now."
            )
        elif enough:
            stop_hint = (
                f"✓ Completeness ({completeness:.2f}) has reached the threshold "
                f"({self._completeness_threshold:.2f}). "
                "You MAY finalise now or ask ONE more clarifying question."
            )
        else:
            remaining = max_turns - turn_count
            stop_hint = (
                f"Completeness: {completeness:.2f} / {self._completeness_threshold:.2f}. "
                f"{remaining} turns remaining."
            )

        # ── Cross-turn loop detection ──────────────────────────────────────
        recent_interviewer_questions = [
            t["content"]
            for t in conversation
            if t["role"] == "interviewer"
        ][-5:]

        if recent_interviewer_questions:
            repeat_guard = (
                "QUESTIONS ALREADY SENT (do NOT ask these again — "
                "the stakeholder has already answered them):\n"
                + "\n".join(f"  • {q[:120]}" for q in recent_interviewer_questions)
                + "\nYou MUST ask about a DIFFERENT topic or aspect."
            )
        else:
            repeat_guard = ""

        # ── Review-restart feedback block ──────────────────────────────────
        if review_feedback:
            review_block = (
                "━━━━━━━━━━━━━━  REVIEW FEEDBACK (previous record was rejected)  ━━━━━━━━━━━━━━\n"
                f"{review_feedback}\n\n"
                "You MUST address ALL points above.\n"
                "USE 'update_requirements' with the appropriate operations:\n"
                "  • To EDIT an existing requirement → use 'modifications' with the req ID,\n"
                "    the field to change, the new value, and your thought explaining why.\n"
                "  • To REMOVE a requirement         → use 'deletions' with the req ID\n"
                "    and your thought explaining why.\n"
                "  • To ADD a missing requirement     → use 'extracted' as before.\n"
                "Apply ALL feedback changes in a SINGLE 'update_requirements' call,\n"
                "then call 'write_interview_record' to produce the corrected record.\n"
            )
        else:
            review_block = ""

        # ── Decision context ───────────────────────────────────────────────
        if review_feedback:
            # Feedback-driven mode: apply reviewer's changes directly on the
            # existing requirements_draft without needing a new stakeholder turn.
            extraction_guidance = (
                "STEP 1 — MANDATORY: call 'update_requirements' RIGHT NOW.\n"
                "  You have review feedback to address. Apply ALL requested changes:\n"
                "  • Use 'modifications' to edit existing requirements (change priority,\n"
                "    description, status, etc.) — provide your 'thought' for each.\n"
                "  • Use 'deletions' to remove requirements the reviewer flagged — \n"
                "    provide your 'thought' for each.\n"
                "  • Use 'extracted' to add any new requirements the reviewer asked for —\n"
                "    provide 'rationale' and optionally 'thought' for each.\n"
                "  Do ALL changes in a SINGLE 'update_requirements' call.\n\n"
                "STEP 2 — After update_requirements returns:\n"
                "  • If completeness is SUFFICIENT → call 'write_interview_record'\n"
                "  • If more info is needed        → 'send_message' to ask the stakeholder\n"
            )
        elif last_stakeholder:
            extraction_guidance = (
                "STEP 1 — MANDATORY: call 'update_requirements' RIGHT NOW.\n"
                f"  The stakeholder just replied at conversation index {last_turn_index}:\n"
                f"  \"{last_stakeholder[:200]}\"\n"
                "  Extract EVERY requirement you can find in that reply.\n"
                "  For EACH requirement you MUST supply a 'rationale' field that:\n"
                "    • Cites the stakeholder's exact words or intent.\n"
                "    • Explains the business goal or constraint the requirement addresses.\n"
                "  Optionally supply a 'thought' field with your chain-of-thought reasoning.\n"
                "  Include functional AND non-functional requirements "
                "(performance, security, reliability, usability).\n"
                "  Do not skip this step — calling 'send_message' without "
                "first calling 'update_requirements' wastes a turn.\n\n"
                "STEP 2 — After update_requirements returns, read the observation:\n"
                "  • CONFLICT detected    → 'send_message' with a Socratic probe\n"
                "                           to resolve the contradiction.\n"
                "  • SUFFICIENT coverage  → 'write_interview_record'\n"
                "  • GAPS listed          → 'send_message' targeting a listed gap\n"
                "  • More info needed     → 'send_message' with ONE 5W1H question\n"
                "                           on a topic NOT in the repeat-guard list.\n"
            )
        else:
            extraction_guidance = (
                "The interview has not started yet.\n"
                "Skip 'update_requirements' (no stakeholder reply yet).\n"
                "Call 'send_message' with an open-ended OPENING question that:\n"
                "  • Introduces yourself briefly.\n"
                "  • Asks the stakeholder to describe the core problem or goal.\n"
            )

        task = (
            f"{self.PROFILE}\n\n"
            "━━━━━━━━━━━━━━  PROJECT  ━━━━━━━━━━━━━━\n"
            f"{state.get('project_description', 'not provided')}\n\n"
            + (review_block if review_block else "")
            + "━━━━━━━━━━━━━━  CONVERSATION SO FAR  ━━━━━━━━━━━━━━\n"
            f"{transcript}\n\n"
            "━━━━━━━━━━━━━━  REQUIREMENTS DRAFT (latest 10)  ━━━━━━━━━━━━━━\n"
            f"{draft_summary}\n\n"
            "━━━━━━━━━━━━━━  STATUS  ━━━━━━━━━━━━━━\n"
            f"{stop_hint}\n\n"
            + (
                "━━━━━━━━━━━━━━  REPEAT GUARD  ━━━━━━━━━━━━━━\n"
                f"{repeat_guard}\n\n"
                if repeat_guard else ""
            )
            + "━━━━━━━━━━━━━━  YOUR NEXT ACTION  ━━━━━━━━━━━━━━\n"
              f"{extraction_guidance}\n"
              "RULES:\n"
              "• ONE tool per ReAct step.\n"
              "• 'send_message': ONE question only. No compound questions.\n"
              "• 'update_requirements':\n"
              "    - 'extracted': EVERY item MUST have a 'rationale' field.\n"
              "      Include 'thought' for richer history tracking.\n"
              "    - 'modifications': provide 'id', 'field', 'new_value', 'thought'.\n"
              "    - 'deletions': provide 'id' and 'thought'.\n"
              "    - You can combine all three in a single call.\n"
              "• 'write_interview_record': do NOT pass a requirements list;\n"
              "  the draft is read automatically. Pass only gaps and notes.\n"
        )

        return self.react(state, task)