from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tool abstraction
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Value returned by every tool function.

    observation   – text the agent sees after the tool call
    state_updates – partial WorkflowState dict to merge after this step
    should_return – if True the ReAct loop exits immediately after this tool
    is_error      – if True the loop aborts with a fatal-error message
    """
    observation:   str
    state_updates: Dict[str, Any] = field(default_factory=dict)
    should_return: bool           = False
    is_error:      bool           = False


class Tool:
    """A named callable available to an agent inside the ReAct loop."""

    def __init__(self, name: str, description: str, func: Callable[..., ToolResult]):
        self.name        = name
        self.description = description
        self._func       = func

    def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            return self._func(**kwargs)
        except Exception as exc:
            logger.exception("Tool '%s' raised: %s", self.name, exc)
            return ToolResult(
                observation=f"[Error in {self.name}]: {exc}",
                is_error=True,
                should_return=True,
            )

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

    Two public execution methods are available to subclasses:

    react()
        Run one full ReAct turn (bind_tools loop).  The model reasons over
        the task and decides which tool(s) to invoke.  Returns accumulated
        WorkflowState updates.

    extract_structured()
        Run a single deterministic LLM call (with_structured_output).  No
        tool routing, no loop — just one prompt → one validated Pydantic
        object.  Returns the parsed instance directly.
        Pass ``include_memory=False`` (default) for stateless extraction
        calls that do not need conversation history.
    """

    def __init__(self, name: str):
        self.name = name

        # ── Config ──────────────────────────────────────────────────────
        from ..config.config_manager import get_config
        raw_config       = get_config()
        self._raw_config = raw_config

        agent_section = raw_config.get("iredev", {}).get("agents", {}).get(name, {})
        llm_cfg       = raw_config.get("llm", {})

        # ── LLM ─────────────────────────────────────────────────────────
        from .llm.factory import LLMFactory
        self.llm = LLMFactory.create_llm(llm_cfg)

        # ── Module 1: Profile ────────────────────────────────────────────
        from ..profile.profile_module import ProfileModule
        self.profile = ProfileModule(f"prompts/{name}_react.txt")

        # ── Module 2: Memory ─────────────────────────────────────────────
        from ..memory.memory_module import MemoryModule
        from ..memory.types import MemoryType
        self.memory = MemoryModule(
            memory_type=MemoryType(str(agent_section.get("memory_type")))
        )

        # ── Module 3: Knowledge ──────────────────────────────────────────
        # Kept as a reference so subclasses can use it inside tool functions.
        self.knowledge = None
        try:
            from ..knowledge.knowledge_module import KnowledgeModule
            self.knowledge = KnowledgeModule.get_instance()
        except Exception as exc:
            logger.warning(
                "Agent '%s': knowledge module unavailable (%s). Skipping.", name, exc
            )

        # ── Module 4: Think (ReAct + structured extraction) ──────────────
        self.think: Optional[Any] = None
        try:
            from ..think.think_module import ThinkModule
            self.think = ThinkModule(llm=self.llm)
        except Exception as exc:
            logger.warning("Agent '%s': ThinkModule failed to init (%s).", name, exc)

        # ── Module 5: Action (ReAct config) ─────────────────────────────
        self.tools: Dict[str, Tool] = {}
        self.max_react_iterations: int = agent_section.get("max_react_iterations", 10)

        self._register_tools()
        logger.info("Agent '%s' ready | tools: %s", name, list(self.tools))

    # ── helpers ───────────────────────────────────────────────────────────

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    # ── ReAct entry point ─────────────────────────────────────────────────

    def react(
        self,
        state:            Dict[str, Any],
        task:             str,
        tool_choice:      Any = "auto",
        profile_addendum: str = "",
        include_memory:   bool = True,
    ) -> Dict[str, Any]:
        """Run one ReAct turn and return WorkflowState updates.

        Parameters
        ----------
        state:
            Current WorkflowState (read-only inside tool functions).
        task:
            Natural-language description of what to accomplish this turn.
        tool_choice:
            ``"auto"``, ``"required"``, or a specific tool dict.
        profile_addendum:
            Extra instructions appended to the base system prompt.
        include_memory:
            If ``True`` (default), prepend recent memory messages between the
            system prompt and the task.  Set to ``False`` for turns that do
            not need conversation history.
        """
        if self.think is None:
            logger.warning(
                "Agent '%s': ThinkModule unavailable — ReAct loop skipped.", self.name
            )
            return {}

        memory_messages: Optional[List[BaseMessage]] = None
        if include_memory:
            _memory_result = self.memory.take()
            # Guard against MemoryModule returning a (value, status) tuple
            # instead of a plain dict — AttributeError otherwise.
            if isinstance(_memory_result, tuple):
                _memory_result = _memory_result[0]
            if isinstance(_memory_result, dict):
                memory_messages = _memory_result.get("messages", [])

        final_profile = self.profile.prompt
        if profile_addendum:
            final_profile += f"\n\n{profile_addendum}"

        return self.think.run_react(
            task=task,
            tools_dict=self.tools,
            workflow_state=state,
            profile_prompt=final_profile,
            memory_messages=memory_messages,
            max_iterations=self.max_react_iterations,
            tool_choice=tool_choice,
        )

    # ── Structured extraction entry point ─────────────────────────────────

    def extract_structured(
        self,
        schema:          Type[BaseModel],
        system_prompt:   str,
        user_prompt:     str,
        include_memory:  bool = False,
    ) -> BaseModel:
        """Run a single structured-output LLM call and return a parsed object.

        This method bypasses the ReAct loop entirely.  It is the standard way
        to perform deterministic extraction tasks where the output schema is
        known in advance — no tool routing needed, no iterative reasoning.

        Parameters
        ----------
        schema:
            Pydantic ``BaseModel`` subclass defining the expected output shape.
        system_prompt:
            Extraction instructions for the LLM.
        user_prompt:
            The content to extract from (e.g. raw project description).
        include_memory:
            If ``True``, prepend recent memory messages to provide
            conversational context.  Defaults to ``False`` — most extraction
            calls are stateless and do not benefit from history.

        Returns
        -------
        BaseModel
            A validated instance of ``schema``.

        Raises
        ------
        RuntimeError
            If ThinkModule is unavailable.
        Exception
            Propagates any LLM or Pydantic validation error.
        """
        if self.think is None:
            raise RuntimeError(
                f"Agent '{self.name}': ThinkModule unavailable — "
                "cannot run extract_structured()."
            )

        memory_messages: Optional[List[BaseMessage]] = None
        if include_memory:
            _memory_result = self.memory.take()
            # Guard against MemoryModule returning a (value, status) tuple
            # instead of a plain dict — AttributeError otherwise.
            if isinstance(_memory_result, tuple):
                _memory_result = _memory_result[0]
            if isinstance(_memory_result, dict):
                memory_messages = _memory_result.get("messages", [])

        return self.think.run_structured(
            schema=schema,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory_messages=memory_messages,
        )

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