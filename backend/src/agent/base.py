from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Memory format guard
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_lc_messages(messages: Any) -> List[BaseMessage]:
    """Convert any message format to a list of LangChain BaseMessage objects.

    MemoryModule implementations differ: some return proper BaseMessage objects,
    others return plain dicts ({"role": "user"|"assistant", "content": "..."})
    or LangChain serialised dicts ({"type": "human", "content": "..."}).
    This guard normalises all of them so ThinkModule.run_react() always receives
    proper BaseMessage instances — the only format .invoke() / bind_tools() accept.
    """
    if not messages:
        return []

    result: List[BaseMessage] = []
    for m in messages:
        if isinstance(m, BaseMessage):
            result.append(m)
            continue
        if not isinstance(m, dict):
            # Fallback: stringify unknown objects
            result.append(HumanMessage(content=str(m)))
            continue

        # Handle both {"role": ..., "content": ...} and {"type": ..., "content": ...}
        role    = m.get("role") or m.get("type") or "user"
        content = m.get("content", "")
        if role in ("user", "human"):
            result.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            result.append(AIMessage(content=content))
        elif role == "system":
            result.append(SystemMessage(content=content))
        else:
            result.append(HumanMessage(content=content))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Tool abstraction
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Value returned by every tool function.

    observation   – text the agent sees after the tool call
    state_updates – partial WorkflowState dict to merge after this step
    should_return – if True the ReAct loop exits immediately after this tool
    """
    observation:   str
    state_updates: Dict[str, Any] = field(default_factory=dict)
    should_return: bool           = False
    is_error: bool = False


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
        self.memory = MemoryModule(memory_type=MemoryType(str(agent_section.get("memory_type"))))

        # ── Module 3: Knowledge ──────────────────────────────────────────
        self.knowledge = None
        try:
            from ..knowledge.knowledge_module import KnowledgeModule
            self.knowledge = KnowledgeModule.get_instance()
        except Exception as exc:
            logger.warning(
                "Agent '%s': knowledge module unavailable (%s). Skipping.", name, exc
            )

        # ── Module 4: Think (ReAct) ──────────────────────────────────────
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
            state: Dict[str, Any],
            task: str,
            tool_choice: Any = "auto",
            profile_addendum: str = ""
    ) -> Dict[str, Any]:
        """Run one ReAct turn and return WorkflowState updates.

        Parameters
        ----------
        state            : current WorkflowState (read-only inside tool functions)
        task             : natural-language description of what to accomplish this turn
        tool_choice      : 'auto', 'required', or a specific tool dict (enforce tool usage)
        profile_addendum : Extra instructions to append to the base profile prompt

        Memory format fix
        -----------------
        Calls _ensure_lc_messages() on the raw memory output so that any format
        (dict, serialised dict, or proper BaseMessage) is normalised to LangChain
        BaseMessage objects before being passed to ThinkModule.
        """
        if self.think is None:
            logger.warning(
                "Agent '%s': ThinkModule unavailable — ReAct loop skipped.", self.name
            )
            return {}

        # 1. Retrieve message history and normalise to LangChain format.
        raw_memory      = self.memory.take().get("messages", [])
        memory_messages = _ensure_lc_messages(raw_memory)

        # 2. Combine base prompt with any agent-specific addendum.
        final_profile = self.profile.prompt
        if profile_addendum:
            final_profile += f"\n\n{profile_addendum}"

        # 3. Run ThinkModule.
        state_updates = self.think.run_react(
            task=task,
            tools_dict=self.tools,
            workflow_state=state,
            profile_prompt=final_profile,
            memory_messages=memory_messages,
            max_iterations=self.max_react_iterations,
            tool_choice=tool_choice,
        )

        return state_updates

    # ── abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def _register_tools(self) -> None:
        """Populate self.tools. Called once at the end of __init__."""

    @abstractmethod
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """LangGraph node entry point."""