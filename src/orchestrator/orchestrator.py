"""
Core orchestrator for the iReDev requirement development process.

This module implements the RequirementOrchestrator class that manages
the entire requirement development workflow, coordinates agents, and
handles human-in-the-loop interactions.
"""

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Set

from ..agent.coordination import AgentCoordinator, Task, TaskPriority, TaskStatus
from ..agent.communication import CommunicationProtocol, Message, MessageType
from ..agent.interviewer import InterviewerAgent
from ..agent.enduser import EndUserAgent
from ..artifact.events import EventBus, Event, EventType
from ..artifact.pool import ArtifactPool
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus, ArtifactMetadata
from ..config.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class ProcessPhase(Enum):
    """Phases of the requirement development process."""

    INITIALIZATION = "initialization"
    INTERVIEW = "interview"
    USER_MODELING = "user_modeling"
    DEPLOYMENT_ANALYSIS = "deployment_analysis"
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    URL_REVIEW = "url_review"  # User Requirements List review
    REQUIREMENT_MODELING = "requirement_modeling"
    MODEL_REVIEW = "model_review"
    SRS_GENERATION = "srs_generation"
    SRS_REVIEW = "srs_review"
    QUALITY_ASSURANCE = "quality_assurance"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessStatus(Enum):
    """Status of the requirement development process."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED_FOR_REVIEW = "paused_for_review"
    WAITING_FOR_FEEDBACK = "waiting_for_feedback"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ProjectConfig:
    """Configuration for a requirement development project."""

    project_name: str
    domain: str
    stakeholders: List[str]
    target_environment: str
    compliance_requirements: List[str] = field(default_factory=list)
    quality_standards: List[str] = field(default_factory=list)
    review_points: List[str] = field(
        default_factory=lambda: ["url_generation", "model_creation", "srs_generation"]
    )
    timeout_minutes: int = 1440  # 24 hours default
    max_iterations: int = 3
    custom_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessSession:
    """Represents a requirement development session."""

    session_id: str
    project_config: ProjectConfig
    current_phase: ProcessPhase
    status: ProcessStatus
    created_at: datetime
    updated_at: datetime
    created_by: str
    progress: float = 0.0  # 0.0 to 1.0
    artifacts: List[str] = field(default_factory=list)  # Artifact IDs
    active_agents: Set[str] = field(default_factory=set)
    review_history: List[Dict[str, Any]] = field(default_factory=list)
    error_log: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # HITL specific fields
    current_review_point: Optional[str] = None

    def __post_init__(self):
        """Ensure session ID is set if not provided."""
        if not self.session_id:
            self.session_id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary."""
        return {
            "session_id": self.session_id,
            "project_config": {
                "project_name": self.project_config.project_name,
                "domain": self.project_config.domain,
                "stakeholders": self.project_config.stakeholders,
                "target_environment": self.project_config.target_environment,
                "compliance_requirements": self.project_config.compliance_requirements,
                "quality_standards": self.project_config.quality_standards,
                "review_points": self.project_config.review_points,
                "timeout_minutes": self.project_config.timeout_minutes,
                "max_iterations": self.project_config.max_iterations,
                "custom_config": self.project_config.custom_config,
            },
            "current_phase": self.current_phase.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "progress": self.progress,
            "artifacts": self.artifacts,
            "active_agents": list(self.active_agents),
            "review_history": self.review_history,
            "error_log": self.error_log,
            "metadata": self.metadata,
            "current_review_point": self.current_review_point,
        }


class RequirementOrchestrator:
    """
    Central orchestrator for the requirement development process.

    Manages the workflow, coordinates agents, handles human-in-the-loop
    interactions, and maintains process state.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        artifact_pool: ArtifactPool,
        event_bus: EventBus,
        human_review_manager=None,
    ):
        """
        Initialize the requirement orchestrator.

        Args:
            config_manager: Configuration manager
            artifact_pool: Shared artifact pool
            event_bus: Event bus for communication
            communication_protocol: Agent communication protocol
        """
        from .human_in_loop import HumanReviewManager
        from .feedback_processor import FeedbackProcessor

        self.config_manager = config_manager
        self.artifact_pool = artifact_pool
        self.event_bus = event_bus
        self.communication_protocol: Optional[CommunicationProtocol] = None

        # Process management
        self.active_sessions: Dict[str, ProcessSession] = {}
        self.agent_coordinators: Dict[str, AgentCoordinator] = {}

        # HITL component
        self.human_review_manager: HumanReviewManager = (
            human_review_manager
            or HumanReviewManager(artifact_pool=artifact_pool, event_bus=event_bus)
        )
        self.feedback_processor = FeedbackProcessor(
            artifact_pool=artifact_pool, event_bus=event_bus
        )

        # State management
        self._lock = threading.RLock()
        self._running = False
        self._orchestration_task: Optional[asyncio.Task] = None

        # Phase definitions and transitions
        self.phase_transitions = {
            ProcessPhase.INITIALIZATION: ProcessPhase.INTERVIEW,
            ProcessPhase.INTERVIEW: ProcessPhase.USER_MODELING,
            ProcessPhase.USER_MODELING: ProcessPhase.DEPLOYMENT_ANALYSIS,
            ProcessPhase.DEPLOYMENT_ANALYSIS: ProcessPhase.REQUIREMENT_ANALYSIS,
            ProcessPhase.REQUIREMENT_ANALYSIS: ProcessPhase.URL_REVIEW,
            ProcessPhase.URL_REVIEW: ProcessPhase.REQUIREMENT_MODELING,
            ProcessPhase.REQUIREMENT_MODELING: ProcessPhase.MODEL_REVIEW,
            ProcessPhase.MODEL_REVIEW: ProcessPhase.SRS_GENERATION,
            ProcessPhase.SRS_GENERATION: ProcessPhase.SRS_REVIEW,
            ProcessPhase.SRS_REVIEW: ProcessPhase.QUALITY_ASSURANCE,
            ProcessPhase.QUALITY_ASSURANCE: ProcessPhase.COMPLETED,
        }

        # Agent assignments for each phase
        self.phase_agents = {
            ProcessPhase.INTERVIEW: ["interviewer"],
            ProcessPhase.USER_MODELING: ["enduser"],
            ProcessPhase.DEPLOYMENT_ANALYSIS: ["deployer"],
            ProcessPhase.REQUIREMENT_ANALYSIS: ["analyst"],
            ProcessPhase.REQUIREMENT_MODELING: ["analyst"],
            ProcessPhase.SRS_GENERATION: ["archivist"],
            ProcessPhase.QUALITY_ASSURANCE: ["reviewer"],
        }

        # Review points that require human intervention
        self.review_phases = {
            # ProcessPhase.INTERVIEW,  # For testing only
            ProcessPhase.URL_REVIEW,
            ProcessPhase.MODEL_REVIEW,
            ProcessPhase.SRS_REVIEW,
        }

        # Callbacks
        self.on_phase_started: Optional[Callable[[str, ProcessPhase], None]] = None
        self.on_phase_completed: Optional[Callable[[str, ProcessPhase], None]] = None
        self.on_review_required: Optional[Callable[[str, str, str], None]] = (
            None  # session_id, artifact_type, artifact_id
        )
        self.on_process_completed: Optional[Callable[[str], None]] = None
        self.on_process_failed: Optional[Callable[[str, str], None]] = None

        # Subscribe to events
        self._setup_event_handlers()

        # Initialize the agents
        self.agents = {}
        self._initialize_agents()

        logger.info("Initialized RequirementOrchestrator")

    def _initialize_agents(self):
        self.agents["interviewer"] = InterviewerAgent()
        self.agents["enduser"] = EndUserAgent()

    def _register_agent_instance(self):
        for agent_name, agent_instance in self.agents.items():
            if self.communication_protocol:
                self.communication_protocol.register_agent_instance(
                    agent_name, agent_instance
                )

    async def start_requirement_process(
        self, project_config: ProjectConfig, created_by: str
    ) -> ProcessSession:
        """
        Start a new requirement development process.

        Args:
            project_config: Project configuration
            created_by: User who started the process

        Returns:
            ProcessSession: The created process session
        """
        with self._lock:
            session = ProcessSession(
                session_id=str(uuid.uuid4()),
                project_config=project_config,
                current_phase=ProcessPhase.INITIALIZATION,
                status=ProcessStatus.NOT_STARTED,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                created_by=created_by,
            )

            self.active_sessions[session.session_id] = session

            # Create agent coordinator for this session
            coordinator = AgentCoordinator(session.session_id)
            self.agent_coordinators[session.session_id] = coordinator

            # Set up coordinator callbacks
            coordinator.on_task_completed = (
                lambda task_id, agent_name: self._on_task_completed(
                    session.session_id, task_id, agent_name
                )
            )
            coordinator.on_task_assigned = (
                lambda task_id, agent_name: self._on_task_assigned(
                    session.session_id, task_id, agent_name
                )
            )

            self.communication_protocol = CommunicationProtocol(
                "agent_coordinator", session.session_id, coordinator
            )
            self.feedback_processor.communication_protocol = self.communication_protocol
            self._register_agent_instance()

            asyncio.create_task(self.communication_protocol.start_async_processing())

            # Publish process started event
            self.event_bus.publish(
                Event(
                    id=str(uuid.uuid4()),
                    type=EventType.PROCESS_PAUSED,  # Using existing event type
                    source="orchestrator",
                    target=None,
                    payload={
                        "session_id": session.session_id,
                        "project_name": project_config.project_name,
                        "phase": ProcessPhase.INITIALIZATION.value,
                    },
                    timestamp=datetime.now(),
                    session_id=session.session_id,
                )
            )

            logger.info(
                f"Started requirement process for project: {project_config.project_name}"
            )

            # Start the orchestration process
            orch_task = asyncio.create_task(self._run_orchestration(session.session_id))
            await asyncio.wait([orch_task])

            return session

    async def pause_for_human_review(
        self, session_id: str, artifact_type: ArtifactType, artifact_id: str
    ) -> None:
        """
        Pause the process for human review.

        Args:
            session_id: Session identifier
            artifact_type: Type of artifact to review
            artifact_id: Artifact identifier
        """
        with self._lock:
            session = self.active_sessions.get(session_id)
            if not session:
                logger.error(f"Session {session_id} not found")
                return

            # Review placeholder
            review_descriptions = {
                ArtifactType.USER_REQUIREMENTS_LIST: "Review User Requirements List for completeness and clarity",
                ArtifactType.REQUIREMENT_MODEL: "Review Requirement Models for accuracy and traceability",
                ArtifactType.SRS_DOCUMENT: "Review Software Requirements Specification document",
            }
            description = review_descriptions.get(
                artifact_type, f"Review {artifact_type.value}"
            )

            session.status = ProcessStatus.PAUSED_FOR_REVIEW
            session.updated_at = datetime.now()

            # Create review point
            review_point = self.human_review_manager.create_review_point(
                session_id=session_id,
                artifact_id=artifact_id,
                phase=session.current_phase.value,
                description=description,
                priority=5 if artifact_type == ArtifactType.SRS_DOCUMENT else 3,
            )
            session.current_review_point = review_point.id

            logger.info(
                f"Paused session {session_id} for review of {artifact_type}: {artifact_id}"
            )

            # Callback
            if self.on_review_required:
                self.on_review_required(session_id, artifact_type.value, artifact_id)
            else:
                await self._on_review_required(
                    session_id, artifact_type.value, artifact_id
                )

    def resume_after_review(self, session_id: str, feedback, artifact_id) -> None:
        """
        Resume the process after human review.

        Args:
            session_id: Session identifier
            feedback: Human feedback
        """
        with self._lock:
            session = self.active_sessions.get(session_id)
            if not session:
                logger.error(f"Session {session_id} not found")
                return

            if session.status != ProcessStatus.PAUSED_FOR_REVIEW:
                logger.warning(f"Session {session_id} is not paused for review")
                return

            self._process_feedback(session_id, feedback, artifact_id)
            # Record feedback
            session.current_review_point = None
            session.review_history.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "phase": session.current_phase.value,
                    "feedback": feedback.to_dict(),
                }
            )

            session.status = ProcessStatus.RUNNING
            session.updated_at = datetime.now()

            logger.info(f"Resumed session {session_id} after review")

            # Continue orchestration
            # asyncio.create_task(self._run_orchestration(session_id))

    def _process_feedback(self, session_id, feedback_data, artifact_id):

        session = self.active_sessions.get(session_id)
        if not session:
            return

        review_point_id = (
            feedback_data.to_dict().get("review_point_id")
            or session.current_review_point
        )

        review_point = None

        # Try to get review point from completed reviews
        for rp in self.human_review_manager.completed_reviews.values():
            if rp.id == review_point_id:
                review_point = rp
                break

        if not review_point:
            logger.error(f"Review point {review_point_id} not found")
            return

        # artifact = self.artifact_pool.get_artifact(artifact_id)
        ## Mockup data
        artifact = Artifact(
            id=str(uuid.uuid4()),
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
            raise ValueError(f"Artifact {artifact_id} not found")

        analysis = self.feedback_processor.process_feedback(feedback_data, artifact)
        correction_tasks = self.feedback_processor.create_correction_tasks(
            analysis, session_id
        )

        for task in correction_tasks:
            success = self.feedback_processor.execute_correction_task(task.id)
            if success:
                validation_criteria = {
                    "min_content_length": 3,  # Minimum content length
                    "required_sections": ["requirements", "specifications"],
                }
                is_valid = self.feedback_processor.validate_correction(
                    task.id, validation_criteria
                )
                if is_valid:
                    logger.info(f"✅ Correction task {task.id} validated successfully")
                else:
                    logger.warning(f"⚠️ Correction task {task.id} failed validation")
            else:
                logger.error(f"❌ Correction task {task.id} execution failed")

    def get_process_status(self, session_id: str) -> Optional[ProcessSession]:
        """
        Get the current status of a process session.

        Args:
            session_id: Session identifier

        Returns:
            ProcessSession or None if not found
        """
        return self.active_sessions.get(session_id)

    def cancel_process(self, session_id: str, reason: str = "") -> bool:
        """
        Cancel a running process.

        Args:
            session_id: Session identifier
            reason: Cancellation reason

        Returns:
            True if cancelled successfully
        """
        with self._lock:
            session = self.active_sessions.get(session_id)
            if not session:
                return False

            session.status = ProcessStatus.CANCELLED
            session.updated_at = datetime.now()
            if reason:
                session.error_log.append(f"Cancelled: {reason}")

            # Stop agent coordinator
            coordinator = self.agent_coordinators.get(session_id)
            if coordinator:
                # Cancel all pending tasks
                for task_id, task in coordinator.tasks.items():
                    if task.status in [
                        TaskStatus.PENDING,
                        TaskStatus.ASSIGNED,
                        TaskStatus.IN_PROGRESS,
                    ]:
                        task.status = TaskStatus.CANCELLED

            logger.info(f"Cancelled session {session_id}: {reason}")
            return True

    def get_active_sessions(self) -> List[ProcessSession]:
        """Get all active process sessions."""
        return list(self.active_sessions.values())

    async def _run_orchestration(self, session_id: str) -> None:
        """
        Run the orchestration process for a session.

        Args:
            session_id: Session identifier
        """
        try:
            session = self.active_sessions.get(session_id)
            if not session:
                logger.error(f"Session {session_id} not found")
                return

            session.status = ProcessStatus.RUNNING

            while (
                session.status == ProcessStatus.RUNNING
                and session.current_phase != ProcessPhase.COMPLETED
                and session.current_phase != ProcessPhase.FAILED
            ):

                # Execute current phase
                await self._execute_phase(session_id)

                # Check if we need to pause for review
                session = self.active_sessions.get(session_id)
                if not session:
                    break

                if session.status == ProcessStatus.PAUSED_FOR_REVIEW:
                    while session.status == ProcessStatus.PAUSED_FOR_REVIEW:
                        pass
                    # break

                # Move to next phase if current phase is completed
                if session.current_phase in self.phase_transitions:
                    next_phase = self.phase_transitions[session.current_phase]
                    await self._transition_to_phase(session_id, next_phase)
                else:
                    # Process completed
                    await self._complete_process(session_id)
                    break

        except Exception as e:
            logger.error(f"Error in orchestration for session {session_id}: {e}")
            await self._fail_process(session_id, str(e))

    async def _execute_phase(self, session_id: str) -> None:
        """
        Execute the current phase of the process.

        Args:
            session_id: Session identifier
        """
        session = self.active_sessions.get(session_id)
        if not session:
            return

        logger.info(
            f"Executing phase {session.current_phase.value} for session {session_id}"
        )

        # Callback
        if self.on_phase_started:
            self.on_phase_started(session_id, session.current_phase)

        # Check if this is a review phase
        if session.current_phase in self.review_phases:
            await self._handle_review_phase(session_id)
            return

        # Get agents for this phase
        agents = self.phase_agents.get(session.current_phase, [])
        if not agents:
            logger.warning(f"No agents defined for phase {session.current_phase.value}")
            return

        # Create and submit tasks for agents
        coordinator = self.agent_coordinators.get(session_id)
        if not coordinator:
            logger.error(f"No coordinator found for session {session_id}")
            return

        for agent_name in agents:
            task = self._create_phase_task(session, agent_name)
            coordinator.submit_task(task)
            session.active_agents.add(agent_name)

        # Assign tasks
        await coordinator.assign_tasks()

        # Wait for phase completion
        await self._wait_for_phase_completion(session_id)

    async def _handle_review_phase(self, session_id: str) -> None:
        """
        Handle a review phase that requires human intervention.

        Args:
            session_id: Session identifier
        """
        session = self.active_sessions.get(session_id)
        if not session:
            return

        # Find the artifact that needs review
        artifact_type = self._get_review_artifact_type(session.current_phase)
        # artifacts = self.artifact_pool.query_artifacts_by_type(
        #     artifact_type, session_id
        # )

        ## Artifact mockup
        artifacts = [
            Artifact(
                id=str(uuid.uuid4()),
                type=ArtifactType.INTERVIEW_RECORD,
                content={},
                metadata=ArtifactMetadata(source_agent="interviewer"),
                version="1.0",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                created_by="interviewer",
                status=ArtifactStatus.DRAFT,
            )
        ]

        if not artifacts:
            logger.error(
                f"No artifacts found for review in phase {session.current_phase.value}"
            )
            return

        # Get the latest artifact
        latest_artifact = max(artifacts, key=lambda a: a.updated_at)

        # Pause for review
        await self.pause_for_human_review(session_id, artifact_type, latest_artifact.id)

    def _get_review_artifact_type(self, phase: ProcessPhase) -> ArtifactType:
        """Get the artifact type that needs review for a given phase."""
        review_artifact_map = {
            ProcessPhase.URL_REVIEW: ArtifactType.USER_REQUIREMENTS_LIST,
            ProcessPhase.MODEL_REVIEW: ArtifactType.REQUIREMENT_MODEL,
            ProcessPhase.SRS_REVIEW: ArtifactType.SRS_DOCUMENT,
        }
        return review_artifact_map.get(phase, ArtifactType.SRS_DOCUMENT)

    def _create_phase_task(self, session: ProcessSession, agent_name: str) -> Task:
        """Create a task for an agent in the current phase."""
        task_descriptions = {
            ProcessPhase.INTERVIEW: "Conduct stakeholder interviews and collect initial requirements",
            ProcessPhase.USER_MODELING: "Create user personas and scenarios based on interview data",
            ProcessPhase.DEPLOYMENT_ANALYSIS: "Analyze deployment constraints and security requirements",
            ProcessPhase.REQUIREMENT_ANALYSIS: "Transform user needs into system requirements",
            ProcessPhase.REQUIREMENT_MODELING: "Create detailed requirement models and traceability",
            ProcessPhase.SRS_GENERATION: "Generate Software Requirements Specification document",
            ProcessPhase.QUALITY_ASSURANCE: "Review and validate the generated SRS document",
        }

        return Task(
            id=str(uuid.uuid4()),
            type=f"{session.current_phase.value}_{agent_name}",
            description=task_descriptions.get(
                session.current_phase, f"Execute {session.current_phase.value}"
            ),
            requirements=[agent_name],
            priority=TaskPriority.NORMAL,
            estimated_duration=timedelta(minutes=30),
            metadata={
                "session_id": session.session_id,
                "phase": session.current_phase.value,
                "project_config": session.project_config.custom_config,
            },
        )

    async def _wait_for_phase_completion(self, session_id: str) -> None:
        """Wait for the current phase to complete."""
        session = self.active_sessions.get(session_id)
        if not session:
            return

        coordinator = self.agent_coordinators.get(session_id)
        if not coordinator:
            return

        # Wait for all tasks in this phase to complete
        timeout = timedelta(minutes=session.project_config.timeout_minutes)
        start_time = datetime.now()

        while datetime.now() - start_time < timeout:
            # Check if all phase tasks are completed
            phase_tasks = [
                task
                for task in coordinator.tasks.values()
                if task.metadata.get("phase") == session.current_phase.value
            ]

            if not phase_tasks:
                break

            # logger.info(f"Phase task for phase {session.current_phase.value}: {phase_tasks}")
            completed_tasks = [
                task
                for task in phase_tasks
                if task.status
                in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
            ]

            if len(completed_tasks) == len(phase_tasks):
                break

            await asyncio.sleep(1)

        # Update progress
        total_phases = len(ProcessPhase) - 2  # Exclude COMPLETED and FAILED
        current_phase_index = list(ProcessPhase).index(session.current_phase)
        session.progress = min(1.0, current_phase_index / total_phases)
        session.updated_at = datetime.now()

        # Callback
        if self.on_phase_completed:
            self.on_phase_completed(session_id, session.current_phase)

    async def _transition_to_phase(
        self, session_id: str, next_phase: ProcessPhase
    ) -> None:
        """Transition to the next phase."""
        session = self.active_sessions.get(session_id)
        if not session:
            return

        logger.info(
            f"Transitioning session {session_id} from {session.current_phase.value} to {next_phase.value}"
        )

        session.current_phase = next_phase
        session.updated_at = datetime.now()
        session.active_agents.clear()

    async def _complete_process(self, session_id: str) -> None:
        """Complete the requirement development process."""
        session = self.active_sessions.get(session_id)
        if not session:
            return

        session.current_phase = ProcessPhase.COMPLETED
        session.status = ProcessStatus.COMPLETED
        session.progress = 1.0
        session.updated_at = datetime.now()

        # Callback
        if self.on_process_completed:
            self.on_process_completed(session_id)

        logger.info(f"Completed requirement process for session {session_id}")

    async def _fail_process(self, session_id: str, error: str) -> None:
        """Fail the requirement development process."""
        session = self.active_sessions.get(session_id)
        if not session:
            return

        session.current_phase = ProcessPhase.FAILED
        session.status = ProcessStatus.FAILED
        session.updated_at = datetime.now()
        session.error_log.append(error)

        # Callback
        if self.on_process_failed:
            self.on_process_failed(session_id, error)

        logger.error(f"Failed requirement process for session {session_id}: {error}")

    def _setup_event_handlers(self) -> None:
        """Set up event handlers for the orchestrator."""
        self.event_bus.subscribe_callable(
            [EventType.AGENT_COMPLETED, EventType.AGENT_FAILED],
            self._handle_agent_event,
        )

        self.event_bus.subscribe_callable(
            [EventType.ARTIFACT_CREATED, EventType.ARTIFACT_UPDATED],
            self._handle_artifact_event,
        )

    def _handle_agent_event(self, event: Event) -> None:
        """Handle agent-related events."""
        session_id = event.session_id
        session = self.active_sessions.get(session_id)

        if not session:
            return

        agent_name = event.payload.get("agent_name", "")

        if event.type == EventType.AGENT_COMPLETED:
            logger.info(f"Agent {agent_name} completed in session {session_id}")
            session.active_agents.discard(agent_name)

        elif event.type == EventType.AGENT_FAILED:
            logger.error(f"Agent {agent_name} failed in session {session_id}")
            session.active_agents.discard(agent_name)
            error = event.payload.get("error", "Unknown error")
            session.error_log.append(f"Agent {agent_name} failed: {error}")

    def _handle_artifact_event(self, event: Event) -> None:
        """Handle artifact-related events."""
        session_id = event.session_id
        session = self.active_sessions.get(session_id)

        if not session:
            return

        artifact_id = event.payload.get("artifact_id")

        if event.type == EventType.ARTIFACT_CREATED and artifact_id:
            if artifact_id not in session.artifacts:
                session.artifacts.append(artifact_id)
                session.updated_at = datetime.now()

    def _on_task_assigned(self, session_id: str, task_id: str, agent_name: str) -> None:
        """Handle task assignment."""
        logger.info(f"Task {task_id} assigned to {agent_name} in session {session_id}")

    def _on_task_completed(
        self, session_id: str, task_id: str, agent_name: str
    ) -> None:
        """Handle task completion."""
        logger.info(f"Task {task_id} completed by {agent_name} in session {session_id}")

    async def _on_review_required(
        self, session_id: str, artifact_type: str, artifact_id: str
    ) -> None:
        from .feedback_processor import FeedbackType

        with self._lock:
            session = self.active_sessions.get(session_id)
            if not session:
                logger.error(f"Session {session_id} not found")
                return

            if session.status != ProcessStatus.PAUSED_FOR_REVIEW:
                logger.warning(f"Session {session_id} is not paused for review")
                return

            # Get current review point
            review_point_id = session.current_review_point
            if not review_point_id:
                logger.error(f"No active review point for session {session_id}")
                return

            # Mock feedback
            feedback_data = {}
            await asyncio.sleep(1.5)
            feedback = self.human_review_manager.submit_feedback(
                review_point_id=review_point_id,
                reviewer=feedback_data.get("reviewer", "anonymous"),
                feedback_type=FeedbackType(
                    feedback_data.get("feedback_type", "modification_request")
                ),
                content=feedback_data.get("content", ""),
                suggestions=feedback_data.get("suggestions", []),
                approval_status=feedback_data.get("approval_status", True),
                confidence_score=feedback_data.get("confidence_score", 0.8),
            )
            logger.info(f"✅ Feedback submitted for review point {review_point_id}")

            self.resume_after_review(session_id, feedback, artifact_id)
