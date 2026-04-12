"""
run_iReDev.py – End-to-end demo runner for iReDev.

Sprint Zero flow:
  interviewer_turn ↔ enduser_turn   → produces: interview_record
  review_turn                        → human-in-the-loop gate (interrupt + resume)
  sprint_agent_turn                  → produces: product_backlog

Review loop:
  • Workflow pauses at review_turn via interrupt().
  • Runner prints the requirements and prompts the human reviewer in-terminal.
  • On approval   → workflow resumes, advances to sprint_agent_turn.
  • On rejection  → workflow resumes with feedback, interview restarts so the
                    InterviewerAgent can address the reviewer's comments before
                    producing a new interview_record for re-review.

Checkpointer:
  SqliteSaver persists state to checkpoints.db so interrupt/resume works
  correctly across the review loop and feedback is never lost.

Usage
─────
  python run_iReDev.py
  python run_iReDev.py --max-turns 15
  python run_iReDev.py --project "Custom project brief..."
  python run_iReDev.py --db checkpoints.db   # custom checkpoint DB path
"""

import os
import uuid
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
    p.add_argument(
        "--max-turns", type=int, default=20,
        help="Safety-net max interview turns (default: 20).",
    )
    p.add_argument(
        "--project",
        type=argparse.FileType('r', encoding='utf-8'),
        default=None,
        help="Đường dẫn tới file chứa mô tả dự án."
    )
    p.add_argument(
        "--db", type=str, default="checkpoints.db",
        help="Path to SQLite checkpoint DB (default: checkpoints.db).",
    )
    p.add_argument(
        "--reset-db",
        action="store_true",
        help="Delete checkpoint DB before running."
    )
    return p.parse_args()


# ── Display helpers ───────────────────────────────────────────────────────────

_SEP = "═" * 70


def _section(title: str) -> None:
    print(f"\n{_SEP}\n  {title}\n{_SEP}")


def _wrap(text: str, indent: int = 4) -> str:
    return textwrap.fill(
        str(text), width=80,
        initial_indent=" " * indent,
        subsequent_indent=" " * indent,
    )


def _display_draft_update(draft: list) -> None:
    if not draft:
        return
    print(f"\n  ┌─ DRAFT UPDATE ({len(draft)} requirements) ─────────────────")
    for r in draft[-5:]:
        icon = {"confirmed": "✓", "inferred": "~", "ambiguous": "?"}.get(r.get("status", ""), "·")
        print(
            f"  │  {icon} [{r.get('id','?')}] "
            f"({r.get('type','?')}, {r.get('priority','?')}) "
            f"{r.get('description','')[:70]}"
        )
    if len(draft) > 5:
        print(f"  │  … (+{len(draft) - 5} earlier requirements)")
    print("  └────────────────────────────────────────────────────────────")


def _display_interview_record(record: dict) -> None:
    _section("ARTIFACT: interview_record")
    reqs = record.get("requirements_identified") or []
    gaps = record.get("gaps_identified") or []
    print(f"  Turns        : {record.get('total_turns', '?')}")
    print(f"  Requirements : {len(reqs)}")
    print(f"    Functional    : {sum(1 for r in reqs if r.get('type') == 'functional')}")
    print(f"    Non-functional: {sum(1 for r in reqs if r.get('type') == 'non_functional')}")
    print(f"    Constraints   : {sum(1 for r in reqs if r.get('type') == 'constraint')}")
    print(f"  Gaps         : {len(gaps)}")
    print(f"  Completeness : {record.get('completeness_score', '?')}")
    print(f"  Notes        : {record.get('notes', '')[:160]}")
    if reqs:
        print("\n  All requirements:")
        for r in reqs:
            icon = {"confirmed": "✓", "inferred": "~", "ambiguous": "?"}.get(r.get("status", ""), "·")
            print(
                f"    {icon} [{r.get('id','?')}] "
                f"({r.get('type','?')}, prio={r.get('priority','?')}) "
                f"{r.get('description','')[:80]}"
            )
    if gaps:
        print("\n  Gaps:")
        for g in gaps:
            print(f"    • {g}")


def _display_product_backlog(artifact: dict) -> None:
    _section("ARTIFACT: product_backlog")
    items = artifact.get("items") or []
    split_parents = artifact.get("split_parents") or []
    methodology = artifact.get("methodology") or {}
    print(f"  Total items    : {artifact.get('total_items', len(items))}")
    print(f"  Split parents  : {len(split_parents)} (for traceability)")
    print(f"  Estimation     : {methodology.get('estimation', 'N/A')}")
    print(f"  Prioritization : {methodology.get('prioritization', 'N/A')}")
    if items:
        print("\n  Ranked backlog:")
        for item in items[:15]:
            rank = item.get('priority_rank', '?')
            wsjf = item.get('wsjf_score')
            pts = item.get('story_points', '?')
            wsjf_str = f"WSJF={wsjf:.2f}" if wsjf else "WSJF=N/A"
            print(
                f"    #{rank} [{item.get('id','?')}] "
                f"{wsjf_str} pts={pts} "
                f"({item.get('type','?')}) "
                f"{item.get('title','')[:60]}"
            )
        if len(items) > 15:
            print(f"    … (+{len(items) - 15} more)")
    print(f"  Notes: {artifact.get('notes', '')[:200]}")


# ── Interrupt: collect human review decision ──────────────────────────────────

def _collect_review_decision(updates: tuple) -> dict:
    """
    Print the review payload from interrupt() and collect the human's decision
    interactively from stdin.

    Returns a dict ready to pass to Command(resume=...):
      {"approved": True}
      {"approved": False, "feedback": "<text>"}
    """
    for interrupt_obj in updates:
        payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        if not isinstance(payload, dict):
            print(f"\n  Interrupt value: {payload}")
            continue

        print(f"\n  {payload.get('review_prompt', '')}")

        score = payload.get("completeness_score")
        if score is not None:
            print(f"\n  Completeness score : {score}")

        gaps = payload.get("gaps", [])
        if gaps:
            print("  Gaps identified    :")
            for g in gaps:
                print(f"    • {g}")

        reqs = payload.get("requirements", [])
        if reqs:
            print(f"\n  Requirements ({len(reqs)}):")
            for r in reqs:
                icon = {"confirmed": "✓", "inferred": "~", "ambiguous": "?"}.get(r.get("status", ""), "·")
                print(
                    f"    {icon} [{r.get('id','?')}] "
                    f"({r.get('type','?')}, prio={r.get('priority','?')}, {r.get('status','?')}) "
                    f"{r.get('description','')[:80]}"
                )
                rationale = r.get("rationale", "")
                if rationale and rationale != "(not provided)":
                    print(f"         rationale: {rationale[:100]}")

    # Collect decision interactively
    print(f"\n{'─'*70}")
    print("  REVIEW DECISION")
    print(f"{'─'*70}")

    while True:
        choice = input("\n  Approve requirements? [y/n]: ").strip().lower()
        if choice in ("y", "n"):
            break
        print("  Please enter y or n.")

    if choice == "y":
        notes = input("  Optional approval notes (press Enter to skip): ").strip()
        return {"approved": True, "feedback": notes or None}
    else:
        print("\n  Please provide feedback for the interviewer to address:")
        print("  (Enter feedback lines, blank line to finish)")
        feedback_lines = []
        while True:
            line = input("  > ")
            if line == "":
                break
            feedback_lines.append(line)
        feedback = " ".join(feedback_lines).strip() or "No specific feedback provided."
        return {"approved": False, "feedback": feedback}


# ── Stream handler ────────────────────────────────────────────────────────────

def _handle_step(node_name: str, updates) -> None:
    if not updates:
        return

    print(f"\n{'─'*70}")
    print(f"  NODE: {node_name.upper()}")
    print(f"{'─'*70}")

    if not isinstance(updates, dict):
        print(f"\n  (unexpected update type: {type(updates).__name__})")
        return

    conversation = updates.get("conversation")
    if conversation:
        last  = conversation[-1]
        label = "INTERVIEWER" if last.get("role") == "interviewer" else "STAKEHOLDER"
        print(f"\n  [{label}]")
        print(_wrap(last.get("content", "")))

    draft = updates.get("requirements_draft")
    if draft is not None:
        _display_draft_update(draft)

    if updates.get("interview_complete"):
        print("\n  ✓ interview_complete = True")

    backlog = updates.get("backlog_draft")
    if backlog is not None:
        print(f"\n  ┌─ BACKLOG DRAFT ({len(backlog)} items) ─────────────────────")
        for item in backlog[-5:]:
            status = item.get("status", "?")
            pts = item.get("story_points", "?")
            wsjf = item.get("wsjf_score")
            wsjf_str = f" WSJF={wsjf:.2f}" if wsjf else ""
            print(
                f"  │  [{item.get('id','?')}] pts={pts} "
                f"status={status}{wsjf_str} "
                f"{item.get('title','')[:50]}"
            )
        if len(backlog) > 5:
            print(f"  │  … (+{len(backlog) - 5} earlier items)")
        print("  └────────────────────────────────────────────────────────────")

    next_node = updates.get("next_node")
    if next_node:
        print(f"\n  → routing to: {'END' if next_node == '__end__' else next_node}")

    artifacts = updates.get("artifacts")
    if artifacts:
        for name, content in artifacts.items():
            if name == "interview_record":
                _display_interview_record(content)
            elif name == "product_backlog":
                _display_product_backlog(content)
            else:
                print(f"\n  Artifact produced: {name}")

    phase = updates.get("system_phase")
    if phase:
        print(f"\n  Phase: {phase}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = _parse_args()

    default_project = (
        "We need a course-registration system for university students. "
        "Students should be able to browse available courses, register for "
        "up to 5 courses per semester, view their schedule, and receive "
        "notifications about enrollment deadlines."
    )
    project = args.project.read() or default_project

    # thread_id scopes the checkpoint to this run.
    # Change it to resume a previous session from disk.
    if args.reset_db and os.path.exists(args.db):
        os.remove(args.db)

    config = {
        "configurable": {
            "thread_id": f"demo_{uuid.uuid4().hex}",
            "recursion_limit": 100
        }
    }

    with SqliteSaver.from_conn_string(args.db) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)

        initial_state = {
            "session_id":          "demo_session_1",
            "project_description": project,
            "system_phase":        "sprint_zero_planning",
            "artifacts":           {},
            "conversation":        [],
            "turn_count":          0,
            "max_turns":           args.max_turns,
            "interview_complete":  False,
            "requirements_draft":  [],
            "backlog_draft":       [],
            "errors":              [],
        }

        _section("iReDev — Sprint Zero Planning")
        print(f"  Project  : {project[:100]}{'…' if len(project) > 100 else ''}")
        print(f"  max_turns: {args.max_turns}")
        print(f"  DB       : {args.db}")

        # ── Stream loop with interrupt/resume support ─────────────────────
        # Outer while-loop re-streams after each resume so the review cycle
        # (reject → re-interview → re-review) works for N iterations.
        # After the first run, stream_input=None tells LangGraph to continue
        # from the latest checkpoint rather than re-initialising state.
        stream_input = initial_state

        while True:
            interrupted = False

            for step_output in graph.stream(stream_input, config=config):
                for node_name, updates in step_output.items():

                    if node_name == "__interrupt__":
                        print(f"\n{'─'*70}")
                        print("  NODE: __INTERRUPT__ — REVIEW GATE")
                        print(f"{'─'*70}")

                        decision = _collect_review_decision(updates)

                        if decision["approved"]:
                            _section("Review: APPROVED ✓")
                            if decision.get("feedback"):
                                print(f"  Notes: {decision['feedback']}")
                        else:
                            _section("Review: REJECTED ✗")
                            print(f"  Feedback: {decision['feedback']}")
                            print("  Interview will restart with this feedback.")

                        stream_input = Command(resume=decision)
                        interrupted = True
                        break

                    else:
                        _handle_step(node_name, updates)

                if interrupted:
                    break

            if not interrupted:
                break  # no interrupt → workflow finished


        _section("Workflow complete")
        print("  interview_record          — full conversation + validated requirements")
        print("  reviewed_interview_record — approved record (if review passed)")
        print("  product_backlog           — initial sprint backlog (if SprintAgent ran)")
        print()