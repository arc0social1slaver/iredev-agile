"""
enduser.py – EndUserAgent  (stakeholder simulator)

Role:  Simulate a realistic stakeholder who responds to the interviewer's
       questions.  The agent reads the last interviewer message from the
       conversation history, uses its knowledge and profile to craft a
       contextually appropriate reply, and posts it back to the state.

ReAct tools
-----------
  search_knowledge – optional lookup for domain context / product patterns
  respond          – post the stakeholder reply; exits the current turn
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


class EndUserAgent(BaseAgent):
    """
    Simulates a stakeholder (product manager / domain expert / end user)
    responding to the interviewer.

    The agent is kept deliberately simple: its main job is to produce
    realistic, project-relevant answers that help the interviewer extract
    useful requirements.  The ``respond`` tool ends its turn immediately.
    """

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="enduser")

        agent_cfg = (
            self._raw_config.get("iredev", {}).get("agents", {}).get("enduser", {})
        )
        custom = agent_cfg.get("custom_params", {})
        self._persona: str = custom.get("persona", "product manager")

    # -- tool registration -------------------------------------------------

    def _register_tools(self) -> None:
        self.register_tool(
            Tool(
                name="search_knowledge",
                description=(
                    "Look up domain knowledge or product patterns to enrich your response. "
                    'Input: {"query": "<text>"}'
                ),
                func=self._tool_search_knowledge,
            )
        )
        self.register_tool(
            Tool(
                name="respond",
                description=(
                    "Post your reply to the interviewer. "
                    "Be specific, realistic, and in character as the stakeholder. "
                    'Input: {"message": "<your answer>"}'
                ),
                func=self._tool_respond,
            )
        )

    # -- tools -------------------------------------------------------------

    def _tool_search_knowledge(self, query: str, state: Dict = None, **_) -> ToolResult:
        if self.knowledge is None:
            return ToolResult(observation="Knowledge base not available.")
        try:
            from ..orchestrator.state import ProcessPhase

            docs = self.knowledge.retrieve(query, phase=ProcessPhase.ELICITATION, k=3)
            if not docs:
                return ToolResult(observation="No relevant knowledge found.")
            snippets = "\n\n".join(
                f"[{d.metadata.get('title', '?')}]\n{d.page_content[:350]}"
                for d in docs
            )
            return ToolResult(observation=f"Context:\n{snippets}")
        except Exception as exc:
            return ToolResult(observation=f"Knowledge search error: {exc}")

    def _tool_respond(
        self,
        message: str = "",  # default prevents crash when LLM omits the key
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """Append the stakeholder's reply to the conversation and exit the turn."""
        if not message:
            logger.warning(
                "EndUserAgent._tool_respond called with empty message; "
                "LLM likely omitted the 'message' key from Action Input."
            )
            message = "(no response provided)"

        conversation = list(state.get("conversation") or [])
        conversation.append(
            {
                "role": "enduser",
                "content": message,
                "timestamp": datetime.now().isoformat(),
            }
        )
        turn_count = (state.get("turn_count") or 0) + 1

        logger.info("[Stakeholder -> Interviewer] %s", message)

        self.memory.add(message, role="assistant")

        return ToolResult(
            observation=f"Response posted: {message}",
            state_updates={
                "conversation": conversation,
                "turn_count": turn_count,
            },
            should_return=True,
        )

    # -- LangGraph node entry point ----------------------------------------

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called by LangGraph on every stakeholder turn.

        Reads the last interviewer question from the conversation and runs
        a short ReAct loop that ends when ``respond`` is called.
        """
        conversation: List[Dict] = state.get("conversation") or []

        last_question = next(
            (
                t["content"]
                for t in reversed(conversation)
                if t["role"] == "interviewer"
            ),
            "(no question yet)",
        )

        prior = [
            t
            for t in conversation
            if not (t["role"] == "interviewer" and t["content"] == last_question)
        ]
        transcript = (
            "\n".join(
                f"{'Interviewer' if t['role'] == 'interviewer' else 'You'}: {t['content']}"
                for t in prior[-10:]
            )
            or "(beginning of conversation)"
        )

        task = (
            f"You are playing the role of a {self._persona} being interviewed "
            f"about software requirements.\n\n"
            f"Project: {state.get('project_description', 'not provided')}\n\n"
            f"Recent conversation:\n{transcript}\n\n"
            f"The interviewer now asks:\n{last_question}\n\n"
            "Instructions:\n"
            "- You MAY use 'search_knowledge' once if you need domain context.\n"
            "- You MUST call 'respond' with your answer to end this turn.\n"
            '  The \'respond\' tool requires exactly this JSON: {"message": "<your answer>"}\n'
            "- Be specific, realistic, and consistent with prior answers.\n"
            "- Speak as the stakeholder -- do NOT acknowledge you are an AI."
        )

        return self.react(state, task)
