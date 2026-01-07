"""
Example usage of the iReDev Artifact System.

This module demonstrates how to use the artifact pool, storage, and event system.
"""

from datetime import datetime
from src.artifact import (
    Artifact, ArtifactMetadata, ArtifactType, ArtifactStatus, ArtifactQuery,
    ArtifactPool, MemoryArtifactStorage, EventBus, EventType
)


def example_usage():
    """Demonstrate basic artifact system usage."""
    
    # Create event bus and artifact pool
    event_bus = EventBus()
    storage = MemoryArtifactStorage()
    pool = ArtifactPool(storage=storage, event_bus=event_bus)
    
    # Set up event handler
    def handle_artifact_events(event):
        print(f"Event: {event.type.value} - {event.payload}")
    
    event_bus.subscribe_callable(
        [EventType.ARTIFACT_CREATED, EventType.ARTIFACT_UPDATED],
        handle_artifact_events
    )
    
    # Create an interview record artifact
    interview_metadata = ArtifactMetadata(
        tags=["interview", "requirements"],
        source_agent="InterviewerAgent",
        custom_properties={"stakeholder": "Product Manager"}
    )
    
    interview_artifact = Artifact(
        id="",  # Will be auto-generated
        type=ArtifactType.INTERVIEW_RECORD,
        content={
            "questions": [
                "What are the main goals of this system?",
                "Who are the primary users?"
            ],
            "answers": [
                "Automate requirement gathering process",
                "Business analysts and product managers"
            ],
            "duration_minutes": 45
        },
        metadata=interview_metadata,
        version="1.0",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        created_by="InterviewerAgent"
    )
    
    # Store the artifact
    print("Storing interview artifact...")
    artifact_id = pool.store_artifact(interview_artifact, "InterviewerAgent")
    print(f"Stored artifact with ID: {artifact_id}")
    
    # Update the artifact
    print("\nUpdating artifact...")
    updates = {
        "content": {
            **interview_artifact.content,
            "follow_up_questions": ["What are the performance requirements?"]
        }
    }
    version_id = pool.update_artifact(artifact_id, updates, "InterviewerAgent", "Added follow-up questions")
    print(f"Updated artifact, new version: {version_id}")
    
    # Query artifacts
    print("\nQuerying artifacts...")
    query = ArtifactQuery(
        artifact_type=ArtifactType.INTERVIEW_RECORD,
        tags=["interview"]
    )
    results = pool.query_artifacts(query)
    print(f"Found {len(results)} interview artifacts")
    
    # Get artifact history
    print("\nGetting artifact history...")
    history = pool.get_artifact_history(artifact_id)
    print(f"Artifact has {len(history)} versions")
    
    # Get change history
    print("\nGetting change history...")
    changes = pool.get_artifact_changes(artifact_id)
    for change in changes:
        print(f"- {change['change_type']} at {change['timestamp']} by {change['changed_by']}")
    
    # Create a user persona artifact and link it
    print("\nCreating related user persona...")
    persona_artifact = Artifact(
        id="",
        type=ArtifactType.USER_PERSONA,
        content={
            "name": "Sarah - Business Analyst",
            "role": "Senior Business Analyst",
            "goals": ["Efficient requirement gathering", "Clear documentation"],
            "pain_points": ["Manual processes", "Inconsistent formats"]
        },
        metadata=ArtifactMetadata(
            tags=["persona", "user"],
            source_agent="EndUserAgent"
        ),
        version="1.0",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        created_by="EndUserAgent"
    )
    
    persona_id = pool.store_artifact(persona_artifact, "EndUserAgent")
    print(f"Created persona artifact: {persona_id}")
    
    # Link the artifacts
    print("\nLinking artifacts...")
    pool.link_artifacts(artifact_id, persona_id, "derived_from", "system")
    
    # Get related artifacts
    related = pool.get_related_artifacts(artifact_id)
    print(f"Found {len(related)} related artifacts")
    
    # Get pool statistics
    print("\nPool statistics:")
    stats = pool.get_statistics()
    for key, value in stats.items():
        print(f"- {key}: {value}")
    
    # Demonstrate event history
    print("\nEvent history:")
    events = event_bus.get_event_history(pool.session_id, limit=5)
    for event in events:
        print(f"- {event.type.value} at {event.timestamp} from {event.source}")


if __name__ == "__main__":
    example_usage()