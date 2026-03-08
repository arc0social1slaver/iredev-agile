"""
Knowledge base management system for iReDev framework.
Handles loading, versioning, and management of five types of knowledge modules.
"""

import os
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Union, Set
import logging

from .base_types import (
    KnowledgeType,
    KnowledgeModule,
    KnowledgeModuleConfig,
    KnowledgeMetadata,
    KnowledgeDependency,
    ModuleStatus,
    LoadPriority,
    KnowledgeQuery,
    KnowledgeException,
    ModuleNotFoundException,
    ModuleLoadException,
    DependencyException,
    ValidationException,
)
from .loaders import KnowledgeLoaderManager

logger = logging.getLogger(__name__)


class KnowledgeManager:
    """Manages knowledge modules for iReDev agents."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize the knowledge manager.

        Args:
            config: Knowledge base configuration dictionary.
        """
        self.config = config
        self.base_path = Path(config.get("base_path", "knowledge"))
        self.cache_enabled = config.get("cache_enabled", True)
        self.auto_reload = config.get("auto_reload", True)
        self.version_control = config.get("version_control", True)

        # Knowledge module storage
        self._modules: Dict[str, KnowledgeModule] = {}
        self._module_configs: Dict[str, KnowledgeModuleConfig] = {}
        self._type_paths: Dict[KnowledgeType, Path] = {}
        self._dependency_graph: Dict[str, Set[str]] = {}

        # Initialize loader manager
        self.loader_manager = KnowledgeLoaderManager()

        # Initialize type-specific paths
        self._initialize_paths()

        # Load module configurations
        self._load_module_configurations()

    def _initialize_paths(self) -> None:
        """Initialize paths for different knowledge types."""
        self._type_paths = {
            KnowledgeType.DOMAIN_KNOWLEDGE: Path(
                self.config.get("domain_knowledge_path", "knowledge/domains")
            ),
            KnowledgeType.METHODOLOGY: Path(
                self.config.get("methodology_path", "knowledge/methodologies")
            ),
            KnowledgeType.STANDARDS: Path(
                self.config.get("standards_path", "knowledge/standards")
            ),
            KnowledgeType.TEMPLATES: Path(
                self.config.get("templates_path", "knowledge/templates")
            ),
            KnowledgeType.STRATEGIES: Path(
                self.config.get("strategies_path", "knowledge/strategies")
            ),
        }

        # Create directories if they don't exist
        for path in self._type_paths.values():
            path.mkdir(parents=True, exist_ok=True)

    def _load_module_configurations(self) -> None:
        """Load knowledge module configurations from the file system."""
        for knowledge_type, type_path in self._type_paths.items():
            config_file = type_path / "modules.yaml"

            if config_file.exists():
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        modules_config = yaml.safe_load(f) or {}

                    for module_id, module_config in modules_config.get(
                        "modules", {}
                    ).items():
                        config_obj = KnowledgeModuleConfig(
                            module_id=module_id,
                            module_type=knowledge_type,
                            file_path=str(
                                type_path
                                / module_config.get("file", f"{module_id}.yaml")
                            ),
                            version=module_config.get("version", "1.0.0"),
                            enabled=module_config.get("enabled", True),
                            cache_enabled=module_config.get("cache_enabled", True),
                            auto_update=module_config.get("auto_update", False),
                            dependencies=module_config.get("dependencies", []),
                            load_priority=module_config.get("load_priority", 0),
                            metadata=module_config.get("metadata", {}),
                        )

                        self._module_configs[module_id] = config_obj

                        # Build dependency graph
                        self._dependency_graph[module_id] = set(config_obj.dependencies)

                except Exception as e:
                    logger.error(
                        f"Failed to load module configuration from {config_file}: {str(e)}"
                    )
            else:
                # Create default configuration file
                self._create_default_module_config(knowledge_type, config_file)

    def _create_default_module_config(
        self, knowledge_type: KnowledgeType, config_file: Path
    ) -> None:
        """Create a default module configuration file.

        Args:
            knowledge_type: Type of knowledge modules.
            config_file: Path to the configuration file.
        """
        default_modules = self._get_default_modules_for_type(knowledge_type)

        config_content = {
            "version": "1.0.0",
            "description": f"Configuration for {knowledge_type.value} modules",
            "modules": default_modules,
        }

        try:
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_content, f, default_flow_style=False, indent=2)

            logger.info(f"Created default module configuration: {config_file}")
        except Exception as e:
            logger.error(
                f"Failed to create default configuration {config_file}: {str(e)}"
            )

    def _get_default_modules_for_type(
        self, knowledge_type: KnowledgeType
    ) -> Dict[str, Any]:
        """Get default module configurations for a knowledge type.

        Args:
            knowledge_type: Type of knowledge modules.

        Returns:
            Dictionary of default module configurations.
        """
        defaults = {
            KnowledgeType.DOMAIN_KNOWLEDGE: {
                "software_engineering": {
                    "file": "software_engineering.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "General software engineering domain knowledge",
                },
                "web_development": {
                    "file": "web_development.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "Web development specific knowledge",
                },
            },
            KnowledgeType.METHODOLOGY: {
                "requirements_elicitation": {
                    "file": "requirements_elicitation.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "Requirements elicitation methodologies",
                },
                "5w1h_methodology": {
                    "file": "5w1h.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "5W1H questioning methodology",
                },
                "socratic_questioning": {
                    "file": "socratic_questioning.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "Socratic questioning techniques",
                },
            },
            KnowledgeType.STANDARDS: {
                "ieee_830": {
                    "file": "ieee_830.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "IEEE 830 standard for SRS",
                },
                "iso_29148": {
                    "file": "iso_29148.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "ISO/IEC/IEEE 29148 requirements engineering standard",
                },
            },
            KnowledgeType.TEMPLATES: {
                "srs_template": {
                    "file": "srs_template.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "Standard SRS document template",
                },
                "user_story_template": {
                    "file": "user_story_template.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "User story template",
                },
            },
            KnowledgeType.STRATEGIES: {
                "moscow_prioritization": {
                    "file": "moscow.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "MoSCoW prioritization strategy",
                },
                "interview_techniques": {
                    "file": "interview_techniques.yaml",
                    "version": "1.0.0",
                    "enabled": True,
                    "description": "Interview techniques and strategies",
                },
            },
        }

        return defaults.get(knowledge_type, {})

    def load_module(
        self, module_id: str, force_reload: bool = False
    ) -> Optional[KnowledgeModule]:
        """Load a knowledge module by ID.

        Args:
            module_id: ID of the module to load.
            force_reload: Force reload even if cached.

        Returns:
            Loaded knowledge module or None if not found.
        """
        # Check cache first
        if not force_reload and self.cache_enabled and module_id in self._modules:
            cached_module = self._modules[module_id]
            if cached_module.is_valid():
                return cached_module
            else:
                logger.warning(
                    f"Cached module {module_id} failed integrity check, reloading"
                )

        # Get module configuration
        config = self._module_configs.get(module_id)
        if not config or not config.enabled:
            logger.warning(f"Module {module_id} not found or disabled")
            return None

        # Load dependencies first
        for dep_id in config.dependencies:
            if dep_id not in self._modules:
                dep_module = self.load_module(dep_id, force_reload)
                if not dep_module:
                    logger.error(
                        f"Failed to load dependency {dep_id} for module {module_id}"
                    )
                    return None

        # Load the module using specialized loader
        try:
            # Use the appropriate loader for this knowledge type
            module = self.loader_manager.load_module(
                knowledge_type=config.module_type,
                module_id=module_id,
                file_path=config.file_path,
                config=config.to_dict(),
            )

            # Cache the module
            if self.cache_enabled:
                self._modules[module_id] = module

            logger.info(f"Loaded knowledge module: {module_id} v{config.version}")
            return module

        except Exception as e:
            if isinstance(
                e, (ModuleNotFoundException, ValidationException, KnowledgeException)
            ):
                raise
            logger.error(f"Failed to load module {module_id}: {str(e)}")
            raise ModuleLoadException(f"Failed to load module {module_id}: {str(e)}")

    def load_modules_by_type(
        self, knowledge_type: KnowledgeType, force_reload: bool = False
    ) -> List[KnowledgeModule]:
        """Load all modules of a specific type.

        Args:
            knowledge_type: Type of knowledge modules to load.
            force_reload: Force reload even if cached.

        Returns:
            List of loaded knowledge modules.
        """
        modules = []

        # Get modules of the specified type
        type_modules = [
            (config.module_id, config)
            for config in self._module_configs.values()
            if config.module_type == knowledge_type and config.enabled
        ]

        # Sort by load priority
        type_modules.sort(key=lambda x: x[1].load_priority)

        # Load modules
        for module_id, config in type_modules:
            module = self.load_module(module_id, force_reload)
            if module:
                modules.append(module)

        return modules

    def load_modules_for_agent(
        self, agent_name: str, module_names: List[str], force_reload: bool = False
    ) -> List[KnowledgeModule]:
        """Load specific modules for an agent.

        Args:
            agent_name: Name of the agent.
            module_names: List of module names to load.
            force_reload: Force reload even if cached.

        Returns:
            List of loaded knowledge modules.
        """
        modules = []

        for module_name in module_names:
            module = self.load_module(module_name, force_reload)
            if module:
                modules.append(module)
            else:
                logger.warning(
                    f"Failed to load module {module_name} for agent {agent_name}"
                )

        return modules

    def get_module_info(self, module_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a module without loading it.

        Args:
            module_id: ID of the module.

        Returns:
            Module information dictionary or None if not found.
        """
        config = self._module_configs.get(module_id)
        if not config:
            return None

        return {
            "id": module_id,
            "type": config.module_type.value,
            "version": config.version,
            "enabled": config.enabled,
            "file_path": config.file_path,
            "dependencies": config.dependencies,
            "metadata": config.metadata,
        }

    def list_available_modules(
        self, knowledge_type: Optional[KnowledgeType] = None
    ) -> List[Dict[str, Any]]:
        """List all available modules, optionally filtered by type.

        Args:
            knowledge_type: Optional filter by knowledge type.

        Returns:
            List of module information dictionaries.
        """
        modules = []

        for module_id, config in self._module_configs.items():
            if knowledge_type is None or config.module_type == knowledge_type:
                modules.append(
                    {
                        "id": module_id,
                        "name": config.metadata.get("name", module_id),
                        "type": config.module_type.value,
                        "version": config.version,
                        "enabled": config.enabled,
                        "description": config.metadata.get("description", ""),
                    }
                )

        return modules

    def reload_all_modules(self) -> None:
        """Reload all cached modules."""
        logger.info("Reloading all knowledge modules")

        # Clear cache
        self._modules.clear()

        # Reload configurations
        self._load_module_configurations()

        # Reload all enabled modules
        for module_id, config in self._module_configs.items():
            if config.enabled:
                self.load_module(module_id, force_reload=True)

    def validate_dependencies(self) -> List[str]:
        """Validate module dependencies.

        Returns:
            List of dependency validation errors.
        """
        errors = []

        for module_id, dependencies in self._dependency_graph.items():
            for dep_id in dependencies:
                if dep_id not in self._module_configs:
                    errors.append(
                        f"Module {module_id} depends on non-existent module {dep_id}"
                    )
                elif not self._module_configs[dep_id].enabled:
                    errors.append(
                        f"Module {module_id} depends on disabled module {dep_id}"
                    )

        # Check for circular dependencies
        circular_deps = self._detect_circular_dependencies()
        if circular_deps:
            errors.append(f"Circular dependencies detected: {circular_deps}")

        return errors

    def _detect_circular_dependencies(self) -> List[List[str]]:
        """Detect circular dependencies in the module graph.

        Returns:
            List of circular dependency chains.
        """
        visited = set()
        rec_stack = set()
        cycles = []

        def dfs(node: str, path: List[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self._dependency_graph.get(node, set()):
                if neighbor not in visited:
                    dfs(neighbor, path.copy())
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])

            rec_stack.remove(node)

        for module_id in self._dependency_graph:
            if module_id not in visited:
                dfs(module_id, [])

        return cycles

    def _validate_module(self, module: KnowledgeModule) -> bool:
        """Validate a knowledge module.

        Args:
            module: Module to validate.

        Returns:
            True if valid, False otherwise.
        """
        try:
            # Check basic structure
            if not module.id or not module.content:
                logger.error(f"Module {module.id} missing required fields")
                return False

            # Check content integrity
            if not module.is_valid():
                logger.error(f"Module {module.id} failed integrity check")
                return False

            # Validate content structure based on type
            if not self._validate_content_structure(module):
                logger.error(f"Module {module.id} has invalid content structure")
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating module {module.id}: {str(e)}")
            return False

    def _validate_content_structure(self, module: KnowledgeModule) -> bool:
        """Validate content structure based on module type.

        Args:
            module: Module to validate.

        Returns:
            True if structure is valid.
        """
        content = module.content

        # Common required fields
        if "name" not in content or "description" not in content:
            return False

        # Type-specific validation
        if module.module_type == KnowledgeType.DOMAIN_KNOWLEDGE:
            return self._validate_domain_knowledge(content)
        elif module.module_type == KnowledgeType.METHODOLOGY:
            return self._validate_methodology(content)
        elif module.module_type == KnowledgeType.STANDARDS:
            return self._validate_standards(content)
        elif module.module_type == KnowledgeType.TEMPLATES:
            return self._validate_templates(content)
        elif module.module_type == KnowledgeType.STRATEGIES:
            return self._validate_strategies(content)

        return True

    def _validate_domain_knowledge(self, content: Dict[str, Any]) -> bool:
        """Validate domain knowledge content structure."""
        required_fields = ["content"]
        return all(field in content for field in required_fields)

    def _validate_methodology(self, content: Dict[str, Any]) -> bool:
        """Validate methodology content structure."""
        required_fields = ["content"]
        return all(field in content for field in required_fields)

    def _validate_standards(self, content: Dict[str, Any]) -> bool:
        """Validate standards content structure."""
        required_fields = ["content"]
        return all(field in content for field in required_fields)

    def _validate_templates(self, content: Dict[str, Any]) -> bool:
        """Validate templates content structure."""
        required_fields = ["content"]
        return all(field in content for field in required_fields)

    def _validate_strategies(self, content: Dict[str, Any]) -> bool:
        """Validate strategies content structure."""
        required_fields = ["content"]
        return all(field in content for field in required_fields)

    def query_modules(self, query: KnowledgeQuery) -> List[KnowledgeModule]:
        """Query knowledge modules using structured query.

        Args:
            query: Knowledge query object.

        Returns:
            List of matching modules.
        """
        query_dict = query.build()
        filters = query_dict["filters"]

        # Get all modules (cached and load if needed)
        all_modules = []
        for module_id in self._module_configs:
            module = self.load_module(module_id)
            if module:
                all_modules.append(module)

        # Apply filters
        filtered_modules = []
        for module in all_modules:
            if self._matches_filters(module, filters):
                filtered_modules.append(module)

        # Apply sorting
        if query_dict["sort_by"]:
            reverse = query_dict["sort_order"] == "desc"
            filtered_modules.sort(
                key=lambda m: self._get_sort_value(m, query_dict["sort_by"]),
                reverse=reverse,
            )

        # Apply pagination
        start = query_dict["offset"]
        end = start + query_dict["limit"] if query_dict["limit"] else None

        return filtered_modules[start:end]

    def _matches_filters(
        self, module: KnowledgeModule, filters: Dict[str, Any]
    ) -> bool:
        """Check if module matches query filters."""
        for field, value in filters.items():
            if field == "module_type" and module.module_type != value:
                return False
            elif field == "status" and module.status != value:
                return False
            elif field == "tags" and not any(
                tag in module.metadata.tags for tag in value
            ):
                return False
            elif field == "domain" and module.metadata.domain != value:
                return False
            elif field == "author" and module.metadata.author != value:
                return False
            elif field == "version" and module.metadata.version != value:
                return False

        return True

    def _get_sort_value(self, module: KnowledgeModule, field: str) -> Any:
        """Get sort value for a module field."""
        if field == "name":
            return module.metadata.name
        elif field == "created_at":
            return module.metadata.created_at
        elif field == "updated_at":
            return module.metadata.updated_at
        elif field == "usage_count":
            return module.metadata.usage_count
        elif field == "confidence_score":
            return module.metadata.confidence_score
        else:
            return ""

    def get_module_statistics(self) -> Dict[str, Any]:
        """Get statistics about knowledge modules.

        Returns:
            Dictionary with module statistics.
        """
        stats = {
            "total_modules": len(self._module_configs),
            "active_modules": 0,
            "cached_modules": len(self._modules),
            "by_type": {},
            "by_status": {},
            "total_usage": 0,
            "average_confidence": 0.0,
        }

        # Initialize counters
        for knowledge_type in KnowledgeType:
            stats["by_type"][knowledge_type.value] = 0

        for status in ModuleStatus:
            stats["by_status"][status.value] = 0

        # Count modules
        total_confidence = 0.0
        active_count = 0

        for module_id, config in self._module_configs.items():
            if config.enabled:
                stats["active_modules"] += 1
                active_count += 1

            stats["by_type"][config.module_type.value] += 1

            # Get module if cached for detailed stats
            if module_id in self._modules:
                module = self._modules[module_id]
                stats["by_status"][module.status.value] += 1
                stats["total_usage"] += module.metadata.usage_count
                total_confidence += module.metadata.confidence_score

        # Calculate averages
        if active_count > 0:
            stats["average_confidence"] = total_confidence / active_count

        return stats

    def update_module(self, module_id: str, new_content: Dict[str, Any]) -> bool:
        """Update a knowledge module's content.

        Args:
            module_id: ID of the module to update.
            new_content: New content for the module.

        Returns:
            True if successful, False otherwise.
        """
        try:
            module = self.load_module(module_id)
            if not module:
                raise ModuleNotFoundException(f"Module not found: {module_id}")

            # Update content
            module.update_content(new_content)

            # Validate updated module
            if not self._validate_module(module):
                raise ValidationException(
                    f"Updated module validation failed: {module_id}"
                )

            # Save to file if file path is available
            if module.file_path:
                self._save_module_to_file(module)

            logger.info(f"Updated knowledge module: {module_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update module {module_id}: {str(e)}")
            return False

    def _save_module_to_file(self, module: KnowledgeModule) -> None:
        """Save module content to file.

        Args:
            module: Module to save.
        """
        try:
            file_path = Path(module.file_path)

            # Prepare content for saving
            save_content = module.content.copy()
            save_content["metadata"] = module.metadata.to_dict()

            with open(file_path, "w", encoding="utf-8") as f:
                if file_path.suffix.lower() == ".json":
                    json.dump(save_content, f, indent=2, default=str)
                else:
                    yaml.dump(save_content, f, default_flow_style=False, indent=2)

            logger.debug(f"Saved module to file: {file_path}")

        except Exception as e:
            logger.error(f"Failed to save module {module.id} to file: {str(e)}")
            raise

    def create_module_template(
        self, knowledge_type: KnowledgeType, module_id: str
    ) -> str:
        """Create a template file for a new knowledge module.

        Args:
            knowledge_type: Type of the knowledge module.
            module_id: ID of the new module.

        Returns:
            Path to the created template file.
        """
        type_path = self._type_paths[knowledge_type]
        template_path = type_path / f"{module_id}.yaml"

        template_content = {
            "name": module_id.replace("_", " ").title(),
            "version": "1.0.0",
            "description": f"Knowledge module for {module_id}",
            "type": knowledge_type.value,
            "created_at": datetime.now().isoformat(),
            "content": {
                "description": f"Content for {knowledge_type.value} module",
                "data": {},
            },
            "metadata": {"author": "iReDev Framework", "tags": [], "references": []},
        }

        try:
            with open(template_path, "w", encoding="utf-8") as f:
                yaml.dump(template_content, f, default_flow_style=False, indent=2)

            logger.info(f"Created module template: {template_path}")
            return str(template_path)

        except Exception as e:
            logger.error(f"Failed to create module template {template_path}: {str(e)}")
            raise


class KnowledgeManagerError(Exception):
    """Exception raised for knowledge manager related errors."""

    pass
