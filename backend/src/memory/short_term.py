from typing import List

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.postgres import PostgresSaver


class ConversationBuffer:
    """Session-scoped message buffer — wiped once an artifact is complete.

    No framework dependency; plain Python list wrapped for convenience.
    Mirrors LangChain message format so it feeds directly into llm.invoke().
    """

    def __init__(self, system_prompt: str = "") -> None:
        self._history: List[BaseMessage] = []
        if system_prompt:
            self._history.append(SystemMessage(content=system_prompt))

    def add_user(self, content: str) -> None:
        """Append a human turn.

        Args:
            content: User message text.
        """
        self._history.append(HumanMessage(content=content))

    def add_assistant(self, content: str) -> None:
        """Append an assistant turn.

        Args:
            content: Model response text.
        """
        self._history.append(AIMessage(content=content))

    def get(self) -> List[BaseMessage]:
        """Return the full message list for llm.invoke().

        Returns:
            List of LangChain BaseMessage objects.
        """
        return list(self._history)

    def clear(self) -> None:
        """Reset buffer, keeping the system prompt if one was set."""
        system = [m for m in self._history if isinstance(m, SystemMessage)]
        self._history = system


def create_checkpointer(pg_conn_str: str) -> PostgresSaver:
    """Create a Postgres-backed LangGraph checkpointer for short-term session state.

    Use with LangGraph graphs: graph.compile(checkpointer=create_checkpointer(...)).
    Scope each session via thread_id: {"configurable": {"thread_id": "session_xyz"}}.

    Args:
        pg_conn_str: PostgreSQL connection string.

    Returns:
        Configured PostgresSaver with tables initialized.
    """
    checkpointer = PostgresSaver.from_conn_string(pg_conn_str)
    checkpointer.setup()
    return checkpointer