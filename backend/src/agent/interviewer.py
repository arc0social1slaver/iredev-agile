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
      Inputs:  project_description + elicitation Q&A
      Output:  List[Requirement] — functional requirements only.
      Key rule: aggressive decomposition — one rich answer yields 3–6 FRs.

    Pass 2 — NFR & CON Extraction:
      Inputs:  same as Pass 1
      Output:  List[Requirement] — non-functional, constraints, out-of-scope.

    Pass 3 — Coverage Check:
      Inputs:  project_description + all requirements from Passes 1+2
      Output:  List[Requirement] — gap-filling items for uncovered PD bullets.
               All stamped source_elicitation_id="PD", status="inferred".

    Pass 4 — Quality Gate + Final Assembly:
      Inputs:  full draft from Passes 1–3 + session metadata
      Output:  SoftwareRequirementsSpecification — audited, renumbered, ordered.
      Checks:  atomicity, testability, banned adjectives, null context on FRs,
               duplicate statements.

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
        description="Job title or group label (e.g. 'First-year Student', 'Course Lecturer')."
    )
    type: Literal["primary_user", "beneficiary", "decision_maker", "blocker"] = Field(
        description=(
            "primary_user   – directly operates the system.\n"
            "beneficiary    – gains value without direct use.\n"
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
        description="True if this assumption must be confirmed before work begins."
    )


class ProductVision(BaseModel):
    """
    North Star artifact produced at the start of elicitation.
    Filtered against every Epic and User Story generated downstream.
    """

    target_audiences: List[StakeholderEntry] = Field(
        description="All relevant stakeholder groups, typed and ranked by influence."
    )
    core_problem: str = Field(
        description=(
            "The single most important pain point the project must solve. "
            "1–2 sentences. Specific enough to reject unrelated feature requests."
        )
    )
    value_proposition: str = Field(
        description=(
            "What this solution uniquely delivers to resolve the core problem. "
            "1–2 sentences. Must NOT read like a feature list."
        )
    )
    hard_constraints: List[str] = Field(
        description=(
            "Non-negotiable limits: timeline, technology, access model, compliance. "
            "Append '(implied)' to constraints inferred but not explicitly stated."
        )
    )
    assumptions: List[Assumption] = Field(
        description=(
            "Implicit beliefs driving design decisions not yet confirmed. "
            "Minimum 3. Flag which ones need stakeholder validation."
        )
    )
    core_workflows: List[str] = Field(
        description=(
            "3–5 major functional areas (Epics) that define the system's boundaries. "
            "Each Epic is a user-journey cluster, not a feature list "
            "(e.g. 'Account Management', 'Core Gameplay', 'Reporting & Archive'). "
            "MUST include at least one operational/system-level Epic "
            "(e.g. 'System Administration', 'Monitoring & Maintenance', 'Data Archive'). "
            "Every downstream requirement will be assigned to exactly one of these Epics."
        )
    )
    out_of_scope: List[str] = Field(
        description=(
            "Capabilities explicitly excluded. At least 2 items. "
            "Prevents scope creep in later sprints."
        )
    )


# ── Fix 1: extended source_field to cover initial requirements ────────────────
class AgendaItem(BaseModel):
    item_id: str = Field(
        description=(
            "Unique identifier. Use prefixes that match source_field:\n"
            "  assumption_N, stakeholder_N, hard_constraint_N,\n"
            "  out_of_scope_N, initial_req_N, eval_criterion_N."
        )
    )
    source_field: Literal[
        "assumption",
        "stakeholder_concern",
        "hard_constraint",
        "out_of_scope",
        "initial_requirement",   # Fix 1 — bullets from "Initial Requirements" section
        "evaluation_criterion",  # Fix 1 — bullets from "Evaluation Criteria" section
    ] = Field(description="Which Vision or project-description field produced this item.")
    source_ref: str = Field(
        description="Verbatim content from the Vision or project description that triggered this item."
    )
    elicitation_goal: str = Field(
        description="What must be confirmed or clarified by asking about this item."
    )
    priority: Literal["high", "medium", "low"] = Field(
        description=(
            "high   = unvalidated assumption OR initial_requirement.\n"
            "medium = constraint / stakeholder / evaluation_criterion.\n"
            "low    = out-of-scope confirmation."
        )
    )


class ElicitationAgenda(BaseModel):
    """
    Ordered list of elicitation items derived from ProductVision fields
    AND the initial requirements / evaluation criteria in the project description.
    Items are sorted high → medium → low priority by the extraction prompt.
    """
    items: List[AgendaItem] = Field(
        description=(
            "One item per elicitation need. Cover ALL of:\n"
            "  • every needs_validation assumption (priority=high)\n"
            "  • every blocker stakeholder concern (priority=medium)\n"
            "  • every hard constraint with hidden conditions (priority=medium)\n"
            "  • every bullet in the 'Initial Requirements' section (priority=high)\n"
            "  • every bullet in the 'Evaluation Criteria' section (priority=medium)\n"
            "  • at least one out-of-scope item for stakeholder confirmation (priority=low)"
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
    epic:                  str = Field(
        description=(
            "The Epic (from ProductVision.core_workflows) this requirement belongs to. "
            "Must match one of the core_workflows strings exactly. "
            "Use 'Cross-Cutting' only when the requirement genuinely spans all Epics."
        )
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
            "Business/academic justification. TWO parts, both required:\n"
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
    requirements:        List[Requirement] = Field(
        description="All derived requirements, ordered by type then priority."
    )


class RequirementList(BaseModel):
    """Wrapper schema for Passes 1–3 so extract_structured enforces req_id."""
    requirements: List[Requirement] = Field(
        description="All requirements extracted in this pass."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Runtime state (stored in WorkflowState["elicitation_agenda"])
# ─────────────────────────────────────────────────────────────────────────────

class AgendaRuntimeItem(BaseModel):
    """AgendaItem extended with runtime tracking fields."""
    item_id:          str
    source_field:     str
    source_ref:       str
    elicitation_goal: str
    priority:         str
    status:           Literal["pending", "answered", "skipped"] = "pending"
    question_asked:   Optional[str] = None
    answer_received:  Optional[str] = None
    # ── Fix 3 fields ──────────────────────────────────────────────────────────
    followup_asked:   bool          = False   # True once a follow-up question is sent
    followup_answer:  Optional[str] = None    # stores the follow-up answer before merge


class AgendaRuntime(BaseModel):
    """Live agenda stored in WorkflowState."""
    items:                List[AgendaRuntimeItem]
    current_index:        int  = 0
    elicitation_complete: bool = False

    @classmethod
    def from_agenda(cls, agenda: ElicitationAgenda) -> "AgendaRuntime":
        return cls(
            items=[
                AgendaRuntimeItem(**item.model_dump())
                for item in agenda.items
            ]
        )

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
    """Return a W-Framework stage recommendation for the current agenda item.

    Stage 1 (Wide/Discovery) — first exposure to a topic; stakeholder hasn't
      spoken about this yet.
    Stage 2 (Deep/Drill-Down) — assumption or initial_requirement that needs
      root-cause probing.
    Stage 4 (Closed/Confirmation) — out-of-scope items; just confirm agreement.

    Stage 3 (High/Pull-Up) is reserved for follow-ups — not injected here.
    """
    if source_field == "out_of_scope":
        return (
            "Stage 4 — CLOSED (Confirmation). "
            "Verify the stakeholder agrees this capability is excluded. "
            "Example: 'Just to confirm — [X] is out of scope for this project?'"
        )
    if source_field in ("assumption", "initial_requirement") or priority == "high":
        return (
            "Stage 2 — DEEP (Drill-Down / 5 Whys). "
            "This item is high-priority — probe the root cause, not just the surface need. "
            "Ask 'why is this important?' or 'what has gone wrong before when this wasn't in place?'"
        )
    # Default for stakeholder_concern, hard_constraint, evaluation_criterion
    return (
        "Stage 1 — WIDE (Discovery). "
        "Open-ended question to surface what the stakeholder values most here. "
        "Ask them to walk you through the current situation or their main concern."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

_VISION_EXTRACTION_SYSTEM = """\
You are a senior Agile Product Owner conducting the opening phase of requirements
elicitation. Read the project description carefully, then produce a ProductVision —
the North Star that will filter every Epic and User Story in this project.

THINK FIRST (internal only — do not output this reasoning):
  Before filling any field, mentally answer three questions:
  (a) Who suffers the most from the current situation, and what exactly is the pain?
  (b) What is the one thing this solution must deliver to be considered a success?
  (c) What is explicitly excluded or clearly out of reach for this project?
  (d) What are the 3–5 major user-journey clusters this system must support?
      At least one cluster must be operational/system-level (admin, monitoring, archive).
  Use these answers to anchor every field below.

RULES:
1. TARGET AUDIENCES
   – List ALL stakeholder groups mentioned or clearly implied.
   – Classify each as: primary_user / beneficiary / decision_maker / blocker.
   – Rank by influence_level (high → medium → low).
   – key_concern: ONE specific need or worry — no generic phrases like "ease of use".
   – MANDATORY: include at least one operational/system-level stakeholder
     (e.g. System Administrator, Developer, Data Analyst, Researcher) who requires
     metrics, maintenance, audit, or archive capabilities.
     If none is mentioned in the project description, infer the most likely one
     and mark their key_concern with "(implied)".

2. CORE PROBLEM
   – 1–2 sentences maximum. Ground it in observable, measurable pain.
   – Specific enough to reject unrelated feature requests as out-of-scope.
   – BAD:  "The system lacks modern tooling."
   – GOOD: "First-year students cannot identify and correct writing style errors
            in their assignments without waiting days for lecturer feedback,
            causing last-minute revisions and lower submission quality."

3. VALUE PROPOSITION
   – The OUTCOME the solution delivers for the stakeholder, not a feature list.
   – Must NOT start with "The system will …" or list technologies/features.
   – BAD:  "Provides real-time grammar checking, plagiarism detection, and a
            recommendation engine for students."
   – GOOD: "Students receive actionable, personalised feedback within seconds,
            enabling independent skill improvement before submission deadlines."

4. CORE WORKFLOWS (Epics)
   – 3–5 major functional areas that define the system's scope boundaries.
   – Each Epic is a user-journey cluster (verb + object noun phrase):
       ✓ "Account & Session Management"
       ✓ "Core Estimation Workflow"
       ✓ "Game Archive & Reporting"
       ✓ "System Administration & Monitoring"
   – MUST include at least one operational/system-level Epic.
   – These become the "hộp cát" (sandboxes) that bound downstream elicitation.
     Every requirement generated later must belong to exactly one Epic.
   – Do NOT use generic labels like "Frontend", "Backend", "Database".

5. HARD CONSTRAINTS
   – Non-negotiable limits: timeline, technology mandate, access model, compliance.
   – ONLY include constraints directly evidenced in the text.
   – Append "(implied)" to constraints you infer but that are not explicitly stated.
   – NEVER fabricate a constraint — if genuinely uncertain, record it as an
     Assumption with needs_validation=True instead.

6. ASSUMPTIONS
   – Minimum 5 implicit beliefs — cover ALL four quadrants below.
     Missing a quadrant is an extraction failure.

   QUADRANT A — USER BEHAVIOUR
     Beliefs about how users will actually interact: motivation levels,
     technical literacy, access patterns (device, location, time of day).

   QUADRANT B — TECHNICAL / INFRASTRUCTURE
     Beliefs about hosting, load, browser/device support, third-party services,
     data storage location, integration with existing systems.
     Examples: "The system will be accessed from campus Wi-Fi only (implied)",
               "No authenticated login is required (implied)".

   QUADRANT C — SECURITY / PRIVACY / COMPLIANCE
     Beliefs about what data is collected, who can see it, and what regulations
     apply (GDPR, FERPA, institutional policy).
     Examples: "No personally identifiable data is stored (implied)",
               "Content does not require editorial review before publishing (implied)".

   QUADRANT D — OPERATIONAL / MAINTENANCE
     Beliefs about who maintains the system after launch, update cadence,
     content ownership, and what happens when content becomes outdated.
     Examples: "Content updates are infrequent and handled by one author (implied)",
               "No SLA or uptime guarantee is required (implied)".

   – risk_if_wrong: ONE concrete consequence sentence (not "it may fail").
   – Set needs_validation=True for any assumption that, if false, would materially
     change the project scope, architecture, timeline, or compliance posture.

7. OUT OF SCOPE
   – At least 2 capabilities EXPLICITLY excluded or clearly outside the boundary.
   – Use definitive language; avoid hedging words like "may" or "might".
   – BAD:  "Advanced analytics may not be included in the first release."
   – GOOD: "Real-time plagiarism detection against external databases is excluded
            from this project."

Return structured JSON only. No prose outside schema fields.
"""

_VISION_EXTRACTION_USER = "Project Description:\n{project_description}"

# ── Fix 1: expanded mapping rules ─────────────────────────────────────────────
_AGENDA_EXTRACTION_SYSTEM = """\
You are an Agile requirements analyst. Given a ProductVision AND the original
project description, build an ordered ElicitationAgenda — a comprehensive list
of AgendaItems that the interviewer must cover to resolve every open question.

THINK FIRST (internal only — do not output this reasoning):
  Scan the ProductVision for every assumption with needs_validation=True, every
  blocker stakeholder, every constraint that could have hidden conditions.
  Scan the project description for every bullet in "Initial Requirements" and
  "Evaluation Criteria" sections. Count how many items each mapping rule produces
  before writing the final list — this ensures no bullet is accidentally omitted.

MAPPING RULES — apply ALL of them, in this order:

  1. assumption (needs_validation=True)
       → one AgendaItem per assumption, priority="high"
       → source_field: "assumption"
       → source_ref: verbatim assumption statement from ProductVision
       → elicitation_goal: TWO-PART — BOTH are required:
           (a) VALIDATION: "Confirm whether '<statement>' is true in this project's
               context and identify how a false assumption changes scope or design."
           (b) SCENARIO PROBE: Name the concrete failure scenario that tests this
               assumption. Write it as: "Ask what happens when [failure condition]."
               For Quadrant B/C/D assumptions this is especially critical:
                 B (infrastructure): "Ask how many concurrent users are expected
                    and whether the system must work offline or on mobile devices."
                 C (security/privacy): "Ask what student data the system will handle
                    and what happens if a data breach occurs."
                 D (operational): "Ask who will update content after launch and
                    what the process is when information becomes outdated."
         Write the elicitation_goal as one combined sentence covering both parts.
       → item_id: "assumption_N" (N = 0-based index)
       → MANDATORY: assumptions from all four quadrants (A=user behaviour,
         B=technical, C=security/privacy, D=operational) MUST each have at least
         one agenda item. If the ProductVision assumptions are clustered in only
         1–2 quadrants, generate synthetic high-priority items for the missing
         quadrants, marking their source_ref with "(inferred — no explicit
         assumption; quadrant must be probed)".

  2. stakeholder with type="blocker"
       → one AgendaItem per blocker, priority="medium"
       → source_field: "stakeholder_concern"
       → source_ref: verbatim key_concern of that stakeholder
       → elicitation_goal: "Clarify what compliance, approval, or veto conditions
         <role> imposes and the minimum threshold to satisfy them."
       → item_id: "stakeholder_N"

  3. hard_constraint
       → one AgendaItem per constraint that may have hidden conditions,
         priority="medium"
       → source_field: "hard_constraint"
       → source_ref: verbatim constraint text from ProductVision
       → elicitation_goal: "Clarify the exact standard, threshold, or exception
         behind this constraint: '<constraint>'."
       → item_id: "hard_constraint_N"

  4. initial_requirement
       → one AgendaItem for EACH bullet in the "Initial Requirements" section
         (or equivalent) of the project description, priority="high"
       → source_field: "initial_requirement"
       → source_ref: verbatim bullet text — copy exactly, do NOT paraphrase
       → elicitation_goal: TWO-PART goal — must cover BOTH:
           (a) SCOPE: "Confirm the exact scope, acceptance threshold, and edge
               cases for: '<bullet>'."
           (b) VALUE: "Identify what the user can do DIFFERENTLY once this
               requirement is met — the concrete outcome or workflow improvement
               they gain ('So that...')."
         Write the elicitation_goal as one combined sentence covering both parts.
       → item_id: "initial_req_N" (N = 0-based index)

  5. evaluation_criterion
       → one AgendaItem for EACH bullet in the "Evaluation Criteria" section
         (or equivalent), priority="medium"
       → source_field: "evaluation_criterion"
       → source_ref: verbatim criterion text — copy exactly, do NOT paraphrase
       → elicitation_goal: "Clarify the measurable threshold that defines
         success for: '<criterion>'."
       → item_id: "eval_criterion_N"

  6. out_of_scope
       → one AgendaItem per out-of-scope item, priority="low"
       → source_field: "out_of_scope"
       → source_ref: verbatim exclusion text from ProductVision
       → elicitation_goal: "Confirm that all stakeholders agree this capability
         is excluded and identify any edge case that might bring it back in scope."
       → item_id: "out_of_scope_N"

  7. epic_coverage
       → one AgendaItem for EACH Epic in ProductVision.core_workflows, priority="medium"
       → source_field: "stakeholder_concern"
       → source_ref: verbatim Epic label from core_workflows
       → elicitation_goal: "For the '<Epic>' area: identify any sub-roles or
         permission levels within this user group (e.g. who can delete vs. who
         can only view), and confirm what a successful outcome looks like for
         the stakeholder most affected by this area."
       → item_id: "epic_N" (N = 0-based index)
       → Skip this rule for any Epic whose content is already fully covered
         by existing initial_requirement items (DEDUPLICATION GUARD applies).

DEDUPLICATION GUARD:
  If two mapping rules would produce items with near-identical elicitation_goal
  (same underlying question), keep only the HIGHER-priority one and note the
  overlap in elicitation_goal. Do NOT generate duplicate questions for the same
  concern expressed in different source sections.

ORDER: high → medium → low.
Within the same priority, preserve the order items appear in the source document.

Return structured JSON only. No prose outside schema fields.
"""

_AGENDA_EXTRACTION_USER = """\
ProductVision (JSON):
{vision_json}

Core Workflows / Epics (from ProductVision — use these as sandboxes for epic_coverage items):
{core_workflows_list}

Original Project Description (for initial_requirement and evaluation_criterion mapping):
{project_description}
"""

# ── v3: Active Listening + LLM-delegated follow-up + relaxed decomposition ─────
_REACT_ADDENDUM = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRE-TURN INNER MONOLOGUE — run silently before every tool call
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before calling any tool, answer these mentally:

  [1] CLASSIFICATION:
      Is the information Functional (what must happen),
      Non-Functional (quality/constraint/performance), or a hidden concern?

  [2] HIDDEN REQUIREMENTS CHECK:
      Is the answer too simple or surface-level?
      If YES → drill down. Ask "Why?" or "What if?"

  [3] STRATEGY: Drill-Down or Pull-Up?
      Drill-Down (Stage 2): Go deeper — root cause, past failures.
      Pull-Up (Stage 3):    Zoom out — competing needs, trade-off balancing.
        Use ONLY when _agenda_needs_followup=True.

  [4] FOLLOW-UP DECISION (only when an answer is present):
      A follow-up is warranted ONLY when a GENUINE TENSION exists.
      Ask: "Which two dimensions pull in opposite directions here?"
        usability ↔ security | automation ↔ control | speed ↔ accuracy
        openness ↔ privacy   | cost ↔ quality       | flexibility ↔ simplicity
      If you CANNOT name the specific tension → needs_follow_up=False.
      Long answers or many topics alone are NOT sufficient reasons.

  [5] ACKNOWLEDGMENT DRAFTING (only when about to call ask_question):
      Draft one sentence mirroring a SPECIFIC element from the prior answer.
      GOOD: "Understood — your concern is that unclear wording gets ignored."
      BAD:  "Thank you for sharing." / "Great, let's move on."
      EXCEPTION: the very first question has no prior answer — pass empty string.

  Then:
    □ Am I about to call more than one tool?  → STOP. One tool only.
    □ ENDUSER ANSWER present AND _agenda_needs_followup=False? → MUST call record_answer.
    □ _agenda_needs_followup=True?  → MUST call ask_question (Stage 3 follow-up).
    □ Have I already asked a follow-up this item? → Do NOT ask another.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TURN STRUCTURE — EXACTLY ONE TOOL PER TURN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Each turn you receive:
  • AGENDA PROGRESS
  • CURRENT ITEM
  • ENDUSER ANSWER (optional)
  • FOLLOW-UP CONTEXT (optional)

DECISION TREE — follow exactly, top to bottom:

  ┌─ elicitation_complete = True?
  │     YES → call conclude ONLY.
  │
  ├─ FOLLOW-UP CONTEXT present (_agenda_needs_followup = True)?
  │     YES → call ask_question ONLY with a Stage 3 tension-balancing question.
  │           Include acknowledgment referencing the prior answer.
  │           Do NOT call record_answer — original answer already stored.
  │
  ├─ ENDUSER ANSWER present AND _agenda_needs_followup = False?
  │     YES → call record_answer ONLY with:
  │             needs_follow_up=True  if a NAMED tension exists (see [4] above)
  │             needs_follow_up=False otherwise
  │             follow_up_reasoning = one sentence naming the tension,
  │               OR empty string if needs_follow_up=False.
  │
  └─ No answer, no follow-up, not complete?
        YES → call ask_question ONLY. One Stage 1 or Stage 2 question.
              Include acknowledgment when a prior answer exists.

NEVER call two tools in one turn.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
W-FRAMEWORK — every question fits exactly one stage
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Stage 1 — WIDE (Discovery)
    Open-ended. Surface what the stakeholder cares about.
    "Walk me through how you currently handle [topic]…"
    "What worries you most about [area]?"
    → Use for the FIRST question on any agenda item.

  Stage 2 — DEEP (Drill-Down / 5 Whys)
    Narrow in on a specific concern. Go to root cause.
    "You mentioned [X] — what specifically makes that a problem for you?"
    "What went wrong in the past when [X] wasn't in place?"
    → Use when the prior answer feels surface-level.

  Stage 3 — HIGH (Pull-Up / Tension Balancing)
    Zoom out. Ask how competing needs should be balanced.
    "How do you want to handle the situation where [A] conflicts with [B]?"
    "If you had to choose between [X] and [Y], which matters more for you?"
    → Use ONLY when _agenda_needs_followup=True.
    → NEVER use as the first question on a new agenda item.

  Stage 4 — CLOSED (Confirmation)
    Verify a specific boundary, threshold, or constraint.
    "So to confirm — if [condition], the system must [behaviour]?"
    → Reserve for out-of-scope or confirmation items only.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FOLLOW-UP RULES (Stage 3 — when _agenda_needs_followup=True)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Step 1 — Read the previous answer. Find the strongest tension.
  Step 2 — Name it: "This is a [X] ↔ [Y] tension."
            If you cannot name it → the follow-up should not have been triggered.
  Step 3 — Ask ONE question about how to BALANCE that tension.

  ✓ GOOD: "You mentioned strict access control — how would you handle a student
    who genuinely needs access from a shared campus library computer?"
  ✗ BAD:  "What types of access controls specifically are you thinking of?"
          (Stage 2 — not a tension question.)

  Hard limit: ONE follow-up per item. Never request a second.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUESTION QUALITY RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. ONE question per turn.
  2. Match W-Framework stage (Stage 1 first, Stage 2 to drill, Stage 3 for follow-up).
  3. Be specific to the current item's elicitation_goal.
  4. Neutral — do not lead the stakeholder toward a preferred answer.
  5. No redundancy — do not re-ask answered questions.
  6. ≤ 2 sentences total (acknowledgment + question).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ANTI-PATTERNS — NEVER do these
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✗ Call record_answer and ask_question in the same turn.
  ✗ Ask a question when an ENDUSER ANSWER is waiting (and no follow-up is due).
  ✗ Ask about a different item than the CURRENT ITEM.
  ✗ Re-ask a question already answered.
  ✗ Lead the stakeholder toward a specific answer.
  ✗ Use technical jargon in question or acknowledgment.
  ✗ Use "how to balance X?" as a first question — Stage 3 is for follow-ups only.
  ✗ Narrate your reasoning — deliver acknowledgment + question only.
  ✗ Request a second follow-up after the first follow-up answer is received.
  ✗ Set needs_follow_up=True because the answer is long — only when you can
    NAME the specific tension dimension.
  ✗ Use generic acknowledgments ("Thank you", "Great point", "Let's move on").

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

# ── Shared field-level guidance injected into every pass prompt ───────────────
_FIELD_GUIDANCE = """\
FIELD-LEVEL RULES (apply to EVERY requirement you generate):

──────────────────────────────────────────────────────
epic
──────────────────────────────────────────────────────
  • Assign to exactly ONE Epic from ProductVision.core_workflows.
  • The Epic label must match the core_workflows string exactly.
  • Use 'Cross-Cutting' ONLY when the requirement genuinely applies to every Epic
    (e.g. a global accessibility or security policy).
  • NEVER leave this field empty. A requirement without an Epic is an
    extraction failure — Pass 4 must reject and re-assign it.

──────────────────────────────────────────────────────
statement
──────────────────────────────────────────────────────
Format:  "The system SHALL …" or "The system SHALL NOT …"
Rules:
  • ONE behaviour, ONE verb.
  • If the sentence contains "and" or "or" linking two DISTINCT behaviours,
    split it into two separate Requirement objects immediately.
  • Testable by a QA engineer from the statement alone — no guessing required.
  • No implementation detail: no library names, no framework choices, no tech stack.
  • BANNED modal verbs in the statement: should, may, can, could, might, ideally.

  BAD:  "The system should handle assignment uploads and provide feedback quickly."
  GOOD-1: "The system SHALL accept assignment uploads in PDF and DOCX formats."
  GOOD-2: "The system SHALL return automated feedback within 30 seconds of submission."

──────────────────────────────────────────────────────
stakeholder
──────────────────────────────────────────────────────
  • A SPECIFIC role from the Project Description
    (e.g. "First-year Students", "Course Lecturers", "IT Support Staff").
  • NEVER "All Users", "Everyone", or "End Users" — if truly universal,
    use the most affected primary_user role and note "(affects all roles)".

──────────────────────────────────────────────────────
context
──────────────────────────────────────────────────────
  • WHERE or WHEN this requirement applies.
    Examples: "On the assignment submission page",
              "When a student clicks 'Submit'",
              "During the grading workflow".
  • MUST NOT be null for any functional requirement.
  • For NFR/CON that apply system-wide, use "Across all system interactions".

──────────────────────────────────────────────────────
rationale
──────────────────────────────────────────────────────
  TWO parts — BOTH are mandatory for every requirement:

  (a) PAIN — cite or closely paraphrase the stakeholder's own words from the
      elicitation answer that describes the current problem or frustration.
      Must be traceable to a specific elicitation item (EL-NNN) or the project
      description (PD).

  (b) OUTCOME ("So that") — the concrete workflow improvement the stakeholder
      achieves once this requirement is met. State it as:
      "So that [specific role] can [observable outcome]."
      If the elicitation answer did not explicitly state the outcome, infer the
      most plausible one from context and set status="inferred" on this requirement.

  Format:  "<pain statement>. So that <outcome statement>."

  BAD:  "This is important for user satisfaction."
  BAD:  "Stakeholder stated: 'Students get frustrated when feedback is slow.'"
        (pain only — missing the outcome)
  GOOD: "Stakeholder stated: 'Students close the tab if they wait more than a
         minute.' So that students can review automated feedback before their
         next revision cycle without losing momentum."

  Do NOT copy-paste the same rationale text across multiple requirements.

──────────────────────────────────────────────────────
acceptance_criteria
──────────────────────────────────────────────────────
  Format:  Given-When-Then bullets (1–3 for FR, 1–2 for NFR).
  Rules:
  • ONLY objective, measurable conditions — no subjective assertions.
  • Use technical thresholds, not adjectives:
      ✗ "The interface should be easy to use."
      ✓ "Response time ≤ 2 s under 500 concurrent users."
      ✓ "WCAG 2.1 Level AA compliance on all interactive elements."
      ✓ "Viewport renders correctly at widths ≥ 320 px."

  BANNED words anywhere in acceptance_criteria:
    easy, clean, user-friendly, intuitive, beautiful, simple, appropriate,
    fast, quickly, seamlessly, properly, correctly (without threshold),
    reasonable, adequate, sufficient.

  Empty list [] is VALID for constraint (CON) and out_of_scope (OOS) items.

──────────────────────────────────────────────────────
priority
──────────────────────────────────────────────────────
  Inherit from the elicitation item's priority unless the stakeholder's answer
  explicitly overrides it. All out_of_scope items → "low".

──────────────────────────────────────────────────────
status
──────────────────────────────────────────────────────
  confirmed  – stakeholder explicitly stated this in their own words.
  inferred   – implied but not directly stated; flag for human reviewer.
               Also set to "inferred" when the rationale outcome was inferred
               rather than explicitly stated by the stakeholder.
  excluded   – out-of-scope; recorded as an anti-requirement.
"""

# ── Pass 1: Functional Requirements ──────────────────────────────────────────
_PASS1_SYSTEM = """\
You are a senior Requirements Engineer performing Pass 1 of a 4-pass SRS
synthesis pipeline.

YOUR ONLY JOB THIS PASS: extract Functional Requirements (FR) from the
elicitation record. Do NOT extract NFR, CON, or OOS items — those belong to Pass 2.

─────────────────────────────────────────────────────
WHAT IS A FUNCTIONAL REQUIREMENT?
─────────────────────────────────────────────────────
A system behaviour — something the system must DO, DISPLAY, ALLOW, or PREVENT.
Functional requirements map from source_fields:
  assumption | stakeholder_concern | initial_requirement

─────────────────────────────────────────────────────
PRE-EXTRACTION SCAN (run before writing any output):
─────────────────────────────────────────────────────
For each elicitation item, read BOTH the main answer AND the [follow-up] block
(if present). They are separate evidence sources — do not skip either.

For each block, count:
  (a) Distinct ACTORS mentioned (including secondary stakeholders).
  (b) Distinct TRIGGERS or entry conditions.
  (c) Distinct SYSTEM RESPONSES, outputs, or content types.
  Each unique combination of (actor + trigger + response) = one FR candidate.

─────────────────────────────────────────────────────
ASSUMPTION ITEM RULE (source_field = "assumption"):
─────────────────────────────────────────────────────
Assumption items are often the richest source of BEHAVIOURAL requirements because
they expose what the system must actively DO to validate or support the assumption.

For EVERY assumption item:
  Step 1 — Read the source_ref (the assumption statement).
  Step 2 — Ask: "What must the system DO or DISPLAY so that this assumption
            holds true or is actively supported?"
  Step 3 — Generate at least ONE FR per distinct system behaviour identified.
  Step 4 — Check the [follow-up] block for engagement/motivation/onboarding
            behaviours (e.g. connecting guidelines to interests, showing benefits,
            providing scaffolding). These yield SEPARATE FRs — do not fold them
            into a single "provide guidance" FR.

  EXAMPLE assumption: "Students are motivated to learn about responsible AI use."
  → FR: "The system SHALL display the real-world consequence (grade penalty or
         academic misconduct flag) of each prohibited AI use case alongside
         the rule that prohibits it."
  → FR: "The system SHALL surface a 'Why this matters' callout on each guidance
         page linking the rule to a concrete student benefit."
  These are DISTINCT from a generic "provide guidance" FR.

─────────────────────────────────────────────────────
SECONDARY STAKEHOLDER RULE:
─────────────────────────────────────────────────────
The elicitation record may mention stakeholders beyond the primary user.
Before finalising output, scan every item for named roles other than the
primary user (e.g. teachers, managers, administrators, advisors, support staff).

For each secondary stakeholder mentioned:
  • Determine whether the answer implies a system behaviour serving that role.
  • If yes → generate a SEPARATE FR with stakeholder set to that role.
  • Do NOT fold secondary-stakeholder needs into primary-user requirements.

  MANDATORY: Items with source_field = "assumption" or "stakeholder_concern"
  frequently mention teacher or admin needs in [follow-up] blocks.
  Scan ALL [follow-up] blocks for secondary stakeholder behaviours even when
  the primary answer was written for students.

─────────────────────────────────────────────────────
FOLLOW-UP EXTRACTION RULE:
─────────────────────────────────────────────────────
[follow-up] blocks contain tension-resolution answers that frequently introduce
new actionable system behaviours not present in the main answer. For each
[follow-up] block:
  (a) Identify any actor+trigger+response combination not already captured
      from the main answer → generate a new FR.
  (b) Identify any new content type, user-facing feature, or support pathway
      mentioned (e.g. onboarding pages, help sections, downloadable resources,
      search features, progressive disclosure patterns, callout components)
      → generate a separate FR per distinct item.
  (c) Identify negated behaviours ("must not", "avoid", "should not", "no X",
      "not flashy", "not cluttered") → generate a SHALL NOT FR for each.
  (d) Identify ENGAGEMENT or MOTIVATION language ("curious", "connect to interests",
      "show benefits", "makes them want to") → these imply a presentation behaviour
      the system must support. Generate a distinct FR for each engagement mechanism.

Do not discard a [follow-up] block because the main answer already yielded FRs.
The two blocks are independent sources.

─────────────────────────────────────────────────────
CONTEXT SPECIFICITY RULE (critical for MDC):
─────────────────────────────────────────────────────
The `context` field MUST identify WHERE or WHEN — as specifically as possible.
Generic values like "On the website" or "In the system" are EXTRACTION FAILURES.

REQUIRED specificity levels:
  • Name the PAGE or SECTION: "On the AI Use Guidelines page"
  • OR name the TRIGGER: "When a student navigates to a risk topic"
  • OR name the WORKFLOW STEP: "During the student's first session on the site"

BANNED context values (reject and rewrite):
  ✗ "On the AIGuidebook website"           → too generic
  ✗ "Across all system interactions"       → use for NFR/CON only, never FR
  ✗ "In the system"                        → too generic
  ✗ "On the website"                       → too generic

GOOD examples:
  ✓ "On the Responsible AI Use guidance page, when a student views a rule"
  ✓ "On the Privacy & Data Protection section"
  ✓ "When a student opens the interactive checklist element"
  ✓ "On the Academic Integrity page, when a student reads an example"
  ✓ "In the Teacher Resources section, when a teacher browses shared materials"

Each FR for a different page/section/trigger must have a DIFFERENT context value.
Two FRs with identical context values must differ in stakeholder or system response.

─────────────────────────────────────────────────────
DECOMPOSITION RULE — split on signal, not on count:
─────────────────────────────────────────────────────
Split one answer into MULTIPLE FRs ONLY when you observe a CLEAR change in at
least one of these three dimensions:

  ACTOR   — a different role is the primary subject (student vs. teacher vs. admin)
  TRIGGER — a different entry condition or user action initiates the behaviour
  OUTCOME — the system produces a distinctly different output or state change

Do NOT split merely because an answer is long, lists several topics, or uses
"also" / "and" as connective tissue. One well-articulated answer may yield
exactly 1 excellent FR.

  SPLIT → "Students can browse rules AND teachers can flag a rule for review."
           Actor changes (student → teacher) + outcome changes → 2 FRs.

  NO SPLIT → "The guidance should be clear, visually clean, and well-organised."
              Same actor + same trigger + same outcome (page presentation) → 1 FR
              with a specific acceptance criterion. Do NOT manufacture 3 FRs.

SELF-CHECK before submitting output:
  For every FR you are about to write, confirm it passes the ACTOR/TRIGGER/OUTCOME
  test against every other FR from the same elicitation item.
  If two FRs share all three dimensions → merge into one more specific statement.
  If they differ on at least one dimension → keep both.

  NOTE: there is NO minimum FR count per item. A focused, specific answer that
  expresses one coherent behaviour should produce exactly 1 FR. Forcing 3–6 FRs
  from such an answer creates near-duplicates that harm MDC and SRS quality.

ASSUMPTION ITEMS — minimum 2 FRs still applies ONLY when:
  • The main answer and the [follow-up] block each contain at least one
    DISTINCT actor/trigger/outcome combination not already captured.
  If the follow-up merely elaborates the same behaviour → do NOT generate a
  separate FR; instead, strengthen the single FR's acceptance_criteria.

MERGE RULE — merge into ONE more specific statement ONLY when two candidates
  share the same stakeholder AND trigger AND outcome (even with different wording):
  ✗ "The system SHALL store user data securely."
  ✗ "The system SHALL protect user data from unauthorised access."
  ✓ "The system SHALL encrypt all user data at rest using AES-256."

DECOMPOSITION EXAMPLES (domain-neutral):
  Answer: "notifications, audit logs, and role-based access"
  → FR-001: The system SHALL send an in-app notification to the actor when a
             watched item changes state.
  → FR-002: The system SHALL write a timestamped audit-log entry for every
             state-changing action performed by any user.
  → FR-003: The system SHALL restrict access to each feature based on the
             authenticated user's assigned role.
  (Three FRs because actor + trigger + outcome each differ across items.)

  Answer: "The page should feel welcoming and use calming colours."
  → FR-001: The system SHALL render the guidance page using a colour palette
             where background and foreground contrast ratio ≥ 4.5:1 (WCAG AA).
  (One FR — same actor, same page, same visual output. Do not split into
   "welcoming tone FR" + "colour FR" + "layout FR" if only one behaviour is described.)

─────────────────────────────────────────────────────
ATOMICITY RULE:
─────────────────────────────────────────────────────
One behaviour per statement. If your statement contains "and" linking two
behaviours → split into two requirements before writing the output.

─────────────────────────────────────────────────────
ID ALLOCATION:
─────────────────────────────────────────────────────
FR-001, FR-002, … (sequential, no gaps, never reuse).
source_elicitation_id: "EL-NNN" matching the elicitation item id.

─────────────────────────────────────────────────────
OUTPUT CONTRACT:
─────────────────────────────────────────────────────
Return a JSON array of Requirement objects ONLY.
No prose, no markdown fences, no explanation text outside the array.
Schema per object: req_id, epic, req_type ("functional"), stakeholder, statement,
context, rationale, acceptance_criteria, priority, source_elicitation_id, status.

{field_guidance}
"""

_PASS1_USER = """\
PROJECT DESCRIPTION:
{project_description}

ELICITATION RECORD ({item_count} items):
{elicitation_json}

EXTRACTION CHECKLIST — work through these in order before writing output:

1. For each assumption item (source_field="assumption"):
   - List distinct actor+trigger+outcome combos from the main answer.
   - List distinct actor+trigger+outcome combos from the [follow-up] block
     (treat as an independent source).
   - Generate one FR per distinct combo. If both blocks describe the same
     behaviour, strengthen one FR's acceptance_criteria — do NOT duplicate.

2. For each initial_requirement item:
   - List distinct actor+trigger+outcome combos (not just topic areas).
   - Confirm context is specific (names a page, section, or trigger — not "On the website").
   - One focused behaviour = 1 FR. Multiple distinct combos = multiple FRs.

3. Scan all [follow-up] blocks for secondary stakeholder mentions (teachers, admins).
   Confirm each generates a SEPARATE FR with that stakeholder — different actor = split.

4. Confirm NO two FRs share identical (actor + trigger + outcome).
   If two FRs match on all three → merge into one more specific statement.

Then extract ALL Functional Requirements. Return a JSON array.
"""

# ── Pass 2: Non-Functional Requirements, Constraints, Out-of-Scope ───────────
_PASS2_SYSTEM = """\
You are a senior Requirements Engineer performing Pass 2 of a 4-pass SRS
synthesis pipeline.

YOUR ONLY JOB THIS PASS: extract Non-Functional Requirements (NFR), Constraints
(CON), and Out-of-Scope items (OOS) from the elicitation record.

─────────────────────────────────────────────────────
NFR IDENTITY TEST — apply before writing any NFR:
─────────────────────────────────────────────────────
Before classifying anything as NFR, apply this two-question test:

  Q1: "Does this statement describe WHAT the system must DO, DISPLAY, or ALLOW?"
      YES → This is a Functional Requirement. It belongs in Pass 1. SKIP — do not
            write it here. Restatements of FR behaviours as NFRs inflate the SRS
            with fake diversity and destroy quality metrics.

  Q2: "Does this statement include a measurable threshold, standard, or limit?"
      NO  → It is NOT ready to be an NFR. Either:
            (a) Derive a threshold from an industry standard (WCAG, ISO 9241,
                OWASP, HTTP response time conventions) and set status="inferred", OR
            (b) Reclassify as CON if it is a hard process/legal limit with no threshold.

  A valid NFR answers: "How WELL, how FAST, how RELIABLY, or how SECURELY
  must the system perform a behaviour that Pass 1 already captured?"

  EXAMPLES of INVALID NFRs (= behaviour restatements — do NOT generate):
    ✗ "The system SHALL provide clear rules and examples."   ← behaviour → Pass 1
    ✗ "The system SHALL be accessible and readable."         ← behaviour → Pass 1
    ✗ "The system SHALL include interactive elements."       ← behaviour → Pass 1

  EXAMPLES of VALID NFRs (= quality attributes with measurable thresholds):
    ✓ "The system SHALL load any page within 3 seconds on a 10 Mbps connection."
    ✓ "The system SHALL achieve WCAG 2.1 Level AA compliance on all public pages."
    ✓ "The system SHALL remain available 99.5% of the time during academic term hours."
    ✓ "The system SHALL NOT collect or store any personally identifiable information."
    ✓ "The system SHALL render all pages correctly at viewport widths ≥ 320 px."
    ✓ "The system SHALL display content in a colour palette where text contrast
       ratio is ≥ 4.5:1 for normal text and ≥ 3:1 for large text (WCAG AA)."

─────────────────────────────────────────────────────
CATEGORY DECISION TABLE — use this to classify each concern:
─────────────────────────────────────────────────────
  Ask: "Does this concern describe WHAT the system must DO?"
    YES → Functional Requirement → belongs in Pass 1, SKIP here.
    NO  → Ask: "Does this describe a quality ATTRIBUTE with a measurable threshold?"
      YES → NFR (non_functional).
      NO  → Ask: "Is this a non-negotiable LIMIT on how the system is built or operated?"
        YES → CON (constraint). Examples: technology mandate, budget cap,
              legal/compliance requirement, deployment environment, access model.
        NO  → Ask: "Is this a capability EXPLICITLY EXCLUDED from this project?"
          YES → OOS (out_of_scope).

─────────────────────────────────────────────────────
QUALITY DIMENSIONS TO PROBE (for CHV coverage):
─────────────────────────────────────────────────────
Scan the elicitation record for evidence of ALL of the following dimensions.
Generate at least one NFR for EACH dimension where evidence exists:

  PERFORMANCE — page load time, response latency, throughput.
    Trigger signals: "crash", "slow", "overloaded", "lots of students", "won't work".

  RELIABILITY / AVAILABILITY — uptime, error recovery.
    Trigger signals: "crash", "work all the time", "academic term", "deadlines".

  ACCESSIBILITY — WCAG level, keyboard navigation, screen reader, contrast ratio.
    Trigger signals: "disabilities", "regardless of abilities", "screen reader",
                     "readable text", "navigate without trouble".

  PRIVACY / DATA PROTECTION — PII handling, GDPR, data minimisation.
    Trigger signals: "data protection", "regulations", "privacy", "GDPR",
                     "personal information", "store data".

  CONTENT INTEGRITY — review/approval process, citation standards, accuracy.
    Trigger signals: "review process", "checked before it goes live",
                     "accurate and trustworthy", "external sources", "citations".

  VISUAL / BRAND CONSISTENCY — colour theme, typography standards.
    Trigger signals: "green theme", "consistent", "colours", "fonts",
                     "professional", "clean design".

  USABILITY THRESHOLD — task completion rate, error rate, time-on-task.
    Trigger signals: "frustration", "give up", "confused", "testing", "usability tests".

─────────────────────────────────────────────────────
ANTI-DUPLICATION RULE (critical):
─────────────────────────────────────────────────────
Pass 1 already owns all system behaviours (what the system must DO/DISPLAY/ALLOW/PREVENT).
If a concern spans both a quality attribute AND a behaviour:
  → Extract ONLY the quality dimension here (the threshold, the standard, the limit).
  → Leave the behaviour itself to Pass 1.

  EXAMPLE — "accessible navigation":
    Pass 1 (FR): "The system SHALL display a persistent navigation menu on every page."
    Pass 2 (NFR): "The system SHALL support full keyboard navigation across all pages
                   with no mouse dependency (WCAG 2.1 SC 2.1.1)."

  EXAMPLE — "clear citation display":
    Pass 1 (FR): "The system SHALL display a formatted citation beneath each
                  externally sourced piece of content."
    Pass 2 (CON): "All external content citations SHALL follow APA 7th edition format."

─────────────────────────────────────────────────────
CATEGORY DEFINITIONS:
─────────────────────────────────────────────────────
  NFR (non_functional) — ID prefix: NFR-001, NFR-002, …
    Maps from: hard_constraint (quality-focused), evaluation_criterion,
    stakeholder_concern (when quality-focused), [follow-up] tension resolution.
    EVERY NFR statement MUST include a measurable threshold or named standard.
    If the elicitation answer does not supply one, set status="inferred" and apply
    the most relevant industry standard (WCAG 2.1, ISO 9241, OWASP, HTTP spec).
    acceptance_criteria MUST contain at least 1 Given-When-Then bullet with a
    measurable condition — empty [] is NOT valid for NFR items.

  CON (constraint) — ID prefix: CON-001, CON-002, …
    Maps from: hard_constraint (operational/legal/compliance).
    Statement describes a non-negotiable limit, NOT a behaviour or quality attribute.
    rationale MUST cite the stakeholder's own words (pain + "So that" outcome).
    Generic rationale like "to meet project goals" is an extraction failure.

  OOS (out_of_scope) — ID prefix: OOS-001, OOS-002, …
    Maps from: out_of_scope agenda items.
    status MUST be "excluded". priority MUST be "low". acceptance_criteria MUST be [].
    Statement format: "The system SHALL NOT provide …"
    rationale MUST state WHY this is excluded (business reason or scope boundary),
    not just restate the statement. A rationale of "." or empty string is a failure.

─────────────────────────────────────────────────────
FOLLOW-UP EXTRACTION RULE:
─────────────────────────────────────────────────────
[follow-up] blocks are the PRIMARY source for CON and NFR items because follow-up
questions specifically probe tensions and trade-offs. Read every [follow-up]
block independently from the main answer and apply the following scan:

  (a) PRIORITY ORDERING → NFR.
      When the stakeholder explicitly ranks two qualities (e.g. "X first, then Y"),
      extract an NFR that encodes the priority as a measurable acceptance criterion.

  (b) NEGATIVE CONSTRAINTS → CON using SHALL NOT.
      Trigger words: "shouldn't", "must not", "avoid", "not overdo", "no X",
      "not flashy", "not cluttered", "not overwhelming", "not too rigid", "limit",
      "don't get stuck in too many meetings", "not overcomplicate".
      For each negative statement found → generate one CON with SHALL NOT.
      Skipping a negative statement is an extraction failure.

  (c) ROLE-DIFFERENTIATED QUALITY NEEDS → separate NFR per role.
      If the [follow-up] mentions a quality need for a secondary stakeholder
      (e.g. teacher flexibility, admin control) that differs from the primary
      user's need → generate a distinct NFR for that role.

  (d) PROCESS / OPERATIONAL CONSTRAINTS → CON.
      Mentions of workflow limits, meeting frequency, team structure, or
      development approach preferences → CON items.

─────────────────────────────────────────────────────
DECOMPOSITION RULE (same as Pass 1):
─────────────────────────────────────────────────────
One answer mentioning multiple quality dimensions → separate NFR per dimension.
  EXAMPLE: "contrast ratios, keyboard navigation, and text alternatives"
    → NFR-001: contrast ratio ≥ 4.5:1 for normal text (WCAG AA)
    → NFR-002: full keyboard navigation without mouse dependency (WCAG 2.1 SC 2.1.1)
    → NFR-003: text alternatives for all non-text content (WCAG 2.1 SC 1.1.1)

Merge near-identical NFRs into one more specific statement — do NOT list both.

─────────────────────────────────────────────────────
ID ALLOCATION:
─────────────────────────────────────────────────────
Start fresh: NFR-001, CON-001, OOS-001. Pass 1 owns FR-NNN.

─────────────────────────────────────────────────────
OUTPUT CONTRACT:
─────────────────────────────────────────────────────
Return a JSON array of Requirement objects ONLY. No prose, no markdown fences.
CRITICAL: req_type MUST be exactly "non_functional" (underscore, NO hyphen).
CRITICAL: Every item MUST include source_elicitation_id ("EL-NNN").
CRITICAL: Every NFR MUST have at least 1 acceptance_criteria bullet with a
          measurable condition. Empty [] on an NFR is an extraction failure.
CRITICAL: Every CON and OOS rationale MUST contain at least one stakeholder quote
          or paraphrase. A rationale of "." or a single generic sentence is a failure.

{field_guidance}
"""

_PASS2_USER = """\
PROJECT DESCRIPTION:
{project_description}

ELICITATION RECORD ({item_count} items):
{elicitation_json}

EXTRACTION CHECKLIST — work through these before writing output:

1. NFR IDENTITY TEST: For each candidate NFR, confirm it passes both questions:
   (Q1) It does NOT restate a behaviour already in Pass 1.
   (Q2) It includes a measurable threshold or named standard.
   If it fails either test → reclassify or discard.

2. QUALITY DIMENSIONS COVERAGE: Confirm you have scanned for evidence of:
   performance | availability | accessibility | privacy/data | content integrity |
   visual/brand | usability threshold
   Generate at least one NFR per dimension where the elicitation provides evidence.

3. [follow-up] blocks: Confirm every negative constraint phrase (avoid, not flashy,
   not too many meetings, etc.) produced a CON with SHALL NOT.

4. CON and OOS rationale: Confirm every rationale cites stakeholder words
   (not a generic justification). "." or single-sentence generic rationale = fail.

Extract all NFR, CON, and OOS requirements. Return a JSON array.
"""

# ── Pass 3: Coverage Check ────────────────────────────────────────────────────
_PASS3_SYSTEM = """\
You are a senior Requirements Engineer performing Pass 3 of a 4-pass SRS
synthesis pipeline.

YOUR ONLY JOB THIS PASS: perform a gap analysis — identify bullets in the Project
Description that are NOT adequately covered by the requirements from Passes 1 and 2,
then generate gap-filling requirements for those bullets only.

─────────────────────────────────────────────────────
GAP DETECTION PROCEDURE — for every bullet in "Initial Requirements"
and "Evaluation Criteria" sections:
─────────────────────────────────────────────────────
  Step 1 — State the INTENT of the bullet in one sentence:
            "This bullet requires that [stakeholder] can [action] resulting in [outcome]."
  Step 2 — Search ALREADY EXTRACTED for any requirement whose statement addresses
            the same stakeholder + action + outcome combination.
  Step 3 — THREE-WAY decision:

    • FULLY COVERED   → An existing requirement has a specific stakeholder, trigger,
                        and measurable outcome matching this bullet's intent.
                        Do NOT generate a new requirement. Move to next bullet.

    • PARTIALLY COVERED → A requirement exists for this topic, BUT its statement is
                          too generic — it lacks a specific actor, specific trigger,
                          or measurable outcome. A broad FR like "The system SHALL
                          display content on the website" does NOT fully cover a bullet
                          that specifically requires teacher-customisable module ordering,
                          a search bar, or a citation display format.
                          → Generate a MORE SPECIFIC complement requirement.
                          Set status="inferred", source_elicitation_id="PD".

    • NOT COVERED     → No existing requirement addresses this intent at all.
                        → Generate a new gap-filling Requirement.

  INTENT MATCH — a bullet is FULLY COVERED only when an existing requirement has:
    (a) the same specific stakeholder role — "Students" does NOT cover a teacher or
        admin bullet, even if teachers benefit from the same feature, AND
    (b) the same trigger or entry condition, AND
    (c) the same resulting system behaviour or output with a measurable outcome.

  GENERIC IS NOT ENOUGH: A broad requirement that covers a topic area is NOT
    full coverage for bullets that mention: secondary stakeholder roles, specific
    UI features (search, filters), content workflows (review, approval, citation),
    visual standards (colour, brand), or progressive disclosure patterns.

─────────────────────────────────────────────────────
MANDATORY DIMENSION SWEEP — run AFTER per-bullet analysis:
─────────────────────────────────────────────────────
After checking every bullet, verify coverage across these six dimensions.
If ANY dimension has zero requirements in ALREADY EXTRACTED, generate at least
one gap-filling requirement from the project description evidence for that dimension:

  [A] SECONDARY STAKEHOLDER ACTIONS — behaviours specific to teachers, admins,
      or other non-primary-user roles. Check: does any FR have a non-student stakeholder?

  [B] SEARCH / NAVIGATION AIDS — any mention of search, filter, or browse
      by category in the project description or elicitation.

  [C] CONTENT REVIEW / APPROVAL WORKFLOW — any mention of content accuracy,
      citation, review process, or source validation.

  [D] VISUAL / BRAND STANDARD — any mention of colour scheme, theme, or
      visual identity. If an evaluation criterion mentions a colour (e.g. green
      theme), generate a FR with a measurable threshold
      (e.g. "primary palette SHALL use #2E7D32 or equivalent").

  [E] PROGRESSIVE CONTENT DISCLOSURE — any mention of layered information,
      "key info first", "more detail on demand", or similar UX patterns.

  [F] OPERATIONAL / SYSTEM-LEVEL — availability, load handling, maintenance,
      data backup, or monitoring. Check: does any NFR address system uptime
      or concurrent-user load capacity?

─────────────────────────────────────────────────────
RULES FOR NEW GAP-FILLING REQUIREMENTS:
─────────────────────────────────────────────────────
  • source_elicitation_id = "PD"    (project description, not elicitation)
  • status = "inferred"             (not confirmed by stakeholder interview)
  • Decomposition rule applies: one bullet may yield multiple requirements
    if it describes multiple distinct behaviours or quality attributes.
  • ID numbering: continue from the next available IDs provided below.
    DO NOT reuse IDs from Passes 1 or 2.

─────────────────────────────────────────────────────
OUTPUT CONTRACT:
─────────────────────────────────────────────────────
Return a JSON array of NEW gap-filling Requirement objects only.
Return an empty array [] if there are no genuine gaps.
No prose, no commentary, no markdown fences.

{field_guidance}
"""

_PASS3_USER = """\
PROJECT DESCRIPTION:
{project_description}

ALREADY EXTRACTED ({already_count} requirements):
{already_json}

Next available IDs: FR-{next_fr:03d}, NFR-{next_nfr:03d}, CON-{next_con:03d}

STEP 1 — Per-bullet gap analysis:
For each bullet in "Initial Requirements" and "Evaluation Criteria":
  (a) State the bullet's intent: "This bullet requires that [stakeholder] can [action]
      resulting in [outcome]."
  (b) Classify: FULLY COVERED / PARTIALLY COVERED / NOT COVERED.
      A generic existing requirement (no specific stakeholder, trigger, or threshold)
      counts as PARTIALLY COVERED, not FULLY COVERED.
  (c) If PARTIALLY COVERED or NOT COVERED → generate the gap-filling Requirement.

STEP 2 — Mandatory dimension sweep:
Check dimensions [A]–[F] in the system prompt. For any dimension with zero
coverage in the extracted requirements, generate at least one gap-filling
requirement sourced from the project description.

Return only the gap-filling requirements as a JSON array ([] if truly none).
"""

# ── Pass 4: Quality Gate ──────────────────────────────────────────────────────
_PASS4_SYSTEM = """\
You are a senior Requirements Engineer performing Pass 4 (Quality Gate) of a
4-pass SRS synthesis pipeline. This is the final editorial and assembly pass.

YOUR ROLE: audit the full draft for quality violations, fix each one in-place,
then assemble and return the final SoftwareRequirementsSpecification.

─────────────────────────────────────────────────────
AUDIT WORKFLOW — process requirements in this order:
─────────────────────────────────────────────────────

STEP 0 — EPIC ASSIGNMENT CHECK
  For every requirement where the `epic` field is empty, null, or set to
  'Cross-Cutting' without justification:
    → Infer the correct Epic from the requirement's statement, context, and
      stakeholder. Assign it to the most specific matching Epic.
    → 'Cross-Cutting' is valid ONLY for system-wide policies (security, accessibility,
      compliance). Any functional requirement marked Cross-Cutting must be
      reassigned to the Epic whose primary user is most affected.

  For every requirement where `rationale` contains only a pain statement
  (no "So that" clause):
    → Infer the most plausible outcome from the statement and context.
    → Append: ". So that [role] can [observable outcome]."
    → Set status="inferred" if not already set.

STEP 1 — ATOMICITY CHECK
  For every requirement whose statement contains "and" or "or" linking two
  DISTINCT behaviours:
    → Split into two requirements. Assign the next available sequential IDs.
    → Each split child inherits the parent's stakeholder, context, rationale,
      priority, source_elicitation_id, status, and epic.
    → Accept "and" only when it is part of an inseparable threshold
      (e.g. "username AND password" in a single authentication step).

STEP 2 — TESTABILITY CHECK
  For every statement where a QA engineer would need to GUESS a threshold
  or interpretation to write a test case:
    → Rewrite to add a measurable condition or observable outcome.
    → If no numeric threshold is available from elicitation, apply the
      relevant industry standard (ISO 9241, WCAG 2.1, OWASP, etc.) and
      set status="inferred" if not already set.

STEP 3 — BANNED WORDS SWEEP
  Scan every statement AND every acceptance_criteria bullet for the following
  prohibited vocabulary. Replace each occurrence with an objective alternative.

  CATEGORY A — Vague quality adjectives:
    easy, simple, clean, intuitive, user-friendly, beautiful, elegant, modern,
    graceful, seamless, appropriate, adequate, sufficient, reasonable, proper

  CATEGORY B — Unquantified speed/frequency adverbs:
    fast, quickly, rapidly, soon, promptly, regularly, often, sometimes,
    normally, ideally, efficiently, effectively

  CATEGORY C — Non-committal modal verbs (in statements):
    should, may, can, could, might, would (replace with SHALL or SHALL NOT)

  CATEGORY D — Implicit multi-requirement conjunctions:
    "and" or "or" linking two DISTINCT behaviours (handled in Step 1 — verify
    no survivors from that step remain)

  REPLACEMENT STRATEGY:
    Adjective → measurable criterion (e.g. "intuitive" → "≤ 3 clicks to complete")
    Adverb → time/frequency threshold (e.g. "quickly" → "within 2 seconds")
    Modal → SHALL (e.g. "should store" → "SHALL store")

STEP 4 — NULL CONTEXT CHECK (functional requirements only)
  For every requirement with req_type="functional" where context is null or empty:
    → Infer the context from the statement and rationale.
    → Provide the most specific context possible
      (e.g. "On the assignment feedback page" rather than "In the system").

STEP 5 — SEMANTIC DUPLICATE DETECTION (cross-type aware)
  Two requirements are SEMANTIC DUPLICATES requiring action when:
    (a) same stakeholder role (or roles that are functionally equivalent for this
        context), AND
    (b) same trigger or entry condition, AND
    (c) same system response or output — regardless of wording differences.

  CRITICAL — CROSS-TYPE DUPLICATE RULE:
    An NFR is a semantic duplicate of an FR when its statement restates the same
    BEHAVIOUR rather than adding a measurable quality THRESHOLD. The test:
      → Does the NFR statement add a number, standard, or measurable condition
         that the FR does not have? (e.g. "SHALL meet WCAG 2.1 Level AA",
         "SHALL respond within 2 seconds under 500 concurrent users")
         If YES → keep both (the NFR is a quality attribute on top of the FR).
      → Does the NFR statement say the same thing as the FR in different words,
         with no measurable threshold and no named standard?
         If YES → REMOVE the NFR. It is not a non-functional requirement; it is
         a behaviour that belongs in Pass 1. Retaining it inflates fake diversity.

  THESE ARE NOT DUPLICATES — do not merge:
    • Requirements with the same topic but different stakeholder roles.
    • A positive FR ("SHALL display X") paired with a negative CON ("SHALL NOT…").
    • Requirements that differ by trigger even when the outcome sounds similar.
    • Requirements that address the same subject area but different quality dimensions
      (e.g. colour vs. layout vs. typography → distinct items).

  Action when a genuine duplicate IS confirmed:
    Keep the MORE SPECIFIC or MORE TESTABLE statement and remove the other.
    When uncertain, retain both and append to each rationale:
    "Retained: distinct [attribute/role/trigger] — reviewed against [REQ-ID]."

STEP 6 — OOS AND CON RATIONALE GUARD
  For every requirement with req_type="out_of_scope" or req_type="constraint":
    → Inspect the rationale field.
    → FAIL conditions (any one is sufficient):
        (a) rationale is null, empty, or a single punctuation character (e.g. ".").
        (b) rationale is a generic phrase with no stakeholder attribution
            (e.g. "To meet project goals", "For better user experience",
            "Adheres to best practices").
        (c) rationale lacks a "So that" clause.
    → Fix action: rewrite using the PAIN + OUTCOME format from the field guidance,
      citing the nearest elicitation item or project description bullet.
      If no evidence exists, write: "Scope boundary confirmed by project
      description. So that the team can maintain delivery focus within the
      agreed timeline."
      Set status="inferred".

─────────────────────────────────────────────────────
FINAL ASSEMBLY:
─────────────────────────────────────────────────────
After all audit steps:
  ORDER:  functional → non_functional → constraint → out_of_scope
  Within each group: high → medium → low
  Renumber ALL IDs sequentially with no gaps:
    FR-001, FR-002, … then NFR-001, NFR-002, … then CON-001, … then OOS-001, …
  Preserve every field — especially source_elicitation_id, status, and epic.
  Copy session_id, project_description, synthesised_at verbatim from METADATA.

─────────────────────────────────────────────────────
OUTPUT CONTRACT:
─────────────────────────────────────────────────────
Return a single JSON object conforming to SoftwareRequirementsSpecification.
CRITICAL SCHEMA RULES:
  - EVERY requirement MUST include source_elicitation_id. Do not drop this field.
  - EVERY requirement MUST include epic. Do not drop this field.
  - req_type values MUST be exactly: "functional", "non_functional", "constraint",
    or "out_of_scope" (underscores, no hyphens, no spaces).
No prose outside schema fields. No markdown fences.
"""

_PASS4_USER = """\
METADATA:
  session_id:          {session_id}
  project_description: {project_description}
  synthesised_at:      {synthesised_at}

FULL DRAFT ({total_count} requirements from Passes 1–3):
{draft_json}

Run the 6-step audit in order:
  Step 0 — Epic assignment + missing "So that" rationale clauses.
  Step 1 — Atomicity: split any statement with two distinct behaviours joined by "and"/"or".
  Step 2 — Testability: rewrite vague statements with measurable thresholds or standards.
  Step 3 — Banned words sweep (Category A–D). Replace ALL occurrences in statements
            AND acceptance_criteria.
  Step 4 — Null context check: every functional requirement must have a non-null context.
  Step 5 — Semantic duplicate detection (cross-type): remove NFRs that merely restate
            an FR without adding a measurable threshold or named standard.
  Step 6 — OOS and CON rationale guard: rewrite any rationale that is null, generic,
            or missing a "So that" outcome clause.

Fix all violations in-place, then return the final SoftwareRequirementsSpecification
JSON object.
"""


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
                "    True  → the answer contains a GENUINE TENSION worth probing at\n"
                "            Stage 3 (Pull-Up). At least two competing requirement\n"
                "            dimensions are present (e.g. openness ↔ security,\n"
                "            flexibility ↔ control). Do NOT set True just because\n"
                "            the answer is long or mentions many topics.\n"
                "    False → the answer is sufficient. Advance to the next item.\n\n"
                "  follow_up_reasoning (str, REQUIRED when needs_follow_up=True):\n"
                "    ONE sentence naming the specific tension: e.g.\n"
                "    'Answer mentions strict access control (security) but also\n"
                "     shared campus devices (usability) — classic openness↔security\n"
                "     tension worth a Stage 3 question.'\n"
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
                "elicitation_goal. Always the LAST tool call in a turn. "
                "Also used for follow-up questions when _agenda_needs_followup=True — "
                "in that case narrow into ONE specific concern from the prior answer.\n\n"
                "MANDATORY: When transitioning from a previous answer (any turn where "
                "record_answer was just called), you MUST include a brief acknowledgment "
                "sentence BEFORE the question. The acknowledgment must:\n"
                "  • Reference a specific element from the stakeholder's last answer.\n"
                "  • Be 1 sentence only — no padding, no generic praise.\n"
                "  • Use plain language — no technical terms.\n"
                "  BAD:  'Thank you for sharing.' / 'Great, let's move on.'\n"
                "  GOOD: 'Understood — the risk of students misusing AI tools without "
                "realising it is a key concern.'\n"
                "If this is the very FIRST question (no prior answer yet), omit the "
                "acknowledgment and go straight to the question.\n\n"
                'Input: {"question": "<the actual question to ask, DO NOT include the acknowledgment here>", '
                '"acknowledgment": "<one-sentence echo of the prior answer, or empty string>"}'
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
        self.register_tool(Tool(
            name="synthesise_requirements",
            description=(
                "INTERNAL — do NOT call this tool from ReAct. "
                "It is invoked automatically by process() after conclude() fires. "
                "Runs the 4-pass SRS synthesis pipeline: FR extraction, "
                "NFR/CON/OOS extraction, coverage check, and quality gate."
            ),
            func=self._tool_synthesise_requirements,
        ))

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

        Follow-up decision is fully delegated to the LLM:
          needs_follow_up=True  → the LLM detected a genuine Stage 3 tension.
                                   Store answer, set followup_asked=True, raise
                                   _agenda_needs_followup=True WITHOUT advancing.
          needs_follow_up=False → normal path: mark answered and advance.

        Follow-up append branch (second call after follow-up question):
          Recognised when followup_asked=True AND followup_answer is None.
          Appends the follow-up answer and advances normally.
        """
        answer  = (state or {}).get("enduser_answer", "")
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
        # The interviewer previously asked a follow-up question (followup_asked=True).
        # This call is arriving with the stakeholder's follow-up answer.
        if item.followup_asked and item.followup_answer is None:
            item.followup_answer = answer or "(no follow-up answer provided)"
            item.answer_received = (
                f"{item.answer_received or ''}\n[follow-up] {item.followup_answer}"
            ).strip()
            item.status = "answered"
            runtime.advance()
            logger.info(
                "[InterviewerAgent] Follow-up answer merged for '%s'. "
                "Next index: %d. Complete: %s",
                item.item_id,
                runtime.current_index,
                runtime.elicitation_complete,
            )
            return ToolResult(
                observation=(
                    f"Follow-up answer merged for '{item.item_id}'. "
                    f"Agenda complete: {runtime.elicitation_complete}. "
                    "Advancing to next item."
                ),
                state_updates={
                    "elicitation_agenda":      runtime.model_dump(),
                    "enduser_answer":          "",
                    "_agenda_needs_question":  True,
                    "_agenda_needs_followup":  False,
                },
                should_return=True,
            )

        # ── Initial answer ────────────────────────────────────────────────────
        item.answer_received = answer or "(no answer provided)"

        # ── Follow-up branch — LLM decided a Stage 3 question is warranted ───
        if needs_follow_up and not item.followup_asked:
            item.followup_asked = True
            logger.info(
                "[InterviewerAgent] LLM requested follow-up for '%s': %s",
                item.item_id,
                follow_up_reasoning or "(no reasoning provided)",
            )
            return ToolResult(
                observation=(
                    f"Answer recorded for '{item.item_id}'. "
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

        # ── Normal path — advance ─────────────────────────────────────────────
        item.status = "answered"
        runtime.advance()
        logger.info(
            "[InterviewerAgent] Recorded answer for '%s'. Next index: %d. Complete: %s",
            item.item_id,
            runtime.current_index,
            runtime.elicitation_complete,
        )
        return ToolResult(
            observation=(
                f"Answer recorded for '{item.item_id}'. "
                f"Agenda complete: {runtime.elicitation_complete}. "
                "Returning now — next turn will ask the new current item."
            ),
            state_updates={
                "elicitation_agenda":     runtime.model_dump(),
                "enduser_answer":         "",
                "current_question":       "",
                "_agenda_needs_question": True,
                "_agenda_needs_followup": False,
            },
            should_return=True,
        )

    def _tool_ask_question(
        self,
        question:        str,
        acknowledgment:  str = "",
        state:           Dict[str, Any] = None,
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
                    requirements.append({
                        "id":           f"EL-{idx + 1:03d}",
                        "source_field": item.source_field,
                        "source_ref":   item.source_ref,
                        "question":     item.question_asked or "",
                        "answer":       item.answer_received,
                        "priority":     item.priority,
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
            Enforces aggressive decomposition: one rich answer → 3-6 FR items.

        Pass 2 — NFR & CON Extraction:
            Extract Non-Functional Requirements, Constraints, and Out-of-Scope
            items from elicitation Q&A.

        Pass 3 — Coverage Check:
            Compare passes 1+2 against the project description.
            Generate gap-filling requirements (source="PD") for any bullet
            in Initial Requirements or Evaluation Criteria not yet covered.

        Pass 4 — Quality Gate:
            Audit all draft requirements for atomicity, testability, banned
            words, cross-type duplicate detection, and OOS/CON rationale guard
            (6-step pipeline). Assemble and return the final Requirement List object.

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

        # Build Epic context header for all synthesis passes
        vision_data    = state.get("product_vision") or {}
        core_workflows = vision_data.get("core_workflows") or []
        epic_context   = (
            "AVAILABLE EPICS (assign every requirement to exactly one):\n"
            + "\n".join(f"  - {e}" for e in core_workflows)
            if core_workflows
            else ""
        )

        elicitation_json = json.dumps(raw_requirements, indent=2, ensure_ascii=False)
        field_guidance   = (epic_context + "\n\n" + _FIELD_GUIDANCE).strip()

        try:
            # ── Pass 1: Functional Requirements ───────────────────────────────
            logger.info("[InterviewerAgent] Requirement List synthesis — Pass 1: FR extraction.")
            pass1_reqs: List[Dict[str, Any]] = self._run_structured_pass(
                system_prompt=_PASS1_SYSTEM.format(field_guidance=field_guidance) + feedback_block,
                user_prompt=_PASS1_USER.format(
                    project_description=project_desc,
                    item_count=len(raw_requirements),
                    elicitation_json=elicitation_json,
                ),
            )
            logger.info(
                "[InterviewerAgent] Pass 1 complete — %d FR(s) extracted.", len(pass1_reqs)
            )

            # ── Pass 2: NFR, CON, OOS ─────────────────────────────────────────
            logger.info("[InterviewerAgent] Requirement List synthesis — Pass 2: NFR/CON/OOS extraction.")
            pass2_reqs: List[Dict[str, Any]] = self._run_structured_pass(
                system_prompt=_PASS2_SYSTEM.format(field_guidance=field_guidance) + feedback_block,
                user_prompt=_PASS2_USER.format(
                    project_description=project_desc,
                    item_count=len(raw_requirements),
                    elicitation_json=elicitation_json,
                ),
            )
            logger.info(
                "[InterviewerAgent] Pass 2 complete — %d NFR/CON/OOS extracted.", len(pass2_reqs)
            )

            # ── Pass 3: Coverage Check ────────────────────────────────────────
            logger.info("[InterviewerAgent] Requirement List synthesis — Pass 3: coverage check.")
            all_so_far  = pass1_reqs + pass2_reqs
            next_fr     = self._next_id_counter(all_so_far, "FR")
            next_nfr    = self._next_id_counter(all_so_far, "NFR")
            next_con    = self._next_id_counter(all_so_far, "CON")

            pass3_reqs: List[Dict[str, Any]] = self._run_structured_pass(
                system_prompt=_PASS3_SYSTEM.format(field_guidance=field_guidance) + feedback_block,
                user_prompt=_PASS3_USER.format(
                    project_description=project_desc,
                    already_count=len(all_so_far),
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

            # ── Pass 4: Quality Gate + Final Assembly ─────────────────────────
            logger.info("[InterviewerAgent] Requirement List synthesis — Pass 4: quality gate.")
            full_draft = all_so_far + pass3_reqs

            srs: SoftwareRequirementsSpecification = self.extract_structured(
                schema=SoftwareRequirementsSpecification,
                system_prompt=_PASS4_SYSTEM + feedback_block,
                user_prompt=_PASS4_USER.format(
                    session_id=session_id,
                    project_description=project_desc,
                    synthesised_at=synthesised_at,
                    total_count=len(full_draft),
                    draft_json=json.dumps(full_draft, indent=2, ensure_ascii=False),
                ),
                include_memory=False,
            )

            # Stamp metadata fields the LLM cannot reliably fill
            rl_dict                         = srs.model_dump()
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
        """
        result: RequirementList = self.extract_structured(
            schema=RequirementList,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            include_memory=False,
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
        core_workflows_list = "\n".join(
            f"  {i+1}. {epic}" for i, epic in enumerate(vision.core_workflows)
        ) if vision.core_workflows else "  (none defined)"
        user_prompt = _AGENDA_EXTRACTION_USER.format(
            vision_json=json.dumps(vision.model_dump(), indent=2),
            core_workflows_list=core_workflows_list,
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
                    len(vision.hard_constraints),
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
                # Strip HITL-gate sentinel fields before deserialising.
                raw_vision = artifacts["reviewed_product_vision"]
                vision_fields = {
                    k: v for k, v in raw_vision.items()
                    if k not in ("status", "reviewed_at", "review_notes", "created_at")
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

    def _build_task(self, state: Dict[str, Any]) -> str:
        """Inject ONLY the current agenda item + minimal Vision context.

        Fix 3 — when _agenda_needs_followup=True, injects a FOLLOW-UP CONTEXT
        block so the interviewer knows to narrow into one specific concern from
        the prior answer instead of moving to the next item.
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

        if needs_followup and item.answer_received:
            # Stage 3 follow-up — tension-balancing (W-Framework Pull-Up)
            sections += [
                "",
                "FOLLOW-UP CONTEXT (W-Framework Stage 3 — Pull-Up / Tension Balancing):",
                f"  Previous answer for this item:",
                f"  \"{item.answer_received}\"",
                "",
                "  INNER MONOLOGUE REMINDER before composing your follow-up:",
                "    [1] Which concern in this answer is the most critical?",
                "    [2] Which requirement dimension does it CONFLICT with?",
                "         (usability↔security | speed↔accuracy | openness↔privacy |",
                "          automation↔control | cost↔quality | flexibility↔simplicity)",
                "    [3] Frame ONE question asking how the stakeholder wants to BALANCE",
                "         that specific tension — NOT asking for more detail on the same topic.",
                "",
                "  → Call ask_question ONLY with this Stage 3 tension-balancing question.",
                "  → Plain language — no technical jargon.",
                "  → ≤ 2 sentences.",
                "  → Example: answer mentions 'strict security' → ask how that balances",
                "    with a student needing access from a shared campus device.",
                "  → Do NOT advance to the next agenda item.",
            ]
        elif enduser_answer:
            sections += [
                "",
                f"ENDUSER ANSWER (waiting to be recorded): {enduser_answer}",
                "→ Call record_answer first. Do not call ask_question now.",
            ]
        else:
            # Inject W-Framework stage hint for first question
            stage_hint = _w_framework_stage_hint(item.source_field, item.priority)
            sections += [
                "",
                f"QUESTION STRATEGY — {stage_hint}",
                "→ Call ask_question to address the current item.",
                "→ Plain language only. ≤ 2 sentences. No jargon.",
            ]

        if vision:
            sections += [
                "",
                "VISION CONTEXT:",
                f"  Core Problem:      {vision.get('core_problem', '—')}",
                f"  Value Proposition: {vision.get('value_proposition', '—')}",
            ]

        return "\n".join(sections)