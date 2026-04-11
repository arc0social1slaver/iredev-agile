"""
run_iReDev.py – End-to-end demo runner for iReDev.

Sprint Zero flow:
  interviewer_turn ↔ enduser_turn   → produces: interview_record
  sprint_agent_turn                  → produces: product_backlog

Incremental extraction
──────────────────────
The InterviewerAgent extracts requirements after EVERY stakeholder turn.
Watch for "DRAFT UPDATE" lines in the output — these show the live
requirements list growing and conflicts being resolved in real time.

Stopping
────────
• PRIMARY : agent calls write_interview_record when completeness ≥ threshold.
• SAFETY  : turn_count >= max_turns  (default 20, CLI-configurable).

Usage
─────
  python run_iReDev.py
  python run_iReDev.py --max-turns 15
  python run_iReDev.py --project "Custom project brief..."
"""

import argparse
import logging
import textwrap
from dotenv import load_dotenv
from src.orchestrator import build_graph

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="iReDev demo runner")
    p.add_argument(
        "--max-turns",
        type=int,
        default=20,
        help="Safety-net max interview turns (default: 20). "
        "The interviewer stops earlier when completeness ≥ threshold.",
    )
    p.add_argument(
        "--project", type=str, default=None, help="Override project description."
    )
    return p.parse_args()


# ── Display helpers ───────────────────────────────────────────────────────────

_SEP = "═" * 70


def _section(title: str) -> None:
    print(f"\n{_SEP}\n  {title}\n{_SEP}")


def _wrap(text: str, indent: int = 4) -> str:
    return textwrap.fill(
        str(text),
        width=80,
        initial_indent=" " * indent,
        subsequent_indent=" " * indent,
    )


def _display_draft_update(draft: list) -> None:
    """Show requirements_draft changes — called after each interviewer turn."""
    if not draft:
        return
    print(f"\n  ┌─ DRAFT UPDATE ({len(draft)} requirements) ─────────────────")
    for r in draft[-5:]:  # show last 5 to keep output readable
        status_icon = {"confirmed": "✓", "inferred": "~", "ambiguous": "?"}.get(
            r.get("status", ""), "·"
        )
        print(
            f"  │  {status_icon} [{r.get('id','?')}] "
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
    print(f"    Functional   : {sum(1 for r in reqs if r.get('type')=='functional')}")
    print(
        f"    Non-functional: {sum(1 for r in reqs if r.get('type')=='non_functional')}"
    )
    print(f"    Constraints  : {sum(1 for r in reqs if r.get('type')=='constraint')}")
    print(f"  Gaps         : {len(gaps)}")
    print(f"  Completeness : {record.get('completeness_score', '?')}")
    print(f"  Notes        : {record.get('notes', '')[:160]}")
    if reqs:
        print("\n  All requirements:")
        for r in reqs:
            status_icon = {"confirmed": "✓", "inferred": "~", "ambiguous": "?"}.get(
                r.get("status", ""), "·"
            )
            print(
                f"    {status_icon} [{r.get('id','?')}] "
                f"({r.get('type','?')}, prio={r.get('priority','?')}) "
                f"{r.get('description','')[:80]}"
            )
    if gaps:
        print("\n  Gaps:")
        for g in gaps:
            print(f"    • {g}")


def _display_product_backlog(artifact: dict) -> None:
    _section("ARTIFACT: product_backlog")
    print(_wrap(str(artifact)[:800]))
    print("  … (truncated)")


# ── Stream handler ────────────────────────────────────────────────────────────


def _handle_step(node_name: str, updates: dict) -> None:
    if not updates:
        return

    print(f"\n{'─'*70}")
    print(f"  NODE: {node_name.upper()}")
    print(f"{'─'*70}")

    # Conversation turns
    conversation = updates.get("conversation")
    if conversation:
        last = conversation[-1]
        role = last.get("role", "unknown")
        label = "INTERVIEWER" if role == "interviewer" else "STAKEHOLDER"
        print(f"\n  [{label}]")
        print(_wrap(last.get("content", "")))

    # Live requirements draft update (incremental extraction)
    draft = updates.get("requirements_draft")
    if draft is not None:
        _display_draft_update(draft)

    # interview_complete flag
    if updates.get("interview_complete"):
        print("\n  ✓ interview_complete = True  (agent satisfied with coverage)")

    # Routing
    next_node = updates.get("next_node")
    if next_node:
        print(f"\n  → routing to: {'END' if next_node == '__end__' else next_node}")

    # Artifacts finalised
    artifacts = updates.get("artifacts")
    if artifacts:
        for name, content in artifacts.items():
            if name == "interview_record":
                _display_interview_record(content)
            elif name == "product_backlog":
                _display_product_backlog(content)
            else:
                print(f"\n  Artifact produced: {name}")

    # Phase
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
    project = args.project or default_project

    graph = build_graph()

    initial_state = {
        # ── Session ───────────────────────────────────────────────────────
        "session_id": "demo_session_1",
        "project_description": project,
        # ── Phase ─────────────────────────────────────────────────────────
        "system_phase": "sprint_zero_planning",
        # ── Artifacts ─────────────────────────────────────────────────────
        "artifacts": {},
        # ── Interview sub-state ───────────────────────────────────────────
        "conversation": [],
        "turn_count": 0,
        # max_turns is a SAFETY NET — the interviewer stops on its own
        # via interview_complete=True when completeness ≥ threshold (0.8).
        # Only change this if you have a specific token-budget constraint.
        "max_turns": args.max_turns,  # default 20
        "interview_complete": False,
        # ── Live requirements draft (populated incrementally per turn) ─────
        # InterviewerAgent.update_requirements appends here after each
        # stakeholder reply. write_interview_record copies this into
        # interview_record["requirements_identified"].
        "requirements_draft": [],
        # ── Misc ──────────────────────────────────────────────────────────
        "errors": [],
    }

    _section("iReDev — Sprint Zero Planning")
    print(f"  Project  : {project[:100]}{'…' if len(project) > 100 else ''}")
    print(
        f"  max_turns: {args.max_turns}  (safety net — agent stops earlier via completeness)"
    )
    print(
        "\n  Watch for DRAFT UPDATE blocks — requirements are extracted and\n"
        "  conflict-checked LIVE after every stakeholder reply."
    )

    while True:
        interrupted = False
        for step_output in graph.stream(
            initial_state, config={"configurable": {"thread_id": "123"}}
        ):
            if "__interrupt__" in step_output:
                from langgraph.types import Command

                interrupt_obj = step_output["__interrupt__"][0]
                payload = interrupt_obj.value

                user_input = input(f"{payload.get("instruction", "Hahaha: ")}").strip()
                approved = user_input.lower() == "y"
                if approved:
                    initial_state = Command(resume={"action": "accept", "feedback": ""})
                else:
                    initial_state = Command(
                        resume={"action": "reject", "feedback": user_input}
                    )
                interrupted = True
                break
            for node_name, updates in step_output.items():
                _handle_step(node_name, updates)

        if not interrupted:
            break
    _section("Workflow complete")
    print("  interview_record  — full conversation + validated requirements")
    print("  product_backlog   — initial sprint backlog (if SprintAgent ran)")
    print()
