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

Sprint Zero artifact chain (6 steps)
──────────────────────────────────────
  1. conduct_requirements_interview → interview_record
  2. review_interview_record        → reviewed_interview_record
  3. build_product_backlog          → product_backlog
  4. review_product_backlog         → reviewed_product_backlog
  5. plan_sprint_backlog            → sprint_backlog_<N>
  6. review_sprint_backlog          → reviewed_sprint_backlog_<N>

Sprint planning sub-state
──────────────────────────
``sprint_feedback`` carries the human planner's inputs for Pipeline B:
  {
    "sprint_goal":        "<one-sentence goal>",
    "capacity_points":    <int>,
    "completed_pbi_ids":  ["PBI-xxx", ...],
    "plan_another":       <bool>,
    "notes":              "<optional planner notes>"
  }

``sprint_draft`` is the working list of PBIs being planned (Pipeline B).
Seeded from product_backlog["items"] on first sprint, then reused across
multiple sprints within a session.

``current_sprint_number`` tracks which sprint is being planned (1-based int).
Incremented by sprint_feedback_turn before each new sprint.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# SystemPhase – top-level phase sequencing (hard flow between phases)
# ---------------------------------------------------------------------------

class SystemPhase(str, Enum):
    SPRINT_ZERO_PLANNING = "sprint_zero_planning"
    SPRINT_EXECUTION     = "sprint_execution"
    SPRINT_REVIEW        = "sprint_review"


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
# ---------------------------------------------------------------------------

class WorkflowState(TypedDict, total=False):

    # ── Session ───────────────────────────────────────────────────────────
    session_id:          str
    project_description: str

    # ── Phase management ──────────────────────────────────────────────────
    system_phase: str

    # ── Artifact store ────────────────────────────────────────────────────
    artifacts:    Dict[str, Any]
    artifact_ids: Dict[str, str]

    # ── Supervisor routing signal ─────────────────────────────────────────
    next_node: str

    # ── Interview sub-state (step 1) ──────────────────────────────────────
    conversation:       List[ConversationTurn]
    turn_count:         int
    max_turns:          int
    interview_complete: bool

    # ── Live requirements draft (step 1) ──────────────────────────────────
    requirements_draft: List[Dict[str, Any]]

    # ── Live backlog draft (step 3) ───────────────────────────────────────
    backlog_draft: List[Dict[str, Any]]

    # ── Human-review gate: interview record (step 2) ───────────────────────
    awaiting_review: bool
    review_approved: bool
    review_feedback: Optional[str]

    # ── Human-review gate: product backlog (step 4) ────────────────────────
    # On rejection: product_backlog removed from artifacts; feedback set so
    # SprintAgent rebuilds the backlog with the reviewer's comments.
    product_backlog_review_approved: bool
    product_backlog_feedback:        Optional[str]

    # ── Sprint planning sub-state (step 5) ────────────────────────────────
    # sprint_feedback_turn collects the human planner's inputs before
    # SprintAgent Pipeline B runs.  The sentinel "_sprint_feedback_ready"
    # (written into artifacts) tells SprintAgent.process() to run Pipeline B.
    sprint_feedback:       Optional[Dict[str, Any]]
    current_sprint_number: int
    sprint_draft:          List[Dict[str, Any]]

    # ── Human-review gate: sprint backlog (step 6) ────────────────────────
    # On rejection: sprint_backlog_N removed from artifacts; feedback set so
    # SprintAgent replans; _sprint_feedback_ready re-added to trigger replan.
    sprint_backlog_review_approved: bool
    sprint_backlog_feedback:        Optional[str]

    # ── Error accumulation ────────────────────────────────────────────────
    errors: List[str]