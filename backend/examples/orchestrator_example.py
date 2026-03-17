"""
Example demonstrating the orchestrator and human-in-the-loop functionality.

This example shows how to use the RequirementOrchestrator, HumanReviewManager,
and FeedbackProcessor to manage a complete requirement development process
with human review points.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import asyncio
import logging
from datetime import datetime, timedelta

from src.artifact.events import EventBus
from src.artifact.pool import ArtifactPool
from src.artifact.storage import InMemoryArtifactStorage
from src.agent.communication import CommunicationProtocol
from src.config.config_manager import ConfigManager
from src.orchestrator.orchestrator import RequirementOrchestrator, ProjectConfig
from src.orchestrator.human_in_loop import HumanReviewManager, FeedbackType
from src.orchestrator.feedback_processor import FeedbackProcessor

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Main example function."""
    logger.info("Starting orchestrator example")
    
    # Initialize components
    config_manager = ConfigManager()
    event_bus = EventBus()
    storage = InMemoryArtifactStorage()
    artifact_pool = ArtifactPool(storage, event_bus)
    communication_protocol = CommunicationProtocol()
    
    # Initialize orchestrator and related components
    orchestrator = RequirementOrchestrator(
        config_manager=config_manager,
        artifact_pool=artifact_pool,
        event_bus=event_bus,
        communication_protocol=communication_protocol
    )
    
    review_manager = HumanReviewManager(
        artifact_pool=artifact_pool,
        event_bus=event_bus
    )
    
    feedback_processor = FeedbackProcessor(
        artifact_pool=artifact_pool,
        event_bus=event_bus,
        communication_protocol=communication_protocol
    )
    
    # Set up callbacks
    def on_review_required(session_id: str, artifact_type: str, artifact_id: str):
        logger.info(f"Review required for {artifact_type}: {artifact_id}")
        
        # Create review point
        review_point = review_manager.create_review_point(
            session_id=session_id,
            artifact_id=artifact_id,
            phase="url_review",
            description=f"Please review the {artifact_type}",
            timeout_minutes=60,
            assigned_reviewer="human_reviewer"
        )
        
        logger.info(f"Created review point: {review_point.id}")
    
    def on_feedback_received(feedback):
        logger.info(f"Feedback received: {feedback.feedback_type.value}")
        
        # Process the feedback
        artifact = artifact_pool.get_artifact(feedback.review_point_id)  # This would need proper mapping
        if artifact:
            analysis = feedback_processor.process_feedback(feedback, artifact)
            logger.info(f"Feedback analysis: {analysis.primary_action.value}")
            
            # Create correction tasks if needed
            if analysis.requires_agent_action:
                tasks = feedback_processor.create_correction_tasks(analysis, "example_session")
                logger.info(f"Created {len(tasks)} correction tasks")
    
    # Set up callbacks
    orchestrator.on_review_required = on_review_required
    review_manager.on_feedback_received = on_feedback_received
    
    # Create a project configuration
    project_config = ProjectConfig(
        project_name="Example Project",
        domain="web_application",
        stakeholders=["product_owner", "end_users", "developers"],
        target_environment="cloud",
        compliance_requirements=["GDPR", "SOC2"],
        quality_standards=["IEEE_830"],
        review_points=["url_generation", "model_creation", "srs_generation"],
        timeout_minutes=60
    )
    
    # Start the requirement development process
    logger.info("Starting requirement development process")
    session = orchestrator.start_requirement_process(
        project_config=project_config,
        created_by="example_user"
    )
    
    logger.info(f"Started session: {session.session_id}")
    
    # Simulate the process running for a while
    await asyncio.sleep(2)
    
    # Check process status
    status = orchestrator.get_process_status(session.session_id)
    if status:
        logger.info(f"Process status: {status.status.value}, Phase: {status.current_phase.value}")
    
    # Simulate human feedback
    logger.info("Simulating human feedback")
    
    # Get pending reviews
    pending_reviews = review_manager.get_pending_reviews(session_id=session.session_id)
    
    if pending_reviews:
        review_point = pending_reviews[0]
        logger.info(f"Found pending review: {review_point.id}")
        
        # Submit feedback
        feedback = review_manager.submit_feedback(
            review_point_id=review_point.id,
            reviewer="human_reviewer",
            feedback_type=FeedbackType.MODIFICATION_REQUEST,
            content="The requirements need more detail in the user authentication section. Please add specific security requirements and error handling scenarios.",
            suggestions=[
                "Add multi-factor authentication requirement",
                "Specify password complexity rules",
                "Define session timeout behavior"
            ],
            approval_status=False,
            confidence_score=0.8
        )
        
        logger.info(f"Submitted feedback: {feedback.id}")
        
        # Resume the process
        orchestrator.resume_after_review(session.session_id, {
            'feedback_id': feedback.id,
            'action': 'modify_and_continue'
        })
        
        logger.info("Resumed process after feedback")
    
    # Wait a bit more
    await asyncio.sleep(2)
    
    # Check final status
    final_status = orchestrator.get_process_status(session.session_id)
    if final_status:
        logger.info(f"Final status: {final_status.status.value}, Progress: {final_status.progress:.2f}")
    
    # Get review statistics
    stats = review_manager.get_review_statistics(session_id=session.session_id)
    logger.info(f"Review statistics: {stats}")
    
    # Get correction status
    if pending_reviews:
        correction_status = feedback_processor.get_correction_status(feedback.id)
        logger.info(f"Correction status: {correction_status}")
    
    logger.info("Orchestrator example completed")


if __name__ == "__main__":
    asyncio.run(main())