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

Three-Stage Elicitation (InterviewerAgent v3)
─────────────────────────────────────────────
Stage 0 — Matrix Synthesis:
  InterviewerAgent reads project_description and builds a domain × stakeholder
  matrix. Each domain = epic-level feature area. Each cell = one elicitation thread.

Stage 1 — 5W1H Elicitation (per cell):
  For each (domain, stakeholder) pair:
    • WHAT  — extracted from project_description on first turn
    • WHO   — the stakeholder of this cell (auto-populated)
    • WHEN  — probing question 1
    • WHERE — probing question 2 (skipped if irrelevant)
    • WHY   — probing question 3 (rationale / business value)
    • HOW   — probing question 4 (acceptance criteria)
  EndUserAgent responds. update_requirements called after each reply.

Stage 2 — Conflict Resolution (Interviewer only, no EndUser):
  Interviewer groups requirements by domain, detects cross-stakeholder
  contradictions, and resolves via priority rules:
    constraint > preference  |  policy > wish
  Unresolvable → status = "ambiguous", conflict_note added.

Stage 3 — Export:
  write_interview_record → interview_record artifact.

Requirements schema (v3 — 5W1H extended)
─────────────────────────────────────────
Each item in requirements_draft:
  {
    "id":            "FR-001" | "NFR-001" | "CON-001",
    "type":          "functional" | "non_functional" | "constraint",
    "description":   "<precise, testable statement>",
    "priority":      "high" | "medium" | "low",
    "source_turn":   <int, 0-based conversation index>,
    "status":        "confirmed" | "inferred" | "ambiguous",
    "rationale":     "<why identified — cites stakeholder words>",

    # 5W1H fields
    "who":    "<stakeholder — auto-filled from matrix cell>",
    "when":   "<timing context, e.g. 'when logging in each day'> | null",
    "where":  "<environment / surface, e.g. 'on the dashboard'> | null",
    "why":    "<business rationale, e.g. 'to maintain study consistency'> | null",
    "how":    ["Given ...", "When ...", "Then ..."]  # acceptance criteria | null,

    # Domain grouping (from matrix cell)
    "domain":        "<epic-level feature area>",

    # Conflict annotation (Stage 2)
    "conflict_note": "<description of cross-stakeholder conflict> | null",

    "history": [
                  {
                    "action":    "created" | "modified" | "deleted"
                                 | "hitl_modified" | "hitl_added" | "hitl_deleted",
                    "turn":      <int>,
                    "reason":    "<explanation>",
                    "old_value": "<previous value if modified>",
                  }, ...
                ]
  }

matrix_cursor schema
─────────────────────
  {
    "domain_list":      ["Epic A", "Epic B", ...],   # ordered list of all domains
    "domain_idx":       <int>,                        # current domain position
    "stakeholder_idx":  <int>,                        # current stakeholder position
    "w_asked":          ["scenario", "how"],           # required elicitation dimensions asked for current cell
                                                       # Valid values: "scenario" | "how"
                                                       # Cell is complete (min coverage) when both are present.
    "probe_count":      <int>,                        # number of optional probe turns sent this cell (max 2)
    "cell_turn_count":  <int>,                        # total turns used in current cell (scenario=1, how=2,
                                                       # probes=3-4). HARD LIMIT: advance_cursor is mandatory
                                                       # when cell_turn_count >= 4, no exceptions.
  }

cell_requirements schema
─────────────────────────
  {
    "<domain>|<stakeholder>": ["FR-001", "NFR-002", ...],
    ...
  }
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


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

    # ── Agenda-driven elicitation (InterviewerAgent v4) ───────────────────
    # Serialised ProductVision dict produced by Pass 1 of InterviewerAgent.
    # Persisted here so LangGraph checkpoints it between turns.
    product_vision: Dict[str, Any]

    # Serialised AgendaRuntime dict:
    #   { items: [...], current_index: int, elicitation_complete: bool }
    # Each item: { item_id, source_field, source_ref, elicitation_goal,
    #              priority, status, question_asked, answer_received }
    elicitation_agenda: Dict[str, Any]

    # Handshake keys between InterviewerAgent and EndUserAgent.
    # InterviewerAgent writes current_question via ask_question tool.
    # EndUserAgent reads current_question, writes enduser_answer via respond tool.
    # InterviewerAgent reads enduser_answer via record_answer tool.
    current_question: str
    enduser_answer:   str

    # Final summary written by the conclude tool.
    # Format: one block per answered item — "Q: ...\nA: ..."
    elicitation_notes: str

    # ── Requirements draft (v3 — 5W1H extended schema) ─────────────────────
    requirements_draft: List[Dict[str, Any]]

    # ── Three-stage elicitation (InterviewerAgent v3) ──────────────────────
    # domain × stakeholder matrix: {"Epic Name": ["Stakeholder1", "Stakeholder2"]}
    domain_stakeholder_matrix: Dict[str, List[str]]

    # cursor tracking current position in the matrix
    matrix_cursor: Dict[str, Any]

    # current stage: "matrix_gen" | "elicitation" | "domain_conflict_resolution"
    #                | "conflict_resolution" | "done"
    elicitation_stage: str

    # per-cell requirement IDs: {"domain|stakeholder": ["FR-001", ...]}
    cell_requirements: Dict[str, List[str]]

    # ── Conflict log (Stage 2 output) ──────────────────────────────────────
    conflict_log: List[Dict[str, Any]]

    # ── Dependency graph ───────────────────────────────────────────────────
    dependency_graph: Dict[str, Any]

    # ── Backlog draft (SprintAgent working list) ───────────────────────────
    backlog_draft: List[Dict[str, Any]]

    # ── Sprint Zero HITL ───────────────────────────────────────────────────
    review_feedback:              Optional[str]   # feedback for interview_record re-run
    product_vision_feedback:      Optional[str]   # feedback for product_vision revision
    elicitation_agenda_feedback:  Optional[str]   # feedback for elicitation_agenda rebuild
    requirement_list_feedback:    Optional[str]   # feedback for requirement_list revision
    product_backlog_feedback:     Optional[str]

    # ── Phase 2: Backlog Refinement ────────────────────────────────────────
    analyst_feedback: Optional[str]

    # AnalystAgent transient accumulators
    _invest_scratch: List[Dict[str, Any]]
    _ac_scratch:     List[Dict[str, Any]]

    # ── ReAct internals (transient) ────────────────────────────────────────
    _last_react_thought:        str
    _react_strategy:            str
    _update_req_done_this_turn: bool
    readiness_approved:         bool

    # Set by _tool_conclude; tells process() to run _synthesise_srs() on the
    # very next invocation (no EndUser turn in between).
    # Cleared by _synthesise_srs() after synthesis succeeds or fails.
    # MUST be declared here so LangGraph persists it across turns.
    _needs_srs_synthesis:       bool

    # Set by record_answer tool; tells after_interviewer to retry
    # interviewer_turn instead of routing to enduser_turn.
    # Cleared implicitly when interviewer_turn runs and ask_question fires.
    _agenda_needs_question:     bool
    _agenda_needs_followup: bool

    # Domain-batching transition controls
    pending_domain_transition:  Dict[str, Any]
    _domain_memory_cleared:     bool
    resolved_domains:           List[str]

    # Compact cross-domain persona constraints keyed by stakeholder
    stakeholder_context_summary: Dict[str, List[str]]

    # ── UI signalling (transient) ──────────────────────────────────────────
    _workflow_started_message: bool

    # ── Error accumulation ─────────────────────────────────────────────────
    errors: List[str]