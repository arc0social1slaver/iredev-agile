"""ThinkModule — agentic reasoning loop for knowledge injection.

Flow per agent turn (Memory-First RAG):

    query + memory_context
        -> [search_memory]  extract prior turns / facts / episodes into plain text
        -> [decide]         heuristic: enough prior context? LLM only when uncertain
             YES -> [blend]
             NO  -> [rewrite_query] -> [retrieve] -> [blend]
        -> context str  (prepended to agent system message)

Design notes:
- LangGraph StateGraph compiles the graph once in __init__; invoke() runs it per turn.
- decide uses a fast heuristic first (no LLM call when memory is clearly empty or
  clearly rich) and only falls back to an LLM call in the ambiguous middle range.
- search_memory reads ALL three memory shapes: SHORT_TERM messages, semantic facts,
  and episodic records — so any agent type gets a useful summary.
- The compiled graph is stored on the instance; each agent owns its own ThinkModule
  but they all share the same KnowledgeModule singleton.
"""

import logging
from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.knowledge import KnowledgeModule
from src.orchestrator import ProcessPhase

# langgraph is imported lazily inside _build_graph() to avoid driver
# initialization at module import time.

logger = logging.getLogger(__name__)

# Minimum number of prior conversation lines before we consider memory "sufficient".
# Below this threshold decide() skips the LLM call and always retrieves knowledge.
_MIN_MEMORY_LINES_FOR_LLM = 3


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class _ThinkState(TypedDict):
    """Shared state threaded through every node in the reasoning graph."""
    query: str
    phase: str                          # ProcessPhase.value — JSON-serializable
    memory_context: Dict[str, Any]
    memory_summary: str                 # Extracted prior context as plain text
    memory_sufficient: bool             # Decide node result
    rewritten_query: str                # Query after LLM rewrite (RAG branch)
    knowledge_docs: List[Document]
    final_context: str                  # Assembled context block returned to caller
    k: int                              # How many knowledge docs to retrieve


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ThinkModule
# ---------------------------------------------------------------------------

class ThinkModule:
    """Per-agent reasoning layer: memory-first RAG via a LangGraph StateGraph.

    Usage in an agent's process():

        context = self.think.build_prompt_context(
            query=user_input,
            phase=ProcessPhase.ELICITATION,
            memory_context=self.memory.take(),
        )
        messages = [("user", user_input)]
        return self.generate_response(messages, knowledge_context=context)
    """

    def __init__(self, knowledge: KnowledgeModule, llm: BaseChatModel) -> None:
        """Compile the reasoning graph.

        Args:
            knowledge: The process-wide KnowledgeModule singleton.
            llm: The agent's LLM — used for decide and query-rewrite steps.
        """
        self._knowledge = knowledge
        self._llm = llm
        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_prompt_context(
        self,
        query: str,
        phase: ProcessPhase,
        memory_context: Optional[Dict[str, Any]] = None,
        k: int = 5,
    ) -> str:
        """Run the reasoning loop and return a formatted context block.

        Returns an empty string when neither memory nor knowledge yields
        useful content, so callers can safely skip injecting a system message.

        Args:
            query: Current user input or agent reasoning context.
            phase: Active process phase for knowledge filtering.
            memory_context: Output of MemoryModule.take().
            k: Maximum number of knowledge snippets to retrieve.

        Returns:
            Formatted context string, or "" if nothing relevant found.
        """
        initial_state: _ThinkState = {
            "query": query,
            "phase": phase.value,
            "memory_context": memory_context or {},
            "memory_summary": "",
            "memory_sufficient": False,
            "rewritten_query": query,
            "knowledge_docs": [],
            "final_context": "",
            "k": k,
        }
        result = self._graph.invoke(initial_state)
        return result.get("final_context", "")

    # ------------------------------------------------------------------
    # Graph nodes
    # ------------------------------------------------------------------

    def _node_search_memory(self, state: _ThinkState) -> Dict[str, Any]:
        """Extract prior context from all three memory shapes into plain text.

        Reads SHORT_TERM messages (last 6 turns), semantic facts, and episodic
        records from memory_context and formats them into a single readable block.
        This unified summary is used by both the decide heuristic and the
        query-rewrite prompt.

        Args:
            state: Current graph state.

        Returns:
            State update with memory_summary populated.
        """
        ctx = state["memory_context"]
        lines: List[str] = []

        # --- SHORT_TERM: extract last 6 human/AI turns from the buffer ---
        messages: List[BaseMessage] = ctx.get("messages", [])
        # Skip the first message if it is the system prompt (profile)
        turns = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
        for msg in turns[-6:]:
            prefix = "[user]" if isinstance(msg, HumanMessage) else "[assistant]"
            # Truncate long turns to keep the summary manageable
            lines.append(f"{prefix} {msg.content[:300]}")

        # --- Long-term: semantic facts ---
        for fact in ctx.get("facts", [])[:6]:
            if "topic" in fact and "content" in fact:
                lines.append(f"[fact] {fact['topic']}: {fact['content']}")

        # --- Long-term: episodic records ---
        for episode in ctx.get("episodes", [])[:4]:
            trigger = episode.get("trigger", "")
            decision = episode.get("decision", "")
            if trigger and decision:
                lines.append(f"[episode] trigger={trigger} | decision={decision}")

        summary = "\n".join(lines) if lines else "(no prior memory)"
        logger.debug("[ThinkModule] memory_summary (%d lines): %s", len(lines), summary[:150])
        return {"memory_summary": summary}

    def _node_decide(self, state: _ThinkState) -> Dict[str, Any]:
        """Decide whether memory context alone is sufficient to answer the query.

        Uses a two-tier approach to avoid unnecessary LLM calls:
          - Fewer than _MIN_MEMORY_LINES_FOR_LLM prior lines -> always retrieve (NO).
          - Many prior lines (>= 10) -> trust memory, skip retrieval (YES).
          - In between -> ask the LLM to decide.

        Args:
            state: Current graph state.

        Returns:
            State update with memory_sufficient flag.
        """
        summary = state["memory_summary"]
        line_count = len([l for l in summary.splitlines() if l.strip()])

        # Clear heuristic: no memory -> always retrieve knowledge
        if summary == "(no prior memory)" or line_count < _MIN_MEMORY_LINES_FOR_LLM:
            logger.debug("[ThinkModule] decide=False (heuristic: sparse memory, lines=%d)", line_count)
            return {"memory_sufficient": False}

        # Rich memory (10+ lines): trust the context, skip RAG to save latency
        if line_count >= 10:
            logger.debug("[ThinkModule] decide=True (heuristic: rich memory, lines=%d)", line_count)
            return {"memory_sufficient": True}

        # Ambiguous range: ask the LLM
        prompt = _DECIDE_PROMPT.format(
            query=state["query"],
            memory_summary=summary,
        )
        response = self._llm.invoke([HumanMessage(content=prompt)])
        # Be strict: only YES counts — any other output routes to RAG
        sufficient = response.content.strip().upper().startswith("YES")
        logger.debug(
            "[ThinkModule] decide=%s (LLM, raw='%s', lines=%d)",
            sufficient, response.content.strip()[:30], line_count,
        )
        return {"memory_sufficient": sufficient}

    def _node_rewrite_query(self, state: _ThinkState) -> Dict[str, Any]:
        """Rewrite the original query for better vector search precision.

        Incorporates the memory summary so the rewritten query references
        already-known context (e.g. "Microsoft SSO authentication methodology"
        instead of the generic "login").

        Args:
            state: Current graph state.

        Returns:
            State update with rewritten_query.
        """
        # If there is no useful memory context just use the raw query —
        # rewriting "(no prior memory)" context adds noise, not signal.
        if state["memory_summary"] == "(no prior memory)":
            return {"rewritten_query": state["query"]}

        prompt = _REWRITE_PROMPT.format(
            query=state["query"],
            memory_summary=state["memory_summary"],
        )
        response = self._llm.invoke([HumanMessage(content=prompt)])
        rewritten = response.content.strip()
        logger.debug("[ThinkModule] rewritten_query: %s", rewritten[:120])
        return {"rewritten_query": rewritten}

    def _node_retrieve(self, state: _ThinkState) -> Dict[str, Any]:
        """Retrieve knowledge documents using the (rewritten) query.

        Args:
            state: Current graph state.

        Returns:
            State update with knowledge_docs.
        """
        phase = ProcessPhase(state["phase"])
        docs = self._knowledge.retrieve(
            query=state["rewritten_query"],
            phase=phase,
            k=state["k"],
        )
        logger.info("[ThinkModule] retrieved %d knowledge docs for phase=%s.", len(docs), phase.value)
        return {"knowledge_docs": docs}

    def _node_blend(self, state: _ThinkState) -> Dict[str, Any]:
        """Assemble memory summary and knowledge docs into one context block.

        Memory (prior conversation / facts) is listed first because it is
        specific to this project and takes priority over general guidelines.
        Knowledge snippets follow as supporting methodology.

        Args:
            state: Current graph state.

        Returns:
            State update with final_context.
        """
        sections: List[str] = []

        # --- Prior conversation context (always included if non-empty) ---
        if state["memory_summary"] != "(no prior memory)":
            sections.append(
                "## Prior Conversation Context\n"
                "Use the following to stay consistent with what has already been discussed.\n\n"
                + state["memory_summary"]
            )

        # --- Knowledge snippets (only on RAG branch) ---
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
                "Prioritize the prior conversation context above over these general guidelines.\n\n"
                + "\n\n".join(snippets)
            )

        final = "\n\n".join(sections)
        return {"final_context": final}

    # ------------------------------------------------------------------
    # Conditional edge
    # ------------------------------------------------------------------

    @staticmethod
    def _route_after_decide(state: _ThinkState) -> str:
        """Route to blend (memory sufficient) or rewrite_query (RAG needed).

        Args:
            state: Current graph state.

        Returns:
            Node name to transition to.
        """
        return "blend" if state["memory_sufficient"] else "rewrite_query"

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        """Compile the LangGraph StateGraph for the reasoning loop.

        Lazy-imports langgraph so the graph machinery is only loaded when the
        first ThinkModule instance is created, not at module import time.

        Returns:
            Compiled runnable graph.
        """
        from langgraph.graph import END, StateGraph

        g = StateGraph(_ThinkState)

        g.add_node("search_memory", self._node_search_memory)
        g.add_node("decide", self._node_decide)
        g.add_node("rewrite_query", self._node_rewrite_query)
        g.add_node("retrieve", self._node_retrieve)
        g.add_node("blend", self._node_blend)

        g.set_entry_point("search_memory")
        g.add_edge("search_memory", "decide")
        g.add_conditional_edges("decide", self._route_after_decide)
        g.add_edge("rewrite_query", "retrieve")
        g.add_edge("retrieve", "blend")
        g.add_edge("blend", END)

        return g.compile()