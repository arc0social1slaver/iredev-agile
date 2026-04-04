"""
think_module.py – ThinkModule: ReAct execution loop only.

RAG is no longer injected automatically.  Agents that need knowledge
context call the ``search_knowledge`` tool themselves during the loop.
Memory is serialised once and prepended to the system message so the
LLM sees the full conversation history inside its context window.

ReAct graph topology
────────────────────
    START → agent ──(has tool_calls)──→ tools
                 ╰──(no tool_calls)──→ END
            tools ──(should_return)──→ END
                  ╰──(continue)─────→ agent

Loop guard: LangGraph's built-in ``recursion_limit``.
Tool results with ``should_return=True`` trigger an immediate exit edge.
``state_updates`` from all tools are merged and returned to the caller.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from typing_extensions import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ReAct graph state
# ─────────────────────────────────────────────────────────────────────────────

def _add_messages(
    left: List[BaseMessage], right: List[BaseMessage]
) -> List[BaseMessage]:
    return list(left) + list(right)


class _ReactState(TypedDict):
    messages:            Annotated[List[BaseMessage], _add_messages]
    workflow_state:      Dict[str, Any]
    accumulated_updates: Dict[str, Any]
    should_return_early: bool


# ─────────────────────────────────────────────────────────────────────────────
# Helper: schema-only LangChain tool stub for LLM bind_tools
# ─────────────────────────────────────────────────────────────────────────────

def _make_schema_tool(tool: Any) -> StructuredTool:
    """Wrap a custom Tool as a schema-only StructuredTool for bind_tools.

    The stub is never invoked directly — actual execution happens inside
    the tools node using our Tool objects (which carry state_updates /
    should_return semantics that LangChain tools lack).
    """
    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", tool.name)
    ArgsModel: type[BaseModel] = type(
        f"_Args_{safe_name}",
        (BaseModel,),
        {"model_config": ConfigDict(extra="allow")},
    )

    def _noop(**kwargs: Any) -> str:
        return ""

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=ArgsModel,
        func=_noop,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ThinkModule
# ─────────────────────────────────────────────────────────────────────────────

class ThinkModule:
    """Per-agent reasoning layer: ReAct execution loop.

    Usage::

        state_updates = self.think.run_react(
            task=task,
            tools_dict=self.tools,
            workflow_state=state,
            profile_prompt=self.profile.prompt,
            memory_messages=self.memory.get_messages(),
            max_iterations=self.max_react_iterations,
        )
    """

    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm
        # Cache compiled graphs by frozenset of tool names.
        self._react_graph_cache: Dict[frozenset, Any] = {}

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def run_react(
        self,
        task:            str,
        tools_dict:      Dict[str, Any],
        workflow_state:  Dict[str, Any],
        profile_prompt:  str,
        memory_messages: Optional[List[BaseMessage]] = None,
        max_iterations:  int = 10,
    ) -> Dict[str, Any]:
        """Run one full ReAct turn and return merged WorkflowState updates.

        Steps
        ─────
        1. Build SystemMessage from profile + serialised memory history.
        2. Compile (or retrieve cached) ReAct graph for this tool-set.
        3. Invoke the graph; LangGraph's recursion_limit guards the loop.
        4. Return all accumulated state_updates from tool calls.

        Args:
            task:            Natural-language goal for this agent turn.
            tools_dict:      Mapping of tool name → Tool instance.
            workflow_state:  Current WorkflowState (read-only inside tools).
            profile_prompt:  Agent system prompt (profile).
            memory_messages: Full message history from MemoryModule.
                             Prepended to the conversation so the LLM has
                             complete context without any summarisation.
            max_iterations:  Upper bound on agent↔tools cycles.

        Returns:
            Dict of WorkflowState keys to update (merged from all tool calls).
        """
        # ── Build system message (profile + memory) ───────────────────────
        system_content = profile_prompt
        if memory_messages:
            history_text = "\n".join(
                f"[{'user' if isinstance(m, HumanMessage) else 'assistant'}] {m.content}"
                for m in memory_messages
                if isinstance(m, (HumanMessage, AIMessage))
            )
            if history_text:
                system_content = (
                    f"{profile_prompt}\n\n"
                    "## Conversation History\n"
                    f"{history_text}"
                )

        system_msg = SystemMessage(content=system_content)

        # ── Compile or retrieve cached graph ──────────────────────────────
        cache_key = frozenset(tools_dict.keys())
        if cache_key not in self._react_graph_cache:
            self._react_graph_cache[cache_key] = self._compile_react_graph(
                tools_dict
            )
        react_graph = self._react_graph_cache[cache_key]

        # ── Run graph ─────────────────────────────────────────────────────
        initial_state: _ReactState = {
            "messages":            [system_msg, HumanMessage(content=task)],
            "workflow_state":      workflow_state,
            "accumulated_updates": {},
            "should_return_early": False,
        }
        recursion_limit = max_iterations * 2 + 4

        try:
            result = react_graph.invoke(
                initial_state,
                config={"recursion_limit": recursion_limit},
            )
        except Exception as exc:
            if "recursion" in type(exc).__name__.lower() or "recursion" in str(exc).lower():
                logger.warning(
                    "[ThinkModule] Max iterations (%d) reached for task: %.80s",
                    max_iterations, task,
                )
                result = {"accumulated_updates": {}}
            else:
                raise

        updates = result.get("accumulated_updates", {})
        logger.debug(
            "[ThinkModule] finished — %d state key(s) updated.", len(updates)
        )
        return updates

    # ──────────────────────────────────────────────────────────────────────
    # ReAct graph construction
    # ──────────────────────────────────────────────────────────────────────

    def _compile_react_graph(self, tools_dict: Dict[str, Any]):
        """Build and compile the ReAct StateGraph for a given tool set.

        Graph topology::

            START → agent ──(has tool_calls)──→ tools
                         ╰──(no tool_calls)──→ END
                    tools ──(should_return)──→ END
                          ╰──(continue)─────→ agent
        """
        from langgraph.graph import END, StateGraph

        lc_stubs         = [_make_schema_tool(t) for t in tools_dict.values()]
        model_with_tools = self._llm.bind_tools(lc_stubs) if lc_stubs else self._llm

        # ── node: agent ───────────────────────────────────────────────────
        def agent_node(state: _ReactState) -> Dict[str, Any]:
            response = model_with_tools.invoke(state["messages"])
            return {"messages": [response]}

        # ── node: tools ───────────────────────────────────────────────────
        def tools_node(state: _ReactState) -> Dict[str, Any]:
            last_ai_msg = state["messages"][-1]
            tool_calls  = getattr(last_ai_msg, "tool_calls", None) or []

            tool_messages: List[ToolMessage] = []
            updates    = dict(state.get("accumulated_updates") or {})
            early_exit = bool(state.get("should_return_early", False))

            for tc in tool_calls:
                name    = tc["name"]
                args    = tc["args"]
                call_id = tc["id"]

                if name in tools_dict:
                    # Merge intra-turn updates so each tool sees state
                    # changes made by earlier tools in the same cycle.
                    effective_state = {**state["workflow_state"], **updates}
                    result = tools_dict[name](state=effective_state, **args)

                    updates.update(getattr(result, "state_updates", {}))
                    early_exit = early_exit or bool(
                        getattr(result, "should_return", False)
                    )
                    observation = result.observation
                else:
                    observation = (
                        f"[Tool Error] Unknown tool '{name}'. "
                        f"Available: {list(tools_dict)}. "
                        "Call one of the listed tools."
                    )

                tool_messages.append(
                    ToolMessage(
                        content=observation,
                        tool_call_id=call_id,
                        name=name,
                    )
                )

            return {
                "messages":            tool_messages,
                "accumulated_updates": updates,
                "should_return_early": early_exit,
            }

        # ── conditional edges ─────────────────────────────────────────────
        def route_after_agent(state: _ReactState) -> str:
            last = state["messages"][-1]
            return "tools" if getattr(last, "tool_calls", None) else END

        def route_after_tools(state: _ReactState) -> str:
            return END if state.get("should_return_early") else "agent"

        # ── assemble ──────────────────────────────────────────────────────
        g = StateGraph(_ReactState)
        g.add_node("agent", agent_node)
        g.add_node("tools", tools_node)
        g.set_entry_point("agent")
        g.add_conditional_edges(
            "agent", route_after_agent, {"tools": "tools", END: END}
        )
        g.add_conditional_edges(
            "tools", route_after_tools, {"agent": "agent", END: END}
        )

        compiled = g.compile()
        logger.debug(
            "[ThinkModule] compiled ReAct graph for tools: %s", list(tools_dict)
        )
        return compiled