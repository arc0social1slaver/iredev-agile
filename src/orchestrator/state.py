"""
state.py

WorkflowState – single source of truth flowing through the LangGraph graph.
SystemPhase   – top-level phases of the workflow (hard sequential progression).
ProcessPhase  – knowledge-retrieval scopes used by ThinkModule.

Design
──────
Phases advance strictly in sequence (hard flow):
  Sprint Zero Planning → Sprint Execution → Sprint Review

Within each phase, routing is artifact-driven:
  The supervisor inspects (system_phase, artifacts) and selects the next
  ArtifactStep whose prerequisites are met but whose output is absent.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# SystemPhase – top-level phase sequencing (hard flow between phases)
# ---------------------------------------------------------------------------

class SystemPhase(str, Enum):
    """
    Top-level workflow phases.  Progress is strictly sequential: once a phase
    is complete (all its artifact steps are done) the workflow advances to the
    next phase and never returns.
    """
    SPRINT_ZERO_PLANNING = "sprint_zero_planning"   # discovery + initial backlog
    SPRINT_EXECUTION     = "sprint_execution"        # sprint N iterations
    SPRINT_REVIEW        = "sprint_review"           # review + retrospective


# ---------------------------------------------------------------------------
# ProcessPhase – knowledge-retrieval scopes (used by ThinkModule internally)
# ---------------------------------------------------------------------------

class ProcessPhase(str, Enum):
    """Scopes used by KnowledgeModule / ThinkModule for retrieval filtering."""
    ELICITATION   = "elicitation"
    ANALYSIS      = "analysis"
    SPECIFICATION = "specification"
    VALIDATION    = "validation"


# ---------------------------------------------------------------------------
# Typed conversation turn
# ---------------------------------------------------------------------------

class ConversationTurn(TypedDict):
    role:      str   # "interviewer" | "enduser"
    content:   str
    timestamp: str


# ---------------------------------------------------------------------------
# WorkflowState
#
# Every node receives the full state and returns a *partial* dict that
# LangGraph merges via reducer.  Fields are total=False (all optional) so
# nodes only need to return the keys they actually change.
# ---------------------------------------------------------------------------

class WorkflowState(TypedDict, total=False):

    # ── session ──────────────────────────────────────────────────────────
    session_id:          str
    project_description: str   # raw brief provided by the user / caller

    # ── phase management (hard sequential flow) ───────────────────────────
    # Stores a SystemPhase value (string).  Defaults to SPRINT_ZERO_PLANNING
    # when absent.  Updated by the supervisor when the phase advances.
    system_phase: str

    # ── artifact store (artifact-driven intra-phase routing) ──────────────
    # All produced artifacts live here, keyed by their logical name.
    # e.g. {"interview_record": {...}, "product_backlog": {...}}
    artifacts:    Dict[str, Any]

    # Optional parallel store of LangGraph store IDs for cross-session lookup.
    artifact_ids: Dict[str, str]

    # ── supervisor routing signal ─────────────────────────────────────────
    # Set by supervisor_node; read by supervisor_router to pick the next edge.
    next_node: str

    # ── interview sub-state (Sprint Zero – step 1) ────────────────────────
    conversation:       List[ConversationTurn]
    turn_count:         int
    max_turns:          int
    interview_complete: bool   # set True by InterviewerAgent._tool_write_interview_record

    # ── human-review gate ─────────────────────────────────────────────────
    awaiting_review: bool
    review_approved: bool
    review_feedback: Optional[str]

    # ── error accumulation ────────────────────────────────────────────────
    errors: List[str]