"""
Orchestrator package.

Public surface
──────────────
ProcessPhase   – used by ThinkModule / KnowledgeModule (backward-compat re-export)
WorkflowState  – LangGraph state
build_graph()  – factory for the compiled workflow graph
"""

from .state import ProcessPhase, WorkflowState  # noqa: F401
from .flow import WORKFLOW_PHASES, PhaseDefinition  # noqa: F401
from .supervisor import supervisor_node, supervisor_router  # noqa: F401
from .graph import build_graph  # noqa: F401

__all__ = [
    "ProcessPhase",
    "WorkflowState",
    "WORKFLOW_PHASES",
    "PhaseDefinition",
    "supervisor_node",
    "supervisor_router",
    "build_graph",
]
