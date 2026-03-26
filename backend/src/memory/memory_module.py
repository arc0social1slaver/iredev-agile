"""Unified memory interface for iReDev agents.

Outside callers only need MemoryModule.
Initialize it with the right MemoryType and connection string;
everything else (which backend, which store, which namespace) is handled internally.

Usage examples:

    # Short-term: Interviewer / EndUser / other artifact agents
    mem = MemoryModule(MemoryType.SHORT_TERM, system_prompt="You are ...")
    mem.add("What are your pain points?", role="assistant")
    mem.add("The UI is too slow.", role="user")
    messages = mem.take()["messages"]   # feed into llm.invoke()
    mem.refresh()                        # wipe after artifact is done

    # Episodic: Reviewer Agent tracking PR review cycles
    mem = MemoryModule(MemoryType.EPISODIC, pg_conn_str=DB_URL, project_id="proj_1")
    mem.add(Episode(trigger="DoD fail", decision="request fix", outcome="pending"), entity_id="pr_42")
    past = mem.take(query="DoD failure", entity_id="pr_42")["episodes"]

    # Semantic: Interviewer Consultant Mode, storing settled decisions
    mem = MemoryModule(MemoryType.SEMANTIC, pg_conn_str=DB_URL, project_id="proj_1")
    mem.add(Fact(topic="auth_method", content="OAuth 2.0 confirmed by client"), entity_id="sprint_discussions")
    facts = mem.take(query="authentication", entity_id="sprint_discussions")["facts"]

    # Episodic + Semantic: Sprint Agent (backlog profile + change history)
    mem = MemoryModule(MemoryType.EPISODIC_SEMANTIC, pg_conn_str=DB_URL, project_id="proj_1")
    mem.add(Fact(topic="backlog_profile", content="{...}"), entity_id="backlog_profile")
    mem.add(Episode(trigger="customer request", decision="add item X", outcome="added"), entity_id="sprint_3")
"""

from typing import Any, Dict, Optional, Union

from .long_term import EpisodicMemory, SemanticMemory, create_store
from .short_term import ConversationBuffer
from .types import Episode, Fact, MemoryType


class MemoryModule:
    """Unified memory interface — routes add / take / refresh to the correct backend.

    The caller declares a MemoryType at init time; internal routing is opaque.
    Long-term backends (EPISODIC, SEMANTIC, EPISODIC_SEMANTIC) require pg_conn_str.
    SHORT_TERM works without a database connection.
    """

    def __init__(
        self,
        memory_type: MemoryType,
        pg_conn_str: Optional[str] = None,
        project_id: str = "default",
        system_prompt: str = "",
        embed_fn=None,
        dims: int = 1536,
    ) -> None:
        """Initialize backends based on memory_type.

        Args:
            memory_type: Which memory strategy to activate.
            pg_conn_str: PostgreSQL connection string — required for EPISODIC / SEMANTIC / EPISODIC_SEMANTIC.
            project_id: Namespace root used to partition the store per project.
            system_prompt: Fixed system prompt injected into the SHORT_TERM buffer.
            embed_fn: Embedding callable to enable semantic search in the store.
            dims: Vector dimensions — must match embed_fn output.
        """
        self._type = memory_type
        self._buffer: Optional[ConversationBuffer] = None
        self._episodic: Optional[EpisodicMemory] = None
        self._semantic: Optional[SemanticMemory] = None

        if memory_type == MemoryType.SHORT_TERM:
            self._buffer = ConversationBuffer(system_prompt)

        if memory_type in (MemoryType.EPISODIC, MemoryType.SEMANTIC, MemoryType.EPISODIC_SEMANTIC):
            if not pg_conn_str:
                raise ValueError(
                    f"pg_conn_str is required for memory_type='{memory_type}'."
                )
            store = create_store(pg_conn_str, embed_fn=embed_fn, dims=dims)

            if memory_type in (MemoryType.EPISODIC, MemoryType.EPISODIC_SEMANTIC):
                self._episodic = EpisodicMemory(store, project_id)

            if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC_SEMANTIC):
                self._semantic = SemanticMemory(store, project_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        content: Union[str, Episode, Fact],
        role: str = "user",
        entity_id: Optional[str] = None,
    ) -> None:
        """Add content to the active memory backend(s).

        Routing by content type:
            str     → SHORT_TERM buffer (role determines user / assistant turn).
            Episode → EPISODIC store (entity_id required — e.g. "pr_42", "sprint_3").
            Fact    → SEMANTIC store (entity_id used as context label, e.g. "backlog_profile").

        An EPISODIC_SEMANTIC agent can call add() with an Episode and separately
        with a Fact — each is routed to its own backend automatically.

        Args:
            content: str for short-term, Episode for episodic, Fact for semantic.
            role: 'user' or 'assistant' — only used for SHORT_TERM str content.
            entity_id: Entity / context identifier for long-term backends.
        """
        if self._buffer is not None and isinstance(content, str):
            if role == "assistant":
                self._buffer.add_assistant(content)
            else:
                self._buffer.add_user(content)

        if self._episodic is not None and isinstance(content, Episode):
            if not entity_id:
                raise ValueError("entity_id is required when adding an Episode.")
            self._episodic.record(entity_id, content)

        if self._semantic is not None and isinstance(content, Fact):
            self._semantic.remember(entity_id or "default", content)

    def take(
        self,
        query: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """Retrieve from active backend(s).

        Returns a dict; only keys for active backends are present:
            'messages' — List[BaseMessage] from the SHORT_TERM buffer.
            'episodes' — List[dict] from EPISODIC store.
            'facts'    — List[dict] from SEMANTIC store
                         (semantic search if query given, full dump otherwise).

        Args:
            query: Natural language query for semantic / episodic search.
            entity_id: PR / sprint ID for episodic; context label for semantic.
            limit: Max results returned from store-backed backends.

        Returns:
            Dict of retrieved memory entries keyed by backend type.
        """
        result: Dict[str, Any] = {}

        if self._buffer is not None:
            result["messages"] = self._buffer.get()

        if self._episodic is not None:
            if not entity_id:
                raise ValueError("entity_id is required to recall episodic memory.")
            result["episodes"] = self._episodic.recall(entity_id, query=query, limit=limit)

        if self._semantic is not None:
            context = entity_id or "default"
            result["facts"] = (
                self._semantic.search(context, query, limit=limit)
                if query
                else self._semantic.recall_all(context)
            )

        return result

    def refresh(self) -> None:
        """Reset the short-term buffer. Long-term Postgres memory persists unchanged."""
        if self._buffer is not None:
            self._buffer.clear()