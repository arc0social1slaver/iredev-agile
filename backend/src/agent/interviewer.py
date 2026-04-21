"""
interviewer.py – InterviewerAgent v2

Three-tier stopping
───────────────────
Tier 1 — Zone saturation (hard gate):
  A zone is locally saturated once consecutive_dry_calls ≥ SATURATION_CALLS.
  All required zones must reach local saturation before Tier-1 passes.

Tier 2 — Marginal information gain per zone (quantitative signal):
  ig_score = max(0.0, 1.0 − consecutive_dry_calls / SATURATION_CALLS).
  When all required zones reach ig_score == 0.0, Tier-2 signals stopping.
  Both Tier-1 and Tier-2 must agree before stopping is considered.

Tier 3 — Metacognitive coherence check (qualitative, lives in [STRATEGY]):
  "Could a software engineer begin system design from the current list?"
  If NO — state the gap and keep probing regardless of Tiers 1 & 2.
  If YES — call write_interview_record.

Memory layout
─────────────
self.memory   — SHORT_TERM_SEMANTIC MemoryModule.
  • Buffer (SHORT_TERM part): ConversationBuffer fed to ThinkModule each turn.
  • Semantic store (SEMANTIC part): replaces the old _BeliefState helper class.
    Use self.memory.settle_fact / recall_zone / count_zone for belief-state ops.

Tool sequence enforcement (in code, not just prompt)
────────────────────────────────────────────────────
_tool_update_requirements sets '_update_req_done_this_turn' = True in state_updates.
_tool_send_message checks this flag before proceeding; if absent when a stakeholder
reply exists it returns a block message so the LLM must call update_requirements first.
Flag is cleared to False inside _tool_send_message on success (reset for next turn).
"""

from __future__ import annotations

import copy
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)

# ── Vague-language detector ───────────────────────────────────────────────────
_VAGUE_WORDS: Set[str] = {
    "quickly", "fast", "easy", "good", "nice", "some", "many",
    "appropriate", "sufficient", "reasonable",
}


# ── Zone factory ──────────────────────────────────────────────────────────────

def _zone(description: str, hint: str, min_reqs: int, required: bool = True) -> Dict[str, Any]:
    """Create a fresh zone entry for a coverage map."""
    return {
        "description":         description,
        "semantic_hint":       hint,
        "min_requirements":    min_reqs,
        "covered":             False,
        "auto_covered":        not required,
        "requirements_mapped": [],
        "last_probed_turn":    None,
    }


def _default_coverage_map() -> Dict[str, Any]:
    """ISO 29148-aligned five-zone skeleton; used when propose_zones is not called."""
    return {
        "zone_stakeholders": _zone(
            "Stakeholders, user roles, and actors",
            "Who uses the system? Who is affected by it? What are their primary goals?",
            min_reqs=1,
        ),
        "zone_functional": _zone(
            "Core functional requirements — what the system SHALL do",
            "Main workflows, business rules, use cases, feature capabilities",
            min_reqs=3,
        ),
        "zone_quality": _zone(
            "Non-functional requirements: performance, security, reliability, usability",
            "Response times, uptime SLA, data protection, accessibility standards",
            min_reqs=2,
        ),
        "zone_constraints": _zone(
            "Technical, legal, budget, and timeline constraints",
            "Technology mandates, regulatory compliance, budget limits, hard deadlines",
            min_reqs=1,
        ),
        "zone_interfaces": _zone(
            "External interfaces: UI paradigm, APIs, integrations, data formats",
            "What does the UI look like? Which external systems must connect?",
            min_reqs=1,
            required=False,    # optional — promote to required if stakeholder mentions it
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# InterviewerAgent
# ─────────────────────────────────────────────────────────────────────────────

class InterviewerAgent(BaseAgent):
    """Conducts multi-turn requirements interviews with three-tier stopping.

    Belief-state memory is provided by self.memory (SHORT_TERM_SEMANTIC):
      self.memory.settle_fact(zone_id, req_id, content) — persist confirmed fact
      self.memory.recall_zone(zone_id, query, limit)    — retrieve facts
      self.memory.count_zone(zone_id)                   — count facts

    Invariants
    ──────────
    1. requirements_draft is the single source of truth for the session.
    2. Every requirement's rationale embeds the [STRATEGY] block for full
       traceability through to the HITL audit trail.
    3. All HITL-driven changes carry "hitl_*" action tags and the reviewer text.
    4. interview_complete is set ONLY by write_interview_record.
    5. write_interview_record has no hard coverage gate; the three-tier judgment
       (expressed in [STRATEGY]) governs entirely.
    6. update_requirements MUST be called before send_message when a stakeholder
       reply exists. This is enforced in code via '_update_req_done_this_turn'.
    """

    # ── System prompt ─────────────────────────────────────────────────────────
    _STOPPING_ADDENDUM = """\
    ━━ TWO-TIER STOPPING & STRICT COMPLETENESS SCORING (MANDATORY) ━━

    TIER 1 — Strict Completeness Score (The 6 Criteria):
      You MUST diversify and gather a HIGH volume of requirements across ALL categories.
      1. Functional: type="functional" (Target: 6+)
      2. Non-Functional: type="non_functional" (Target: 4+)
      3. Constraints: type="constraint" — MUST use keywords: must, cannot, limited, restricted, compliance (Target: 3+)
      4. Business Objectives: MUST use keywords: business, objective, goal, value, benefit, roi (Target: 3+)
      5. Acceptance Criteria: MUST use keywords: accept, criteria, test, verify, validate (Target: 2+)
      6. Volume: Total requirements >= 15

      CRITICAL: Look at your current stats. If ANY category is 0 or below its target (especially Constraints and Non-Functional), STOP asking about features. Probe the missing categories immediately!

    TIER 2 — Metacognitive Coherence Check (Qualitative Gate):
      Answer: "Could a software engineer begin system design from the current list without further questions?"
      YES → call write_interview_record.
      NO  → state the specific gap and continue probing.
      CRITICAL: You CANNOT select YES if your current metrics show 0 for Constraints or Non-Functional requirements.
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        super().__init__(name="interviewer")
        agent_cfg = self._raw_config.get("iredev", {}).get("agents", {}).get("interviewer", {})
        custom    = agent_cfg.get("custom_params", {})
        self._completeness_threshold: float = custom.get("completeness_threshold")
        self._max_turns:              int   = custom.get("max_turns")
        logger.info("InterviewerAgent config | completeness_threshold=%.2f, max_turns=%d", self._completeness_threshold, self._max_turns)
        # Note: belief-state memory is provided by self.memory (SHORT_TERM_SEMANTIC).
        # No separate _BeliefState needed — use self.memory.settle_fact/recall_zone/count_zone.

    # ── Tool registration ─────────────────────────────────────────────────────

    def _register_tools(self) -> None:
        for name, doc, func in [
            ("propose_zones",           self._DOC_PROPOSE_ZONES,          self._tool_propose_zones),
            ("search_knowledge",        self._DOC_SEARCH_KNOWLEDGE,       self._tool_search_knowledge),
            ("update_requirements",     self._DOC_UPDATE_REQUIREMENTS,    self._tool_update_requirements),
            ("send_message",            self._DOC_SEND_MESSAGE,           self._tool_send_message),
            ("check_coverage",          self._DOC_CHECK_COVERAGE,         self._tool_check_coverage),
            ("map_requirement_to_zone", self._DOC_MAP_TO_ZONE,            self._tool_map_requirement_to_zone),
            ("detect_dependency",       self._DOC_DETECT_DEPENDENCY,      self._tool_detect_dependency),
            ("flag_conflict",           self._DOC_FLAG_CONFLICT,          self._tool_flag_conflict),
            ("evaluate_readiness",      self._DOC_EVALUATE_READINESS,     self._tool_evaluate_readiness), # <--- THÊM MỚI
            ("write_interview_record",  self._DOC_WRITE_RECORD,           self._tool_write_interview_record),
        ]:
            self.register_tool(Tool(name=name, description=doc, func=func))

    # ── Tool docstrings ───────────────────────────────────────────────────────

    _DOC_PROPOSE_ZONES = (
        "Define coverage zones for this session. Call ONCE on the first turn.\n"
        "Derive 4–8 zones from the project description using ISO 29148 SRS sections.\n"
        "Mark nice-to-have zones with required=false.\n\n"
        "Input: {\"zones\": [{\"id\": \"zone_<n>\", \"description\": \"<1 sentence>\",\n"
        "  \"semantic_hint\": \"<probing questions>\",\n"
        "  \"min_requirements\": <int>, \"required\": true|false}]}\n\n"
        "Does NOT end the turn — call send_message next."
    )
    _DOC_SEARCH_KNOWLEDGE = (
        "Search interviewing methodology, ISO standards, or domain knowledge.\n"
        "Input: {\"query\": \"<text>\"}"
    )
    _DOC_UPDATE_REQUIREMENTS = (
        "Extract, modify, or delete requirements. MUST be called after every stakeholder\n"
        "reply before send_message. Confirmed requirements are written to belief-state memory.\n"
        "Sets '_update_req_done_this_turn' flag — send_message will block without it.\n\n"
        "Input: {\n"
        "  \"extracted\": [{\"type\": \"functional|non_functional|constraint\",\n"
        "    \"description\": \"<precise, testable statement>\",\n"
        "    \"priority\": \"high|medium|low\", \"source_turn\": <int>,\n"
        "    \"status\": \"confirmed|inferred|ambiguous\",\n"
        "    \"rationale\": \"<WHY — cite exact stakeholder words>\"}],\n"
        "  \"modifications\": [{\"id\", \"field\", \"new_value\", \"reason\"}],\n"
        "  \"deletions\":     [{\"id\", \"reason\"}]\n"
        "}\n"
        "The [STRATEGY] block from your Thought is auto-appended to each new requirement's rationale."
    )
    _DOC_SEND_MESSAGE = (
        "Send ONE interview question to the stakeholder. ENDS the current agent turn.\n"
        "BLOCKED if update_requirements has not been called this turn (when a reply exists).\n"
        "BLOCKED if the message is identical to a recent question (repeat guard).\n"
        "Input: {\"message\": \"<single question>\", \"target_zone\": \"<zone_id>\"}"
    )
    _DOC_CHECK_COVERAGE = (
        "Inspect zone coverage, Tier-1 saturation flags, Tier-2 IG scores, and belief-state\n"
        "settled facts. Call before deciding whether to continue probing or finalise.\n"
        "Input: {}"
    )
    _DOC_MAP_TO_ZONE = (
        "Manually map a requirement to a zone (use when auto-mapping missed a connection).\n"
        "Input: {\"req_id\": \"FR-001\", \"zone_id\": \"zone_<n>\"}"
    )
    _DOC_DETECT_DEPENDENCY = (
        "Record a directed dependency between two requirements.\n"
        "Input: {\"from_req\": \"FR-002\", \"to_req\": \"CON-001\",\n"
        "  \"relation_type\": \"depends_on|enables|conflicts_with|refinement_of\",\n"
        "  \"rationale\": \"<why this relationship exists>\"}"
    )
    _DOC_FLAG_CONFLICT = (
        "Log a semantic conflict between two requirements for human review.\n"
        "Input: {\"req_a\": \"FR-005\", \"req_b\": \"CON-002\",\n"
        "  \"conflict_type\": \"scope_creep|implementation_clash|priority_inversion\",\n"
        "  \"description\": \"<what the conflict is>\"}"
    )
    _DOC_WRITE_RECORD = (
        "Finalise the interview: write interview_record and set interview_complete=True.\n"
        "Call ONLY when ALL THREE TIERS confirm completeness in your [STRATEGY] block.\n"
        "No hard coverage gate — your three-tier judgment governs entirely.\n"
        "Input: {\"gaps\": [\"<unclear area>\", ...], \"notes\": \"<2–3 sentence summary>\"}"
    )

    # ── Tool implementations ──────────────────────────────────────────────────

    def _tool_propose_zones(
        self,
        zones: List[Dict] = None,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        if state.get("coverage_map"):
            return ToolResult(
                observation=(
                    f"Coverage map already initialised: {list(state['coverage_map'].keys())}. "
                    "propose_zones is a no-op."
                )
            )
        if not zones:
            cmap = _default_coverage_map()
            return ToolResult(
                observation=f"No zones provided — using ISO 29148 default skeleton: {list(cmap.keys())}.",
                state_updates={"coverage_map": cmap},
            )

        cmap: Dict[str, Any] = {}
        warnings: List[str] = []
        for spec in zones:
            zid = re.sub(r"[^a-zA-Z0-9_]", "_", (spec.get("id") or "").strip()).lower()
            if not zid:
                warnings.append("Zone skipped: missing id.")
                continue
            if not zid.startswith("zone_"):
                zid = f"zone_{zid}"
            cmap[zid] = _zone(
                description = spec.get("description", zid),
                hint        = spec.get("semantic_hint", ""),
                min_reqs    = max(1, int(spec.get("min_requirements", 1))),
                required    = bool(spec.get("required", True)),
            )

        if not cmap:
            cmap = _default_coverage_map()
            warnings.append("All zones invalid — fell back to ISO 29148 skeleton.")

        req_n = sum(1 for z in cmap.values() if not z["auto_covered"])
        obs = (
            f"Coverage map: {len(cmap)} zones ({req_n} required, {len(cmap) - req_n} optional).\n"
            f"Zones: { {zid: zd['description'] for zid, zd in cmap.items()} }"
        )
        if warnings:
            obs += "\nWarnings: " + "; ".join(warnings)
        logger.info("[Interviewer] propose_zones: %d zones (%d required).", len(cmap), req_n)
        return ToolResult(observation=obs, state_updates={"coverage_map": cmap})

    # ------------------------------------------------------------------

    def _tool_search_knowledge(self, query: str, state: Dict = None, **_) -> ToolResult:
        if self.knowledge is None:
            return ToolResult(observation="Knowledge base not available.")
        try:
            from ..orchestrator.state import ProcessPhase
            docs = self.knowledge.retrieve(query, phase=ProcessPhase.ELICITATION, k=4)
            if not docs:
                return ToolResult(observation="No relevant knowledge found.")
            snippets = "\n\n".join(
                f"[{d.metadata.get('title', '?')}]\n{d.page_content[:400]}" for d in docs
            )
            return ToolResult(observation=f"Knowledge:\n{snippets}")
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
        """Extract / modify / delete requirements; update belief state."""
        extracted = extracted or []
        modifications = modifications or []
        deletions = deletions or []

        if not extracted and not modifications and not deletions:
            logger.info("[Interviewer] update_requirements called with NO operations (empty).")
            return ToolResult(
                observation="No operations provided.",
                state_updates={"_update_req_done_this_turn": True},
            )

        react_strategy = (state.get("_react_strategy") or "").strip()
        review_feedback = (state.get("review_feedback") or "").strip()
        turn_index = state.get("turn_count", 0)
        is_hitl = bool(review_feedback)

        draft: List[Dict] = list(state.get("requirements_draft") or [])
        coverage_map: Dict = copy.deepcopy(state.get("coverage_map") or {})
        draft_by_id = {r["id"]: r for r in draft}

        newly_added: List[str] = []
        modified_ids: List[str] = []
        deleted_ids: List[str] = []
        skipped: List[str] = []
        warnings: List[str] = []
        zone_changes: List[str] = []
        zones_with_new: Set[str] = set()

        # ── Deletions ─────────────────────────────────────────────────────────
        for op in deletions:
            did = (op.get("id") or "").strip()
            reason = op.get("reason", "")
            if is_hitl:
                reason = f"[HITL] {review_feedback}\n" + reason
            if not did or did not in draft_by_id:
                warnings.append(f"Deletion skipped: '{did}' not found.")
                continue
            for zone in coverage_map.values():
                mapped = zone.get("requirements_mapped", [])
                if did in mapped:
                    mapped.remove(did)
                    if len(mapped) < zone.get("min_requirements", 1):
                        zone["covered"] = False
            draft_by_id[did].setdefault("history", []).append({
                "action": "hitl_deleted" if is_hitl else "deleted",
                "turn": turn_index,
                "reason": reason,
                "old_value": draft_by_id[did].get("description", ""),
            })
            draft = [r for r in draft if r["id"] != did]
            draft_by_id.pop(did, None)
            deleted_ids.append(did)

        # ── Modifications ─────────────────────────────────────────────────────
        for op in modifications:
            mid = (op.get("id") or "").strip()
            field = (op.get("field") or "").strip()
            nval = op.get("new_value")
            reason = op.get("reason", "")
            if is_hitl:
                reason = f"[HITL] {review_feedback}\n" + reason
            if not mid or not field or mid not in draft_by_id:
                warnings.append(f"Modification skipped: id='{mid}', field='{field}'.")
                continue
            req = draft_by_id[mid]
            req.setdefault("history", []).append({
                "action": "hitl_modified" if is_hitl else "modified",
                "turn": turn_index,
                "field": field,
                "old_value": req.get(field),
                "reason": reason,
            })
            req[field] = nval
            modified_ids.append(mid)

        # ── New extractions ───────────────────────────────────────────────────
        fr_n = sum(1 for r in draft if r["type"] == "functional")
        nfr_n = sum(1 for r in draft if r["type"] == "non_functional")
        con_n = sum(1 for r in draft if r["type"] == "constraint")

        def _next_id(rtype: str) -> str:
            nonlocal fr_n, nfr_n, con_n
            if rtype == "functional":     fr_n += 1; return f"FR-{fr_n:03d}"
            if rtype == "non_functional": nfr_n += 1; return f"NFR-{nfr_n:03d}"
            con_n += 1;
            return f"CON-{con_n:03d}"

        for raw in extracted:
            rtype = raw.get("type", "functional")
            desc = (raw.get("description") or "").strip()
            rat = (raw.get("rationale") or "").strip()

            if not desc:
                warnings.append("Skipped: empty description.")
                continue
            if not rat:
                warnings.append(f"Skipped: no rationale for '{desc[:60]}'.")
                continue

            vague = [w for w in _VAGUE_WORDS if w in desc.lower().split()]
            if vague:
                warnings.append(f"Vague language in '{desc[:60]}': {vague}.")

            dup_of, conflict_of = self._check_conflicts(raw, draft)
            if dup_of:
                skipped.append(f"'{desc[:40]}' (dup of {dup_of})")
                continue
            if conflict_of:
                warnings.append(f"Potential conflict with {conflict_of} for: '{desc[:60]}'.")

            if react_strategy:
                rat += f"\n\n[Strategy]:\n{react_strategy[:600]}"
            if is_hitl:
                rat = f"[HITL] From reviewer: {review_feedback}\n" + rat

            req_id = _next_id(rtype)
            new_req: Dict[str, Any] = {
                "id": req_id,
                "type": rtype,
                "description": desc,
                "priority": raw.get("priority", "medium"),
                "source_turn": raw.get("source_turn", turn_index),
                "status": raw.get("status", "inferred"),
                "rationale": rat,
                "history": [{
                    "action": "hitl_added" if is_hitl else "created",
                    "turn": turn_index,
                    "reason": f"[HITL] {review_feedback}" if is_hitl else "Extracted from interview.",
                }],
            }
            draft.append(new_req)
            draft_by_id[req_id] = new_req
            newly_added.append(req_id)

            # Semantic zone auto-mapping
            matched_zones = self._semantic_map_to_zones(new_req, coverage_map)
            for zid in matched_zones:
                zone = coverage_map[zid]
                if req_id not in zone["requirements_mapped"]:
                    zone["requirements_mapped"].append(req_id)
                    was = zone["covered"]
                    if len(zone["requirements_mapped"]) >= zone.get("min_requirements", 1):
                        zone["covered"] = True
                    if not was and zone["covered"]:
                        zone_changes.append(f"✓ '{zone['description']}' now COVERED.")
                zones_with_new.add(zid)

            # Belief state: persist confirmed facts via MemoryModule
            if new_req["status"] == "confirmed":
                primary = matched_zones[0] if matched_zones else "general"
                self.memory.settle_fact(primary, req_id, desc)

        # ── Assess Completeness ──────────────────────────────────────────────
        completeness = self._assess_completeness(draft)

        obs_parts = [
            "Requirements updated ("
            + (f"+{len(newly_added)} added: {newly_added}" if newly_added else "no new")
            + (f", {len(modified_ids)} modified" if modified_ids else "")
            + (f", {len(deleted_ids)} deleted" if deleted_ids else "")
            + (f", {len(skipped)} dups skipped" if skipped else "")
            + f"). Total: {len(draft)} ({fr_n} FR / {nfr_n} NFR / {con_n} CON).",
            f"Coverage: {len(zones_with_new)} zones updated. "
            f"Completeness Score: {completeness:.2f}/{self._completeness_threshold:.2f}.",
        ]
        if zone_changes: obs_parts.append("Zone updates: " + " ".join(zone_changes))
        if warnings:     obs_parts.append("Warnings: " + "; ".join(warnings))

        logger.info(
            "[Interviewer] update_requirements: +%d new, %d modified, %d deleted, "
            "%d total, completeness=%.2f.",
            len(newly_added), len(modified_ids), len(deleted_ids),
            len(draft), completeness
        )

        return ToolResult(
            observation="\n".join(obs_parts),
            state_updates={
                "requirements_draft": draft,
                "coverage_map": coverage_map,
                "_update_req_done_this_turn": True,  # ← sequence gate flag
            },
        )

    # ------------------------------------------------------------------

    def _tool_send_message(
        self,
        message:     str,
        target_zone: str = "",
        state:       Dict = None,
        **_,
    ) -> ToolResult:
        message = message or "Could you elaborate on that?"

        # ── Sequence guard: update_requirements must precede send_message ──
        # Only enforced when a stakeholder reply exists (not on the first turn).
        conversation    = list(state.get("conversation") or [])
        has_enduser_msg = any(t.get("role") == "enduser" for t in conversation)

        if has_enduser_msg and not state.get("_update_req_done_this_turn"):
            return ToolResult(
                observation=(
                    "[SEQUENCE VIOLATION] update_requirements MUST be called before "
                    "send_message when a stakeholder reply exists. "
                    "Call update_requirements first, then send_message."
                ),
                # should_return=False: loop continues so agent can correct itself.
            )

        # ── Repeat guard: reject questions identical to recent ones ────────
        recent_questions = [
            t["content"].strip()
            for t in conversation
            if t.get("role") == "interviewer"
        ][-5:]

        if message.strip() in recent_questions:
            return ToolResult(
                observation=(
                    f"[REPEAT VIOLATION] This exact question was already asked: "
                    f'"{message[:120]}". '
                    "You MUST ask about a DIFFERENT aspect or a DIFFERENT zone. "
                    "Check the coverage table and select an uncovered zone."
                ),
                # should_return=False: loop continues so agent picks a better question.
            )

        # ── Post the message ───────────────────────────────────────────────
        conversation.append({
            "role":      "interviewer",
            "content":   message,
            "timestamp": datetime.now().isoformat(),
        })
        logger.info("[Interviewer → Stakeholder] %s", message)

        updates: Dict[str, Any] = {
            "conversation":               conversation,
            "_update_req_done_this_turn": False,   # reset for the next turn
        }
        if target_zone:
            cmap = copy.deepcopy(state.get("coverage_map") or {})
            if target_zone in cmap:
                cmap[target_zone]["last_probed_turn"] = state.get("turn_count", 0)
                updates["coverage_map"] = cmap

        return ToolResult(
            observation=f"Question sent: {message}",
            state_updates=updates,
            should_return=True,
        )

    # ------------------------------------------------------------------

    def _tool_check_coverage(self, state: Dict = None, **_) -> ToolResult:
        """Full zone status and belief-state facts."""
        coverage_map = state.get("coverage_map") or {}

        if not coverage_map:
            return ToolResult(observation="Coverage map not initialised — call propose_zones first.")

        requirements = state.get("requirements_draft") or []
        completeness = self._assess_completeness(requirements)

        lines:        List[str] = ["━━ COVERAGE & BELIEF STATE ━━"]
        uncovered_n   = 0

        for zone_id, zd in coverage_map.items():
            if zd.get("auto_covered"):
                lines.append(f"  ➖ [{zone_id}] {zd['description']}: optional")
                continue

            mapped   = len(zd.get("requirements_mapped", []))
            needed   = zd.get("min_requirements", 1)
            covered  = zd.get("covered", False)

            if not covered: uncovered_n += 1

            lines.append(
                f"  {'✓' if covered else '✗'} [{zone_id}] {zd['description']}\n"
                f"      Reqs: {mapped}/{needed}"
            )
            if not covered:
                lines.append(f"      Hint: {zd.get('semantic_hint', '')}")

            # Belief-state settled facts via MemoryModule
            settled = self.memory.recall_zone(zone_id, limit=3)
            if settled:
                lines.append("      Settled: " + " | ".join(s[:70] for s in settled))

        lines.append("\n━━ SUMMARY ━━")
        lines.append(f"Completeness : {completeness:.2f} / {self._completeness_threshold:.2f}")
        lines.append(f"Uncovered    : {uncovered_n} zone(s)")

        if completeness >= self._completeness_threshold:
            lines.append(
                "\n→ COMPLETENESS THRESHOLD MET.\n"
                "  Perform Tier-2 Coherence Check in [STRATEGY]:\n" 
                "  'Could a software engineer begin system design from this list?'\n"
                "  YES → call write_interview_record.\n"
                "  NO  → state the specific gap and probe it."
            )
        else:
            lines.append("\n→ Continue probing to reach the completeness threshold.")

        return ToolResult(observation="\n".join(lines))

    # ------------------------------------------------------------------

    def _tool_write_interview_record(
            self,
            gaps: List[str] = None,
            notes: str = "",
            state: Dict = None,
            **_,
    ) -> ToolResult:
        if not state.get("readiness_approved"):
            return ToolResult(
                observation="BLOCKED — You MUST call 'evaluate_readiness' and pass the global check before writing the interview record.",
                should_return=False
            )

        requirements = list(state.get("requirements_draft") or [])
        if not requirements:
            return ToolResult(
                observation="BLOCKED — cannot write an empty record. Extract requirements first."
            )

        coverage_map = state.get("coverage_map") or {}
        conversation = state.get("conversation") or []
        conflict_log = list(state.get("conflict_log") or [])
        dep_graph = dict(state.get("dependency_graph") or {})
        gaps = list(gaps or [])

        uncovered = [
            zd.get("description", zid)
            for zid, zd in coverage_map.items()
            if not zd.get("covered") and not zd.get("auto_covered")
        ]
        if uncovered:
            gaps += [f"Zone '{z}' not fully covered" for z in uncovered]

        completeness = self._assess_completeness(requirements)
        fr_n = sum(1 for r in requirements if r["type"] == "functional")
        nfr_n = sum(1 for r in requirements if r["type"] == "non_functional")
        con_n = sum(1 for r in requirements if r["type"] == "constraint")

        record: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "session_id": state.get("session_id", str(uuid.uuid4())),
            "project_description": state.get("project_description", ""),
            "conversation": conversation,
            "total_turns": state.get("turn_count", len(conversation) // 2),
            "requirements_identified": requirements,
            "gaps_identified": gaps,
            "notes": notes,
            "completeness_score": completeness,
            "coverage_report": {
                zid: {
                    "description": zd.get("description", zid),
                    "covered": zd.get("covered", False),
                    "requirements_mapped": zd.get("requirements_mapped", []),
                }
                for zid, zd in coverage_map.items()
            },
            "dependency_report": self._build_dependency_report(dep_graph, requirements),
            "conflict_log": conflict_log,
            "created_at": datetime.now().isoformat(),
            "status": "pending_review",
        }

        artifacts = dict(state.get("artifacts") or {})
        artifacts["interview_record"] = record

        logger.info(
            "[Interviewer] Record written: %d reqs (%d FR/%d NFR/%d CON), "
            "completeness=%.2f, %d gaps, %d conflicts.",
            len(requirements), fr_n, nfr_n, con_n,
            completeness, len(gaps), len(conflict_log),
        )

        obs = (
            f"Interview record written: {len(requirements)} requirements "
            f"({fr_n} FR / {nfr_n} NFR / {con_n} CON), "
            f"completeness={completeness:.2f}, {len(gaps)} gaps."
        )
        if uncovered:
            obs += f"\n⚠ Soft warning: {len(uncovered)} zone(s) uncovered: {uncovered}."

        return ToolResult(
            observation=obs,
            state_updates={"artifacts": artifacts, "interview_complete": True},
            should_return=True,
        )

    # ------------------------------------------------------------------
    # Thin delegation tools
    # ------------------------------------------------------------------

    def _tool_map_requirement_to_zone(
        self, req_id: str, zone_id: str, state: Dict = None, **_
    ) -> ToolResult:
        cmap    = copy.deepcopy(state.get("coverage_map") or {})
        req_ids = {r["id"] for r in (state.get("requirements_draft") or [])}

        if zone_id not in cmap:
            return ToolResult(observation=f"Zone '{zone_id}' not found: {list(cmap.keys())}")
        if req_id not in req_ids:
            return ToolResult(observation=f"Requirement '{req_id}' not found.")

        zone = cmap[zone_id]
        if req_id in zone.get("requirements_mapped", []):
            return ToolResult(observation=f"{req_id} already mapped to '{zone_id}'.")

        zone.setdefault("requirements_mapped", []).append(req_id)
        if len(zone["requirements_mapped"]) >= zone.get("min_requirements", 1):
            zone["covered"] = True

        return ToolResult(
            observation=(
                f"Mapped {req_id} → '{zone.get('description', zone_id)}'. "
                f"Zone: {'COVERED' if zone['covered'] else 'still uncovered'} "
                f"({len(zone['requirements_mapped'])}/{zone.get('min_requirements', 1)} reqs)."
            ),
            state_updates={"coverage_map": cmap},
        )

    def _tool_detect_dependency(
        self,
        from_req:      str,
        to_req:        str,
        relation_type: str,
        rationale:     str = "",
        state:         Dict = None,
        **_,
    ) -> ToolResult:
        valid = {"depends_on", "enables", "conflicts_with", "refinement_of"}
        ids   = {r["id"] for r in (state.get("requirements_draft") or [])}

        for rid in (from_req, to_req):
            if rid not in ids:
                return ToolResult(observation=f"Requirement '{rid}' not in draft.")
        if relation_type not in valid:
            return ToolResult(observation=f"relation_type must be one of {valid}.")

        dep_graph = copy.deepcopy(state.get("dependency_graph") or {})
        deps = dep_graph.setdefault(from_req, {}).setdefault(relation_type, [])
        if to_req not in deps:
            deps.append(to_req)

        return ToolResult(
            observation=f"Dep: {from_req} --[{relation_type}]--> {to_req}. {rationale}",
            state_updates={"dependency_graph": dep_graph},
        )

    def _tool_flag_conflict(
        self,
        req_a:         str,
        req_b:         str,
        conflict_type: str,
        description:   str = "",
        state:         Dict = None,
        **_,
    ) -> ToolResult:
        valid = {"scope_creep", "implementation_clash", "priority_inversion"}
        ids   = {r["id"] for r in (state.get("requirements_draft") or [])}

        for rid in (req_a, req_b):
            if rid not in ids:
                return ToolResult(observation=f"Requirement '{rid}' not found.")
        if conflict_type not in valid:
            return ToolResult(observation=f"conflict_type must be one of {valid}.")

        conflict_log = list(state.get("conflict_log") or [])
        conflict_log.append({
            "req_a":             req_a,
            "req_b":             req_b,
            "conflict_type":     conflict_type,
            "description":       description,
            "resolution_status": "unresolved",
            "logged_at":         datetime.now().isoformat(),
        })
        return ToolResult(
            observation=f"Conflict logged: {req_a} ↔ {req_b} [{conflict_type}]. {description}",
            state_updates={"conflict_log": conflict_log},
        )

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _semantic_map_to_zones(req: Dict, coverage_map: Dict) -> List[str]:
        """Return up to 2 zone IDs best matching a requirement via Jaccard similarity."""
        text  = (req.get("description", "") + " " + req.get("rationale", "")).lower()
        rtype = req.get("type", "")
        scored: List[Tuple[str, float]] = []

        for zid, zd in coverage_map.items():
            if zd.get("auto_covered"):
                continue
            zone_text = (zd.get("description", "") + " " + zd.get("semantic_hint", "")).lower()
            sim = InterviewerAgent._jaccard(text, zone_text)
            if rtype == "non_functional" and any(
                kw in zone_text for kw in ("non-functional", "quality", "performance", "reliability", "security")
            ):
                sim += 0.25
            if rtype == "constraint" and any(
                kw in zone_text for kw in ("constraint", "legal", "budget", "timeline", "limitation")
            ):
                sim += 0.25
            if sim > 0.05:
                scored.append((zid, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [z[0] for z in scored[:2]]

    @staticmethod
    def _jaccard(a: str, b: str) -> float:
        stop = {
            "the", "a", "an", "is", "are", "be", "to", "of", "and", "or",
            "that", "it", "for", "in", "on", "with", "as", "what", "how",
            "when", "where", "who", "why",
        }
        wa = set(a.split()) - stop
        wb = set(b.split()) - stop
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

    @staticmethod
    def _assess_completeness(requirements: List[Dict]) -> float:
        """Extreme 6-criteria weighted scoring with priority check and severe penalties."""
        if not requirements:
            return 0.0

        def count_keywords(reqs: List[Dict], keywords: set) -> int:
            return sum(1 for r in reqs if
                       any(kw in (r.get("description", "") + " " + r.get("rationale", "")).lower() for kw in keywords))

        # 1. Functional (20%, target 8)
        fr_n = sum(1 for r in requirements if r.get("type") == "functional")
        score_fr = 0.20 * min(1.0, fr_n / 8.0)

        # 2. Non-Functional (20%, target 5)
        nfr_n = sum(1 for r in requirements if r.get("type") == "non_functional")
        score_nfr = 0.20 * min(1.0, nfr_n / 5.0)

        # 3. Constraints (20%, target 4)
        con_kws = {"must", "cannot", "limited", "restricted", "compliance", "require"}
        score_con = 0.20 * min(1.0, count_keywords(requirements, con_kws) / 4.0)

        # 4. Business Objectives (15%, target 3)
        bus_kws = {"business", "objective", "goal", "value", "benefit", "roi", "purpose"}
        score_bus = 0.15 * min(1.0, count_keywords(requirements, bus_kws) / 3.0)

        # 5. Acceptance Criteria (15%, target 3)
        acc_kws = {"accept", "criteria", "test", "verify", "validate", "ensure"}
        score_acc = 0.15 * min(1.0, count_keywords(requirements, acc_kws) / 3.0)

        # 6. Volume (10%, target 20 total)
        score_stake = 0.10 * min(1.0, len(requirements) / 20.0)

        score = score_fr + score_nfr + score_con + score_bus + score_acc + score_stake

        # PRIORITY PENALTY: Trừ thẳng 15% tổng điểm nếu lạm dụng "High" priority (> 50% tổng số reqs)
        high_prio_n = sum(1 for r in requirements if r.get("priority", "").lower() == "high")
        if len(requirements) > 0 and (high_prio_n / len(requirements)) > 0.5:
            score -= 0.15

            # BÀN TAY THÉP: Chia đôi điểm nếu thiếu bất kỳ nhóm Cốt lõi nào
        if fr_n == 0 or nfr_n == 0 or count_keywords(requirements, con_kws) == 0 or count_keywords(requirements,
                                                                                                   acc_kws) == 0:
            score *= 0.5

        return round(max(0.0, min(score, 1.0)), 3)

    @staticmethod
    def _build_dependency_report(dep_graph: Dict, requirements: List[Dict]) -> Dict[str, Any]:
        req_map    = {r["id"]: r for r in requirements}
        issues:    List[Dict] = []
        ordering:  List[str]  = []
        visited:   Set[str]   = set()
        rec_stack: Set[str]   = set()

        def _has_cycle(node: str) -> bool:
            visited.add(node); rec_stack.add(node)
            for nb in dep_graph.get(node, {}).get("depends_on", []):
                if nb not in visited:
                    if _has_cycle(nb): return True
                elif nb in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for rid in dep_graph:
            if rid not in visited and _has_cycle(rid):
                issues.append({"type": "circular_dependency", "req_id": rid})

        prank = {"high": 3, "medium": 2, "low": 1}
        for rid, rels in dep_graph.items():
            rp = prank.get(req_map.get(rid, {}).get("priority", "low"), 1)
            for dep_id in rels.get("depends_on", []):
                dp = prank.get(req_map.get(dep_id, {}).get("priority", "low"), 1)
                if rp > dp:
                    issues.append({"type": "priority_inversion", "req_id": rid, "dep_id": dep_id})

        if not any(i["type"] == "circular_dependency" for i in issues):
            in_deg = {rid: 0 for rid in req_map}
            for rid, rels in dep_graph.items():
                for dep in rels.get("depends_on", []):
                    in_deg[rid] = in_deg.get(rid, 0) + 1
            queue     = [r for r, d in in_deg.items() if d == 0]
            processed: List[str] = []
            while queue:
                node = queue.pop(0); processed.append(node)
                for rid, rels in dep_graph.items():
                    if node in rels.get("depends_on", []):
                        in_deg[rid] -= 1
                        if in_deg[rid] == 0: queue.append(rid)
            ordering = processed

        return {"dependency_graph": dep_graph, "issues": issues, "suggested_order": ordering}

    @staticmethod
    def _check_conflicts(new_req: Dict, draft: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
        new_desc = new_req.get("description", "")
        dup, conflict = None, None
        for ex in draft:
            overlap = InterviewerAgent._jaccard(new_desc, ex.get("description", ""))
            if overlap > 0.55:
                new_neg = bool({"not", "never", "no", "without"} & set(new_desc.lower().split()))
                ex_neg  = bool({"not", "never", "no", "without"} & set(ex.get("description", "").lower().split()))
                if new_neg != ex_neg:
                    conflict = conflict or ex.get("id")
                else:
                    dup = dup or ex.get("id")
            if dup and conflict:
                break
        return dup, conflict

    _DOC_EVALUATE_READINESS = (
        "Perform a global review of ALL extracted requirements before finalisation.\n"
        "Checks for unresolved conflicts, implicit duplications, and ensures the system\n"
        "architecture is coherent. MUST be called when Completeness threshold is met.\n"
        "Input: {}"
    )

    def _tool_evaluate_readiness(self, state: Dict = None, **_) -> ToolResult:
        draft = state.get("requirements_draft") or []
        completeness = self._assess_completeness(draft)

        # 1. Artifact-Driven Gate: Threshold check
        if completeness < self._completeness_threshold:
            return ToolResult(
                observation=f"Readiness check failed: Completeness ({completeness:.2f}) is below threshold ({self._completeness_threshold:.2f}). Continue elicitation."
            )

        # 2. Global Scan: Deduplication & Conflict Detection
        conflicts = []
        for i in range(len(draft)):
            for j in range(i + 1, len(draft)):
                dup, conf = self._check_conflicts(draft[i], [draft[j]])
                if conf:
                    conflicts.append(f"[{draft[i]['id']}] conflicts with [{draft[j]['id']}]")
                elif dup:
                    conflicts.append(f"[{draft[i]['id']}] is highly duplicated with [{draft[j]['id']}]")

        # 3. Check for manually flagged conflicts that are unresolved
        conflict_log = state.get("conflict_log") or []
        unresolved = [c for c in conflict_log if c.get("resolution_status") != "resolved"]

        if conflicts or unresolved:
            obs = "Readiness check FAILED: Unresolved global issues detected.\n"
            if conflicts:
                obs += "Semantic clashes / duplicates found in draft:\n" + "\n".join(f"- {c}" for c in conflicts)
            if unresolved:
                obs += "\nUnresolved manually logged conflicts:\n" + "\n".join(
                    f"- {c['req_a']} vs {c['req_b']} ({c['conflict_type']})" for c in unresolved)

            obs += "\n\nACTION REQUIRED: You MUST resolve these by using 'update_requirements' (modifying/deleting) or 'send_message' (asking stakeholder) before re-evaluating."
            return ToolResult(observation=obs)

        # Passed: Artifact is ready for the next phase
        return ToolResult(
            observation="Readiness check PASSED. No global conflicts found. Backlog is groomed. You are now authorized to call write_interview_record.",
            state_updates={"readiness_approved": True}
        )

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph node entry point."""
        conversation = state.get("conversation") or []
        turn_count = state.get("turn_count", 0)
        max_turns = state.get("max_turns", self._max_turns)
        draft = state.get("requirements_draft") or []
        coverage_map = state.get("coverage_map") or {}
        review_feedback = (state.get("review_feedback") or "").strip()

        completeness = self._assess_completeness(draft)
        is_first_turn = not coverage_map

        # ── 1. SYNC NATIVE MEMORY (Limit to last 8 turns) ─────────────────
        self.memory.refresh()  # Clear short-term buffer from previous runs
        recent_turns = conversation[-8:] if conversation else []

        for turn in recent_turns:
            # For Interviewer: its own messages are 'assistant', stakeholder's are 'user'
            if turn.get("role") == "interviewer":
                self.memory.add(turn["content"], role="assistant")
            else:
                self.memory.add(turn["content"], role="user")

        # ── 2. EXTRACT LATEST REPLY FOR FOCUSED EXTRACTION ────────────────
        latest_reply = "(none)"
        if conversation and conversation[-1].get("role") == "enduser":
            latest_reply = conversation[-1].get("content", "")

        # ── Requirements summary ──────────────────────────────────────────
        draft_summary = (
                "\n".join(
                    f"  [{r['id']}] ({r['type']}, {r['status']}) {r.get('description', '')[:80]}\n"
                    f"    ↳ {r.get('rationale', '')[:80]}"
                    for r in draft[-12:]
                ) or "  (none yet)"
        )

        # ── Coverage summary ──────────────────────────────────────────────
        required_zones = [(zid, zd) for zid, zd in coverage_map.items() if not zd.get("auto_covered")]
        covered_n = sum(1 for _, zd in required_zones if zd.get("covered"))

        if coverage_map:
            cov_lines: List[str] = [f"Coverage: {covered_n}/{len(required_zones)} required zones."]
            for zid, zd in required_zones:
                mapped = len(zd.get("requirements_mapped", []))
                needed = zd.get("min_requirements", 1)
                settled_n = self.memory.count_zone(zid)

                line = (
                    f"  {'✓' if zd.get('covered') else '✗'} [{zid}] {zd.get('description', zid)}: "
                    f"{mapped}/{needed} reqs | settled={settled_n}"
                )
                if not zd.get("covered"):
                    line += f"\n       Hint: {zd.get('semantic_hint', '')}"
                cov_lines.append(line)
            coverage_block = "\n".join(cov_lines)
        else:
            coverage_block = "(not yet defined — call propose_zones first)"

        # ── Situation label ───────────────────────────────────────────────
        if is_first_turn:
            situation = (
                "FIRST TURN — Step 1: Call 'propose_zones'. "
                "Step 2: Call 'update_requirements' to extract initial requirements from the PROJECT DESCRIPTION. "
                "Step 3: Call 'send_message' with your opening question."
            )
        elif review_feedback:
            situation = (
                "HITL RE-INTERVIEW — apply all reviewer feedback via update_requirements, "
                "then re-evaluate readiness."
            )
        elif state.get("readiness_approved"):
            situation = (
                "FINAL VERIFICATION — Readiness approved. The backlog is clean. "
                "Call write_interview_record to finish the session."
            )
        elif completeness >= self._completeness_threshold:
            situation = (
                "BACKLOG GROOMING — Completeness score is sufficient. "
                "You MUST call 'evaluate_readiness' to perform a global conflict and dependency check. Do not finalise yet."
            )
        elif turn_count >= max(4, max_turns - 3):
            situation = f"APPROACHING LIMIT ({turn_count}/{max_turns}) — extract remaining data quickly."
        else:
            situation = "INTERVIEW IN PROGRESS — focus on raising the completeness score and filling coverage."

        # ── Repeat guard ──────────────────────────────────────────────────
        recent_qs = [t["content"] for t in conversation if t["role"] == "interviewer"][-5:]
        repeat_guard = (
                "Recent questions (do not repeat — send_message will block exact repeats):\n"
                + "\n".join(f"  • {q[:100]}" for q in recent_qs)
        ) if recent_qs else ""

        # ── Review feedback block ─────────────────────────────────────────
        review_block = (
            "━━━━━━━━  REVIEW FEEDBACK (record rejected)  ━━━━━━━━\n"
            f"{review_feedback}\n"
            "Address ALL reviewer points via update_requirements before finalising.\n\n"
        ) if review_feedback else ""

        # ── 3. REVISED TASK PROMPT ────────────────────────────────────────
        task = (
            "━━━━━━━━  PROJECT  ━━━━━━━━\n"
            f"{state.get('project_description', '(not provided)')}\n\n"
            + review_block
            + "━━━━━━━━  LATEST STAKEHOLDER REPLY (ANALYZE & EXTRACT FROM THIS!)  ━━━━━━━━\n"
              f"{latest_reply}\n\n"
              "━━━━━━━━  COVERAGE & STATUS  ━━━━━━━━\n"
              f"{coverage_block}\n\n"
              "━━━━━━━━  REQUIREMENTS DRAFT (last 12)  ━━━━━━━━\n"
              f"{draft_summary}\n\n"
              "━━━━━━━━  CURRENT METRICS  ━━━━━━━━\n"
              f"Turn {turn_count}/{max_turns} | "
              f"Completeness: {completeness:.2f}/{self._completeness_threshold:.2f} | "
              f"Coverage: {covered_n}/{len(required_zones)}\n\n"
            + (f"━━━━━━━━  REPEAT GUARD  ━━━━━━━━\n{repeat_guard}\n\n" if repeat_guard else "")
            + "━━━━━━━━  SITUATION  ━━━━━━━━\n"
              f"{situation}\n\n"
              "━━━━━━━━  MANDATORY RULES  ━━━━━━━━\n"
              "• Every Thought MUST begin with [STRATEGY]...[/STRATEGY].\n"
              "• You MUST extract any new requirements from the LATEST STAKEHOLDER REPLY before asking a new question.\n"
              "• update_requirements BEFORE send_message when a stakeholder reply exists.\n"
              "• send_message: ONE question; always set target_zone.\n"
              "• Exact repeat questions are blocked by send_message — always pick a new angle.\n"
              "• ALL TWO TIERS must confirm before calling write_interview_record.\n"
              "• FINISH only after write_interview_record confirms success.\n"
        )

        return self.react(
            state=state,
            task=task,
            tool_choice="required",
            profile_addendum=self._STOPPING_ADDENDUM
        )