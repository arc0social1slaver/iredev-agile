"""ThinkModule — agentic reasoning with Memory-First RAG *and* the ReAct loop.

Two responsibilities
─────────────────────────────────────────────────────────────────────────────
1. RAG context injection  (existing, unchanged)
   Memory-First RAG via a LangGraph StateGraph:

       query + memory_context
           -> [search_memory]  extract prior turns / facts / episodes
           -> [decide]         enough prior context? (heuristic + LLM fallback)
                YES -> [blend]
                NO  -> [rewrite_query] -> [retrieve] -> [blend]
           -> context str  (prepended to agent system message)

2. ReAct execution loop  (new — moved from BaseAgent)
   Tool-calling loop via a separate LangGraph StateGraph:

       SystemMessage(profile + knowledge_context)
       HumanMessage(task)
           -> [agent]   LLM with tools bound (function-calling style)
           -> [tools]   custom executor — runs our Tool objects,
                        collects state_updates, honours should_return
           -> [agent]   … until no tool_calls or should_return_early
           -> accumulated_updates returned to caller

Design notes
─────────────────────────────────────────────────────────────────────────────
- Both graphs are compiled once per ThinkModule instance (RAG graph) or per
  unique tool-set (ReAct graph cached by frozenset of tool names).
- Loop detection is delegated entirely to LangGraph's built-in recursion_limit
  mechanism; no manual counter or fingerprint tracking required.
- LLM tool-binding uses lightweight schema-only StructuredTool stubs so the
  LLM knows the tool catalogue.  Actual execution uses our Tool objects, which
  carry state_updates / should_return semantics that LangChain tools lack.
- The ThinkModule never imports from base.py to avoid circular imports;
  ToolResult attributes are accessed via duck-typing (getattr).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from typing_extensions import Annotated, TypedDict

from langchain_core.documents import Document
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

from ..knowledge import KnowledgeModule
from ..orchestrator import ProcessPhase

logger = logging.getLogger(__name__)

# Minimum prior-conversation lines before consider memory "sufficient".
_MIN_MEMORY_LINES_FOR_LLM = 3


# ─────────────────────────────────────────────────────────────────────────────
# RAG graph state  (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────

class _ThinkState(TypedDict):
    """Shared state threaded through every node in the RAG reasoning graph."""
    query:             str
    phase:             str                   # ProcessPhase.value
    memory_context:    Dict[str, Any]
    memory_summary:    str
    memory_sufficient: bool
    rewritten_query:   str
    knowledge_docs:    List[Document]
    final_context:     str
    k:                 int


# ─────────────────────────────────────────────────────────────────────────────
# ReAct graph state
# ─────────────────────────────────────────────────────────────────────────────

def _add_messages(left: List[BaseMessage], right: List[BaseMessage]) -> List[BaseMessage]:
    """Reducer: append new messages to the existing list (LangGraph convention)."""
    return list(left) + list(right)


class _ReactState(TypedDict):
    """Shared state threaded through the ReAct execution graph."""
    # Conversation buffer — grows with each agent/tool round-trip
    messages:            Annotated[List[BaseMessage], _add_messages]
    # The calling agent's WorkflowState — read-only inside tool functions
    workflow_state:      Dict[str, Any]
    # Merged state_updates returned by all tools so far
    accumulated_updates: Dict[str, Any]
    # Set to True by any tool whose ToolResult.should_return is True
    should_return_early: bool


# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates for the RAG graph  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

_DECIDE_PROMPT = """\
You are a requirements engineering assistant.

Current question from the stakeholder:
{query}

Prior conversation context already available:
{memory_summary}

Does the prior context above already contain enough information to answer
the current question WITHOUT consulting an external knowledge base?

Reply with exactly one word: YES or NO."""

_REWRITE_PROMPT = """\
You are a search query optimizer for a requirements engineering knowledge base.

Original question:
{query}

Prior conversation context (use this to make the query more specific):
{memory_summary}

Rewrite the question as a concise retrieval query (1-2 sentences) that will
surface the most relevant methodology, standard, or template.
Output only the rewritten query, nothing else."""


# ─────────────────────────────────────────────────────────────────────────────
# Helper: schema-only LangChain tool stub for LLM bind_tools
# ─────────────────────────────────────────────────────────────────────────────

def _make_schema_tool(tool: Any) -> StructuredTool:
    """Wrap a custom Tool as a schema-only LangChain StructuredTool.

    The stub is passed to ``llm.bind_tools()`` so the LLM knows the tool
    catalogue and can emit structured tool-call JSON.  The stub's func is
    never invoked — actual execution happens inside ``_build_tools_node``.

    Using ``**kwargs: Any`` as the function signature produces a JSON Schema
    with ``{"type": "object", "properties": {}}`` which is accepted by all
    major function-calling LLMs.  The natural-language ``description`` guides
    the LLM on which keyword args to supply.

    Args:
        tool: An instance of our custom Tool dataclass (base.Tool).

    Returns:
        A LangChain StructuredTool suitable for bind_tools.
    """
    # Build a Pydantic model that accepts any extra keyword args.
    # We use type() with a unique name per tool to avoid Pydantic model
    # registry collisions when many tools share the same class name.
    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", tool.name)
    cls_name  = f"_Args_{safe_name}"

    ArgsModel: type[BaseModel] = type(
        cls_name,
        (BaseModel,),
        {"model_config": ConfigDict(extra="allow")},
    )

    def _noop(**kwargs: Any) -> str:  # noqa: ANN003
        """Schema-only stub — never called directly."""
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
    """Per-agent reasoning layer: Memory-First RAG + ReAct execution loop.

    RAG usage (existing — unchanged)::

        context = self.think.build_prompt_context(
            query=user_input,
            phase=ProcessPhase.ELICITATION,
            memory_context=self.memory.take(),
        )

    ReAct usage (new — replaces BaseAgent.react)::

        state_updates = self.think.run_react(
            task=task,
            tools_dict=self.tools,
            workflow_state=state,
            profile_prompt=self.profile.prompt,
            memory_context=self.memory.take(),
            max_iterations=self.max_react_iterations,
        )
    """

    def __init__(self, knowledge: KnowledgeModule, llm: BaseChatModel) -> None:
        self._knowledge = knowledge
        self._llm       = llm
        self._rag_graph = self._build_rag_graph()

        # Cache compiled ReAct graphs keyed by frozenset of tool names so we
        # don't recompile for every run_react call from the same agent.
        self._react_graph_cache: Dict[frozenset, Any] = {}

    # ──────────────────────────────────────────────────────────────────────
    # Public API — RAG context
    # ──────────────────────────────────────────────────────────────────────

    def build_prompt_context(
        self,
        query:          str,
        phase:          ProcessPhase,
        memory_context: Optional[Dict[str, Any]] = None,
        k:              int = 5,
    ) -> str:
        """Run the Memory-First RAG loop and return a formatted context block.

        Returns an empty string when neither memory nor knowledge yields
        useful content.

        Args:
            query:          Current user input or agent reasoning context.
            phase:          Active process phase for knowledge filtering.
            memory_context: Output of MemoryModule.take().
            k:              Maximum number of knowledge snippets to retrieve.

        Returns:
            Formatted context string, or "" if nothing relevant found.
        """
        initial: _ThinkState = {
            "query":             query,
            "phase":             phase.value,
            "memory_context":    memory_context or {},
            "memory_summary":    "",
            "memory_sufficient": False,
            "rewritten_query":   query,
            "knowledge_docs":    [],
            "final_context":     "",
            "k":                 k,
        }
        result = self._rag_graph.invoke(initial)
        return result.get("final_context", "")

    # ──────────────────────────────────────────────────────────────────────
    # Public API — ReAct loop
    # ──────────────────────────────────────────────────────────────────────

    def run_react(
        self,
        task:            str,
        tools_dict:      Dict[str, Any],       # Dict[str, base.Tool]
        workflow_state:  Dict[str, Any],
        profile_prompt:  str,
        memory_context:  Optional[Dict[str, Any]] = None,
        max_iterations:  int = 10,
        phase:           Optional[ProcessPhase] = None,
    ) -> Dict[str, Any]:
        """Run one full ReAct turn and return merged WorkflowState updates.

        Steps
        ─────
        1. Knowledge context is obtained via the Memory-First RAG graph
           (single call before the loop — context does not change mid-turn).
        2. A LangGraph StateGraph with two nodes (``agent`` → ``tools``) is
           compiled and invoked.  LangGraph's ``recursion_limit`` guards against
           infinite loops — no manual counter required.
        3. All ``state_updates`` emitted by tools are merged and returned.

        Args:
            task:           Natural-language goal for this agent turn.
            tools_dict:     Mapping of tool name → Tool instance.
            workflow_state: Current WorkflowState (read-only inside tools).
            profile_prompt: Agent system prompt (profile).
            memory_context: Output of MemoryModule.take().
            max_iterations: Upper bound on agent↔tools cycles.
            phase:          ProcessPhase for RAG filtering (default: ELICITATION).

        Returns:
            Dict of WorkflowState keys to update (merged from all tool calls).
        """
        if phase is None:
            phase = ProcessPhase.ELICITATION

        # ── Step 1: build knowledge context (once) ────────────────────────
        knowledge_ctx = self.build_prompt_context(
            query=task,
            phase=phase,
            memory_context=memory_context,
        )

        # ── Step 2: build system message ──────────────────────────────────
        system_parts = [profile_prompt]
        if knowledge_ctx:
            system_parts.append(knowledge_ctx)
        system_msg = SystemMessage(content="\n\n---\n\n".join(system_parts))

        # ── Step 3: compile (or retrieve cached) ReAct graph ─────────────
        cache_key = frozenset(tools_dict.keys())
        if cache_key not in self._react_graph_cache:
            self._react_graph_cache[cache_key] = self._compile_react_graph(tools_dict)
        react_graph = self._react_graph_cache[cache_key]

        # ── Step 4: run the ReAct graph ───────────────────────────────────
        initial_state: _ReactState = {
            "messages":            [system_msg, HumanMessage(content=task)],
            "workflow_state":      workflow_state,
            "accumulated_updates": {},
            "should_return_early": False,
        }

        # Each agent+tools cycle is 2 graph steps; add buffer for entry/exit.
        recursion_limit = max_iterations * 2 + 4

        try:
            from langgraph.errors import GraphRecursionError
            result = react_graph.invoke(
                initial_state,
                config={"recursion_limit": recursion_limit},
            )
        except Exception as exc:
            # Catch GraphRecursionError and any provider-side recursion signals.
            if "recursion" in type(exc).__name__.lower() or "recursion" in str(exc).lower():
                logger.warning(
                    "[ThinkModule/ReAct] Max iterations (%d) reached for task: %.80s",
                    max_iterations, task,
                )
                result = {"accumulated_updates": {}}
            else:
                raise

        updates = result.get("accumulated_updates", {})
        logger.debug(
            "[ThinkModule/ReAct] finished — %d state key(s) updated.",
            len(updates),
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

        Args:
            tools_dict: Mapping of tool name → Tool instance.

        Returns:
            A compiled LangGraph ``CompiledStateGraph``.
        """
        from langgraph.graph import END, START, StateGraph

        # Bind schema-only stubs to the LLM for function-calling awareness.
        lc_stubs         = [_make_schema_tool(t) for t in tools_dict.values()]
        model_with_tools = self._llm.bind_tools(lc_stubs) if lc_stubs else self._llm

        # ── node: agent ───────────────────────────────────────────────────
        def agent_node(state: _ReactState) -> Dict[str, Any]:
            """Call the LLM; its tool_calls (if any) drive the next step."""
            response = model_with_tools.invoke(state["messages"])
            return {"messages": [response]}

        # ── node: tools ───────────────────────────────────────────────────
        def tools_node(state: _ReactState) -> Dict[str, Any]:
            """Execute every tool_call in the last AI message.

            Reads ``workflow_state`` from graph state, runs each matching
            Tool, collects observations as ToolMessages, merges state_updates,
            and sets ``should_return_early`` if any tool requests it.

            Unknown tool names are handled gracefully with an error observation
            so the agent can self-correct in the next cycle.
            """
            last_ai_msg = state["messages"][-1]
            tool_calls  = getattr(last_ai_msg, "tool_calls", None) or []

            tool_messages: List[ToolMessage] = []
            updates       = dict(state.get("accumulated_updates") or {})
            early_exit    = bool(state.get("should_return_early", False))

            for tc in tool_calls:
                name    = tc["name"]
                args    = tc["args"]
                call_id = tc["id"]

                if name in tools_dict:
                    # Duck-typed call — avoids circular import from base.py.
                    # Our Tool.__call__ returns a ToolResult with:
                    #   .observation   str
                    #   .state_updates dict
                    #   .should_return bool
                    #
                    # IMPORTANT: merge accumulated_updates into workflow_state
                    # before each tool call so that later tools (e.g.
                    # write_interview_record) see state changes made by earlier
                    # tools in the same ReAct turn (e.g. update_requirements).
                    # Without this merge, every tool receives the frozen
                    # workflow_state snapshot from the start of run_react(),
                    # causing requirements_draft (and any other intra-turn
                    # state) to appear empty to tools that run after the first.
                    effective_state = {**state["workflow_state"], **updates}
                    result = tools_dict[name](
                        state=effective_state, **args
                    )
                    observation = result.observation
                    updates.update(getattr(result, "state_updates", {}))
                    early_exit  = early_exit or bool(getattr(result, "should_return", False))
                else:
                    observation = (
                        f"[Tool Error] Unknown tool '{name}'. "
                        f"Available tools: {list(tools_dict)}. "
                        "Please call one of the listed tools or call FINISH."
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
            """Go to tools if the LLM emitted tool_calls, else end."""
            last = state["messages"][-1]
            if getattr(last, "tool_calls", None):
                return "tools"
            return END

        def route_after_tools(state: _ReactState) -> str:
            """End early if any tool requested it; otherwise loop to agent."""
            if state.get("should_return_early"):
                return END
            return "agent"

        # ── assemble graph ────────────────────────────────────────────────
        g = StateGraph(_ReactState)
        g.add_node("agent", agent_node)
        g.add_node("tools", tools_node)
        g.set_entry_point("agent")
        g.add_conditional_edges(
            "agent",
            route_after_agent,
            {"tools": "tools", END: END},
        )
        g.add_conditional_edges(
            "tools",
            route_after_tools,
            {"agent": "agent", END: END},
        )

        compiled = g.compile()
        logger.debug(
            "[ThinkModule] compiled ReAct graph for %d tool(s): %s",
            len(tools_dict), list(tools_dict),
        )
        return compiled

    # ──────────────────────────────────────────────────────────────────────
    # RAG graph nodes  (unchanged from original)
    # ──────────────────────────────────────────────────────────────────────

    def _node_search_memory(self, state: _ThinkState) -> Dict[str, Any]:
        """Extract prior context from all three memory shapes into plain text."""
        ctx   = state["memory_context"]
        lines: List[str] = []

        messages: List[BaseMessage] = ctx.get("messages", [])
        turns = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
        for msg in turns[-6:]:
            prefix = "[user]" if isinstance(msg, HumanMessage) else "[assistant]"
            lines.append(f"{prefix} {msg.content[:300]}")

        for fact in ctx.get("facts", [])[:6]:
            if "topic" in fact and "content" in fact:
                lines.append(f"[fact] {fact['topic']}: {fact['content']}")

        for episode in ctx.get("episodes", [])[:4]:
            trigger  = episode.get("trigger", "")
            decision = episode.get("decision", "")
            if trigger and decision:
                lines.append(f"[episode] trigger={trigger} | decision={decision}")

        summary = "\n".join(lines) if lines else "(no prior memory)"
        logger.debug("[ThinkModule] memory_summary (%d lines): %.150s", len(lines), summary)
        return {"memory_summary": summary}

    def _node_decide(self, state: _ThinkState) -> Dict[str, Any]:
        """Decide whether memory context alone is sufficient."""
        summary    = state["memory_summary"]
        line_count = len([ln for ln in summary.splitlines() if ln.strip()])

        if summary == "(no prior memory)" or line_count < _MIN_MEMORY_LINES_FOR_LLM:
            logger.debug("[ThinkModule] decide=False (heuristic: sparse memory, lines=%d)", line_count)
            return {"memory_sufficient": False}

        if line_count >= 10:
            logger.debug("[ThinkModule] decide=True (heuristic: rich memory, lines=%d)", line_count)
            return {"memory_sufficient": True}

        prompt   = _DECIDE_PROMPT.format(query=state["query"], memory_summary=summary)
        response = self._llm.invoke([HumanMessage(content=prompt)])
        sufficient = response.content.strip().upper().startswith("YES")
        logger.debug(
            "[ThinkModule] decide=%s (LLM, raw='%.30s', lines=%d)",
            sufficient, response.content.strip(), line_count,
        )
        return {"memory_sufficient": sufficient}

    def _node_rewrite_query(self, state: _ThinkState) -> Dict[str, Any]:
        """Rewrite the query for better vector search precision."""
        if state["memory_summary"] == "(no prior memory)":
            return {"rewritten_query": state["query"]}

        prompt   = _REWRITE_PROMPT.format(query=state["query"], memory_summary=state["memory_summary"])
        response = self._llm.invoke([HumanMessage(content=prompt)])
        rewritten = response.content.strip()
        logger.debug("[ThinkModule] rewritten_query: %.120s", rewritten)
        return {"rewritten_query": rewritten}

    def _node_retrieve(self, state: _ThinkState) -> Dict[str, Any]:
        """Retrieve knowledge documents using the (rewritten) query."""
        phase = ProcessPhase(state["phase"])
        docs  = self._knowledge.retrieve(
            query=state["rewritten_query"],
            phase=phase,
            k=state["k"],
        )
        logger.info(
            "[ThinkModule] retrieved %d knowledge docs for phase=%s.",
            len(docs), phase.value,
        )
        return {"knowledge_docs": docs}

    def _node_blend(self, state: _ThinkState) -> Dict[str, Any]:
        """Assemble memory summary and knowledge docs into one context block."""
        sections: List[str] = []

        if state["memory_summary"] != "(no prior memory)":
            sections.append(
                "## Prior Conversation Context\n"
                "Use the following to stay consistent with what has already been discussed.\n\n"
                + state["memory_summary"]
            )

        docs: List[Document] = state["knowledge_docs"]
        if docs:
            snippets = []
            for i, doc in enumerate(docs, start=1):
                title = doc.metadata.get("title", f"Snippet {i}")
                ktype = doc.metadata.get("knowledge_type", "")
                snippets.append(f"### [{i}] {title} ({ktype})\n{doc.page_content}")

            sections.append(
                "## Relevant Methodology & Standards\n"
                "Apply the following knowledge to guide your next question or analysis. "
                "Prioritise the prior conversation context above over these general guidelines.\n\n"
                + "\n\n".join(snippets)
            )

        return {"final_context": "\n\n".join(sections)}

    # ──────────────────────────────────────────────────────────────────────
    # RAG graph conditional edge  (unchanged)
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _route_after_decide(state: _ThinkState) -> str:
        return "blend" if state["memory_sufficient"] else "rewrite_query"

    # ──────────────────────────────────────────────────────────────────────
    # RAG graph construction  (unchanged)
    # ──────────────────────────────────────────────────────────────────────

    def _build_rag_graph(self):
        """Compile the Memory-First RAG StateGraph.

        Lazy-imports langgraph to avoid driver initialisation at module import.
        """
        from langgraph.graph import END, StateGraph

        g = StateGraph(_ThinkState)
        g.add_node("search_memory",  self._node_search_memory)
        g.add_node("decide",         self._node_decide)
        g.add_node("rewrite_query",  self._node_rewrite_query)
        g.add_node("retrieve",       self._node_retrieve)
        g.add_node("blend",          self._node_blend)

        g.set_entry_point("search_memory")
        g.add_edge("search_memory", "decide")
        g.add_conditional_edges("decide", self._route_after_decide)
        g.add_edge("rewrite_query", "retrieve")
        g.add_edge("retrieve",      "blend")
        g.add_edge("blend",         END)

        return g.compile()