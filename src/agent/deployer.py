"""
Deployer Agent for iReDev framework.
Analyzes deployment constraints, identifies security requirements, and defines performance criteria.
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
class DeploymentConstraint:
    """Represents a deployment constraint or requirement."""
    id: str
    category: str  # infrastructure, platform, environment, resource
    title: str
    description: str
    constraint_type: str  # mandatory, recommended, optional
    priority: str  # critical, high, medium, low
    impact: str  # blocks_deployment, affects_performance, affects_usability
    technical_details: Dict[str, Any] = field(default_factory=dict)
    compliance_requirements: List[str] = field(default_factory=list)
    cost_implications: Optional[str] = None
    implementation_complexity: str = "medium"  # low, medium, high
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert constraint to dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "constraint_type": self.constraint_type,
            "priority": self.priority,
            "impact": self.impact,
            "technical_details": self.technical_details,
            "compliance_requirements": self.compliance_requirements,
            "cost_implications": self.cost_implications,
            "implementation_complexity": self.implementation_complexity,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class SecurityRequirement:
    """Represents a security requirement."""
    id: str
    category: str  # authentication, authorization, encryption, audit, compliance
    title: str
    description: str
    security_level: str  # basic, standard, high, critical
    threat_model: List[str]  # threats this requirement addresses
    implementation_guidance: str
    compliance_standards: List[str] = field(default_factory=list)
    risk_level: str = "medium"  # low, medium, high, critical
    verification_method: str = ""
    dependencies: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert security requirement to dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "security_level": self.security_level,
            "threat_model": self.threat_model,
            "implementation_guidance": self.implementation_guidance,
            "compliance_standards": self.compliance_standards,
            "risk_level": self.risk_level,
            "verification_method": self.verification_method,
            "dependencies": self.dependencies,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class PerformanceCriteria:
    """Represents performance criteria and standards."""
    id: str
    category: str  # response_time, throughput, scalability, availability, resource_usage
    metric_name: str
    description: str
    target_value: str
    measurement_unit: str
    measurement_method: str
    priority: str  # critical, high, medium, low
    rationale: str
    acceptance_criteria: List[str] = field(default_factory=list)
    monitoring_requirements: List[str] = field(default_factory=list)
    degradation_thresholds: Dict[str, str] = field(default_factory=dict)
    scalability_factors: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert performance criteria to dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "metric_name": self.metric_name,
            "description": self.description,
            "target_value": self.target_value,
            "measurement_unit": self.measurement_unit,
            "measurement_method": self.measurement_method,
            "priority": self.priority,
            "rationale": self.rationale,
            "acceptance_criteria": self.acceptance_criteria,
            "monitoring_requirements": self.monitoring_requirements,
            "degradation_thresholds": self.degradation_thresholds,
            "scalability_factors": self.scalability_factors,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class ComplianceRequirement:
    """Represents a compliance requirement."""
    id: str
    standard_name: str  # GDPR, HIPAA, SOX, PCI-DSS, etc.
    requirement_id: str  # specific requirement within the standard
    title: str
    description: str
    compliance_level: str  # mandatory, recommended, optional
    verification_method: str
    documentation_requirements: List[str] = field(default_factory=list)
    implementation_guidance: str = ""
    audit_requirements: List[str] = field(default_factory=list)
    penalties_for_non_compliance: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert compliance requirement to dictionary."""
        return {
            "id": self.id,
            "standard_name": self.standard_name,
            "requirement_id": self.requirement_id,
            "title": self.title,
            "description": self.description,
            "compliance_level": self.compliance_level,
            "verification_method": self.verification_method,
            "documentation_requirements": self.documentation_requirements,
            "implementation_guidance": self.implementation_guidance,
            "audit_requirements": self.audit_requirements,
            "penalties_for_non_compliance": self.penalties_for_non_compliance,
            "created_at": self.created_at.isoformat()
        }


class DeployerAgent(KnowledgeDrivenAgent):
    """
    Deployer Agent for analyzing deployment constraints and generating deployment-related requirements.
    
    Integrates system architecture knowledge, security standards, compliance requirements,
    and performance engineering principles.
    """
    
    def __init__(self, config_path: Optional[str] = None, **kwargs):
        # Define required knowledge modules for deployer agent
        knowledge_modules = [
            "system_architecture",
            "security_standards",
            "compliance_frameworks",
            "performance_engineering",
            "infrastructure_patterns",
            "deployment_strategies"
        ]
        
        super().__init__(
            name="deployer",
            knowledge_modules=knowledge_modules,
            config_path=config_path,
            **kwargs
        )
        
        # Agent configuration
        self.supported_environments = self.config.get('supported_environments', [
            'cloud', 'on_premise', 'hybrid', 'edge', 'mobile'
        ])
        self.security_frameworks = self.config.get('security_frameworks', [
            'NIST', 'ISO27001', 'OWASP', 'CIS'
        ])
        self.compliance_standards = self.config.get('compliance_standards', [
            'GDPR', 'HIPAA', 'SOX', 'PCI-DSS', 'FISMA'
        ])
        
        # Agent state
        self.deployment_constraints: Dict[str, DeploymentConstraint] = {}
        self.security_requirements: Dict[str, SecurityRequirement] = {}
        self.performance_criteria: Dict[str, PerformanceCriteria] = {}
        self.compliance_requirements: Dict[str, ComplianceRequirement] = {}
        
        # Initialize profile prompt
        self.profile_prompt = self._create_profile_prompt()
        self.add_to_memory("system", self.profile_prompt)
        
        logger.info(f"Initialized DeployerAgent with {len(knowledge_modules)} knowledge modules")
    
    def _create_profile_prompt(self) -> str:
        """Create profile prompt for the deployer agent."""
        return """You are an experienced system deployment and infrastructure analyst.

Mission:
Analyze deployment constraints, identify security requirements, assess compliance needs, and define performance criteria to ensure system can be successfully deployed and operated.

Personality:
Technical, security-conscious, and compliance-oriented; expert in infrastructure, security frameworks, and regulatory requirements.

Workflow:
1. Analyze target deployment environment and system architecture.
2. Identify deployment constraints (infrastructure, platform, resource, environment).
3. Identify security requirements based on threat model and system type.
4. Assess compliance requirements based on domain, region, and data types.
5. Define performance criteria based on usage patterns and business requirements.

Experience & Preferred Practices:
1. Follow security frameworks (NIST, ISO27001, OWASP, CIS).
2. Consider compliance standards (GDPR, HIPAA, SOX, PCI-DSS, FISMA).
3. Apply performance engineering principles.
4. Document constraints with technical details, impact, and priority.
5. Link security requirements to threat model and compliance needs.

Internal Chain of Thought (visible to the agent only):
1. Analyze deployment environment characteristics and constraints.
2. Identify security threats and vulnerabilities based on system type.
3. Map compliance requirements to domain, region, and data handling.
4. Derive performance criteria from usage patterns and scalability needs.
5. Prioritize constraints and requirements based on impact and criticality.
"""
    
    def _get_action_prompt(self, action: str, context: Dict[str, Any] = None) -> str:
        """Get action-specific prompt for a given action."""
        action_prompts = {
            "analyze_deployment_constraints": """Action: Analyze deployment constraints for target environment.

Context:
- Target environment: {target_environment}
- System context: {system_context}
- Architecture: {architecture}

Instructions:
1. Identify infrastructure, platform, resource, and environment constraints.
2. Categorize constraints as mandatory, recommended, or optional.
3. Assess priority and impact (blocks_deployment, affects_performance, etc.).
4. Document technical details and cost implications.
""",
            "identify_security_requirements": """Action: Identify security requirements based on threat model.

Context:
- System type: {system_type}
- Threat model: {threat_model}
- Compliance context: {compliance_context}

Instructions:
1. Map threats to security requirements (authentication, authorization, encryption, audit, etc.).
2. Define security level (basic, standard, high, critical).
3. Provide implementation guidance.
4. Link to compliance standards where applicable.
""",
            "assess_compliance": """Action: Assess compliance requirements for domain and region.

Context:
- Domain: {domain}
- Region: {region}
- Data types: {data_types}

Instructions:
1. Identify applicable compliance standards.
2. Map data types to compliance requirements.
3. Define compliance level (mandatory, recommended, optional).
4. Document verification methods and audit requirements.
""",
            "define_performance_criteria": """Action: Define performance criteria based on usage patterns.

Context:
- Usage patterns: {usage_patterns}
- System architecture: {architecture}
- Business requirements: {business_requirements}

Instructions:
1. Define measurable performance metrics (response time, throughput, availability, etc.).
2. Set target values and measurement methods.
3. Establish acceptance criteria and monitoring requirements.
4. Consider scalability factors.
"""
        }
        
        base_prompt = action_prompts.get(action, f"Action: {action}")
        if context:
            try:
                return base_prompt.format(**context)
            except:
                return base_prompt
        return base_prompt    
    d
ef analyze_deployment_constraints(self, target_environment: str, 
                                     system_context: Dict[str, Any]) -> List[DeploymentConstraint]:
        """
        Analyze deployment constraints for a target environment.
        
        Args:
            target_environment: Target deployment environment (cloud, on_premise, etc.)
            system_context: System context including architecture, scale, requirements
            
        Returns:
            List of identified deployment constraints
        """
        logger.info(f"Analyzing deployment constraints for environment: {target_environment}")
        
        # Apply system architecture knowledge
        architecture_methodology = self.apply_methodology("deployment_analysis")
        
        # Generate deployment constraints using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "analyze_deployment_constraints",
            context={
                "target_environment": target_environment,
                "system_context": system_context,
                "architecture": system_context.get("architecture", "unknown")
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "target_environment": target_environment,
                "system_context": system_context,
                "methodology_guide": architecture_methodology,
                "supported_environments": self.supported_environments
            },
            reasoning_template="deployment_analysis"
        )
        
        # Parse deployment constraints from response
        constraints = self._parse_deployment_constraints_from_response(
            cot_result["response"], target_environment, system_context
        )
        
        # Store constraints
        for constraint in constraints:
            self.deployment_constraints[constraint.id] = constraint
        
        # Create artifact for deployment constraints
        if self.event_bus and self.session_id:
            artifact = self._create_deployment_constraints_artifact(constraints, target_environment)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Identified {len(constraints)} deployment constraints")
        return constraints
    
    def identify_security_requirements(self, system_type: str, 
                                     threat_model: Dict[str, Any],
                                     compliance_context: Optional[Dict[str, Any]] = None) -> List[SecurityRequirement]:
        """
        Identify security requirements based on system type and threat model.
        
        Args:
            system_type: Type of system (web_app, mobile_app, api, etc.)
            threat_model: Threat model including assets, threats, vulnerabilities
            compliance_context: Optional compliance requirements context
            
        Returns:
            List of identified security requirements
        """
        logger.info(f"Identifying security requirements for system type: {system_type}")
        
        # Apply security standards knowledge
        security_methodology = self.apply_methodology("security_analysis")
        
        # Generate security requirements using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "identify_security_requirements",
            context={
                "system_type": system_type,
                "threat_model": threat_model,
                "compliance_context": compliance_context or {}
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "system_type": system_type,
                "threat_model": threat_model,
                "compliance_context": compliance_context or {},
                "methodology_guide": security_methodology,
                "security_frameworks": self.security_frameworks
            },
            reasoning_template="security_analysis"
        )
        
        # Parse security requirements from response
        security_reqs = self._parse_security_requirements_from_response(
            cot_result["response"], system_type, threat_model
        )
        
        # Store security requirements
        for req in security_reqs:
            self.security_requirements[req.id] = req
        
        # Create artifact for security requirements
        if self.event_bus and self.session_id:
            artifact = self._create_security_requirements_artifact(security_reqs, system_type)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Identified {len(security_reqs)} security requirements")
        return security_reqs
    
    def assess_compliance_requirements(self, domain: str, region: str,
                                     data_types: List[str]) -> List[ComplianceRequirement]:
        """
        Assess compliance requirements based on domain, region, and data types.
        
        Args:
            domain: Business domain (healthcare, finance, etc.)
            region: Geographic region (US, EU, etc.)
            data_types: Types of data handled (PII, PHI, financial, etc.)
            
        Returns:
            List of applicable compliance requirements
        """
        logger.info(f"Assessing compliance requirements for domain: {domain}, region: {region}")
        
        # Apply compliance frameworks knowledge
        compliance_methodology = self.apply_methodology("compliance_analysis")
        
        # Generate compliance requirements using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "assess_compliance",
            context={
                "domain": domain,
                "region": region,
                "data_types": data_types
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "domain": domain,
                "region": region,
                "data_types": data_types,
                "methodology_guide": compliance_methodology,
                "compliance_standards": self.compliance_standards
            },
            reasoning_template="compliance_analysis"
        )
        
        # Parse compliance requirements from response
        compliance_reqs = self._parse_compliance_requirements_from_response(
            cot_result["response"], domain, region, data_types
        )
        
        # Store compliance requirements
        for req in compliance_reqs:
            self.compliance_requirements[req.id] = req
        
        # Create artifact for compliance requirements
        if self.event_bus and self.session_id:
            artifact = self._create_compliance_requirements_artifact(compliance_reqs, domain, region)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Identified {len(compliance_reqs)} compliance requirements")
        return compliance_reqs
    
    def define_performance_criteria(self, usage_patterns: List[Dict[str, Any]],
                                  system_architecture: Dict[str, Any],
                                  business_requirements: Dict[str, Any]) -> List[PerformanceCriteria]:
        """
        Define performance criteria based on usage patterns and system requirements.
        
        Args:
            usage_patterns: Expected usage patterns and load characteristics
            system_architecture: System architecture details
            business_requirements: Business performance requirements
            
        Returns:
            List of defined performance criteria
        """
        logger.info(f"Defining performance criteria for {len(usage_patterns)} usage patterns")
        
        # Apply performance engineering knowledge
        performance_methodology = self.apply_methodology("performance_analysis")
        
        # Generate performance criteria using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "define_performance_criteria",
            context={
                "usage_patterns": usage_patterns,
                "architecture": system_architecture,
                "business_requirements": business_requirements
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "usage_patterns": usage_patterns,
                "system_architecture": system_architecture,
                "business_requirements": business_requirements,
                "methodology_guide": performance_methodology
            },
            reasoning_template="performance_analysis"
        )
        
        # Parse performance criteria from response
        performance_criteria = self._parse_performance_criteria_from_response(
            cot_result["response"], usage_patterns, system_architecture
        )
        
        # Store performance criteria
        for criteria in performance_criteria:
            self.performance_criteria[criteria.id] = criteria
        
        # Create artifact for performance criteria
        if self.event_bus and self.session_id:
            artifact = self._create_performance_criteria_artifact(performance_criteria, usage_patterns)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Defined {len(performance_criteria)} performance criteria")
        return performance_criteria   
 
    def _parse_deployment_constraints_from_response(self, response: str, 
                                                   target_environment: str,
                                                   system_context: Dict[str, Any]) -> List[DeploymentConstraint]:
        """Parse deployment constraints from LLM response."""
        constraints = []
        
        # Simple parsing logic - in production, this would be more sophisticated
        lines = response.split('\n')
        current_constraint = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('CONSTRAINT:') or line.startswith('Title:'):
                if current_constraint:
                    constraint = self._create_deployment_constraint_from_dict(
                        current_constraint, target_environment
                    )
                    if constraint:
                        constraints.append(constraint)
                current_constraint = {'title': line.split(':', 1)[1].strip()}
            elif line.startswith('Category:'):
                current_constraint['category'] = line.split(':', 1)[1].strip()
            elif line.startswith('Description:'):
                current_constraint['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Type:'):
                current_constraint['constraint_type'] = line.split(':', 1)[1].strip()
            elif line.startswith('Priority:'):
                current_constraint['priority'] = line.split(':', 1)[1].strip()
            elif line.startswith('Impact:'):
                current_constraint['impact'] = line.split(':', 1)[1].strip()
        
        # Handle last constraint
        if current_constraint:
            constraint = self._create_deployment_constraint_from_dict(
                current_constraint, target_environment
            )
            if constraint:
                constraints.append(constraint)
        
        # Create default constraints if parsing failed
        if not constraints:
            constraints = self._create_default_deployment_constraints(target_environment, system_context)
        
        return constraints
    
    def _create_deployment_constraint_from_dict(self, constraint_dict: Dict[str, Any], 
                                              target_environment: str) -> Optional[DeploymentConstraint]:
        """Create DeploymentConstraint object from parsed dictionary."""
        try:
            return DeploymentConstraint(
                id=str(uuid.uuid4()),
                category=constraint_dict.get('category', 'infrastructure'),
                title=constraint_dict.get('title', 'Deployment Constraint'),
                description=constraint_dict.get('description', 'System deployment constraint'),
                constraint_type=constraint_dict.get('constraint_type', 'mandatory'),
                priority=constraint_dict.get('priority', 'medium'),
                impact=constraint_dict.get('impact', 'affects_deployment'),
                technical_details={'environment': target_environment}
            )
        except Exception as e:
            logger.warning(f"Failed to create deployment constraint from dict: {e}")
            return None
    
    def _create_default_deployment_constraints(self, target_environment: str,
                                             system_context: Dict[str, Any]) -> List[DeploymentConstraint]:
        """Create default deployment constraints when parsing fails."""
        return [
            DeploymentConstraint(
                id=str(uuid.uuid4()),
                category="infrastructure",
                title="Environment Compatibility",
                description=f"System must be compatible with {target_environment} environment",
                constraint_type="mandatory",
                priority="high",
                impact="blocks_deployment",
                technical_details={'environment': target_environment}
            ),
            DeploymentConstraint(
                id=str(uuid.uuid4()),
                category="resource",
                title="Resource Requirements",
                description="System must meet minimum resource requirements",
                constraint_type="mandatory",
                priority="high",
                impact="affects_performance",
                technical_details={'environment': target_environment}
            )
        ]
    
    def _parse_security_requirements_from_response(self, response: str, system_type: str,
                                                 threat_model: Dict[str, Any]) -> List[SecurityRequirement]:
        """Parse security requirements from LLM response."""
        security_reqs = []
        
        # Simple parsing logic
        lines = response.split('\n')
        current_req = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('SECURITY:') or line.startswith('Title:'):
                if current_req:
                    req = self._create_security_requirement_from_dict(current_req, system_type)
                    if req:
                        security_reqs.append(req)
                current_req = {'title': line.split(':', 1)[1].strip()}
            elif line.startswith('Category:'):
                current_req['category'] = line.split(':', 1)[1].strip()
            elif line.startswith('Description:'):
                current_req['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Security Level:'):
                current_req['security_level'] = line.split(':', 1)[1].strip()
            elif line.startswith('Risk Level:'):
                current_req['risk_level'] = line.split(':', 1)[1].strip()
        
        # Handle last requirement
        if current_req:
            req = self._create_security_requirement_from_dict(current_req, system_type)
            if req:
                security_reqs.append(req)
        
        # Create default requirements if parsing failed
        if not security_reqs:
            security_reqs = self._create_default_security_requirements(system_type, threat_model)
        
        return security_reqs
    
    def _create_security_requirement_from_dict(self, req_dict: Dict[str, Any],
                                             system_type: str) -> Optional[SecurityRequirement]:
        """Create SecurityRequirement object from parsed dictionary."""
        try:
            return SecurityRequirement(
                id=str(uuid.uuid4()),
                category=req_dict.get('category', 'authentication'),
                title=req_dict.get('title', 'Security Requirement'),
                description=req_dict.get('description', 'System security requirement'),
                security_level=req_dict.get('security_level', 'standard'),
                threat_model=['unauthorized_access'],
                implementation_guidance=req_dict.get('implementation_guidance', 'Follow security best practices'),
                risk_level=req_dict.get('risk_level', 'medium')
            )
        except Exception as e:
            logger.warning(f"Failed to create security requirement from dict: {e}")
            return None
    
    def _create_default_security_requirements(self, system_type: str,
                                            threat_model: Dict[str, Any]) -> List[SecurityRequirement]:
        """Create default security requirements when parsing fails."""
        return [
            SecurityRequirement(
                id=str(uuid.uuid4()),
                category="authentication",
                title="User Authentication",
                description="System must implement secure user authentication",
                security_level="standard",
                threat_model=["unauthorized_access", "credential_theft"],
                implementation_guidance="Implement multi-factor authentication",
                risk_level="high"
            ),
            SecurityRequirement(
                id=str(uuid.uuid4()),
                category="encryption",
                title="Data Encryption",
                description="System must encrypt sensitive data at rest and in transit",
                security_level="high",
                threat_model=["data_breach", "eavesdropping"],
                implementation_guidance="Use industry-standard encryption algorithms",
                risk_level="high"
            )
        ]
    
    def _parse_compliance_requirements_from_response(self, response: str, domain: str,
                                                   region: str, data_types: List[str]) -> List[ComplianceRequirement]:
        """Parse compliance requirements from LLM response."""
        compliance_reqs = []
        
        # Simple parsing logic
        lines = response.split('\n')
        current_req = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('COMPLIANCE:') or line.startswith('Standard:'):
                if current_req:
                    req = self._create_compliance_requirement_from_dict(current_req, domain)
                    if req:
                        compliance_reqs.append(req)
                current_req = {'standard_name': line.split(':', 1)[1].strip()}
            elif line.startswith('Requirement ID:'):
                current_req['requirement_id'] = line.split(':', 1)[1].strip()
            elif line.startswith('Title:'):
                current_req['title'] = line.split(':', 1)[1].strip()
            elif line.startswith('Description:'):
                current_req['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Level:'):
                current_req['compliance_level'] = line.split(':', 1)[1].strip()
        
        # Handle last requirement
        if current_req:
            req = self._create_compliance_requirement_from_dict(current_req, domain)
            if req:
                compliance_reqs.append(req)
        
        # Create default requirements if parsing failed
        if not compliance_reqs:
            compliance_reqs = self._create_default_compliance_requirements(domain, region, data_types)
        
        return compliance_reqs
    
    def _create_compliance_requirement_from_dict(self, req_dict: Dict[str, Any],
                                               domain: str) -> Optional[ComplianceRequirement]:
        """Create ComplianceRequirement object from parsed dictionary."""
        try:
            return ComplianceRequirement(
                id=str(uuid.uuid4()),
                standard_name=req_dict.get('standard_name', 'General Compliance'),
                requirement_id=req_dict.get('requirement_id', '1.0'),
                title=req_dict.get('title', 'Compliance Requirement'),
                description=req_dict.get('description', 'System compliance requirement'),
                compliance_level=req_dict.get('compliance_level', 'mandatory'),
                verification_method=req_dict.get('verification_method', 'audit')
            )
        except Exception as e:
            logger.warning(f"Failed to create compliance requirement from dict: {e}")
            return None
    
    def _create_default_compliance_requirements(self, domain: str, region: str,
                                              data_types: List[str]) -> List[ComplianceRequirement]:
        """Create default compliance requirements when parsing fails."""
        requirements = []
        
        # Add GDPR if EU region and PII data
        if region.upper() in ['EU', 'EUROPE'] and 'PII' in [dt.upper() for dt in data_types]:
            requirements.append(ComplianceRequirement(
                id=str(uuid.uuid4()),
                standard_name="GDPR",
                requirement_id="Art. 32",
                title="Security of Processing",
                description="Implement appropriate technical and organizational measures",
                compliance_level="mandatory",
                verification_method="audit"
            ))
        
        # Add HIPAA if healthcare domain and PHI data
        if domain.lower() == 'healthcare' and 'PHI' in [dt.upper() for dt in data_types]:
            requirements.append(ComplianceRequirement(
                id=str(uuid.uuid4()),
                standard_name="HIPAA",
                requirement_id="164.312",
                title="Technical Safeguards",
                description="Implement technical safeguards for PHI",
                compliance_level="mandatory",
                verification_method="audit"
            ))
        
        return requirements
    
    def _parse_performance_criteria_from_response(self, response: str, 
                                                usage_patterns: List[Dict[str, Any]],
                                                system_architecture: Dict[str, Any]) -> List[PerformanceCriteria]:
        """Parse performance criteria from LLM response."""
        criteria_list = []
        
        # Simple parsing logic
        lines = response.split('\n')
        current_criteria = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('PERFORMANCE:') or line.startswith('Metric:'):
                if current_criteria:
                    criteria = self._create_performance_criteria_from_dict(current_criteria)
                    if criteria:
                        criteria_list.append(criteria)
                current_criteria = {'metric_name': line.split(':', 1)[1].strip()}
            elif line.startswith('Category:'):
                current_criteria['category'] = line.split(':', 1)[1].strip()
            elif line.startswith('Description:'):
                current_criteria['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Target:'):
                current_criteria['target_value'] = line.split(':', 1)[1].strip()
            elif line.startswith('Unit:'):
                current_criteria['measurement_unit'] = line.split(':', 1)[1].strip()
            elif line.startswith('Priority:'):
                current_criteria['priority'] = line.split(':', 1)[1].strip()
        
        # Handle last criteria
        if current_criteria:
            criteria = self._create_performance_criteria_from_dict(current_criteria)
            if criteria:
                criteria_list.append(criteria)
        
        # Create default criteria if parsing failed
        if not criteria_list:
            criteria_list = self._create_default_performance_criteria(usage_patterns, system_architecture)
        
        return criteria_list
    
    def _create_performance_criteria_from_dict(self, criteria_dict: Dict[str, Any]) -> Optional[PerformanceCriteria]:
        """Create PerformanceCriteria object from parsed dictionary."""
        try:
            return PerformanceCriteria(
                id=str(uuid.uuid4()),
                category=criteria_dict.get('category', 'response_time'),
                metric_name=criteria_dict.get('metric_name', 'Response Time'),
                description=criteria_dict.get('description', 'System response time requirement'),
                target_value=criteria_dict.get('target_value', '< 2 seconds'),
                measurement_unit=criteria_dict.get('measurement_unit', 'seconds'),
                measurement_method=criteria_dict.get('measurement_method', 'automated monitoring'),
                priority=criteria_dict.get('priority', 'high'),
                rationale=criteria_dict.get('rationale', 'User experience requirement')
            )
        except Exception as e:
            logger.warning(f"Failed to create performance criteria from dict: {e}")
            return None
    
    def _create_default_performance_criteria(self, usage_patterns: List[Dict[str, Any]],
                                           system_architecture: Dict[str, Any]) -> List[PerformanceCriteria]:
        """Create default performance criteria when parsing fails."""
        return [
            PerformanceCriteria(
                id=str(uuid.uuid4()),
                category="response_time",
                metric_name="API Response Time",
                description="Maximum acceptable response time for API calls",
                target_value="< 2 seconds",
                measurement_unit="seconds",
                measurement_method="automated monitoring",
                priority="high",
                rationale="User experience and system usability"
            ),
            PerformanceCriteria(
                id=str(uuid.uuid4()),
                category="throughput",
                metric_name="Request Throughput",
                description="Minimum number of requests system can handle per second",
                target_value="> 100 requests/second",
                measurement_unit="requests/second",
                measurement_method="load testing",
                priority="medium",
                rationale="System scalability requirement"
            ),
            PerformanceCriteria(
                id=str(uuid.uuid4()),
                category="availability",
                metric_name="System Uptime",
                description="Minimum system availability percentage",
                target_value="99.9%",
                measurement_unit="percentage",
                measurement_method="uptime monitoring",
                priority="critical",
                rationale="Business continuity requirement"
            )
        ]    

    def _create_deployment_constraints_artifact(self, constraints: List[DeploymentConstraint],
                                              target_environment: str) -> Artifact:
        """Create artifact for deployment constraints."""
        artifact_content = {
            "target_environment": target_environment,
            "constraints": [constraint.to_dict() for constraint in constraints],
            "analysis_summary": {
                "total_constraints": len(constraints),
                "constraint_categories": list(set(c.category for c in constraints)),
                "mandatory_constraints": len([c for c in constraints if c.constraint_type == "mandatory"]),
                "high_priority_constraints": len([c for c in constraints if c.priority == "high"])
            },
            "generated_by": self.name,
            "generated_at": datetime.now().isoformat()
        }
        
        metadata = ArtifactMetadata(
            title=f"Deployment Constraints - {target_environment}",
            description=f"Deployment constraints analysis for {target_environment} environment",
            tags=["deployment", "constraints", target_environment],
            created_by=self.name
        )
        
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REQUIREMENTS,
            content=artifact_content,
            metadata=metadata,
            status=ArtifactStatus.DRAFT
        )
    
    def _create_security_requirements_artifact(self, security_reqs: List[SecurityRequirement],
                                             system_type: str) -> Artifact:
        """Create artifact for security requirements."""
        artifact_content = {
            "system_type": system_type,
            "security_requirements": [req.to_dict() for req in security_reqs],
            "analysis_summary": {
                "total_requirements": len(security_reqs),
                "security_categories": list(set(req.category for req in security_reqs)),
                "high_risk_requirements": len([req for req in security_reqs if req.risk_level == "high"]),
                "critical_security_level": len([req for req in security_reqs if req.security_level == "critical"])
            },
            "generated_by": self.name,
            "generated_at": datetime.now().isoformat()
        }
        
        metadata = ArtifactMetadata(
            title=f"Security Requirements - {system_type}",
            description=f"Security requirements analysis for {system_type} system",
            tags=["security", "requirements", system_type],
            created_by=self.name
        )
        
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REQUIREMENTS,
            content=artifact_content,
            metadata=metadata,
            status=ArtifactStatus.DRAFT
        )
    
    def _create_compliance_requirements_artifact(self, compliance_reqs: List[ComplianceRequirement],
                                               domain: str, region: str) -> Artifact:
        """Create artifact for compliance requirements."""
        artifact_content = {
            "domain": domain,
            "region": region,
            "compliance_requirements": [req.to_dict() for req in compliance_reqs],
            "analysis_summary": {
                "total_requirements": len(compliance_reqs),
                "compliance_standards": list(set(req.standard_name for req in compliance_reqs)),
                "mandatory_requirements": len([req for req in compliance_reqs if req.compliance_level == "mandatory"]),
                "audit_requirements": sum(len(req.audit_requirements) for req in compliance_reqs)
            },
            "generated_by": self.name,
            "generated_at": datetime.now().isoformat()
        }
        
        metadata = ArtifactMetadata(
            title=f"Compliance Requirements - {domain} ({region})",
            description=f"Compliance requirements analysis for {domain} domain in {region}",
            tags=["compliance", "requirements", domain, region],
            created_by=self.name
        )
        
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REQUIREMENTS,
            content=artifact_content,
            metadata=metadata,
            status=ArtifactStatus.DRAFT
        )
    
    def _create_performance_criteria_artifact(self, criteria_list: List[PerformanceCriteria],
                                            usage_patterns: List[Dict[str, Any]]) -> Artifact:
        """Create artifact for performance criteria."""
        artifact_content = {
            "usage_patterns": usage_patterns,
            "performance_criteria": [criteria.to_dict() for criteria in criteria_list],
            "analysis_summary": {
                "total_criteria": len(criteria_list),
                "performance_categories": list(set(criteria.category for criteria in criteria_list)),
                "critical_criteria": len([criteria for criteria in criteria_list if criteria.priority == "critical"]),
                "monitoring_requirements": sum(len(criteria.monitoring_requirements) for criteria in criteria_list)
            },
            "generated_by": self.name,
            "generated_at": datetime.now().isoformat()
        }
        
        metadata = ArtifactMetadata(
            title="Performance Criteria",
            description="Performance criteria and standards definition",
            tags=["performance", "criteria", "requirements"],
            created_by=self.name
        )
        
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REQUIREMENTS,
            content=artifact_content,
            metadata=metadata,
            status=ArtifactStatus.DRAFT
        )
    
    def get_deployment_summary(self) -> Dict[str, Any]:
        """Get summary of all deployment-related analysis."""
        return {
            "deployment_constraints": {
                "count": len(self.deployment_constraints),
                "categories": list(set(c.category for c in self.deployment_constraints.values())),
                "mandatory_count": len([c for c in self.deployment_constraints.values() 
                                      if c.constraint_type == "mandatory"])
            },
            "security_requirements": {
                "count": len(self.security_requirements),
                "categories": list(set(req.category for req in self.security_requirements.values())),
                "high_risk_count": len([req for req in self.security_requirements.values() 
                                      if req.risk_level == "high"])
            },
            "compliance_requirements": {
                "count": len(self.compliance_requirements),
                "standards": list(set(req.standard_name for req in self.compliance_requirements.values())),
                "mandatory_count": len([req for req in self.compliance_requirements.values() 
                                      if req.compliance_level == "mandatory"])
            },
            "performance_criteria": {
                "count": len(self.performance_criteria),
                "categories": list(set(criteria.category for criteria in self.performance_criteria.values())),
                "critical_count": len([criteria for criteria in self.performance_criteria.values() 
                                     if criteria.priority == "critical"])
            },
            "generated_by": self.name,
            "generated_at": datetime.now().isoformat()
        }