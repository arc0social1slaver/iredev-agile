"""
think_module.py – ThinkModule: ReAct execution loop + structured extraction.

Two public mechanisms
─────────────────────
1. run_react()       – Full ReAct loop (bind_tools).  Use for agentic turns
                       where the model must reason and decide which tool to call.

2. run_structured()  – Single deterministic LLM call (with_structured_output).
                       Use for extraction tasks where the output schema is known
                       in advance and no tool-selection reasoning is needed.

Both methods accept ``memory_messages`` as an optional parameter.  Pass ``None``
(or omit) to skip memory injection — useful for stateless extraction calls that
do not need conversation history.

Strategy Factorization support
───────────────────────────────
Agents (primarily InterviewerAgent) embed a [STRATEGY]...[/STRATEGY] block
inside their Thought text before any tool call.  The tools_node extracts this
block and stores it as ``_react_strategy`` in accumulated_updates so that tool
implementations (e.g. update_requirements) can attach it as rationale to every
artifact they produce.

The rationale chain therefore looks like:
  LLM Thought → [STRATEGY] block → _react_strategy in state →
  update_requirements reads it → stored in requirement["rationale"] →
  surfaced in HITL review payload → recorded in history on every HITL edit.

ReAct graph topology
────────────────────
    START → agent ──(has tool_calls)──→ tools
                 ╰──(no tool_calls)──→ END
            tools ──(should_return)──→ END
                  ╰──(continue)─────→ agent

tool_choice support
───────────────────
Pass ``tool_choice`` to ``run_react()`` to force the LLM to call a specific
tool or any tool:

  "required"               – model MUST call at least one tool (any tool)
  "auto"                   – model chooses freely (default)
  {"name": "<tool_name>"}  – model MUST call this specific tool
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from typing_extensions import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, create_model
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

ToolChoice = Union[str, Dict[str, str], None]

# ── Strategy block regex ──────────────────────────────────────────────────────
_STRATEGY_RE = re.compile(r"\[STRATEGY\](.*?)\[/STRATEGY\]", re.DOTALL | re.IGNORECASE)


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
# Schema-only LangChain tool stub (for bind_tools)
# ─────────────────────────────────────────────────────────────────────────────

def _make_schema_tool(tool: Any) -> StructuredTool:
    """Wrap a custom Tool as a schema-only StructuredTool for bind_tools.

    The stub is never invoked directly — actual execution happens inside the
    tools node using our Tool objects, which carry state_updates / should_return
    semantics that LangChain StructuredTools lack.
    """
    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", tool.name)
    ArgsModel = create_model(
        f"_Args_{safe_name}",
        __base__=BaseModel,
        __config__=ConfigDict(extra="allow"),
    )

    def _noop(**kwargs: Any) -> str:
        return ""

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=ArgsModel,
        func=_noop,
    )


def _tc_cache_key(tool_choice: ToolChoice) -> str:
    if tool_choice is None or tool_choice == "auto":
        return "auto"
    if isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, dict):
        return f"fn:{tool_choice.get('name', '')}"
    return str(tool_choice)


# ─────────────────────────────────────────────────────────────────────────────
# ThinkModule
# ─────────────────────────────────────────────────────────────────────────────

class ThinkModule:
    """Per-agent reasoning layer: ReAct loop (bind_tools) + structured extraction.

    Two public methods
    ──────────────────
    ``run_react()``
        Full agentic ReAct loop.  The model reasons over the task and decides
        which tool(s) to call.  All tool results are merged into a single
        state-update dict that is returned to the caller.

    ``run_structured()``
        Single deterministic LLM call using ``with_structured_output``.
        No tool routing, no loop — just one prompt → one validated object.
        Returns the parsed Pydantic instance directly.

    Both methods accept an optional ``memory_messages`` list.  Pass ``None``
    to skip memory injection entirely (e.g. for stateless extraction calls).

    Strategy Factorization
    ──────────────────────
    When an agent's Thought contains a [STRATEGY]...[/STRATEGY] block the
    block is extracted and stored under ``_react_strategy`` in
    accumulated_updates before any tool in the same step is called.  Tool
    implementations read ``state.get("_react_strategy")`` to attach the
    reasoning to the artifacts they produce.
    """

    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm
        self._react_graph_cache: Dict[Tuple[frozenset, str], Any] = {}

    # ── Public API: ReAct loop ─────────────────────────────────────────────

    def run_react(
        self,
        task:            str,
        tools_dict:      Dict[str, Any],
        workflow_state:  Dict[str, Any],
        profile_prompt:  str,
        memory_messages: Optional[List[BaseMessage]] = None,
        max_iterations:  int = 10,
        tool_choice:     ToolChoice = None,
    ) -> Dict[str, Any]:
        """Run the ReAct loop and return accumulated WorkflowState updates.

        Parameters
        ----------
        task:
            Natural-language description of what to accomplish this turn.
        tools_dict:
            Mapping of tool name → Tool instance available for this turn.
        workflow_state:
            Current read-only WorkflowState passed into every tool call.
        profile_prompt:
            System prompt (base profile ± addendum).
        memory_messages:
            Recent conversation messages prepended after the system prompt.
            Pass ``None`` to skip memory injection.
        max_iterations:
            Maximum number of agent↔tools round-trips before aborting.
        tool_choice:
            ``"auto"`` (default), ``"required"``, or ``{"name": "<tool>"}``
            to force a specific tool on the first step.
        """
        system_msg = SystemMessage(content=profile_prompt)
        recent     = (memory_messages or [])[-20:]
        messages   = [system_msg] + recent + [HumanMessage(content=task)]

        tc_key    = _tc_cache_key(tool_choice)
        cache_key = (frozenset(tools_dict.keys()), tc_key)
        if cache_key not in self._react_graph_cache:
            self._react_graph_cache[cache_key] = self._compile_react_graph(
                tools_dict, tool_choice=tool_choice
            )
        react_graph = self._react_graph_cache[cache_key]

        initial_state: _ReactState = {
            "messages":            messages,
            "workflow_state":      workflow_state,
            "accumulated_updates": {},
            "should_return_early": False,
        }

        STEPS_PER_ITERATION = 2
        OVERHEAD_STEPS      = 4
        recursion_limit     = max_iterations * STEPS_PER_ITERATION + OVERHEAD_STEPS

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
        logger.debug("[ThinkModule] run_react finished — %d state key(s) updated.", len(updates))
        return updates

    # ── Public API: structured extraction ─────────────────────────────────

    def run_structured(
        self,
        schema:          Type[BaseModel],
        system_prompt:   str,
        user_prompt:     str,
        memory_messages: Optional[List[BaseMessage]] = None,
    ) -> BaseModel:
        """Run a single structured-output LLM call and return a parsed object.

        This method deliberately bypasses the ReAct loop.  It creates a
        fresh ``with_structured_output`` chain on top of the base LLM — no
        ``bind_tools`` involved — so there is zero conflict with the ReAct
        mechanism.

        Parameters
        ----------
        schema:
            A Pydantic ``BaseModel`` subclass that defines the expected output.
            The LLM is constrained to produce JSON matching this schema.
        system_prompt:
            Instructions that describe the extraction task.
        user_prompt:
            The content to extract from (e.g. project description).
        memory_messages:
            Optional recent messages prepended between the system and user
            prompts.  Pass ``None`` (default) to omit — most extraction
            calls are stateless and do not need history.

        Returns
        -------
        BaseModel
            A validated instance of ``schema``.

        Raises
        ------
        Exception
            Propagates any LLM or validation error to the caller so that the
            tool function can decide how to handle it.
        """
        structured_llm = self._llm.with_structured_output(schema)

        recent: List[BaseMessage] = (memory_messages or [])[-20:]
        messages: List[BaseMessage] = (
            [SystemMessage(content=system_prompt)]
            + recent
            + [HumanMessage(content=user_prompt)]
        )

        result = structured_llm.invoke(messages)
        logger.debug(
            "[ThinkModule] run_structured finished — schema=%s", schema.__name__
        )
        return result

    # ── ReAct graph construction ───────────────────────────────────────────

    def _compile_react_graph(
        self,
        tools_dict:  Dict[str, Any],
        tool_choice: ToolChoice = None,
    ):
        lc_stubs = [_make_schema_tool(t) for t in tools_dict.values()]

        if lc_stubs:
            bind_kwargs: Dict[str, Any] = {"parallel_tool_calls": False}
            if tool_choice is not None and tool_choice != "auto":
                bind_kwargs["tool_choice"] = tool_choice
            model_with_tools = self._llm.bind_tools(lc_stubs, **bind_kwargs)
        else:
            model_with_tools = self._llm

        # ── node: agent ──────────────────────────────────────────────────
        def agent_node(state: _ReactState) -> Dict[str, Any]:
            response = model_with_tools.invoke(state["messages"])
            return {"messages": [response]}

        # ── node: tools ──────────────────────────────────────────────────
        def tools_node(state: _ReactState) -> Dict[str, Any]:
            last_ai_msg = state["messages"][-1]
            tool_calls  = getattr(last_ai_msg, "tool_calls", None) or []

            tool_messages: List[ToolMessage] = []
            updates    = dict(state.get("accumulated_updates") or {})
            early_exit = bool(state.get("should_return_early", False))

            # ── Strategy Factorization: extract [STRATEGY] block ─────────
            # Must happen BEFORE the tool loop so that every tool called in
            # this step can read _react_strategy via effective_state.
            ai_thought = getattr(last_ai_msg, "content", "") or ""
            if ai_thought:
                updates["_last_react_thought"] = ai_thought
                m = _STRATEGY_RE.search(ai_thought)
                if m:
                    updates["_react_strategy"] = m.group(1).strip()
                    logger.debug(
                        "[ThinkModule] [STRATEGY] block captured (%d chars).",
                        len(updates["_react_strategy"]),
                    )

            # ── Tool execution loop ──────────────────────────────────────
            for tc in tool_calls:
                name    = tc["name"]
                args    = tc["args"]
                call_id = tc["id"]

                if name in tools_dict:
                    # Merge workflow_state with all accumulated updates so
                    # tools see the latest _react_strategy and other prior
                    # tool results from this same step.
                    effective_state = {**state["workflow_state"], **updates}
                    result          = tools_dict[name](state=effective_state, **args)

                    if result.is_error:
                        early_exit = True
                        tool_messages.append(ToolMessage(
                            content=(
                                f"[Fatal Error] Tool '{name}' crashed: "
                                f"{result.observation}. Stop and report; do not retry."
                            ),
                            tool_call_id=call_id,
                            name=name,
                        ))
                        break

                    updates.update(result.state_updates)
                    early_exit  = early_exit or result.should_return
                    observation = result.observation

                else:
                    early_exit  = True
                    observation = (
                        f"[Not Found] Tool '{name}' does not exist. "
                        f"Available tools: {list(tools_dict)}. "
                        "Do not guess or modify tool names."
                    )

                tool_messages.append(ToolMessage(
                    content=observation, tool_call_id=call_id, name=name
                ))
                if early_exit:
                    break

            return {
                "messages":            tool_messages,
                "accumulated_updates": updates,
                "should_return_early": early_exit,
            }

        # ── conditional edges ────────────────────────────────────────────
        def route_after_agent(state: _ReactState) -> str:
            if state.get("should_return_early"):
                return END
            last = state["messages"][-1]
            if getattr(last, "tool_calls", None):
                return "tools"
            logger.warning(
                "[ThinkModule] agent produced no tool_calls and no early-exit. "
                "Ending loop. Last message: %.120s",
                getattr(last, "content", ""),
            )
            return END

        def route_after_tools(state: _ReactState) -> str:
            return END if state.get("should_return_early") else "agent"

        # ── assemble ─────────────────────────────────────────────────────
        g = StateGraph(_ReactState)
        g.add_node("agent", agent_node)
        g.add_node("tools", tools_node)
        g.set_entry_point("agent")
        g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
        g.add_conditional_edges("tools", route_after_tools, {"agent": "agent", END: END})

        compiled = g.compile()
        logger.debug(
            "[ThinkModule] compiled ReAct graph — tools: %s (tool_choice=%s)",
            list(tools_dict), tool_choice,
        )
        return compiled