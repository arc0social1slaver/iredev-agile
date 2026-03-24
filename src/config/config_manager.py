"""
Configuration management system for iReDev framework.
Extends the existing configuration system to support complex iReDev requirements.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class KnowledgeType(Enum):
    """Types of knowledge modules supported by iReDev."""
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    METHODOLOGY = "methodology"
    STANDARDS = "standards"
    TEMPLATES = "templates"
    STRATEGIES = "strategies"


@dataclass
class KnowledgeModuleConfig:
    """Configuration for a knowledge module."""
    module_type: KnowledgeType
    path: str
    version: str = "1.0.0"
    enabled: bool = True
    cache_enabled: bool = True
    auto_update: bool = False
    dependencies: List[str] = field(default_factory=list)


@dataclass
class AgentConfig:
    """Configuration for an individual agent."""
    name: str
    llm_config: str = "default"
    knowledge_modules: List[str] = field(default_factory=list)
    max_turns: int = 50
    timeout_seconds: int = 300
    memory_limit_mb: int = 512
    enabled: bool = True
    custom_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HumanInLoopConfig:
    """Configuration for human-in-the-loop mechanisms."""
    enabled: bool = True
    review_points: List[str] = field(default_factory=lambda: [
        "url_generation", "model_creation", "srs_generation"
    ])
    timeout_minutes: int = 1440  # 24 hours
    notification_channels: List[str] = field(default_factory=lambda: ["email"])
    auto_approve_after_timeout: bool = False
    require_explicit_approval: bool = True


@dataclass
class ArtifactPoolConfig:
    """Configuration for the artifact pool."""
    storage_backend: str = "memory"
    storage_path: str = "artifacts"
    version_control: bool = True
    backup_enabled: bool = True
    backup_interval_minutes: int = 60
    max_versions_per_artifact: int = 10
    compression_enabled: bool = True


@dataclass
class iReDevConfig:
    """Main configuration class for iReDev framework."""
    # Base configuration (inherited from existing system)
    llm: Dict[str, Any] = field(default_factory=dict)
    rate_limits: Dict[str, Any] = field(default_factory=dict)
    flow_control: Dict[str, Any] = field(default_factory=dict)
    
    # iReDev specific configurations
    agents: Dict[str, AgentConfig] = field(default_factory=dict)
    knowledge_base: Dict[str, Any] = field(default_factory=dict)
    knowledge_modules: Dict[str, KnowledgeModuleConfig] = field(default_factory=dict)
    human_in_loop: HumanInLoopConfig = field(default_factory=HumanInLoopConfig)
    artifact_pool: ArtifactPoolConfig = field(default_factory=ArtifactPoolConfig)
    
    # System configuration
    logging_level: str = "INFO"
    debug_mode: bool = False
    metrics_enabled: bool = True
    
    @classmethod
    def get_default_config(cls) -> 'iReDevConfig':
        """Get default configuration with sensible defaults."""
        config = cls()
        
        # Set default knowledge base paths
        config.knowledge_base = {
            "base_path": "knowledge",
            "domain_knowledge_path": "knowledge/domains",
            "methodology_path": "knowledge/methodologies", 
            "standards_path": "knowledge/standards",
            "templates_path": "knowledge/templates",
            "strategies_path": "knowledge/strategies",
            "cache_enabled": True,
            "auto_reload": True
        }
        
        # Set default agents
        config.agents = {
            "interviewer": AgentConfig(
                name="interviewer",
                knowledge_modules=["requirements_elicitation", "interview_techniques"],
                max_turns=50
            ),
            "enduser": AgentConfig(
                name="enduser", 
                knowledge_modules=["user_experience", "persona_modeling"],
                max_turns=30
            ),
            "deployer": AgentConfig(
                name="deployer",
                knowledge_modules=["system_architecture", "security", "compliance"],
                max_turns=20
            ),
            "analyst": AgentConfig(
                name="analyst",
                knowledge_modules=["requirements_analysis", "system_modeling", "traceability"],
                max_turns=40
            ),
            "archivist": AgentConfig(
                name="archivist",
                knowledge_modules=["ieee_830", "iso_29148", "technical_writing"],
                max_turns=25
            ),
            "reviewer": AgentConfig(
                name="reviewer",
                knowledge_modules=["quality_assurance", "validation", "verification"],
                max_turns=35
            )
        }
        
        return config


class ConfigManager:
    """Manages configuration loading, validation, and inheritance for iReDev framework."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the configuration manager.
        
        Args:
            config_path: Path to the configuration file. If None, uses default paths.
        """
        self.config_path = config_path or self._find_config_file()
        self._config: Optional[iReDevConfig] = None
        self._config_cache: Dict[str, Any] = {}
        
    def _find_config_file(self) -> str:
        """Find the configuration file in standard locations."""
        possible_paths = [
            "config/iredev_config.yaml",
            "config/agent_config.yaml",  # Fallback to existing config
            "iredev_config.yaml",
            os.path.expanduser("~/.iredev/config.yaml")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
                
        # Return default path if none found
        return "config/iredev_config.yaml"
    
    def load_config(self, force_reload: bool = False) -> iReDevConfig:
        """Load configuration from file with validation and defaults.
        
        Args:
            force_reload: Force reload even if config is cached.
            
        Returns:
            Loaded and validated configuration.
            
        Raises:
            ConfigurationError: If configuration is invalid.
        """
        if self._config is not None and not force_reload:
            return self._config
            
        try:
            # Start with default configuration
            config = iReDevConfig.get_default_config()
            
            # Load from file if it exists
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    file_config = yaml.safe_load(f) or {}
                
                # Merge file config with defaults
                config = self._merge_configs(config, file_config)
            else:
                logger.warning(f"Configuration file not found at {self.config_path}, using defaults")
            
            # Validate configuration
            self._validate_config(config)
            
            self._config = config
            return config
            
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {str(e)}") from e
    
    def _merge_configs(self, base_config: iReDevConfig, file_config: Dict[str, Any]) -> iReDevConfig:
        """Merge file configuration with base configuration.
        
        Args:
            base_config: Base configuration with defaults.
            file_config: Configuration loaded from file.
            
        Returns:
            Merged configuration.
        """
        # Handle base LLM configuration (backward compatibility)
        if "llm" in file_config:
            base_config.llm = file_config["llm"]
        if "rate_limits" in file_config:
            base_config.rate_limits = file_config["rate_limits"]
        if "flow_control" in file_config:
            base_config.flow_control = file_config["flow_control"]
            
        # Handle iReDev specific configuration
        if "iredev" in file_config:
            iredev_config = file_config["iredev"]
            
            # Merge agents configuration
            if "agents" in iredev_config:
                for agent_name, agent_config in iredev_config["agents"].items():
                    if agent_name in base_config.agents:
                        # Update existing agent config
                        existing = base_config.agents[agent_name]
                        for key, value in agent_config.items():
                            setattr(existing, key, value)
                    else:
                        # Add new agent config
                        base_config.agents[agent_name] = AgentConfig(
                            name=agent_name, **agent_config
                        )
            
            # Merge knowledge base configuration
            if "knowledge_base" in iredev_config:
                base_config.knowledge_base.update(iredev_config["knowledge_base"])
            
            # Merge human in loop configuration
            if "human_in_loop" in iredev_config:
                hil_config = iredev_config["human_in_loop"]
                for key, value in hil_config.items():
                    setattr(base_config.human_in_loop, key, value)
            
            # Merge artifact pool configuration
            if "artifact_pool" in iredev_config:
                ap_config = iredev_config["artifact_pool"]
                for key, value in ap_config.items():
                    setattr(base_config.artifact_pool, key, value)
            
            # Handle other top-level iReDev configs
            for key in ["logging_level", "debug_mode", "metrics_enabled"]:
                if key in iredev_config:
                    setattr(base_config, key, iredev_config[key])
        
        return base_config
    
    def _validate_config(self, config: iReDevConfig) -> None:
        """Validate the configuration for consistency and completeness.
        
        Args:
            config: Configuration to validate.
            
        Raises:
            ConfigurationError: If configuration is invalid.
        """
        errors = []
        
        # Validate LLM configuration
        if not config.llm:
            errors.append("LLM configuration is required")
        elif "type" not in config.llm:
            errors.append("LLM type must be specified")
        
        # Validate agent configurations
        for agent_name, agent_config in config.agents.items():
            if not agent_config.name:
                errors.append(f"Agent {agent_name} must have a name")
            if agent_config.max_turns <= 0:
                errors.append(f"Agent {agent_name} max_turns must be positive")
            if agent_config.timeout_seconds <= 0:
                errors.append(f"Agent {agent_name} timeout_seconds must be positive")
        
        # Validate knowledge base paths
        if config.knowledge_base:
            base_path = config.knowledge_base.get("base_path", "knowledge")
            if not isinstance(base_path, str):
                errors.append("Knowledge base path must be a string")
        
        # Validate human in loop configuration
        if config.human_in_loop.timeout_minutes <= 0:
            errors.append("Human in loop timeout must be positive")
        
        if errors:
            raise ConfigurationError("Configuration validation failed: " + "; ".join(errors))
    
    def get_agent_config(self, agent_name: str) -> Optional[AgentConfig]:
        """Get configuration for a specific agent.
        
        Args:
            agent_name: Name of the agent.
            
        Returns:
            Agent configuration or None if not found.
        """
        config = self.load_config()
        return config.agents.get(agent_name)
    
    def get_knowledge_module_config(self, module_name: str) -> Optional[KnowledgeModuleConfig]:
        """Get configuration for a specific knowledge module.
        
        Args:
            module_name: Name of the knowledge module.
            
        Returns:
            Knowledge module configuration or None if not found.
        """
        config = self.load_config()
        return config.knowledge_modules.get(module_name)
    
    def get_llm_config(self, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """Get LLM configuration for an agent or default.
        
        Args:
            agent_name: Name of the agent. If None, returns default LLM config.
            
        Returns:
            LLM configuration dictionary.
        """
        config = self.load_config()
        
        # Check for agent-specific LLM config
        if agent_name:
            agent_config = config.agents.get(agent_name)
            if agent_config and agent_config.llm_config != "default":
                # Return agent-specific LLM config if available
                # This would need to be implemented based on specific requirements
                pass
        
        return config.llm
    
    def save_config(self, config: iReDevConfig, path: Optional[str] = None) -> None:
        """Save configuration to file.
        
        Args:
            config: Configuration to save.
            path: Optional path to save to. If None, uses current config path.
        """
        save_path = path or self.config_path
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # Convert config to dictionary for YAML serialization
        config_dict = self._config_to_dict(config)
        
        with open(save_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_dict, f, default_flow_style=False, indent=2)
        
        logger.info(f"Configuration saved to {save_path}")
    
    def _config_to_dict(self, config: iReDevConfig) -> Dict[str, Any]:
        """Convert configuration object to dictionary for serialization.
        
        Args:
            config: Configuration object.
            
        Returns:
            Configuration as dictionary.
        """
        # This is a simplified version - in practice, you'd want more sophisticated
        # serialization that handles dataclasses properly
        return {
            "llm": config.llm,
            "rate_limits": config.rate_limits,
            "flow_control": config.flow_control,
            "iredev": {
                "agents": {
                    name: {
                        "llm_config": agent.llm_config,
                        "knowledge_modules": agent.knowledge_modules,
                        "max_turns": agent.max_turns,
                        "timeout_seconds": agent.timeout_seconds,
                        "memory_limit_mb": agent.memory_limit_mb,
                        "enabled": agent.enabled,
                        "custom_params": agent.custom_params
                    }
                    for name, agent in config.agents.items()
                },
                "knowledge_base": config.knowledge_base,
                "human_in_loop": {
                    "enabled": config.human_in_loop.enabled,
                    "review_points": config.human_in_loop.review_points,
                    "timeout_minutes": config.human_in_loop.timeout_minutes,
                    "notification_channels": config.human_in_loop.notification_channels,
                    "auto_approve_after_timeout": config.human_in_loop.auto_approve_after_timeout,
                    "require_explicit_approval": config.human_in_loop.require_explicit_approval
                },
                "artifact_pool": {
                    "storage_backend": config.artifact_pool.storage_backend,
                    "storage_path": config.artifact_pool.storage_path,
                    "version_control": config.artifact_pool.version_control,
                    "backup_enabled": config.artifact_pool.backup_enabled,
                    "backup_interval_minutes": config.artifact_pool.backup_interval_minutes,
                    "max_versions_per_artifact": config.artifact_pool.max_versions_per_artifact,
                    "compression_enabled": config.artifact_pool.compression_enabled
                },
                "logging_level": config.logging_level,
                "debug_mode": config.debug_mode,
                "metrics_enabled": config.metrics_enabled
            }
        }


class ConfigurationError(Exception):
    """Exception raised for configuration-related errors."""
    pass


# Global configuration manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(config_path: Optional[str] = None) -> ConfigManager:
    """Get the global configuration manager instance.
    
    Args:
        config_path: Optional path to configuration file.
        
    Returns:
        Configuration manager instance.
    """
    global _config_manager
    if _config_manager is None or config_path is not None:
        _config_manager = ConfigManager(config_path)
    return _config_manager


def get_config(force_reload: bool = False) -> iReDevConfig:
    """Get the current configuration.
    
    Args:
        force_reload: Force reload configuration from file.
        
    Returns:
        Current configuration.
    """
    return get_config_manager().load_config(force_reload)