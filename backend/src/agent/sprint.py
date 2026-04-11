"""
sprint_agent.py – SprintAgent  (Sprint Zero, step 2)

Role
----
After the requirements interview completes, the SprintAgent is automatically
triggered by the supervisor.  It reads the interview_record artifact and
produces the initial product_backlog artifact.

This implementation is a proof-of-concept stub that demonstrates:
  1. The agent is called only after interview_record exists.
  2. It reads and logs the requirements from interview_record.
  3. It writes a product_backlog artifact into WorkflowState["artifacts"].

Replace the stub body of _build_backlog_items() with a real LLM call
(or a full BaseAgent subclass with a ReAct loop) when ready.

Integration
-----------
Triggered by:  supervisor_node (when interview_record present, product_backlog absent)
Graph node  :  sprint_agent_turn  (registered in graph.py)
Produces    :  WorkflowState["artifacts"]["product_backlog"]
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_SEP = "=" * 65


class SprintAgent:
    """
    Stub SprintAgent – proof-of-concept for artifact-driven activation.

    Activation condition (evaluated by the supervisor in flow.py):
      - system_phase == "sprint_zero_planning"
      - "interview_record" present in WorkflowState["artifacts"]
      - "product_backlog" NOT present in WorkflowState["artifacts"]

    To replace with a full LLM-powered implementation:
      - Subclass BaseAgent.
      - Override _register_tools() with tools for backlog generation.
      - Replace process() with a call to self.react(state, task).
    """

    # -- LangGraph node entry point ----------------------------------------

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called by graph.py's sprint_agent_turn_fn.

        Reads interview_record from state, prints confirmation to demonstrate
        the trigger, and returns a stub product_backlog artifact.
        """
        feedback = state.get("review_feedback")
        review_approved = state.get("review_approved")
        artifacts = state.get("artifacts") or {}
        messID = state.get("metadata", {}).get("messID")
        interview_record = artifacts.get("interview_record", {})
        requirements = interview_record.get("requirements_identified") or []
        session_id = state.get("session_id", "unknown")
        completeness = interview_record.get("completeness_score", 0.0)
        gaps = interview_record.get("gaps_identified") or []

        if feedback:
            state["artifacts"]["product_backlog"]["gaps_carried_over"].append(feedback)
            return state
        elif review_approved == True:
            return state
        if not messID:
            import uuid

            state["metadata"] = {}
            state["metadata"]["messID"] = str(uuid.uuid4())

        self._print_trigger_report(session_id, requirements, gaps, completeness)

        backlog_items = self._build_backlog_items(requirements)
        product_backlog = {
            "id": session_id,
            "source_artifact": "interview_record",
            "status": "draft",
            "total_items": len(backlog_items),
            "items": backlog_items,
            "gaps_carried_over": gaps,
            "notes": (
                "STUB – generated directly from interview_record requirements. "
                "Replace SprintAgent.process() with a real LLM-based "
                "implementation to add story points, acceptance criteria, "
                "sprint assignments, and priority scoring."
            ),
            "created_at": datetime.now().isoformat(),
        }

        updated_artifacts = {**artifacts, "product_backlog": product_backlog}
        state["artifacts"]["product_backlog"] = product_backlog

        logger.info(
            "SprintAgent: product_backlog written -- %d items from %d requirements.",
            len(backlog_items),
            len(requirements),
        )

        return state

    # -- Internal helpers ---------------------------------------------------

    def _print_trigger_report(
        self,
        session_id: str,
        requirements: List[Dict],
        gaps: List[str],
        completeness: float,
    ) -> None:
        print(f"\n{_SEP}")
        print("  SprintAgent -- triggered by supervisor")
        print(_SEP)
        print(f"  Session    : {session_id}")
        print(f"  Phase      : sprint_zero_planning  ->  build_product_backlog")
        print(f"  Input      : interview_record")
        print(f"  Completeness score : {completeness:.2%}")
        print(f"  Requirements found : {len(requirements)}")

        if requirements:
            print()
            print("  Requirements (first 8):")
            for req in requirements[:8]:
                req_id = req.get("id", "?")
                req_type = req.get("type", "?")[:3].upper()
                desc = req.get("description", "")[:72]
                priority = req.get("priority", "?")
                print(f"    [{req_id}] ({req_type}, {priority}) {desc}")
            if len(requirements) > 8:
                print(f"    ... and {len(requirements) - 8} more")

        if gaps:
            print()
            print(f"  Gaps identified ({len(gaps)}):")
            for gap in gaps[:4]:
                print(f"    - {gap[:80]}")
            if len(gaps) > 4:
                print(f"    ... and {len(gaps) - 4} more")

        print()
        print("  Output     : product_backlog  [stub -- replace with LLM call]")
        print(_SEP + "\n")

    @staticmethod
    def _build_backlog_items(requirements: List[Dict]) -> List[Dict]:
        """
        Convert interview_record requirements into Product Backlog Items (PBIs).

        This is a 1-to-1 stub mapping.  A real implementation would call an
        LLM to merge and refine requirements, estimate story points, write
        acceptance criteria, assign sprint priorities, and detect duplicates.
        """
        if not requirements:
            return [
                {
                    "id": "PBI-001",
                    "title": "STUB -- no requirements extracted from interview",
                    "type": "functional",
                    "priority": "high",
                    "source_req_id": None,
                    "story_points": None,
                    "status": "open",
                    "acceptance_criteria": [],
                    "notes": (
                        "The interview_record contained no requirements. "
                        "Review the interview quality or re-run the interview phase."
                    ),
                }
            ]

        items = []
        for i, req in enumerate(requirements, start=1):
            items.append(
                {
                    "id": f"PBI-{i:03d}",
                    "title": req.get("description", f"Requirement {i}")[:100],
                    "type": req.get("type", "functional"),
                    "priority": req.get("priority", "medium"),
                    "source_req_id": req.get("id"),
                    "story_points": None,
                    "status": "open",
                    "acceptance_criteria": [],
                    "notes": "STUB -- story points and acceptance criteria pending.",
                }
            )

        return items
