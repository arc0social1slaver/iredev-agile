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

Requirements elicitation sub-state
───────────────────────────────────
``requirements_draft`` is the live, incrementally-updated requirement list
maintained by InterviewerAgent throughout the interview loop.
  • Populated by: InterviewerAgent._tool_update_requirements  (per turn)
  • Finalised by: InterviewerAgent._tool_write_interview_record
    (copies draft → interview_record artifact; does NOT clear the draft)

Each item follows the schema:
  {
    "id":          "FR-001" | "NFR-001" | "CON-001",
    "type":        "functional" | "non_functional" | "constraint",
    "description": "<precise, testable statement>",
    "priority":    "high" | "medium" | "low",
    "source_turn": <int, 0-based index in conversation list>,
    "status":      "confirmed" | "inferred" | "ambiguous",
    "rationale":   "<why this requirement was identified — evidence from the
                     stakeholder's exact words, business goal, or constraint
                     it addresses; also records any modification reason>",
    "history":     [                          # populated on every edit
                     {
                       "action":    "created" | "modified" | "conflict_flagged",
                       "turn":      <int>,
                       "reason":    "<brief explanation of the change>",
                       "old_value": "<previous description, if modified>",
                     }, ...
                   ]
  }
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

    # ── Session ───────────────────────────────────────────────────────────
    session_id:          str
    project_description: str   # raw brief provided by the user / caller

    # ── Phase management (hard sequential flow) ───────────────────────────
    # Stores a SystemPhase value (string).  Defaults to SPRINT_ZERO_PLANNING
    # when absent.  Updated by the supervisor when the phase advances.
    system_phase: str

    # ── Artifact store (artifact-driven intra-phase routing) ──────────────
    # All produced artifacts live here, keyed by their logical name.
    # e.g. {"interview_record": {...}, "reviewed_interview_record": {...},
    #        "product_backlog": {...}}
    artifacts:    Dict[str, Any]

    # Optional parallel store of LangGraph store IDs for cross-session lookup.
    artifact_ids: Dict[str, str]

    # ── Supervisor routing signal ─────────────────────────────────────────
    # Set by supervisor_node; read by supervisor_router to pick the next edge.
    next_node: str

    # ── Interview sub-state (Sprint Zero – step 1) ────────────────────────
    conversation:       List[ConversationTurn]
    turn_count:         int
    max_turns:          int
    interview_complete: bool   # set True by InterviewerAgent._tool_write_interview_record

    # ── Live requirements draft (Sprint Zero – step 1) ────────────────────
    # Incrementally built by InterviewerAgent._tool_update_requirements.
    # Each entry: {id, type, description, priority, source_turn, status,
    #              rationale, history}
    # Copied into interview_record["requirements_identified"] when finalised.
    # Persists in state for downstream inspection (e.g. SprintAgent).
    requirements_draft: List[Dict[str, Any]]

    # ── Live backlog draft (Sprint Zero – step 3) ─────────────────────────
    # Incrementally built by SprintAgent tools (triage, split, validate, prioritize).
    # Each entry: {id, title, description, story_points, status, wsjf_score, history, ...}
    # Copied into product_backlog["items"] when finalised.
    backlog_draft: List[Dict[str, Any]]

    # ── Human-review gate (Sprint Zero – step 2: review_interview_record) ─
    # Set by the review_turn node via LangGraph interrupt().
    # review_feedback is injected back into the InterviewerAgent's task prompt
    # when the interview restarts after a rejection so the agent knows what
    # to improve.
    awaiting_review: bool
    review_approved: bool
    review_feedback: Optional[str]   # populated on rejection; None on approval

    # ── Error accumulation ────────────────────────────────────────────────
    errors: List[str]