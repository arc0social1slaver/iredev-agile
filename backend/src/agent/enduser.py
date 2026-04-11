"""
enduser.py – EndUserAgent  (constrained stakeholder simulator)

Role
────
Simulate a realistic business stakeholder who responds to the interviewer.
The agent reads the latest interviewer question, consults its persona and
project knowledge, and posts a contextually appropriate reply.

Design constraints (enforced at multiple levels)
─────────────────────────────────────────────────
1. EndUserAgent CANNOT end the interview.  The 'respond' tool uses
   should_return=True to exit the agent's OWN ReAct loop, but it does NOT
   set interview_complete.  Only InterviewerAgent can set that flag.

2. The 4-layer behavioural constraints (Technical Language Wall, Local
   Disclosure Rule, Hesitation Mechanism, Emotional Authenticity) are
   enforced through:
     a) enduser_profile.txt   — base persona with constraints
     b) process() task string — per-turn constraint reminders derived from
                                 the specific question being answered
     c) Prompt engineering    — the format template in enduser_react.txt

3. Knowledge Base access is constrained: the 'search_knowledge' tool may be
   called at most once per turn.  This limit is enforced IN CODE via the
   '_sk_used_this_turn' flag in accumulated_updates (ThinkModule merges it
   into effective_state before every tool call).  The agent must not treat
   retrieved context as permission to dump all known facts — the Local
   Disclosure Rule still applies to retrieved knowledge.

ReAct tools
───────────
  search_knowledge – optional domain context lookup (max once per turn,
                     enforced in code — subsequent calls return a block message)
  respond          – post the stakeholder reply and exit the current turn
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


class EndUserAgent(BaseAgent):
    """Simulates a constrained business stakeholder in a requirements interview."""

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(name="enduser")

        agent_cfg      = self._raw_config.get("agents", {}).get("enduser", {})
        custom         = agent_cfg.get("custom_params", {})
        self._persona: str = custom.get("persona", "business stakeholder")

    # ── Tool registration ──────────────────────────────────────────────────

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="search_knowledge",
            description=(
                "Look up domain background or business context to help you answer "
                "more accurately.  Use at most ONCE per turn — this limit is enforced "
                "in code; a second call returns a block message and you must call "
                "'respond' immediately.\n"
                "Input: {\"query\": \"<what you need to know>\"}"
            ),
            func=self._tool_search_knowledge,
        ))
        self.register_tool(Tool(
            name="respond",
            description=(
                "Post your reply to the interviewer's question.  "
                "This ENDS your current turn.  Stay fully in character.\n"
                "Input: {\"message\": \"<your answer — 2-5 sentences, in character>\"}"
            ),
            func=self._tool_respond,
        ))

    # ── Tools ──────────────────────────────────────────────────────────────

    def _tool_search_knowledge(
        self, query: str, state: Dict = None, **_
    ) -> ToolResult:
        """Retrieve domain context from the knowledge base.

        Enforces the 'at most once per turn' rule in code using the
        '_sk_used_this_turn' flag in accumulated_updates.  ThinkModule merges
        accumulated_updates into effective_state before every tool call, so
        the flag is visible to this function on any subsequent call within
        the same ReAct loop.
        """
        # ── Hard enforcement: once per turn ────────────────────────────────
        if state and state.get("_sk_used_this_turn"):
            return ToolResult(
                observation=(
                    "[RULE VIOLATION] search_knowledge may only be called ONCE per turn. "
                    "You MUST call 'respond' now — no further searching is permitted."
                ),
                # No state_updates — flag stays True so any further call also blocks.
                # should_return=False so the loop continues and the agent can call respond.
            )

        # ── Perform the actual search ──────────────────────────────────────
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
        state:   Dict = None,
        **_,
    ) -> ToolResult:
        """Append the stakeholder's reply to the conversation and exit the turn.

        Note: should_return=True exits the EndUserAgent's ReAct loop only.
        It does NOT set interview_complete — that remains exclusively with
        InterviewerAgent._tool_write_interview_record.

        Resets '_sk_used_this_turn' so the next turn starts fresh.
        """
        if not message:
            logger.warning(
                "[EndUserAgent] respond called with empty message; using fallback."
            )
            message = "(I'm not sure I understood the question — could you rephrase?)"

        conversation = list(state.get("conversation") or [])
        conversation.append({
            "role":      "enduser",
            "content":   message,
            "timestamp": datetime.now().isoformat(),
        })
        turn_count = (state.get("turn_count") or 0) + 1

        logger.info("[Stakeholder → Interviewer] %s", message)
        self.memory.add(message, role="assistant")

        return ToolResult(
            observation="Response posted.",
            state_updates={
                "conversation":       conversation,
                "turn_count":         turn_count,
                "_sk_used_this_turn": False,   # reset for the next turn
            },
            should_return=True,   # exits OWN ReAct loop; does NOT end interview
        )

    # ── Constraint analysis helpers ────────────────────────────────────────

    @staticmethod
    def _detect_technical_terms(question: str) -> List[str]:
        """Flag technical terms in the interviewer's question for the agent."""
        technical_vocabulary = {
            "api", "apis", "rest", "restful", "graphql", "endpoint", "endpoints",
            "database", "db", "schema", "query", "sql", "nosql", "orm",
            "frontend", "backend", "server", "client", "microservice", "service",
            "framework", "library", "dependency", "package", "module",
            "cache", "caching", "latency", "throughput", "async", "sync",
            "webhook", "authentication", "oauth", "jwt", "token", "ssl", "tls",
            "deployment", "devops", "ci/cd", "docker", "kubernetes", "cloud",
            "state", "redux", "context", "component", "render", "hook",
            "repository", "repo", "git", "branch", "merge", "pipeline",
        }
        words   = set(question.lower().split())
        matches = [w for w in words if w in technical_vocabulary]
        return matches

    @staticmethod
    def _classify_question_type(question: str) -> str:
        """Classify the question to guide Layer 2 and Layer 3 application."""
        q_lower = question.lower()
        if any(w in q_lower for w in ("what if", "edge case", "error", "fail",
                                       "exception", "when something goes wrong",
                                       "corner case", "what happens if")):
            return "edge_case"  # → trigger Layer 3 Hesitation Mechanism
        if any(w in q_lower for w in ("all", "everything", "describe your",
                                       "tell me about", "overview")):
            return "broad"      # → trigger Layer 2 clarification request
        return "specific"       # → answer directly, honour Layer 2 scope limit

    # ── LangGraph node entry point ─────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph node entry point for EndUserAgent."""
        conversation = state.get("conversation") or []
        retry_hint = state.get("_enduser_retry_hint", "")

        # ── 1. SYNC NATIVE MEMORY FOR SIMULATED PERSONA ───────────────────
        self.memory.refresh()  # Clear short-term buffer from previous runs
        recent_turns = conversation[-8:] if conversation else []

        for turn in recent_turns:
            # REVERSE ROLES: For EndUser, its own messages are 'assistant', Interviewer is 'user'
            if turn.get("role") == "enduser":
                self.memory.add(turn["content"], role="assistant")
            else:
                self.memory.add(turn["content"], role="user")

        # ── 2. EXTRACT LATEST QUESTION TO ANSWER ──────────────────────────
        latest_question = "(none)"
        if conversation and conversation[-1].get("role") == "interviewer":
            latest_question = conversation[-1].get("content", "")

        # ── 3. REVISED TASK PROMPT ────────────────────────────────────────
        task = (
            "━━━━━━━━  PROJECT CONTEXT  ━━━━━━━━\n"
            f"{state.get('project_description', '(not provided)')}\n\n"
            "━━━━━━━━  LATEST QUESTION TO ANSWER  ━━━━━━━━\n"
            f"{latest_question}\n\n"
            "━━━━━━━━  INSTRUCTIONS  ━━━━━━━━\n"
            "Act as the stakeholder for this project. Answer the latest question naturally "
            "based on your persona. Provide specific pain points, goals, and constraints.\n\n"
            "CRITICAL RULES FOR STAKEHOLDER PERSONA:\n"
            "1. DO NOT brainstorm or invent long lists of features. You are a regular user/stakeholder, NOT a software architect or product manager.\n"
            "2. Keep your answers BRIEF and conversational (2 to 4 sentences maximum).\n"
            "3. Focus ONLY on your actual pain points and basic needs. Do NOT suggest advanced technical features (like AI chatbots, LMS integration, or Gamification) unless specifically asked.\n"
            "4. If the interviewer asks 'what additional features...', and your core needs are already met, simply say you don't have any more to add or that the current scope looks good enough for a first version.\n"
        )

        if retry_hint:
            task += f"\n[SYSTEM WARNING]: {retry_hint}\n"

        return self.react(state, task, tool_choice="required")