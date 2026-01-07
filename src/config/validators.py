"""
Configuration validation utilities for iReDev framework.
"""

import os
import re
from typing import Dict, Any, List, Optional, Union
from pathlib import Path
import logging

from .config_manager import iReDevConfig, AgentConfig, KnowledgeModuleConfig, ConfigurationError

logger = logging.getLogger(__name__)


class ConfigValidator:
    """Validates iReDev configuration for consistency and completeness."""
    
    @staticmethod
    def validate_full_config(config: iReDevConfig) -> List[str]:
        """Validate the complete configuration.
        
        Args:
            config: Configuration to validate.
            
        Returns:
            List of validation error messages. Empty if valid.
        """
        errors = []
        
        # Validate LLM configuration
        errors.extend(ConfigValidator._validate_llm_config(config.llm))
        
        # Validate agent configurations
        errors.extend(ConfigValidator._validate_agents_config(config.agents))
        
        # Validate knowledge base configuration
        errors.extend(ConfigValidator._validate_knowledge_base_config(config.knowledge_base))
        
        # Validate human in loop configuration
        errors.extend(ConfigValidator._validate_human_in_loop_config(config.human_in_loop))
        
        # Validate artifact pool configuration
        errors.extend(ConfigValidator._validate_artifact_pool_config(config.artifact_pool))
        
        return errors
    
    @staticmethod
    def _validate_llm_config(llm_config: Dict[str, Any]) -> List[str]:
        """Validate LLM configuration.
        
        Args:
            llm_config: LLM configuration dictionary.
            
        Returns:
            List of validation errors.
        """
        errors = []
        
        if not llm_config:
            errors.append("LLM configuration is required")
            return errors
        
        # Validate required fields
        required_fields = ["type"]
        for field in required_fields:
            if field not in llm_config:
                errors.append(f"LLM configuration missing required field: {field}")
        
        # Validate LLM type
        valid_types = ["openai", "claude", "gemini", "huggingface"]
        llm_type = llm_config.get("type")
        if llm_type and llm_type not in valid_types:
            errors.append(f"Invalid LLM type: {llm_type}. Must be one of: {valid_types}")
        
        # Validate API key for non-local models
        if llm_type not in ["huggingface"] and not llm_config.get("api_key"):
            errors.append(f"API key is required for LLM type: {llm_type}")
        
        # Validate numeric parameters
        numeric_params = {
            "temperature": (0.0, 2.0),
            "max_output_tokens": (1, 100000),
            "max_input_tokens": (1, 1000000)
        }
        
        for param, (min_val, max_val) in numeric_params.items():
            if param in llm_config:
                value = llm_config[param]
                if not isinstance(value, (int, float)):
                    errors.append(f"LLM parameter {param} must be numeric")
                elif not (min_val <= value <= max_val):
                    errors.append(f"LLM parameter {param} must be between {min_val} and {max_val}")
        
        return errors
    
    @staticmethod
    def _validate_agents_config(agents_config: Dict[str, AgentConfig]) -> List[str]:
        """Validate agents configuration.
        
        Args:
            agents_config: Dictionary of agent configurations.
            
        Returns:
            List of validation errors.
        """
        errors = []
        
        if not agents_config:
            errors.append("At least one agent must be configured")
            return errors
        
        # Required agents for iReDev framework
        required_agents = ["interviewer", "enduser", "deployer", "analyst", "archivist", "reviewer"]
        
        for required_agent in required_agents:
            if required_agent not in agents_config:
                errors.append(f"Required agent '{required_agent}' is not configured")
        
        # Validate each agent configuration
        for agent_name, agent_config in agents_config.items():
            agent_errors = ConfigValidator._validate_agent_config(agent_name, agent_config)
            errors.extend(agent_errors)
        
        return errors
    
    @staticmethod
    def _validate_agent_config(agent_name: str, agent_config: AgentConfig) -> List[str]:
        """Validate individual agent configuration.
        
        Args:
            agent_name: Name of the agent.
            agent_config: Agent configuration.
            
        Returns:
            List of validation errors.
        """
        errors = []
        
        # Validate agent name
        if not agent_config.name:
            errors.append(f"Agent {agent_name} must have a name")
        elif not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', agent_config.name):
            errors.append(f"Agent name '{agent_config.name}' must be a valid identifier")
        
        # Validate numeric parameters
        if agent_config.max_turns <= 0:
            errors.append(f"Agent {agent_name} max_turns must be positive")
        
        if agent_config.timeout_seconds <= 0:
            errors.append(f"Agent {agent_name} timeout_seconds must be positive")
        
        if agent_config.memory_limit_mb <= 0:
            errors.append(f"Agent {agent_name} memory_limit_mb must be positive")
        
        # Validate knowledge modules
        if not agent_config.knowledge_modules:
            errors.append(f"Agent {agent_name} should have at least one knowledge module")
        
        # Validate LLM config reference
        if not agent_config.llm_config:
            errors.append(f"Agent {agent_name} must specify an LLM configuration")
        
        return errors
    
    @staticmethod
    def _validate_knowledge_base_config(kb_config: Dict[str, Any]) -> List[str]:
        """Validate knowledge base configuration.
        
        Args:
            kb_config: Knowledge base configuration dictionary.
            
        Returns:
            List of validation errors.
        """
        errors = []
        
        if not kb_config:
            errors.append("Knowledge base configuration is required")
            return errors
        
        # Validate required paths
        required_paths = [
            "base_path",
            "domain_knowledge_path",
            "methodology_path",
            "standards_path",
            "templates_path",
            "strategies_path"
        ]
        
        for path_key in required_paths:
            if path_key not in kb_config:
                errors.append(f"Knowledge base missing required path: {path_key}")
            else:
                path_value = kb_config[path_key]
                if not isinstance(path_value, str):
                    errors.append(f"Knowledge base path {path_key} must be a string")
                elif not path_value.strip():
                    errors.append(f"Knowledge base path {path_key} cannot be empty")
        
        # Validate boolean parameters
        boolean_params = ["cache_enabled", "auto_reload"]
        for param in boolean_params:
            if param in kb_config and not isinstance(kb_config[param], bool):
                errors.append(f"Knowledge base parameter {param} must be boolean")
        
        return errors
    
    @staticmethod
    def _validate_human_in_loop_config(hil_config) -> List[str]:
        """Validate human in loop configuration.
        
        Args:
            hil_config: Human in loop configuration.
            
        Returns:
            List of validation errors.
        """
        errors = []
        
        # Validate timeout
        if hil_config.timeout_minutes <= 0:
            errors.append("Human in loop timeout_minutes must be positive")
        
        # Validate review points
        if not hil_config.review_points:
            errors.append("Human in loop must have at least one review point")
        
        valid_review_points = [
            "url_generation", "model_creation", "srs_generation",
            "interview_completion", "analysis_completion"
        ]
        
        for point in hil_config.review_points:
            if point not in valid_review_points:
                errors.append(f"Invalid review point: {point}. Must be one of: {valid_review_points}")
        
        # Validate notification channels
        valid_channels = ["email", "slack", "webhook", "console"]
        for channel in hil_config.notification_channels:
            if channel not in valid_channels:
                errors.append(f"Invalid notification channel: {channel}. Must be one of: {valid_channels}")
        
        return errors
    
    @staticmethod
    def _validate_artifact_pool_config(ap_config) -> List[str]:
        """Validate artifact pool configuration.
        
        Args:
            ap_config: Artifact pool configuration.
            
        Returns:
            List of validation errors.
        """
        errors = []
        
        # Validate storage backend
        valid_backends = ["memory", "filesystem", "postgresql", "mongodb"]
        if ap_config.storage_backend not in valid_backends:
            errors.append(f"Invalid storage backend: {ap_config.storage_backend}. Must be one of: {valid_backends}")
        
        # Validate storage path
        if not ap_config.storage_path:
            errors.append("Artifact pool storage_path cannot be empty")
        
        # Validate numeric parameters
        if ap_config.backup_interval_minutes <= 0:
            errors.append("Artifact pool backup_interval_minutes must be positive")
        
        if ap_config.max_versions_per_artifact <= 0:
            errors.append("Artifact pool max_versions_per_artifact must be positive")
        
        return errors
    
    @staticmethod
    def validate_paths_exist(config: iReDevConfig, create_missing: bool = False) -> List[str]:
        """Validate that configured paths exist.
        
        Args:
            config: Configuration to validate.
            create_missing: Whether to create missing directories.
            
        Returns:
            List of validation errors.
        """
        errors = []
        
        # Check knowledge base paths
        if config.knowledge_base:
            paths_to_check = [
                config.knowledge_base.get("base_path"),
                config.knowledge_base.get("domain_knowledge_path"),
                config.knowledge_base.get("methodology_path"),
                config.knowledge_base.get("standards_path"),
                config.knowledge_base.get("templates_path"),
                config.knowledge_base.get("strategies_path")
            ]
            
            for path in paths_to_check:
                if path and not os.path.exists(path):
                    if create_missing:
                        try:
                            os.makedirs(path, exist_ok=True)
                            logger.info(f"Created missing directory: {path}")
                        except OSError as e:
                            errors.append(f"Failed to create directory {path}: {str(e)}")
                    else:
                        errors.append(f"Knowledge base path does not exist: {path}")
        
        # Check artifact pool storage path
        storage_path = config.artifact_pool.storage_path
        if storage_path and not os.path.exists(storage_path):
            if create_missing:
                try:
                    os.makedirs(storage_path, exist_ok=True)
                    logger.info(f"Created missing directory: {storage_path}")
                except OSError as e:
                    errors.append(f"Failed to create artifact storage directory {storage_path}: {str(e)}")
            else:
                errors.append(f"Artifact pool storage path does not exist: {storage_path}")
        
        return errors


class ConfigDefaults:
    """Provides default values and validation for configuration parameters."""
    
    @staticmethod
    def get_default_agent_config(agent_name: str) -> AgentConfig:
        """Get default configuration for a specific agent.
        
        Args:
            agent_name: Name of the agent.
            
        Returns:
            Default agent configuration.
        """
        defaults = {
            "interviewer": AgentConfig(
                name="interviewer",
                knowledge_modules=["requirements_elicitation", "interview_techniques", "5w1h", "socratic_questioning"],
                max_turns=50,
                timeout_seconds=600
            ),
            "enduser": AgentConfig(
                name="enduser",
                knowledge_modules=["user_experience", "persona_modeling", "scenario_design"],
                max_turns=30,
                timeout_seconds=300
            ),
            "deployer": AgentConfig(
                name="deployer",
                knowledge_modules=["system_architecture", "security", "compliance", "performance"],
                max_turns=20,
                timeout_seconds=300
            ),
            "analyst": AgentConfig(
                name="analyst",
                knowledge_modules=["requirements_analysis", "system_modeling", "traceability", "prioritization"],
                max_turns=40,
                timeout_seconds=600
            ),
            "archivist": AgentConfig(
                name="archivist",
                knowledge_modules=["ieee_830", "iso_29148", "technical_writing", "document_templates"],
                max_turns=25,
                timeout_seconds=400
            ),
            "reviewer": AgentConfig(
                name="reviewer",
                knowledge_modules=["quality_assurance", "validation", "verification", "defect_identification"],
                max_turns=35,
                timeout_seconds=500
            )
        }
        
        return defaults.get(agent_name, AgentConfig(name=agent_name))
    
    @staticmethod
    def validate_and_apply_defaults(config: iReDevConfig) -> iReDevConfig:
        """Validate configuration and apply defaults where needed.
        
        Args:
            config: Configuration to validate and enhance.
            
        Returns:
            Configuration with defaults applied.
        """
        # Apply default agent configurations for missing agents
        required_agents = ["interviewer", "enduser", "deployer", "analyst", "archivist", "reviewer"]
        
        for agent_name in required_agents:
            if agent_name not in config.agents:
                config.agents[agent_name] = ConfigDefaults.get_default_agent_config(agent_name)
        
        # Apply default knowledge base configuration if missing
        if not config.knowledge_base:
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
        
        return config