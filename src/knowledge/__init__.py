# Knowledge management module for iReDev framework

from .base_types import (
    KnowledgeType,
    KnowledgeModule,
    KnowledgeMetadata,
    KnowledgeDependency,
    KnowledgeModuleConfig,
    ModuleStatus,
    LoadPriority,
    KnowledgeQuery,
    KnowledgeException,
    ModuleNotFoundException,
    ModuleLoadException,
    DependencyException,
    ValidationException,
    VersionException,
)

from .knowledge_manager import KnowledgeManager
from .version_manager import KnowledgeVersionManager, KnowledgeUpdateManager
from .dynamic_loader import DynamicKnowledgeLoader, LoaderConfig
from .cot_engine import ChainOfThoughtEngine, CoTProcess, CoTStep, ReasoningStep
from .loaders import (
    BaseKnowledgeLoader,
    DomainKnowledgeLoader,
    MethodologyLoader,
    StandardsLoader,
    TemplatesLoader,
    StrategiesLoader,
    KnowledgeLoaderFactory,
    KnowledgeLoaderManager,
)

__all__ = [
    # Base types
    "KnowledgeType",
    "KnowledgeModule",
    "KnowledgeMetadata",
    "KnowledgeDependency",
    "KnowledgeModuleConfig",
    "ModuleStatus",
    "LoadPriority",
    "KnowledgeQuery",
    "KnowledgeException",
    "ModuleNotFoundException",
    "ModuleLoadException",
    "DependencyException",
    "ValidationException",
    "VersionException",
    # Core managers
    "KnowledgeManager",
    "KnowledgeVersionManager",
    "KnowledgeUpdateManager",
    "DynamicKnowledgeLoader",
    "LoaderConfig",
    # Chain-of-Thought engine
    "ChainOfThoughtEngine",
    "CoTProcess",
    "CoTStep",
    "ReasoningStep",
    # Loaders
    "BaseKnowledgeLoader",
    "DomainKnowledgeLoader",
    "MethodologyLoader",
    "StandardsLoader",
    "TemplatesLoader",
    "StrategiesLoader",
    "KnowledgeLoaderFactory",
    "KnowledgeLoaderManager",
]
