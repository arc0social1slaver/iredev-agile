"""
demo_agent.py – End-to-end demo runner.

Starts the workflow from Sprint Zero Planning with a sample project brief.
Uses .stream() so each node's output is printed in real time.
"""

import logging
from dotenv import load_dotenv
from src.orchestrator import build_graph

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


if __name__ == "__main__":
    graph = build_graph()

    initial_state = {
        # -- Session -------------------------------------------------------
        "session_id":          "demo_session_1",
        "project_description": (
            "We need a course-registration system for university students. "
            "Students should be able to browse available courses, register for "
            "up to 5 courses per semester, view their schedule, and receive "
            "notifications about enrollment deadlines."
        ),

        # -- Phase management ----------------------------------------------
        "system_phase": "sprint_zero_planning",

        # -- Artifacts -----------------------------------------------------
        "artifacts": {},

        # -- Interview sub-state -------------------------------------------
        # max_turns=2: interviewer asks 2 questions, enduser answers twice,
        # then the interviewer writes the interview_record.  Keeps token cost
        # low during debugging; raise to 10-15 for a real run.
        "conversation":       [],
        "turn_count":         0,
        "max_turns":          2,
        "interview_complete": False,

        # -- Misc ----------------------------------------------------------
        "errors": [],
    }

    print("\nStarting workflow -- Sprint Zero Planning")
    print("=" * 65)

    for step_output in graph.stream(initial_state):
        for node_name, state_updates in step_output.items():
            print(f"\n--- [{node_name.upper()}] ---")

            if not state_updates:
                continue

            conversation = state_updates.get("conversation")
            if conversation:
                last  = conversation[-1]
                role  = last.get("role", "unknown")
                content = last.get("content", "")
                label = "INTERVIEWER" if role == "interviewer" else "STAKEHOLDER"
                print(f"[{label}]: {content}")

            artifacts = state_updates.get("artifacts")
            if artifacts:
                for name in artifacts:
                    print(f"Artifact produced: {name}")

            phase = state_updates.get("system_phase")
            if phase:
                print(f"Phase: {phase}")

    print("\n" + "=" * 65)
    print("Workflow complete.")