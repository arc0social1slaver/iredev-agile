"""
Artifact data models for the iReDev framework.

This module defines the core data structures for artifacts, including
metadata, versioning, and query capabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
import json
import uuid


class ArtifactType(Enum):
    """Types of artifacts in the iReDev system."""

    INTERVIEW_RECORD = "interview_record"
    USER_PERSONA = "user_persona"
    USER_PERSONAS = "user_personas"  # Collection of personas
    USER_SCENARIO = "user_scenario"
    USER_SCENARIOS = "user_scenarios"  # Collection of scenarios
    DEPLOYMENT_CONSTRAINTS = "deployment_constraints"
    USER_REQUIREMENTS_LIST = "user_requirements_list"
    REQUIREMENT_MODEL = "requirement_model"
    SRS_DOCUMENT = "srs_document"
    REVIEW_REPORT = "review_report"
    PAIN_POINTS = "pain_points"
    NON_FUNCTIONAL_REQUIREMENTS = "non_functional_requirements"
    PRODUCT_BACKLOG = "product_backlog"
    SPRINT_BACKLOG = "sprint_backlog"


class ArtifactStatus(Enum):
    """Status of artifacts in the system."""

    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass
class ArtifactMetadata:
    """Metadata associated with an artifact."""

    tags: List[str] = field(default_factory=list)
    source_agent: Optional[str] = None
    related_artifacts: List[str] = field(default_factory=list)
    quality_score: Optional[float] = None
    review_comments: List[str] = field(default_factory=list)
    custom_properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "tags": self.tags,
            "source_agent": self.source_agent,
            "related_artifacts": self.related_artifacts,
            "quality_score": self.quality_score,
            "review_comments": self.review_comments,
            "custom_properties": self.custom_properties,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactMetadata":
        """Create metadata from dictionary."""
        return cls(
            tags=data.get("tags", []),
            source_agent=data.get("source_agent"),
            related_artifacts=data.get("related_artifacts", []),
            quality_score=data.get("quality_score"),
            review_comments=data.get("review_comments", []),
            custom_properties=data.get("custom_properties", {}),
        )


@dataclass
class ArtifactVersion:
    """Represents a version of an artifact."""

    version_id: str
    artifact_id: str
    content: Dict[str, Any]
    metadata: ArtifactMetadata
    created_at: datetime
    created_by: str
    change_description: str = ""
    parent_version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert version to dictionary."""
        return {
            "version_id": self.version_id,
            "artifact_id": self.artifact_id,
            "content": self.content,
            "metadata": self.metadata.to_dict(),
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "change_description": self.change_description,
            "parent_version": self.parent_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactVersion":
        """Create version from dictionary."""
        return cls(
            version_id=data["version_id"],
            artifact_id=data["artifact_id"],
            content=data["content"],
            metadata=ArtifactMetadata.from_dict(data["metadata"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data["created_by"],
            change_description=data.get("change_description", ""),
            parent_version=data.get("parent_version"),
        )


@dataclass
class Artifact:
    """Core artifact class representing any piece of work in the iReDev system."""

    id: str
    type: ArtifactType
    content: Dict[str, Any]
    metadata: ArtifactMetadata
    version: str
    created_at: datetime
    updated_at: datetime
    created_by: str
    status: ArtifactStatus = ArtifactStatus.DRAFT

    def __post_init__(self):
        """Ensure ID is set if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert artifact to dictionary for serialization."""
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "metadata": self.metadata.to_dict(),
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Artifact":
        """Create artifact from dictionary."""
        return cls(
            id=data["id"],
            type=ArtifactType(data["type"]),
            content=data["content"],
            metadata=ArtifactMetadata.from_dict(data["metadata"]),
            version=data["version"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data["created_by"],
            status=ArtifactStatus(data["status"]),
        )

    def to_json(self) -> str:
        """Convert artifact to JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "Artifact":
        """Create artifact from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def create_version(self, change_description: str = "") -> ArtifactVersion:
        """Create a version snapshot of the current artifact."""
        return ArtifactVersion(
            version_id=str(uuid.uuid4()),
            artifact_id=self.id,
            content=self.content.copy(),
            metadata=ArtifactMetadata.from_dict(self.metadata.to_dict()),
            created_at=datetime.now(),
            created_by=self.created_by,
            change_description=change_description,
            parent_version=self.version,
        )


@dataclass
class ArtifactQuery:
    """Query parameters for searching artifacts."""

    artifact_type: Optional[ArtifactType] = None
    status: Optional[ArtifactStatus] = None
    created_by: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    content_contains: Optional[str] = None
    related_to: Optional[str] = None
    limit: Optional[int] = None
    offset: int = 0

    def matches(self, artifact: Artifact) -> bool:
        """Check if an artifact matches this query."""
        # Type filter
        if self.artifact_type and artifact.type != self.artifact_type:
            return False

        # Status filter
        if self.status and artifact.status != self.status:
            return False

        # Creator filter
        if self.created_by and artifact.created_by != self.created_by:
            return False

        # Tags filter
        if self.tags and not any(tag in artifact.metadata.tags for tag in self.tags):
            return False

        # Date filters
        if self.created_after and artifact.created_at < self.created_after:
            return False

        if self.created_before and artifact.created_at > self.created_before:
            return False

        # Content search
        if self.content_contains:
            content_str = json.dumps(artifact.content, ensure_ascii=False).lower()
            if self.content_contains.lower() not in content_str:
                return False

        # Related artifacts filter
        if (
            self.related_to
            and self.related_to not in artifact.metadata.related_artifacts
        ):
            return False

        return True
