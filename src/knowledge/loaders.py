"""
Specialized loaders for five types of knowledge modules in iReDev framework.
Each loader handles the specific parsing and validation requirements for its knowledge type.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Type
from abc import ABC, abstractmethod
import logging

from .base_types import (
    KnowledgeType, KnowledgeModule, KnowledgeMetadata, KnowledgeDependency,
    ModuleStatus, LoadPriority, KnowledgeException, ValidationException
)

logger = logging.getLogger(__name__)


class BaseKnowledgeLoader(ABC):
    """Base class for knowledge module loaders."""
    
    def __init__(self, knowledge_type: KnowledgeType):
        """Initialize the loader.
        
        Args:
            knowledge_type: Type of knowledge this loader handles.
        """
        self.knowledge_type = knowledge_type
        self.validation_rules: Dict[str, Any] = {}
        self._initialize_validation_rules()
    
    @abstractmethod
    def _initialize_validation_rules(self) -> None:
        """Initialize validation rules specific to this knowledge type."""
        pass
    
    @abstractmethod
    def _validate_content_structure(self, content: Dict[str, Any]) -> bool:
        """Validate the content structure for this knowledge type.
        
        Args:
            content: Content to validate.
            
        Returns:
            True if valid, False otherwise.
        """
        pass
    
    @abstractmethod
    def _parse_specialized_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Parse and enhance content specific to this knowledge type.
        
        Args:
            content: Raw content from file.
            
        Returns:
            Enhanced content with type-specific processing.
        """
        pass
    
    def load_module(self, module_id: str, file_path: str, config: Dict[str, Any] = None) -> KnowledgeModule:
        """Load a knowledge module from file.
        
        Args:
            module_id: Unique identifier for the module.
            file_path: Path to the module file.
            config: Optional configuration parameters.
            
        Returns:
            Loaded knowledge module.
            
        Raises:
            KnowledgeException: If loading fails.
        """
        try:
            # Load content from file
            content = self._load_file_content(file_path)
            
            # Validate basic structure
            if not self._validate_basic_structure(content):
                raise ValidationException(f"Invalid basic structure in {file_path}")
            
            # Validate type-specific structure
            if not self._validate_content_structure(content):
                raise ValidationException(f"Invalid {self.knowledge_type.value} structure in {file_path}")
            
            # Parse specialized content
            enhanced_content = self._parse_specialized_content(content)
            
            # Extract metadata
            metadata = self._extract_metadata(content, module_id)
            
            # Extract dependencies
            dependencies = self._extract_dependencies(content)
            
            # Create module
            module = KnowledgeModule(
                id=module_id,
                module_type=self.knowledge_type,
                content=enhanced_content,
                metadata=metadata,
                dependencies=dependencies,
                status=ModuleStatus.ACTIVE,
                load_priority=LoadPriority(config.get("load_priority", 2) if config else 2),
                file_path=file_path
            )
            
            logger.info(f"Loaded {self.knowledge_type.value} module: {module_id}")
            return module
            
        except Exception as e:
            logger.error(f"Failed to load {self.knowledge_type.value} module {module_id}: {str(e)}")
            raise KnowledgeException(f"Failed to load module {module_id}: {str(e)}")
    
    def _load_file_content(self, file_path: str) -> Dict[str, Any]:
        """Load content from file.
        
        Args:
            file_path: Path to the file.
            
        Returns:
            Loaded content dictionary.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Module file not found: {file_path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            if path.suffix.lower() == '.json':
                return json.load(f)
            else:
                return yaml.safe_load(f) or {}
    
    def _validate_basic_structure(self, content: Dict[str, Any]) -> bool:
        """Validate basic structure common to all knowledge types.
        
        Args:
            content: Content to validate.
            
        Returns:
            True if valid.
        """
        required_fields = ["name", "description", "content"]
        return all(field in content for field in required_fields)
    
    def _extract_metadata(self, content: Dict[str, Any], module_id: str) -> KnowledgeMetadata:
        """Extract metadata from content.
        
        Args:
            content: Content dictionary.
            module_id: Module identifier.
            
        Returns:
            Knowledge metadata object.
        """
        metadata_dict = content.get("metadata", {})
        
        return KnowledgeMetadata(
            name=content.get("name", module_id),
            description=content.get("description", ""),
            author=metadata_dict.get("author", ""),
            version=content.get("version", "1.0.0"),
            tags=metadata_dict.get("tags", []),
            references=metadata_dict.get("references", []),
            language=metadata_dict.get("language", "en"),
            domain=metadata_dict.get("domain", ""),
            confidence_score=metadata_dict.get("confidence_score", 1.0)
        )
    
    def _extract_dependencies(self, content: Dict[str, Any]) -> List[KnowledgeDependency]:
        """Extract dependencies from content.
        
        Args:
            content: Content dictionary.
            
        Returns:
            List of knowledge dependencies.
        """
        dependencies = []
        deps_list = content.get("dependencies", [])
        
        for dep in deps_list:
            if isinstance(dep, str):
                # Simple string dependency
                dependencies.append(KnowledgeDependency(
                    module_id=dep,
                    version_constraint="*",
                    dependency_type="required"
                ))
            elif isinstance(dep, dict):
                # Detailed dependency specification
                dependencies.append(KnowledgeDependency(
                    module_id=dep.get("module_id", ""),
                    version_constraint=dep.get("version", "*"),
                    dependency_type=dep.get("type", "required"),
                    description=dep.get("description", "")
                ))
        
        return dependencies


class DomainKnowledgeLoader(BaseKnowledgeLoader):
    """Loader for domain knowledge modules."""
    
    def __init__(self):
        """Initialize domain knowledge loader."""
        super().__init__(KnowledgeType.DOMAIN_KNOWLEDGE)
    
    def _initialize_validation_rules(self) -> None:
        """Initialize validation rules for domain knowledge."""
        self.validation_rules = {
            "required_sections": ["concepts", "principles", "best_practices"],
            "optional_sections": ["examples", "case_studies", "tools", "resources"],
            "content_types": ["text", "list", "dict", "examples"]
        }
    
    def _validate_content_structure(self, content: Dict[str, Any]) -> bool:
        """Validate domain knowledge content structure."""
        content_section = content.get("content", {})
        
        # Check for domain-specific structure
        if "concepts" not in content_section and "principles" not in content_section:
            return False
        
        return True
    
    def _parse_specialized_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Parse domain knowledge specific content."""
        enhanced_content = content.copy()
        content_section = enhanced_content.get("content", {})
        
        # Parse concepts
        if "concepts" in content_section:
            content_section["concepts"] = self._parse_concepts(content_section["concepts"])
        
        # Parse principles
        if "principles" in content_section:
            content_section["principles"] = self._parse_principles(content_section["principles"])
        
        # Parse best practices
        if "best_practices" in content_section:
            content_section["best_practices"] = self._parse_best_practices(content_section["best_practices"])
        
        # Add domain-specific metadata
        enhanced_content["domain_type"] = self._identify_domain_type(content_section)
        enhanced_content["complexity_level"] = self._assess_complexity(content_section)
        
        return enhanced_content
    
    def _parse_concepts(self, concepts: Any) -> Dict[str, Any]:
        """Parse domain concepts."""
        if isinstance(concepts, dict):
            return concepts
        elif isinstance(concepts, list):
            return {f"concept_{i}": concept for i, concept in enumerate(concepts)}
        else:
            return {"general": str(concepts)}
    
    def _parse_principles(self, principles: Any) -> Dict[str, Any]:
        """Parse domain principles."""
        if isinstance(principles, dict):
            return principles
        elif isinstance(principles, list):
            return {f"principle_{i}": principle for i, principle in enumerate(principles)}
        else:
            return {"general": str(principles)}
    
    def _parse_best_practices(self, practices: Any) -> Dict[str, Any]:
        """Parse best practices."""
        if isinstance(practices, dict):
            return practices
        elif isinstance(practices, list):
            return {f"practice_{i}": practice for i, practice in enumerate(practices)}
        else:
            return {"general": str(practices)}
    
    def _identify_domain_type(self, content: Dict[str, Any]) -> str:
        """Identify the type of domain knowledge."""
        # Simple heuristic based on content keywords
        content_str = str(content).lower()
        
        if "software" in content_str or "programming" in content_str:
            return "software_engineering"
        elif "web" in content_str or "frontend" in content_str or "backend" in content_str:
            return "web_development"
        elif "data" in content_str or "analytics" in content_str:
            return "data_science"
        else:
            return "general"
    
    def _assess_complexity(self, content: Dict[str, Any]) -> str:
        """Assess the complexity level of the domain knowledge."""
        # Simple heuristic based on content depth
        total_items = 0
        for section in content.values():
            if isinstance(section, dict):
                total_items += len(section)
            elif isinstance(section, list):
                total_items += len(section)
        
        if total_items > 20:
            return "advanced"
        elif total_items > 10:
            return "intermediate"
        else:
            return "basic"


class MethodologyLoader(BaseKnowledgeLoader):
    """Loader for methodology knowledge modules."""
    
    def __init__(self):
        """Initialize methodology loader."""
        super().__init__(KnowledgeType.METHODOLOGY)
    
    def _initialize_validation_rules(self) -> None:
        """Initialize validation rules for methodologies."""
        self.validation_rules = {
            "required_sections": ["framework", "steps", "application"],
            "optional_sections": ["benefits", "limitations", "examples", "tools"],
            "step_structure": ["description", "inputs", "outputs", "activities"]
        }
    
    def _validate_content_structure(self, content: Dict[str, Any]) -> bool:
        """Validate methodology content structure."""
        content_section = content.get("content", {})
        
        # Check for methodology-specific structure
        if "framework" not in content_section and "steps" not in content_section:
            return False
        
        return True
    
    def _parse_specialized_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Parse methodology specific content."""
        enhanced_content = content.copy()
        content_section = enhanced_content.get("content", {})
        
        # Parse framework
        if "framework" in content_section:
            content_section["framework"] = self._parse_framework(content_section["framework"])
        
        # Parse steps
        if "steps" in content_section:
            content_section["steps"] = self._parse_steps(content_section["steps"])
        
        # Parse application guidelines
        if "application" in content_section:
            content_section["application"] = self._parse_application(content_section["application"])
        
        # Add methodology-specific metadata
        enhanced_content["methodology_type"] = self._identify_methodology_type(content_section)
        enhanced_content["process_complexity"] = self._assess_process_complexity(content_section)
        enhanced_content["step_count"] = self._count_steps(content_section)
        
        return enhanced_content
    
    def _parse_framework(self, framework: Any) -> Dict[str, Any]:
        """Parse methodology framework."""
        if isinstance(framework, dict):
            return framework
        else:
            return {"description": str(framework)}
    
    def _parse_steps(self, steps: Any) -> List[Dict[str, Any]]:
        """Parse methodology steps."""
        if isinstance(steps, list):
            parsed_steps = []
            for i, step in enumerate(steps):
                if isinstance(step, dict):
                    parsed_steps.append(step)
                else:
                    parsed_steps.append({
                        "step_number": i + 1,
                        "description": str(step)
                    })
            return parsed_steps
        elif isinstance(steps, dict):
            return [{"step_number": i + 1, **step} for i, step in enumerate(steps.values())]
        else:
            return [{"step_number": 1, "description": str(steps)}]
    
    def _parse_application(self, application: Any) -> Dict[str, Any]:
        """Parse application guidelines."""
        if isinstance(application, dict):
            return application
        else:
            return {"guidelines": str(application)}
    
    def _identify_methodology_type(self, content: Dict[str, Any]) -> str:
        """Identify the type of methodology."""
        content_str = str(content).lower()
        
        if "interview" in content_str or "elicitation" in content_str:
            return "requirements_elicitation"
        elif "analysis" in content_str or "modeling" in content_str:
            return "analysis_methodology"
        elif "design" in content_str or "architecture" in content_str:
            return "design_methodology"
        elif "testing" in content_str or "validation" in content_str:
            return "validation_methodology"
        else:
            return "general_methodology"
    
    def _assess_process_complexity(self, content: Dict[str, Any]) -> str:
        """Assess the complexity of the methodology process."""
        step_count = self._count_steps(content)
        
        if step_count > 10:
            return "complex"
        elif step_count > 5:
            return "moderate"
        else:
            return "simple"
    
    def _count_steps(self, content: Dict[str, Any]) -> int:
        """Count the number of steps in the methodology."""
        steps = content.get("steps", [])
        if isinstance(steps, list):
            return len(steps)
        elif isinstance(steps, dict):
            return len(steps)
        else:
            return 1


class StandardsLoader(BaseKnowledgeLoader):
    """Loader for standards knowledge modules."""
    
    def __init__(self):
        """Initialize standards loader."""
        super().__init__(KnowledgeType.STANDARDS)
    
    def _initialize_validation_rules(self) -> None:
        """Initialize validation rules for standards."""
        self.validation_rules = {
            "required_sections": ["standard_info", "requirements", "compliance"],
            "optional_sections": ["examples", "checklists", "tools", "references"],
            "standard_types": ["ieee", "iso", "organizational", "industry"]
        }
    
    def _validate_content_structure(self, content: Dict[str, Any]) -> bool:
        """Validate standards content structure."""
        content_section = content.get("content", {})
        
        # Check for standards-specific structure
        if "standard_info" not in content_section and "requirements" not in content_section:
            return False
        
        return True
    
    def _parse_specialized_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Parse standards specific content."""
        enhanced_content = content.copy()
        content_section = enhanced_content.get("content", {})
        
        # Parse standard information
        if "standard_info" in content_section:
            content_section["standard_info"] = self._parse_standard_info(content_section["standard_info"])
        
        # Parse requirements
        if "requirements" in content_section:
            content_section["requirements"] = self._parse_requirements(content_section["requirements"])
        
        # Parse compliance information
        if "compliance" in content_section:
            content_section["compliance"] = self._parse_compliance(content_section["compliance"])
        
        # Add standards-specific metadata
        enhanced_content["standard_type"] = self._identify_standard_type(content_section)
        enhanced_content["compliance_level"] = self._assess_compliance_level(content_section)
        enhanced_content["requirement_count"] = self._count_requirements(content_section)
        
        return enhanced_content
    
    def _parse_standard_info(self, info: Any) -> Dict[str, Any]:
        """Parse standard information."""
        if isinstance(info, dict):
            return info
        else:
            return {"description": str(info)}
    
    def _parse_requirements(self, requirements: Any) -> List[Dict[str, Any]]:
        """Parse standard requirements."""
        if isinstance(requirements, list):
            return [{"requirement": req} if isinstance(req, str) else req for req in requirements]
        elif isinstance(requirements, dict):
            return [{"id": k, **v} if isinstance(v, dict) else {"id": k, "requirement": v} 
                   for k, v in requirements.items()]
        else:
            return [{"requirement": str(requirements)}]
    
    def _parse_compliance(self, compliance: Any) -> Dict[str, Any]:
        """Parse compliance information."""
        if isinstance(compliance, dict):
            return compliance
        else:
            return {"description": str(compliance)}
    
    def _identify_standard_type(self, content: Dict[str, Any]) -> str:
        """Identify the type of standard."""
        content_str = str(content).lower()
        
        if "ieee" in content_str:
            return "ieee"
        elif "iso" in content_str:
            return "iso"
        elif "organizational" in content_str or "company" in content_str:
            return "organizational"
        else:
            return "industry"
    
    def _assess_compliance_level(self, content: Dict[str, Any]) -> str:
        """Assess the compliance level required."""
        requirements = content.get("requirements", [])
        
        if isinstance(requirements, list) and len(requirements) > 20:
            return "strict"
        elif isinstance(requirements, list) and len(requirements) > 10:
            return "moderate"
        else:
            return "basic"
    
    def _count_requirements(self, content: Dict[str, Any]) -> int:
        """Count the number of requirements in the standard."""
        requirements = content.get("requirements", [])
        if isinstance(requirements, list):
            return len(requirements)
        elif isinstance(requirements, dict):
            return len(requirements)
        else:
            return 1


class TemplatesLoader(BaseKnowledgeLoader):
    """Loader for template knowledge modules."""
    
    def __init__(self):
        """Initialize templates loader."""
        super().__init__(KnowledgeType.TEMPLATES)
    
    def _initialize_validation_rules(self) -> None:
        """Initialize validation rules for templates."""
        self.validation_rules = {
            "required_sections": ["template_structure", "sections"],
            "optional_sections": ["examples", "guidelines", "formatting", "validation"],
            "template_types": ["document", "form", "checklist", "report"]
        }
    
    def _validate_content_structure(self, content: Dict[str, Any]) -> bool:
        """Validate templates content structure."""
        content_section = content.get("content", {})
        
        # Check for template-specific structure
        if "template_structure" not in content_section and "sections" not in content_section:
            return False
        
        return True
    
    def _parse_specialized_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Parse templates specific content."""
        enhanced_content = content.copy()
        content_section = enhanced_content.get("content", {})
        
        # Parse template structure
        if "template_structure" in content_section:
            content_section["template_structure"] = self._parse_template_structure(content_section["template_structure"])
        
        # Parse sections
        if "sections" in content_section:
            content_section["sections"] = self._parse_sections(content_section["sections"])
        
        # Parse formatting guidelines
        if "formatting" in content_section:
            content_section["formatting"] = self._parse_formatting(content_section["formatting"])
        
        # Add template-specific metadata
        enhanced_content["template_type"] = self._identify_template_type(content_section)
        enhanced_content["complexity_level"] = self._assess_template_complexity(content_section)
        enhanced_content["section_count"] = self._count_sections(content_section)
        
        return enhanced_content
    
    def _parse_template_structure(self, structure: Any) -> Dict[str, Any]:
        """Parse template structure."""
        if isinstance(structure, dict):
            return structure
        else:
            return {"description": str(structure)}
    
    def _parse_sections(self, sections: Any) -> Dict[str, Any]:
        """Parse template sections."""
        if isinstance(sections, dict):
            return sections
        elif isinstance(sections, list):
            return {f"section_{i}": section for i, section in enumerate(sections)}
        else:
            return {"main": str(sections)}
    
    def _parse_formatting(self, formatting: Any) -> Dict[str, Any]:
        """Parse formatting guidelines."""
        if isinstance(formatting, dict):
            return formatting
        else:
            return {"guidelines": str(formatting)}
    
    def _identify_template_type(self, content: Dict[str, Any]) -> str:
        """Identify the type of template."""
        content_str = str(content).lower()
        
        if "srs" in content_str or "specification" in content_str:
            return "specification_document"
        elif "report" in content_str:
            return "report_template"
        elif "checklist" in content_str:
            return "checklist_template"
        elif "form" in content_str:
            return "form_template"
        else:
            return "document_template"
    
    def _assess_template_complexity(self, content: Dict[str, Any]) -> str:
        """Assess the complexity of the template."""
        section_count = self._count_sections(content)
        
        if section_count > 15:
            return "complex"
        elif section_count > 8:
            return "moderate"
        else:
            return "simple"
    
    def _count_sections(self, content: Dict[str, Any]) -> int:
        """Count the number of sections in the template."""
        sections = content.get("sections", {})
        if isinstance(sections, dict):
            return len(sections)
        elif isinstance(sections, list):
            return len(sections)
        else:
            return 1


class StrategiesLoader(BaseKnowledgeLoader):
    """Loader for strategy knowledge modules."""
    
    def __init__(self):
        """Initialize strategies loader."""
        super().__init__(KnowledgeType.STRATEGIES)
    
    def _initialize_validation_rules(self) -> None:
        """Initialize validation rules for strategies."""
        self.validation_rules = {
            "required_sections": ["strategy_info", "application", "benefits"],
            "optional_sections": ["examples", "best_practices", "limitations", "tools"],
            "strategy_types": ["prioritization", "analysis", "communication", "planning"]
        }
    
    def _validate_content_structure(self, content: Dict[str, Any]) -> bool:
        """Validate strategies content structure."""
        content_section = content.get("content", {})
        
        # Check for strategy-specific structure
        if "strategy_info" not in content_section and "application" not in content_section:
            return False
        
        return True
    
    def _parse_specialized_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Parse strategies specific content."""
        enhanced_content = content.copy()
        content_section = enhanced_content.get("content", {})
        
        # Parse strategy information
        if "strategy_info" in content_section:
            content_section["strategy_info"] = self._parse_strategy_info(content_section["strategy_info"])
        
        # Parse application guidelines
        if "application" in content_section:
            content_section["application"] = self._parse_application(content_section["application"])
        
        # Parse benefits
        if "benefits" in content_section:
            content_section["benefits"] = self._parse_benefits(content_section["benefits"])
        
        # Add strategy-specific metadata
        enhanced_content["strategy_type"] = self._identify_strategy_type(content_section)
        enhanced_content["applicability"] = self._assess_applicability(content_section)
        enhanced_content["effectiveness_level"] = self._assess_effectiveness(content_section)
        
        return enhanced_content
    
    def _parse_strategy_info(self, info: Any) -> Dict[str, Any]:
        """Parse strategy information."""
        if isinstance(info, dict):
            return info
        else:
            return {"description": str(info)}
    
    def _parse_application(self, application: Any) -> Dict[str, Any]:
        """Parse application guidelines."""
        if isinstance(application, dict):
            return application
        else:
            return {"guidelines": str(application)}
    
    def _parse_benefits(self, benefits: Any) -> List[str]:
        """Parse strategy benefits."""
        if isinstance(benefits, list):
            return [str(benefit) for benefit in benefits]
        elif isinstance(benefits, dict):
            return list(benefits.values())
        else:
            return [str(benefits)]
    
    def _identify_strategy_type(self, content: Dict[str, Any]) -> str:
        """Identify the type of strategy."""
        content_str = str(content).lower()
        
        if "prioritization" in content_str or "moscow" in content_str:
            return "prioritization_strategy"
        elif "analysis" in content_str or "evaluation" in content_str:
            return "analysis_strategy"
        elif "communication" in content_str or "interview" in content_str:
            return "communication_strategy"
        elif "planning" in content_str or "management" in content_str:
            return "planning_strategy"
        else:
            return "general_strategy"
    
    def _assess_applicability(self, content: Dict[str, Any]) -> str:
        """Assess the applicability of the strategy."""
        # Simple heuristic based on content breadth
        sections = len(content)
        
        if sections > 8:
            return "broad"
        elif sections > 4:
            return "moderate"
        else:
            return "specific"
    
    def _assess_effectiveness(self, content: Dict[str, Any]) -> str:
        """Assess the effectiveness level of the strategy."""
        benefits = content.get("benefits", [])
        
        if isinstance(benefits, list) and len(benefits) > 5:
            return "high"
        elif isinstance(benefits, list) and len(benefits) > 2:
            return "moderate"
        else:
            return "basic"


class KnowledgeLoaderFactory:
    """Factory for creating knowledge loaders."""
    
    _loaders: Dict[KnowledgeType, Type[BaseKnowledgeLoader]] = {
        KnowledgeType.DOMAIN_KNOWLEDGE: DomainKnowledgeLoader,
        KnowledgeType.METHODOLOGY: MethodologyLoader,
        KnowledgeType.STANDARDS: StandardsLoader,
        KnowledgeType.TEMPLATES: TemplatesLoader,
        KnowledgeType.STRATEGIES: StrategiesLoader
    }
    
    @classmethod
    def create_loader(cls, knowledge_type: KnowledgeType) -> BaseKnowledgeLoader:
        """Create a loader for the specified knowledge type.
        
        Args:
            knowledge_type: Type of knowledge loader to create.
            
        Returns:
            Knowledge loader instance.
            
        Raises:
            ValueError: If knowledge type is not supported.
        """
        loader_class = cls._loaders.get(knowledge_type)
        if not loader_class:
            raise ValueError(f"Unsupported knowledge type: {knowledge_type}")
        
        return loader_class()
    
    @classmethod
    def get_supported_types(cls) -> List[KnowledgeType]:
        """Get list of supported knowledge types.
        
        Returns:
            List of supported knowledge types.
        """
        return list(cls._loaders.keys())
    
    @classmethod
    def register_loader(cls, knowledge_type: KnowledgeType, loader_class: Type[BaseKnowledgeLoader]) -> None:
        """Register a custom loader for a knowledge type.
        
        Args:
            knowledge_type: Knowledge type to register.
            loader_class: Loader class to register.
        """
        cls._loaders[knowledge_type] = loader_class
        logger.info(f"Registered custom loader for {knowledge_type.value}")


class KnowledgeLoaderManager:
    """Manager for coordinating knowledge module loading across all types."""
    
    def __init__(self):
        """Initialize the loader manager."""
        self.loaders: Dict[KnowledgeType, BaseKnowledgeLoader] = {}
        self._initialize_loaders()
    
    def _initialize_loaders(self) -> None:
        """Initialize all knowledge loaders."""
        for knowledge_type in KnowledgeType:
            try:
                self.loaders[knowledge_type] = KnowledgeLoaderFactory.create_loader(knowledge_type)
                logger.info(f"Initialized {knowledge_type.value} loader")
            except Exception as e:
                logger.error(f"Failed to initialize {knowledge_type.value} loader: {str(e)}")
    
    def load_module(self, knowledge_type: KnowledgeType, module_id: str, 
                   file_path: str, config: Dict[str, Any] = None) -> KnowledgeModule:
        """Load a knowledge module using the appropriate loader.
        
        Args:
            knowledge_type: Type of knowledge module.
            module_id: Module identifier.
            file_path: Path to module file.
            config: Optional configuration.
            
        Returns:
            Loaded knowledge module.
            
        Raises:
            KnowledgeException: If loading fails.
        """
        loader = self.loaders.get(knowledge_type)
        if not loader:
            raise KnowledgeException(f"No loader available for {knowledge_type.value}")
        
        return loader.load_module(module_id, file_path, config)
    
    def get_loader(self, knowledge_type: KnowledgeType) -> Optional[BaseKnowledgeLoader]:
        """Get loader for a specific knowledge type.
        
        Args:
            knowledge_type: Knowledge type.
            
        Returns:
            Knowledge loader or None if not found.
        """
        return self.loaders.get(knowledge_type)
    
    def validate_module_file(self, knowledge_type: KnowledgeType, file_path: str) -> bool:
        """Validate a module file without loading it.
        
        Args:
            knowledge_type: Type of knowledge module.
            file_path: Path to module file.
            
        Returns:
            True if valid, False otherwise.
        """
        try:
            loader = self.loaders.get(knowledge_type)
            if not loader:
                return False
            
            content = loader._load_file_content(file_path)
            return (loader._validate_basic_structure(content) and 
                   loader._validate_content_structure(content))
        except Exception:
            return False
    
    def get_loader_stats(self) -> Dict[str, Any]:
        """Get statistics about loaded modules by type.
        
        Returns:
            Dictionary with loader statistics.
        """
        stats = {
            "total_loaders": len(self.loaders),
            "available_types": [kt.value for kt in self.loaders.keys()],
            "loader_status": {}
        }
        
        for knowledge_type, loader in self.loaders.items():
            stats["loader_status"][knowledge_type.value] = {
                "initialized": loader is not None,
                "validation_rules": len(loader.validation_rules) if loader else 0
            }
        
        return stats