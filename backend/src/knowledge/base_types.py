"""
Base types and enums for the knowledge system in iReDev framework.
Defines core data structures and type definitions.
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json


class KnowledgeType(Enum):
    """Types of knowledge modules supported by iReDev."""
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    METHODOLOGY = "methodology"
    STANDARDS = "standards"
    TEMPLATES = "templates"
    STRATEGIES = "strategies"


class ModuleStatus(Enum):
    """Status of a knowledge module."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    UNDER_REVIEW = "under_review"
    DRAFT = "draft"


class LoadPriority(Enum):
    """Load priority levels for knowledge modules."""
    CRITICAL = 0    # Must load first
    HIGH = 1        # Load early
    NORMAL = 2      # Standard priority
    LOW = 3         # Load when needed
    OPTIONAL = 4    # Load if resources allow


@dataclass
class KnowledgeMetadata:
    """Metadata for a knowledge module."""
    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    language: str = "en"
    domain: str = ""
    confidence_score: float = 1.0
    usage_count: int = 0
    last_accessed: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "references": self.references,
            "language": self.language,
            "domain": self.domain,
            "confidence_score": self.confidence_score,
            "usage_count": self.usage_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeMetadata':
        """Create metadata from dictionary."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            author=data.get("author", ""),
            version=data.get("version", "1.0.0"),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.now().isoformat())),
            tags=data.get("tags", []),
            references=data.get("references", []),
            language=data.get("language", "en"),
            domain=data.get("domain", ""),
            confidence_score=data.get("confidence_score", 1.0),
            usage_count=data.get("usage_count", 0),
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None
        )


@dataclass
class KnowledgeDependency:
    """Represents a dependency between knowledge modules."""
    module_id: str
    version_constraint: str = "*"  # Semantic version constraint
    dependency_type: str = "required"  # required, optional, recommended
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert dependency to dictionary."""
        return {
            "module_id": self.module_id,
            "version_constraint": self.version_constraint,
            "dependency_type": self.dependency_type,
            "description": self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeDependency':
        """Create dependency from dictionary."""
        return cls(
            module_id=data.get("module_id", ""),
            version_constraint=data.get("version_constraint", "*"),
            dependency_type=data.get("dependency_type", "required"),
            description=data.get("description", "")
        )


@dataclass
class KnowledgeModule:
    """Represents a knowledge module with metadata and content."""
    id: str
    module_type: KnowledgeType
    content: Dict[str, Any]
    metadata: KnowledgeMetadata
    dependencies: List[KnowledgeDependency] = field(default_factory=list)
    status: ModuleStatus = ModuleStatus.ACTIVE
    load_priority: LoadPriority = LoadPriority.NORMAL
    checksum: str = ""
    file_path: str = ""
    
    def __post_init__(self):
        """Calculate checksum after initialization."""
        if not self.checksum:
            self.checksum = self._calculate_checksum()
    
    def _calculate_checksum(self) -> str:
        """Calculate checksum of the content for integrity verification."""
        content_str = json.dumps(self.content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()
    
    def is_valid(self) -> bool:
        """Verify the integrity of the knowledge module."""
        return self.checksum == self._calculate_checksum()
    
    def update_content(self, new_content: Dict[str, Any]) -> None:
        """Update module content and recalculate checksum."""
        self.content = new_content
        self.checksum = self._calculate_checksum()
        self.metadata.updated_at = datetime.now()
    
    def increment_usage(self) -> None:
        """Increment usage count and update last accessed time."""
        self.metadata.usage_count += 1
        self.metadata.last_accessed = datetime.now()
    
    def add_dependency(self, dependency: KnowledgeDependency) -> None:
        """Add a dependency to the module."""
        # Check if dependency already exists
        for existing_dep in self.dependencies:
            if existing_dep.module_id == dependency.module_id:
                # Update existing dependency
                existing_dep.version_constraint = dependency.version_constraint
                existing_dep.dependency_type = dependency.dependency_type
                existing_dep.description = dependency.description
                return
        
        # Add new dependency
        self.dependencies.append(dependency)
    
    def remove_dependency(self, module_id: str) -> bool:
        """Remove a dependency from the module."""
        for i, dep in enumerate(self.dependencies):
            if dep.module_id == module_id:
                del self.dependencies[i]
                return True
        return False
    
    def get_required_dependencies(self) -> List[str]:
        """Get list of required dependency module IDs."""
        return [dep.module_id for dep in self.dependencies 
                if dep.dependency_type == "required"]
    
    def get_optional_dependencies(self) -> List[str]:
        """Get list of optional dependency module IDs."""
        return [dep.module_id for dep in self.dependencies 
                if dep.dependency_type == "optional"]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert module to dictionary representation."""
        return {
            "id": self.id,
            "module_type": self.module_type.value,
            "content": self.content,
            "metadata": self.metadata.to_dict(),
            "dependencies": [dep.to_dict() for dep in self.dependencies],
            "status": self.status.value,
            "load_priority": self.load_priority.value,
            "checksum": self.checksum,
            "file_path": self.file_path
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeModule':
        """Create module from dictionary representation."""
        return cls(
            id=data.get("id", ""),
            module_type=KnowledgeType(data.get("module_type", "domain_knowledge")),
            content=data.get("content", {}),
            metadata=KnowledgeMetadata.from_dict(data.get("metadata", {})),
            dependencies=[KnowledgeDependency.from_dict(dep) for dep in data.get("dependencies", [])],
            status=ModuleStatus(data.get("status", "active")),
            load_priority=LoadPriority(data.get("load_priority", 2)),
            checksum=data.get("checksum", ""),
            file_path=data.get("file_path", "")
        )


@dataclass
class KnowledgeModuleConfig:
    """Configuration for a knowledge module."""
    module_id: str
    module_type: KnowledgeType
    file_path: str
    version: str = "1.0.0"
    enabled: bool = True
    cache_enabled: bool = True
    auto_update: bool = False
    dependencies: List[str] = field(default_factory=list)  # Simple dependency list for backward compatibility
    load_priority: int = 2  # Maps to LoadPriority enum
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "module_id": self.module_id,
            "module_type": self.module_type.value,
            "file_path": self.file_path,
            "version": self.version,
            "enabled": self.enabled,
            "cache_enabled": self.cache_enabled,
            "auto_update": self.auto_update,
            "dependencies": self.dependencies,
            "load_priority": self.load_priority,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, module_id: str, data: Dict[str, Any]) -> 'KnowledgeModuleConfig':
        """Create config from dictionary."""
        return cls(
            module_id=module_id,
            module_type=KnowledgeType(data.get("module_type", "domain_knowledge")),
            file_path=data.get("file_path", ""),
            version=data.get("version", "1.0.0"),
            enabled=data.get("enabled", True),
            cache_enabled=data.get("cache_enabled", True),
            auto_update=data.get("auto_update", False),
            dependencies=data.get("dependencies", []),
            load_priority=data.get("load_priority", 2),
            metadata=data.get("metadata", {})
        )


class KnowledgeQuery:
    """Query builder for knowledge modules."""
    
    def __init__(self):
        """Initialize query builder."""
        self.filters: Dict[str, Any] = {}
        self.sort_by: Optional[str] = None
        self.sort_order: str = "asc"
        self.limit: Optional[int] = None
        self.offset: int = 0
    
    def filter_by_type(self, knowledge_type: KnowledgeType) -> 'KnowledgeQuery':
        """Filter by knowledge type."""
        self.filters["module_type"] = knowledge_type
        return self
    
    def filter_by_status(self, status: ModuleStatus) -> 'KnowledgeQuery':
        """Filter by module status."""
        self.filters["status"] = status
        return self
    
    def filter_by_tag(self, tag: str) -> 'KnowledgeQuery':
        """Filter by tag."""
        if "tags" not in self.filters:
            self.filters["tags"] = []
        self.filters["tags"].append(tag)
        return self
    
    def filter_by_domain(self, domain: str) -> 'KnowledgeQuery':
        """Filter by domain."""
        self.filters["domain"] = domain
        return self
    
    def filter_by_author(self, author: str) -> 'KnowledgeQuery':
        """Filter by author."""
        self.filters["author"] = author
        return self
    
    def filter_by_version(self, version: str) -> 'KnowledgeQuery':
        """Filter by version."""
        self.filters["version"] = version
        return self
    
    def sort(self, field: str, order: str = "asc") -> 'KnowledgeQuery':
        """Set sort criteria."""
        self.sort_by = field
        self.sort_order = order
        return self
    
    def paginate(self, limit: int, offset: int = 0) -> 'KnowledgeQuery':
        """Set pagination."""
        self.limit = limit
        self.offset = offset
        return self
    
    def build(self) -> Dict[str, Any]:
        """Build query dictionary."""
        query = {
            "filters": self.filters,
            "sort_by": self.sort_by,
            "sort_order": self.sort_order,
            "limit": self.limit,
            "offset": self.offset
        }
        return query


class KnowledgeException(Exception):
    """Base exception for knowledge system."""
    pass


class ModuleNotFoundException(KnowledgeException):
    """Exception raised when a knowledge module is not found."""
    pass


class ModuleLoadException(KnowledgeException):
    """Exception raised when a knowledge module fails to load."""
    pass


class DependencyException(KnowledgeException):
    """Exception raised for dependency-related issues."""
    pass


class ValidationException(KnowledgeException):
    """Exception raised for validation failures."""
    pass


class VersionException(KnowledgeException):
    """Exception raised for version-related issues."""
    pass