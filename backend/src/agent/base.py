"""
base.py – BaseAgent with six modules; the ReAct loop lives in ThinkModule.

Six modules
───────────
1. Profile   ProfileModule       – system prompt loaded from a file
2. Memory    MemoryModule        – short-term conversation buffer
3. Knowledge KnowledgeModule     – pgvector knowledge retrieval (singleton)
4. Think     ThinkModule         – Memory-First RAG  +  ReAct execution loop
5. LLM       BaseLLM             – language-model from LLMFactory
6. Action    react()             – thin shim; delegates to ThinkModule.run_react()
             + per-agent tools registered via _register_tools()

The ``process(state)`` method is the LangGraph node entry point.
Subclasses implement ``_register_tools()`` and ``process()``.

ReAct design (owned by ThinkModule)
────────────────────────────────────
  • LangGraph StateGraph with two nodes: ``agent`` (LLM) and ``tools``
    (custom executor that understands ToolResult semantics).
  • Loop control via LangGraph's built-in ``recursion_limit`` — no manual
    counter or regex-based output parsing needed.
  • Knowledge context injected once per turn via the Memory-First RAG graph
    before the first ``agent`` call.
  • ``ToolResult.state_updates`` are merged across all tool calls and returned
    as the dict that LangGraph merges into WorkflowState.
  • ``ToolResult.should_return = True`` triggers an immediate conditional-edge
    exit from the ReAct graph.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tool abstraction  (unchanged — subclasses register tools via these classes)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ToolResult:
    """Value returned by every tool function.

    observation   – text the agent sees after the tool call
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


# ─────────────────────────────────────────────────────────────────────────────
# BaseAgent
# ─────────────────────────────────────────────────────────────────────────────


class BaseAgent(ABC):
    """Abstract base for all iReDev agents.

    Subclasses must implement:
      _register_tools() – populate self.tools with Tool instances
      process(state)     – top-level LangGraph node entry point
    """

    def __init__(self, name: str):
        self.name = name

        # ── Config ──────────────────────────────────────────────────────
        from ..config.config_manager import get_config

        raw_config = get_config()
        self._raw_config = raw_config

        agent_section = raw_config.get("iredev", {}).get("agents", {}).get(name, {})

        llm_cfg = raw_config.get("llm", {})

        # ── LLM ─────────────────────────────────────────────────────────
        from .llm.factory import LLMFactory

        self.llm = LLMFactory.create_llm(llm_cfg)

        # ── Module 1: Profile ────────────────────────────────────────────
        from ..profile.profile_module import ProfileModule

        self.profile = ProfileModule(f"prompts/{name}_profile.txt")

        # ── Module 2: Memory ─────────────────────────────────────────────
        from ..memory.memory_module import MemoryModule
        from ..memory.types import MemoryType

        self.memory = MemoryModule(
            memory_type=MemoryType(str(agent_section.get("memory_type"))),
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

        # ── Module 4: Think (RAG + ReAct) ────────────────────────────────
        self.think: Optional[Any] = None

        try:
            from ..think.think_module import ThinkModule

            self.think = ThinkModule(knowledge=self.knowledge, llm=self.llm)
        except Exception as exc:
            logger.warning("Agent '%s': ThinkModule failed to init (%s).", name, exc)

        # ── Module 6: Action (ReAct config) ─────────────────────────────
        self.tools: Dict[str, Tool] = {}
        self.max_react_iterations: int = agent_section.get("max_react_iterations", 10)

        self._register_tools()
        logger.info("Agent '%s' ready | tools: %s", name, list(self.tools))

    # ── helpers ───────────────────────────────────────────────────────────

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    # ── ReAct entry point ─────────────────────────────────────────────────

    def react(self, state: Dict[str, Any], task: str) -> Dict[str, Any]:
        """Run one ReAct turn and return WorkflowState updates.

        All loop logic, LLM calls, tool dispatching, loop-guard, and knowledge
        injection are handled by ``ThinkModule.run_react()``.  This method is a
        thin shim that collects the required inputs and merges memory afterwards.

        Parameters
        ----------
        state : current WorkflowState (read-only inside tool functions)
        task  : natural-language description of what to accomplish this turn

        Returns
        -------
        dict of WorkflowState keys to update (merged by LangGraph)
        """
        if self.think is None:
            logger.warning(
                "Agent '%s': ThinkModule unavailable — ReAct loop skipped.", self.name
            )
            return {}

        state_updates = self.think.run_react(
            task=task,
            tools_dict=self.tools,
            workflow_state=state,
            profile_prompt=self.profile.prompt,
            memory_context=self.memory.take(),
            max_iterations=self.max_react_iterations,
        )

        # Record the completed turn in the agent's memory buffer so that
        # subsequent turns (and the ThinkModule's decide node) have context.
        self.memory.add(
            f"Task: {task}\nCompleted with {len(state_updates)} state update(s).",
            role="assistant",
        )

        return state_updates

    # ── abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def _register_tools(self) -> None:
        """Populate self.tools. Called once at the end of __init__."""

    @abstractmethod
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph node entry point.

        Receives the current WorkflowState, returns a partial dict of
        state keys to update.
        """
