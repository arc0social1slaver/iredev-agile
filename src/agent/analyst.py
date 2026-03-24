"""
Analyst Agent for iReDev framework.
Transforms user requirements into system requirements, creates requirement models,
and establishes traceability matrices.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import logging
import uuid

from .knowledge_driven_agent import KnowledgeDrivenAgent
from ..knowledge.base_types import KnowledgeType
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus, ArtifactMetadata

logger = logging.getLogger(__name__)


@dataclass
class SystemRequirement:
    """Represents a system requirement derived from user requirements."""
    id: str
    title: str
    description: str
    category: str  # functional, non_functional, constraint
    priority: str  # critical, high, medium, low
    source_user_requirements: List[str]  # IDs of source user requirements
    rationale: str
    acceptance_criteria: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    verification_method: str = "inspection"  # inspection, analysis, test, demonstration
    complexity: str = "medium"  # low, medium, high
    effort_estimate: Optional[str] = None
    business_value: str = "medium"  # low, medium, high
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert system requirement to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "source_user_requirements": self.source_user_requirements,
            "rationale": self.rationale,
            "acceptance_criteria": self.acceptance_criteria,
            "assumptions": self.assumptions,
            "dependencies": self.dependencies,
            "risks": self.risks,
            "verification_method": self.verification_method,
            "complexity": self.complexity,
            "effort_estimate": self.effort_estimate,
            "business_value": self.business_value,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class RequirementModel:
    """Represents a structured requirement model with relationships."""
    id: str
    functional_requirements: List[SystemRequirement] = field(default_factory=list)
    non_functional_requirements: List[SystemRequirement] = field(default_factory=list)
    constraints: List[SystemRequirement] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    dependencies: List[Dict[str, Any]] = field(default_factory=list)
    stakeholders: List[Dict[str, Any]] = field(default_factory=list)
    glossary: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert requirement model to dictionary."""
        return {
            "id": self.id,
            "functional_requirements": [req.to_dict() for req in self.functional_requirements],
            "non_functional_requirements": [req.to_dict() for req in self.non_functional_requirements],
            "constraints": [req.to_dict() for req in self.constraints],
            "assumptions": self.assumptions,
            "dependencies": self.dependencies,
            "stakeholders": self.stakeholders,
            "glossary": self.glossary,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class TraceabilityLink:
    """Represents a traceability link between requirements."""
    id: str
    source_id: str
    target_id: str
    link_type: str  # derives_from, depends_on, conflicts_with, refines, implements
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert traceability link to dictionary."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "link_type": self.link_type,
            "description": self.description,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class TraceabilityMatrix:
    """Represents a traceability matrix for requirements."""
    id: str
    links: List[TraceabilityLink] = field(default_factory=list)
    coverage_analysis: Dict[str, Any] = field(default_factory=dict)
    orphaned_requirements: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert traceability matrix to dictionary."""
        return {
            "id": self.id,
            "links": [link.to_dict() for link in self.links],
            "coverage_analysis": self.coverage_analysis,
            "orphaned_requirements": self.orphaned_requirements,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class RequirementConflict:
    """Represents a conflict between requirements."""
    id: str
    conflicting_requirements: List[str]
    conflict_type: str  # contradiction, inconsistency, overlap, resource_conflict
    description: str
    severity: str  # critical, high, medium, low
    resolution_suggestions: List[str] = field(default_factory=list)
    status: str = "open"  # open, resolved, deferred
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert requirement conflict to dictionary."""
        return {
            "id": self.id,
            "conflicting_requirements": self.conflicting_requirements,
            "conflict_type": self.conflict_type,
            "description": self.description,
            "severity": self.severity,
            "resolution_suggestions": self.resolution_suggestions,
            "status": self.status,
            "created_at": self.created_at.isoformat()
        }


class AnalystAgent(KnowledgeDrivenAgent):
    """
    Analyst Agent for transforming user requirements into system requirements
    and creating structured requirement models.
    
    Integrates requirements analysis methodologies, modeling techniques,
    and traceability management.
    """
    
    def __init__(self, config_path: Optional[str] = None, **kwargs):
        # Define required knowledge modules for analyst agent
        knowledge_modules = [
            "requirements_analysis",
            "requirements_modeling",
            "traceability_management",
            "requirements_prioritization",
            "conflict_resolution",
            "verification_validation"
        ]
        
        super().__init__(
            name="analyst",
            knowledge_modules=knowledge_modules,
            config_path=config_path,
            **kwargs
        )
        
        # Agent configuration
        self.prioritization_methods = self.config.get('prioritization_methods', [
            'moscow', 'kano', 'value_vs_effort', 'risk_based'
        ])
        self.verification_methods = self.config.get('verification_methods', [
            'inspection', 'analysis', 'test', 'demonstration'
        ])
        
        # Agent state
        self.system_requirements: Dict[str, SystemRequirement] = {}
        self.requirement_models: Dict[str, RequirementModel] = {}
        self.traceability_matrices: Dict[str, TraceabilityMatrix] = {}
        self.requirement_conflicts: Dict[str, RequirementConflict] = {}
        
        # Initialize profile prompt
        self.profile_prompt = self._create_profile_prompt()
        self.add_to_memory("system", self.profile_prompt)
        
        logger.info(f"Initialized AnalystAgent with {len(knowledge_modules)} knowledge modules")
    
    def _create_profile_prompt(self) -> str:
        """Create profile prompt for the analyst agent."""
        return """You are an experienced requirements analyst and systems engineer.

Mission:
Transform user requirements into precise, verifiable system requirements, create structured requirement models, and establish comprehensive traceability.

Personality:
Analytical, systematic, and detail-oriented; skilled in abstraction and technical specification.

Workflow:
1. Analyze user requirements and system context.
2. Transform user needs into system-level requirements with acceptance criteria.
3. Categorize requirements (functional, non-functional, constraints).
4. Create structured requirement models with relationships and dependencies.
5. Establish traceability matrix linking system requirements to user requirements.
6. Prioritize requirements and detect conflicts.

Experience & Preferred Practices:
1. Follow ISO/IEC/IEEE 29148 and IEEE 830 standards.
2. Apply requirements analysis methodologies (MoSCoW, Kano, value vs effort).
3. Ensure requirements are specific, measurable, achievable, relevant, and time-bound (SMART).
4. Establish bidirectional traceability.
5. Validate requirements for completeness, consistency, and verifiability.

Internal Chain of Thought (visible to the agent only):
1. Analyze user requirements to extract system-level implications.
2. Abstract user needs into technical specifications.
3. Categorize and structure requirements by type and priority.
4. Identify dependencies and relationships between requirements.
5. Map system requirements back to originating user requirements for traceability.
6. Detect conflicts and inconsistencies through systematic analysis.
"""
    
    def _get_action_prompt(self, action: str, context: Dict[str, Any] = None) -> str:
        """Get action-specific prompt for a given action."""
        action_prompts = {
            "transform_requirements": """Action: Transform user requirements into system requirements.

Context:
- User requirements: {user_requirements}
- System context: {system_context}
- Domain: {domain}

Instructions:
1. Analyze each user requirement to extract system-level implications.
2. Transform into precise system requirements with clear acceptance criteria.
3. Categorize as functional, non-functional, or constraint.
4. Assign priority and verification method.
5. Link system requirements to source user requirements.
""",
            "create_requirement_model": """Action: Create structured requirement model.

Context:
- System requirements: {requirements}
- Stakeholder info: {stakeholder_info}
- Domain: {domain}

Instructions:
1. Organize requirements into functional, non-functional, and constraints.
2. Identify assumptions and dependencies.
3. Define stakeholders and their roles.
4. Create glossary of key terms.
5. Establish relationships between requirements.
""",
            "establish_traceability": """Action: Establish traceability matrix.

Context:
- System requirements: {system_requirements}
- User requirements: {user_requirements}

Instructions:
1. Create links from system requirements to user requirements.
2. Identify coverage gaps (orphaned requirements).
3. Analyze forward and backward traceability.
4. Document link types (derives_from, depends_on, implements, etc.).
""",
            "prioritize_requirements": """Action: Prioritize system requirements.

Context:
- Requirements: {requirements}
- Criteria: {criteria}
- Business context: {business_context}

Instructions:
1. Apply prioritization method (MoSCoW, value vs effort, risk-based).
2. Assess business value, implementation risk, and user impact.
3. Sort requirements by priority.
4. Document prioritization rationale.
""",
            "detect_conflicts": """Action: Detect requirement conflicts.

Context:
- Requirements: {requirements}

Instructions:
1. Analyze requirements for contradictions and inconsistencies.
2. Identify resource conflicts and overlaps.
3. Categorize conflict types (contradiction, inconsistency, overlap, resource_conflict).
4. Assess conflict severity.
5. Suggest resolution approaches.
"""
        }
        
        base_prompt = action_prompts.get(action, f"Action: {action}")
        if context:
            try:
                return base_prompt.format(**context)
            except:
                return base_prompt
        return base_prompt    
 
   def transform_to_system_requirements(self, user_requirements: List[Dict[str, Any]], 
                                       context: Dict[str, Any]) -> List[SystemRequirement]:
        """
        Transform user requirements into system requirements.
        
        Args:
            user_requirements: List of user requirements from interviews and user agents
            context: Context information including domain, constraints, etc.
            
        Returns:
            List of transformed system requirements
        """
        logger.info(f"Transforming {len(user_requirements)} user requirements to system requirements")
        
        # Apply requirements analysis methodology
        analysis_methodology = self.apply_methodology("requirements_transformation")
        
        # Transform requirements using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "transform_requirements",
            context={
                "user_requirements": user_requirements,
                "system_context": context,
                "domain": context.get("domain", "general")
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "user_requirements": user_requirements,
                "system_context": context,
                "methodology_guide": analysis_methodology,
                "verification_methods": self.verification_methods
            },
            reasoning_template="requirements_analysis"
        )
        
        # Parse system requirements from response
        system_reqs = self._parse_system_requirements_from_response(
            cot_result["response"], user_requirements, context
        )
        
        # Store system requirements
        for req in system_reqs:
            self.system_requirements[req.id] = req
        
        # Create artifact for system requirements
        if self.event_bus and self.session_id:
            artifact = self._create_system_requirements_artifact(system_reqs, context)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Transformed to {len(system_reqs)} system requirements")
        return system_reqs
    
    def create_requirement_model(self, requirements: List[SystemRequirement],
                               stakeholder_info: Dict[str, Any]) -> RequirementModel:
        """
        Create a structured requirement model from system requirements.
        
        Args:
            requirements: List of system requirements
            stakeholder_info: Information about stakeholders and their roles
            
        Returns:
            Structured requirement model
        """
        logger.info(f"Creating requirement model from {len(requirements)} requirements")
        
        # Apply requirements modeling methodology
        modeling_methodology = self.apply_methodology("requirements_modeling")
        
        # Create requirement model using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "create_requirement_model",
            context={
                "requirements": [req.to_dict() for req in requirements],
                "stakeholder_info": stakeholder_info,
                "domain": "general"
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "requirements": [req.to_dict() for req in requirements],
                "stakeholder_info": stakeholder_info,
                "methodology_guide": modeling_methodology
            },
            reasoning_template="requirements_modeling"
        )
        
        # Create requirement model
        model = self._create_requirement_model_from_requirements(requirements, stakeholder_info, cot_result)
        
        # Store requirement model
        self.requirement_models[model.id] = model
        
        # Create artifact for requirement model
        if self.event_bus and self.session_id:
            artifact = self._create_requirement_model_artifact(model)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Created requirement model with ID: {model.id}")
        return model
    
    def establish_traceability_matrix(self, requirements: List[SystemRequirement],
                                    user_requirements: List[Dict[str, Any]]) -> TraceabilityMatrix:
        """
        Establish traceability matrix linking system requirements to user requirements.
        
        Args:
            requirements: List of system requirements
            user_requirements: List of original user requirements
            
        Returns:
            Traceability matrix with links and coverage analysis
        """
        logger.info(f"Establishing traceability matrix for {len(requirements)} system requirements")
        
        # Apply traceability management methodology
        traceability_methodology = self.apply_methodology("traceability_management")
        
        # Create traceability links using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "establish_traceability",
            context={
                "system_requirements": [req.to_dict() for req in requirements],
                "user_requirements": user_requirements
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "system_requirements": [req.to_dict() for req in requirements],
                "user_requirements": user_requirements,
                "methodology_guide": traceability_methodology
            },
            reasoning_template="traceability_analysis"
        )
        
        # Create traceability matrix
        matrix = self._create_traceability_matrix(requirements, user_requirements, cot_result)
        
        # Store traceability matrix
        self.traceability_matrices[matrix.id] = matrix
        
        # Create artifact for traceability matrix
        if self.event_bus and self.session_id:
            artifact = self._create_traceability_matrix_artifact(matrix)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Created traceability matrix with {len(matrix.links)} links")
        return matrix
    
    def prioritize_requirements(self, requirements: List[SystemRequirement], 
                              criteria: Dict[str, Any]) -> List[SystemRequirement]:
        """
        Prioritize requirements based on specified criteria.
        
        Args:
            requirements: List of system requirements to prioritize
            criteria: Prioritization criteria (business_value, risk, effort, etc.)
            
        Returns:
            List of requirements sorted by priority
        """
        logger.info(f"Prioritizing {len(requirements)} requirements using criteria: {list(criteria.keys())}")
        
        # Apply prioritization methodology
        prioritization_methodology = self.apply_methodology("requirements_prioritization")
        
        # Prioritize requirements using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "prioritize_requirements",
            context={
                "requirements": [req.to_dict() for req in requirements],
                "criteria": criteria,
                "business_context": criteria
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "requirements": [req.to_dict() for req in requirements],
                "criteria": criteria,
                "methodology_guide": prioritization_methodology,
                "prioritization_methods": self.prioritization_methods
            },
            reasoning_template="requirements_prioritization"
        )
        
        # Parse prioritized requirements
        prioritized_reqs = self._parse_prioritized_requirements(cot_result["response"], requirements)
        
        # Update stored requirements with new priorities
        for req in prioritized_reqs:
            if req.id in self.system_requirements:
                self.system_requirements[req.id] = req
        
        logger.info(f"Prioritized {len(prioritized_reqs)} requirements")
        return prioritized_reqs
    
    def detect_requirement_conflicts(self, requirements: List[SystemRequirement]) -> List[RequirementConflict]:
        """
        Detect conflicts between requirements.
        
        Args:
            requirements: List of system requirements to analyze
            
        Returns:
            List of detected conflicts
        """
        logger.info(f"Detecting conflicts in {len(requirements)} requirements")
        
        # Apply conflict detection methodology
        conflict_methodology = self.apply_methodology("conflict_detection")
        
        # Detect conflicts using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "detect_conflicts",
            context={
                "requirements": [req.to_dict() for req in requirements]
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "requirements": [req.to_dict() for req in requirements],
                "methodology_guide": conflict_methodology
            },
            reasoning_template="conflict_analysis"
        )
        
        # Parse detected conflicts
        conflicts = self._parse_requirement_conflicts(cot_result["response"], requirements)
        
        # Store conflicts
        for conflict in conflicts:
            self.requirement_conflicts[conflict.id] = conflict
        
        logger.info(f"Detected {len(conflicts)} requirement conflicts")
        return conflicts
    
    def resolve_requirement_conflicts(self, conflicts: List[RequirementConflict],
                                    stakeholder_preferences: Dict[str, Any]) -> List[RequirementConflict]:
        """
        Provide resolution suggestions for requirement conflicts.
        
        Args:
            conflicts: List of conflicts to resolve
            stakeholder_preferences: Stakeholder preferences for resolution
            
        Returns:
            List of conflicts with resolution suggestions
        """
        logger.info(f"Resolving {len(conflicts)} requirement conflicts")
        
        # Apply conflict resolution methodology
        resolution_methodology = self.apply_methodology("conflict_resolution")
        
        resolved_conflicts = []
        
        for conflict in conflicts:
            # Generate resolution suggestions using CoT reasoning
            cot_result = self.generate_with_cot(
                prompt=f"Provide resolution suggestions for requirement conflict: {conflict.description}",
                context={
                    "conflict": conflict.to_dict(),
                    "stakeholder_preferences": stakeholder_preferences,
                    "methodology_guide": resolution_methodology
                },
                reasoning_template="conflict_resolution"
            )
            
            # Update conflict with resolution suggestions
            updated_conflict = self._update_conflict_with_resolutions(conflict, cot_result["response"])
            resolved_conflicts.append(updated_conflict)
            
            # Update stored conflict
            self.requirement_conflicts[updated_conflict.id] = updated_conflict
        
        logger.info(f"Generated resolution suggestions for {len(resolved_conflicts)} conflicts")
        return resolved_conflicts
    
    def analyze_requirement_changes(self, original_requirements: List[SystemRequirement],
                                  updated_requirements: List[SystemRequirement]) -> Dict[str, Any]:
        """
        Analyze the impact of requirement changes.
        
        Args:
            original_requirements: Original list of requirements
            updated_requirements: Updated list of requirements
            
        Returns:
            Change impact analysis
        """
        logger.info("Analyzing requirement changes and impact")
        
        # Apply change impact analysis methodology
        impact_methodology = self.apply_methodology("change_impact_analysis")
        
        # Analyze changes using CoT reasoning
        cot_result = self.generate_with_cot(
            prompt="Analyze the impact of requirement changes on the system",
            context={
                "original_requirements": [req.to_dict() for req in original_requirements],
                "updated_requirements": [req.to_dict() for req in updated_requirements],
                "methodology_guide": impact_methodology
            },
            reasoning_template="change_impact_analysis"
        )
        
        # Parse change analysis
        change_analysis = self._parse_change_analysis(cot_result["response"], original_requirements, updated_requirements)
        
        logger.info("Completed requirement change impact analysis")
        return change_analysis    
 
   def _parse_system_requirements_from_response(self, response: str, 
                                               user_requirements: List[Dict[str, Any]],
                                               context: Dict[str, Any]) -> List[SystemRequirement]:
        """Parse system requirements from LLM response."""
        system_reqs = []
        
        # Simple parsing logic - in production, this would be more sophisticated
        lines = response.split('\n')
        current_req = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('REQUIREMENT:') or line.startswith('Title:'):
                if current_req:
                    req = self._create_system_requirement_from_dict(current_req, user_requirements)
                    if req:
                        system_reqs.append(req)
                current_req = {'title': line.split(':', 1)[1].strip()}
            elif line.startswith('Description:'):
                current_req['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Category:'):
                current_req['category'] = line.split(':', 1)[1].strip()
            elif line.startswith('Priority:'):
                current_req['priority'] = line.split(':', 1)[1].strip()
            elif line.startswith('Rationale:'):
                current_req['rationale'] = line.split(':', 1)[1].strip()
            elif line.startswith('Acceptance Criteria:'):
                current_req['acceptance_criteria'] = line.split(':', 1)[1].strip()
            elif line.startswith('Verification Method:'):
                current_req['verification_method'] = line.split(':', 1)[1].strip()
        
        # Handle last requirement
        if current_req:
            req = self._create_system_requirement_from_dict(current_req, user_requirements)
            if req:
                system_reqs.append(req)
        
        # Create default requirements if parsing failed
        if not system_reqs:
            system_reqs = self._create_default_system_requirements(user_requirements, context)
        
        return system_reqs
    
    def _create_system_requirement_from_dict(self, req_dict: Dict[str, Any],
                                           user_requirements: List[Dict[str, Any]]) -> Optional[SystemRequirement]:
        """Create SystemRequirement object from parsed dictionary."""
        try:
            return SystemRequirement(
                id=str(uuid.uuid4()),
                title=req_dict.get('title', 'System Requirement'),
                description=req_dict.get('description', 'System requirement description'),
                category=req_dict.get('category', 'functional'),
                priority=req_dict.get('priority', 'medium'),
                source_user_requirements=[req.get('id', str(uuid.uuid4())) for req in user_requirements[:2]],
                rationale=req_dict.get('rationale', 'Derived from user requirements'),
                acceptance_criteria=self._parse_list_field(req_dict.get('acceptance_criteria', '')),
                verification_method=req_dict.get('verification_method', 'inspection')
            )
        except Exception as e:
            logger.warning(f"Failed to create system requirement from dict: {e}")
            return None
    
    def _create_default_system_requirements(self, user_requirements: List[Dict[str, Any]],
                                          context: Dict[str, Any]) -> List[SystemRequirement]:
        """Create default system requirements when parsing fails."""
        return [
            SystemRequirement(
                id=str(uuid.uuid4()),
                title="User Authentication",
                description="System shall provide secure user authentication mechanism",
                category="functional",
                priority="high",
                source_user_requirements=[req.get('id', str(uuid.uuid4())) for req in user_requirements[:1]],
                rationale="Required for system security and user access control",
                acceptance_criteria=["User can login with valid credentials", "Invalid credentials are rejected"],
                verification_method="test"
            ),
            SystemRequirement(
                id=str(uuid.uuid4()),
                title="System Performance",
                description="System shall respond to user requests within acceptable time limits",
                category="non_functional",
                priority="medium",
                source_user_requirements=[req.get('id', str(uuid.uuid4())) for req in user_requirements[:1]],
                rationale="Required for acceptable user experience",
                acceptance_criteria=["Response time < 2 seconds for 95% of requests"],
                verification_method="test"
            )
        ]
    
    def _create_requirement_model_from_requirements(self, requirements: List[SystemRequirement],
                                                  stakeholder_info: Dict[str, Any],
                                                  cot_result: Dict[str, Any]) -> RequirementModel:
        """Create requirement model from system requirements."""
        # Categorize requirements
        functional_reqs = [req for req in requirements if req.category == 'functional']
        non_functional_reqs = [req for req in requirements if req.category == 'non_functional']
        constraints = [req for req in requirements if req.category == 'constraint']
        
        # Extract assumptions and dependencies from CoT result
        assumptions = self._extract_assumptions_from_cot(cot_result)
        dependencies = self._extract_dependencies_from_cot(cot_result)
        glossary = self._extract_glossary_from_cot(cot_result)
        
        return RequirementModel(
            id=str(uuid.uuid4()),
            functional_requirements=functional_reqs,
            non_functional_requirements=non_functional_reqs,
            constraints=constraints,
            assumptions=assumptions,
            dependencies=dependencies,
            stakeholders=self._format_stakeholder_info(stakeholder_info),
            glossary=glossary
        )
    
    def _create_traceability_matrix(self, requirements: List[SystemRequirement],
                                  user_requirements: List[Dict[str, Any]],
                                  cot_result: Dict[str, Any]) -> TraceabilityMatrix:
        """Create traceability matrix from requirements."""
        links = []
        
        # Create traceability links
        for req in requirements:
            for source_id in req.source_user_requirements:
                link = TraceabilityLink(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    target_id=req.id,
                    link_type="derives_from",
                    description=f"System requirement {req.title} derives from user requirement"
                )
                links.append(link)
        
        # Analyze coverage
        coverage_analysis = self._analyze_traceability_coverage(links, requirements, user_requirements)
        
        # Find orphaned requirements
        orphaned_requirements = self._find_orphaned_requirements(links, requirements)
        
        return TraceabilityMatrix(
            id=str(uuid.uuid4()),
            links=links,
            coverage_analysis=coverage_analysis,
            orphaned_requirements=orphaned_requirements
        )
    
    def _parse_prioritized_requirements(self, response: str, 
                                      requirements: List[SystemRequirement]) -> List[SystemRequirement]:
        """Parse prioritized requirements from response."""
        # Simple priority parsing - in production would be more sophisticated
        priority_map = {}
        lines = response.split('\n')
        
        for line in lines:
            if 'Priority:' in line and 'ID:' in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'ID:' and i + 1 < len(parts):
                        req_id = parts[i + 1]
                    elif part == 'Priority:' and i + 1 < len(parts):
                        priority = parts[i + 1]
                        if req_id in [req.id for req in requirements]:
                            priority_map[req_id] = priority
        
        # Update priorities and sort
        for req in requirements:
            if req.id in priority_map:
                req.priority = priority_map[req.id]
        
        # Sort by priority (critical > high > medium > low)
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        return sorted(requirements, key=lambda r: priority_order.get(r.priority, 2))
    
    def _parse_requirement_conflicts(self, response: str, 
                                   requirements: List[SystemRequirement]) -> List[RequirementConflict]:
        """Parse requirement conflicts from response."""
        conflicts = []
        
        # Simple parsing logic
        lines = response.split('\n')
        current_conflict = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('CONFLICT:') or line.startswith('Description:'):
                if current_conflict:
                    conflict = self._create_conflict_from_dict(current_conflict, requirements)
                    if conflict:
                        conflicts.append(conflict)
                current_conflict = {'description': line.split(':', 1)[1].strip()}
            elif line.startswith('Type:'):
                current_conflict['conflict_type'] = line.split(':', 1)[1].strip()
            elif line.startswith('Severity:'):
                current_conflict['severity'] = line.split(':', 1)[1].strip()
            elif line.startswith('Requirements:'):
                current_conflict['requirements'] = line.split(':', 1)[1].strip()
        
        # Handle last conflict
        if current_conflict:
            conflict = self._create_conflict_from_dict(current_conflict, requirements)
            if conflict:
                conflicts.append(conflict)
        
        return conflicts
    
    def _create_conflict_from_dict(self, conflict_dict: Dict[str, Any],
                                 requirements: List[SystemRequirement]) -> Optional[RequirementConflict]:
        """Create RequirementConflict from parsed dictionary."""
        try:
            # Extract conflicting requirement IDs (simplified)
            conflicting_reqs = [req.id for req in requirements[:2]]  # Simplified for demo
            
            return RequirementConflict(
                id=str(uuid.uuid4()),
                conflicting_requirements=conflicting_reqs,
                conflict_type=conflict_dict.get('conflict_type', 'inconsistency'),
                description=conflict_dict.get('description', 'Requirements conflict detected'),
                severity=conflict_dict.get('severity', 'medium')
            )
        except Exception as e:
            logger.warning(f"Failed to create conflict from dict: {e}")
            return None
    
    def _update_conflict_with_resolutions(self, conflict: RequirementConflict, 
                                        response: str) -> RequirementConflict:
        """Update conflict with resolution suggestions from response."""
        # Parse resolution suggestions from response
        suggestions = []
        lines = response.split('\n')
        
        for line in lines:
            line = line.strip()
            if line.startswith('SUGGESTION:') or line.startswith('-'):
                suggestion = line.replace('SUGGESTION:', '').replace('-', '').strip()
                if suggestion:
                    suggestions.append(suggestion)
        
        # Update conflict
        conflict.resolution_suggestions = suggestions if suggestions else [
            "Review conflicting requirements with stakeholders",
            "Prioritize requirements based on business value",
            "Consider alternative implementation approaches"
        ]
        
        return conflict
    
    def _parse_change_analysis(self, response: str, 
                             original_requirements: List[SystemRequirement],
                             updated_requirements: List[SystemRequirement]) -> Dict[str, Any]:
        """Parse change analysis from response."""
        return {
            "total_original": len(original_requirements),
            "total_updated": len(updated_requirements),
            "added_requirements": max(0, len(updated_requirements) - len(original_requirements)),
            "removed_requirements": max(0, len(original_requirements) - len(updated_requirements)),
            "modified_requirements": min(len(original_requirements), len(updated_requirements)),
            "impact_assessment": "Medium impact - requires review of dependent components",
            "recommendations": [
                "Update traceability matrix",
                "Review impact on system architecture",
                "Update test cases and verification methods"
            ]
        }
    
    def _parse_list_field(self, field_str: str) -> List[str]:
        """Parse comma-separated string into list."""
        if not field_str:
            return []
        return [item.strip() for item in field_str.split(',') if item.strip()]
    
    def _extract_assumptions_from_cot(self, cot_result: Dict[str, Any]) -> List[str]:
        """Extract assumptions from CoT reasoning result."""
        # Simplified extraction - in production would parse reasoning steps
        return [
            "Users have basic technical knowledge",
            "System will be deployed in standard environment",
            "Network connectivity is reliable"
        ]
    
    def _extract_dependencies_from_cot(self, cot_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract dependencies from CoT reasoning result."""
        return [
            {
                "id": str(uuid.uuid4()),
                "type": "external_system",
                "description": "Authentication service dependency",
                "criticality": "high"
            }
        ]
    
    def _extract_glossary_from_cot(self, cot_result: Dict[str, Any]) -> Dict[str, str]:
        """Extract glossary terms from CoT reasoning result."""
        return {
            "User": "Any person who interacts with the system",
            "System": "The software application being developed",
            "Requirement": "A condition or capability needed by a user"
        }
    
    def _format_stakeholder_info(self, stakeholder_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Format stakeholder information for requirement model."""
        stakeholders = []
        for name, info in stakeholder_info.items():
            stakeholders.append({
                "name": name,
                "role": info.get("role", "Stakeholder"),
                "responsibilities": info.get("responsibilities", []),
                "contact": info.get("contact", "")
            })
        return stakeholders
    
    def _analyze_traceability_coverage(self, links: List[TraceabilityLink],
                                     requirements: List[SystemRequirement],
                                     user_requirements: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze traceability coverage."""
        total_user_reqs = len(user_requirements)
        total_system_reqs = len(requirements)
        covered_user_reqs = len(set(link.source_id for link in links))
        
        return {
            "total_user_requirements": total_user_reqs,
            "total_system_requirements": total_system_reqs,
            "covered_user_requirements": covered_user_reqs,
            "coverage_percentage": (covered_user_reqs / total_user_reqs * 100) if total_user_reqs > 0 else 0,
            "total_links": len(links)
        }
    
    def _find_orphaned_requirements(self, links: List[TraceabilityLink],
                                  requirements: List[SystemRequirement]) -> List[str]:
        """Find requirements without traceability links."""
        linked_req_ids = set(link.target_id for link in links)
        all_req_ids = set(req.id for req in requirements)
        return list(all_req_ids - linked_req_ids)
    
    def _create_system_requirements_artifact(self, requirements: List[SystemRequirement],
                                           context: Dict[str, Any]) -> Artifact:
        """Create artifact for system requirements."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.USER_REQUIREMENTS_LIST,  # Using existing type
            content={
                "requirements": [req.to_dict() for req in requirements],
                "context": context,
                "total_count": len(requirements),
                "categories": {
                    "functional": len([r for r in requirements if r.category == 'functional']),
                    "non_functional": len([r for r in requirements if r.category == 'non_functional']),
                    "constraints": len([r for r in requirements if r.category == 'constraint'])
                }
            },
            metadata=ArtifactMetadata(
                source_agent=self.name,
                tags=["system_requirements", "analysis", "transformation"]
            ),
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT
        )
    
    def _create_requirement_model_artifact(self, model: RequirementModel) -> Artifact:
        """Create artifact for requirement model."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REQUIREMENT_MODEL,
            content=model.to_dict(),
            metadata=ArtifactMetadata(
                source_agent=self.name,
                tags=["requirement_model", "analysis", "structure"]
            ),
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT
        )
    
    def _create_traceability_matrix_artifact(self, matrix: TraceabilityMatrix) -> Artifact:
        """Create artifact for traceability matrix."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REVIEW_REPORT,  # Using existing type for traceability
            content=matrix.to_dict(),
            metadata=ArtifactMetadata(
                source_agent=self.name,
                tags=["traceability", "matrix", "analysis"]
            ),
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT
        )