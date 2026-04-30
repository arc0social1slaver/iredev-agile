"""
interviewer.py – InterviewerAgent (Agenda-driven elicitation)

Elicitation flow
────────────────────────────────────────────────────────────────────────────
Turn 1 — Bootstrap (runs once):
  Pass 1: extract_structured(ProductVision)    → state["product_vision"]
  Pass 2: extract_structured(ElicitationAgenda) → state["elicitation_agenda"]
  Return early so LangGraph checkpoints state before ReAct starts.

Turn N (N > 1) — Elicitation loop:
  react() runs with only the CURRENT agenda item injected as context.
  Tools:
    record_answer   – write EndUser's reply into the current item, optionally
                      trigger a follow-up if the answer is rich (3+ concerns).
                      Advances the agenda index only when follow-up is exhausted.
    ask_question    – generate and deliver the next question (should_return=True)
    conclude        – write interview_record artifact, set _needs_srs_synthesis=True

Turn LAST — SRS Synthesis (runs once, no ReAct):
  Triggered when _needs_srs_synthesis=True in state.
  _synthesise_srs() runs a 4-pass pipeline:

    Pass 1 — FR Extraction:
      Inputs:  project_description + elicitation Q&A (including elicitation_goal per item)
      Output:  List[Requirement] — functional requirements only.
      Key rule: CoT via reasoning_log — every FR must be anchored in a stakeholder
                quote and a concrete user outcome. Echoes of the project description
                with no new stakeholder detail are marked status="inferred".

    Pass 2 — NFR & CON Extraction:
      Inputs:  same as Pass 1
      Output:  List[Requirement] — non-functional, constraints, out-of-scope.
      Key rule: CoT via reasoning_log — pre-classification table forces WHAT vs
                HOW WELL decision and measurable threshold per NFR candidate.

    Pass 3 — Coverage Check:
      Inputs:  project_description + all requirements from Passes 1+2
      Output:  List[Requirement] — gap-filling items for uncovered PD bullets.
               All stamped source_elicitation_id="PD", status="inferred".
               Dimension [G] catches tension-resolution gaps from [follow-up] blocks.

    Pass 4 — Quality Gate + Final Assembly:
      Inputs:  full draft from Passes 1–3 + session metadata
      Output:  SoftwareRequirementsSpecification — audited, renumbered, ordered.
      Checks:  Step 0.5 User Value Gate (echo FRs rewritten or downgraded),
               atomicity, testability, vague language sweep,
               null context on FRs, duplicate statements.

  Sets interview_complete=True and clears _needs_srs_synthesis.

Stopping condition
──────────────────
Natural: _needs_srs_synthesis=True triggers synthesis pass → interview_complete=True.

Follow-up mechanism (Fix 3)
────────────────────────────
AgendaRuntimeItem gains two fields:
  followup_asked:   bool — True after the first follow-up question is delivered.
  followup_answer:  Optional[str] — appended into answer_received before advance.

When record_answer fires and the current item's answer contains 3+ distinct
concerns AND followup_asked=False, the tool sets _agenda_needs_followup=True
instead of _agenda_needs_question=True.  _build_task() injects a FOLLOW-UP
CONTEXT block so the interviewer narrows into the richest concern.  After the
follow-up answer arrives, record_answer appends it, clears the flag, and
advances normally.  Hard limit: exactly one follow-up per item, no chaining.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional
from pathlib import Path
from datetime import datetime
import json
import re

from pydantic import BaseModel, Field

from .base import BaseAgent, Tool, ToolResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class StakeholderEntry(BaseModel):
    role: str = Field(
        description=(
            "The name of ONE individual stakeholder or stakeholder group as it appears "
            "in the project description. One entry per named individual or group.\n"
            "NEVER combine multiple distinct stakeholders into a comma-separated string. "
            "If the PD lists multiple named roles under a single category label, each "
            "becomes a separate StakeholderEntry with its own role string. The category "
            "label determines the type field but is not the role name."
        )
    )
    type: Literal["primary_user", "secondary_user", "beneficiary", "decision_maker", "blocker"] = Field(
        description=(
            "primary_user   – directly operates the system as the main audience.\n"
            "secondary_user – uses the system occasionally or in a supporting role. "
            "They interact with the system but are not the primary audience.\n"
            "beneficiary    – gains value without directly using the system.\n"
            "decision_maker – approves scope, budget, or direction.\n"
            "blocker        – can veto or block the project."
        )
    )
    key_concern: str = Field(
        description="The single most important need or worry this stakeholder has."
    )
    influence_level: Literal["high", "medium", "low"] = Field(
        description="How much this stakeholder can shape or derail the project."
    )


class Assumption(BaseModel):
    statement: str = Field(
        description="The assumption stated as a plain declarative sentence."
    )
    risk_if_wrong: str = Field(
        description="One sentence describing the consequence if this assumption is false."
    )
    needs_validation: bool = Field(
        description=(
            "True if a false assumption would materially change scope, architecture, "
            "or user trust before or during development. "
            "Assumptions with needs_validation=true generate high-priority agenda items."
        )
    )


class ProductVision(BaseModel):
    """
    North Star artifact produced at the start of elicitation.

    Scope: vision-level fields only — core problem, value proposition, stakeholders,
    assumptions, constraints, evaluation criteria, and out-of-scope items.

    Intentionally omitted (extracted downstream by the agenda agent from the
    project description text directly):
      - initial_requirements  → agenda items with source_field="initial_requirement"
      - non_functional_requirements → agenda items with source_field="non_functional_requirement"
    """

    target_audiences: List[StakeholderEntry] = Field(
        description="All relevant stakeholder groups, typed and ranked by influence."
    )
    core_problem: str = Field(
        description=(
            "The underlying tension the project must resolve, stated as the primary "
            "pain point. Names two competing forces, not just an observable symptom."
        )
    )
    value_proposition: str = Field(
        description=(
            "The outcome delivered to users when the core tension is resolved. "
            "Describes what changes for the user, not what the system does."
        )
    )
    evaluation_criteria: List[str] = Field(
        default_factory=list,
        description="Specific measurable design or testing expectations ACTUALLY stated in the project description. Extract only items that appear verbatim or are clearly declared."
    )
    project_constraints: List[str] = Field(
        default_factory=list,
        description="Hard delivery limits explicitly stated in the project description: timeline, budget, methodology, tooling, team size, or other non-negotiable conditions."
    )
    assumptions: List[Assumption] = Field(
        description=(
            "Implicit beliefs that must be true for the solution to work, "
            "but are not confirmed anywhere in the project description. "
            "Each carries a risk_if_wrong consequence and a needs_validation flag."
        )
    )

    out_of_scope: List[str] = Field(
        description=(
            "Capabilities explicitly excluded from the system. "
            "Each item names something a stakeholder might reasonably expect to be included "
            "but which the project explicitly rejects."
        )
    )
    reasoning_log: str = Field(
        description=(
            "Chain-of-thought scratchpad. Records the five reasoning steps "
            "(tension + stakeholder value map, success condition, boundaries, "
            "capability & quality scan, stakeholder inventory) before any "
            "other field is populated. "
            "Used for debugging and quality review; not shown to end users."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
class AgendaItem(BaseModel):
    item_id: str = Field(
        description=(
            "Unique identifier using the canonical prefix for each source_field:\n"
            "  source_field=assumption              → assumption_N\n"
            "  source_field=stakeholder_concern     → stakeholder_N\n"
            "  source_field=project_constraint      → hard_constraint_N\n"
            "  source_field=non_functional_requirement → nfr_N\n"
            "  source_field=out_of_scope            → out_of_scope_N\n"
            "  source_field=initial_requirement     → initial_req_N\n"
            "  source_field=evaluation_criterion    → eval_criterion_N\n"
            "N is a zero-based index within each category."
        )
    )
    source_field: Literal[
        "assumption",
        "stakeholder_concern",
        "project_constraint",
        "non_functional_requirement",
        "out_of_scope",
        "initial_requirement",
        "evaluation_criterion",
    ] = Field(
        description=(
            "Classification of the item based on its source and the Q1→Q4 decision test.\n\n"
            "TWO SOURCES — each type has exactly one source:\n\n"
            "  From Vision JSON (structural reading):\n"
            "    assumption, stakeholder_concern, project_constraint,\n"
            "    evaluation_criterion, out_of_scope.\n\n"
            "  From Project Description text (semantic reading):\n"
            "    initial_requirement     → binary capability in PD (Q4 = YES).\n"
            "    non_functional_requirement → quality on a spectrum in PD (Q3 = YES).\n"
            "    Vision excluded these intentionally. Read PD text only.\n"
            "    The PD Extraction Audit (enumerate → classify → tally) ensures\n"
            "    these are not missed."
        )
    )
    source_ref: str = Field(
        description=(
            "Traceability link to the source material. Two valid forms:\n"
            "  Form 1 — Verbatim: copy the exact sentence or bullet from the ProductVision\n"
            "    JSON or project description that triggered this item. Use whenever a\n"
            "    source sentence exists.\n"
            "  Form 2 — Inferred gap: write 'No assumption recorded about [risk area].\n"
            "    This item surfaces a project-threatening blind spot not addressed in\n"
            "    the current ProductVision.' Use only when no verbatim source exists\n"
            "    but the risk is significant enough that omitting it could cause the\n"
            "    project to fail silently."
        )
    )
    elicitation_goal: str = Field(
        description=(
            "The specific user pain, need, or value this item must surface — not a system\n"
            "specification to confirm. Must pass the stakeholder VALUE LENS: what does the\n"
            "stakeholder value, and how could this item fail that value?\n\n"
            "Every goal must satisfy all of:\n"
            "  1. Names a user pain, need, or value (not a system property or spec decision)\n"
            "  2. States the evidence the interviewer must hear to write a testable requirement\n"
            "  3. Specific enough that a draft acceptance criterion can be written after the answer\n"
            "  4. Domain-specific — cannot be copy-pasted unchanged to a different project\n\n"
            "Framing is derived from what KIND of thing the item is (concept-driven):\n"
            "  Capability (Q4) → surface the ACTIVITY and FRICTION, not the feature spec.\n"
            "  Quality (Q3) → surface the FAILURE MOMENT and TRUST THRESHOLD, not metrics.\n"
            "  Constraint (Q1) → surface the IMPACT ON THE USER, not the constraint definition.\n"
            "  Assumption → surface the CONCRETE FAILURE SCENARIO, not mitigation plans.\n\n"
            "Banned framing (spec questions disguised as elicitation):\n"
            "  'Identify what criteria...', 'Define what types...', 'Clarify what specific...',\n"
            "  'Determine the [property]...', 'Explore what defines...'"
        )
    )
    priority: Literal["high", "medium", "low"] = Field(
        description=(
            "high   = assumption (needs_validation=true) | initial_requirement |\n"
            "         stakeholder_concern where the stakeholder's veto or approval\n"
            "         is on the critical path (decision_maker or blocker gating delivery).\n"
            "medium = project_constraint | non_functional_requirement |\n"
            "         evaluation_criterion | stakeholder_concern (default).\n"
            "low    = out_of_scope."
        )
    )
    stakeholders: List[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of stakeholder roles whose perspective must be captured for this item. "
            "Values must be EXACT role strings from ProductVision.target_audiences[].role. "
            "Order by relevance: most directly affected role first. "
            "Every item must have at least one stakeholder. "
            "An item with multiple stakeholders generates one question per role; "
            "all answers are collected before the item is marked answered. "
            "List only roles whose perspective genuinely adds distinct information — "
            "maximum three roles per item."
        )
    )


class ElicitationAgenda(BaseModel):
    """
    Ordered list of elicitation items produced by the agenda extraction agent.

    The agenda agent receives two inputs and processes them in strict sequence
    to prevent working memory overload:

      Phase 2 — PD text first (semantic reading):
        Source for: initial_requirement (Q4), non_functional_requirement (Q3).
        Vision excluded these intentionally. Extracted via the 3-substep PD
        Extraction Audit (enumerate → classify → tally) BEFORE opening
        the Vision JSON.

      Phase 3 — Vision JSON second (structural reading):
        Source for: assumption, project_constraint, evaluation_criterion,
        out_of_scope, stakeholder_concern (from target_audiences[]).
        Cross-source dedup runs AFTER both inventories are complete.

    Stakeholder coverage is resolved in Phase 4 (EMBED-GATE):
      decision_maker and blocker → standalone. primary_user, secondary_user,
      beneficiary → embedded into initial_req/nfr/eval_criterion host items
      when the host genuinely addresses their key_concern. Standalone only
      when no host qualifies.

    Items are ordered high → medium → low priority.
    """
    items: List[AgendaItem] = Field(
        description=(
            "One item per elicitation need. Two inputs processed in strict sequence:\n\n"
            "  Phase 2 — PD text first (semantic reading) → source for:\n"
            "    initial_requirement (Q4 capability), non_functional_requirement (Q3 quality).\n"
            "    Extracted via the 3-substep PD Extraction Audit (enumerate → classify\n"
            "    → tally) BEFORE opening the Vision JSON. A project with capability\n"
            "    bullets in the PD must produce initial_requirement items.\n\n"
            "  Phase 3 — Vision JSON second (structural reading) → source for:\n"
            "    assumption, project_constraint, evaluation_criterion,\n"
            "    out_of_scope, stakeholder_concern.\n\n"
            "Stakeholder coverage (Phase 4 EMBED-GATE):\n"
            "  decision_maker, blocker  → always standalone stakeholder_N items.\n"
            "  primary_user, secondary_user, beneficiary → embedded into host items\n"
            "    (initial_req, nfr, eval_criterion) when the host's elicitation_goal\n"
            "    genuinely surfaces their key_concern.\n\n"
            "Priority order: high → medium → low."
        )
    )
    reasoning_log: str = Field(
        description=(
            "Chain-of-thought scratchpad written before the items array is populated.\n"
            "Records all six reasoning phases in strict sequence:\n"
            "  Phase 1 — Read for tension.\n"
            "  Phase 2 — PD Extraction (PD text only, Vision JSON not yet opened):\n"
            "    Substep A (raw enumeration), Substep B (Q1→Q4 classification),\n"
            "    Substep C (tally and lock).\n"
            "  Phase 3 — Vision JSON inventory (structural reading, then cross-source dedup).\n"
            "  Phase 4 — Coverage map & stakeholder embedding (EMBED-GATE).\n"
            "  Phase 5 — Draft all items with VALUE LENS reasoning per goal,\n"
            "    concept-driven framing, blind spot audit.\n"
            "  Phase 6 — Audit: duplication, missing risk, goal precision, coverage.\n"
            "Used for debugging and quality review; not shown to end users."
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# SRS schemas  (synthesis step — final turn)
# ─────────────────────────────────────────────────────────────────────────────

class Requirement(BaseModel):
    """
    One atomic software requirement derived from elicitation evidence.

    req_id       – Stable traceability key. Prefix encodes type:
                   FR-NNN functional | NFR-NNN non-functional |
                   CON-NNN constraint | OOS-NNN out-of-scope.

    req_type     – Routes downstream: FR → user story, NFR → DoD,
                   CON → sprint guard rail, OOS → anti-requirement.

    stakeholder  – 'Who': the role that expressed or is most affected by this
                   requirement. "All Users" when universal.

    statement    – 'What': precise, testable imperative — "The system SHALL …"
                   No implementation detail (no tech stack, no library names).

    context      – 'Where'/'When': trigger condition or UI surface. Null when
                   the requirement applies universally.

    rationale    – 'Why': must cite or closely paraphrase the stakeholder's own
                   words from the elicitation answer.

    acceptance_criteria – 'How': 1–3 Given-When-Then bullets for functional/NFR.
                          Empty list is valid for constraint and out_of_scope items.

    priority     – Inherited from elicitation priority unless the answer
                   contradicts it.

    source_elicitation_id – Foreign key back to the ElicitedItem (e.g. "EL-003")
                            or "PD" when the requirement is inferred from the
                            project description alone (Fix 2).

    status       – confirmed: explicitly stated by stakeholder.
                   inferred:  implied but not stated; reviewer must validate.
                   excluded:  out-of-scope; recorded as an anti-requirement.
    """
    req_id:                str = Field(
        description="Unique ID — FR-NNN, NFR-NNN, CON-NNN, or OOS-NNN. Sequential within each prefix."
    )

    req_type:              Literal["functional", "non_functional", "constraint", "out_of_scope"] = Field(
        description="Category that determines how SprintAgent handles this requirement downstream."
    )
    stakeholder:           str = Field(
        description="Primary role who expressed or is most affected by this requirement."
    )
    statement:             str = Field(
        description="Precise, testable imperative — 'The system SHALL …' or 'The system SHALL NOT …'. No solution detail."
    )
    context:               Optional[str] = Field(
        default=None,
        description="Trigger condition, UI surface, or timing. Null when the requirement is universal."
    )
    rationale:             str = Field(
        description=(
            "Justification grounded in stakeholder evidence. TWO parts, both required:\n"
            "  (a) PAIN — cite or paraphrase the stakeholder's own words about the current problem.\n"
            "  (b) OUTCOME — the concrete improvement the user achieves when this requirement is met "
            "      ('So that [user] can [outcome]'). If elicitation did not surface an explicit outcome, "
            "      infer the most plausible one and set status='inferred'.\n"
            "Format: '<pain statement>. So that <outcome statement>.'"
        )
    )
    acceptance_criteria:   List[str] = Field(
        default_factory=list,
        description="Given-When-Then bullets (1–3 for FR/NFR). Empty list for CON and OOS items."
    )
    priority:              Literal["high", "medium", "low"] = Field(
        description="Inherited from elicitation priority unless the answer shifts it."
    )
    source_elicitation_id: str = Field(
        description=(
            "EL-NNN — foreign key to the elicitation item that produced this requirement.\n"
            "Use 'PD' when the requirement is inferred from the project description "
            "but was not explicitly elicited (Fix 2)."
        )
    )
    status:                Literal["confirmed", "inferred", "excluded"] = Field(
        description="confirmed=explicitly stated; inferred=implied, needs review; excluded=out-of-scope."
    )


class SoftwareRequirementsSpecification(BaseModel):
    """
    Top-level Requirement List artifact written to artifacts['requirement_list'].

    requirements is ordered: functional → non_functional → constraint → out_of_scope,
    then high → medium → low within each group.
    """
    session_id:          str             = Field(description="Copied from WorkflowState.session_id.")
    project_description: str             = Field(description="Copied verbatim for self-contained traceability.")
    synthesised_at:      str             = Field(description="ISO-8601 timestamp of this synthesis pass.")
    reasoning_log:       str             = Field(
        default="",
        description=(
            "Pass 4 audit scratchpad. Record all audit decisions here: "
            "Step 3 vague language found, Step 5 duplicate verdicts, "
            "Step 7 status changes. This field is not shown to end users."
        )
    )
    requirements:        List[Requirement] = Field(
        description="All derived requirements, ordered by type then priority."
    )


class RequirementList(BaseModel):
    """Wrapper schema for Passes 1–3 so extract_structured enforces req_id."""
    reasoning_log: str = Field(
        description=(
            "Write your full chain of thought here BEFORE populating the requirements list. "
            "This is a mandatory scratchpad. For every elicitation item you process, record: "
            "(1) the specific pain the stakeholder expressed in their own words, "
            "(2) the concrete outcome the user gains when this need is met, "
            "(3) whether a candidate requirement describes a system behaviour (FR) or a "
            "quality attribute with a measurable threshold (NFR), and "
            "(4) whether the candidate is grounded in what the stakeholder actually said "
            "or is merely a paraphrase of the project description. "
            "Only requirements that pass all four checks are written into the requirements list. "
            "This field is not shown to end users but is used for quality review."
        )
    )
    requirements: List[Requirement] = Field(
        description="All requirements extracted in this pass."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Runtime state (stored in WorkflowState["elicitation_agenda"])
# ─────────────────────────────────────────────────────────────────────────────

class AgendaRuntimeItem(BaseModel):
    """AgendaItem extended with runtime tracking fields.

    Multi-stakeholder elicitation
    ──────────────────────────────
    Each item carries an ordered ``stakeholders`` list.  The runtime iterates
    through it one by one: for each role it asks the same elicitation_goal
    question, collects the answer into ``answers[role]``, then moves the cursor
    (``stakeholder_idx``) to the next role.  The item is only marked "answered"
    when all roles have been heard.

    ``interviewed_stakeholder_role`` still tracks the CURRENT role being
    interviewed (kept for backward-compat with synthesis passes that read it
    from the interview_record).  It is updated each time stakeholder_idx advances.

    ``answer_received`` is kept as a merged summary (all answers concatenated)
    so that existing synthesis passes (Passes 1-4) that read ``answer_received``
    see the full picture without modification.
    """
    item_id:                    str
    source_field:               str
    source_ref:                 str
    elicitation_goal:           str
    priority:                   str
    stakeholders:               List[str]     = Field(default_factory=list)
    status:                     Literal["pending", "answered", "skipped"] = "pending"
    question_asked:             Optional[str] = None
    answer_received:            Optional[str] = None

    # ── Multi-stakeholder runtime fields ──────────────────────────────────────
    # Per-role answer store: {"Role A": "...", "Role B": "..."}
    answers:                    Dict[str, str] = Field(default_factory=dict)
    # Index into stakeholders list — which role is being interviewed right now
    stakeholder_idx:            int            = 0

    # ── interviewed_stakeholder_role ──────────────────────────────────────────
    # Always mirrors stakeholders[stakeholder_idx] for the current turn.
    # Preserved in interview_record for synthesis passes (no breaking change).
    interviewed_stakeholder_role: Optional[str] = None

    # ── Fix 3 fields ──────────────────────────────────────────────────────────
    followup_asked:             bool          = False   # True once a follow-up question is sent
    followup_answer:            Optional[str] = None    # stores the follow-up answer before merge

    # ── Helpers ───────────────────────────────────────────────────────────────

    def current_stakeholder(self) -> Optional[str]:
        """Return the role currently being interviewed, or None when all are done."""
        if self.stakeholders and self.stakeholder_idx < len(self.stakeholders):
            return self.stakeholders[self.stakeholder_idx]
        return None

    def all_stakeholders_answered(self) -> bool:
        """True when every assigned stakeholder has an entry in answers."""
        if not self.stakeholders:
            return bool(self.answers)   # legacy: no list → rely on answer_received
        return self.stakeholder_idx >= len(self.stakeholders)

    def advance_stakeholder(self) -> None:
        """Move to the next stakeholder and update interviewed_stakeholder_role."""
        self.stakeholder_idx += 1
        role = self.current_stakeholder()
        self.interviewed_stakeholder_role = role  # None when all done

    def merge_answers(self) -> str:
        """Produce a merged answer string for backward-compat synthesis passes."""
        if not self.answers:
            return self.answer_received or "(no answers collected)"
        parts = [
            f"[{role}] {ans}"
            for role, ans in self.answers.items()
        ]
        return "\n".join(parts)


class AgendaRuntime(BaseModel):
    """Live agenda stored in WorkflowState."""
    items:                List[AgendaRuntimeItem]
    current_index:        int  = 0
    elicitation_complete: bool = False

    @classmethod
    def from_agenda(cls, agenda: ElicitationAgenda) -> "AgendaRuntime":
        items = []
        for item in agenda.items:
            d = item.model_dump()
            # Seed interviewed_stakeholder_role from the first stakeholder in the list
            first_role = item.stakeholders[0] if item.stakeholders else None
            d["interviewed_stakeholder_role"] = first_role
            d["stakeholder_idx"]              = 0
            d["answers"]                      = {}
            items.append(AgendaRuntimeItem(**d))
        return cls(items=items)

    def current_item(self) -> Optional[AgendaRuntimeItem]:
        if self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    def advance(self) -> None:
        """Mark current item answered and move to the next pending item."""
        self.current_index += 1
        while self.current_index < len(self.items):
            if self.items[self.current_index].status == "pending":
                break
            self.current_index += 1
        if self.current_index >= len(self.items):
            self.elicitation_complete = True


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _w_framework_stage_hint(source_field: str, priority: str) -> str:
    """Return a W-Framework stage label for the current agenda item.

    Returns a short label only — the full stage explanation lives in _REACT_ADDENDUM.
    The label anchors the agent to the correct stage without duplicating guidance.
    """
    if source_field == "out_of_scope":
        return "Stage 4 — CLOSED (Confirmation)"
    if source_field in ("assumption", "initial_requirement", "non_functional_requirement") or priority == "high":
        return "Stage 2 — DEEP (Drill-Down)"
    return "Stage 1 — WIDE (Discovery)"

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
_INTERVIEWER_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "interviewer"

def _load_interviewer_prompt(filename: str) -> str:
    return (_INTERVIEWER_PROMPTS_DIR / filename).read_text(encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────────

_VISION_EXTRACTION_SYSTEM = _load_interviewer_prompt("vision_extraction_system.txt")


_VISION_EXTRACTION_USER = _load_interviewer_prompt("vision_extraction_user.txt")


# ── Expanded mapping rules ─────────────────────────────────────────────

_AGENDA_EXTRACTION_SYSTEM = _load_interviewer_prompt("agenda_extraction_system.txt")


_AGENDA_EXTRACTION_USER = _load_interviewer_prompt("agenda_extraction_user.txt")


# ── v3: Active Listening + LLM-delegated follow-up + relaxed decomposition ─────
_REACT_ADDENDUM = """
PRE-TURN INNER MONOLOGUE — run silently before every tool call

Start with the person, not the requirement. Before classifying anything, answer
these questions mentally in order.

First — who is this person? Read CURRENT STAKEHOLDER in the task. What role do
they play in daily life? What would go wrong for THEM specifically if this project
failed? Hold their perspective as the lens for everything that follows.

Second — what did they actually say, and what did they NOT say? If an ENDUSER
ANSWER is present, read it as a human statement, not a requirements input. What
concern is underneath the words? What would they be worried about losing?

Third — is this answer complete enough to write a testable requirement? If the
answer is surface-level or vague, the right move is to go deeper — not broader.
Ask why this matters to them, or what happened in the past when it went wrong.

Fourth — is there a genuine tension in this answer? Two needs the stakeholder
expressed that pull in opposite directions at the same time. The two sides must
come from what the stakeholder ACTUALLY SAID — not from abstract categories.
Test: can you write '[A] vs [B]' where both [A] and [B] are quoted or closely
paraphrased from their answer? If you cannot fill in both slots with their
words, there is no tension. A long answer or a list of topics is not a
tension. Set needs_follow_up to False unless you can write both sides clearly.

Fifth — if you are about to call ask_question, draft the acknowledgment from
THIS stakeholder's words — not from the agenda item's label, and not from
another stakeholder's answer listed under PRIOR ANSWERS. Quote or closely
paraphrase something THIS person said — their concern, their example, their
frustration. If you are asking this stakeholder for the first time on this
item (they have no prior answer yet), pass an empty string.

Sixth — check tool discipline. You may call exactly one tool this turn. Stop
before calling. Is there an ENDUSER ANSWER present and _agenda_needs_followup is
False? Then call record_answer. Is _agenda_needs_followup True? Then call
ask_question with a Stage 3 tension-balancing question only. Is neither condition
met and elicitation is not complete? Then call ask_question with a Stage 1 or
Stage 2 question. Is elicitation_complete True? Then call conclude.

TURN STRUCTURE — EXACTLY ONE TOOL PER TURN

Each turn you receive agenda progress, the current item, an optional ENDUSER
ANSWER, and an optional FOLLOW-UP CONTEXT. Follow this decision sequence exactly,
stopping at the first match.

If elicitation_complete is True, call conclude and nothing else.

If FOLLOW-UP CONTEXT is present (meaning _agenda_needs_followup is True), call
ask_question with a Stage 3 tension-balancing question. Include an acknowledgment
referencing the prior answer. Do not call record_answer — the original answer is
already stored.

If ENDUSER ANSWER is present and _agenda_needs_followup is False, call
record_answer with needs_follow_up set to True if a named tension exists, or False
otherwise. Pass a one-sentence description of the tension in follow_up_reasoning if
needs_follow_up is True, or an empty string if it is False.

If no answer is present, no follow-up is active, and elicitation is not complete,
call ask_question with one Stage 1 or Stage 2 question. Include an acknowledgment
when a prior answer exists.

Never call two tools in one turn.

W-FRAMEWORK — every question fits exactly one stage

Stage 1 is Wide or Discovery. Open-ended. Let the stakeholder define what matters.
Use Stage 1 for the first question on any agenda item. Ask them to walk you through
their current situation or their main concern — in their own words.

Stage 2 is Deep or Drill-Down. Narrow into a specific concern raised by the
stakeholder and go to root cause. Ask why it matters to them, or what went wrong in
the past. Use Stage 2 when the prior answer is surface-level or leaves the real
concern unstated.

Stage 3 is High or Pull-Up, for Tension Balancing. Ask how the stakeholder wants to
navigate a situation where two things they care about conflict. A good Stage 3
question names the two competing needs in the stakeholder's own language and asks
how they would choose. Use Stage 3 only when _agenda_needs_followup is True.
Never use it as the first question on a new agenda item.

Stage 4 is Closed or Confirmation. Verify a specific boundary or constraint that
was stated earlier. Reserve Stage 4 for out-of-scope items only.

FOLLOW-UP RULES (Stage 3 only)

When _agenda_needs_followup is True, find the strongest tension in the previous
answer. Name both sides in plain language — the stakeholder's language, not
requirement-category language. Then ask one question about how the stakeholder
would want to handle that conflict if both things cannot be fully satisfied at the
same time. A good Stage 3 question puts the trade-off in the stakeholder's hands.
A bad one asks for more detail on the same topic — that is Stage 2. The hard limit
is one follow-up per item. Never request a second.

QUESTION QUALITY RULES

Ask one question per turn. Match the W-Framework stage to the QUESTION STRATEGY
label provided in the task — do not override it based on your own classification.
Be specific to the current item's elicitation_goal AND to this stakeholder's role.
Stay neutral. Do not lead. Keep total output to at most two sentences.

ANTI-PATTERNS

Never call record_answer and ask_question in the same turn. Never ask a question
when an ENDUSER ANSWER is waiting and no follow-up is due. Never ask about a
different item than the current item. Never re-ask an answered question. Never lead
the stakeholder toward a specific answer. Never use technical jargon in the
question or acknowledgment. Never use a tension-balancing question as the first
question on a new agenda item. Never narrate your reasoning — deliver the
acknowledgment and question only. Never request a second follow-up after the first
follow-up answer is received. Never set needs_follow_up to True because the answer
is long — only set it True when you can write both sides as '[A] vs [B]' from the
stakeholder's words. Never use generic acknowledgments such as "Thank you",
"Great point", or "Let's move on". Never acknowledge what a DIFFERENT stakeholder
said as if the current stakeholder said it — PRIOR ANSWERS belong to other people.

Never chain two tool calls in one turn. The orchestrator handles sequencing.
"""

# ─────────────────────────────────────────────────────────────────────────────
# SRS Synthesis — 4-Pass Pipeline Prompts
#
# Pass 1 — FR Extraction:   elicitation Q&A  → functional requirements only
# Pass 2 — NFR & CON:       elicitation Q&A  → non-functional + constraints + OOS
# Pass 3 — Coverage Check:  project desc     → catch any missed requirements
# Pass 4 — Quality Gate:    all passes       → atomicity check + final assembly
# ─────────────────────────────────────────────────────────────────────────────

# ── Per-pass field guidance loaded from individual files ─────────────────────
# Each pass has its own COMPLETE guidance file — no shared base.
# Loading is done lazily here so missing files fail loudly at startup.
_FIELD_GUIDANCE_PASS1  = _load_interviewer_prompt("field_guidance_pass1.txt")
_FIELD_GUIDANCE_PASS2  = _load_interviewer_prompt("field_guidance_pass2.txt")
_FIELD_GUIDANCE_PASS3  = _load_interviewer_prompt("field_guidance_pass3.txt")
_FIELD_GUIDANCE_PASS4  = _load_interviewer_prompt("field_guidance_pass4.txt")

# ── Pass 1: Functional Requirements ──────────────────────────────────────────
_PASS1_SYSTEM = _load_interviewer_prompt("pass1_system.txt")


_PASS1_USER = _load_interviewer_prompt("pass1_user.txt")


# ── Pass 2: Non-Functional Requirements, Constraints, Out-of-Scope ───────────
_PASS2_SYSTEM = _load_interviewer_prompt("pass2_system.txt")


_PASS2_USER = _load_interviewer_prompt("pass2_user.txt")


# ── Pass 3: Coverage Check ────────────────────────────────────────────────────
_PASS3_SYSTEM = _load_interviewer_prompt("pass3_system.txt")


_PASS3_USER = _load_interviewer_prompt("pass3_user.txt")


# ── Pass 4: Quality Gate ──────────────────────────────────────────────────────
_PASS4_SYSTEM = _load_interviewer_prompt("pass4_system.txt")


_PASS4_USER = _load_interviewer_prompt("pass4_user.txt")



# ─────────────────────────────────────────────────────────────────────────────
# InterviewerAgent
# ─────────────────────────────────────────────────────────────────────────────

class InterviewerAgent(BaseAgent):

    def __init__(self):
        super().__init__(name="interviewer")

    # ─────────────────────────────────────────────────────────────────────────
    # Tool registration
    # ─────────────────────────────────────────────────────────────────────────

    def _register_tools(self) -> None:
        self.register_tool(Tool(
            name="record_answer",
            description=(
                "Record the EndUser's latest reply into the current agenda item.\n\n"
                "YOU decide whether a follow-up is needed — the system no longer "
                "makes this decision for you. Pass two arguments:\n\n"
                "  needs_follow_up (bool, REQUIRED):\n"
                "    True  → the answer contains a GENUINE TENSION worth probing.\n"
                "            A tension means TWO SPECIFIC NEEDS the stakeholder\n"
                "            expressed that pull in opposite directions. You must\n"
                "            be able to name BOTH sides from the answer text.\n"
                "            Do NOT set True just because the answer is long,\n"
                "            mentions many topics, or sounds important.\n"
                "    False → the answer is sufficient. Advance to the next item.\n\n"
                "  follow_up_reasoning (str, REQUIRED when needs_follow_up=True):\n"
                "    MANDATORY FORMAT: '[A] vs [B]' where [A] and [B] are the two\n"
                "    competing needs quoted or closely paraphrased from the\n"
                "    stakeholder's ACTUAL answer. Both sides must come from what\n"
                "    they said — not from abstract category labels.\n"
                "    If you cannot fill in both [A] and [B] with words the\n"
                "    stakeholder actually used, set needs_follow_up to False.\n"
                "    Pass an empty string when needs_follow_up=False.\n\n"
                "Call this whenever an ENDUSER ANSWER is waiting in state AND\n"
                "_agenda_needs_followup is NOT already True.\n\n"
                'Input: {"needs_follow_up": bool, "follow_up_reasoning": str}'
            ),
            func=self._tool_record_answer,
        ))
        self.register_tool(Tool(
            name="ask_question",
            description=(
                "Generate and deliver ONE question targeting the current agenda item's "
                "elicitation_goal. This is the ONE AND ONLY tool call this turn — "
                "never pair it with record_answer or any other tool in the same turn.\n"
                "Also used for follow-up questions when _agenda_needs_followup=True — "
                "in that case narrow into ONE specific concern from the prior answer.\n\n"
                "MANDATORY: When transitioning from a previous answer (any turn where "
                "record_answer was just called), you MUST include a brief acknowledgment "
                "sentence BEFORE the question. The acknowledgment must:\n"
                "  • Reference a specific element from the CURRENT stakeholder's\n"
                "    ACTUAL last answer — not from a different stakeholder's answer.\n"
                "  • Be 1 sentence only — no padding, no generic praise.\n"
                "  • Use plain language — no technical terms.\n"
                "  • NEVER use a generic phrase like 'Thank you for sharing' or "
                "'Great, let\\'s move on'. Instead, name the concrete thing they said.\n"
                "  • NEVER acknowledge answers given by OTHER stakeholders listed\n"
                "    under PRIOR ANSWERS. Those belong to different people.\n"
                "If this is the very FIRST question to this stakeholder (no prior\n"
                "answer from THEM yet), pass an empty string for acknowledgment —\n"
                "do not fabricate a transition.\n\n"
                'Input: {"question": "<the actual question to ask, DO NOT include the acknowledgment here>", '
                '"acknowledgment": "<one-sentence echo of THIS stakeholder\'s prior answer, or empty string>"}'
            ),
            func=self._tool_ask_question,
        ))
        self.register_tool(Tool(
            name="conclude",
            description=(
                "Call when elicitation_complete=True. "
                "Summarise all answers and mark elicitation as done. "
                "Input: {} — no arguments needed."
            ),
            func=self._tool_conclude,
        ))
        # synthesise_requirements is NOT registered here.
        # It is called directly by process() when _needs_srs_synthesis=True.
        # Exposing it to the ReAct tool list would allow the agent to call it
        # erroneously under tool_choice="required" edge cases.

    # ─────────────────────────────────────────────────────────────────────────
    # Tool implementations
    # ─────────────────────────────────────────────────────────────────────────

    def _tool_record_answer(
        self,
        needs_follow_up:     bool = False,
        follow_up_reasoning: str  = "",
        state:               Dict[str, Any] = None,
        **_,
    ) -> ToolResult:
        """Write EndUser's reply into the current agenda item.

        Multi-stakeholder aware
        ───────────────────────
        Each AgendaRuntimeItem carries an ordered ``stakeholders`` list.
        record_answer now checks whether the current item still has more
        stakeholders to interview:

          • If yes → store answer in item.answers[current_role], advance
            stakeholder_idx, update state["current_stakeholder_role"] to the
            next role, set _agenda_needs_question=True WITHOUT advancing the
            agenda index.  InterviewerAgent will re-ask the same elicitation
            goal to the new stakeholder on the next turn.

          • If no  → merge all per-role answers into item.answer_received,
            mark item "answered", advance agenda index normally.

        Follow-up logic is applied PER STAKEHOLDER: a follow-up is only
        triggered for the current role and does not block the next role.

        Backward compatibility
        ──────────────────────
        Items with an empty stakeholders list behave exactly as before:
        single-answer path with no stakeholder iteration.
        """
        answer       = (state or {}).get("enduser_answer", "")
        # current_stakeholder_role is the authoritative source — set by
        # graph.py/enduser_turn_fn from item.current_stakeholder() before
        # each EndUser turn.  Fallback to legacy enduser_role for compat.
        enduser_role = (
            (state or {}).get("current_stakeholder_role")
            or (state or {}).get("enduser_role", "")
        ).strip()

        runtime = self._load_runtime(state)
        if runtime is None:
            return ToolResult(
                observation="[record_answer] No agenda found in state.",
                is_error=True,
                should_return=True,
            )

        item = runtime.current_item()
        if item is None:
            return ToolResult(
                observation="[record_answer] Agenda already complete — nothing to record.",
                should_return=True,
            )

        # ── Follow-up append branch ───────────────────────────────────────────
        # The interviewer previously asked a follow-up for the CURRENT stakeholder.
        if item.followup_asked and item.followup_answer is None:
            if enduser_role and not item.interviewed_stakeholder_role:
                item.interviewed_stakeholder_role = enduser_role
            item.followup_answer = answer or "(no follow-up answer provided)"
            # Append follow-up into the per-role slot if multi-stakeholder
            current_role = enduser_role or item.interviewed_stakeholder_role or "unknown"
            if current_role in item.answers:
                item.answers[current_role] = (
                    f"{item.answers[current_role]}\n[follow-up] {item.followup_answer}"
                )
            else:
                item.answers[current_role] = f"[follow-up] {item.followup_answer}"
            # Reset follow-up state for next stakeholder
            item.followup_asked  = False
            item.followup_answer = None

            # After follow-up, check if more stakeholders remain
            return self._advance_or_next_stakeholder(
                item=item,
                runtime=runtime,
                state=state or {},
                context="Follow-up merged",
            )

        # ── Store answer for current stakeholder ──────────────────────────────
        current_role = enduser_role or item.current_stakeholder() or "unknown"
        item.answers[current_role] = answer or "(no answer provided)"
        if not item.interviewed_stakeholder_role:
            item.interviewed_stakeholder_role = current_role

        # ── Follow-up branch — LLM decided a Stage 3 question is warranted ───
        if needs_follow_up and not item.followup_asked:
            item.followup_asked = True
            logger.info(
                "[InterviewerAgent] LLM requested follow-up for '%s' (role=%s): %s",
                item.item_id,
                current_role,
                follow_up_reasoning or "(no reasoning provided)",
            )
            return ToolResult(
                observation=(
                    f"Answer recorded for '{item.item_id}' (role={current_role}). "
                    f"Follow-up warranted: {follow_up_reasoning or '(see LLM reasoning)'}. "
                    "Call ask_question with a Stage 3 tension-balancing question."
                ),
                state_updates={
                    "elicitation_agenda":     runtime.model_dump(),
                    "enduser_answer":         "",
                    "current_question":       "",
                    "_agenda_needs_followup": True,
                    "_agenda_needs_question": False,
                },
                should_return=True,
            )

        # ── Normal path: check if more stakeholders remain ────────────────────
        return self._advance_or_next_stakeholder(
            item=item,
            runtime=runtime,
            state=state or {},
            context="Answer recorded",
        )

    def _advance_or_next_stakeholder(
        self,
        item:    "AgendaRuntimeItem",  # type: ignore[name-defined]
        runtime: "AgendaRuntime",      # type: ignore[name-defined]
        state:   Dict[str, Any],
        context: str = "",
    ) -> ToolResult:
        """Helper: after storing an answer, decide whether to move to the next
        stakeholder within the same item or advance the agenda index.

        Returns a ToolResult ready to be returned from record_answer.
        """
        # Advance the stakeholder cursor
        if item.stakeholders:
            item.advance_stakeholder()

        next_role = item.current_stakeholder()

        if next_role is not None:
            # More stakeholders to interview for this item
            logger.info(
                "[InterviewerAgent] %s for '%s'. Next stakeholder: '%s'.",
                context, item.item_id, next_role,
            )
            # Merge partial answers into answer_received so _build_task can show context
            item.answer_received = item.merge_answers()
            return ToolResult(
                observation=(
                    f"{context} for '{item.item_id}'. "
                    f"Next stakeholder to interview: '{next_role}'. "
                    "Returning — next turn will ask the same item to the new role."
                ),
                state_updates={
                    "elicitation_agenda":        runtime.model_dump(),
                    "enduser_answer":            "",
                    "current_question":          "",
                    "current_stakeholder_role":  next_role,
                    "_agenda_needs_question":    True,
                    "_agenda_needs_followup":    False,
                },
                should_return=True,
            )

        # All stakeholders answered — merge and advance agenda
        item.answer_received = item.merge_answers()
        item.status          = "answered"
        runtime.advance()
        logger.info(
            "[InterviewerAgent] %s for '%s' (all stakeholders done). "
            "Next agenda index: %d. Complete: %s",
            context, item.item_id,
            runtime.current_index,
            runtime.elicitation_complete,
        )
        # Determine the first stakeholder for the newly current item (if any)
        next_item      = runtime.current_item()
        next_role_new  = next_item.current_stakeholder() if next_item else None
        return ToolResult(
            observation=(
                f"{context} for '{item.item_id}' (all stakeholders answered). "
                f"Agenda complete: {runtime.elicitation_complete}. "
                "Advancing to next item."
            ),
            state_updates={
                "elicitation_agenda":       runtime.model_dump(),
                "enduser_answer":           "",
                "current_question":         "",
                "current_stakeholder_role": next_role_new or "",
                "_agenda_needs_question":   True,
                "_agenda_needs_followup":   False,
            },
            should_return=True,
        )

    def _tool_ask_question(
            self,
            question: str,
            acknowledgment: str = "",
            state: Dict[str, Any] = None,
            **_,
    ) -> ToolResult:
        """Deliver one elicitation question and mark it on the current item.

        acknowledgment — optional 1-sentence echo of the prior answer.
          When present, it is prepended to the question so the delivered text
          reads: "<acknowledgment> <question>".  Stored verbatim in
          item.question_asked for traceability.

        Clears _agenda_needs_followup when acting as a follow-up delivery,
        so after_interviewer correctly routes the next turn to enduser_turn.
        """
        runtime = self._load_runtime(state)

        # Compose the full delivered text: acknowledgment (if any) + question
        delivered = (
            f"{acknowledgment.strip()} {question.strip()}".strip()
            if acknowledgment
            else question
        )

        conversation = list((state or {}).get("conversation") or [])
        conversation.append(
            {
                "role": "interviewer",
                "content": delivered,
                "timestamp": datetime.now().isoformat(),
            }
        )

        if runtime is not None:
            item = runtime.current_item()
            if item is not None:
                item.question_asked = delivered

        state_updates: Dict[str, Any] = {
            "current_question": delivered,
            "conversation": conversation,
            "_agenda_needs_question": False,
            "_agenda_needs_followup": False,  # Fix 3 — clear flag after follow-up is sent
        }
        if runtime is not None:
            state_updates["elicitation_agenda"] = runtime.model_dump()

        return ToolResult(
            observation=f"Question delivered: {delivered}",
            state_updates=state_updates,
            should_return=True,
        )

    def _tool_conclude(
        self,
        state: Dict[str, Any] = None,
        **_,
    ) -> ToolResult:
        """Summarise elicitation answers and write interview_record artifact.

        Also writes product_vision as a standalone artifact so it can be
        reviewed / revised independently via HITL before requirement synthesis.

        Does NOT set interview_complete=True here.
        Instead sets _needs_srs_synthesis=True so that process() triggers the
        synthesis pass on the very next invocation (no EndUser turn in between).
        """

        runtime      = self._load_runtime(state)
        state        = state or {}
        summary_lines: List[str] = []
        requirements: List[Dict[str, Any]] = []

        if runtime:
            for idx, item in enumerate(runtime.items):
                if item.answer_received:
                    summary_lines.append(
                        f"[{item.item_id}] {item.source_ref}\n"
                        f"  Q: {item.question_asked or '(not recorded)'}\n"
                        f"  A: {item.answer_received}"
                    )
                    # Export one record entry per answering stakeholder so
                    # synthesis passes see each role's perspective individually.
                    if item.answers:
                        for role, ans in item.answers.items():
                            requirements.append({
                                "id":                           f"EL-{idx + 1:03d}",
                                "source_field":                 item.source_field,
                                "source_ref":                   item.source_ref,
                                "elicitation_goal":             item.elicitation_goal,
                                "question":                     item.question_asked or "",
                                "answer":                       ans,
                                "priority":                     item.priority,
                                "status":                       "answered",
                                "interviewed_stakeholder_role": role,
                            })
                    else:
                        # Legacy single-answer fallback
                        requirements.append({
                            "id":                           f"EL-{idx + 1:03d}",
                            "source_field":                 item.source_field,
                            "source_ref":                   item.source_ref,
                            "elicitation_goal":             item.elicitation_goal,
                            "question":                     item.question_asked or "",
                            "answer":                       item.answer_received,
                            "priority":                     item.priority,
                            "status":                       "answered",
                            "interviewed_stakeholder_role": item.interviewed_stakeholder_role or "",
                        })
                else:
                    # Skipped items are recorded with null answer so Pass 3
                    # can detect coverage gaps from the project description.
                    requirements.append({
                        "id":                           f"EL-{idx + 1:03d}",
                        "source_field":                 item.source_field,
                        "source_ref":                   item.source_ref,
                        "elicitation_goal":             item.elicitation_goal,
                        "question":                     item.question_asked or "",
                        "answer":                       None,
                        "priority":                     item.priority,
                        "status":                       "skipped",
                        "interviewed_stakeholder_role": item.interviewed_stakeholder_role or "",
                    })

        elicitation_notes = "\n\n".join(summary_lines) or "(no answers recorded)"

        interview_record = {
            "session_id":              state.get("session_id", ""),
            "project_description":     state.get("project_description", ""),
            "created_at":              datetime.now().isoformat(),
            "requirements_identified": requirements,
            "elicitation_notes":       elicitation_notes,
            "status":                  "pending_review",
        }

        existing_artifacts = dict(state.get("artifacts") or {})
        existing_artifacts["interview_record"] = interview_record

        # ── Also export product_vision as a reviewable artifact ───────────────
        vision_data = state.get("product_vision")
        if vision_data and "product_vision" not in existing_artifacts:
            existing_artifacts["product_vision"] = {
                **vision_data,
                "created_at":   datetime.now().isoformat(),
                "status":       "pending_review",
            }

        logger.info(
            "[InterviewerAgent] Elicitation concluded — %d item(s), interview_record + "
            "product_vision artifacts written. Scheduling requirement_list synthesis pass.",
            len(requirements),
        )

        return ToolResult(
            observation=(
                "Elicitation complete. interview_record and product_vision artifacts written. "
                "requirement_list synthesis will run on the next process() invocation."
            ),
            state_updates={
                "elicitation_notes":    elicitation_notes,
                "artifacts":            existing_artifacts,
                "_needs_srs_synthesis": True,
            },
            should_return=True,
        )

    def _tool_synthesise_requirements(self, **_) -> ToolResult:
        """Stub — never called from ReAct. Exists only so the tool is registered."""
        return ToolResult(
            observation="[synthesise_requirements] This tool is invoked by process(), not ReAct.",
            is_error=True,
            should_return=True,
        )

    @staticmethod
    def _group_elicitation_records(
        raw_requirements: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Group flat per-role elicitation records into multi-stakeholder items.

        The interview record now contains one entry PER STAKEHOLDER PER ITEM —
        e.g. EL-001 appears three times if three roles answered it.  Synthesis
        passes need to see them as ONE logical elicitation item with multiple
        responses so they can:
          • merge agreements into a single requirement
          • record distinct perspectives as separate requirements
          • flag and resolve cross-stakeholder conflicts

        Output schema per grouped item
        ───────────────────────────────
        {
          "id":               "EL-001",
          "source_field":     "assumption",
          "source_ref":       "...",
          "elicitation_goal": "...",
          "priority":         "high",
          "question":         "...",      # question asked (same for all roles)
          "status":           "answered",
          "responses": [
            {
              "stakeholder": "Role A",
              "answer":      "..."
            },

            ...
          ]
        }
        """
        from collections import OrderedDict

        # Preserve insertion order so high-priority items stay first
        groups: OrderedDict[str, Dict[str, Any]] = OrderedDict()

        for rec in raw_requirements:
            eid = rec.get("id", "")
            if eid not in groups:
                groups[eid] = {
                    "id":               eid,
                    "source_field":     rec.get("source_field", ""),
                    "source_ref":       rec.get("source_ref", ""),
                    "elicitation_goal": rec.get("elicitation_goal", ""),
                    "priority":         rec.get("priority", "medium"),
                    "question":         rec.get("question", ""),
                    "status":           rec.get("status", "answered"),
                    "responses":        [],
                }
            role   = rec.get("interviewed_stakeholder_role") or "Unknown"
            answer = rec.get("answer") or ""
            # Retain slot even for skipped/empty answers to signal coverage gap.
            # Consensus analysis is delegated to the LLM in Pass 1/2 reasoning_log.
            groups[eid]["responses"].append({
                "stakeholder": role,
                "answer":      answer,
            })

        return list(groups.values())

    def _synthesise_srs(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        4-Pass Requirement List Synthesis Pipeline.

        Called directly from process() when _needs_srs_synthesis=True.
        No ReAct, no memory — all passes are stateless LLM calls.

        If state contains requirement_list_feedback (from a previous HITL rejection),
        that feedback is injected as an additional constraint into all four passes
        so the agent addresses the reviewer's comments in the new synthesis.

        Pass 1 — FR Extraction:
            Extract only Functional Requirements from elicitation Q&A.
            CoT via reasoning_log: LLM must anchor every FR in a stakeholder quote
            and a concrete user outcome before writing it. Echoes of the project
            description without new stakeholder detail are marked status="inferred".
            elicitation_goal from each agenda item is included so the LLM can judge
            whether the stakeholder's answer actually addressed what was asked.
            No external assumptions block is injected — status ("confirmed" vs
            "inferred") is derived from the answer text of each elicitation item
            alone, using the Q1/Q2/Q3 MANDATORY PRE-EXTRACTION BEHAVIOUR CHECK.

        Pass 2 — NFR & CON Extraction:
            Extract Non-Functional Requirements, Constraints, and Out-of-Scope
            items from elicitation Q&A.
            CoT via reasoning_log: evidence-gated — LLM must declare whether direct
            stakeholder evidence exists for each quality dimension before generating
            an NFR; zero NFRs for a dimension is a valid outcome. The Pass 1 FR list
            is injected so the LLM can cross-check candidates and avoid restating
            behaviours already captured as FRs. Thresholds must be grounded in the
            project's own context rather than imported from external standards lists.

        Pass 3 — Coverage Check:
            Compare passes 1+2 against both the project description and the approved
            ProductVision. Gap detection is Vision-driven: every needs_validation
            assumption must have coverage; every project constraint must have a CON;
            every Vision NFR must have an NFR.
            An elicitation goal coverage map is provided so the LLM can spot goals
            that produced no requirements without free-form matching.
            All gap-filling requirements are stamped source="PD", status="inferred".

        Pass 4 — Quality Gate:
            Audit all draft requirements for atomicity, testability, banned
            words, cross-type duplicate detection, and OOS/CON rationale guard.
            Step 0.5 (User Value Gate) rewrites or downgrades FRs that are echoes
            of the project description with no new stakeholder specifics.
            Vague language sweep requires explicit listing before replacement.
            Assembles and returns the final Requirement List object.

        Returns a partial state dict ready to merge.
        """

        state              = state or {}
        project_desc       = state.get("project_description", "")
        existing_artifacts = dict(state.get("artifacts") or {})
        interview_record   = existing_artifacts.get("interview_record", {})
        raw_requirements   = interview_record.get("requirements_identified", [])
        session_id         = state.get("session_id", "")
        synthesised_at     = datetime.now().isoformat()

        # ── HITL feedback injection ───────────────────────────────────────────
        rl_feedback = (state.get("requirement_list_feedback") or "").strip()
        feedback_block = (
            f"\n\nREVIEWER FEEDBACK (must be addressed in this synthesis pass):\n"
            f"{rl_feedback}"
            if rl_feedback else ""
        )

        # Build context header for all synthesis passes.
        # IMPORTANT: prefer reviewed_product_vision (post-HITL) over the raw
        # product_vision draft so that any Stakeholders removed/renamed
        # by the reviewer are correctly reflected in synthesis.
        reviewed_vision = existing_artifacts.get("reviewed_product_vision") or {}
        vision_data     = reviewed_vision or state.get("product_vision") or {}
        target_audiences = vision_data.get("target_audiences") or []

        stakeholder_context = (
            "KNOWN STAKEHOLDERS (use these roles in the 'stakeholder' field):\n"
            + "\n".join(
                f"  - {s.get('role', '?')} ({s.get('type', '?')}) — concern: {s.get('key_concern', '?')}"
                for s in target_audiences
            )
            if target_audiences
            else ""
        )
        logger.info(
            "[InterviewerAgent] Synthesis using %s vision — %d stakeholder(s).",
            "reviewed" if reviewed_vision else "draft",
            len(target_audiences),
        )

        # ── Group flat per-role records into multi-stakeholder items ─────────
        # Each EL-NNN may appear N times (once per stakeholder who answered it).
        # Synthesis passes receive ONE grouped object per elicitation goal so
        # they can merge agreements, record distinct perspectives, and resolve
        # conflicts before generating requirements.
        grouped_records  = self._group_elicitation_records(raw_requirements)
        elicitation_json = json.dumps(grouped_records, indent=2, ensure_ascii=False)
        logger.info(
            "[InterviewerAgent] Grouped %d flat record(s) into %d elicitation item(s) "
            "for synthesis.",
            len(raw_requirements),
            len(grouped_records),
        )

        # NOTE: validated_assumptions_block removed — Pass 1 now derives
        # status ("confirmed" vs "inferred") from the answer text of each
        # elicitation item directly, via the Q1/Q2/Q3 MANDATORY PRE-EXTRACTION
        # BEHAVIOUR CHECK. No external list is injected into the prompt.
        assumptions_list = vision_data.get("assumptions") or []

        # Pass 1 & 2: Stakeholders enter via system prompt (field_guidance) only.
        # Pass 3 & 4: also need out_of_scope in user prompt — LLM must not generate
        # gap-fill requirements for capabilities already ruled out by Vision scope.
        out_of_scope_list = vision_data.get("out_of_scope") or []
        out_of_scope_block = (
            "OUT-OF-SCOPE BOUNDARIES (do NOT generate requirements for these):\n"
            + "\n".join(f"  - {item}" for item in out_of_scope_list)
            + "\n\n"
            if out_of_scope_list
            else ""
        )

        # ── Vision block for Pass 3 (full rubric) ─────────────────────────────
        # Pass 3 uses the reviewed Vision as the authoritative gap-detection rubric.
        # Each section is included only when it carries content.
        vision_section_lines = []
        if assumptions_list:
            needs_val_items = [
                a for a in assumptions_list if a.get("needs_validation", False)
            ]
            if needs_val_items:
                vision_section_lines.append(
                    "Assumptions requiring validation (each must have at least one FR or NFR "
                    "that addresses whether the assumption holds):\n"
                    + "\n".join(
                        f"  - [{a.get('item_id', 'unknown')}] {a.get('statement', '')}"
                        if "item_id" in a
                        else f"  - {a.get('statement', '')}"
                        for a in needs_val_items
                    )
                )
        project_constraints_list = vision_data.get("project_constraints") or []
        if project_constraints_list:
            vision_section_lines.append(
                "Project Constraints (each must have a corresponding CON requirement):\n"
                + "\n".join(f"  - {c}" for c in project_constraints_list)
            )
        pass3_vision_block = "\n\n".join(vision_section_lines) if vision_section_lines else "(no structured Vision data available)"

        # Pass 4 gets a compact Vision block (OOS) directly in user prompt.
        vision_block_lines = []
        if out_of_scope_list:
            vision_block_lines.append(
                "OUT-OF-SCOPE (any requirement covering these must be OOS or removed):\n"
                + "\n".join(f"  - {item}" for item in out_of_scope_list)
            )
        vision_block = ("\n\n".join(vision_block_lines) + "\n\n") if vision_block_lines else ""

        # ── Vision context for Passes 1, 2, 4 (lightweight reasoning anchor) ──
        core_problem      = vision_data.get("core_problem", "")
        value_proposition  = vision_data.get("value_proposition", "")
        vision_context = ""
        if core_problem or value_proposition:
            vision_context = (
                "VISION CONTEXT (reasoning anchor — do not generate requirements FROM these fields):\n"
                f"  Core Problem:      {core_problem or '(not available)'}\n"
                f"  Value Proposition: {value_proposition or '(not available)'}\n"
            )

        # ── Evaluation criteria for Pass 2 (NFR threshold derivation source) ──
        eval_criteria_list = vision_data.get("evaluation_criteria") or []
        evaluation_criteria_block = ""
        if eval_criteria_list:
            evaluation_criteria_block = (
                "EVALUATION CRITERIA (from Vision — use to ground NFR thresholds):\n"
                + "\n".join(f"  - {c}" for c in eval_criteria_list)
            )

        vision_header  = stakeholder_context
        # Each pass gets its own field guidance to avoid cross-contamination of rules:
        #   Pass 1 — FR-only rules (stakeholder assignment from interviewed role,
        #             external precondition guard)
        #   Pass 2 — NFR/CON/OOS rules (stakeholder from interviewed role,
        #             external precondition → CON conversion)
        #   Pass 3 — gap-filling rules (all new reqs are inferred)
        #   Pass 4 — audit rules (status audit + quality gate)
        field_guidance_pass1 = (vision_header + "\n\n" + _FIELD_GUIDANCE_PASS1).strip()
        field_guidance_pass2 = (vision_header + "\n\n" + _FIELD_GUIDANCE_PASS2).strip()
        field_guidance_pass3 = (vision_header + "\n\n" + _FIELD_GUIDANCE_PASS3).strip()
        field_guidance_pass4 = (vision_header + "\n\n" + _FIELD_GUIDANCE_PASS4).strip()
        # Legacy alias kept for any remaining {field_guidance} references
        field_guidance       = field_guidance_pass4

        try:
            # ── Pass 1: Functional Requirements ───────────────────────────────
            logger.info("[InterviewerAgent] Requirement List synthesis — Pass 1: FR extraction.")
            pass1_reqs: List[Dict[str, Any]] = self._run_structured_pass(
                system_prompt=_PASS1_SYSTEM.format(field_guidance=field_guidance_pass1) + feedback_block,
                user_prompt=_PASS1_USER.format(
                    project_description=project_desc,
                    vision_context=vision_context,
                    item_count=len(grouped_records),
                    elicitation_json=elicitation_json,
                ),
            )

            logger.info("[InterviewerAgent] Pass 1 complete — %d FR(s) extracted.", len(pass1_reqs))

            print(f"\n{'='*70}\nDEBUG START - PASS 1 ARTIFACT\n{'='*70}")
            print(json.dumps(pass1_reqs, indent=2, ensure_ascii=False))
            print(f"{'='*70}\nDEBUG END - PASS 1 ARTIFACT\n{'='*70}\n")

            # ── Pass 2: NFR, CON, OOS ─────────────────────────────────────────
            logger.info("[InterviewerAgent] Requirement List synthesis — Pass 2: NFR/CON/OOS extraction.")
            pass1_json_for_p2 = json.dumps(pass1_reqs, indent=2, ensure_ascii=False)
            pass2_reqs: List[Dict[str, Any]] = self._run_structured_pass(
                system_prompt=_PASS2_SYSTEM.format(field_guidance=field_guidance_pass2) + feedback_block,
                user_prompt=_PASS2_USER.format(
                    project_description=project_desc,
                    vision_context=vision_context,
                    evaluation_criteria_block=evaluation_criteria_block,
                    pass1_count=len(pass1_reqs),
                    pass1_json=pass1_json_for_p2,
                    item_count=len(grouped_records),
                    elicitation_json=elicitation_json,
                ),
            )
            logger.info("[InterviewerAgent] Pass 2 complete — %d NFR/CON/OOS extracted.", len(pass2_reqs))

            print(f"\n{'='*70}\nDEBUG START - PASS 2 ARTIFACT\n{'='*70}")
            print(json.dumps(pass2_reqs, indent=2, ensure_ascii=False))
            print(f"{'='*70}\nDEBUG END - PASS 2 ARTIFACT\n{'='*70}\n")

            # ── Pass 3: Coverage Check ────────────────────────────────────────
            logger.info("[InterviewerAgent] Requirement List synthesis — Pass 3: coverage check.")
            all_so_far  = pass1_reqs + pass2_reqs
            next_fr     = self._next_id_counter(all_so_far, "FR")
            next_nfr    = self._next_id_counter(all_so_far, "NFR")
            next_con    = self._next_id_counter(all_so_far, "CON")

            # Build elicitation goal coverage map from GROUPED records.
            # Each group is one logical elicitation item — using grouped_records
            # prevents duplicate EL-NNN entries from inflating the coverage map.
            req_by_source: Dict[str, List[str]] = {}
            for req in all_so_far:
                src = req.get("source_elicitation_id", "")
                if src and src != "PD":
                    req_by_source.setdefault(src, []).append(req.get("req_id", ""))
            goal_coverage = [
                {
                    "item_id":          g.get("id", ""),
                    "elicitation_goal": g.get("elicitation_goal", ""),
                    "stakeholders":     [r["stakeholder"] for r in g.get("responses", [])],
                    "requirements":     req_by_source.get(g.get("id", ""), []),
                }
                for g in grouped_records
            ]
            goal_coverage_json = json.dumps(goal_coverage, indent=2, ensure_ascii=False)

            pass3_reqs: List[Dict[str, Any]] = self._run_structured_pass(
                system_prompt=_PASS3_SYSTEM.format(field_guidance=field_guidance_pass3) + feedback_block,
                user_prompt=_PASS3_USER.format(
                    project_description=project_desc,
                    out_of_scope_block=out_of_scope_block,
                    vision_context=vision_context,
                    vision_block=pass3_vision_block,
                    item_count=len(grouped_records),
                    goal_coverage_json=goal_coverage_json,
                    already_count=len(all_so_far),
                    already_count_half=len(all_so_far) // 2,
                    already_json=json.dumps(all_so_far, indent=2, ensure_ascii=False),
                    next_fr=next_fr,
                    next_nfr=next_nfr,
                    next_con=next_con,
                ),
            )
            logger.info(
                "[InterviewerAgent] Pass 3 complete — %d gap-filling requirement(s) added.",
                len(pass3_reqs),
            )

            print(f"\n{'='*70}\nDEBUG START - PASS 3 ARTIFACT\n{'='*70}")
            print(json.dumps(pass3_reqs, indent=2, ensure_ascii=False))
            print(f"{'='*70}\nDEBUG END - PASS 3 ARTIFACT\n{'='*70}\n")

            # ── Pass 4: Quality Gate + Final Assembly ─────────────────────────
            logger.info("[InterviewerAgent] Requirement List synthesis — Pass 4: quality gate.")
            full_draft = all_so_far + pass3_reqs

            srs: SoftwareRequirementsSpecification = self.extract_structured(
                schema=SoftwareRequirementsSpecification,
                system_prompt=_PASS4_SYSTEM.format(field_guidance=field_guidance_pass4) + feedback_block,
                user_prompt=_PASS4_USER.format(
                    session_id=session_id,
                    project_description=project_desc,
                    synthesised_at=synthesised_at,
                    vision_context=vision_context,
                    vision_block=vision_block,
                    total_count=len(full_draft),
                    draft_json=json.dumps(full_draft, indent=2, ensure_ascii=False),
                ),
                include_memory=False,
            )

            # Stamp metadata fields the LLM cannot reliably fill
            rl_dict                         = srs.model_dump()
            # Log audit scratchpad then strip — it's internal, not a deliverable field
            if rl_dict.get("reasoning_log"):
                logger.debug(
                    "[InterviewerAgent] Pass 4 reasoning_log (first 500 chars): %s",
                    rl_dict["reasoning_log"][:500],
                )
            rl_dict.pop("reasoning_log", None)
            rl_dict["session_id"]           = session_id
            rl_dict["project_description"]  = project_desc
            rl_dict["synthesised_at"]       = synthesised_at
            rl_dict["status"]               = "pending_review"

            existing_artifacts["requirement_list"] = rl_dict

            logger.info(
                "[InterviewerAgent] Requirement List synthesis complete — %d requirement(s) "
                "(FR=%d NFR=%d CON=%d OOS=%d).",
                len(srs.requirements),
                sum(1 for r in srs.requirements if r.req_type == "functional"),
                sum(1 for r in srs.requirements if r.req_type == "non_functional"),
                sum(1 for r in srs.requirements if r.req_type == "constraint"),
                sum(1 for r in srs.requirements if r.req_type == "out_of_scope"),
            )

            print(f"\n{'='*70}\nDEBUG START - PASS 4 (FINAL) ARTIFACT\n{'='*70}")
            print(json.dumps(rl_dict, indent=2, ensure_ascii=False))
            print(f"{'='*70}\nDEBUG END - PASS 4 (FINAL) ARTIFACT\n{'='*70}\n")

            return {
                "artifacts":                  existing_artifacts,
                "interview_complete":          True,
                "_needs_srs_synthesis":        False,
                "requirement_list_feedback":   None,   # clear after successful synthesis
            }

        except Exception as exc:
            logger.error("[InterviewerAgent] Requirement List synthesis failed: %s", exc)
            return {
                "_needs_srs_synthesis": False,
                "interview_complete":   True,
                "errors": (state.get("errors") or []) + [f"Requirement List synthesis failed: {exc}"],
            }

    # ── Synthesis helpers ─────────────────────────────────────────────────────

    def _run_structured_pass(
        self,
        system_prompt: str,
        user_prompt:   str,
    ) -> List[Dict[str, Any]]:
        """Run one synthesis pass via extract_structured (Pydantic-enforced).

        Uses RequirementList wrapper so with_structured_output works with a list.
        Guarantees req_id and all other required fields are present — eliminates
        the 'id' vs 'req_id' mismatch that caused validation errors in Pass 4.
        Returns a list of raw requirement dicts ready to merge into the draft.

        reasoning_log is consumed for debugging but not propagated to the draft.
        """
        result: RequirementList = self.extract_structured(
            schema=RequirementList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            include_memory=False,
        )
        if result.reasoning_log:
            logger.debug(
                "[InterviewerAgent] Pass reasoning_log (first 500 chars): %s",
                result.reasoning_log[:500],
            )
        return [r.model_dump() for r in result.requirements]

    @staticmethod
    def _next_id_counter(reqs: List[Dict[str, Any]], prefix: str) -> int:
        """
        Return the next sequential integer for a given ID prefix (FR, NFR, CON, OOS).

        Scans req_id fields in the provided list, extracts numeric suffixes,
        and returns max + 1 (or 1 if none found).
        """

        pattern = re.compile(rf"^{prefix}-(\d+)$", re.IGNORECASE)
        used = [
            int(m.group(1))
            for r in reqs
            if (m := pattern.match(r.get("req_id", "")))
        ]
        return max(used, default=0) + 1

    def _extract_product_vision(
        self,
        project_description: str,
        reviewer_feedback: Optional[str] = None,
    ) -> ProductVision:
        user_prompt = _VISION_EXTRACTION_USER.format(
            project_description=project_description
        )
        if reviewer_feedback:
            user_prompt += (
                f"\n\nREVIEWER FEEDBACK (must be fully addressed in this revised vision):\n"
                f"{reviewer_feedback}"
            )
        return self.extract_structured(
            schema=ProductVision,
            system_prompt=_VISION_EXTRACTION_SYSTEM,
            user_prompt=user_prompt,
            include_memory=False,
        )

    def _extract_agenda(
        self,
        vision: ProductVision,
        project_description: str = "",
        reviewer_feedback: Optional[str] = None,
    ) -> ElicitationAgenda:
        user_prompt = _AGENDA_EXTRACTION_USER.format(
            vision_json=json.dumps(vision.model_dump(), indent=2),
            project_description=project_description,
        )
        if reviewer_feedback:
            user_prompt += (
                f"\n\nREVIEWER FEEDBACK (must be fully addressed in this revised agenda):\n"
                f"{reviewer_feedback}"
            )
        return self.extract_structured(
            schema=ElicitationAgenda,
            system_prompt=_AGENDA_EXTRACTION_SYSTEM,
            user_prompt=user_prompt,
            include_memory=False,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # process() — LangGraph node entry point
    # ─────────────────────────────────────────────────────────────────────────

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Called by LangGraph every turn.

        Turn 1 — Vision Bootstrap (returns early, no ReAct):
          Pass 1: extract ProductVision from project_description.
          Writes product_vision + artifacts["product_vision"] and returns early.
          after_interviewer sees no current_question + no reviewed_product_vision
          → routes to supervisor → review_product_vision_turn (HITL Step 2).

        Turn 2 — Agenda Bootstrap (returns early, no ReAct):
          Precondition: reviewed_product_vision present in artifacts.
          Triggered when elicitation_agenda NOT in state AND
          elicitation_agenda_artifact NOT in artifacts (or rebuild after HITL rejection).
          Pass 2: extract ElicitationAgenda from reviewed_product_vision + project_description.
          Writes elicitation_agenda (runtime) + artifacts["elicitation_agenda_artifact"].
          Returns early — after_interviewer routes to supervisor →
          review_elicitation_agenda_turn (HITL Step 4).

        Turn 3+ — Elicitation loop (ReAct):
          Both bootstrap guards are skipped (keys already in state).
          react() drives: record_answer → ask_question → (repeat) → conclude.

        Turn LAST — SRS Synthesis (no ReAct):
          Triggered when _needs_srs_synthesis=True (set by _tool_conclude).
          _synthesise_srs() runs the 4-pass pipeline, writes artifacts["requirement_list"],
          sets interview_complete=True.
          Returns immediately — supervisor routes to review_interview_record next.

        Separation rationale:
          Vision and Agenda MUST be separate turns so LangGraph can checkpoint the
          product_vision before the HITL gate fires, and so after_interviewer can
          correctly distinguish "just produced vision" (→ supervisor for HITL review)
          from "just produced agenda" (→ supervisor for HITL review) from
          "elicitation ongoing" (→ enduser_turn).
        """
        artifacts = dict(state.get("artifacts") or {})

        # ── Turn 1: Vision Bootstrap ──────────────────────────────────────────
        # Run when: product_vision absent, OR HITL rejected vision (feedback present).
        # Note: on HITL rejection, graph.py pops product_vision from artifacts so
        # "product_vision" not in state triggers a clean re-extraction.
        pv_feedback            = (state.get("product_vision_feedback") or "").strip()
        vision_absent          = "product_vision" not in state
        vision_rejected        = bool(pv_feedback)  # feedback means HITL rejected it

        if vision_absent or vision_rejected:
            logger.info(
                "[InterviewerAgent] Turn 1 — extracting ProductVision%s.",
                " (revision with reviewer feedback)" if vision_rejected else "",
            )
            project_description = state.get("project_description", "")
            if not project_description:
                logger.warning("[InterviewerAgent] 'project_description' missing — cannot extract vision.")
                return {}
            try:
                vision = self._extract_product_vision(
                    project_description,
                    reviewer_feedback=pv_feedback or None,
                )
                vision_dict = vision.model_dump()
                artifacts["product_vision"] = {
                    **vision_dict,
                    "created_at": datetime.now().isoformat(),
                    "status":     "pending_review",
                }
                updates: Dict[str, Any] = {
                    "product_vision": vision_dict,
                    "artifacts":      artifacts,
                }
                if pv_feedback:
                    updates["product_vision_feedback"] = None
                logger.info(
                    "[InterviewerAgent] ProductVision extracted — "
                    "%d stakeholder(s), %d assumption(s), %d constraint(s).",
                    len(vision.target_audiences),
                    len(vision.assumptions),
                    len(vision.project_constraints),
                )
                return updates
            except Exception as exc:
                logger.error("[InterviewerAgent] Vision extraction failed: %s", exc)
                return {}

        # ── Turn 2: Agenda Bootstrap ──────────────────────────────────────────
        # Precondition: reviewed_product_vision must exist in artifacts.
        # Run when:
        #   (a) Normal path  — elicitation_agenda not yet built AND artifact absent.
        #   (b) Rebuild path — HITL rejected agenda (elicitation_agenda_feedback set);
        #                      graph.py already popped elicitation_agenda_artifact.
        agenda_feedback       = (state.get("elicitation_agenda_feedback") or "").strip()
        reviewed_vision_ready = "reviewed_product_vision" in artifacts
        agenda_runtime_absent = "elicitation_agenda" not in state
        agenda_artifact_absent= "elicitation_agenda_artifact" not in artifacts

        if reviewed_vision_ready and (agenda_runtime_absent or agenda_artifact_absent or agenda_feedback):
            logger.info(
                "[InterviewerAgent] Turn 2 — building ElicitationAgenda%s.",
                " (rebuild with reviewer feedback)" if agenda_feedback else "",
            )
            try:
                # Strip HITL-gate sentinel fields and any fields removed from the
                # schema (initial_requirements, non_functional_requirements) before
                # deserialising — guards against stale state from older runs.
                raw_vision = artifacts["reviewed_product_vision"]
                _STRIP_FROM_VISION = {
                    "status", "reviewed_at", "review_notes", "created_at",
                    "initial_requirements", "non_functional_requirements",
                }
                vision_fields = {
                    k: v for k, v in raw_vision.items()
                    if k not in _STRIP_FROM_VISION
                }
                vision_obj          = ProductVision(**vision_fields)
                project_description = state.get("project_description", "")

                if agenda_feedback:
                    agenda = self._extract_agenda(
                        vision_obj,
                        project_description=project_description,
                        reviewer_feedback=agenda_feedback,
                    )
                else:
                    agenda = self._extract_agenda(vision_obj, project_description)

                runtime = AgendaRuntime.from_agenda(agenda)

                artifacts["elicitation_agenda_artifact"] = {
                    "session_id": state.get("session_id", ""),
                    "created_at": datetime.now().isoformat(),
                    "status":     "pending_review",
                    "items":      [item.model_dump() for item in agenda.items],
                }
                updates = {
                    "elicitation_agenda": runtime.model_dump(),
                    "artifacts":          artifacts,
                }
                if agenda_feedback:
                    updates["elicitation_agenda_feedback"] = None
                logger.info(
                    "[InterviewerAgent] ElicitationAgenda built — %d item(s).",
                    len(runtime.items),
                )
                return updates
            except Exception as exc:
                logger.error("[InterviewerAgent] Agenda extraction failed: %s", exc)
                return {}

        # ── SRS Synthesis pass (once, after conclude fires) ───────────────────
        if state.get("_needs_srs_synthesis"):
            logger.info("[InterviewerAgent] Running SRS synthesis pass.")
            return self._synthesise_srs(state)

        # ── ReAct loop (all elicitation turns after both bootstrap turns) ─────
        task          = self._build_task(state)
        react_updates = self.react(
            state=state,
            task=task,
            tool_choice="required",
            profile_addendum=_REACT_ADDENDUM,
            include_memory=True,
        )

        return react_updates

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_runtime(state: Optional[Dict[str, Any]]) -> Optional[AgendaRuntime]:
        """Deserialise AgendaRuntime from state, or return None."""
        raw = (state or {}).get("elicitation_agenda")
        if raw is None:
            return None
        if isinstance(raw, AgendaRuntime):
            return raw
        try:
            return AgendaRuntime(**raw)
        except Exception as exc:
            logger.warning("[InterviewerAgent] Failed to load AgendaRuntime: %s", exc)
            return None

    @staticmethod
    def _resolve_stakeholder_detail(
        vision: Dict[str, Any],
        role_name: str,
    ) -> str:
        """Look up key_concern and type for a stakeholder from ProductVision.

        Returns a formatted string like:
          '  Type: primary_user — directly uses the system.'
          '  Key concern: "Need clear rules and examples."'
        or "" if the role is not found.
        """
        _TYPE_LABELS = {
            "primary_user":   "directly uses the system as the main audience",
            "secondary_user": "uses the system occasionally or in a supporting role",
            "beneficiary":    "gains value without directly using the system",
            "decision_maker": "approves scope, budget, or direction",
            "blocker":        "can veto or block the project",
        }

        audiences = vision.get("target_audiences") or []
        if not audiences:
            return ""

        match = None
        for entry in audiences:
            if entry.get("role", "").strip().lower() == role_name.strip().lower():
                match = entry
                break

        if match is None:
            return ""

        lines = []
        stype = match.get("type", "")
        if stype:
            label = _TYPE_LABELS.get(stype, stype)
            lines.append(f"  Type: {stype} — {label}.")
        key_concern = match.get("key_concern", "")
        if key_concern:
            lines.append(f'  Key concern: "{key_concern}"')
        return "\n".join(lines)

    def _build_task(self, state: Dict[str, Any]) -> str:
        """Inject ONLY the current agenda item + minimal Vision context.

        Fix 3 — when _agenda_needs_followup=True, injects a FOLLOW-UP CONTEXT
        block so the interviewer knows to narrow into one specific concern from
        the prior answer instead of moving to the next item.

        Multi-stakeholder — injects CURRENT STAKEHOLDER so the interviewer
        knows exactly who they are speaking with, plus already-collected
        answers from prior stakeholders as context.
        """
        runtime = self._load_runtime(state)
        vision: dict = state.get("product_vision") or {}

        # ── No agenda yet ─────────────────────────────────────────────────────
        if runtime is None:
            project_desc = state.get("project_description", "(not provided)")
            return (
                f"PROJECT: {project_desc}\n\n"
                "The elicitation agenda could not be built. "
                "Begin elicitation based on the project description alone."
            )

        # ── All items done ────────────────────────────────────────────────────
        if runtime.elicitation_complete:
            if state.get("_needs_srs_synthesis") or state.get("interview_complete"):
                return "Elicitation and synthesis complete. No further action needed."
            return (
                "All agenda items have been answered.\n"
                "Call conclude() to finalise elicitation."
            )

        item = runtime.current_item()
        if item is None:
            return "Agenda is complete. Call conclude()."

        # ── Determine current stakeholder for this turn ───────────────────────
        current_role   = (
            state.get("current_stakeholder_role")
            or item.current_stakeholder()
            or item.interviewed_stakeholder_role
            or "Unknown Stakeholder"
        )
        total_roles    = len(item.stakeholders) if item.stakeholders else 1
        role_idx       = item.stakeholder_idx if item.stakeholders else 0

        # ── Normal turn: inject current item + lightweight Vision context ─────
        answered_count = sum(1 for i in runtime.items if i.status == "answered")
        total_count    = len(runtime.items)
        enduser_answer = state.get("enduser_answer", "")
        needs_followup = state.get("_agenda_needs_followup", False)

        sections = [
            f"AGENDA PROGRESS: {answered_count}/{total_count} items answered.",
            "",
            "CURRENT ITEM:",
            f"  id:               {item.item_id}",
            f"  source_field:     {item.source_field}",
            f"  source_ref:       {item.source_ref}",
            f"  elicitation_goal: {item.elicitation_goal}",
            f"  priority:         {item.priority}",
        ]

        # ── Stakeholder context block ─────────────────────────────────────────
        # Look up key_concern and type from ProductVision so the interviewer
        # can target questions at the stakeholder's core worry.
        stakeholder_detail = self._resolve_stakeholder_detail(vision, current_role)

        if item.stakeholders:
            sections += [
                "",
                f"STAKEHOLDER COVERAGE: {role_idx + 1}/{total_roles} roles for this item.",
                f"  CURRENT STAKEHOLDER: {current_role}",
            ]
            if stakeholder_detail:
                sections.append(stakeholder_detail)
            sections.append(
                f"  Remaining after this: {', '.join(item.stakeholders[role_idx + 1:]) or 'none'}",
            )
        else:
            sections += [
                "",
                f"CURRENT STAKEHOLDER: {current_role}",
            ]
            if stakeholder_detail:
                sections.append(stakeholder_detail)

        # ── Already-collected answers from prior stakeholders ─────────────────
        if item.answers:
            prior_answers = {
                role: ans
                for role, ans in item.answers.items()
                if role != current_role
            }
            if prior_answers:
                sections += ["", "PRIOR ANSWERS FOR THIS ITEM (from other stakeholders — NOT the person you are talking to):"]
                for role, ans in prior_answers.items():
                    sections.append(f"  [{role}]: {ans}")
                sections.append(
                    "  → Use these answers as BACKGROUND CONTEXT only. "
                    "Do NOT repeat what has already been asked. "
                    "Do NOT acknowledge or reference these answers as if the "
                    "current stakeholder said them — they belong to different people. "
                    "Frame your question to surface THIS stakeholder's specific perspective."
                )

        if needs_followup and item.answer_received:
            # Stage 3 follow-up — tension-balancing (W-Framework Pull-Up)
            sections += [
                "",
                "FOLLOW-UP CONTEXT (Stage 3 — Tension Balancing):",
                f"  Stakeholder: {current_role}",
                f"  Their previous answer:",
                f"  \"{item.answer_received}\"",
                "",
                f"  Your job is to surface how {current_role} wants to navigate the tension"
                f"  in this answer — not to classify it. Call ask_question with a Stage 3"
                f"  question that names both competing needs in plain language and puts the"
                f"  trade-off in their hands.",
            ]
        elif enduser_answer:
            sections += [
                "",
                f"ENDUSER ANSWER (waiting to be recorded): {enduser_answer}",
                "→ Call record_answer first. Do not call ask_question now.",
            ]
        else:
            # Inject W-Framework stage label only — full stage guidance is in the system prompt.
            stage_hint = _w_framework_stage_hint(item.source_field, item.priority)
            sections += [
                "",
                f"QUESTION STRATEGY — {stage_hint}",
                f"→ Call ask_question. One question only. Plain language. ≤ 2 sentences.",
                f"→ Ground the question in {current_role}'s role and daily reality.",
                f"→ You are speaking with: {current_role}",
            ]

        if vision:
            sections += [
                "",
                "VISION CONTEXT:",
                f"  Core Problem:      {vision.get('core_problem', '—')}",
                f"  Value Proposition: {vision.get('value_proposition', '—')}",
            ]

        return "\n".join(sections)