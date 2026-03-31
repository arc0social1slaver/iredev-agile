from enum import Enum
from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Memory strategy for an agent."""
    NONE = "none"
    SHORT_TERM = "short_term"           # session-scoped buffer, wiped after artifact
    EPISODIC = "episodic"               # event-log per PR / sprint across sessions
    SEMANTIC = "semantic"               # fact / profile store with semantic search
    EPISODIC_SEMANTIC = "episodic_semantic"  # Sprint Agent: both combined


class Episode(BaseModel):
    """One recorded event for episodic memory."""
    trigger: str = Field(..., description="What caused this event.")
    decision: str = Field(..., description="What was decided or observed.")
    outcome: str = Field(..., description="Result or follow-up action.")


class Fact(BaseModel):
    """One settled piece of knowledge for semantic memory."""
    topic: str = Field(..., description="Short label for the fact.")
    content: str = Field(..., description="The fact in plain language.")