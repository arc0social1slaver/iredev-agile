import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langgraph.store.base import BaseStore
from langgraph.store.postgres import PostgresStore

from .types import Episode, Fact


# ---------------------------------------------------------------------------
# Shared store factory
# ---------------------------------------------------------------------------

def create_store(pg_conn_str: str, embed_fn=None, dims: int = 1536) -> PostgresStore:
    """Create the shared Postgres-backed LangGraph store.

    Pass embed_fn + dims to enable semantic vector search.
    Omit both for exact key lookup only (dev / no-embedding mode).

    Args:
        pg_conn_str: PostgreSQL connection string.
        embed_fn: Callable[[list[str]], list[list[float]]] or LangChain Embeddings.
        dims: Embedding vector dimensions — must match embed_fn output.

    Returns:
        PostgresStore with tables initialized via setup().
    """
    if embed_fn is None:
        store = PostgresStore.from_conn_string(pg_conn_str)
    else:
        store = PostgresStore.from_conn_string(
            pg_conn_str,
            index={"embed": embed_fn, "dims": dims},
        )
    store.setup()
    return store


# ---------------------------------------------------------------------------
# Episodic Memory — Reviewer Agent (per PR), Sprint Agent
# ---------------------------------------------------------------------------

class EpisodicMemory:
    """Stores and retrieves event episodes per project / entity.

    Each episode records one trigger → decision → outcome cycle.
    Namespace: (project_id, "episodes", entity_id)
    where entity_id is a PR number, sprint ID, etc.
    """

    def __init__(self, store: BaseStore, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    def record(self, entity_id: str, episode: Episode) -> None:
        """Persist one episode under the given entity.

        Args:
            entity_id: PR number, sprint ID, or any unique identifier.
            episode: Episode schema with trigger, decision, outcome.
        """
        namespace = (self._project_id, "episodes", entity_id)
        self._store.put(
            namespace,
            str(uuid.uuid4()),
            {
                "trigger": episode.trigger,
                "decision": episode.decision,
                "outcome": episode.outcome,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def recall(
        self,
        entity_id: str,
        query: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Retrieve past episodes for an entity.

        With embed_fn configured on the store, query enables semantic search.
        Without it, returns the most recent episodes up to limit.

        Args:
            entity_id: Identifier used when recording.
            query: Natural language query for semantic similarity search.
            limit: Max number of episodes to return.

        Returns:
            List of episode dicts.
        """
        namespace = (self._project_id, "episodes", entity_id)
        results = self._store.search(namespace, query=query, limit=limit)
        return [r.value for r in results]


# ---------------------------------------------------------------------------
# Semantic Memory — Interviewer (Consultant Mode), Sprint Agent (backlog profile)
# ---------------------------------------------------------------------------

class SemanticMemory:
    """Stores settled facts and profile data; prevents re-asking known topics.

    Fact topic is used as the key — writing the same topic overwrites the old value,
    which is the intended pattern for profile-style single-source-of-truth storage.
    Namespace: (project_id, "facts", context)
    where context is e.g. "sprint_discussions" or "backlog_profile".
    """

    def __init__(self, store: BaseStore, project_id: str) -> None:
        self._store = store
        self._project_id = project_id

    def remember(self, context: str, fact: Fact) -> None:
        """Store or overwrite a settled fact (topic is the dedup key).

        Args:
            context: Logical grouping (e.g. 'sprint_discussions', 'backlog_profile').
            fact: Fact schema with topic and content.
        """
        namespace = (self._project_id, "facts", context)
        self._store.put(namespace, fact.topic, {"topic": fact.topic, "content": fact.content})

    def search(self, context: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve facts semantically similar to query.

        Call before asking a question to check whether the topic was already settled.

        Args:
            context: Logical grouping to search within.
            query: The question or topic to check.
            limit: Max results.

        Returns:
            List of fact dicts; empty list if nothing relevant found.
        """
        namespace = (self._project_id, "facts", context)
        results = self._store.search(namespace, query=query, limit=limit)
        return [r.value for r in results]

    def recall_all(self, context: str) -> List[Dict[str, Any]]:
        """Return every fact in a context (e.g. full backlog profile dump).

        Args:
            context: Logical grouping to dump.

        Returns:
            List of all stored fact dicts.
        """
        namespace = (self._project_id, "facts", context)
        results = self._store.search(namespace, limit=1000)
        return [r.value for r in results]