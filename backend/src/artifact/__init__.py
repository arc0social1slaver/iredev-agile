"""
iReDev Artifact System

This module provides the core artifact management system for the iReDev framework,
including data models, storage interfaces, and event-driven mechanisms.
"""

from .models import (
    Artifact,
    ArtifactMetadata,
    ArtifactVersion,
    ArtifactType,
    ArtifactStatus,
    ArtifactQuery
)

from .storage import (
    ArtifactStorage,
    MemoryArtifactStorage,
    FileSystemArtifactStorage
)

from .events import (
    Event,
    EventType,
    EventBus,
    EventHandler
)

from .pool import ArtifactPool

__all__ = [
    'Artifact',
    'ArtifactMetadata', 
    'ArtifactVersion',
    'ArtifactType',
    'ArtifactStatus',
    'ArtifactQuery',
    'ArtifactStorage',
    'MemoryArtifactStorage',
    'FileSystemArtifactStorage',
    'Event',
    'EventType',
    'EventBus',
    'EventHandler',
    'ArtifactPool'
]