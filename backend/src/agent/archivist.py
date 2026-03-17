"""
Archivist Agent for iReDev framework.
Generates SRS documents, applies document templates, and ensures standard compliance.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import logging
import uuid
import re

from .knowledge_driven_agent import KnowledgeDrivenAgent
from ..knowledge.base_types import KnowledgeType
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus, ArtifactMetadata

logger = logging.getLogger(__name__)


@dataclass
class SRSSection:
    """Represents a section in an SRS document."""
    id: str
    number: str
    title: str
    content: str
    subsections: List['SRSSection'] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)  # Requirement IDs
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert SRS section to dictionary."""
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "content": self.content,
            "subsections": [sub.to_dict() for sub in self.subsections],
            "requirements": self.requirements,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class SRSDocument:
    """Represents a complete SRS document."""
    id: str
    title: str
    version: str
    date: datetime
    authors: List[str]
    reviewers: List[str] = field(default_factory=list)
    approval_authority: str = ""
    
    # Document metadata
    project_name: str = ""
    document_type: str = "Software Requirements Specification"
    standard_compliance: List[str] = field(default_factory=list)
    
    # Document structure
    sections: List[SRSSection] = field(default_factory=list)
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    glossary: Dict[str, str] = field(default_factory=dict)
    references: List[Dict[str, str]] = field(default_factory=list)
    
    # Quality metrics
    completeness_score: Optional[float] = None
    consistency_score: Optional[float] = None
    traceability_score: Optional[float] = None
    
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert SRS document to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "version": self.version,
            "date": self.date.isoformat(),
            "authors": self.authors,
            "reviewers": self.reviewers,
            "approval_authority": self.approval_authority,
            "project_name": self.project_name,
            "document_type": self.document_type,
            "standard_compliance": self.standard_compliance,
            "sections": [section.to_dict() for section in self.sections],
            "revision_history": self.revision_history,
            "glossary": self.glossary,
            "references": self.references,
            "completeness_score": self.completeness_score,
            "consistency_score": self.consistency_score,
            "traceability_score": self.traceability_score,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class DocumentTemplate:
    """Represents a document template."""
    id: str
    name: str
    standard: str  # IEEE 830, ISO 29148, etc.
    structure: Dict[str, Any]
    formatting_rules: Dict[str, Any]
    quality_checklist: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert template to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "standard": self.standard,
            "structure": self.structure,
            "formatting_rules": self.formatting_rules,
            "quality_checklist": self.quality_checklist
        }


@dataclass
class ComplianceReport:
    """Represents a standard compliance report."""
    id: str
    document_id: str
    standard: str
    compliance_score: float
    violations: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    quality_metrics: Dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert compliance report to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "standard": self.standard,
            "compliance_score": self.compliance_score,
            "violations": self.violations,
            "recommendations": self.recommendations,
            "quality_metrics": self.quality_metrics,
            "created_at": self.created_at.isoformat()
        }


class ArchivistAgent(KnowledgeDrivenAgent):
    """
    Archivist Agent for generating SRS documents and ensuring standard compliance.
    
    Integrates document templates, standard specifications, and quality assurance
    methodologies to create high-quality requirements documentation.
    """
    
    def __init__(self, config_path: Optional[str] = None, **kwargs):
        # Define required knowledge modules for archivist agent
        knowledge_modules = [
            "ieee_830",
            "iso_29148", 
            "srs_template",
            "technical_writing",
            "document_quality",
            "requirements_traceability"
        ]
        
        super().__init__(
            name="archivist",
            knowledge_modules=knowledge_modules,
            config_path=config_path,
            **kwargs
        )
        
        # Agent configuration
        self.supported_standards = self.config.get('supported_standards', [
            'IEEE 830', 'ISO/IEC/IEEE 29148', 'Custom'
        ])
        self.default_standard = self.config.get('default_standard', 'IEEE 830')
        self.quality_thresholds = self.config.get('quality_thresholds', {
            'completeness': 0.85,
            'consistency': 0.90,
            'traceability': 0.80
        })
        
        # Agent state
        self.srs_documents: Dict[str, SRSDocument] = {}
        self.document_templates: Dict[str, DocumentTemplate] = {}
        self.compliance_reports: Dict[str, ComplianceReport] = {}
        
        # Load document templates from knowledge modules
        self._load_document_templates()
        
        # Initialize profile prompt
        self.profile_prompt = self._create_profile_prompt()
        self.add_to_memory("system", self.profile_prompt)
        
        logger.info(f"Initialized ArchivistAgent with {len(knowledge_modules)} knowledge modules")
    
    def _create_profile_prompt(self) -> str:
        """Create profile prompt for the archivist agent."""
        return """You are an experienced technical writer and requirements documentation specialist.

Mission:
Generate structured, logically consistent Software Requirements Specification (SRS) documents that strictly adhere to industry standards, ensuring completeness, clarity, and traceability.

Personality:
Precise, systematic, and standards-compliant; expert in technical writing and document structure.

Workflow:
1. Analyze system requirements and requirement models.
2. Apply appropriate document template based on target standard (IEEE 830, ISO/IEC/IEEE 29148).
3. Generate SRS document with proper chapter structure, terminology, and constraint expressions.
4. Ensure logical consistency and cross-references.
5. Validate compliance with selected standard.
6. Generate compliance report.

Experience & Preferred Practices:
1. Strictly follow ISO/IEC/IEEE 29148 and IEEE 830 standards.
2. Use standard chapter structures, terminology conventions, and constraint expression formats.
3. Ensure all requirements are traceable to source artifacts.
4. Maintain consistent terminology throughout document.
5. Structure document as formal specification, not free-form summary.
6. Include proper cross-references, glossary, and appendices.

Internal Chain of Thought (visible to the agent only):
1. Analyze system requirements and models to understand scope and structure.
2. Select appropriate template and standard format.
3. Organize requirements into standard sections (Introduction, Overall Description, Specific Requirements, etc.).
4. Transform requirements into formal specification language.
5. Establish cross-references and traceability links.
6. Validate document structure and terminology consistency.
7. Check compliance with selected standard.
"""
    
    def _get_action_prompt(self, action: str, context: Dict[str, Any] = None) -> str:
        """Get action-specific prompt for a given action."""
        action_prompts = {
            "generate_srs": """Action: Generate Software Requirements Specification document.

Context:
- Standard: {standard}
- System requirements: {requirements}
- Requirement model: {requirement_model}
- Traceability matrix: {traceability_matrix}

Instructions:
1. Apply standard template for selected standard (IEEE 830 or ISO/IEC/IEEE 29148).
2. Organize requirements into proper sections.
3. Use formal specification language, not free-form summary.
4. Ensure all requirements are traceable.
5. Include proper cross-references and glossary.
6. Maintain terminology consistency.
""",
            "apply_template": """Action: Apply document template to structure SRS.

Context:
- Template: {template_name}
- Standard: {standard}
- Content: {content}

Instructions:
1. Map content to template sections.
2. Follow template structure strictly.
3. Fill in all required sections.
4. Maintain standard terminology.
""",
            "validate_compliance": """Action: Validate SRS compliance with standard.

Context:
- SRS document: {srs_document}
- Target standard: {standard}

Instructions:
1. Check document structure against standard requirements.
2. Verify terminology usage.
3. Validate section completeness.
4. Check cross-reference consistency.
5. Generate compliance report with findings.
"""
        }
        
        base_prompt = action_prompts.get(action, f"Action: {action}")
        if context:
            try:
                return base_prompt.format(**context)
            except:
                return base_prompt
        return base_prompt
    
    def _load_document_templates(self) -> None:
        """Load document templates from knowledge modules."""
        for module_id, module in self.knowledge_modules.items():
            if module.module_type == KnowledgeType.TEMPLATES:
                template = self._create_template_from_knowledge(module)
                if template:
                    self.document_templates[template.id] = template
                    logger.info(f"Loaded document template: {template.name}")
    
    def _create_template_from_knowledge(self, module) -> Optional[DocumentTemplate]:
        """Create document template from knowledge module."""
        try:
            content = module.content
            return DocumentTemplate(
                id=module.id,
                name=content.get("name", "Unknown Template"),
                standard=content.get("standard", "Custom"),
                structure=content.get("template_structure", {}),
                formatting_rules=content.get("formatting_guidelines", {}),
                quality_checklist=content.get("quality_checklist", {})
            )
        except Exception as e:
            logger.warning(f"Failed to create template from knowledge module {module.id}: {e}")
            return None 
   def generate_srs_document(self, requirements: List[Dict[str, Any]], 
                            requirement_model: Dict[str, Any],
                            project_info: Dict[str, Any]) -> SRSDocument:
        """
        Generate SRS document from requirements and requirement model.
        
        Args:
            requirements: List of system requirements
            requirement_model: Structured requirement model
            project_info: Project information and metadata
            
        Returns:
            Generated SRS document
        """
        logger.info(f"Generating SRS document for project: {project_info.get('name', 'Unknown')}")
        
        # Apply document generation methodology
        generation_methodology = self.apply_methodology("srs_generation")
        
        # Generate SRS document using CoT reasoning with action prompt
        standard = project_info.get('standard', self.default_standard)
        action_prompt = self._get_action_prompt(
            "generate_srs",
            context={
                "standard": standard,
                "requirements": requirements,
                "requirement_model": requirement_model,
                "traceability_matrix": "provided"
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "requirements": requirements,
                "requirement_model": requirement_model,
                "project_info": project_info,
                "methodology_guide": generation_methodology,
                "supported_standards": self.supported_standards,
                "default_standard": self.default_standard
            },
            reasoning_template="document_generation"
        )
        
        # Create SRS document structure
        srs_document = self._create_srs_document_structure(
            requirements, requirement_model, project_info, cot_result
        )
        
        # Apply document template
        template_id = project_info.get('template', 'srs_template')
        if template_id in self.document_templates:
            srs_document = self.apply_document_template(srs_document, template_id)
        
        # Store SRS document
        self.srs_documents[srs_document.id] = srs_document
        
        # Create artifact for SRS document
        if self.event_bus and self.session_id:
            artifact = self._create_srs_document_artifact(srs_document)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Generated SRS document with ID: {srs_document.id}")
        return srs_document
    
    def apply_document_template(self, srs_document: SRSDocument, template_id: str) -> SRSDocument:
        """
        Apply document template to SRS document.
        
        Args:
            srs_document: SRS document to apply template to
            template_id: ID of template to apply
            
        Returns:
            SRS document with template applied
        """
        logger.info(f"Applying template {template_id} to SRS document {srs_document.id}")
        
        if template_id not in self.document_templates:
            logger.warning(f"Template {template_id} not found, using default structure")
            return srs_document
        
        template = self.document_templates[template_id]
        
        # Apply template structure using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "apply_template",
            context={
                "template_name": template.name,
                "standard": template.standard,
                "content": srs_document.to_dict()
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "srs_document": srs_document.to_dict(),
                "template": template.to_dict(),
                "formatting_rules": template.formatting_rules
            },
            reasoning_template="template_application"
        )
        
        # Update document structure based on template
        updated_document = self._apply_template_structure(srs_document, template, cot_result)
        
        # Update compliance information
        updated_document.standard_compliance = [template.standard]
        
        logger.info(f"Applied template {template.name} to SRS document")
        return updated_document
    
    def organize_document_structure(self, content: Dict[str, Any], 
                                  standard: str = "IEEE 830") -> Dict[str, Any]:
        """
        Organize document structure according to specified standard.
        
        Args:
            content: Raw document content
            standard: Standard to follow (IEEE 830, ISO 29148, etc.)
            
        Returns:
            Organized document structure
        """
        logger.info(f"Organizing document structure according to {standard}")
        
        # Apply document organization methodology
        organization_methodology = self.apply_methodology("document_organization")
        
        # Get standard structure from knowledge modules
        standard_structure = self._get_standard_structure(standard)
        
        # Organize structure using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "apply_template",
            context={
                "template_name": f"{standard} template",
                "standard": standard,
                "content": content
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "content": content,
                "standard": standard,
                "standard_structure": standard_structure,
                "methodology_guide": organization_methodology
            },
            reasoning_template="document_organization"
        )
        
        # Parse organized structure
        organized_structure = self._parse_organized_structure(cot_result["response"], content, standard)
        
        logger.info(f"Organized document structure with {len(organized_structure.get('sections', []))} sections")
        return organized_structure
    
    def ensure_standard_compliance(self, document: SRSDocument, 
                                 standard: str = "IEEE 830") -> ComplianceReport:
        """
        Ensure document compliance with specified standard.
        
        Args:
            document: SRS document to check
            standard: Standard to check against
            
        Returns:
            Compliance report with violations and recommendations
        """
        logger.info(f"Checking compliance of document {document.id} against {standard}")
        
        # Apply compliance checking methodology
        compliance_methodology = self.apply_methodology("compliance_checking")
        
        # Get standard requirements from knowledge modules
        standard_requirements = self._get_standard_requirements(standard)
        
        # Check compliance using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "validate_compliance",
            context={
                "srs_document": document.to_dict(),
                "standard": standard
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "document": document.to_dict(),
                "standard": standard,
                "standard_requirements": standard_requirements,
                "methodology_guide": compliance_methodology,
                "quality_thresholds": self.quality_thresholds
            },
            reasoning_template="compliance_checking"
        )
        
        # Create compliance report
        compliance_report = self._create_compliance_report(document, standard, cot_result)
        
        # Store compliance report
        self.compliance_reports[compliance_report.id] = compliance_report
        
        # Create artifact for compliance report
        if self.event_bus and self.session_id:
            artifact = self._create_compliance_report_artifact(compliance_report)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Compliance check completed with score: {compliance_report.compliance_score:.2f}")
        return compliance_report
    
    def assess_document_quality(self, document: SRSDocument) -> Dict[str, float]:
        """
        Assess overall document quality metrics.
        
        Args:
            document: SRS document to assess
            
        Returns:
            Dictionary of quality metrics
        """
        logger.info(f"Assessing quality of document {document.id}")
        
        # Apply quality assessment methodology
        quality_methodology = self.apply_methodology("document_quality_assessment")
        
        # Assess quality using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "validate_compliance",
            context={
                "srs_document": document.to_dict(),
                "standard": document.standard_compliance[0] if document.standard_compliance else "IEEE 830"
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "document": document.to_dict(),
                "methodology_guide": quality_methodology,
                "quality_thresholds": self.quality_thresholds
            },
            reasoning_template="quality_assessment"
        )
        
        # Parse quality metrics
        quality_metrics = self._parse_quality_metrics(cot_result["response"])
        
        # Update document with quality scores
        document.completeness_score = quality_metrics.get("completeness", 0.0)
        document.consistency_score = quality_metrics.get("consistency", 0.0)
        document.traceability_score = quality_metrics.get("traceability", 0.0)
        
        logger.info(f"Quality assessment completed: {quality_metrics}")
        return quality_metrics
    
    def generate_document_from_artifacts(self, artifact_ids: List[str]) -> SRSDocument:
        """
        Generate SRS document from multiple artifacts.
        
        Args:
            artifact_ids: List of artifact IDs to include in document
            
        Returns:
            Generated SRS document
        """
        logger.info(f"Generating SRS document from {len(artifact_ids)} artifacts")
        
        # This would typically retrieve artifacts from the artifact pool
        # For now, we'll create a placeholder implementation
        artifacts_data = {
            "requirements": [],
            "requirement_model": {},
            "project_info": {
                "name": "Generated Project",
                "version": "1.0",
                "authors": [self.name]
            }
        }
        
        return self.generate_srs_document(
            artifacts_data["requirements"],
            artifacts_data["requirement_model"],
            artifacts_data["project_info"]
        )   
 def _create_srs_document_structure(self, requirements: List[Dict[str, Any]],
                                      requirement_model: Dict[str, Any],
                                      project_info: Dict[str, Any],
                                      cot_result: Dict[str, Any]) -> SRSDocument:
        """Create SRS document structure from inputs."""
        document_id = str(uuid.uuid4())
        
        # Create document header information
        srs_document = SRSDocument(
            id=document_id,
            title=f"{project_info.get('name', 'System')} Software Requirements Specification",
            version=project_info.get('version', '1.0'),
            date=datetime.now(),
            authors=project_info.get('authors', [self.name]),
            project_name=project_info.get('name', 'System'),
            standard_compliance=[self.default_standard]
        )
        
        # Create document sections
        srs_document.sections = self._create_document_sections(
            requirements, requirement_model, project_info
        )
        
        # Create revision history
        srs_document.revision_history = [{
            "version": srs_document.version,
            "date": srs_document.date.strftime("%Y-%m-%d"),
            "author": self.name,
            "description": "Initial version generated by ArchivistAgent"
        }]
        
        # Extract glossary from requirement model
        srs_document.glossary = requirement_model.get('glossary', {})
        
        # Create references
        srs_document.references = [
            {"id": "IEEE830", "title": "IEEE Std 830-1998", "author": "IEEE", "date": "1998"}
        ]
        
        return srs_document
    
    def _create_document_sections(self, requirements: List[Dict[str, Any]],
                                requirement_model: Dict[str, Any],
                                project_info: Dict[str, Any]) -> List[SRSSection]:
        """Create document sections following IEEE 830 structure."""
        sections = []
        
        # 1. Introduction
        intro_section = SRSSection(
            id=str(uuid.uuid4()),
            number="1",
            title="Introduction",
            content="This document specifies the requirements for the system."
        )
        
        intro_section.subsections = [
            SRSSection(
                id=str(uuid.uuid4()),
                number="1.1",
                title="Purpose",
                content=f"This document specifies the requirements for {project_info.get('name', 'the system')}."
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="1.2", 
                title="Scope",
                content=f"{project_info.get('name', 'The system')} is designed to meet the specified requirements."
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="1.3",
                title="Definitions, acronyms, and abbreviations",
                content=self._format_glossary(requirement_model.get('glossary', {}))
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="1.4",
                title="References",
                content="IEEE Std 830-1998, IEEE Recommended Practice for Software Requirements Specifications"
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="1.5",
                title="Overview",
                content="This document is organized into three main sections: Introduction, Overall Description, and Specific Requirements."
            )
        ]
        sections.append(intro_section)
        
        # 2. Overall Description
        overall_section = SRSSection(
            id=str(uuid.uuid4()),
            number="2",
            title="Overall description",
            content="This section provides an overview of the system."
        )
        
        overall_section.subsections = [
            SRSSection(
                id=str(uuid.uuid4()),
                number="2.1",
                title="Product perspective",
                content="The system operates as a standalone application."
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="2.2",
                title="Product functions",
                content=self._format_product_functions(requirements)
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="2.3",
                title="User characteristics",
                content=self._format_user_characteristics(requirement_model.get('stakeholders', []))
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="2.4",
                title="Constraints",
                content=self._format_constraints(requirement_model.get('constraints', []))
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="2.5",
                title="Assumptions and dependencies",
                content=self._format_assumptions_dependencies(requirement_model.get('assumptions', []))
            )
        ]
        sections.append(overall_section)
        
        # 3. Specific Requirements
        specific_section = SRSSection(
            id=str(uuid.uuid4()),
            number="3",
            title="Specific requirements",
            content="This section contains all the detailed requirements."
        )
        
        specific_section.subsections = [
            SRSSection(
                id=str(uuid.uuid4()),
                number="3.1",
                title="External interfaces",
                content="User interfaces, hardware interfaces, software interfaces, and communications interfaces."
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="3.2",
                title="Functions",
                content=self._format_functional_requirements(requirements)
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="3.3",
                title="Performance requirements",
                content=self._format_performance_requirements(requirements)
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="3.4",
                title="Logical database requirements",
                content="Data requirements and logical database design constraints."
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="3.5",
                title="Design constraints",
                content="Standards compliance, hardware limitations, and other design constraints."
            ),
            SRSSection(
                id=str(uuid.uuid4()),
                number="3.6",
                title="Software system attributes",
                content=self._format_system_attributes(requirements)
            )
        ]
        sections.append(specific_section)
        
        return sections
    
    def _apply_template_structure(self, document: SRSDocument, 
                                template: DocumentTemplate,
                                cot_result: Dict[str, Any]) -> SRSDocument:
        """Apply template structure to document."""
        # This is a simplified implementation
        # In practice, this would apply detailed template formatting
        
        # Update document metadata based on template
        if template.standard not in document.standard_compliance:
            document.standard_compliance.append(template.standard)
        
        # Apply formatting rules (simplified)
        for section in document.sections:
            self._apply_section_formatting(section, template.formatting_rules)
        
        return document
    
    def _apply_section_formatting(self, section: SRSSection, formatting_rules: Dict[str, Any]) -> None:
        """Apply formatting rules to a section."""
        # Apply numbering format
        numbering_format = formatting_rules.get("numbering", "hierarchical")
        if numbering_format == "hierarchical":
            # Already using hierarchical numbering
            pass
        
        # Apply content formatting
        if "requirements_format" in formatting_rules:
            # Format requirements within the section
            pass
        
        # Recursively apply to subsections
        for subsection in section.subsections:
            self._apply_section_formatting(subsection, formatting_rules)
    
    def _get_standard_structure(self, standard: str) -> Dict[str, Any]:
        """Get standard structure from knowledge modules."""
        for module_id, module in self.knowledge_modules.items():
            if (module.module_type == KnowledgeType.STANDARDS and 
                standard.lower() in module_id.lower()):
                return module.content.get("document_structure", {})
        
        # Return default IEEE 830 structure
        return {
            "1": {"title": "Introduction"},
            "2": {"title": "Overall description"},
            "3": {"title": "Specific requirements"}
        }
    
    def _get_standard_requirements(self, standard: str) -> Dict[str, Any]:
        """Get standard requirements from knowledge modules."""
        for module_id, module in self.knowledge_modules.items():
            if (module.module_type == KnowledgeType.STANDARDS and 
                standard.lower() in module_id.lower()):
                return module.content.get("quality_characteristics", {})
        
        # Return default requirements
        return {
            "completeness": {"description": "All requirements must be specified"},
            "consistency": {"description": "No conflicting requirements"},
            "correctness": {"description": "Requirements must be accurate"}
        }
    
    def _parse_organized_structure(self, response: str, content: Dict[str, Any], 
                                 standard: str) -> Dict[str, Any]:
        """Parse organized structure from CoT response."""
        # Simplified parsing - in practice would be more sophisticated
        return {
            "sections": content.get("sections", []),
            "standard": standard,
            "organization_applied": True
        }
    
    def _create_compliance_report(self, document: SRSDocument, standard: str,
                                cot_result: Dict[str, Any]) -> ComplianceReport:
        """Create compliance report from CoT result."""
        report_id = str(uuid.uuid4())
        
        # Parse compliance score from response (simplified)
        compliance_score = self._extract_compliance_score(cot_result["response"])
        
        # Parse violations
        violations = self._extract_violations(cot_result["response"])
        
        # Parse recommendations
        recommendations = self._extract_recommendations(cot_result["response"])
        
        # Calculate quality metrics
        quality_metrics = {
            "completeness": document.completeness_score or 0.8,
            "consistency": document.consistency_score or 0.85,
            "traceability": document.traceability_score or 0.75
        }
        
        return ComplianceReport(
            id=report_id,
            document_id=document.id,
            standard=standard,
            compliance_score=compliance_score,
            violations=violations,
            recommendations=recommendations,
            quality_metrics=quality_metrics
        )
    
    def _parse_quality_metrics(self, response: str) -> Dict[str, float]:
        """Parse quality metrics from response."""
        metrics = {
            "completeness": 0.8,
            "consistency": 0.85,
            "traceability": 0.75,
            "clarity": 0.8,
            "verifiability": 0.7
        }
        
        # Simple parsing logic - in practice would be more sophisticated
        lines = response.split('\n')
        for line in lines:
            if 'completeness' in line.lower() and ':' in line:
                try:
                    score = float(re.search(r'(\d+\.?\d*)', line.split(':')[1]).group(1))
                    if score <= 1.0:
                        metrics["completeness"] = score
                    elif score <= 100:
                        metrics["completeness"] = score / 100
                except:
                    pass
            elif 'consistency' in line.lower() and ':' in line:
                try:
                    score = float(re.search(r'(\d+\.?\d*)', line.split(':')[1]).group(1))
                    if score <= 1.0:
                        metrics["consistency"] = score
                    elif score <= 100:
                        metrics["consistency"] = score / 100
                except:
                    pass
        
        return metrics
    
    def _extract_compliance_score(self, response: str) -> float:
        """Extract compliance score from response."""
        # Simple extraction logic
        lines = response.split('\n')
        for line in lines:
            if 'compliance' in line.lower() and 'score' in line.lower():
                try:
                    score = float(re.search(r'(\d+\.?\d*)', line).group(1))
                    if score <= 1.0:
                        return score
                    elif score <= 100:
                        return score / 100
                except:
                    pass
        return 0.8  # Default score
    
    def _extract_violations(self, response: str) -> List[Dict[str, Any]]:
        """Extract violations from response."""
        violations = []
        lines = response.split('\n')
        
        for line in lines:
            if 'violation' in line.lower() or 'error' in line.lower():
                violations.append({
                    "type": "compliance_violation",
                    "description": line.strip(),
                    "severity": "medium"
                })
        
        return violations
    
    def _extract_recommendations(self, response: str) -> List[str]:
        """Extract recommendations from response."""
        recommendations = []
        lines = response.split('\n')
        
        for line in lines:
            if 'recommend' in line.lower() or 'suggest' in line.lower():
                recommendations.append(line.strip())
        
        return recommendations
    
    def _format_glossary(self, glossary: Dict[str, str]) -> str:
        """Format glossary for document."""
        if not glossary:
            return "No specific terms defined."
        
        formatted = []
        for term, definition in glossary.items():
            formatted.append(f"{term}: {definition}")
        
        return "\n".join(formatted)
    
    def _format_product_functions(self, requirements: List[Dict[str, Any]]) -> str:
        """Format product functions from requirements."""
        functions = []
        for req in requirements:
            if req.get('category') == 'functional':
                functions.append(f"- {req.get('title', 'Function')}: {req.get('description', '')}")
        
        return "\n".join(functions) if functions else "Product functions to be defined."
    
    def _format_user_characteristics(self, stakeholders: List[Dict[str, Any]]) -> str:
        """Format user characteristics from stakeholders."""
        if not stakeholders:
            return "User characteristics to be defined."
        
        characteristics = []
        for stakeholder in stakeholders:
            characteristics.append(f"- {stakeholder.get('role', 'User')}: {stakeholder.get('description', '')}")
        
        return "\n".join(characteristics)
    
    def _format_constraints(self, constraints: List[Dict[str, Any]]) -> str:
        """Format constraints."""
        if not constraints:
            return "No specific constraints identified."
        
        formatted = []
        for constraint in constraints:
            if isinstance(constraint, dict):
                formatted.append(f"- {constraint.get('title', 'Constraint')}: {constraint.get('description', '')}")
            else:
                formatted.append(f"- {constraint}")
        
        return "\n".join(formatted)
    
    def _format_assumptions_dependencies(self, assumptions: List[str]) -> str:
        """Format assumptions and dependencies."""
        if not assumptions:
            return "No specific assumptions or dependencies identified."
        
        formatted = []
        for assumption in assumptions:
            formatted.append(f"- {assumption}")
        
        return "\n".join(formatted)
    
    def _format_functional_requirements(self, requirements: List[Dict[str, Any]]) -> str:
        """Format functional requirements."""
        functional_reqs = [req for req in requirements if req.get('category') == 'functional']
        
        if not functional_reqs:
            return "Functional requirements to be specified."
        
        formatted = []
        for i, req in enumerate(functional_reqs, 1):
            formatted.append(f"FUNC-{i:03d}: {req.get('title', 'Requirement')}")
            formatted.append(f"Description: {req.get('description', '')}")
            if req.get('acceptance_criteria'):
                formatted.append(f"Acceptance Criteria: {req.get('acceptance_criteria')}")
            formatted.append("")
        
        return "\n".join(formatted)
    
    def _format_performance_requirements(self, requirements: List[Dict[str, Any]]) -> str:
        """Format performance requirements."""
        perf_reqs = [req for req in requirements if req.get('category') == 'non_functional' and 'performance' in req.get('title', '').lower()]
        
        if not perf_reqs:
            return "Performance requirements to be specified."
        
        formatted = []
        for i, req in enumerate(perf_reqs, 1):
            formatted.append(f"PERF-{i:03d}: {req.get('title', 'Performance Requirement')}")
            formatted.append(f"Description: {req.get('description', '')}")
            formatted.append("")
        
        return "\n".join(formatted)
    
    def _format_system_attributes(self, requirements: List[Dict[str, Any]]) -> str:
        """Format system attributes."""
        attr_reqs = [req for req in requirements if req.get('category') == 'non_functional']
        
        if not attr_reqs:
            return "System attributes to be specified."
        
        formatted = []
        for req in attr_reqs:
            formatted.append(f"- {req.get('title', 'Attribute')}: {req.get('description', '')}")
        
        return "\n".join(formatted)
    
    def _create_srs_document_artifact(self, srs_document: SRSDocument) -> Artifact:
        """Create artifact for SRS document."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.SRS_DOCUMENT,
            content=srs_document.to_dict(),
            metadata=ArtifactMetadata(
                tags=["srs", "document", "requirements"],
                source_agent=self.name,
                quality_score=srs_document.completeness_score
            ),
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT
        )
    
    def _create_compliance_report_artifact(self, report: ComplianceReport) -> Artifact:
        """Create artifact for compliance report."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REVIEW_REPORT,
            content=report.to_dict(),
            metadata=ArtifactMetadata(
                tags=["compliance", "report", "quality"],
                source_agent=self.name,
                related_artifacts=[report.document_id],
                quality_score=report.compliance_score
            ),
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT
        )