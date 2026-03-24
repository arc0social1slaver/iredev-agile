"""
Artifact Pool - Central coordination for artifact management.

This module provides the main ArtifactPool class that integrates storage,
versioning, event handling, and change tracking.
"""

import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable

from .models import Artifact, ArtifactVersion, ArtifactQuery, ArtifactStatus, ArtifactType
from .storage import ArtifactStorage, MemoryArtifactStorage
from .events import EventBus, Event, EventType, get_event_bus


class ChangeTracker:
    """Tracks changes to artifacts for audit and rollback purposes."""
    
    def __init__(self):
        self._changes: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.RLock()
    
    def record_change(self, artifact_id: str, change_type: str, 
                     old_value: Any, new_value: Any, changed_by: str) -> None:
        """Record a change to an artifact."""
        with self._lock:
            if artifact_id not in self._changes:
                self._changes[artifact_id] = []
            
            change_record = {
                'timestamp': datetime.now(),
                'change_type': change_type,
                'old_value': old_value,
                'new_value': new_value,
                'changed_by': changed_by,
                'change_id': str(uuid.uuid4())
            }
            
            self._changes[artifact_id].append(change_record)
    
    def get_changes(self, artifact_id: str) -> List[Dict[str, Any]]:
        """Get all changes for an artifact."""
        with self._lock:
            return self._changes.get(artifact_id, []).copy()
    
    def get_recent_changes(self, artifact_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent changes for an artifact."""
        changes = self.get_changes(artifact_id)
        changes.sort(key=lambda c: c['timestamp'], reverse=True)
        return changes[:limit]


class ArtifactPool:
    """
    Central artifact pool that manages storage, versioning, events, and change tracking.
    
    This is the main interface for artifact management in the iReDev system.
    """
    
    def __init__(self, storage: Optional[ArtifactStorage] = None, 
                 event_bus: Optional[EventBus] = None,
                 session_id: Optional[str] = None):
        self.storage = storage or MemoryArtifactStorage()
        self.event_bus = event_bus or get_event_bus()
        self.session_id = session_id or str(uuid.uuid4())
        self.change_tracker = ChangeTracker()
        self._lock = threading.RLock()
        
        # Subscribe to relevant events
        self._setup_event_handlers()
    
    def _setup_event_handlers(self) -> None:
        """Set up event handlers for the artifact pool."""
        def handle_artifact_events(event: Event) -> None:
            # This can be extended to handle specific artifact events
            pass
        
        self.event_bus.subscribe_callable(
            [EventType.ARTIFACT_CREATED, EventType.ARTIFACT_UPDATED, EventType.ARTIFACT_DELETED],
            handle_artifact_events
        )
    
    def store_artifact(self, artifact: Artifact, created_by: str = "system") -> str:
        """
        Store an artifact in the pool.
        
        Args:
            artifact: The artifact to store
            created_by: Who created the artifact
            
        Returns:
            The artifact ID
        """
        with self._lock:
            # Set metadata if not provided
            if not artifact.created_by:
                artifact.created_by = created_by
            
            if not artifact.created_at:
                artifact.created_at = datetime.now()
            
            if not artifact.updated_at:
                artifact.updated_at = datetime.now()
            
            # Store in backend
            artifact_id = self.storage.store_artifact(artifact)
            
            # Create initial version
            version = artifact.create_version("Initial version")
            self.storage.store_version(version)
            
            # Record change
            self.change_tracker.record_change(
                artifact_id, "created", None, artifact.to_dict(), created_by
            )
            
            # Publish event
            self.event_bus.publish_artifact_created(
                artifact_id, artifact.type.value, created_by, self.session_id
            )
            
            return artifact_id
    
    def get_artifact(self, artifact_id: str, version: Optional[str] = None) -> Optional[Artifact]:
        """
        Get an artifact by ID, optionally at a specific version.
        
        Args:
            artifact_id: The artifact ID
            version: Optional version ID to retrieve
            
        Returns:
            The artifact or None if not found
        """
        with self._lock:
            if version:
                # Get specific version
                artifact_version = self.storage.get_version(version)
                if artifact_version and artifact_version.artifact_id == artifact_id:
                    # Reconstruct artifact from version
                    artifact = Artifact(
                        id=artifact_version.artifact_id,
                        type=ArtifactType(artifact_version.content.get('type', 'unknown')),
                        content=artifact_version.content.get('content', {}),
                        metadata=artifact_version.metadata,
                        version=artifact_version.version_id,
                        created_at=artifact_version.created_at,
                        updated_at=artifact_version.created_at,
                        created_by=artifact_version.created_by,
                        status=ArtifactStatus(artifact_version.content.get('status', 'draft'))
                    )
                    return artifact
                return None
            else:
                # Get current version
                return self.storage.get_artifact(artifact_id)
    
    def update_artifact(self, artifact_id: str, updates: Dict[str, Any], 
                       updated_by: str = "system", 
                       change_description: str = "") -> Optional[str]:
        """
        Update an artifact with new data.
        
        Args:
            artifact_id: The artifact ID
            updates: Dictionary of updates to apply
            updated_by: Who updated the artifact
            change_description: Description of the changes
            
        Returns:
            New version ID if successful, None otherwise
        """
        with self._lock:
            # Get current artifact
            artifact = self.storage.get_artifact(artifact_id)
            if not artifact:
                return None
            
            # Record old values for change tracking
            old_values = {}
            
            # Apply updates
            for key, value in updates.items():
                if hasattr(artifact, key):
                    old_values[key] = getattr(artifact, key)
                    setattr(artifact, key, value)
                elif key in artifact.content:
                    old_values[key] = artifact.content[key]
                    artifact.content[key] = value
                else:
                    old_values[key] = None
                    artifact.content[key] = value
            
            # Update timestamp
            artifact.updated_at = datetime.now()
            
            # Create new version before updating
            version = artifact.create_version(change_description or "Updated artifact")
            version_id = self.storage.store_version(version)
            
            # Update version in artifact
            artifact.version = version_id
            
            # Store updated artifact
            success = self.storage.update_artifact(artifact)
            
            if success:
                # Record changes
                for key, old_value in old_values.items():
                    new_value = updates.get(key)
                    self.change_tracker.record_change(
                        artifact_id, f"updated_{key}", old_value, new_value, updated_by
                    )
                
                # Publish event
                self.event_bus.publish_artifact_updated(
                    artifact_id, updates, updated_by, self.session_id
                )
                
                return version_id
            
            return None
    
    def delete_artifact(self, artifact_id: str, deleted_by: str = "system") -> bool:
        """
        Delete an artifact from the pool.
        
        Args:
            artifact_id: The artifact ID
            deleted_by: Who deleted the artifact
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            # Get artifact before deletion for event
            artifact = self.storage.get_artifact(artifact_id)
            if not artifact:
                return False
            
            # Delete from storage
            success = self.storage.delete_artifact(artifact_id)
            
            if success:
                # Record change
                self.change_tracker.record_change(
                    artifact_id, "deleted", artifact.to_dict(), None, deleted_by
                )
                
                # Publish event
                event = Event(
                    id=str(uuid.uuid4()),
                    type=EventType.ARTIFACT_DELETED,
                    source=deleted_by,
                    target=None,
                    payload={'artifact_id': artifact_id, 'artifact_type': artifact.type.value},
                    timestamp=datetime.now(),
                    session_id=self.session_id
                )
                self.event_bus.publish(event)
            
            return success
    
    def query_artifacts(self, query: ArtifactQuery) -> List[Artifact]:
        """
        Query artifacts based on criteria.
        
        Args:
            query: Query parameters
            
        Returns:
            List of matching artifacts
        """
        return self.storage.query_artifacts(query)
    
    def query_artifacts_by_type(self, artifact_type: ArtifactType, session_id: Optional[str] = None) -> List[Artifact]:
        """
        Query artifacts by type, optionally filtered by session ID.
        
        Args:
            artifact_type: Type of artifacts to query
            session_id: Optional session ID filter
            
        Returns:
            List of matching artifacts
        """
        query = ArtifactQuery(artifact_type=artifact_type)
        artifacts = self.storage.query_artifacts(query)
        
        # Filter by session ID if provided
        if session_id:
            # Note: This assumes artifacts have session_id in metadata or content
            # In practice, you might need to adjust this based on your artifact structure
            filtered_artifacts = []
            for artifact in artifacts:
                # Check if artifact belongs to this session
                # This is a simplified check - adjust based on your actual artifact structure
                if hasattr(artifact.metadata, 'custom_properties'):
                    artifact_session = artifact.metadata.custom_properties.get('session_id')
                    if artifact_session == session_id:
                        filtered_artifacts.append(artifact)
                else:
                    # If no session filtering in metadata, include all
                    filtered_artifacts.append(artifact)
            return filtered_artifacts
        
        return artifacts
    
    def get_artifact_history(self, artifact_id: str) -> List[ArtifactVersion]:
        """
        Get version history for an artifact.
        
        Args:
            artifact_id: The artifact ID
            
        Returns:
            List of artifact versions
        """
        return self.storage.get_versions(artifact_id)
    
    def get_artifact_changes(self, artifact_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get change history for an artifact.
        
        Args:
            artifact_id: The artifact ID
            limit: Maximum number of changes to return
            
        Returns:
            List of change records
        """
        return self.change_tracker.get_recent_changes(artifact_id, limit)
    
    def rollback_artifact(self, artifact_id: str, version_id: str, 
                         rolled_back_by: str = "system") -> bool:
        """
        Rollback an artifact to a previous version.
        
        Args:
            artifact_id: The artifact ID
            version_id: The version to rollback to
            rolled_back_by: Who performed the rollback
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            # Get the target version
            target_version = self.storage.get_version(version_id)
            if not target_version or target_version.artifact_id != artifact_id:
                return False
            
            # Get current artifact
            current_artifact = self.storage.get_artifact(artifact_id)
            if not current_artifact:
                return False
            
            # Create rollback updates
            updates = {
                'content': target_version.content.get('content', {}),
                'status': ArtifactStatus(target_version.content.get('status', 'draft'))
            }
            
            # Perform update
            new_version_id = self.update_artifact(
                artifact_id, updates, rolled_back_by, 
                f"Rolled back to version {version_id}"
            )
            
            return new_version_id is not None
    
    def set_artifact_status(self, artifact_id: str, status: ArtifactStatus, 
                           updated_by: str = "system") -> bool:
        """
        Set the status of an artifact.
        
        Args:
            artifact_id: The artifact ID
            status: New status
            updated_by: Who updated the status
            
        Returns:
            True if successful, False otherwise
        """
        updates = {'status': status}
        version_id = self.update_artifact(
            artifact_id, updates, updated_by, f"Status changed to {status.value}"
        )
        
        if version_id:
            # Publish status change event
            event = Event(
                id=str(uuid.uuid4()),
                type=EventType.ARTIFACT_STATUS_CHANGED,
                source=updated_by,
                target=None,
                payload={
                    'artifact_id': artifact_id,
                    'new_status': status.value,
                    'version_id': version_id
                },
                timestamp=datetime.now(),
                session_id=self.session_id
            )
            self.event_bus.publish(event)
            
            return True
        
        return False
    
    def link_artifacts(self, source_id: str, target_id: str, 
                      relationship: str = "related", 
                      linked_by: str = "system") -> bool:
        """
        Create a link between two artifacts.
        
        Args:
            source_id: Source artifact ID
            target_id: Target artifact ID
            relationship: Type of relationship
            linked_by: Who created the link
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            # Get source artifact
            source_artifact = self.storage.get_artifact(source_id)
            if not source_artifact:
                return False
            
            # Add to related artifacts if not already present
            if target_id not in source_artifact.metadata.related_artifacts:
                source_artifact.metadata.related_artifacts.append(target_id)
                
                # Update the artifact
                updates = {'metadata': source_artifact.metadata}
                version_id = self.update_artifact(
                    source_id, updates, linked_by, 
                    f"Linked to artifact {target_id} ({relationship})"
                )
                
                return version_id is not None
            
            return True
    
    def get_related_artifacts(self, artifact_id: str) -> List[Artifact]:
        """
        Get all artifacts related to the given artifact.
        
        Args:
            artifact_id: The artifact ID
            
        Returns:
            List of related artifacts
        """
        artifact = self.storage.get_artifact(artifact_id)
        if not artifact:
            return []
        
        related_artifacts = []
        for related_id in artifact.metadata.related_artifacts:
            related_artifact = self.storage.get_artifact(related_id)
            if related_artifact:
                related_artifacts.append(related_artifact)
        
        return related_artifacts
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the artifact pool.
        
        Returns:
            Dictionary with statistics
        """
        # Query all artifacts
        all_artifacts = self.query_artifacts(ArtifactQuery())
        
        # Count by type
        type_counts = {}
        status_counts = {}
        
        for artifact in all_artifacts:
            type_name = artifact.type.value
            status_name = artifact.status.value
            
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
            status_counts[status_name] = status_counts.get(status_name, 0) + 1
        
        return {
            'total_artifacts': len(all_artifacts),
            'by_type': type_counts,
            'by_status': status_counts,
            'session_id': self.session_id
        }