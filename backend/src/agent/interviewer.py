"""
interviewer.py – InterviewerAgent  (LangGraph edition)

Role
────
Conduct a multi-turn requirements interview with a simulated stakeholder
(EndUserAgent) while maintaining a LIVE, incrementally-updated requirements
draft.  Every turn the agent:

  1. Reads the latest stakeholder utterance.
  2. Calls ``update_requirements`` → extracts new requirements from that
     utterance, merges them into the running ``requirements_draft`` in state,
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
    appends to it and checks consistency.  ``write_interview_record`` reads
    from it directly — the LLM never needs to re-extract from the full
    transcript at the end.
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
3. After EACH stakeholder reply, extract requirements via 'update_requirements'.
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
                "After the stakeholder replies, extract requirements from their "
                "latest utterance and update the running draft.\n"
                "This tool DOES NOT end the turn — call it first, then decide "
                "whether to 'send_message' or 'write_interview_record'.\n"
                "Input: {\n"
                "  \"extracted\": [\n"
                "    {\n"
                "      \"type\":        \"functional\" | \"non_functional\" | \"constraint\",\n"
                "      \"description\": \"<precise, testable statement>\",\n"
                "      \"priority\":    \"high\" | \"medium\" | \"low\",\n"
                "      \"source_turn\": <int — 0-based turn index in conversation>,\n"
                "      \"status\":      \"confirmed\" | \"inferred\" | \"ambiguous\"\n"
                "    }, ...\n"
                "  ]\n"
                "}\n"
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
            state: Dict = None,
            **_,
    ) -> ToolResult:
        """Merge newly extracted requirements into the running draft.

        Steps:
          1. Return early with a clear message when extracted is empty so the
             LLM receives an actionable signal rather than a misleading
             "0 new, continue gathering" observation.
          2. Auto-assign IDs (FR-xxx / NFR-xxx / CON-xxx).
          3. For each new requirement, check against the existing draft for:
               a. Semantic overlap  — Jaccard similarity > 0.55 → skip (not add)
               b. Logical conflict  — high overlap where one side has negation
               c. Vague language    — flag for measurable follow-up
          4. Append only non-duplicate entries to the draft.
          5. Recompute completeness score.
          6. Build a gap analysis (missing NFR / constraint categories) so the
             LLM knows which requirement types still need to be elicited.
          7. Return a rich observation the LLM uses to pick its next action.

        Does NOT set should_return=True — the ReAct loop continues.
        """
        extracted = extracted or []

        # Guard: if the LLM called this tool with an empty list, return an
        # actionable message immediately instead of writing a useless observation.
        if not extracted:
            return ToolResult(
                observation=(
                    "No requirements were extracted (empty list received). "
                    "Make sure the 'extracted' field contains at least one item "
                    "with all required keys (type, description, priority, "
                    "source_turn, status). "
                    "Then call 'send_message' to ask the next question."
                ),
                state_updates={},
            )

        draft: List[Dict] = list(state.get("requirements_draft") or [])

        # ── ID counters ────────────────────────────────────────────────────
        fr_count = sum(1 for r in draft if r.get("id", "").startswith("FR-"))
        nfr_count = sum(1 for r in draft if r.get("id", "").startswith("NFR-"))
        con_count = sum(1 for r in draft if r.get("id", "").startswith("CON-"))

        newly_added: List[str] = []
        skipped: List[str] = []  # duplicates that were blocked
        conflicts: List[str] = []
        warnings: List[str] = []

        for req in extracted:
            rtype = req.get("type", "functional")

            # ── Assign ID ────────────────────────────────────────────────
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

            rid = req["id"]
            desc = req.get("description", "").strip()

            # ── Conflict / duplicate check ────────────────────────────────
            duplicate_of, conflict_with = self._check_conflicts(req, draft)

            if conflict_with:
                # Conflicts are flagged but still added so the LLM can ask
                # the stakeholder to resolve them explicitly.
                conflicts.append(
                    f"⚠ CONFLICT: {rid} contradicts {conflict_with}. "
                    "Ask the stakeholder to resolve this."
                )
                req["status"] = "ambiguous"

            elif duplicate_of:
                # Duplicates are silently skipped — appending them inflates
                # the count without adding coverage, which previously caused
                # the LLM to keep re-asking about the same topic (the count
                # kept rising but completeness never improved because no new
                # requirement *types* were added).
                skipped.append(rid)
                warnings.append(
                    f"{rid} is a probable duplicate of {duplicate_of} — skipped. "
                    "Consider merging or clarifying scope instead of re-asking."
                )
                continue  # do NOT append to draft

            # ── Vague language check ──────────────────────────────────────
            vague_found = _VAGUE_WORDS & set(desc.lower().split())
            if vague_found:
                warnings.append(
                    f"{rid} uses vague language "
                    f"({', '.join(sorted(vague_found))}). "
                    "Add measurable criteria in a follow-up question."
                )

            # ── Append to draft ───────────────────────────────────────────
            draft.append(req)
            newly_added.append(rid)

        # ── Completeness ──────────────────────────────────────────────────
        completeness = self._assess_completeness(draft)
        enough = completeness >= self._completeness_threshold

        # ── Gap analysis ─────────────────────────────────────────────────
        # Count each requirement type currently in the draft so the LLM
        # knows exactly which categories are missing, rather than receiving
        # only a numeric score and having to infer the gap itself.
        fr_in_draft = sum(1 for r in draft if r.get("type") == "functional")
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

        # ── Build observation ─────────────────────────────────────────────
        parts = [
            f"Requirements draft: {len(draft)} total "
            f"(+{len(newly_added)} added: {newly_added or 'none'}"
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
            "[Interviewer] update_requirements: +%d new, %d skipped, %d total, "
            "completeness=%.2f, conflicts=%d",
            len(newly_added), len(skipped), len(draft), completeness, len(conflicts),
        )

        return ToolResult(
            observation="\n".join(parts),
            state_updates={"requirements_draft": draft},
            # should_return is intentionally False — the ReAct loop continues
            # so the agent can pick its next action based on this observation.
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

        The LLM supplies only ``gaps`` and ``notes``; requirements are read
        directly from state so no re-extraction is needed.
        """
        conversation: List[Dict] = state.get("conversation") or []
        requirements: List[Dict] = list(state.get("requirements_draft") or [])
        gaps = gaps or []

        record: Dict[str, Any] = {
            "session_id":              state.get("session_id", str(uuid.uuid4())),
            "project_description":     state.get("project_description", ""),
            "conversation":            conversation,
            "total_turns":             state.get("turn_count", len(conversation) // 2),
            "requirements_identified": requirements,
            "gaps_identified":         gaps,
            "notes":                   notes,
            "completeness_score":      self._assess_completeness(requirements),
            "created_at":              datetime.now().isoformat(),
            "status":                  "completed",
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
        duplicate_of = None
        conflict_with = None

        for existing in draft:
            ex_desc  = existing.get("description", "")
            ex_id    = existing.get("id", "?")
            overlap  = InterviewerAgent._word_overlap(new_desc, ex_desc)

            if overlap > 0.55:
                # Check for negation → likely a conflict
                new_tokens = set(new_desc.lower().split())
                ex_tokens  = set(ex_desc.lower().split())
                new_has_neg = bool({"not", "never", "no", "without"} & new_tokens)
                ex_has_neg  = bool({"not", "never", "no", "without"} & ex_tokens)

                if new_has_neg != ex_has_neg:
                    conflict_with = conflict_with or ex_id
                else:
                    duplicate_of = duplicate_of or ex_id

            if duplicate_of and conflict_with:
                break   # found both; no need to scan further

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

        Cross-turn loop prevention
        ──────────────────────────
        The react() loop guard resets each process() call, so it cannot catch
        a question that repeats across multiple graph cycles. This method
        builds an explicit "recent questions sent" block and injects it as a
        hard constraint so the LLM never re-asks a question already in the
        conversation history.

        Forced update_requirements
        ──────────────────────────
        If a stakeholder reply is present but update_requirements has not been
        called yet this turn (detected by comparing draft size before/after),
        the task prompt uses imperative language and places the extraction step
        before any other instruction to prevent the LLM from skipping it.
        """
        conversation = state.get("conversation") or []
        turn_count = state.get("turn_count", 0)
        max_turns = state.get("max_turns", self._max_turns)
        draft = state.get("requirements_draft") or []
        completeness = self._assess_completeness(draft)
        enough = completeness >= self._completeness_threshold

        # ── Build transcript ──────────────────────────────────────────────
        transcript = "\n".join(
            f"[{i}] {'Interviewer' if t['role'] == 'interviewer' else 'Stakeholder'}: "
            f"{t['content']}"
            for i, t in enumerate(conversation)
        ) or "(interview has not started yet)"

        # ── Last stakeholder utterance ────────────────────────────────────
        last_stakeholder = next(
            (t["content"] for t in reversed(conversation)
             if t["role"] == "enduser"),
            None,
        )
        last_turn_index = len(conversation) - 1

        # ── Draft summary ─────────────────────────────────────────────────
        draft_summary = (
                "\n".join(
                    f"  [{r.get('id', '?')}] ({r.get('type', '?')}, "
                    f"{r.get('status', '?')}) {r.get('description', '')[:80]}"
                    for r in draft[-10:]
                ) or "  (no requirements captured yet)"
        )

        # ── Stopping hint ─────────────────────────────────────────────────
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

        # ── Cross-turn loop detection ─────────────────────────────────────
        # Collect the last 5 questions the interviewer has already sent so
        # the LLM can be explicitly told not to repeat any of them.
        # This is necessary because react()'s action_repeat_counts resets
        # on every process() call and cannot track cross-turn repetition.
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

        # ── Decision context ──────────────────────────────────────────────
        if last_stakeholder:
            extraction_guidance = (
                "STEP 1 — MANDATORY: call 'update_requirements' RIGHT NOW.\n"
                f"  The stakeholder just replied at conversation index {last_turn_index}:\n"
                f"  \"{last_stakeholder[:200]}\"\n"
                "  Extract EVERY requirement you can find in that reply.\n"
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
                "━━━━━━━━━━━━━━  CONVERSATION SO FAR  ━━━━━━━━━━━━━━\n"
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
                  "• 'update_requirements': include source_turn index for traceability.\n"
                  "• 'write_interview_record': do NOT pass a requirements list;\n"
                  "  the draft is read automatically. Pass only gaps and notes.\n"
        )

        return self.react(state, task)