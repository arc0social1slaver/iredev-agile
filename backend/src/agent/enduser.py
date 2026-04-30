"""
enduser.py – EndUserAgent (v3: Domain-Agnostic Stakeholder Simulation)

Key Design Principles
─────────────────────
1. Persona Archetypes — "The Resister", "The Perfectionist", "The Optimist".
   Archetype label is injected into the task; full behavioural definitions
   live in enduser_react.txt (single source of truth).

2. Vocabulary — no hardcoded banned-term list. The prompt teaches the agent
   the concept: "never use terms a person in your role wouldn't naturally use".
   The agent decides what counts as jargon based on its persona.

3. Stakeholder Context — key_concern and type are looked up from
   ProductVision target_audiences at build_task time.  This grounds the
   persona's answers in their core worry and relationship to the system.

4. Topic Awareness — source_field of the current agenda item is resolved and
   injected as a concept-level TOPIC NATURE hint so the agent calibrates its
   answer style (assumption → express uncertainty; constraint → express
   practical realities) without seeing the interviewer's elicitation strategy.

5. Information Asymmetry — agent NEVER sees: elicitation_goal, source_ref,
   item_id, or any agenda structure.

Handshake protocol (unchanged)
──────────────────────────────
InterviewerAgent writes → state["current_question"]
EndUserAgent reads      → builds task from current_question
EndUserAgent writes     → state["enduser_answer"]  (via respond tool)
InterviewerAgent reads  → record_answer tool picks it up next turn
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Archetype labels (behaviour definitions live in enduser_react.txt)
# ─────────────────────────────────────────────────────────────────────────────

_VALID_ARCHETYPES = {"resister", "perfectionist", "optimist"}
_DEFAULT_ARCHETYPE = "resister"


# ─────────────────────────────────────────────────────────────────────────────
# Topic-nature hints (source_field → concept-level context for the persona)
#
# These tell the agent *what kind of topic* the current question touches on,
# so it can calibrate answer style (e.g., express uncertainty for assumptions,
# describe practical realities for constraints).  They NEVER expose the
# elicitation_goal, source_ref, or interviewer strategy.
# ─────────────────────────────────────────────────────────────────────────────

_TOPIC_HINTS: Dict[str, str] = {
    "assumption": (
        "something that is believed but unconfirmed about this project. "
        "You may have your own opinion or experience that supports or contradicts it."
    ),
    "initial_requirement": (
        "a specific capability that is expected from the system. "
        "You have experience with how this works or doesn't work today."
    ),
    "non_functional_requirement": (
        "how well something should work — quality, speed, ease-of-use, or similar. "
        "You care about this from your daily experience."
    ),
    "project_constraint": (
        "a hard limit or rule that applies to this project. "
        "You know the practical realities of working under this constraint."
    ),
    "evaluation_criterion": (
        "how the result will be judged. "
        "You have opinions about what 'good enough' looks like from your perspective."
    ),
    "out_of_scope": (
        "something that may or may not be included in the project. "
        "You may or may not have strong feelings about this."
    ),
    "stakeholder_concern": (
        "a concern that directly affects people in your role. "
        "You have firsthand experience with this."
    ),
}

_TOPIC_HINT_FALLBACK = (
    "a topic related to this project. Answer from your lived experience in this role."
)


# ─────────────────────────────────────────────────────────────────────────────
# Stakeholder type → natural-language relationship description
# ─────────────────────────────────────────────────────────────────────────────

_STAKEHOLDER_TYPE_LABELS: Dict[str, str] = {
    "primary_user":   "You use this system directly and regularly — it is built for people like you.",
    "secondary_user": "You use this system occasionally or in a supporting role.",
    "beneficiary":    "You benefit from this system's outputs without using it directly.",
    "decision_maker": "You have authority over the project's scope, direction, or approval.",
    "blocker":        "You can veto or block this project if your concerns are not addressed.",
}


class EndUserAgent(BaseAgent):
    """Domain-agnostic stakeholder simulation.

    Grounds persona answers in ProductVision stakeholder data (key_concern,
    type) and agenda-derived topic hints (source_field) without exposing the
    interviewer's elicitation strategy.
    """

    def __init__(self):
        super().__init__(name="enduser")

        agent_cfg = self._raw_config.get("agents", {}).get("enduser", {})
        custom    = agent_cfg.get("custom_params", {})

        self._persona: str = custom.get("persona", "business stakeholder")

        # ── Archetype ────────────────────────────────────────────────────────
        raw_archetype    = custom.get("archetype", "").strip().lower()
        self._archetype  = raw_archetype if raw_archetype in _VALID_ARCHETYPES \
                           else _DEFAULT_ARCHETYPE

        # ── Implicit requirements (knowledge gaps) ───────────────────────────
        # These are concerns the agent must NOT volunteer — only reveal when
        # the interviewer drills down with "why?" / "what if?" questions.
        raw_implicit: Any = custom.get("implicit_requirements", [])
        self._implicit_requirements: List[str] = (
            raw_implicit if isinstance(raw_implicit, list) else []
        )

    # ── Tool registration ──────────────────────────────────────────────────

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="search_knowledge",
            description=(
                "Look up domain background or business context to help answer "
                "more accurately. Use at most ONCE per turn.\n"
                'Input: {"query": "<what you need to know>"}'
            ),
            func=self._tool_search_knowledge,
        ))
        self.register_tool(Tool(
            name="respond",
            description=(
                "Post your reply to the interviewer's question. "
                "Always the LAST tool call in a turn. Stay fully in character.\n"
                'Input: {"message": "<your answer — 2–4 sentences, in character>"}'
            ),
            func=self._tool_respond,
        ))

    # ── Tool implementations ───────────────────────────────────────────────

    def _tool_search_knowledge(
        self,
        query: str,
        state: Dict = None,
        **_,
    ) -> ToolResult:
        if (state or {}).get("_sk_used_this_turn"):
            return ToolResult(
                observation=(
                    "[RULE VIOLATION] search_knowledge may only be called ONCE per turn. "
                    "Call 'respond' now."
                ),
            )

        if self.knowledge is None:
            return ToolResult(
                observation="Knowledge base not available.",
                state_updates={"_sk_used_this_turn": True},
            )

        try:
            from ..orchestrator.state import ProcessPhase
            docs = self.knowledge.retrieve(query, phase=ProcessPhase.ELICITATION, k=3)
            if not docs:
                return ToolResult(
                    observation="No relevant context found.",
                    state_updates={"_sk_used_this_turn": True},
                )
            snippets = "\n\n".join(
                f"[{d.metadata.get('title', '?')}]\n{d.page_content[:350]}"
                for d in docs
            )
            return ToolResult(
                observation=f"Background context:\n{snippets}",
                state_updates={"_sk_used_this_turn": True},
            )
        except Exception as exc:
            return ToolResult(
                observation=f"Knowledge search error: {exc}",
                state_updates={"_sk_used_this_turn": True},
            )

    def _tool_respond(
        self,
        message: str = "",
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Record the stakeholder's reply and exit the ReAct loop."""
        if not message:
            logger.warning("[EndUserAgent] respond called with empty message; using fallback.")
            message = "(I'm not sure I understood the question — could you rephrase?)"

        conversation = list((state or {}).get("conversation") or [])
        conversation.append({
            "role":      "enduser",
            "content":   message,
            "timestamp": datetime.now().isoformat(),
        })
        turn_count = ((state or {}).get("turn_count") or 0) + 1

        self.memory.add(message, role="assistant")

        return ToolResult(
            observation="Response posted.",
            state_updates={
                "enduser_answer":      message,
                "conversation":        conversation,
                "turn_count":          turn_count,
                "_sk_used_this_turn":  False,
            },
            should_return=True,
        )

    # ── Task builder ───────────────────────────────────────────────────────

    def _build_task(self, state: Dict[str, Any]) -> str:
        """Compose the task prompt for this turn.

        Injects only what a real stakeholder would naturally know:
          • their own persona + archetype label
          • key_concern and type (from ProductVision — what the stakeholder
            cares about and their relationship to the system)
          • topic nature hint (from agenda source_field — what *kind* of
            topic is being discussed, without exposing the interviewer's
            elicitation strategy)
          • implicit requirements (knowledge gaps, if configured)
          • the question being asked
          • brief project context (description only)

        Stakeholder identity resolution (priority order):
          1. state["current_stakeholder_role"]  — set by graph.py/enduser_turn_fn
             from the agenda cursor; always the authoritative source.
          2. self._persona                       — config fallback.

        Deliberately excludes: elicitation_goal, source_ref, item_id,
        agenda structure.
        """
        question     = state.get("current_question", "").strip()
        project_desc = state.get("project_description", "(not provided)")

        # Resolve persona: agenda cursor wins over static config
        agenda_role = (state.get("current_stakeholder_role") or "").strip()
        active_persona = agenda_role if agenda_role else self._persona

        if not question:
            return (
                "The interviewer has not asked a question yet. "
                "Wait for a question before responding."
            )

        # ── Archetype (label only; behaviour is defined in enduser_react.txt) ─
        archetype_block = f"Your archetype is: The {self._archetype.capitalize()}"

        # ── Stakeholder context from ProductVision ────────────────────────────
        # Look up key_concern and type for the current role.
        stakeholder_context = self._resolve_stakeholder_context(
            state, active_persona
        )

        # ── Topic nature from agenda source_field ─────────────────────────────
        # Tells the persona *what kind of topic* is being discussed so they
        # calibrate their answer style — without exposing elicitation_goal.
        topic_block = self._resolve_topic_hint(state)

        # ── Implicit requirements (knowledge gaps) ────────────────────────────
        implicit_block = ""
        if self._implicit_requirements:
            items = "\n".join(f"  • {r}" for r in self._implicit_requirements)
            implicit_block = (
                "HIDDEN CONCERNS (you hold these but must NOT volunteer them unprompted):\n"
                + items + "\n"
                "Reveal one of these ONLY IF the interviewer asks 'why?', "
                "'what if X happens?', or a scenario-specific follow-up question.\n"
                "Do NOT mention any of these in a normal answer."
            )

        parts = [
            f"PERSONA: {active_persona}",
            f"(You are playing the role of: {active_persona}. "
            "Answer entirely from this stakeholder's perspective.)",
            "",
            archetype_block,
        ]

        if stakeholder_context:
            parts += ["", stakeholder_context]

        if topic_block:
            parts += ["", topic_block]

        if implicit_block:
            parts += ["", implicit_block]

        parts += [
            "",
            "PROJECT CONTEXT (what you know as a stakeholder):",
            f"  {project_desc}",
            "",
            "INTERVIEWER'S QUESTION:",
            f"  {question}",
            "",
            f"Answer the question from the perspective of: {active_persona}.",
            "Stay in character. Use plain, everyday language — not technical terms.",
            "You may call search_knowledge once if you need domain context.",
            "Then call respond with your answer.",
        ]

        return "\n".join(parts)

    # ── Stakeholder context resolution ─────────────────────────────────────

    @staticmethod
    def _resolve_stakeholder_context(
        state: Dict[str, Any],
        role_name: str,
    ) -> str:
        """Look up key_concern and type for the current stakeholder from
        ProductVision target_audiences.  Returns a formatted block or "".

        Uses reviewed_product_vision (post-HITL) if available, else falls back
        to the draft product_vision.
        """
        # Prefer reviewed vision (post-HITL), fall back to draft
        artifacts = state.get("artifacts") or {}
        vision = (
            artifacts.get("reviewed_product_vision")
            or state.get("product_vision")
            or {}
        )
        audiences = vision.get("target_audiences") or []
        if not audiences:
            return ""

        # Find matching stakeholder entry by role name
        match = None
        for entry in audiences:
            if entry.get("role", "").strip().lower() == role_name.strip().lower():
                match = entry
                break

        if match is None:
            return ""

        key_concern    = match.get("key_concern", "")
        stype          = match.get("type", "")
        type_label     = _STAKEHOLDER_TYPE_LABELS.get(stype, "")

        lines = ["YOUR STAKEHOLDER PROFILE:"]
        if type_label:
            lines.append(f"  Relationship: {type_label}")
        if key_concern:
            lines.append(f"  Your main concern: \"{key_concern}\"")
            lines.append(
                "  → This concern colours how you hear and answer every question."
                "  When in doubt, steer your answer toward this worry."
            )
        return "\n".join(lines)

    @staticmethod
    def _resolve_topic_hint(state: Dict[str, Any]) -> str:
        """Derive a concept-level topic hint from the current agenda item's
        source_field.  Returns a formatted TOPIC NATURE block or "".

        The hint tells the persona *what kind of topic* is being discussed
        so it can calibrate answer style (e.g. express uncertainty for
        assumptions, describe practical realities for constraints).
        It NEVER exposes elicitation_goal, source_ref, or item_id.
        """
        raw_agenda = state.get("elicitation_agenda")
        if not raw_agenda:
            return ""

        try:
            # Lazy import to avoid circular dependency
            from .interviewer import AgendaRuntime
            runtime = (
                AgendaRuntime(**raw_agenda)
                if isinstance(raw_agenda, dict)
                else raw_agenda
            )
            item = runtime.current_item()
            if item is None:
                return ""
            source_field = getattr(item, "source_field", "")
        except Exception:
            return ""

        hint = _TOPIC_HINTS.get(source_field, _TOPIC_HINT_FALLBACK)
        return (
            f"TOPIC NATURE: This question touches on {hint}\n"
            "Use this to calibrate your answer — do not mention this hint directly."
        )

    # ── LangGraph node entry point ─────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        task = self._build_task(state)
        return self.react(
            state=state,
            task=task,
            tool_choice="required",
            include_memory=True,
        )