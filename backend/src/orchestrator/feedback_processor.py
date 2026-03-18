"""
Feedback processing and correction mechanism for the iReDev framework.

This module handles the parsing, classification, and automated correction
of human feedback to improve artifacts and continue the development process.
"""

import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Tuple

from ..agent.communication import CommunicationProtocol, Message, MessageType
from ..artifact.events import EventBus, Event, EventType
from ..artifact.pool import ArtifactPool
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus, ArtifactMetadata
from .human_in_loop import HumanFeedback, FeedbackType

logger = logging.getLogger(__name__)


class FeedbackAction(Enum):
    """Actions that can be taken based on feedback."""

    APPROVE = "approve"
    MODIFY = "modify"
    REGENERATE = "regenerate"
    ADD_CONTENT = "add_content"
    REMOVE_CONTENT = "remove_content"
    CLARIFY = "clarify"
    ESCALATE = "escalate"
    REJECT = "reject"


class FeedbackSeverity(Enum):
    """Severity levels for feedback."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FeedbackAnalysis:
    """Analysis results of human feedback."""

    feedback_id: str
    primary_action: FeedbackAction
    secondary_actions: List[FeedbackAction] = field(default_factory=list)
    severity: FeedbackSeverity = FeedbackSeverity.MEDIUM
    confidence: float = 0.0  # 0.0 to 1.0
    specific_issues: List[str] = field(default_factory=list)
    suggested_changes: List[str] = field(default_factory=list)
    affected_sections: List[str] = field(default_factory=list)
    requires_agent_action: bool = True
    estimated_effort: int = 1  # 1-5 scale
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert analysis to dictionary."""
        return {
            "feedback_id": self.feedback_id,
            "primary_action": self.primary_action.value,
            "secondary_actions": [a.value for a in self.secondary_actions],
            "severity": self.severity.value,
            "confidence": self.confidence,
            "specific_issues": self.specific_issues,
            "suggested_changes": self.suggested_changes,
            "affected_sections": self.affected_sections,
            "requires_agent_action": self.requires_agent_action,
            "estimated_effort": self.estimated_effort,
            "metadata": self.metadata,
        }


@dataclass
class CorrectionTask:
    """Represents a correction task based on feedback."""

    id: str
    feedback_id: str
    artifact_id: str
    agent_name: str
    action: FeedbackAction
    description: str
    instructions: List[str]
    priority: int = 1  # 1-5 scale
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, in_progress, completed, failed
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure ID is set if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert correction task to dictionary."""
        return {
            "id": self.id,
            "feedback_id": self.feedback_id,
            "artifact_id": self.artifact_id,
            "agent_name": self.agent_name,
            "action": self.action.value,
            "description": self.description,
            "instructions": self.instructions,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "status": self.status,
            "result": self.result,
            "metadata": self.metadata,
        }


class FeedbackProcessor:
    """
    Processes human feedback and generates correction tasks.

    Analyzes feedback content, determines appropriate actions,
    and coordinates with agents to implement corrections.
    """

    def __init__(
        self,
        artifact_pool: ArtifactPool,
        event_bus: EventBus,
        communication_protocol: Optional[CommunicationProtocol] = None,
    ):
        """
        Initialize the feedback processor.

        Args:
            artifact_pool: Shared artifact pool
            event_bus: Event bus for communication
            communication_protocol: Agent communication protocol
        """
        self.artifact_pool = artifact_pool
        self.event_bus = event_bus
        self.communication_protocol = communication_protocol

        # Processing state
        self.feedback_analyses: Dict[str, FeedbackAnalysis] = {}
        self.correction_tasks: Dict[str, CorrectionTask] = {}
        self.processing_history: List[Dict[str, Any]] = []

        # State management
        self._lock = threading.RLock()

        # Configuration
        self.max_correction_iterations = 3
        self.auto_approve_threshold = 0.9  # Confidence threshold for auto-approval

        # Agent mappings for different artifact types
        self.artifact_agent_map = {
            ArtifactType.INTERVIEW_RECORD: "interviewer",
            ArtifactType.USER_PERSONAS: "enduser",
            ArtifactType.USER_SCENARIOS: "enduser",
            ArtifactType.DEPLOYMENT_CONSTRAINTS: "deployer",
            ArtifactType.USER_REQUIREMENTS_LIST: "analyst",
            ArtifactType.REQUIREMENT_MODEL: "analyst",
            ArtifactType.SRS_DOCUMENT: "archivist",
            ArtifactType.REVIEW_REPORT: "reviewer",
        }

        # Feedback patterns for analysis
        self.feedback_patterns = {
            FeedbackAction.APPROVE: [
                r"(?i)\b(approve|accept|good|correct|fine|ok|okay)\b",
                r"(?i)\b(looks good|well done|satisfactory)\b",
            ],
            FeedbackAction.MODIFY: [
                r"(?i)\b(modify|change|update|revise|edit|improve)\b",
                r"(?i)\b(needs? (to be )?changed?|should be modified)\b",
            ],
            FeedbackAction.REGENERATE: [
                r"(?i)\b(regenerate|recreate|redo|start over|rewrite)\b",
                r"(?i)\b(completely wrong|totally incorrect)\b",
            ],
            FeedbackAction.ADD_CONTENT: [
                r"(?i)\b(add|include|missing|need to add|should include)\b",
                r"(?i)\b(lacks?|absent|not mentioned|forgot to)\b",
            ],
            FeedbackAction.REMOVE_CONTENT: [
                r"(?i)\b(remove|delete|unnecessary|not needed|redundant)\b",
                r"(?i)\b(too much|excessive|should not include)\b",
            ],
            FeedbackAction.CLARIFY: [
                r"(?i)\b(clarify|unclear|confusing|ambiguous|vague)\b",
                r"(?i)\b(not clear|hard to understand|needs explanation)\b",
            ],
        }

        # Callbacks
        self.on_feedback_processed: Optional[Callable[[FeedbackAnalysis], None]] = None
        self.on_correction_created: Optional[Callable[[CorrectionTask], None]] = None
        self.on_correction_completed: Optional[Callable[[CorrectionTask], None]] = None

        logger.info("Initialized FeedbackProcessor")

    def process_feedback(
        self, feedback: HumanFeedback, artifact: Artifact
    ) -> FeedbackAnalysis:
        """
        Process human feedback and generate analysis.

        Args:
            feedback: Human feedback to process
            artifact: Artifact being reviewed

        Returns:
            FeedbackAnalysis: Analysis results
        """
        with self._lock:
            logger.info(f"Processing feedback {feedback.id} for artifact {artifact.id}")

            # Analyze feedback content
            analysis = self._analyze_feedback_content(feedback, artifact)

            # Store analysis
            self.feedback_analyses[feedback.id] = analysis

            # Add to processing history
            self.processing_history.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "feedback_id": feedback.id,
                    "artifact_id": artifact.id,
                    "analysis": analysis.to_dict(),
                }
            )

            # Callback
            if self.on_feedback_processed:
                self.on_feedback_processed(analysis)

            logger.info(
                f"Analyzed feedback {feedback.id}: {analysis.primary_action.value}"
            )

            return analysis

    def create_correction_tasks(
        self, analysis: FeedbackAnalysis, session_id: str
    ) -> List[CorrectionTask]:
        """
        Create correction tasks based on feedback analysis.

        Args:
            analysis: Feedback analysis
            session_id: Session identifier

        Returns:
            List of correction tasks
        """
        with self._lock:
            tasks = []

            # Get the artifact
            artifact = self._get_artifact_from_analysis(analysis)
            if not artifact:
                logger.error(f"Artifact not found for analysis {analysis.feedback_id}")
                return tasks

            # Determine responsible agent
            agent_name = self.artifact_agent_map.get(artifact.type)
            if not agent_name:
                logger.error(f"No agent mapped for artifact type {artifact.type.value}")
                return tasks

            # Create primary correction task
            primary_task = self._create_correction_task(
                analysis, artifact, agent_name, analysis.primary_action, session_id
            )
            tasks.append(primary_task)

            # Create secondary tasks if needed
            for secondary_action in analysis.secondary_actions:
                secondary_task = self._create_correction_task(
                    analysis,
                    artifact,
                    agent_name,
                    secondary_action,
                    session_id,
                    priority=max(1, primary_task.priority - 1),
                )
                tasks.append(secondary_task)

            # Store tasks
            for task in tasks:
                self.correction_tasks[task.id] = task

                # Callback
                if self.on_correction_created:
                    self.on_correction_created(task)

            logger.info(
                f"Created {len(tasks)} correction tasks for feedback {analysis.feedback_id}"
            )

            return tasks

    def execute_correction_task(self, task_id: str) -> bool:
        """
        Execute a correction task.

        Args:
            task_id: Correction task identifier

        Returns:
            True if task executed successfully
        """
        with self._lock:
            task = self.correction_tasks.get(task_id)
            if not task:
                logger.error(f"Correction task {task_id} not found")
                return False

            if task.status != "pending":
                logger.warning(f"Correction task {task_id} is not pending")
                return False

            task.status = "in_progress"

            try:
                # Execute the correction based on action type
                success = self._execute_action(task)

                if success:
                    task.status = "completed"
                    task.completed_at = datetime.now()

                    # Callback
                    if self.on_correction_completed:
                        self.on_correction_completed(task)

                    logger.info(f"Completed correction task {task_id}")
                else:
                    task.status = "failed"
                    logger.error(f"Failed to execute correction task {task_id}")

                return success

            except Exception as e:
                task.status = "failed"
                task.metadata["error"] = str(e)
                logger.error(f"Error executing correction task {task_id}: {e}")
                return False

    def validate_correction(
        self, task_id: str, validation_criteria: Dict[str, Any]
    ) -> bool:
        """
        Validate the results of a correction task.

        Args:
            task_id: Correction task identifier
            validation_criteria: Criteria for validation

        Returns:
            True if correction is valid
        """
        with self._lock:
            task = self.correction_tasks.get(task_id)
            if not task or task.status != "completed":
                return False

            # Get the updated artifact
            artifact = self.artifact_pool.get_artifact(task.artifact_id)

            ## Arifact mockup
            artifact = Artifact(
                id=task.artifact_id,
                type=ArtifactType.INTERVIEW_RECORD,
                content={"Subject": "PPL"},
                metadata=ArtifactMetadata(source_agent="interviewer"),
                version="1.0",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                created_by="interviewer",
                status=ArtifactStatus.APPROVED,
            )
            if not artifact:
                return False

            # Perform validation based on criteria
            validation_result = self._validate_artifact_changes(
                artifact, task, validation_criteria
            )

            # Store validation result
            task.metadata["validation_result"] = validation_result

            logger.info(f"Validated correction task {task_id}: {validation_result}")

            return validation_result.get("is_valid", False)

    def get_correction_status(self, feedback_id: str) -> Dict[str, Any]:
        """
        Get the status of corrections for a feedback.

        Args:
            feedback_id: Feedback identifier

        Returns:
            Dictionary with correction status
        """
        with self._lock:
            # Find tasks for this feedback
            tasks = [
                task
                for task in self.correction_tasks.values()
                if task.feedback_id == feedback_id
            ]

            if not tasks:
                return {"status": "no_tasks", "tasks": []}

            # Calculate overall status
            pending_count = len([t for t in tasks if t.status == "pending"])
            in_progress_count = len([t for t in tasks if t.status == "in_progress"])
            completed_count = len([t for t in tasks if t.status == "completed"])
            failed_count = len([t for t in tasks if t.status == "failed"])

            overall_status = "pending"
            if failed_count > 0:
                overall_status = "failed"
            elif completed_count == len(tasks):
                overall_status = "completed"
            elif in_progress_count > 0:
                overall_status = "in_progress"

            return {
                "status": overall_status,
                "total_tasks": len(tasks),
                "pending": pending_count,
                "in_progress": in_progress_count,
                "completed": completed_count,
                "failed": failed_count,
                "tasks": [task.to_dict() for task in tasks],
            }

    def _analyze_feedback_content(
        self, feedback: HumanFeedback, artifact: Artifact
    ) -> FeedbackAnalysis:
        """Analyze feedback content to determine actions."""
        content = feedback.content.lower()

        # Determine primary action based on feedback type and content
        if feedback.feedback_type == FeedbackType.APPROVAL:
            primary_action = FeedbackAction.APPROVE
            severity = FeedbackSeverity.LOW
        elif feedback.feedback_type == FeedbackType.REJECTION:
            primary_action = FeedbackAction.REGENERATE
            severity = FeedbackSeverity.HIGH
        else:
            # Analyze content using patterns
            primary_action = self._match_feedback_patterns(content)
            severity = self._determine_severity(content, feedback)

        # Extract specific issues and suggestions
        specific_issues = self._extract_issues(content)
        suggested_changes = feedback.suggestions or self._extract_suggestions(content)
        affected_sections = self._identify_affected_sections(content, artifact)

        # Determine secondary actions
        secondary_actions = self._determine_secondary_actions(content, primary_action)

        # Calculate confidence based on feedback clarity and specificity
        confidence = self._calculate_confidence(
            feedback, specific_issues, suggested_changes
        )

        return FeedbackAnalysis(
            feedback_id=feedback.id,
            primary_action=primary_action,
            secondary_actions=secondary_actions,
            severity=severity,
            confidence=confidence,
            specific_issues=specific_issues,
            suggested_changes=suggested_changes,
            affected_sections=affected_sections,
            requires_agent_action=primary_action != FeedbackAction.APPROVE,
            estimated_effort=self._estimate_effort(
                primary_action, len(specific_issues)
            ),
            metadata={"artifact_id": artifact.id},
        )

    def _match_feedback_patterns(self, content: str) -> FeedbackAction:
        """Match feedback content against patterns to determine action."""
        action_scores = {}

        for action, patterns in self.feedback_patterns.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, content))
                score += matches
            action_scores[action] = score

        # Return action with highest score, default to MODIFY
        if action_scores:
            best_action = max(action_scores, key=action_scores.get)
            if action_scores[best_action] > 0:
                return best_action

        return FeedbackAction.MODIFY

    def _determine_severity(
        self, content: str, feedback: HumanFeedback
    ) -> FeedbackSeverity:
        """Determine severity based on content and feedback type."""
        if feedback.feedback_type == FeedbackType.REJECTION:
            return FeedbackSeverity.CRITICAL

        # Check for severity indicators
        critical_words = ["critical", "major", "serious", "urgent", "important"]
        high_words = ["significant", "substantial", "considerable"]
        low_words = ["minor", "small", "trivial", "cosmetic"]

        content_lower = content.lower()

        if any(word in content_lower for word in critical_words):
            return FeedbackSeverity.CRITICAL
        elif any(word in content_lower for word in high_words):
            return FeedbackSeverity.HIGH
        elif any(word in content_lower for word in low_words):
            return FeedbackSeverity.LOW

        return FeedbackSeverity.MEDIUM

    def _extract_issues(self, content: str) -> List[str]:
        """Extract specific issues from feedback content."""
        issues = []

        # Look for issue indicators
        issue_patterns = [
            r"(?i)issue:?\s*(.+?)(?:\.|$)",
            r"(?i)problem:?\s*(.+?)(?:\.|$)",
            r"(?i)error:?\s*(.+?)(?:\.|$)",
            r"(?i)incorrect:?\s*(.+?)(?:\.|$)",
            r"(?i)missing:?\s*(.+?)(?:\.|$)",
        ]

        for pattern in issue_patterns:
            matches = re.findall(pattern, content)
            issues.extend([match.strip() for match in matches])

        return issues[:10]  # Limit to 10 issues

    def _extract_suggestions(self, content: str) -> List[str]:
        """Extract suggestions from feedback content."""
        suggestions = []

        # Look for suggestion indicators
        suggestion_patterns = [
            r"(?i)suggest:?\s*(.+?)(?:\.|$)",
            r"(?i)recommend:?\s*(.+?)(?:\.|$)",
            r"(?i)should:?\s*(.+?)(?:\.|$)",
            r"(?i)could:?\s*(.+?)(?:\.|$)",
            r"(?i)try:?\s*(.+?)(?:\.|$)",
        ]

        for pattern in suggestion_patterns:
            matches = re.findall(pattern, content)
            suggestions.extend([match.strip() for match in matches])

        return suggestions[:10]  # Limit to 10 suggestions

    def _identify_affected_sections(
        self, content: str, artifact: Artifact
    ) -> List[str]:
        """Identify which sections of the artifact are affected."""
        sections = []

        # Common section names
        section_patterns = [
            r"(?i)\b(introduction|overview|summary)\b",
            r"(?i)\b(requirements?|specs?|specifications?)\b",
            r"(?i)\b(design|architecture|structure)\b",
            r"(?i)\b(implementation|development)\b",
            r"(?i)\b(testing|validation|verification)\b",
            r"(?i)\b(conclusion|recommendations?)\b",
        ]

        for pattern in section_patterns:
            if re.search(pattern, content):
                match = re.search(pattern, content)
                if match:
                    sections.append(match.group(1).lower())

        return list(set(sections))  # Remove duplicates

    def _determine_secondary_actions(
        self, content: str, primary_action: FeedbackAction
    ) -> List[FeedbackAction]:
        """Determine secondary actions based on content analysis."""
        secondary_actions = []

        # If primary action is modify, check for specific types of modifications
        if primary_action == FeedbackAction.MODIFY:
            if re.search(r"(?i)\b(add|include|missing)\b", content):
                secondary_actions.append(FeedbackAction.ADD_CONTENT)
            if re.search(r"(?i)\b(remove|delete|unnecessary)\b", content):
                secondary_actions.append(FeedbackAction.REMOVE_CONTENT)
            if re.search(r"(?i)\b(clarify|unclear|confusing)\b", content):
                secondary_actions.append(FeedbackAction.CLARIFY)

        return secondary_actions

    def _calculate_confidence(
        self,
        feedback: HumanFeedback,
        specific_issues: List[str],
        suggested_changes: List[str],
    ) -> float:
        """Calculate confidence score for the analysis."""
        confidence = 0.5  # Base confidence

        # Increase confidence based on feedback specificity
        if feedback.confidence_score:
            confidence += feedback.confidence_score * 0.3

        if specific_issues:
            confidence += min(0.2, len(specific_issues) * 0.05)

        if suggested_changes:
            confidence += min(0.2, len(suggested_changes) * 0.05)

        # Increase confidence for clear feedback types
        if feedback.feedback_type in [FeedbackType.APPROVAL, FeedbackType.REJECTION]:
            confidence += 0.2

        return min(1.0, confidence)

    def _estimate_effort(self, action: FeedbackAction, issue_count: int) -> int:
        """Estimate effort required for correction (1-5 scale)."""
        base_effort = {
            FeedbackAction.APPROVE: 1,
            FeedbackAction.MODIFY: 2,
            FeedbackAction.ADD_CONTENT: 2,
            FeedbackAction.REMOVE_CONTENT: 1,
            FeedbackAction.CLARIFY: 2,
            FeedbackAction.REGENERATE: 4,
            FeedbackAction.ESCALATE: 3,
            FeedbackAction.REJECT: 5,
        }

        effort = base_effort.get(action, 2)

        # Adjust based on number of issues
        if issue_count > 5:
            effort = min(5, effort + 2)
        elif issue_count > 2:
            effort = min(5, effort + 1)

        return effort

    def _create_correction_task(
        self,
        analysis: FeedbackAnalysis,
        artifact: Artifact,
        agent_name: str,
        action: FeedbackAction,
        session_id: str,
        priority: Optional[int] = None,
    ) -> CorrectionTask:
        """Create a correction task."""
        if priority is None:
            priority = 5 if analysis.severity == FeedbackSeverity.CRITICAL else 3

        # Generate instructions based on action and analysis
        instructions = self._generate_instructions(action, analysis, artifact)

        return CorrectionTask(
            id=str(uuid.uuid4()),
            feedback_id=analysis.feedback_id,
            artifact_id=artifact.id,
            agent_name=agent_name,
            action=action,
            description=f"{action.value.replace('_', ' ').title()} {artifact.type.value}",
            instructions=instructions,
            priority=priority,
            metadata={
                "session_id": session_id,
                "artifact_type": artifact.type.value,
                "severity": analysis.severity.value,
                "confidence": analysis.confidence,
            },
        )

    def _generate_instructions(
        self, action: FeedbackAction, analysis: FeedbackAnalysis, artifact: Artifact
    ) -> List[str]:
        """Generate specific instructions for a correction action."""
        instructions = []

        if action == FeedbackAction.MODIFY:
            instructions.append(
                "Review the feedback and modify the artifact accordingly"
            )
            if analysis.specific_issues:
                instructions.append(
                    f"Address these specific issues: {', '.join(analysis.specific_issues)}"
                )
            if analysis.suggested_changes:
                instructions.append(
                    f"Consider these suggestions: {', '.join(analysis.suggested_changes)}"
                )

        elif action == FeedbackAction.ADD_CONTENT:
            instructions.append("Add missing content to the artifact")
            if analysis.suggested_changes:
                instructions.append(
                    f"Add the following: {', '.join(analysis.suggested_changes)}"
                )

        elif action == FeedbackAction.REMOVE_CONTENT:
            instructions.append("Remove unnecessary or incorrect content")
            if analysis.specific_issues:
                instructions.append(f"Remove: {', '.join(analysis.specific_issues)}")

        elif action == FeedbackAction.CLARIFY:
            instructions.append("Clarify unclear or ambiguous content")
            if analysis.affected_sections:
                instructions.append(
                    f"Focus on these sections: {', '.join(analysis.affected_sections)}"
                )

        elif action == FeedbackAction.REGENERATE:
            instructions.append("Regenerate the artifact from scratch")
            instructions.append("Consider all previous feedback and requirements")

        return instructions

    def _execute_action(self, task: CorrectionTask) -> bool:
        """Execute a correction action."""
        try:
            # Send correction request to the responsible agent
            message = Message(
                id=str(uuid.uuid4()),
                type=MessageType.REQUEST,
                sender="feedback_processor",
                recipient=task.agent_name,
                payload={
                    "task_type": "correction",
                    "action": task.action.value,
                    "artifact_id": task.artifact_id,
                    "instructions": task.instructions,
                    "priority": task.priority,
                    "metadata": task.metadata,
                },
                timestamp=datetime.now(),
                session_id=task.metadata.get("session_id", ""),
            )

            # Send message through communication protocol
            success = None
            if self.communication_protocol:
                success = self.communication_protocol.send_message(
                    recipient=task.agent_name,
                    message_type=MessageType.REQUEST,
                    payload={
                        "task_type": "correction",
                        "action": task.action.value,
                        "artifact_id": task.artifact_id,
                        "instructions": task.instructions,
                        "priority": task.priority,
                        "metadata": task.metadata,
                    },
                )

            if success:
                task.result = {"message_sent": True, "message_id": message.id}
                return True

            return False

        except Exception as e:
            logger.error(f"Error executing correction action: {e}")
            return False

    def _validate_artifact_changes(
        self, artifact: Artifact, task: CorrectionTask, criteria: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate changes made to an artifact."""
        validation_result = {"is_valid": True, "issues": [], "score": 1.0}

        # Basic validation checks
        if not artifact.content:
            validation_result["is_valid"] = False
            validation_result["issues"].append("Artifact content is empty")
            validation_result["score"] = 0.0

        # Check if artifact status is appropriate
        if artifact.status not in [ArtifactStatus.DRAFT, ArtifactStatus.APPROVED]:
            validation_result["issues"].append(
                f"Unexpected artifact status: {artifact.status.value}"
            )

        # Additional validation based on criteria
        for criterion, expected_value in criteria.items():
            if criterion == "min_content_length":
                content_length = len(str(artifact.content))
                if content_length < expected_value:
                    validation_result["is_valid"] = False
                    validation_result["issues"].append(
                        f"Content too short: {content_length} < {expected_value}"
                    )
                    validation_result["score"] *= 0.8

        return validation_result

    def _get_artifact_from_analysis(
        self, analysis: FeedbackAnalysis
    ) -> Optional[Artifact]:
        """Get artifact from feedback analysis."""
        # This would need to be implemented based on how we track
        # which artifact the feedback is about
        # For now, we'll need to get this information from the feedback metadata
        # return None  # Placeholder

        artifact_id = analysis.metadata.get("artifact_id", "")

        # artifact = self.artifact_pool.get_artifact(artifact_id)

        ## Artifact mockup
        from .orchestrator import ArtifactMetadata

        artifact = Artifact(
            id=artifact_id,
            type=ArtifactType.INTERVIEW_RECORD,
            content={},
            metadata=ArtifactMetadata(source_agent="interviewer"),
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by="interviewer",
            status=ArtifactStatus.DRAFT,
        )
        if not artifact:
            return None
        return artifact
