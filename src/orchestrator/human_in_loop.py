"""
Human-in-the-loop mechanism for the iReDev framework.

This module provides functionality for pausing the requirement development
process at critical points for human review and feedback collection.
"""

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Set

from ..artifact.events import EventBus, Event, EventType
from ..artifact.pool import ArtifactPool
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus

logger = logging.getLogger(__name__)


class ReviewStatus(Enum):
    """Status of a human review."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FeedbackType(Enum):
    """Types of human feedback."""

    APPROVAL = "approval"
    REJECTION = "rejection"
    MODIFICATION_REQUEST = "modification_request"
    CLARIFICATION_REQUEST = "clarification_request"
    ADDITIONAL_REQUIREMENTS = "additional_requirements"


@dataclass
class ReviewPoint:
    """Represents a point in the process where human review is required."""

    id: str
    session_id: str
    artifact_id: str
    artifact_type: ArtifactType
    phase: str
    description: str
    created_at: datetime
    timeout_at: datetime
    status: ReviewStatus = ReviewStatus.PENDING
    assigned_reviewer: Optional[str] = None
    priority: int = 1  # 1-5 scale, 5 being highest
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure ID is set if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def is_expired(self) -> bool:
        """Check if the review point has expired."""
        return datetime.now() > self.timeout_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert review point to dictionary."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "phase": self.phase,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "timeout_at": self.timeout_at.isoformat(),
            "status": self.status.value,
            "assigned_reviewer": self.assigned_reviewer,
            "priority": self.priority,
            "metadata": self.metadata,
        }


@dataclass
class HumanFeedback:
    """Represents feedback provided by a human reviewer."""

    id: str
    review_point_id: str
    reviewer: str
    feedback_type: FeedbackType
    content: str
    suggestions: List[str] = field(default_factory=list)
    approval_status: bool = False
    confidence_score: Optional[float] = None  # 0.0 to 1.0
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure ID is set if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert feedback to dictionary."""
        return {
            "id": self.id,
            "review_point_id": self.review_point_id,
            "reviewer": self.reviewer,
            "feedback_type": self.feedback_type.value,
            "content": self.content,
            "suggestions": self.suggestions,
            "approval_status": self.approval_status,
            "confidence_score": self.confidence_score,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class HumanReviewManager:
    """
    Manages human-in-the-loop review processes.

    Handles creation of review points, collection of feedback,
    and coordination with the orchestrator.
    """

    def __init__(self, artifact_pool: ArtifactPool, event_bus: EventBus):
        """
        Initialize the human review manager.

        Args:
            artifact_pool: Shared artifact pool
            event_bus: Event bus for communication
        """
        self.artifact_pool = artifact_pool
        self.event_bus = event_bus

        # Review management
        self.active_reviews: Dict[str, ReviewPoint] = {}
        self.completed_reviews: Dict[str, ReviewPoint] = {}
        self.feedback_history: Dict[str, List[HumanFeedback]] = {}

        # State management
        self._lock = threading.RLock()

        # Configuration
        self.default_timeout_minutes = 1440  # 24 hours
        self.max_review_iterations = 3

        # Callbacks
        self.on_review_created: Optional[Callable[[ReviewPoint], None]] = None
        self.on_feedback_received: Optional[Callable[[HumanFeedback], None]] = None
        self.on_review_completed: Optional[
            Callable[[ReviewPoint, HumanFeedback], None]
        ] = None
        self.on_review_timeout: Optional[Callable[[ReviewPoint], None]] = None

        # Subscribe to events
        self._setup_event_handlers()

        logger.info("Initialized HumanReviewManager")

    def create_review_point(
        self,
        session_id: str,
        artifact_id: str,
        phase: str,
        description: str,
        timeout_minutes: Optional[int] = None,
        priority: int = 1,
        assigned_reviewer: Optional[str] = None,
    ) -> ReviewPoint:
        """
        Create a new review point.

        Args:
            session_id: Session identifier
            artifact_id: Artifact to review
            phase: Current process phase
            description: Review description
            timeout_minutes: Review timeout in minutes
            priority: Review priority (1-5)
            assigned_reviewer: Specific reviewer to assign

        Returns:
            ReviewPoint: The created review point
        """
        with self._lock:
            # Get artifact to determine type
            # artifact = self.artifact_pool.get_artifact(artifact_id)
            # if not artifact:
            #     raise ValueError(f"Artifact {artifact_id} not found")

            ## Artifact mockup
            from .orchestrator import ArtifactMetadata

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

            # Create review point
            timeout_minutes = timeout_minutes or self.default_timeout_minutes
            review_point = ReviewPoint(
                id=str(uuid.uuid4()),
                session_id=session_id,
                artifact_id=artifact_id,
                artifact_type=artifact.type,
                phase=phase,
                description=description,
                created_at=datetime.now(),
                timeout_at=datetime.now() + timedelta(minutes=timeout_minutes),
                priority=priority,
                assigned_reviewer=assigned_reviewer,
            )

            self.active_reviews[review_point.id] = review_point

            # Update artifact status
            artifact.status = ArtifactStatus.UNDER_REVIEW
            self.artifact_pool.update_artifact(
                artifact_id, {"status": ArtifactStatus.UNDER_REVIEW.value}
            )

            # Publish review requested event
            self.event_bus.publish(
                Event(
                    id=str(uuid.uuid4()),
                    type=EventType.REVIEW_REQUESTED,
                    source="human_review_manager",
                    target=assigned_reviewer or "human_reviewer",
                    payload={
                        "review_point_id": review_point.id,
                        "artifact_id": artifact_id,
                        "artifact_type": artifact.type.value,
                        "phase": phase,
                        "description": description,
                        "priority": priority,
                        "timeout_at": review_point.timeout_at.isoformat(),
                    },
                    timestamp=datetime.now(),
                    session_id=session_id,
                )
            )

            # Callback
            if self.on_review_created:
                self.on_review_created(review_point)

            logger.info(
                f"Created review point {review_point.id} for artifact {artifact_id}"
            )

            return review_point

    def submit_feedback(
        self,
        review_point_id: str,
        reviewer: str,
        feedback_type: FeedbackType,
        content: str,
        suggestions: Optional[List[str]] = None,
        approval_status: bool = False,
        confidence_score: Optional[float] = None,
    ) -> HumanFeedback:
        """
        Submit feedback for a review point.

        Args:
            review_point_id: Review point identifier
            reviewer: Name of the reviewer
            feedback_type: Type of feedback
            content: Feedback content
            suggestions: List of suggestions
            approval_status: Whether the artifact is approved
            confidence_score: Reviewer's confidence (0.0-1.0)

        Returns:
            HumanFeedback: The submitted feedback
        """
        with self._lock:
            review_point = self.active_reviews.get(review_point_id)
            if not review_point:
                raise ValueError(
                    f"Review point {review_point_id} not found or already completed"
                )

            if review_point.status != ReviewStatus.PENDING:
                raise ValueError(f"Review point {review_point_id} is not pending")

            # Create feedback
            feedback = HumanFeedback(
                id=str(uuid.uuid4()),
                review_point_id=review_point_id,
                reviewer=reviewer,
                feedback_type=feedback_type,
                content=content,
                suggestions=suggestions or [],
                approval_status=approval_status,
                confidence_score=confidence_score,
            )

            # Store feedback
            if review_point_id not in self.feedback_history:
                self.feedback_history[review_point_id] = []
            self.feedback_history[review_point_id].append(feedback)

            # Update review point status
            review_point.status = ReviewStatus.COMPLETED
            review_point.assigned_reviewer = reviewer

            # Move to completed reviews
            self.completed_reviews[review_point_id] = review_point
            del self.active_reviews[review_point_id]

            # Update artifact status based on feedback
            artifact = self.artifact_pool.get_artifact(review_point.artifact_id)
            if artifact:
                if approval_status:
                    artifact.status = ArtifactStatus.APPROVED
                    self.artifact_pool.update_artifact(
                        review_point.artifact_id,
                        {"status": ArtifactStatus.APPROVED.value},
                    )
                else:
                    artifact.status = ArtifactStatus.DRAFT
                    self.artifact_pool.update_artifact(
                        review_point.artifact_id, {"status": ArtifactStatus.DRAFT.value}
                    )

            # Publish feedback received event
            self.event_bus.publish(
                Event(
                    id=str(uuid.uuid4()),
                    type=EventType.HUMAN_FEEDBACK_RECEIVED,
                    source=reviewer,
                    target="orchestrator",
                    payload={
                        "review_point_id": review_point_id,
                        "feedback_id": feedback.id,
                        "feedback_type": feedback_type.value,
                        "approval_status": approval_status,
                        "content": content,
                        "suggestions": suggestions or [],
                    },
                    timestamp=datetime.now(),
                    session_id=review_point.session_id,
                )
            )

            # Callbacks
            if self.on_feedback_received:
                self.on_feedback_received(feedback)

            if self.on_review_completed:
                self.on_review_completed(review_point, feedback)

            logger.info(
                f"Received feedback for review point {review_point_id} from {reviewer}"
            )

            return feedback

    def get_pending_reviews(
        self, reviewer: Optional[str] = None, session_id: Optional[str] = None
    ) -> List[ReviewPoint]:
        """
        Get pending review points.

        Args:
            reviewer: Filter by assigned reviewer
            session_id: Filter by session

        Returns:
            List of pending review points
        """
        with self._lock:
            reviews = list(self.active_reviews.values())

            # Filter by reviewer
            if reviewer:
                reviews = [
                    r
                    for r in reviews
                    if r.assigned_reviewer == reviewer or r.assigned_reviewer is None
                ]

            # Filter by session
            if session_id:
                reviews = [r for r in reviews if r.session_id == session_id]

            # Sort by priority and creation time
            reviews.sort(key=lambda r: (-r.priority, r.created_at))

            return reviews

    def get_review_history(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get review history for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of review history entries
        """
        with self._lock:
            history = []

            # Get completed reviews for this session
            session_reviews = [
                r for r in self.completed_reviews.values() if r.session_id == session_id
            ]

            for review in session_reviews:
                feedback_list = self.feedback_history.get(review.id, [])

                history.append(
                    {
                        "review_point": review.to_dict(),
                        "feedback": [f.to_dict() for f in feedback_list],
                    }
                )

            # Sort by creation time
            history.sort(key=lambda h: h["review_point"]["created_at"])

            return history

    def cancel_review(self, review_point_id: str, reason: str = "") -> bool:
        """
        Cancel a pending review.

        Args:
            review_point_id: Review point identifier
            reason: Cancellation reason

        Returns:
            True if cancelled successfully
        """
        with self._lock:
            review_point = self.active_reviews.get(review_point_id)
            if not review_point:
                return False

            review_point.status = ReviewStatus.CANCELLED
            review_point.metadata["cancellation_reason"] = reason

            # Move to completed reviews
            self.completed_reviews[review_point_id] = review_point
            del self.active_reviews[review_point_id]

            # Update artifact status
            artifact = self.artifact_pool.get_artifact(review_point.artifact_id)
            if artifact:
                artifact.status = ArtifactStatus.DRAFT
                self.artifact_pool.update_artifact(
                    review_point.artifact_id, {"status": ArtifactStatus.DRAFT.value}
                )

            logger.info(f"Cancelled review point {review_point_id}: {reason}")
            return True

    def check_timeouts(self) -> List[ReviewPoint]:
        """
        Check for timed out reviews and handle them.

        Returns:
            List of timed out review points
        """
        with self._lock:
            timed_out = []

            for review_id, review_point in list(self.active_reviews.items()):
                if review_point.is_expired():
                    review_point.status = ReviewStatus.TIMEOUT

                    # Move to completed reviews
                    self.completed_reviews[review_id] = review_point
                    del self.active_reviews[review_id]

                    # Update artifact status
                    artifact = self.artifact_pool.get_artifact(review_point.artifact_id)
                    if artifact:
                        artifact.status = ArtifactStatus.DRAFT
                        self.artifact_pool.update_artifact(
                            review_point.artifact_id,
                            {"status": ArtifactStatus.DRAFT.value},
                        )

                    timed_out.append(review_point)

                    # Callback
                    if self.on_review_timeout:
                        self.on_review_timeout(review_point)

                    logger.warning(f"Review point {review_id} timed out")

            return timed_out

    def get_review_statistics(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get review statistics.

        Args:
            session_id: Optional session filter

        Returns:
            Dictionary with review statistics
        """
        with self._lock:
            # Filter reviews by session if specified
            if session_id:
                active = [
                    r
                    for r in self.active_reviews.values()
                    if r.session_id == session_id
                ]
                completed = [
                    r
                    for r in self.completed_reviews.values()
                    if r.session_id == session_id
                ]
            else:
                active = list(self.active_reviews.values())
                completed = list(self.completed_reviews.values())

            # Calculate statistics
            total_reviews = len(active) + len(completed)
            pending_count = len([r for r in active if r.status == ReviewStatus.PENDING])
            completed_count = len(
                [r for r in completed if r.status == ReviewStatus.COMPLETED]
            )
            timeout_count = len(
                [r for r in completed if r.status == ReviewStatus.TIMEOUT]
            )
            cancelled_count = len(
                [r for r in completed if r.status == ReviewStatus.CANCELLED]
            )

            # Calculate average response time for completed reviews
            avg_response_time = None
            if completed_count > 0:
                response_times = []
                for review in completed:
                    if review.status == ReviewStatus.COMPLETED:
                        feedback_list = self.feedback_history.get(review.id, [])
                        if feedback_list:
                            response_time = (
                                feedback_list[0].created_at - review.created_at
                            ).total_seconds()
                            response_times.append(response_time)

                if response_times:
                    avg_response_time = sum(response_times) / len(response_times)

            return {
                "total_reviews": total_reviews,
                "pending": pending_count,
                "completed": completed_count,
                "timeout": timeout_count,
                "cancelled": cancelled_count,
                "avg_response_time_seconds": avg_response_time,
                "completion_rate": (
                    completed_count / total_reviews if total_reviews > 0 else 0.0
                ),
            }

    def _setup_event_handlers(self) -> None:
        """Set up event handlers for the review manager."""
        self.event_bus.subscribe_callable(
            [EventType.REVIEW_COMPLETED], self._handle_review_event
        )

    def _handle_review_event(self, event: Event) -> None:
        """Handle review-related events."""
        if event.type == EventType.REVIEW_COMPLETED:
            review_point_id = event.payload.get("review_point_id")
            if review_point_id and review_point_id in self.active_reviews:
                logger.info(f"Review completed event received for {review_point_id}")
