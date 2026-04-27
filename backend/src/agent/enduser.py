"""
enduser.py – EndUserAgent (v2: High-Fidelity Stakeholder Simulation)

Changes from v1
───────────────
1. Persona Archetypes — "The Resister", "The Perfectionist", "The Optimist".
   Archetype is read from config or inferred from persona description.
   Injected into task so the ReAct prompt honours the archetype's friction
   patterns (impatience, hedging, over-optimism).

2. Negative Vocabulary Constraints — agent is forbidden from using or
   understanding technical jargon. A banned-term list is injected into the
   task. If the interviewer uses a banned term, the agent must respond as a
   real non-technical stakeholder would: ask for clarification.

3. Implicit Requirements (Knowledge Gaps) — the agent is given a structured
   set of "hidden concerns" it must NOT volunteer until the interviewer drills
   down with Why / What if / specific scenario questions. This models the
   real-world phenomenon where stakeholders only surface edge cases when probed.

4. Information Asymmetry preserved — agent still does NOT read
   elicitation_agenda or ProductVision internals.

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
# Archetype definitions
# ─────────────────────────────────────────────────────────────────────────────

_ARCHETYPE_PROMPTS: Dict[str, str] = {
    "resister": """\
ARCHETYPE — The Resister:
  • You are busy and skeptical. Every question costs you time.
  • You give short, direct answers. You do NOT elaborate unless pushed.
  • If the interviewer repeats something you've already addressed,
    show mild impatience: "I already mentioned that."
  • You doubt whether "the system" will actually solve the real problem.
  • You will NOT answer hypotheticals enthusiastically — "I don't know,
    that hasn't happened yet." is a perfectly acceptable response for you.""",

    "perfectionist": """\
ARCHETYPE — The Perfectionist:
  • You are afraid of committing to something that turns out to be wrong.
  • Every answer comes with qualifications: "That depends…",
    "I'd need to check with my colleagues first…", "I'm not 100% sure."
  • You notice edge cases and volunteer them even when not asked.
  • You are reluctant to give a final answer without caveats.
  • If the interviewer asks you to confirm something, you add conditions.""",

    "optimist": """\
ARCHETYPE — The Optimist:
  • You want the project to succeed and assume it will.
  • You underestimate complexity: "Oh, that should be easy."
  • You volunteer feature ideas and expansions beyond what was asked.
  • You rarely mention risks or blockers unless directly forced to.
  • You tend to over-promise what the system should do.""",
}

_DEFAULT_ARCHETYPE = "resister"

# ─────────────────────────────────────────────────────────────────────────────
# Banned technical vocabulary
# ─────────────────────────────────────────────────────────────────────────────

_BANNED_JARGON = [
    "UI/UX", "responsive", "lazy loading", "WCAG", "API", "backend",
    "frontend", "microservice", "scalable", "agile", "sprint", "user story",
    "endpoint", "refactor", "deploy", "stack", "pipeline", "cache",
    "throughput", "latency", "asynchronous", "webhook", "OAuth",
    "idempotent", "schema", "payload", "middleware",
]


class EndUserAgent(BaseAgent):
    """High-fidelity project stakeholder simulation with archetype, jargon
    constraints, and implicit requirements (knowledge gaps)."""

    def __init__(self):
        super().__init__(name="enduser")

        agent_cfg = self._raw_config.get("agents", {}).get("enduser", {})
        custom    = agent_cfg.get("custom_params", {})

        self._persona: str = custom.get("persona", "business stakeholder")

        # ── Archetype ────────────────────────────────────────────────────────
        raw_archetype    = custom.get("archetype", "").strip().lower()
        self._archetype  = raw_archetype if raw_archetype in _ARCHETYPE_PROMPTS \
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

        Injects only what a real stakeholder would know:
          • their own persona + archetype (behavioural instructions)
          • banned technical vocabulary (negative constraints)
          • implicit requirements they hold but haven't yet revealed
          • the question being asked
          • brief project context (description only)

        Deliberately excludes: elicitation_agenda, elicitation_goal,
        ProductVision internals.
        """
        question     = state.get("current_question", "").strip()
        project_desc = state.get("project_description", "(not provided)")

        if not question:
            return (
                "The interviewer has not asked a question yet. "
                "Wait for a question before responding."
            )

        archetype_block = _ARCHETYPE_PROMPTS.get(self._archetype, "")

        banned_block = (
            "BANNED VOCABULARY (terms you must never use or understand naturally):\n"
            + ", ".join(_BANNED_JARGON)
            + "\n"
            "If the interviewer uses any of these terms, respond as a real "
            "non-technical person: ask what they mean in plain language."
        )

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
            f"PERSONA: {self._persona}",
            "",
            archetype_block,
            "",
            banned_block,
        ]
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
            "Answer the question from your stakeholder perspective.",
            "Stay in character. Use plain, everyday language — not technical terms.",
            "You may call search_knowledge once if you need domain context.",
            "Then call respond with your answer.",
        ]

        return "\n".join(parts)

    # ── LangGraph node entry point ─────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        task = self._build_task(state)
        return self.react(
            state=state,
            task=task,
            tool_choice="required",
            include_memory=True,
        )