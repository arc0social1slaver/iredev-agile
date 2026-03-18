"""
Sprint Manager Agent for iReDev framework.
Acts as Technical Product Owner to maintain and prioritize Product Backlog.
"""

import asyncio
import logging
import uuid
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Set, Tuple
from enum import Enum

from .knowledge_driven_agent import KnowledgeDrivenAgent
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus, ArtifactMetadata
from ..artifact.pool import ArtifactPool
from ..orchestrator.human_in_loop import HumanReviewManager

logger = logging.getLogger(__name__)


class SprintManagerAgent(KnowledgeDrivenAgent):
    """
    Sprint Manager Agent - acts as Technical Product Owner.

    Responsibilities:
    - Synthesize Product Backlog from User Stories
    - Prioritize backlog items based on business value and dependencies
    - Validate backlog items when criteria are met
    - Generate Sprint Backlogs for sprint planning
    - Track dependencies between items
    """

    def __init__(
        self,
        agent_id: str = "sprint_manager",
        config_path: Optional[str] = None,
        artifact_pool: Optional[ArtifactPool] = None,
        human_queue: Optional[asyncio.Queue] = None,
        human_review_manager: Optional[HumanReviewManager] = None,
        **kwargs,
    ):
        # Define required knowledge modules
        knowledge_modules = [
            "agile_frameworks",
            "estimation_techniques",
            "dependency_management",
            "prioritization_methods",
            "jira_ticketing",
        ]

        super().__init__(
            name=agent_id,
            knowledge_modules=knowledge_modules,
            config_path=config_path,
            **kwargs,
        )

        self.agent_id = agent_id
        self.artifact_pool = artifact_pool
        self.human_queue: Optional[asyncio.Queue] = human_queue
        self.human_review_manager: Optional[HumanReviewManager] = human_review_manager

        # Agent configuration
        self.prioritization_formula = self.config.get(
            "prioritization_formula", "wsjf"  # Weighted Shortest Job First
        )
        self.business_value_weight = self.config.get("business_value_weight", 0.6)
        self.complexity_weight = self.config.get("complexity_weight", 0.4)
        self.default_sprint_capacity = self.config.get("default_sprint_capacity", 40)

        # Profile prompt
        self.profile_prompt = self._create_profile_prompt()
        self.add_to_memory("system", self.profile_prompt)

    def _create_profile_prompt(self) -> str:
        """Create strategic, visionary persona prompt."""
        return """You are the Sprint Manager - a strategic Technical Product Owner.

Your Mission:
Synthesize stakeholder needs with technical feasibility to maintain a healthy, prioritized Product Backlog.

Your Persona:
- Strategic and visionary, seeing the big picture
- Deep understanding of business value and technical dependencies
- Decisive prioritizer, balancing competing interests
- Keeper of the Product Backlog's health and readiness

Your Responsibilities:
1. Synthesize User Stories into a coherent Product Backlog
2. Prioritize items based on business value and technical dependencies
3. Validate backlog items when they meet completeness criteria
4. Generate Sprint Backlogs for team execution
5. Track dependencies and manage spillover

Key Principles:
- Business value drives priority, but technical dependencies constrain ordering
- Every backlog item must have clear acceptance criteria
- Dependencies must be explicitly tracked and managed
- Items are only "ready" when validated
- Sprint Backlogs respect team capacity

Your Decision Framework:
- Use WSJF (Weighted Shortest Job First) for prioritization
- Consider both value and effort
- Respect dependency chains
- Ensure each item is independently valuable and testable

Always maintain a strategic view while ensuring tactical readiness for development.
"""

    def _get_action_prompt(self, action: str, context: Dict[str, Any] = None) -> str:
        """Get action-specific prompt."""
        action_prompts = {
            "synthesize_backlog": """You are synthesizing User Stories into a Product Backlog.

Context:
- User Stories: {user_stories}
- Functional Requirements: {functional_reqs}
- Non-Functional Requirements: {nfr_reqs}

Your Task:
Analyze these artifacts and create a structured Product Backlog.

Guidelines:
1. Each User Story becomes a backlog item
2. Group related stories that form an epic
3. Extract clear titles and descriptions
4. Identify business value indicators
5. Assess technical complexity
6. Note any obvious dependencies
7. Note that the Product Backlog must cover all user stories
8. Prioritize Product Backlog items using WSJF (Weighted Shortest Job First)

For each backlog item, determine:
- Title (clear and concise)
- Description (what, why, who)
- Business Value (1-10)
- Technical Complexity (1-10)
- Epic grouping (at least 1 user story)
- Initial dependencies
- Priority Score
- Priority

Calculation:
Priority Score = Business Value / Technical Complexity

RESPONSE FORMAT:
Return JSON array of backlog items. Each backlog item should have:
- title
- description
- business_value (1-10)
- technical_complexity (1-10)
- epic
- dependencies (list of user stories with ID that this item depends on)
- priority_score
- priority (critical/high/medium/low/nice_to_have)
- acceptance_criteria (general acceptance criteria of user stories' list in dependencies)

Return ONLY the JSON array, no other text.
""",
            "process_feedback": """You are processing user feedback on the Product Backlog.

Feedback Received:
{feedback}

Current Backlog Items:
{backlog_items}

Your Task:
Analyze the feedback and determine required changes to backlog items.

Feedback Types and Responses:
1. CLARIFICATION: User needs more detail
   → Add notes, expand description, add acceptance criteria

2. PRIORITY_CHANGE: User disagrees with priority
   → Adjust business value, recalculate priority score

3. NEW_REQUIREMENT: User identifies missing feature
   → Create new backlog item with extracted details

4. SCOPE_CHANGE: User wants to modify existing item
   → Update item description, adjust complexity

5. DEPENDENCY: User points out missing dependency
   → Add dependency user stories

6. REJECTION: User rejects the item entirely
   → Mark for removal or archive

Guidelines
1. New backlog item should have:
- title
- description
- business_value (1-10)
- technical_complexity (1-10)
- epic
- dependencies (list of user stories with ID that this item depends on, at least 1 user stories)
- priority_score
- priority (critical/high/medium/low/nice_to_have)
- acceptance_criteria (general acceptance criteria of user stories' list in dependencies)

RESPONSE FORMAT:
Return a JSON object with exactly this structure:
{{
    "feedback_type": [clarification|priority_change|new_requirement|scope_change|dependency|rejection],
    "affected_items": [list of backlog item ID affected],
    "changes": [
        {{
            "item_id": [Backlog item ID],
            "action": [update|create|delete],
            "updates": {{
                "field": "new value"
            }}
        }}
    ],
    "new_items": [
        {{
            "title": [Backlog item's title (clear and concise)],
            "description": [Backlog item's description (what, why, who)],
            "business_value": [Backlog item's Business Value (1-10)],
            "technical_complexity": [Backlog item's Technical Complexity (1-10)],
            "epic": [Backlog item's epic name],
            "dependencies": [Backlog item's Epic grouping (at least 1 user story)],
            "priority": [Backlog item's priority (critical/high/medium/low/nice_to_have)],
            "priority_score": [Backlog item's priority score (Calculation: Priority Score = Business Value / Technical Complexity)],
            "acceptance_criteria": [Backlog items's general acceptance criteria of user stories' list in dependencies]
        }}
    ],
    "rationale": [Explanation of changes made]
}}

Return ONLY the JSON object, no other text. Note that feedback_type MUST be one of the values: "clarification", "priority_change", "new_requirement", "scope_change", "dependency", "rejection".
""",
            "process_sprint_feedback": """You are processing user feedback on the Sprint Backlog.

Feedback Received:
{feedback}

Available Product Backlog Items (prioritized):
{prioritized_items}

Current Sprint Backlog Items:
{backlog_items}

Your Task:
Analyze the feedback and determine required changes to backlog items.

Feedback Types and Responses:
1. OVER_CAPACITY: Total points exceed team capacity
   → Remove lowest priority items until within capacity

2. UNDER_CAPACITY: Team has spare capacity
   → Add next highest priority validated items

3. DEPENDENCY_VIOLATION: Item in sprint has unmet product backlog items
   → Either add items from product backlog or remove item

4. GOAL_MISALIGNMENT: Items don't support sprint goal
   → Replace with better aligned items


RESPONSE FORMAT:
Return a JSON object with exactly this structure:
{{
    "feedback_type": [over_capacity|under_capacity|dependency_violation|goal_misalignment],
    "selected_items": [list of updated selected product backlog items with ID. If there is no changes, return list of original selected product backlog items],
    "total_points": [Total story points updated. If there is no change, return the original total story points],
    "sprint_goal_refined": [Return updated sprint goal. If there is no change, return the original refined sprint goal],
    "rationale": [Explanation of changes made]
}}

Return ONLY the JSON object, no other text. Note that feedback_type MUST be one of the values: "over_capacity", "under_capacity", "dependency_violation", "goal_misalignment".
""",
            "prioritize_backlog": """You are prioritizing the Product Backlog.

Current Backlog Items:
{backlog_items}

Dependency Graph:
{dependency_graph}

Your Task:
Prioritize these items using WSJF (Weighted Shortest Job First).

Calculation:
Priority Score = Business Value / Technical Complexity

Rules:
1. Higher score = higher priority
2. Items with dependencies must come after their dependencies
3. Consider critical path items for higher priority
4. Balance business urgency with technical sequencing

Output Format:
Return prioritized list with:
- item_id
- priority_score
- priority (critical/high/medium/low/nice_to_have)
- rationale (brief explanation)
""",
            "validate_backlog_item": """You are validating a backlog item.

Backlog Item:
{backlog_item}

Validation Criteria:
1. Clear, unambiguous title
2. Well-defined description
3. Business value is quantified
4. Acceptance criteria are specific and testable
5. Dependencies are identified
6. Item is independently valuable

Your Task:
Determine if this item is ready for sprint planning.

Output Format:
{{
    "is_valid": true/false,
    "validation_notes": ["note1", "note2"],
    "missing_elements": ["missing1", "missing2"],
    "suggested_improvements": ["suggestion1"]
}}
""",
            "generate_sprint_backlog": """You are generating a Sprint Backlog.

Available Items (prioritized):
{prioritized_items}

User Stories: 
{user_stories}

Sprint Context:
- Sprint Number: {sprint_number}
- Team Capacity: {capacity} story points
- Sprint Goal: {sprint_goal}

Your Task:
In each product backlog item, dependencies is list of user stories with ID that this item depends on. Select items for this sprint that:
1. Fit within capacity
2. Align with sprint goal
3. Have all dependencies satisfied
4. Are validated and ready

Rules:
- Take highest priority items first
- Don't exceed capacity
- Items must be validated

RESPONSE FORMAT:
{{
    "selected_items": [list of selected product backlog items with ID],
    "total_points": [Total story points],
    "sprint_goal_refined": [Refined sprint goal],
    "rationale": [Explanation of selected product backlog items]
}}

Return ONLY the JSON object, no other text.
""",
        }

        base_prompt = action_prompts.get(action, f"Action: {action}")
        if context:
            try:
                return base_prompt.format(**context)
            except KeyError as e:
                logger.warning(f"Missing context key: {e}")
                return base_prompt
        return base_prompt

    async def initialize_product_backlog(self):

        artifacts = self.artifact_pool.query_artifacts_by_type(
            artifact_type=ArtifactType.INTERVIEW_RECORD
        )
        func_reqs, non_func_reqs, user_stories = [], [], []
        for artifact in artifacts:
            func_req_artifact = artifact.content.get("functional_requirements", [])
            func_req_artifact = [
                {
                    "text": func_req.get("text", ""),
                    "measurable_criteria": func_req.get("measurable_criteria", []),
                    "acceptance_criteria": func_req.get("acceptance_criteria", []),
                    "priority": func_req.get("priority", "medium"),
                    "confidence": func_req.get("confidence", 0.7),
                }
                for func_req in func_req_artifact
            ]
            func_reqs.extend(func_req_artifact)
            non_func_req_artifact = artifact.content.get(
                "non_functional_requirements", []
            )
            non_func_req_artifact = [
                {
                    "text": func_req.get("text", ""),
                    "category": func_req.get("category", ""),
                    "measurable_criteria": func_req.get("measurable_criteria", []),
                    "acceptance_criteria": func_req.get("acceptance_criteria", []),
                    "priority": func_req.get("priority", "medium"),
                    "confidence": func_req.get("confidence", 0.7),
                }
                for func_req in non_func_req_artifact
            ]
            non_func_reqs.extend(non_func_req_artifact)

            user_stories_artifact = artifact.content.get("raw_user_stories", [])
            user_stories_artifact = [
                {
                    "id": user_story.get("id", ""),
                    "role": user_story.get("role", ""),
                    "goal": user_story.get("goal", ""),
                    "benefit": user_story.get("benefit", ""),
                    "text": user_story.get("text", ""),
                    "priority": user_story.get("priority", ""),
                    "confidence": user_story.get("confidence", ""),
                }
                for user_story in user_stories_artifact
            ]
            user_stories.extend(user_stories_artifact)

        extraction_prompt = self._get_action_prompt(
            "synthesize_backlog",
            context={
                "user_stories": json.dumps(user_stories),
                "functional_reqs": json.dumps(func_reqs),
                "nfr_reqs": json.dumps(non_func_reqs),
            },
        )

        cot_result = await asyncio.to_thread(
            self.generate_with_cot,
            prompt=extraction_prompt,
            context={"action": "Generate Product Backlog"},
            reasoning_template="backlog_generate",
            profile_prompt=self.profile_prompt,
        )

        response_text = cot_result["response"].strip()
        logger.info(f"[Sprint Manager]: {response_text}")

        json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
        if json_match:
            extracted_data = json.loads(json_match.group())
        else:
            logger.warning("No JSON found in extraction response, using empty data")
            extracted_data = []

        # Create artifact metadata
        metadata = ArtifactMetadata(
            tags=["product_backlog", "requirements", "elicitation", "user stories"],
            source_agent="sprint_manager",
            related_artifacts=[],
            quality_score=None,
            review_comments=[],
            custom_properties={},
        )

        product_backlog_lst = []
        for item in extracted_data:
            backlog_item = {
                "id": str(uuid.uuid4()),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "business_value": item.get("business_value", 1),
                "technical_complexity": item.get("technical_complexity", 1),
                "epic": item.get("epic", ""),
                "priority_score": item.get("priority_score", 5),
                "priority": item.get("priority", "medium"),
                "dependencies": item.get("dependencies", []),
                "acceptance_criteria": item.get("acceptance_criteria", []),
                "extracted_at": datetime.now().isoformat(),
            }
            product_backlog_lst.append(backlog_item)

        artifact_content = {"product_backlog_items": product_backlog_lst}

        artifact = Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.PRODUCT_BACKLOG,
            content=artifact_content,
            metadata=metadata,
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.UNDER_REVIEW,
        )

        self.artifact_pool.store_artifact(artifact, self.name)

        return artifact

    async def process_product_backlog_feedback(self, product_backlog: Dict[str, Any]):

        feedback_user = []
        if self.human_queue:
            await self.human_queue.put("START")
            await asyncio.sleep(1)

        while True and self.human_queue:
            msg = await self.human_queue.get()

            if msg == "STOP":
                print("Receiver terminating.")
                break
            elif msg != "START":
                print(f"Received: {msg}")
                feedback_user.append(msg)
                tmp_product_backlogs = product_backlog.copy()
                for tmp_backlog in tmp_product_backlogs.get(
                    "product_backlog_items", []
                ):
                    tmp_backlog.pop("extracted_at", None)

                action_prompt = self._get_action_prompt(
                    "process_feedback",
                    context={
                        "feedback": msg,
                        "backlog_items": json.dumps(
                            tmp_product_backlogs.get("product_backlog_items", [])
                        ),
                    },
                )
                cot_result = await asyncio.to_thread(
                    self.generate_with_cot,
                    prompt=action_prompt,
                    context={"action": "Process Feedback to Product Backlog"},
                    reasoning_template="backlog_feedback",
                    profile_prompt=self.profile_prompt,
                )
                response_text = cot_result["response"].strip()

                logger.info(f"[Sprint Manager]: {response_text}")

                json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if json_match:
                    extracted_data = json.loads(json_match.group())
                else:
                    logger.warning(
                        "No JSON found in extraction response, using empty data"
                    )
                    extracted_data = {
                        "feedback_type": "",
                        "affected_items": [],
                        "changes": [],
                        "new_items": [],
                        "rationale": "",
                    }

                for changed_item in extracted_data.get("changes", []):
                    for idx, prod_backlog in enumerate(
                        product_backlog.get("product_backlog_items", [])
                    ):
                        if prod_backlog.get("id") == changed_item.get("item_id"):
                            if changed_item.get("action", "") == "delete":
                                product_backlog.get("product_backlog_items", []).pop(
                                    idx
                                )
                            else:
                                for k, v in changed_item.get("updates", {}).items():
                                    prod_backlog[k] = v
                            break

                for item in extracted_data.get("new_items", []):
                    backlog_item = {
                        "id": str(uuid.uuid4()),
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                        "business_value": item.get("business_value", 1),
                        "technical_complexity": item.get("technical_complexity", 1),
                        "epic": item.get("epic", ""),
                        "priority_score": item.get("priority_score", 5),
                        "priority": item.get("priority", "medium"),
                        "dependencies": item.get("dependencies", []),
                        "acceptance_criteria": item.get("acceptance_criteria", []),
                        "extracted_at": datetime.now().isoformat(),
                    }
                    product_backlog.get("product_backlog_items", []).append(
                        backlog_item
                    )
                # logger.info(f"New product backlog artifact: {product_backlog}")

            self.human_queue.task_done()

        return feedback_user

    async def initialize_sprint_backlog(self, product_backlog: Artifact):

        artifacts = self.artifact_pool.query_artifacts_by_type(
            artifact_type=ArtifactType.INTERVIEW_RECORD
        )
        user_stories = []
        for artifact in artifacts:

            user_stories_artifact = artifact.content.get("raw_user_stories", [])
            user_stories_artifact = [
                {
                    "id": user_story.get("id", ""),
                    "role": user_story.get("role", ""),
                    "goal": user_story.get("goal", ""),
                    "benefit": user_story.get("benefit", ""),
                    "text": user_story.get("text", ""),
                    "priority": user_story.get("priority", ""),
                    "confidence": user_story.get("confidence", ""),
                }
                for user_story in user_stories_artifact
            ]
            user_stories.extend(user_stories_artifact)

        tmp_product_backlogs = product_backlog.content.copy()
        for tmp_backlog in tmp_product_backlogs.get("product_backlog_items", []):
            tmp_backlog.pop("extracted_at", None)

        extraction_prompt = self._get_action_prompt(
            "generate_sprint_backlog",
            context={
                "prioritized_items": json.dumps(
                    tmp_product_backlogs.get("product_backlog_items", [])[-6:]
                ),
                "sprint_number": 1,
                "sprint_goal": "Complete high-priority items",
                "capacity": 10,
                "user_stories": json.dumps(user_stories),
            },
        )

        cot_result = await asyncio.to_thread(
            self.generate_with_cot,
            prompt=extraction_prompt,
            context={"action": "Generate Sprint Backlog"},
            reasoning_template="sprint_generate",
            profile_prompt=self.profile_prompt,
        )
        response_text = cot_result["response"].strip()
        logger.info(f"[Sprint Manager]: {response_text}")

        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            extracted_data = json.loads(json_match.group())
        else:
            logger.warning("No JSON found in extraction response, using empty data")
            extracted_data = {}

        metadata = ArtifactMetadata(
            tags=["product_backlog", "requirements", "elicitation", "sprint_backlog"],
            source_agent="sprint_manager",
            related_artifacts=[],
            quality_score=None,
            review_comments=[],
            custom_properties={},
        )

        artifact_content = {
            "sprint_number": 1,
            "sprint_goal": extracted_data.get(
                "sprint_goal_refined", "Complete high-priority items"
            ),
            "capacity": 10,
            "selected_items": [
                items.get("id")
                for items in extracted_data.get("selected_items", [])
                if items.get("id")
            ],
            "total_points": extracted_data.get("total_points", 0),
        }

        artifact = Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.SPRINT_BACKLOG,
            content=artifact_content,
            metadata=metadata,
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.UNDER_REVIEW,
        )
        self.artifact_pool.store_artifact(artifact, self.name)

        return artifact

    async def process_sprint_backlog_feedback(
        self, sprint_backlog: Artifact, product_backlog: Artifact
    ):

        feedback_user = []
        if self.human_queue:
            await self.human_queue.put("START")
            await asyncio.sleep(1)

        while True and self.human_queue:
            msg = await self.human_queue.get()

            if msg == "STOP":
                print("Receiver terminating.")
                break
            elif msg != "START":
                print(f"Received: {msg}")
                feedback_user.append(msg)
                tmp_product_backlogs = product_backlog.content.copy()
                for tmp_backlog in tmp_product_backlogs.get(
                    "product_backlog_items", []
                ):
                    tmp_backlog.pop("extracted_at", None)

                action_prompt = self._get_action_prompt(
                    "process_sprint_feedback",
                    context={
                        "feedback": msg,
                        "prioritized_items": json.dumps(
                            tmp_product_backlogs.get("product_backlog_items", [])[-6:]
                        ),
                        "backlog_items": json.dumps(sprint_backlog.content),
                    },
                )
                cot_result = await asyncio.to_thread(
                    self.generate_with_cot,
                    prompt=action_prompt,
                    context={"action": "Process Feedback to Sprint Backlog"},
                    reasoning_template="sprint_backlog_feedback",
                    profile_prompt=self.profile_prompt,
                )
                response_text = cot_result["response"].strip()

                logger.info(f"[Sprint Manager]: {response_text}")

                json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if json_match:
                    extracted_data = json.loads(json_match.group())
                else:
                    logger.warning(
                        "No JSON found in extraction response, using empty data"
                    )
                    extracted_data = {}

                selected_items = []

                for items in extracted_data.get("selected_items", []):
                    if isinstance(items, str):
                        selected_items.append(items)
                    elif isinstance(items, dict) and items.get("id"):
                        selected_items.append(items.get("id"))

                sprint_backlog.content = {
                    "sprint_number": 1,
                    "sprint_goal": extracted_data.get(
                        "sprint_goal_refined", "Complete high-priority items"
                    ),
                    "capacity": 10,
                    "selected_items": selected_items,
                    "total_points": extracted_data.get("total_points", 0),
                }

                # logger.info(f"New sprint backlog artifact: {sprint_backlog.content}")

            self.human_queue.task_done()

        return feedback_user

    # ==================== TASK PROCESSING ====================

    async def process(
        self,
        session: Any,
        review_point_id: Any,
    ) -> Dict[str, Any]:
        """
        Process tasks assigned by the coordinator.
        """

        from ..orchestrator.orchestrator import ProcessPhase

        logger.info(
            f"Sprint Manager {self.agent_id} processing session: {session.current_phase.value}"
        )
        if (
            session.current_phase == ProcessPhase.INTERVIEW_REVIEW
            and self.artifact_pool
        ):
            product_backlog = self.artifact_pool.query_artifacts_by_type(
                artifact_type=ArtifactType.PRODUCT_BACKLOG
            )
            if not product_backlog:
                product_backlog = await self.initialize_product_backlog()
            else:
                product_backlog = product_backlog[0]

            review_comments = await self.process_product_backlog_feedback(
                product_backlog.content
            )
            product_backlog.metadata.review_comments = review_comments
            product_backlog.status = ArtifactStatus.APPROVED

            self.artifact_pool.store_artifact(product_backlog, self.name)

            sprint_backlog = self.artifact_pool.query_artifacts_by_type(
                artifact_type=ArtifactType.SPRINT_BACKLOG
            )
            if not sprint_backlog:
                sprint_backlog = await self.initialize_sprint_backlog(product_backlog)
            else:
                sprint_backlog = sprint_backlog[0]

            review_comments_sprint = await self.process_sprint_backlog_feedback(
                sprint_backlog, product_backlog
            )
            sprint_backlog.metadata.review_comments = review_comments_sprint
            review_comments.extend(review_comments_sprint)
            sprint_backlog.status = ArtifactStatus.APPROVED

            self.artifact_pool.store_artifact(sprint_backlog, self.name)

        return {
            "status": "completed",
            "agent": self.agent_id,
        }
