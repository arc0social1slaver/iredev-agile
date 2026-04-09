"""
run_iReDev.py – End-to-end demo runner for iReDev.

Sprint Zero flow (6 steps):
  Step 1  interviewer_turn ↔ enduser_turn  → interview_record
  Step 2  review_turn                      → reviewed_interview_record      [interrupt]
  Step 3  sprint_agent_turn (Pipeline A)   → product_backlog
  Step 4  review_product_backlog_turn      → reviewed_product_backlog       [interrupt]
  Step 5  sprint_feedback_turn             → (inputs) → sprint_agent_turn   [interrupt]
          sprint_agent_turn (Pipeline B)   → sprint_backlog_N
  Step 6  review_sprint_backlog_turn       → reviewed_sprint_backlog_N      [interrupt]

Review/replan loops:
  Step 2: Rejected → interview restarts (InterviewerAgent re-interviews).
  Step 4: Rejected → SprintAgent rebuilds product backlog (Pipeline A).
  Step 5: plan_another=True → loop back for next sprint.
  Step 6: Rejected → SprintAgent replans sprint (Pipeline B replan).
          Approved + plan_another=True → loop to step 5 for next sprint.
          Approved + plan_another=False → workflow ends.

Usage
─────
  python run_iReDev.py
  python run_iReDev.py --max-turns 15
  python run_iReDev.py --project "Custom project brief..."
  python run_iReDev.py --db checkpoints.db
"""

import argparse
import logging
import textwrap
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from src.orchestrator import build_graph

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="iReDev demo runner")
    p.add_argument("--max-turns", type=int, default=20,
                   help="Safety-net max interview turns (default: 20).")
    p.add_argument("--project", type=str, default=None,
                   help="Override project description.")
    p.add_argument("--db", type=str, default="checkpoints.db",
                   help="Path to SQLite checkpoint DB (default: checkpoints.db).")
    return p.parse_args()


# ── Display helpers ───────────────────────────────────────────────────────────

_SEP  = "═" * 70
_SEP2 = "─" * 70


def _section(title: str) -> None:
    print(f"\n{_SEP}\n  {title}\n{_SEP}")


def _sub(title: str) -> None:
    print(f"\n{_SEP2}\n  {title}\n{_SEP2}")


def _wrap(text: str, indent: int = 4) -> str:
    return textwrap.fill(
        str(text), width=80,
        initial_indent=" " * indent,
        subsequent_indent=" " * indent,
    )


def _status_icon(status: str) -> str:
    return {"confirmed": "✓", "inferred": "~", "ambiguous": "?"}.get(status, "·")


# ── Artifact display ──────────────────────────────────────────────────────────

def _display_requirements_draft(draft: list) -> None:
    if not draft:
        return
    print(f"\n  ┌─ REQUIREMENTS DRAFT ({len(draft)} items) ──────────────────────")
    for r in draft[-5:]:
        icon = _status_icon(r.get("status", ""))
        print(
            f"  │  {icon} [{r.get('id','?')}] "
            f"({r.get('type','?')}, {r.get('priority','?')}) "
            f"{r.get('description','')[:70]}"
        )
    if len(draft) > 5:
        print(f"  │  … (+{len(draft) - 5} earlier requirements)")
    print("  └────────────────────────────────────────────────────────────────")


def _display_backlog_draft(backlog: list) -> None:
    if not backlog:
        return
    print(f"\n  ┌─ BACKLOG DRAFT ({len(backlog)} items) ──────────────────────────")
    for item in backlog[-5:]:
        pts  = item.get("story_points", "?")
        wsjf = item.get("wsjf_score")
        wsjf_str = f" WSJF={wsjf:.2f}" if wsjf else ""
        print(
            f"  │  [{item.get('id','?')}] pts={pts}{wsjf_str} "
            f"status={item.get('status','?')} "
            f"{item.get('title','')[:55]}"
        )
    if len(backlog) > 5:
        print(f"  │  … (+{len(backlog) - 5} earlier items)")
    print("  └────────────────────────────────────────────────────────────────")


def _display_interview_record(record: dict) -> None:
    _section("ARTIFACT: interview_record")
    reqs = record.get("requirements_identified") or []
    gaps = record.get("gaps_identified") or []
    print(f"  Turns        : {record.get('total_turns', '?')}")
    print(f"  Completeness : {record.get('completeness_score', '?')}")
    print(f"  Requirements : {len(reqs)}")
    print(f"    Functional     : {sum(1 for r in reqs if r.get('type') == 'functional')}")
    print(f"    Non-functional : {sum(1 for r in reqs if r.get('type') == 'non_functional')}")
    print(f"    Constraints    : {sum(1 for r in reqs if r.get('type') == 'constraint')}")
    print(f"  Gaps         : {len(gaps)}")
    if record.get("notes"):
        print(f"  Notes        : {record['notes'][:160]}")
    if reqs:
        print("\n  All requirements:")
        for r in reqs:
            icon = _status_icon(r.get("status", ""))
            print(
                f"    {icon} [{r.get('id','?')}] "
                f"({r.get('type','?')}, prio={r.get('priority','?')}) "
                f"{r.get('description','')[:80]}"
            )
            rationale = r.get("rationale", "")
            if rationale and rationale not in ("(not provided)", "(rationale not provided)"):
                print(f"       ↳ {rationale[:100]}")
    if gaps:
        print("\n  Gaps:")
        for g in gaps:
            print(f"    • {g}")


def _display_product_backlog(artifact: dict, label: str = "product_backlog") -> None:
    _section(f"ARTIFACT: {label}")
    items = artifact.get("items") or []
    methodology = artifact.get("methodology") or {}
    print(f"  Total items    : {artifact.get('total_items', len(items))}")
    print(f"  Status         : {artifact.get('status', '?')}")
    print(f"  Estimation     : {methodology.get('estimation', 'N/A')}")
    print(f"  Prioritization : {methodology.get('prioritization', 'N/A')}")
    if artifact.get("reviewed_at"):
        print(f"  Reviewed at    : {artifact['reviewed_at']}")
    if artifact.get("review_notes"):
        print(f"  Review notes   : {artifact['review_notes'][:120]}")
    if items:
        print("\n  Ranked backlog:")
        for item in items[:20]:
            rank     = item.get("priority_rank", "?")
            sid      = item.get("id", "?")
            pts      = item.get("story_points", "?")
            wsjf     = item.get("wsjf_score")
            wsjf_str = f"WSJF={wsjf:.2f}" if wsjf else "WSJF=N/A"
            invest   = item.get("invest") or {}
            failed   = [k for k, v in invest.items() if not v]
            inv_str  = f" ⚠INVEST:{failed}" if failed else " ✓INVEST"
            print(
                f"    #{rank} [{sid}] {wsjf_str} pts={pts} "
                f"({item.get('type','?')}){inv_str} "
                f"{item.get('title','')[:55]}"
            )
        if len(items) > 20:
            print(f"    … (+{len(items) - 20} more)")
    if artifact.get("notes"):
        print(f"\n  Notes: {artifact['notes'][:200]}")


def _display_sprint_backlog(artifact: dict, label: str = None) -> None:
    sprint_num = artifact.get("sprint_number", "?")
    label = label or f"sprint_backlog_{sprint_num}"
    _section(f"ARTIFACT: {label}")
    items = artifact.get("items") or []
    print(f"  Sprint number   : {sprint_num}")
    print(f"  Sprint goal     : {artifact.get('sprint_goal', '(not set)')}")
    print(f"  Status          : {artifact.get('status', '?')}")
    print(f"  Capacity        : {artifact.get('capacity_points', '?')} pts")
    print(f"  Allocated       : {artifact.get('allocated_points', '?')} pts")
    print(f"  Remaining       : {artifact.get('remaining_points', '?')} pts")
    print(f"  Items selected  : {artifact.get('total_items', len(items))}")
    print(f"  Plan another    : {artifact.get('plan_another', False)}")
    if artifact.get("reviewed_at"):
        print(f"  Reviewed at     : {artifact['reviewed_at']}")
    if artifact.get("review_notes"):
        print(f"  Review notes    : {artifact['review_notes'][:120]}")
    completed = artifact.get("completed_pbi_ids") or []
    if completed:
        print(f"  Completed PBIs  : {completed}")
    if items:
        print("\n  Selected items (by priority):")
        for item in items:
            rank     = item.get("priority_rank", "?")
            sid      = item.get("id", "?")
            pts      = item.get("story_points", "?")
            wsjf     = item.get("wsjf_score")
            wsjf_str = f"WSJF={wsjf:.2f}" if wsjf else "WSJF=N/A"
            dep_on   = item.get("depends_on") or []
            dep_str  = f" deps={dep_on}" if dep_on else ""
            dtype    = item.get("dep_type", "none")
            reason   = item.get("inclusion_reason", "")[:60]
            print(
                f"    #{rank} [{sid}] {wsjf_str} pts={pts} "
                f"dep={dtype}{dep_str}\n"
                f"       {item.get('title','')[:65]}\n"
                f"       ↳ {reason}"
            )
    if artifact.get("notes"):
        print(f"\n  Notes: {artifact['notes'][:200]}")


# ── Interrupt collectors ──────────────────────────────────────────────────────

def _collect_interview_review(updates) -> dict:
    """Display the interview record and collect reviewer's decision."""
    for interrupt_obj in updates:
        payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        if not isinstance(payload, dict):
            continue

        _sub("REVIEW GATE — Interview Record")
        print(f"\n  {payload.get('review_prompt', '')}")

        proj = payload.get("project_description", "")
        if proj:
            print(f"\n  Project          : {proj[:120]}")

        score = payload.get("completeness_score")
        if score is not None:
            print(f"  Completeness     : {score}")

        turns = payload.get("total_turns")
        if turns is not None:
            print(f"  Total turns      : {turns}")

        gaps = payload.get("gaps", [])
        if gaps:
            print(f"  Gaps ({len(gaps)}):")
            for g in gaps:
                print(f"    • {g}")

        reqs = payload.get("requirements", [])
        if reqs:
            print(f"\n  Requirements ({len(reqs)}):")
            fn  = sum(1 for r in reqs if r.get("type") == "functional")
            nfn = sum(1 for r in reqs if r.get("type") == "non_functional")
            con = sum(1 for r in reqs if r.get("type") == "constraint")
            print(f"    Functional: {fn}  |  Non-functional: {nfn}  |  Constraints: {con}")
            print()
            for r in reqs:
                icon = _status_icon(r.get("status", ""))
                print(
                    f"  {icon} [{r.get('id','?')}] "
                    f"({r.get('type','?')}, prio={r.get('priority','?')}, "
                    f"{r.get('status','?')})\n"
                    f"    {r.get('description','')[:90]}"
                )
                rationale = r.get("rationale", "")
                if rationale and rationale not in ("(not provided)",):
                    print(f"    ↳ rationale: {rationale[:100]}")
                hist = r.get("history") or []
                if hist:
                    for h in hist:
                        print(f"    ↳ {h}")

    return _prompt_approve_reject("interview record")


def _collect_backlog_review(updates) -> dict:
    """Display the product backlog and collect reviewer's decision."""
    for interrupt_obj in updates:
        payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        if not isinstance(payload, dict):
            continue

        _sub("REVIEW GATE — Product Backlog")
        print(f"\n  {payload.get('review_prompt', '')}")
        print(f"\n  Total items : {payload.get('total_items', '?')}")
        print(f"  Created at  : {payload.get('created_at', '?')}")

        methodology = payload.get("methodology") or {}
        if methodology:
            print(f"  Estimation  : {methodology.get('estimation', 'N/A')}")
            print(f"  Prioritize  : {methodology.get('prioritization', 'N/A')}")

        notes = payload.get("notes", "")
        if notes:
            print(f"  Notes       : {notes[:160]}")

        items = payload.get("items") or []
        if items:
            print(f"\n  Product Backlog Items ({len(items)}):")
            print(f"  {'Rank':<5} {'ID':<10} {'WSJF':>7} {'Pts':>5} {'BV':>4} "
                  f"{'TC':>4} {'RR':>4} {'INVEST':<8}  Title")
            print(f"  {'─'*5} {'─'*10} {'─'*7} {'─'*5} {'─'*4} "
                  f"{'─'*4} {'─'*4} {'─'*8}  {'─'*40}")
            for item in items:
                rank     = item.get("priority_rank", "?")
                sid      = item.get("id", "?")
                wsjf     = item.get("wsjf_score")
                wsjf_str = f"{wsjf:.2f}" if wsjf else "N/A"
                pts      = item.get("story_points", "?")
                bv       = item.get("business_value", "?")
                tc       = item.get("time_criticality", "?")
                rr       = item.get("risk_reduction", "?")
                failed   = item.get("invest_failed") or []
                inv_str  = "FAIL:"+",".join(f[0] for f in failed) if failed else "PASS"
                title    = (item.get("title") or "")[:45]
                print(
                    f"  #{rank:<4} {sid:<10} {wsjf_str:>7} {pts:>5} {bv:>4} "
                    f"{tc:>4} {rr:>4} {inv_str:<8}  {title}"
                )
            print()
            # Show descriptions for each item
            for item in items:
                sid  = item.get("id", "?")
                desc = item.get("description", "")[:120]
                if desc:
                    print(f"  [{sid}] {desc}")

    return _prompt_approve_reject("product backlog")


def _collect_sprint_feedback(updates) -> dict:
    """Display the product backlog summary and collect sprint planning inputs."""
    payload = {}
    for interrupt_obj in updates:
        val = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        if isinstance(val, dict):
            payload = val
            break

    sprint_num = payload.get("sprint_number", 1)
    _sub(f"SPRINT PLANNING — Sprint {sprint_num}")
    print(f"\n  {payload.get('prompt', '')}")

    proj = payload.get("project_description", "")
    if proj:
        print(f"\n  Project: {proj[:120]}")

    prev_feedback = payload.get("sprint_backlog_feedback")
    if prev_feedback:
        print(f"\n  ⚠ Previous sprint backlog was REJECTED.")
        print(f"  Feedback: {prev_feedback[:200]}")

    completed_sprints = payload.get("completed_sprints") or []
    if completed_sprints:
        print(f"\n  Already approved sprints: {completed_sprints}")

    backlog_lines = payload.get("product_backlog_summary") or []
    if backlog_lines:
        print(f"\n  Product Backlog ({len(backlog_lines)} items):")
        for line in backlog_lines:
            print(f"    {line}")

    print(f"\n{'─'*70}")
    print(f"  SPRINT {sprint_num} PLANNING INPUTS")
    print(f"{'─'*70}")

    sprint_goal = input(f"\n  Sprint {sprint_num} goal: ").strip()
    if not sprint_goal:
        sprint_goal = f"Sprint {sprint_num} — deliver highest-priority backlog items"

    while True:
        cap_str = input(f"  Capacity (story points) [default 20]: ").strip()
        if not cap_str:
            capacity = 20
            break
        try:
            capacity = int(cap_str)
            break
        except ValueError:
            print("  Please enter an integer.")

    completed_str = input(
        "  Completed PBI IDs (comma-separated, or Enter for none): "
    ).strip()
    completed_ids = [c.strip() for c in completed_str.split(",") if c.strip()]

    plan_another_str = input("  Plan another sprint after this one? [y/n, default n]: ").strip().lower()
    plan_another     = plan_another_str == "y"

    notes = input("  Optional notes for the SprintAgent (Enter to skip): ").strip()

    print(f"\n  ✓ Sprint {sprint_num} inputs collected:")
    print(f"    Goal      : {sprint_goal}")
    print(f"    Capacity  : {capacity} pts")
    print(f"    Completed : {completed_ids or '(none)'}")
    print(f"    Another   : {plan_another}")
    if notes:
        print(f"    Notes     : {notes}")

    return {
        "sprint_goal":       sprint_goal,
        "capacity_points":   capacity,
        "completed_pbi_ids": completed_ids,
        "plan_another":      plan_another,
        "notes":             notes,
    }


def _collect_sprint_review(updates) -> dict:
    """Display the sprint backlog and collect reviewer's decision."""
    for interrupt_obj in updates:
        payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        if not isinstance(payload, dict):
            continue

        sprint_num = payload.get("sprint_number", "?")
        _sub(f"REVIEW GATE — Sprint {sprint_num} Backlog")
        print(f"\n  {payload.get('review_prompt', '')}")

        print(f"\n  Sprint number   : {sprint_num}")
        print(f"  Sprint goal     : {payload.get('sprint_goal', '(not set)')}")
        print(f"  Capacity        : {payload.get('capacity_points', '?')} pts")
        print(f"  Allocated       : {payload.get('allocated_points', '?')} pts")
        print(f"  Remaining       : {payload.get('remaining_points', '?')} pts")
        print(f"  Items selected  : {payload.get('total_items', '?')}")
        print(f"  Plan another    : {payload.get('plan_another', False)}")

        notes = payload.get("notes", "")
        if notes:
            print(f"  Notes           : {notes[:160]}")

        items = payload.get("items") or []
        if items:
            print(f"\n  Selected PBIs ({len(items)}):")
            print(f"  {'Rank':<5} {'ID':<10} {'WSJF':>7} {'Pts':>5} {'Dep':>6}  Title")
            print(f"  {'─'*5} {'─'*10} {'─'*7} {'─'*5} {'─'*6}  {'─'*45}")
            for item in items:
                rank     = item.get("priority_rank", "?")
                sid      = item.get("id", "?")
                wsjf     = item.get("wsjf_score")
                wsjf_str = f"{wsjf:.2f}" if wsjf else "N/A"
                pts      = item.get("story_points", "?")
                dtype    = item.get("dep_type", "none")[:6]
                dep_on   = item.get("depends_on") or []
                dep_str  = f"({','.join(dep_on)})" if dep_on else ""
                title    = (item.get("title") or "")[:45]
                print(
                    f"  #{rank:<4} {sid:<10} {wsjf_str:>7} {pts:>5} {dtype:>6}  {title}"
                )
                if dep_str:
                    print(f"          deps: {dep_str}")
                reason = item.get("inclusion_reason", "")[:100]
                if reason:
                    print(f"          ↳ {reason}")
            print()
            # Show descriptions
            for item in items:
                desc = item.get("description", "")[:120]
                if desc:
                    print(f"  [{item.get('id','?')}] {desc}")

    return _prompt_approve_reject(f"sprint backlog")


def _prompt_approve_reject(subject: str) -> dict:
    """Generic approve/reject prompt."""
    print(f"\n{'─'*70}")
    print(f"  REVIEW DECISION — {subject.upper()}")
    print(f"{'─'*70}")

    while True:
        choice = input(f"\n  Approve {subject}? [y/n]: ").strip().lower()
        if choice in ("y", "n"):
            break
        print("  Please enter y or n.")

    if choice == "y":
        notes = input("  Optional approval notes (Enter to skip): ").strip()
        return {"approved": True, "feedback": notes or None}
    else:
        print(f"\n  Please provide feedback (blank line to finish):")
        lines = []
        while True:
            line = input("  > ")
            if not line:
                break
            lines.append(line)
        feedback = " ".join(lines).strip() or "No specific feedback provided."
        return {"approved": False, "feedback": feedback}


# ── Node step display ─────────────────────────────────────────────────────────

def _handle_step(node_name: str, updates) -> None:
    if not updates:
        return
    if not isinstance(updates, dict):
        print(f"\n  (unexpected update type: {type(updates).__name__})")
        return

    print(f"\n{_SEP2}")
    print(f"  NODE: {node_name.upper()}")
    print(f"{_SEP2}")

    # ── Interview conversation ─────────────────────────────────────────────
    conversation = updates.get("conversation")
    if conversation:
        last  = conversation[-1]
        label = "INTERVIEWER" if last.get("role") == "interviewer" else "STAKEHOLDER"
        print(f"\n  [{label}]")
        print(_wrap(last.get("content", "")))

    # ── Requirements draft ────────────────────────────────────────────────
    draft = updates.get("requirements_draft")
    if draft is not None:
        _display_requirements_draft(draft)

    # ── Interview complete flag ───────────────────────────────────────────
    if updates.get("interview_complete"):
        print("\n  ✓ interview_complete = True")

    # ── Backlog draft ─────────────────────────────────────────────────────
    backlog_draft = updates.get("backlog_draft")
    if backlog_draft is not None:
        _display_backlog_draft(backlog_draft)

    # ── Routing signal ────────────────────────────────────────────────────
    next_node = updates.get("next_node")
    if next_node:
        dest = "END" if next_node == "__end__" else next_node
        print(f"\n  → routing to: {dest}")

    # ── Artifacts ─────────────────────────────────────────────────────────
    artifacts = updates.get("artifacts") or {}
    for name, content in artifacts.items():
        if name.startswith("_"):
            continue  # skip internal sentinels
        if name == "interview_record":
            _display_interview_record(content)
        elif name in ("product_backlog", "reviewed_product_backlog"):
            _display_product_backlog(content, label=name)
        elif name.startswith("sprint_backlog_") or name.startswith("reviewed_sprint_backlog_"):
            _display_sprint_backlog(content, label=name)
        else:
            print(f"\n  Artifact produced: {name}")

    # ── Sprint feedback collection result ─────────────────────────────────
    sprint_feedback = updates.get("sprint_feedback")
    if sprint_feedback:
        print(f"\n  Sprint feedback recorded:")
        print(f"    Goal     : {sprint_feedback.get('sprint_goal','?')}")
        print(f"    Capacity : {sprint_feedback.get('capacity_points','?')} pts")
        print(f"    Completed: {sprint_feedback.get('completed_pbi_ids') or '(none)'}")
        print(f"    Another  : {sprint_feedback.get('plan_another', False)}")

    # ── Sprint number ─────────────────────────────────────────────────────
    sprint_num = updates.get("current_sprint_number")
    if sprint_num:
        print(f"\n  Current sprint number: {sprint_num}")

    # ── Review flags ──────────────────────────────────────────────────────
    for flag, label in [
        ("review_approved",                 "Interview review"),
        ("product_backlog_review_approved", "Product backlog review"),
        ("sprint_backlog_review_approved",  "Sprint backlog review"),
    ]:
        val = updates.get(flag)
        if val is not None:
            icon = "✓ APPROVED" if val else "✗ REJECTED"
            print(f"\n  {label}: {icon}")

    # ── Phase ─────────────────────────────────────────────────────────────
    phase = updates.get("system_phase")
    if phase:
        print(f"\n  Phase: {phase}")


# ── Interrupt router ──────────────────────────────────────────────────────────

# Maps the node that triggered the interrupt to the appropriate handler.
# Determined by inspecting the last non-supervisor node name in the stream.
_INTERRUPT_NODE_CONTEXT: str = ""


def _route_interrupt(updates, node_context: str) -> dict:
    """
    Route an interrupt to the correct handler based on which node is waiting.
    node_context is the last non-supervisor, non-interrupt node name seen.
    """
    if node_context == "review_turn":
        return _collect_interview_review(updates)
    elif node_context == "review_product_backlog_turn":
        return _collect_backlog_review(updates)
    elif node_context == "sprint_feedback_turn":
        return _collect_sprint_feedback(updates)
    elif node_context == "review_sprint_backlog_turn":
        return _collect_sprint_review(updates)
    else:
        # Fallback: try to determine from payload content
        for interrupt_obj in updates:
            payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
            if isinstance(payload, dict):
                if "requirements" in payload:
                    return _collect_interview_review(updates)
                elif "sprint_number" in payload and "items" in payload and "sprint_goal" in payload:
                    return _collect_sprint_review([interrupt_obj])
                elif "items" in payload and "methodology" in payload:
                    return _collect_backlog_review([interrupt_obj])
                elif "sprint_number" in payload and "product_backlog_summary" in payload:
                    return _collect_sprint_feedback([interrupt_obj])
        # Last resort
        print("\n  Unknown interrupt — defaulting to approve.")
        return {"approved": True}


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = _parse_args()

    default_project = (
        "We need a course-registration system for university students. "
        "Students should be able to browse available courses, register for "
        "up to 5 courses per semester, view their schedule, and receive "
        "notifications about enrollment deadlines."
    )
    project = args.project or default_project

    config = {"configurable": {"thread_id": "demo_session_1"}}

    with SqliteSaver.from_conn_string(args.db) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)

        initial_state = {
            "session_id":            "demo_session_1",
            "project_description":   project,
            "system_phase":          "sprint_zero_planning",
            "artifacts":             {},
            "conversation":          [],
            "turn_count":            0,
            "max_turns":             args.max_turns,
            "interview_complete":    False,
            "requirements_draft":    [],
            "backlog_draft":         [],
            "sprint_draft":          [],
            "current_sprint_number": 1,
            "sprint_feedback":       None,
            "errors":                [],
        }

        _section("iReDev — Sprint Zero Planning")
        print(f"  Project    : {project[:100]}{'…' if len(project) > 100 else ''}")
        print(f"  max_turns  : {args.max_turns}")
        print(f"  DB         : {args.db}")
        print()
        print("  Sprint Zero flow:")
        print("    Step 1  Requirements Interview (AI agents)")
        print("    Step 2  Review Interview Record         [you review]")
        print("    Step 3  Build Product Backlog (AI)")
        print("    Step 4  Review Product Backlog          [you review]")
        print("    Step 5  Sprint Planning inputs          [you provide]")
        print("            Plan Sprint Backlog (AI)")
        print("    Step 6  Review Sprint Backlog           [you review]")

        stream_input   = initial_state
        last_node_name = ""  # track for interrupt routing

        while True:
            interrupted = False

            for step_output in graph.stream(stream_input, config=config):
                for node_name, updates in step_output.items():

                    if node_name == "__interrupt__":
                        print(f"\n{_SEP2}")
                        print(f"  NODE: __INTERRUPT__ (triggered by: {last_node_name})")
                        print(f"{_SEP2}")

                        decision = _route_interrupt(updates, last_node_name)

                        if decision.get("approved"):
                            _section(f"✓ APPROVED — {last_node_name}")
                            if decision.get("feedback"):
                                print(f"  Notes: {decision['feedback']}")
                        else:
                            _section(f"✗ REJECTED / INPUT COLLECTED — {last_node_name}")
                            fb = decision.get("feedback") or decision.get("sprint_goal", "")
                            if fb:
                                print(f"  Feedback / Input: {str(fb)[:120]}")

                        # Resume the graph
                        for resume_output in graph.stream(
                            Command(resume=decision), config=config
                        ):
                            for rnode, rupdates in resume_output.items():
                                if rnode != "__interrupt__":
                                    _handle_step(rnode, rupdates)
                                    if rnode not in ("supervisor", "__interrupt__"):
                                        last_node_name = rnode

                        interrupted = True
                        break

                    else:
                        _handle_step(node_name, updates)
                        if node_name not in ("supervisor", "__interrupt__"):
                            last_node_name = node_name

                if interrupted:
                    break

            if not interrupted:
                break

            stream_input = None  # continue from checkpoint on next iteration

        _section("Workflow Complete")
        print("  Artifacts produced:")
        print("    interview_record           — validated requirements")
        print("    reviewed_interview_record  — human-approved requirements")
        print("    product_backlog            — WSJF-ranked backlog")
        print("    reviewed_product_backlog   — human-approved backlog")
        print("    sprint_backlog_N           — sprint plan(s)")
        print("    reviewed_sprint_backlog_N  — approved sprint plan(s)")
        print()