from typing import TypedDict, Annotated, Dict, Any, List
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    Represents the shared memory and monitor module for the agents.
    LangGraph tracks this state across execution steps.
    """
    # Memory Module: Stores dialogue history and sequential interactions
    messages: Annotated[List[BaseMessage], add_messages]

    # # Artifact Pool / Monitor Module: Tracks generated artifacts (URL, SRS, Models)
    # artifacts: Dict[str, Any]
    #
    # # Execution Context: Guides the CoT and retrieval processes
    # current_phase: str  # e.g., "Elicitation", "Analysis", "Specification"
    # next_action: str  # Used for routing in LangGraph