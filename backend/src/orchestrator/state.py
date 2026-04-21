"""
state.py

WorkflowState – single source of truth flowing through the LangGraph graph.

Artifact chain
──────────────
Phase 1 (sprint_zero_planning):
  interview_record → reviewed_interview_record → product_backlog
  → product_backlog_approved

Phase 2 (backlog_refinement):
  validated_product_backlog → analyst_review_done

Stopping mechanism (two-tier, Interviewer-only)
───────────────────────────────────────────────
Only InterviewerAgent can set interview_complete=True.  EndUserAgent has no
mechanism to end the interview.

TIER 2 — Marginal Information Gain per domain (primary semantic gate):
  Tracked via goal_tracker (see below).  After each update_requirements call,
  the agent computes an ig_score per zone.  When all required zones have
  ig_score == 0.0 (≥ 3 consecutive calls with no new requirements), Tier 2
  signals saturation.  The Interviewer's [STRATEGY] block interprets this
  and decides whether to finalise.

TIER 3 — Metacognitive Coherence Check (secondary gate):
  Enforced entirely inside the Interviewer's [STRATEGY] block.  Before calling
  write_interview_record, the agent must explicitly answer: "Could a software
  engineer start designing from this requirements list without further questions?"
  If the answer is no, the agent must continue probing regardless of Tier 2.

Requirements schema
───────────────────
Each item in requirements_draft:
  {
    "id":          "FR-001" | "NFR-001" | "CON-001",
    "type":        "functional" | "non_functional" | "constraint",
    "description": "<precise, testable statement>",
    "priority":    "high" | "medium" | "low",
    "source_turn": <int, 0-based conversation index>,
    "status":      "confirmed" | "inferred" | "ambiguous",
    "rationale":   "<why identified — cites stakeholder words + [STRATEGY] reasoning>",
    "history":     [
                     {
                       "action":    "created" | "modified" | "deleted"
                                    | "hitl_modified" | "hitl_added" | "hitl_deleted",
                       "turn":      <int>,
                       "reason":    "<explanation — for HITL actions, includes reviewer feedback>",
                       "old_value": "<previous value if modified>",
                     }, ...
                   ]
  }

goal_tracker schema
───────────────────
  {
    "<zone_id>": {
      "consecutive_dry_calls": <int>,   # update_requirements calls with 0 new reqs for this zone
      "total_calls":           <int>,   # total update_requirements calls so far
      "last_new_req_turn":     <int>,   # conversation turn when last new req was mapped here
      "ig_score":              <float>, # 0.0–1.0; 0.0 = zone saturated (Tier-2 signal)
    },
    ...
  }
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class SystemPhase(str, Enum):
    SPRINT_ZERO_PLANNING = "sprint_zero_planning"
    BACKLOG_REFINEMENT   = "backlog_refinement"
    SPRINT_EXECUTION     = "sprint_execution"
    SPRINT_REVIEW        = "sprint_review"


class ProcessPhase(str, Enum):
    ELICITATION   = "elicitation"
    ANALYSIS      = "analysis"
    SPECIFICATION = "specification"
    VALIDATION    = "validation"


class ConversationTurn(TypedDict):
    role:      str
    content:   str
    timestamp: str


class WorkflowState(TypedDict, total=False):

    # ── Session ────────────────────────────────────────────────────────────
    session_id:          str
    project_description: str

    # ── Phase management ───────────────────────────────────────────────────
    system_phase: str

    # ── Artifact store ─────────────────────────────────────────────────────
    artifacts:    Dict[str, Any]
    artifact_ids: Dict[str, str]

    # ── Supervisor routing ─────────────────────────────────────────────────
    next_node: str

    # ── Interview sub-state ────────────────────────────────────────────────
    conversation:       List[ConversationTurn]
    turn_count:         int
    max_turns:          int
    interview_complete: bool

    # ── Requirements draft ─────────────────────────────────────────────────
    requirements_draft: List[Dict[str, Any]]

    # ── Coverage map ───────────────────────────────────────────────────────
    coverage_map: Dict[str, Any]

    # ── Goal tracker ───────────────────────────────────────────────────────
    goal_tracker: Dict[str, Any]

    # ── Conflict and dependency logs ───────────────────────────────────────
    conflict_log:     List[Dict[str, Any]]
    dependency_graph: Dict[str, Any]

    # ── Backlog draft (SprintAgent working list during build_product_backlog)
    backlog_draft: List[Dict[str, Any]]

    # ── Sprint Zero HITL ───────────────────────────────────────────────────
    awaiting_review:  bool
    review_approved:  bool
    # review_feedback: injected on interview_record rejection
    review_feedback:  Optional[str]
    # product_backlog_feedback: injected on product_backlog rejection
    product_backlog_feedback: Optional[str]

    # ── Phase 2: Backlog Refinement ────────────────────────────────────────
    # analyst_feedback: injected on validated_product_backlog rejection
    analyst_feedback: Optional[str]

    # AnalystAgent transient accumulators (within a single ReAct turn)
    _invest_scratch: List[Dict[str, Any]]   # output of check_invest_quality
    _ac_scratch:     List[Dict[str, Any]]   # output of write_acceptance_criteria

    # ── ReAct internals (transient) ────────────────────────────────────────
    _last_react_thought:        str
    _react_strategy:            str
    _update_req_done_this_turn: bool
    readiness_approved:         bool

    # ── UI signalling (transient, consumed by ws_handler) ──────────────────
    _workflow_started_message: bool

    # ── Error accumulation ─────────────────────────────────────────────────
    errors: List[str]