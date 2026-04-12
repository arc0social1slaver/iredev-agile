"""Unified memory interface for iReDev agents.

Outside callers only need MemoryModule.
Initialize it with the right MemoryType and connection string;
everything else (which backend, which store, which namespace) is handled internally.

Usage examples:

    # Short-term: EndUser / other artifact agents
    mem = MemoryModule(MemoryType.SHORT_TERM)
    mem.add("What are your pain points?", role="assistant")
    mem.add("The UI is too slow.", role="user")
    messages = mem.take()["messages"]   # feed into llm.invoke()
    mem.refresh()                        # wipe after artifact is done

    # Short-term + Semantic: InterviewerAgent (buffer + belief-state facts)
    mem = MemoryModule(MemoryType.SHORT_TERM_SEMANTIC, project_id="proj_1")
    mem.add("Turn completed.", role="assistant")                     # → buffer
    mem.settle_fact("zone_functional", "FR-001", "User can login")  # → semantic store
    facts  = mem.recall_zone("zone_functional", query="login")      # → list[str]
    count  = mem.count_zone("zone_functional")                      # → int

    # Episodic: Reviewer Agent tracking PR review cycles
    mem = MemoryModule(MemoryType.EPISODIC, project_id="proj_1")
    mem.add(Episode(trigger="DoD fail", decision="request fix", outcome="pending"), entity_id="pr_42")
    past = mem.take(query="DoD failure", entity_id="pr_42")["episodes"]

    # Semantic: Interviewer Consultant Mode, storing settled decisions
    mem = MemoryModule(MemoryType.SEMANTIC, project_id="proj_1")
    mem.add(Fact(topic="auth_method", content="OAuth 2.0 confirmed"), entity_id="sprint_discussions")
    facts = mem.take(query="authentication", entity_id="sprint_discussions")["facts"]

    # Episodic + Semantic: Sprint Agent (backlog profile + change history)
    mem = MemoryModule(MemoryType.EPISODIC_SEMANTIC, project_id="proj_1")
    mem.add(Fact(topic="backlog_profile", content="{...}"), entity_id="backlog_profile")
    mem.add(Episode(trigger="customer request", decision="add item X", outcome="added"), entity_id="sprint_3")
"""

from typing import Any, Dict, List, Optional, Union

from .long_term import EpisodicMemory, SemanticMemory, create_store
from .short_term import ConversationBuffer
from .types import Episode, Fact, MemoryType
from ..config.config_manager import get_config


class MemoryModule:
    """Unified memory interface — routes add / take / refresh to the correct backend.

    The caller declares a MemoryType at init time; internal routing is opaque.
    Long-term backends require a pg_connection in config.
    SHORT_TERM and SHORT_TERM_SEMANTIC work without a pg connection for the buffer part.

    SHORT_TERM_SEMANTIC (InterviewerAgent)
    ──────────────────────────────────────
    Combines:
      • ConversationBuffer  — per-turn message history (wiped by refresh())
      • SemanticMemory      — persistent belief-state facts across turns

    Use the convenience methods settle_fact / recall_zone / count_zone instead of
    add(Fact(...)) / take(entity_id=...) to work with belief-state facts.
    """

    def __init__(
        self,
        memory_type: MemoryType,
        project_id:  str = "default",
        embed_fn     = None,
        dims:        int = 1536,
    ) -> None:
        self._type     = memory_type
        self._buffer:   Optional[ConversationBuffer] = None
        self._episodic: Optional[EpisodicMemory]     = None
        self._semantic: Optional[SemanticMemory]     = None

        # ── Short-term buffer ─────────────────────────────────────────────────
        # BUG FIX: previously missing — buffer was never created for SHORT_TERM.
        if memory_type in (MemoryType.SHORT_TERM, MemoryType.SHORT_TERM_SEMANTIC):
            self._buffer = ConversationBuffer()

        # ── Long-term Postgres backends ───────────────────────────────────────
        if memory_type in (
            MemoryType.EPISODIC,
            MemoryType.SEMANTIC,
            MemoryType.EPISODIC_SEMANTIC,
            MemoryType.SHORT_TERM_SEMANTIC,
        ):
            cfg         = get_config().get("iredev", {}).get("knowledge_base", {})
            pg_conn_str = cfg.get("pg_connection")
            store       = create_store(pg_conn_str, embed_fn=embed_fn, dims=dims)

            if memory_type in (MemoryType.EPISODIC, MemoryType.EPISODIC_SEMANTIC):
                self._episodic = EpisodicMemory(store, project_id)

            if memory_type in (
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC_SEMANTIC,
                MemoryType.SHORT_TERM_SEMANTIC,
            ):
                self._semantic = SemanticMemory(store, project_id)

    # ── Public API ────────────────────────────────────────────────────────────

    def add(
        self,
        content:   Union[str, Episode, Fact],
        role:      str = "user",
        entity_id: Optional[str] = None,
    ) -> None:
        """Add content to the active memory backend(s).

        Routing by content type:
            str     → SHORT_TERM buffer (role determines user / assistant turn).
            Episode → EPISODIC store (entity_id required).
            Fact    → SEMANTIC store (entity_id used as context label).
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
        query:     Optional[str] = None,
        entity_id: Optional[str] = None,
        limit:     int = 5,
    ) -> Dict[str, Any]:
        """Retrieve from active backend(s).

        Returns a dict; only keys for active backends are present:
            'messages' — List[BaseMessage] from the SHORT_TERM buffer.
            'episodes' — List[dict] from EPISODIC store.
            'facts'    — List[dict] from SEMANTIC store.
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

    # ── Belief-state convenience API (SHORT_TERM_SEMANTIC / SEMANTIC only) ────
    # These replace the old _BeliefState helper class in InterviewerAgent.
    # Using zone_id as the context label keeps belief facts grouped per zone,
    # exactly as _BeliefState.settle / recall / count did.

    def settle_fact(self, zone_id: str, req_id: str, content: str) -> None:
        """Persist a confirmed requirement fact for the given zone.

        Replaces: _BeliefState.settle(zone_id, req_id, content)
        """
        if self._semantic is None:
            return
        self._semantic.remember(
            zone_id,
            Fact(topic=f"{zone_id}:{req_id}", content=content),
        )

    def recall_zone(
        self,
        zone_id: str,
        query:   str = "",
        limit:   int = 4,
    ) -> List[str]:
        """Return settled fact contents for a zone, optionally filtered by query.

        Replaces: _BeliefState.recall(zone_id, query, limit)

        Returns:
            List of content strings (empty list when semantic store not active).
        """
        if self._semantic is None:
            return []
        results = (
            self._semantic.search(zone_id, query, limit=limit)
            if query
            else self._semantic.recall_all(zone_id)[:limit]
        )
        return [r["content"] for r in results]

    def count_zone(self, zone_id: str) -> int:
        """Number of settled facts for a zone.

        Replaces: _BeliefState.count(zone_id)
        """
        if self._semantic is None:
            return 0
        return len(self._semantic.recall_all(zone_id))