"""
interviewer.py – InterviewerAgent

Role:  Conduct a multi-turn requirements interview with a simulated stakeholder
       (EndUserAgent) and produce an ``interview_record`` artifact.

ReAct tools
───────────
  search_knowledge        – retrieve methodology / best-practice snippets
  send_message            – post one question to the conversation; hands control
                            to the EndUserAgent and exits the current turn
  write_interview_record  – compile the conversation into a structured artifact,
                            mark the interview complete, and hand back to the
                            supervisor

Artifact storage
────────────────
  The interview_record is written directly into WorkflowState["artifacts"].
  The graph layer (graph.py) mirrors it into the LangGraph store automatically.
  The old ArtifactPool / MemoryArtifactStorage classes are no longer used here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# InterviewerAgent
# ---------------------------------------------------------------------------


class InterviewerAgent(BaseAgent):
    """
    Drives the interview phase.

    Each LangGraph turn runs a ReAct loop that either:
    * Asks one question  → ``send_message``          → waits for stakeholder
    * Ends the interview → ``write_interview_record`` → artifact written, done
    """

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="interviewer", config_path=config_path)

        agent_cfg = self._raw_config.get("agents", {}).get("interviewer", {})
        custom = agent_cfg.get("custom_params", {})
        self._completeness_threshold: float = custom.get("completeness_threshold", 0.75)
        self._max_turns: int = custom.get("max_turns", 20)

    # ── tool registration ─────────────────────────────────────────────────

    def _register_tools(self) -> None:
        self.register_tool(
            Tool(
                name="search_knowledge",
                description=(
                    "Search the knowledge base for interviewing techniques, "
                    "requirements-elicitation methodologies, or domain context. "
                    'Input: {"query": "<text>"}'
                ),
                func=self._tool_search_knowledge,
            )
        )
        self.register_tool(
            Tool(
                name="send_message",
                description=(
                    "Send one interview question to the stakeholder. "
                    "The stakeholder will reply and you will be called again. "
                    'Input: {"message": "<your question>"}'
                ),
                func=self._tool_send_message,
            )
        )
        self.register_tool(
            Tool(
                name="write_interview_record",
                description=(
                    "Finalise the interview: provide structured requirements extracted "
                    "from the full conversation, write the interview_record artifact, "
                    "and mark the phase complete. "
                    "Input: {"
                    '"requirements": [{"id":"FR-001","type":"functional",'
                    '"description":"...","priority":"high","source":"stakeholder"},...], '
                    '"gaps": ["<unclear area>", ...], '
                    '"notes": "<overall summary>"}'
                ),
                func=self._tool_write_interview_record,
            )
        )

    # ── tools ─────────────────────────────────────────────────────────────

    def _tool_search_knowledge(self, query: str, state: Dict = None, **_) -> ToolResult:
        if self.knowledge is None:
            return ToolResult(observation="Knowledge base not available.")
        try:
            from ..orchestrator.state import ProcessPhase

            docs = self.knowledge.retrieve(query, phase=ProcessPhase.ELICITATION, k=4)
            if not docs:
                return ToolResult(observation="No relevant knowledge found.")
            snippets = "\n\n".join(
                f"[{d.metadata.get('title', '?')}]\n{d.page_content[:400]}"
                for d in docs
            )
            return ToolResult(observation=f"Knowledge retrieved:\n{snippets}")
        except Exception as exc:
            return ToolResult(observation=f"Knowledge search failed: {exc}")

    def _tool_send_message(self, message: str, state: Dict = None, **_) -> ToolResult:
        """Append the interviewer's question and exit the turn."""
        conversation = list(state.get("conversation") or [])
        conversation.append(
            {
                "role": "interviewer",
                "content": message,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.info("[Interviewer → Stakeholder] %s", message)
        return ToolResult(
            observation=f"Question sent: {message}",
            state_updates={"conversation": conversation},
            should_return=True,
        )

    def _tool_write_interview_record(
        self,
        requirements: List[Dict] = None,
        gaps: List[str] = None,
        notes: str = "",
        state: Dict = None,
        **_,
    ) -> ToolResult:
        """
        Build the interview_record artifact and write it directly into WorkflowState.

        The LangGraph store sync happens automatically in graph.py's
        interviewer_turn_fn after this tool returns.
        """
        conversation = state.get("conversation") or []
        requirements = requirements or []
        gaps = gaps or []

        record: Dict[str, Any] = {
            "session_id": state.get("session_id", str(uuid.uuid4())),
            "project_description": state.get("project_description", ""),
            "conversation": conversation,
            "total_turns": state.get("turn_count", len(conversation) // 2),
            "requirements_identified": requirements,
            "gaps_identified": gaps,
            "notes": notes,
            "completeness_score": self._assess_completeness(requirements),
            "created_at": datetime.now().isoformat(),
            "status": "completed",
        }

        artifacts = dict(state.get("artifacts") or {})
        artifacts["interview_record"] = record

        logger.info(
            "[Interviewer] Interview complete – %d requirements, %d gaps.",
            len(requirements),
            len(gaps),
        )

        return ToolResult(
            observation=(
                f"Interview record written. "
                f"{len(requirements)} requirements and {len(gaps)} gaps identified."
            ),
            state_updates={
                "artifacts": artifacts,
                "interview_complete": True,
            },
            should_return=True,
        )

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _assess_completeness(requirements: List[Dict]) -> float:
        """Heuristic completeness score based on requirement coverage."""
        if not requirements:
            return 0.0
        has_functional = any(r.get("type") == "functional" for r in requirements)
        has_non_functional = any(
            r.get("type") == "non_functional" for r in requirements
        )
        score = 0.4 * has_functional + 0.3 * has_non_functional
        score += min(0.3, len(requirements) / 30)
        return round(score, 3)

    def _should_end(self, requirements: List, turn_count: int, max_turns: int) -> bool:
        if self._assess_completeness(requirements) >= self._completeness_threshold:
            return True
        if turn_count >= max_turns:
            return True
        return False

    # ── LangGraph node entry point ────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called by LangGraph on every interviewer turn.

        Builds a task description from the current conversation and runs the
        ReAct loop.  The loop terminates when either:
          - ``send_message`` is called        (question sent; waits for stakeholder)
          - ``write_interview_record`` called  (interview over)
          - ``max_react_iterations`` reached   (safety fallback)
        """
        conversation = state.get("conversation") or []
        turn_count = state.get("turn_count", 0)
        max_turns = state.get("max_turns", self._max_turns)

        transcript = (
            "\n".join(
                f"{'Interviewer' if t['role'] == 'interviewer' else 'Stakeholder'}: "
                f"{t['content']}"
                for t in conversation
            )
            or "(interview has not started yet)"
        )

        # Heuristic: treat every pair of turns as one requirement candidate
        # The LLM will do the real extraction when writing the record.
        heuristic_req_count = max(0, turn_count // 2)
        enough_info = (
            turn_count >= min(8, max_turns)  # gathered at least 4 exchanges
            or turn_count >= max_turns  # hit hard limit
        )

        # ── instructions for writing the record ───────────────────────────
        write_record_instructions = (
            "IMPORTANT – when you call 'write_interview_record':\n"
            "  1. Re-read the ENTIRE conversation transcript above carefully.\n"
            "  2. Extract EVERY requirement mentioned by the stakeholder.\n"
            "  3. For each requirement use the schema:\n"
            '       {"id": "FR-001", "type": "functional",\n'
            '        "description": "...", "priority": "high",\n'
            '        "source": "stakeholder"}\n'
            "     type must be 'functional' or 'non_functional'.\n"
            "  4. List any topics the stakeholder was vague about as 'gaps'.\n"
            "  5. Write a 2-3 sentence 'notes' summary.\n"
            "  DO NOT pass an empty requirements list – extract from the transcript."
        )

        task = (
            f"You are conducting a software-requirements interview.\n\n"
            f"Project description: {state.get('project_description', 'not provided')}\n\n"
            f"Conversation so far ({turn_count} turns, max {max_turns}):\n"
            f"{transcript}\n\n"
            f"Estimated requirements identified so far: ~{heuristic_req_count}\n"
            f"Enough information gathered: {enough_info}\n\n"
            "Decide your next action:\n"
            "• If you need MORE information → use 'send_message' with ONE clear, "
            "open-ended question targeting an uncovered requirement area.\n"
            f"• If you have ENOUGH information → use 'write_interview_record'.\n"
            f"{write_record_instructions}\n"
            "• You may call 'search_knowledge' first to guide your next question.\n"
            "One action per turn. Be concise."
        )

        return self.react(state, task)
