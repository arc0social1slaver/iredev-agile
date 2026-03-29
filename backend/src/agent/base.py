"""
base.py – BaseAgent with six modules and a generic ReAct loop.

Six modules
───────────
1. Profile   ProfileModule       – system prompt loaded from a file
2. Memory    MemoryModule        – short-term conversation buffer
3. Knowledge KnowledgeModule     – pgvector knowledge retrieval (singleton)
4. Think     ThinkModule         – memory-first RAG reasoning graph
5. LLM       BaseLLM             – language-model from LLMFactory
6. Action    ReAct loop          – generic tool-calling loop (this file)
             + per-agent tools registered via _register_tools()

The ``process(state)`` method is the LangGraph node entry point.
Subclasses implement ``_register_tools()`` and ``process()``.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool abstraction
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """
    Value returned by every tool function.

    observation   – text the agent sees in the ReAct scratchpad
    state_updates – partial WorkflowState dict to merge after this step
    should_return – if True the ReAct loop exits immediately after this tool
    """

    observation: str
    state_updates: Dict[str, Any] = field(default_factory=dict)
    should_return: bool = False


class Tool:
    """A named callable available to an agent inside the ReAct loop."""

    def __init__(self, name: str, description: str, func: Callable[..., ToolResult]):
        self.name = name
        self.description = description
        self._func = func

    def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            return self._func(**kwargs)
        except Exception as exc:
            logger.exception("Tool '%s' raised: %s", self.name, exc)
            return ToolResult(observation=f"[Error in {self.name}]: {exc}")

    def describe(self) -> str:
        return f"  {self.name}: {self.description}"


# ---------------------------------------------------------------------------
# Default ReAct prompt (used when the file is missing)
# ---------------------------------------------------------------------------

_DEFAULT_REACT_PROMPT = """\
{profile}

## Available Tools
{tools}

## Your Task
{task}

## Prior Context
{memory}

---
Reply with EXACTLY this format – one step at a time:

Thought: <your reasoning>
Action: <tool_name>
Action Input: <valid JSON object>

When finished:

Thought: <summary>
Action: FINISH
Action Input: {{}}
"""


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------


class BaseAgent(ABC):
    """
    Abstract base for all iReDev agents.

    Subclasses must implement:
      _register_tools() – populate self.tools with Tool instances
      process(state)     – top-level LangGraph node entry point
    """

    def __init__(self, name: str, config_path: Optional[str] = None):
        self.name = name

        # ── Config ──────────────────────────────────────────────────────
        # All config loading goes through ConfigManager so that ${ENV_VAR}
        # placeholders are expanded consistently and .env is loaded first.
        from ..config.config_manager import get_config_manager, get_raw
        from .llm.factory import LLMFactory

        cfg_path = config_path or "config/agent_config.yaml"

        # Initialise the singleton with the explicit path (no-op if already
        # set to the same path).
        get_config_manager(cfg_path)

        raw_config = get_raw(cfg_path)
        self._raw_config = raw_config

        agent_section = (
            raw_config.get("agents", {}).get(name)
            or raw_config.get("iredev", {}).get("agents", {}).get(name)
            or {}
        )
        llm_cfg = raw_config.get("agent_llms", {}).get(name) or raw_config.get(
            "llm", {}
        )

        # ── LLM ─────────────────────────────────────────────────────────
        self.llm = LLMFactory.create_llm(llm_cfg)

        self.llm_params = {
            "temperature": llm_cfg.get("temperature", 0.7),
            "max_tokens": llm_cfg.get("max_tokens", 4096),
        }

        # ── Module 1: Profile ────────────────────────────────────────────
        from ..profile.profile_module import ProfileModule

        prompt_path = agent_section.get(
            "profile_prompt_path", f"prompts/{name}_profile.txt"
        )
        self.profile = ProfileModule(prompt_path)

        # ── Module 2: Memory ─────────────────────────────────────────────
        from ..memory.memory_module import MemoryModule
        from ..memory.types import MemoryType

        self.memory = MemoryModule(
            memory_type=MemoryType.SHORT_TERM,
            system_prompt=self.profile.prompt,
        )

        # ── Module 3: Knowledge ──────────────────────────────────────────
        self.knowledge = None
        try:
            from ..knowledge.knowledge_module import KnowledgeModule

            self.knowledge = KnowledgeModule.get_instance()
        except Exception as exc:
            logger.warning(
                "Agent '%s': knowledge module unavailable (%s). Skipping.", name, exc
            )

        # ── Module 4: Think ──────────────────────────────────────────────
        self.think = None
        if self.knowledge is not None:
            try:
                from ..think.think_module import ThinkModule

                self.think = ThinkModule(knowledge=self.knowledge, llm=self.llm)
            except Exception as exc:
                logger.warning(
                    "Agent '%s': ThinkModule failed to init (%s).", name, exc
                )

        # ── Module 6: Action (ReAct) ─────────────────────────────────────
        self.tools: Dict[str, Tool] = {}
        self.max_react_iterations: int = agent_section.get("max_react_iterations", 10)

        react_prompt_path = agent_section.get(
            "react_prompt_path", f"prompts/{name}_react.txt"
        )
        self._react_template = self._load_text(react_prompt_path, _DEFAULT_REACT_PROMPT)

        self._register_tools()
        logger.info("Agent '%s' ready | tools: %s", name, list(self.tools))

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _load_text(path: str, default: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.debug("File not found '%s', using built-in default.", path)
            return default

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def _tools_text(self) -> str:
        return "\n".join(t.describe() for t in self.tools.values())

    # ── ReAct core ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_react_output(text: str):
        """Parse raw LLM ReAct output into (thought, action, action_input).

        Uses brace-depth counting instead of a non-greedy regex so that
        arbitrarily nested JSON objects and arrays are captured correctly.
        A non-greedy r'{.*?}' stops at the first closing brace, which silently
        truncates inputs like {"extracted": [{...}, {...}]}.
        """
        thought_m = re.search(r"Thought:\s*(.*?)(?=\nAction:|\Z)", text, re.DOTALL)
        action_m = re.search(r"Action:\s*(\S+)", text)

        thought = thought_m.group(1).strip() if thought_m else ""
        action = action_m.group(1).strip() if action_m else "FINISH"

        action_input: Dict[str, Any] = {}
        ai_pos = re.search(r"Action Input:\s*", text)
        if ai_pos:
            start = ai_pos.end()
            # Skip any leading whitespace / newlines before the opening brace
            while start < len(text) and text[start] in " \t\n\r":
                start += 1
            if start < len(text) and text[start] == "{":
                depth, end = 0, start
                for i in range(start, len(text)):
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                try:
                    action_input = json.loads(text[start:end])
                except json.JSONDecodeError:
                    action_input = {}

        return thought, action, action_input

    def _call_llm(self, prompt: str) -> str:
        """Call the LangChain chat model with the formatted prompt."""
        messages = [HumanMessage(content=prompt)]
        response = self.llm.invoke(messages)
        content = response.content

        # Normalize: some providers (e.g. Gemini) return a list of content blocks
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    parts.append(block.get("text") or block.get("thinking") or "")
            content = "".join(parts)

        return content

    def _get_knowledge_context(self, task: str) -> str:
        """Try to get knowledge-augmented context via ThinkModule."""
        if self.think is None:
            return ""
        try:
            from ..orchestrator.state import ProcessPhase

            return self.think.build_prompt_context(
                query=task,
                phase=ProcessPhase.ELICITATION,
                memory_context=self.memory.take(),
            )
        except Exception as exc:
            logger.warning("ThinkModule error for '%s': %s", self.name, exc)
            return ""

    def react(self, state: Dict[str, Any], task: str) -> Dict[str, Any]:
        """Run the ReAct loop for one agent turn.

        Parameters
        ----------
        state : current WorkflowState (read-only inside tools)
        task  : natural-language description of what to accomplish this turn

        Returns
        -------
        dict of WorkflowState keys to update (merged by LangGraph)
        """
        knowledge_ctx = self._get_knowledge_context(task)
        memory_ctx = "\n".join(
            f"{m.type.upper()}: {m.content}"
            for m in (self.memory.take().get("messages") or [])
            if getattr(m, "type", "") != "system"
        )

        prompt = self._react_template.format(
            profile=self.profile.prompt,
            tools=self._tools_text(),
            task=task,
            memory=memory_ctx or "(no prior context)",
        )
        if knowledge_ctx:
            prompt += f"\n\n## Relevant Knowledge\n{knowledge_ctx}"

        scratchpad: List[str] = []
        state_updates: Dict[str, Any] = {}

        # Track how many times each (action, message) pair has been emitted
        # to detect infinite loops before they exhaust max_react_iterations.
        action_repeat_counts: Dict[str, int] = {}

        for step in range(self.max_react_iterations):
            full_prompt = prompt + (
                "\n\n" + "\n".join(scratchpad) if scratchpad else ""
            )

            raw_output = self._call_llm(full_prompt)
            thought, action, action_input = self._parse_react_output(raw_output)

            scratchpad.append(f"Thought: {thought}")

            if action == "FINISH":
                logger.debug("[%s] ReAct FINISH at step %d.", self.name, step + 1)
                break

            # ── Loop detection ────────────────────────────────────────────
            # Build a short fingerprint from the action and the first 80 chars
            # of its most meaningful input field so that minor LLM paraphrasing
            # does not mask a genuine repeat.
            _msg_field = (
                action_input.get("message")
                or action_input.get("query")
                or str(action_input)
            )
            loop_key = f"{action}::{str(_msg_field)[:80]}"
            action_repeat_counts[loop_key] = action_repeat_counts.get(loop_key, 0) + 1

            if action_repeat_counts[loop_key] >= 3:
                logger.warning(
                    "[%s] Loop detected: action='%s' repeated %d times at step %d. "
                    "Breaking ReAct loop to prevent infinite cycle.",
                    self.name,
                    action,
                    action_repeat_counts[loop_key],
                    step + 1,
                )
                # Append a visible hint to the scratchpad so the next LLM call
                # (if any) is aware that this path was already exhausted.
                scratchpad.append(
                    f"Observation: [LOOP GUARD] Action '{action}' with the same "
                    "input has been repeated 3 times without progress. "
                    "You MUST choose a different action or call FINISH."
                )
                break
            # ─────────────────────────────────────────────────────────────

            if action not in self.tools:
                obs = f"Unknown tool '{action}'. Available: {list(self.tools)}"
                scratchpad.append(f"Action: {action}")
                scratchpad.append(f"Observation: {obs}")
                continue

            tool_state = {**state, **state_updates}
            result: ToolResult = self.tools[action](state=tool_state, **action_input)

            scratchpad.append(f"Action: {action}")
            scratchpad.append(f"Action Input: {json.dumps(action_input)}")
            scratchpad.append(f"Observation: {result.observation}")

            self.memory.add(
                f"Thought: {thought}\nAction: {action}\nObs: {result.observation}",
                role="assistant",
            )

            state_updates.update(result.state_updates)

            if result.should_return:
                logger.debug(
                    "[%s] Tool '%s' triggered early return.", self.name, action
                )
                break

        return state_updates

    # ── abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def _register_tools(self) -> None:
        """Populate self.tools. Called once at the end of __init__."""

    @abstractmethod
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        LangGraph node entry point.

        Receives the current WorkflowState, returns a partial dict of
        state keys to update.
        """
