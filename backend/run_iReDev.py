"""
run_iReDev.py - Unified runner for full flow or debug starting/ending at any artifact.

Usage (full workflow):
    python run_iReDev.py
    python run_iReDev.py --max-turns 15
    python run_iReDev.py --project path/to/brief.txt
    python run_iReDev.py --db my_checkpoints.db --reset-db

Usage (debug from a specific artifact):
    python run_iReDev.py --start-at requirement_list
    python run_iReDev.py --start-at validated_product_backlog_approved --auto-approve

Usage (stop after a specific artifact is produced):
    python run_iReDev.py --end-at product_backlog
    python run_iReDev.py --start-at requirement_list --end-at product_backlog

Usage (debug from one artifact to another):
    python run_iReDev.py --start-at interview_record --end-at requirement_list_approved
"""

import argparse
import json
import logging
import os
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Debug manifest: for every target artifact, the artifacts that must be
# pre-loaded so the supervisor will select that step.
# Each entry: (state_key, file_prefix, is_sentinel)
# Sentinel artifacts are optional (missing file -> {}), non-sentinel are required.
# ---------------------------------------------------------------------------
def _manifest_for_product_vision():
    return []

def _manifest_for_reviewed_product_vision():
    return [("product_vision", "product_vision", False)]

def _manifest_for_elicitation_agenda_artifact():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
    ]

def _manifest_for_reviewed_elicitation_agenda():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
    ]

def _manifest_for_interview_record():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
    ]

def _manifest_for_reviewed_interview_record():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
    ]

def _manifest_for_requirement_list():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
    ]

def _manifest_for_requirement_list_approved():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
    ]

def _manifest_for_product_backlog():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
        ("requirement_list_approved", "requirement_list_approved", True),
    ]

def _manifest_for_product_backlog_approved():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
        ("requirement_list_approved", "requirement_list_approved", True),
        ("product_backlog", "product_backlog", False),
    ]

def _manifest_for_validated_product_backlog():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
        ("requirement_list_approved", "requirement_list_approved", True),
        ("product_backlog", "product_backlog", False),
        ("product_backlog_approved", "product_backlog_approved", True),
    ]

def _manifest_for_validated_product_backlog_approved():
    return [
        ("product_vision", "product_vision", False),
        ("reviewed_product_vision", "reviewed_product_vision", True),
        ("elicitation_agenda_artifact", "elicitation_agenda_artifact", False),
        ("reviewed_elicitation_agenda", "reviewed_elicitation_agenda", True),
        ("interview_record", "interview_record", False),
        ("reviewed_interview_record", "reviewed_interview_record", True),
        ("requirement_list", "requirement_list", False),
        ("requirement_list_approved", "requirement_list_approved", True),
        ("product_backlog", "product_backlog", False),
        ("product_backlog_approved", "product_backlog_approved", True),
        ("validated_product_backlog", "validated_product_backlog", False),
    ]

DEBUG_MANIFESTS: Dict[str, callable] = {
    "product_vision":                    _manifest_for_product_vision,
    "reviewed_product_vision":           _manifest_for_reviewed_product_vision,
    "elicitation_agenda_artifact":       _manifest_for_elicitation_agenda_artifact,
    "reviewed_elicitation_agenda":       _manifest_for_reviewed_elicitation_agenda,
    "interview_record":                  _manifest_for_interview_record,
    "reviewed_interview_record":         _manifest_for_reviewed_interview_record,
    "requirement_list":                  _manifest_for_requirement_list,
    "requirement_list_approved":         _manifest_for_requirement_list_approved,
    "product_backlog":                   _manifest_for_product_backlog,
    "product_backlog_approved":          _manifest_for_product_backlog_approved,
    "validated_product_backlog":         _manifest_for_validated_product_backlog,
    "validated_product_backlog_approved": _manifest_for_validated_product_backlog_approved,
}

SEP = "=" * 70

def section(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")

def wrap(text: str, indent: int = 4) -> str:
    return textwrap.fill(
        str(text), width=80,
        initial_indent=" " * indent,
        subsequent_indent=" " * indent,
    )

# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="iReDev unified runner - full flow or debug from/to any artifact",
    )
    p.add_argument(
        "--start-at",
        type=str,
        default=None,
        choices=list(DEBUG_MANIFESTS.keys()),
        help="Debug mode: start at the step that produces this artifact.",
    )
    p.add_argument(
        "--end-at",
        type=str,
        default=None,
        choices=list(DEBUG_MANIFESTS.keys()),
        help="Stop the workflow immediately after this artifact is produced.",
    )
    p.add_argument(
        "--max-turns",
        type=int,
        default=20,
        help="Safety-net max interview turns (default: 20).",
    )
    p.add_argument(
        "--project",
        type=argparse.FileType("r", encoding="utf-8"),
        default=None,
        help="Path to project description file.",
    )
    p.add_argument(
        "--db",
        type=str,
        default="checkpoints.db",
        help="Path to SQLite checkpoint DB (default: checkpoints.db).",
    )
    p.add_argument(
        "--reset-db",
        action="store_true",
        help="Delete checkpoint DB before running.",
    )
    p.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve all HITL gates without prompting.",
    )
    p.add_argument(
        "--artifact-dir",
        type=str,
        default=None,
        help="Directory containing artifact JSON files (default: auto-detect ./artifacts/artifact/).",
    )
    p.add_argument(
        "--session",
        type=str,
        default="demo_session_1",
        help="Session ID used in artifact file names (default: demo_session_1).",
    )
    return p.parse_args()

# ---------------------------------------------------------------------------
# Artifact loading helpers
# ---------------------------------------------------------------------------
def resolve_artifact_dir(artifact_dir_arg: Optional[str]) -> Path:
    if artifact_dir_arg:
        p = Path(artifact_dir_arg).expanduser().resolve()
        if not p.is_dir():
            print(f"[ERROR] --artifact-dir does not exist: {p}")
            sys.exit(1)
        return p
    here = Path(__file__).resolve().parent
    for candidate in [here] + list(here.parents):
        guess = candidate / "artifacts" / "artifact"
        if guess.is_dir():
            return guess
    print("[ERROR] Could not find artifacts/artifact/ directory. Use --artifact-dir.")
    sys.exit(1)

def load_artifact(
    artifact_dir: Path,
    file_prefix: str,
    session: str,
    is_sentinel: bool,
) -> Optional[Dict[str, Any]]:
    path = artifact_dir / f"{file_prefix}_{session}.json"
    if not path.exists():
        if is_sentinel:
            print(f"  Sentinel missing, using empty dict: {path.name}")
            return {}
        print(f"  Required artifact not found: {path}")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        chars = len(json.dumps(data, ensure_ascii=False))
        tag = "  [sentinel]" if is_sentinel else ""
        print(f"  Loaded {path.name:<55} (~{chars:>7,} chars){tag}")
        return data
    except json.JSONDecodeError as exc:
        print(f"  JSON error in {path.name}: {exc}")
        sys.exit(1)

def build_artifacts(
    target: str,
    session: str,
    artifact_dir: Path,
) -> Dict[str, Any]:
    manifest_fn = DEBUG_MANIFESTS[target]
    manifest = manifest_fn()
    artifacts: Dict[str, Any] = {}
    missing_required: List[str] = []

    print(f"\nArtifact directory: {artifact_dir}")
    print(f"Loading {len(manifest)} prerequisite(s) to start at '{target}':\n")

    for state_key, file_prefix, is_sentinel in manifest:
        data = load_artifact(artifact_dir, file_prefix, session, is_sentinel)
        if data is None:
            missing_required.append(f"{file_prefix}_{session}.json")
        else:
            artifacts[state_key] = data

    if missing_required:
        print(f"\n[ERROR] Missing {len(missing_required)} required artifact(s):")
        for f in missing_required:
            print(f"   • {f}")
        sys.exit(1)

    print(f"\nLoaded {len(artifacts)} artifact(s) into initial state.")
    return artifacts

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def display_product_vision(vision: dict) -> None:
    section("ARTIFACT: product_vision")
    stakeholders = vision.get("target_audiences") or []
    assumptions  = vision.get("assumptions") or []
    print(f"  Core Problem    : {vision.get('core_problem', '?')}")
    print(f"  Value Prop.     : {vision.get('value_proposition', '?')}")
    constraints = vision.get("project_constraints") or []
    nfrs = vision.get("non_functional_requirements") or []
    combined_constraints = constraints + nfrs
    print(f"  Constraints & NFRs ({len(combined_constraints)}) :")
    for c in combined_constraints:
        print(f"    • {c}")

    eval_criteria = vision.get("evaluation_criteria") or []
    if eval_criteria:
        print(f"  Evaluation Criteria ({len(eval_criteria)}) :")
        for e in eval_criteria:
            print(f"    • {e}")

    oos = vision.get("out_of_scope") or []
    print(f"  Out-of-Scope ({len(oos)}):")
    for o in oos:
        print(f"    • {o}")
    if stakeholders:
        print(f"\n  Stakeholders ({len(stakeholders)}):")
        for s in stakeholders:
            print(
                f"    [{s.get('type','?')}] {s.get('role','?')} "
                f"(influence={s.get('influence_level','?')}) - {s.get('key_concern','')[:80]}"
            )
    if assumptions:
        needs_val = [a for a in assumptions if a.get("needs_validation")]
        print(f"\n  Assumptions: {len(assumptions)} total, {len(needs_val)} need validation")
        for a in needs_val[:5]:
            print(f"    [WARNING] {a.get('statement','')[:100]}")
        if len(needs_val) > 5:
            print(f"    ... (+{len(needs_val) - 5} more)")

def display_requirement_list(rl: dict) -> None:
    section("ARTIFACT: requirement_list")
    reqs = rl.get("requirements") or []
    by_type: Dict[str, int] = {}
    for r in reqs:
        rt = r.get("req_type", "unknown")
        by_type[rt] = by_type.get(rt, 0) + 1
    print(f"  Synthesised at  : {rl.get('synthesised_at', '?')}")
    print(f"  Total           : {len(reqs)}")
    for t, c in by_type.items():
        print(f"    {t:15s}: {c}")
    if reqs:
        print("\n  All requirements:")
        for r in reqs:
            icon = {"confirmed": "*", "inferred": "~", "excluded": "x"}.get(r.get("status", ""), ".")
            print(
                f"    {icon} [{r.get('req_id','?')}] "
                f"({r.get('req_type','?')}, prio={r.get('priority','?')}) "
                f"[{r.get('epic','?')}] "
                f"{r.get('statement','')}"
            )

def display_product_backlog(artifact: dict) -> None:
    section("ARTIFACT: product_backlog")
    items = artifact.get("items") or []
    methodology = artifact.get("methodology") or {}
    print(f"  Total items    : {artifact.get('total_items', len(items))}")
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
            print(f"    ... (+{len(items) - 15} more)")

# ---------------------------------------------------------------------------
# HITL interactive / auto-approve handler
# ---------------------------------------------------------------------------
def collect_review_decision(updates: tuple, auto_approve: bool) -> Dict[str, Any]:
    for interrupt_obj in updates:
        payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        if not isinstance(payload, dict):
            continue
        review_type = payload.get("review_type", "unknown")
        print(f"\n{'─'*70}")
        print(f"  HITL GATE - {review_type.upper().replace('_', ' ')}")
        print(f"{'─'*70}")

        artifact_data = payload.get("artifact_data") or {}
        if review_type == "requirement_list":
            reqs = artifact_data.get("requirements") or []
            by_type: Dict[str, int] = {}
            for r in reqs:
                by_type[r.get("req_type", "?")] = by_type.get(r.get("req_type", "?"), 0) + 1
            print(f"\n  {len(reqs)} requirements (FR={by_type.get('functional',0)} ... )")
        elif review_type == "product_backlog":
            items = artifact_data.get("items") or []
            print(f"\n  {len(items)} user stories")
        elif review_type == "validated_product_backlog":
            items = artifact_data.get("items") or []
            print(f"\n  {len(items)} validated PBIs")
        # other types can be added similarly

    if auto_approve:
        print("\n  [auto-approve] Approved")
        return {"approved": True, "feedback": None}

    print(f"\n{'─'*70}  REVIEW DECISION")
    while True:
        choice = input("\n  Approve? [y/n]: ").strip().lower()
        if choice in ("y", "n"):
            break
        print("  Please enter y or n.")

    if choice == "y":
        notes = input("  Optional notes (Enter to skip): ").strip()
        return {"approved": True, "feedback": notes or None}
    else:
        print("\n  Provide feedback (blank line to finish):")
        lines = []
        while True:
            line = input("  > ")
            if not line:
                break
            lines.append(line)
        feedback = " ".join(lines).strip() or "No specific feedback provided."
        return {"approved": False, "feedback": feedback}

# ---------------------------------------------------------------------------
# State initialisation
# ---------------------------------------------------------------------------
def build_initial_state(args, preloaded_artifacts=None):
    if args.project:
        project_desc = args.project.read()
        args.project.close()
    else:
        project_desc = (
            "We need a course-registration system for university students. "
            "Students should be able to browse available courses, register for "
            "up to 5 courses per semester, view their schedule, and receive "
            "notifications about enrollment deadlines."
        )

    state: Dict[str, Any] = {}

    if preloaded_artifacts:
        interview_record = preloaded_artifacts.get("interview_record") or {}
        pd_from_record = interview_record.get("project_description")
        if pd_from_record:
            project_desc = pd_from_record
        artifacts = preloaded_artifacts

        # Seed the agent’s own state fields so it doesn’t re‑run bootstrap steps
        if "product_vision" in artifacts:
            state["product_vision"] = artifacts["product_vision"]
        if "elicitation_agenda_artifact" in artifacts:
            state["elicitation_agenda"] = artifacts["elicitation_agenda_artifact"]

        needs_srs = (args.start_at == "requirement_list")
        interview_complete = True if needs_srs else False
    else:
        artifacts = {}
        needs_srs = False
        interview_complete = False

    state.update({
        "session_id":          args.session,
        "project_description": project_desc,
        "system_phase":        "sprint_zero_planning",
        "artifacts":           artifacts,
        "conversation":        [],
        "turn_count":          0,
        "max_turns":           args.max_turns,
        "interview_complete":  interview_complete,
        "requirements_draft":  [],
        "backlog_draft":       [],
        "errors":              [],
        "_needs_srs_synthesis": needs_srs,
    })
    return state

# ---------------------------------------------------------------------------
# Stream loop with interrupt and end-at support
# ---------------------------------------------------------------------------
def run_workflow(initial_state, config, args):
    from src.orchestrator import build_graph
    preloaded_keys = set(initial_state.get("artifacts", {}).keys())
    final_artifacts = dict(initial_state.get("artifacts", {}))
    end_artifact = args.end_at

    # If the end artifact is already present, stop immediately
    if end_artifact and end_artifact in final_artifacts:
        print(f"\nTarget end artifact '{end_artifact}' already in initial state. Nothing to do.")
        return final_artifacts

    with SqliteSaver.from_conn_string(args.db) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        stream_input = initial_state
        should_stop = False

        last_printed_turn = 0

        while not should_stop:
            interrupted = False
            for step_output in graph.stream(stream_input, config=config):
                for node_name, updates in step_output.items():
                    if node_name == "__interrupt__":
                        decision = collect_review_decision(updates, args.auto_approve)
                        stream_input = Command(resume=decision)
                        interrupted = True
                        break
                    else:
                        print(f"\n{'─'*70}\n  NODE: {node_name.upper()}\n{'─'*70}")

                        if node_name == "interviewer_turn":
                            question = updates.get("current_question")
                            if question:
                                print(f"\n  [INTERVIEWER] {question}\n")

                        if node_name == "enduser_turn":
                            conv = updates.get("conversation")
                            if conv:
                                new_turns = conv[last_printed_turn:]
                                for turn in new_turns:
                                    role = turn.get("role", "enduser")
                                    content = turn.get("content", "")
                                    print(f"\n  [{role.upper()}] {content}\n")
                                last_printed_turn = len(conv)

                        if isinstance(updates, dict):
                            next_node = updates.get("next_node")
                            if next_node:
                                dest = "END" if next_node == "__end__" else next_node
                                print(f"\n  Routing to: {dest}")

                            new_arts = updates.get("artifacts") or {}
                            for name, content in new_arts.items():
                                if name not in preloaded_keys:
                                    if name == "product_vision":
                                        display_product_vision(content)
                                    elif name == "requirement_list":
                                        display_requirement_list(content)
                                    elif name == "product_backlog":
                                        display_product_backlog(content)
                                    else:
                                        print(f"\n  Artifact produced: {name}")

                            errors = updates.get("errors")
                            if errors:
                                print(f"\n  Errors:")
                                for e in errors:
                                    print(f"    • {e}")

                            phase = updates.get("system_phase")
                            if phase:
                                print(f"\n  Phase: {phase}")

                            final_artifacts.update(new_arts)

                            # Check if end-at artifact just appeared
                            if end_artifact and end_artifact in final_artifacts:
                                print(f"\nTarget end artifact '{end_artifact}' produced. Stopping.")
                                should_stop = True
                                break  # break inner for-loop

                if interrupted or should_stop:
                    break  # break outer step_output loop

    return final_artifacts

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    if args.reset_db and os.path.exists(args.db):
        os.remove(args.db)

    if args.start_at:
        artifact_dir = resolve_artifact_dir(args.artifact_dir)
        preloaded = build_artifacts(args.start_at, args.session, artifact_dir)
        initial_state = build_initial_state(args, preloaded)
        section(f"DEBUG START - target artifact: {args.start_at}")
    else:
        initial_state = build_initial_state(args)
        section("iReDev - Full Sprint Zero + Refinement flow")

    if args.end_at:
        print(f"  Will stop after: {args.end_at}")

    print(f"  Session      : {args.session}")
    print(f"  DB           : {args.db}")
    print(f"  Auto-approve : {args.auto_approve}")

    config = {
        "configurable": {
            "thread_id": f"run_{uuid.uuid4().hex}",
            "recursion_limit": 100,
        }
    }

    final_artifacts = run_workflow(initial_state, config, args)

    section("Workflow complete")
    produced = [k for k in final_artifacts if k != "session_id"]
    print(f"  Final artifacts: {', '.join(produced) if produced else '(none)'}")

    errors = final_artifacts.get("errors") or []
    if errors:
        print(f"\n  Accumulated errors ({len(errors)}):")
        for e in errors:
            print(f"    • {e}")

if __name__ == "__main__":
    main()