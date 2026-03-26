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
from langchain_core.messages import HumanMessage
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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

        # ── LLM ─────────────────────────────────────────────────
        from .llm.factory import LLMFactory

        cfg_path = config_path or "config/agent_config.yaml"
        raw_config = LLMFactory.load_config(cfg_path)
        self._raw_config = raw_config

        agent_section = (
            raw_config.get("agents", {}).get(name)
            or raw_config.get("iredev", {}).get("agents", {}).get(name)
            or {}
        )
        llm_cfg = raw_config.get("agent_llms", {}).get(name) or raw_config.get(
            "llm", {}
        )

        self.llm = LLMFactory.create_llm(llm_cfg)

        self.llm_params = {
            "temperature": llm_cfg.get("temperature", 0.7),
            "max_tokens": llm_cfg.get("max_tokens", 4096),
        }

        # ── Module 1: Profile ─────────────────────────────────────────────
        from ..profile.profile_module import ProfileModule

        prompt_path = agent_section.get(
            "profile_prompt_path", f"prompts/{name}_profile.txt"
        )
        self.profile = ProfileModule(prompt_path)

        # ── Module 2: Memory ──────────────────────────────────────────────
        from ..memory.memory_module import MemoryModule
        from ..memory.types import MemoryType

        self.memory = MemoryModule(
            memory_type=MemoryType.SHORT_TERM,
            system_prompt=self.profile.prompt,
        )

        # ── Module 3: Knowledge ───────────────────────────────────────────
        self.knowledge = None
        try:
            from ..knowledge.knowledge_module import KnowledgeModule

            self.knowledge = KnowledgeModule.get_instance()
        except Exception as exc:
            logger.warning(
                "Agent '%s': knowledge module unavailable (%s). Skipping.", name, exc
            )

        # ── Module 4: Think ───────────────────────────────────────────────
        self.think = None
        if self.knowledge is not None:
            try:
                from ..think.think_module import ThinkModule

                self.think = ThinkModule(knowledge=self.knowledge, llm=self.llm)
            except Exception as exc:
                logger.warning(
                    "Agent '%s': ThinkModule failed to init (%s).", name, exc
                )

        # ── Module 6: Action (ReAct) ──────────────────────────────────────
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

    # ── ReAct core ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_react_output(text: str):
        """Return (thought, action, action_input_dict) from raw LLM output."""
        thought_m = re.search(r"Thought:\s*(.*?)(?=\nAction:|\Z)", text, re.DOTALL)
        action_m = re.search(r"Action:\s*(\S+)", text)
        input_m = re.search(r"Action Input:\s*(\{.*?\})", text, re.DOTALL)

        thought = thought_m.group(1).strip() if thought_m else ""
        action = action_m.group(1).strip() if action_m else "FINISH"
        try:
            action_input = json.loads(input_m.group(1)) if input_m else {}
        except json.JSONDecodeError:
            action_input = {}
        return thought, action, action_input

    def _call_llm(self, prompt: str) -> str:
        """Calls the LangChain chat model with the formatted prompt."""
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
                    # e.g. {"type": "text", "text": "..."} or {"type": "thinking", ...}
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
        """
        Run the ReAct loop for one agent turn.

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

            if action not in self.tools:
                obs = f"Unknown tool '{action}'. Available: {list(self.tools)}"
                scratchpad.append(f"Action: {action}")
                scratchpad.append(f"Observation: {obs}")
                continue

            # Merge accumulated updates into a view of state for the tool
            tool_state = {**state, **state_updates}
            result: ToolResult = self.tools[action](state=tool_state, **action_input)

            scratchpad.append(f"Action: {action}")
            scratchpad.append(f"Action Input: {json.dumps(action_input)}")
            scratchpad.append(f"Observation: {result.observation}")

            # Persist step in short-term memory
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

    # ── abstract interface ─────────────────────────────────────────────────

    @abstractmethod
    def _register_tools(self) -> None:
        """Populate self.tools.  Called once at the end of __init__."""

    @abstractmethod
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        LangGraph node entry point.

        Receives the current WorkflowState, returns a partial dict of
        state keys to update.
        """
