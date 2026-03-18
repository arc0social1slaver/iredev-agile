"""
Reviewer Agent for iReDev framework.
Validates consistency, completeness, and traceability of SRS documents.
Provides quality assurance and improvement recommendations.
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
class ConsistencyViolation:
    """Represents a consistency violation in the document."""
    id: str
    violation_type: str  # terminology, numbering, format, logic
    description: str
    severity: str  # critical, high, medium, low
    location: str  # section or requirement ID
    conflicting_elements: List[str] = field(default_factory=list)
    recommendation: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert consistency violation to dictionary."""
        return {
            "id": self.id,
            "violation_type": self.violation_type,
            "description": self.description,
            "severity": self.severity,
            "location": self.location,
            "conflicting_elements": self.conflicting_elements,
            "recommendation": self.recommendation,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class CompletenessGap:
    """Represents a completeness gap in the document."""
    id: str
    gap_type: str  # missing_section, missing_requirement, incomplete_specification
    description: str
    severity: str  # critical, high, medium, low
    expected_content: str
    current_content: str = ""
    recommendation: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert completeness gap to dictionary."""
        return {
            "id": self.id,
            "gap_type": self.gap_type,
            "description": self.description,
            "severity": self.severity,
            "expected_content": self.expected_content,
            "current_content": self.current_content,
            "recommendation": self.recommendation,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class TraceabilityIssue:
    """Represents a traceability issue in the document."""
    id: str
    issue_type: str  # missing_link, broken_link, circular_dependency, orphaned_requirement
    description: str
    severity: str  # critical, high, medium, low
    source_id: str
    target_id: str = ""
    recommendation: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert traceability issue to dictionary."""
        return {
            "id": self.id,
            "issue_type": self.issue_type,
            "description": self.description,
            "severity": self.severity,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "recommendation": self.recommendation,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class QualityDefect:
    """Represents a quality defect identified in the document."""
    id: str
    defect_type: str  # ambiguity, inconsistency, incompleteness, unverifiability
    description: str
    severity: str  # critical, high, medium, low
    location: str
    impact: str  # description of potential impact
    root_cause: str = ""
    recommendation: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert quality defect to dictionary."""
        return {
            "id": self.id,
            "defect_type": self.defect_type,
            "description": self.description,
            "severity": self.severity,
            "location": self.location,
            "impact": self.impact,
            "root_cause": self.root_cause,
            "recommendation": self.recommendation,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class ConsistencyReport:
    """Represents a consistency validation report."""
    id: str
    document_id: str
    consistency_score: float  # 0.0 to 1.0
    violations: List[ConsistencyViolation] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert consistency report to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "consistency_score": self.consistency_score,
            "violations": [v.to_dict() for v in self.violations],
            "summary": self.summary,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class CompletenessReport:
    """Represents a completeness validation report."""
    id: str
    document_id: str
    completeness_score: float  # 0.0 to 1.0
    gaps: List[CompletenessGap] = field(default_factory=list)
    coverage_analysis: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert completeness report to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "completeness_score": self.completeness_score,
            "gaps": [g.to_dict() for g in self.gaps],
            "coverage_analysis": self.coverage_analysis,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class TraceabilityReport:
    """Represents a traceability validation report."""
    id: str
    document_id: str
    traceability_score: float  # 0.0 to 1.0
    issues: List[TraceabilityIssue] = field(default_factory=list)
    coverage_matrix: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert traceability report to dictionary."""
        return {
            "id": self.id,
            "document_id": self.document_id,
            "traceability_score": self.traceability_score,
            "issues": [i.to_dict() for i in self.issues],
            "coverage_matrix": self.coverage_matrix,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class QualityMetrics:
    """Represents overall quality metrics for a document."""
    document_id: str
    overall_score: float  # 0.0 to 1.0
    consistency_score: float
    completeness_score: float
    traceability_score: float
    clarity_score: float
    verifiability_score: float
    defect_density: float  # defects per page/section
    improvement_potential: float  # 0.0 to 1.0
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert quality metrics to dictionary."""
        return {
            "document_id": self.document_id,
            "overall_score": self.overall_score,
            "consistency_score": self.consistency_score,
            "completeness_score": self.completeness_score,
            "traceability_score": self.traceability_score,
            "clarity_score": self.clarity_score,
            "verifiability_score": self.verifiability_score,
            "defect_density": self.defect_density,
            "improvement_potential": self.improvement_potential,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class ImprovementRecommendation:
    """Represents an improvement recommendation."""
    id: str
    category: str  # structure, content, quality, process
    priority: str  # critical, high, medium, low
    title: str
    description: str
    rationale: str
    implementation_effort: str  # low, medium, high
    expected_benefit: str
    action_items: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert improvement recommendation to dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "priority": self.priority,
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "implementation_effort": self.implementation_effort,
            "expected_benefit": self.expected_benefit,
            "action_items": self.action_items,
            "created_at": self.created_at.isoformat()
        }


class ReviewerAgent(KnowledgeDrivenAgent):
    """
    Reviewer Agent for validating SRS documents and ensuring quality.
    
    Integrates quality assurance methodologies, verification techniques,
    and defect identification to provide comprehensive document reviews.
    """
    
    def __init__(self, config_path: Optional[str] = None, **kwargs):
        # Define required knowledge modules for reviewer agent
        knowledge_modules = [
            "quality_assurance",
            "verification_validation",
            "document_review",
            "defect_identification",
            "ieee_830",
            "iso_29148",
            "requirements_quality"
        ]
        
        super().__init__(
            name="reviewer",
            knowledge_modules=knowledge_modules,
            config_path=config_path,
            **kwargs
        )
        
        # Agent configuration
        self.quality_thresholds = self.config.get('quality_thresholds', {
            'consistency': 0.90,
            'completeness': 0.85,
            'traceability': 0.80,
            'overall': 0.85
        })
        
        self.severity_weights = self.config.get('severity_weights', {
            'critical': 1.0,
            'high': 0.7,
            'medium': 0.4,
            'low': 0.1
        })
        
        self.supported_standards = self.config.get('supported_standards', [
            'IEEE 830', 'ISO/IEC/IEEE 29148'
        ])
        
        # Agent state
        self.consistency_reports: Dict[str, ConsistencyReport] = {}
        self.completeness_reports: Dict[str, CompletenessReport] = {}
        self.traceability_reports: Dict[str, TraceabilityReport] = {}
        self.quality_metrics: Dict[str, QualityMetrics] = {}
        self.improvement_recommendations: Dict[str, List[ImprovementRecommendation]] = {}
        
        # Initialize profile prompt
        self.profile_prompt = self._create_profile_prompt()
        self.add_to_memory("system", self.profile_prompt)
        
        logger.info(f"Initialized ReviewerAgent with {len(knowledge_modules)} knowledge modules")
    
    def _create_profile_prompt(self) -> str:
        """Create profile prompt for the reviewer agent."""
        return """You are an experienced requirements quality assurance specialist and document reviewer.

Mission:
Systematically validate SRS documents against quality standards, identify defects, inconsistencies, and gaps, and provide actionable improvement recommendations.

Personality:
Meticulous, objective, and standards-driven; expert in quality criteria and systematic review processes.

Workflow:
1. Validate document consistency (terminology, numbering, format, logic).
2. Check document completeness against requirements and standard structure.
3. Verify requirement traceability and identify missing or broken links.
4. Assess overall quality metrics and generate quality report.
5. Provide specific, actionable improvement recommendations.
6. Generate comprehensive review report.

Experience & Preferred Practices:
1. Follow ISO/IEC/IEEE 29148 and IEEE 830 quality criteria.
2. Check for completeness, consistency, clarity, verifiability, and ambiguity.
3. Identify conflicts, omissions, and contradictions systematically.
4. Assess traceability coverage and link quality.
5. Provide severity-based issue classification (critical, high, medium, low).
6. Ensure recommendations are specific, actionable, and prioritized.

Internal Chain of Thought (visible to the agent only):
1. Analyze document structure and content systematically.
2. Check consistency across terminology, numbering, format, and logical relationships.
3. Compare document against source requirements and standard structure for completeness.
4. Verify traceability links and identify gaps or broken references.
5. Calculate quality metrics based on identified issues.
6. Prioritize issues by severity and impact.
7. Generate specific, actionable recommendations for each issue.
"""
    
    def _get_action_prompt(self, action: str, context: Dict[str, Any] = None) -> str:
        """Get action-specific prompt for a given action."""
        action_prompts = {
            "validate_consistency": """Action: Validate document consistency.

Context:
- Document: {document_id}
- Standard: {standard}

Instructions:
1. Check terminology consistency throughout document.
2. Verify numbering and cross-reference consistency.
3. Validate format consistency.
4. Check logical consistency and identify contradictions.
5. Generate consistency report with issues and recommendations.
""",
            "check_completeness": """Action: Check document completeness.

Context:
- Document: {document_id}
- Requirements: {requirements_count}
- Standard: {standard}

Instructions:
1. Compare document against source requirements.
2. Check standard structure completeness.
3. Identify missing sections, requirements, or information.
4. Assess coverage and gaps.
5. Generate completeness report with findings.
""",
            "verify_traceability": """Action: Verify requirement traceability.

Context:
- Document: {document_id}
- Traceability matrix: {traceability_matrix}

Instructions:
1. Verify all traceability links are present and correct.
2. Identify missing or broken links.
3. Check forward and backward traceability coverage.
4. Assess link quality and completeness.
5. Generate traceability report with gaps and recommendations.
""",
            "assess_quality": """Action: Assess overall document quality.

Context:
- Document: {document_id}
- Consistency report: {consistency_report}
- Completeness report: {completeness_report}
- Traceability report: {traceability_report}

Instructions:
1. Aggregate quality metrics from all validation reports.
2. Calculate overall quality score.
3. Identify critical issues requiring immediate attention.
4. Prioritize improvement recommendations.
5. Generate comprehensive quality assessment report.
""",
            "generate_recommendations": """Action: Generate improvement recommendations.

Context:
- Issues identified: {issues}
- Quality metrics: {quality_metrics}

Instructions:
1. For each issue, provide specific, actionable recommendation.
2. Prioritize recommendations by severity and impact.
3. Link recommendations to quality criteria.
4. Provide implementation guidance where applicable.
5. Structure recommendations by category and priority.
"""
        }
        
        base_prompt = action_prompts.get(action, f"Action: {action}")
        if context:
            try:
                return base_prompt.format(**context)
            except:
                return base_prompt
        return base_prompt 
   def validate_consistency(self, srs_document: Dict[str, Any]) -> ConsistencyReport:
        """
        Validate consistency of SRS document.
        
        Args:
            srs_document: SRS document to validate
            
        Returns:
            Consistency validation report
        """
        logger.info(f"Validating consistency of document: {srs_document.get('id', 'Unknown')}")
        
        # Apply consistency validation methodology
        validation_methodology = self.apply_methodology("consistency_validation")
        
        # Validate consistency using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "validate_consistency",
            context={
                "document_id": srs_document.get('id', 'Unknown'),
                "standard": srs_document.get('standard', 'IEEE 830')
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "document": srs_document,
                "methodology_guide": validation_methodology,
                "quality_thresholds": self.quality_thresholds,
                "supported_standards": self.supported_standards
            },
            reasoning_template="consistency_validation"
        )
        
        # Create consistency report
        consistency_report = self._create_consistency_report(srs_document, cot_result)
        
        # Store consistency report
        self.consistency_reports[consistency_report.id] = consistency_report
        
        # Create artifact for consistency report
        if self.event_bus and self.session_id:
            artifact = self._create_consistency_report_artifact(consistency_report)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Consistency validation completed with score: {consistency_report.consistency_score:.2f}")
        return consistency_report
    
    def check_completeness(self, srs_document: Dict[str, Any], 
                          requirements: List[Dict[str, Any]]) -> CompletenessReport:
        """
        Check completeness of SRS document against requirements.
        
        Args:
            srs_document: SRS document to check
            requirements: List of system requirements
            
        Returns:
            Completeness validation report
        """
        logger.info(f"Checking completeness of document: {srs_document.get('id', 'Unknown')}")
        
        # Apply completeness checking methodology
        completeness_methodology = self.apply_methodology("completeness_checking")
        
        # Check completeness using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "check_completeness",
            context={
                "document_id": srs_document.get('id', 'Unknown'),
                "requirements_count": len(requirements),
                "standard": srs_document.get('standard', 'IEEE 830')
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "document": srs_document,
                "requirements": requirements,
                "methodology_guide": completeness_methodology,
                "quality_thresholds": self.quality_thresholds,
                "supported_standards": self.supported_standards
            },
            reasoning_template="completeness_validation"
        )
        
        # Create completeness report
        completeness_report = self._create_completeness_report(srs_document, requirements, cot_result)
        
        # Store completeness report
        self.completeness_reports[completeness_report.id] = completeness_report
        
        # Create artifact for completeness report
        if self.event_bus and self.session_id:
            artifact = self._create_completeness_report_artifact(completeness_report)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Completeness check completed with score: {completeness_report.completeness_score:.2f}")
        return completeness_report
    
    def verify_traceability(self, srs_document: Dict[str, Any], 
                           traceability_matrix: Dict[str, Any]) -> TraceabilityReport:
        """
        Verify traceability of requirements in SRS document.
        
        Args:
            srs_document: SRS document to verify
            traceability_matrix: Traceability matrix with requirement links
            
        Returns:
            Traceability validation report
        """
        logger.info(f"Verifying traceability of document: {srs_document.get('id', 'Unknown')}")
        
        # Apply traceability verification methodology
        traceability_methodology = self.apply_methodology("traceability_verification")
        
        # Verify traceability using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "verify_traceability",
            context={
                "document_id": srs_document.get('id', 'Unknown'),
                "traceability_matrix": "provided"
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "document": srs_document,
                "traceability_matrix": traceability_matrix,
                "methodology_guide": traceability_methodology,
                "quality_thresholds": self.quality_thresholds
            },
            reasoning_template="traceability_verification"
        )
        
        # Create traceability report
        traceability_report = self._create_traceability_report(srs_document, traceability_matrix, cot_result)
        
        # Store traceability report
        self.traceability_reports[traceability_report.id] = traceability_report
        
        # Create artifact for traceability report
        if self.event_bus and self.session_id:
            artifact = self._create_traceability_report_artifact(traceability_report)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Traceability verification completed with score: {traceability_report.traceability_score:.2f}")
        return traceability_report
    
    def _create_consistency_report(self, srs_document: Dict[str, Any], 
                                 cot_result: Dict[str, Any]) -> ConsistencyReport:
        """Create consistency report from validation results."""
        report_id = str(uuid.uuid4())
        document_id = srs_document.get('id', 'unknown')
        
        # Parse violations from CoT result
        violations = self._parse_consistency_violations(cot_result["response"], srs_document)
        
        # Calculate consistency score
        consistency_score = self._calculate_consistency_score(violations, srs_document)
        
        # Create summary
        summary = {
            "total_violations": len(violations),
            "critical_violations": len([v for v in violations if v.severity == "critical"]),
            "high_violations": len([v for v in violations if v.severity == "high"]),
            "medium_violations": len([v for v in violations if v.severity == "medium"]),
            "low_violations": len([v for v in violations if v.severity == "low"]),
            "violation_types": self._group_violations_by_type(violations)
        }
        
        return ConsistencyReport(
            id=report_id,
            document_id=document_id,
            consistency_score=consistency_score,
            violations=violations,
            summary=summary
        )
    
    def _create_completeness_report(self, srs_document: Dict[str, Any], 
                                  requirements: List[Dict[str, Any]],
                                  cot_result: Dict[str, Any]) -> CompletenessReport:
        """Create completeness report from validation results."""
        report_id = str(uuid.uuid4())
        document_id = srs_document.get('id', 'unknown')
        
        # Parse gaps from CoT result
        gaps = self._parse_completeness_gaps(cot_result["response"], srs_document, requirements)
        
        # Calculate completeness score
        completeness_score = self._calculate_completeness_score(gaps, srs_document, requirements)
        
        # Create coverage analysis
        coverage_analysis = self._analyze_requirement_coverage(srs_document, requirements)
        
        return CompletenessReport(
            id=report_id,
            document_id=document_id,
            completeness_score=completeness_score,
            gaps=gaps,
            coverage_analysis=coverage_analysis
        )
    
    def _create_traceability_report(self, srs_document: Dict[str, Any], 
                                  traceability_matrix: Dict[str, Any],
                                  cot_result: Dict[str, Any]) -> TraceabilityReport:
        """Create traceability report from verification results."""
        report_id = str(uuid.uuid4())
        document_id = srs_document.get('id', 'unknown')
        
        # Parse traceability issues from CoT result
        issues = self._parse_traceability_issues(cot_result["response"], srs_document, traceability_matrix)
        
        # Calculate traceability score
        traceability_score = self._calculate_traceability_score(issues, traceability_matrix)
        
        # Create coverage matrix
        coverage_matrix = self._create_traceability_coverage_matrix(srs_document, traceability_matrix)
        
        return TraceabilityReport(
            id=report_id,
            document_id=document_id,
            traceability_score=traceability_score,
            issues=issues,
            coverage_matrix=coverage_matrix
        )
    
    def _parse_consistency_violations(self, response: str, 
                                    srs_document: Dict[str, Any]) -> List[ConsistencyViolation]:
        """Parse consistency violations from CoT response."""
        violations = []
        
        # Simple parsing logic - in production would be more sophisticated
        lines = response.split('\n')
        current_violation = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('VIOLATION:') or line.startswith('Type:'):
                if current_violation:
                    violation = self._create_consistency_violation_from_dict(current_violation)
                    if violation:
                        violations.append(violation)
                current_violation = {'violation_type': line.split(':', 1)[1].strip()}
            elif line.startswith('Description:'):
                current_violation['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Severity:'):
                current_violation['severity'] = line.split(':', 1)[1].strip()
            elif line.startswith('Location:'):
                current_violation['location'] = line.split(':', 1)[1].strip()
            elif line.startswith('Recommendation:'):
                current_violation['recommendation'] = line.split(':', 1)[1].strip()
        
        # Handle last violation
        if current_violation:
            violation = self._create_consistency_violation_from_dict(current_violation)
            if violation:
                violations.append(violation)
        
        # Create default violations if parsing failed
        if not violations:
            violations = self._create_default_consistency_violations(srs_document)
        
        return violations
    
    def _parse_completeness_gaps(self, response: str, srs_document: Dict[str, Any],
                               requirements: List[Dict[str, Any]]) -> List[CompletenessGap]:
        """Parse completeness gaps from CoT response."""
        gaps = []
        
        # Simple parsing logic
        lines = response.split('\n')
        current_gap = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('GAP:') or line.startswith('Type:'):
                if current_gap:
                    gap = self._create_completeness_gap_from_dict(current_gap)
                    if gap:
                        gaps.append(gap)
                current_gap = {'gap_type': line.split(':', 1)[1].strip()}
            elif line.startswith('Description:'):
                current_gap['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Severity:'):
                current_gap['severity'] = line.split(':', 1)[1].strip()
            elif line.startswith('Expected:'):
                current_gap['expected_content'] = line.split(':', 1)[1].strip()
            elif line.startswith('Recommendation:'):
                current_gap['recommendation'] = line.split(':', 1)[1].strip()
        
        # Handle last gap
        if current_gap:
            gap = self._create_completeness_gap_from_dict(current_gap)
            if gap:
                gaps.append(gap)
        
        # Create default gaps if parsing failed
        if not gaps:
            gaps = self._create_default_completeness_gaps(srs_document, requirements)
        
        return gaps
    
    def _parse_traceability_issues(self, response: str, srs_document: Dict[str, Any],
                                 traceability_matrix: Dict[str, Any]) -> List[TraceabilityIssue]:
        """Parse traceability issues from CoT response."""
        issues = []
        
        # Simple parsing logic
        lines = response.split('\n')
        current_issue = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('ISSUE:') or line.startswith('Type:'):
                if current_issue:
                    issue = self._create_traceability_issue_from_dict(current_issue)
                    if issue:
                        issues.append(issue)
                current_issue = {'issue_type': line.split(':', 1)[1].strip()}
            elif line.startswith('Description:'):
                current_issue['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Severity:'):
                current_issue['severity'] = line.split(':', 1)[1].strip()
            elif line.startswith('Source:'):
                current_issue['source_id'] = line.split(':', 1)[1].strip()
            elif line.startswith('Target:'):
                current_issue['target_id'] = line.split(':', 1)[1].strip()
            elif line.startswith('Recommendation:'):
                current_issue['recommendation'] = line.split(':', 1)[1].strip()
        
        # Handle last issue
        if current_issue:
            issue = self._create_traceability_issue_from_dict(current_issue)
            if issue:
                issues.append(issue)
        
        # Create default issues if parsing failed
        if not issues:
            issues = self._create_default_traceability_issues(srs_document, traceability_matrix)
        
        return issues    def
 _create_consistency_violation_from_dict(self, violation_dict: Dict[str, Any]) -> Optional[ConsistencyViolation]:
        """Create ConsistencyViolation object from parsed dictionary."""
        try:
            return ConsistencyViolation(
                id=str(uuid.uuid4()),
                violation_type=violation_dict.get('violation_type', 'unknown'),
                description=violation_dict.get('description', 'Consistency violation detected'),
                severity=violation_dict.get('severity', 'medium'),
                location=violation_dict.get('location', 'unknown'),
                recommendation=violation_dict.get('recommendation', 'Review and correct the violation')
            )
        except Exception as e:
            logger.warning(f"Failed to create consistency violation from dict: {e}")
            return None
    
    def _create_completeness_gap_from_dict(self, gap_dict: Dict[str, Any]) -> Optional[CompletenessGap]:
        """Create CompletenessGap object from parsed dictionary."""
        try:
            return CompletenessGap(
                id=str(uuid.uuid4()),
                gap_type=gap_dict.get('gap_type', 'unknown'),
                description=gap_dict.get('description', 'Completeness gap detected'),
                severity=gap_dict.get('severity', 'medium'),
                expected_content=gap_dict.get('expected_content', 'Missing content'),
                recommendation=gap_dict.get('recommendation', 'Add the missing content')
            )
        except Exception as e:
            logger.warning(f"Failed to create completeness gap from dict: {e}")
            return None
    
    def _create_traceability_issue_from_dict(self, issue_dict: Dict[str, Any]) -> Optional[TraceabilityIssue]:
        """Create TraceabilityIssue object from parsed dictionary."""
        try:
            return TraceabilityIssue(
                id=str(uuid.uuid4()),
                issue_type=issue_dict.get('issue_type', 'unknown'),
                description=issue_dict.get('description', 'Traceability issue detected'),
                severity=issue_dict.get('severity', 'medium'),
                source_id=issue_dict.get('source_id', 'unknown'),
                target_id=issue_dict.get('target_id', ''),
                recommendation=issue_dict.get('recommendation', 'Fix the traceability issue')
            )
        except Exception as e:
            logger.warning(f"Failed to create traceability issue from dict: {e}")
            return None
    
    def _create_default_consistency_violations(self, srs_document: Dict[str, Any]) -> List[ConsistencyViolation]:
        """Create default consistency violations when parsing fails."""
        return [
            ConsistencyViolation(
                id=str(uuid.uuid4()),
                violation_type="terminology",
                description="Inconsistent terminology usage detected",
                severity="medium",
                location="document-wide",
                recommendation="Standardize terminology usage throughout the document"
            )
        ]
    
    def _create_default_completeness_gaps(self, srs_document: Dict[str, Any],
                                        requirements: List[Dict[str, Any]]) -> List[CompletenessGap]:
        """Create default completeness gaps when parsing fails."""
        return [
            CompletenessGap(
                id=str(uuid.uuid4()),
                gap_type="missing_section",
                description="Some required sections may be missing",
                severity="medium",
                expected_content="All IEEE 830 required sections",
                recommendation="Review document structure against IEEE 830 standard"
            )
        ]
    
    def _create_default_traceability_issues(self, srs_document: Dict[str, Any],
                                          traceability_matrix: Dict[str, Any]) -> List[TraceabilityIssue]:
        """Create default traceability issues when parsing fails."""
        return [
            TraceabilityIssue(
                id=str(uuid.uuid4()),
                issue_type="missing_link",
                description="Some requirements may lack proper traceability links",
                severity="medium",
                source_id="unknown",
                recommendation="Establish complete traceability links for all requirements"
            )
        ]
    
    def _calculate_consistency_score(self, violations: List[ConsistencyViolation], 
                                   srs_document: Dict[str, Any]) -> float:
        """Calculate consistency score based on violations."""
        if not violations:
            return 1.0
        
        # Calculate weighted penalty based on violation severity
        total_penalty = 0.0
        for violation in violations:
            penalty = self.severity_weights.get(violation.severity, 0.5)
            total_penalty += penalty
        
        # Normalize by document size (approximate)
        document_size = len(srs_document.get('sections', [])) + 1
        normalized_penalty = total_penalty / document_size
        
        # Calculate score (1.0 - penalty, minimum 0.0)
        score = max(0.0, 1.0 - normalized_penalty)
        return round(score, 3)
    
    def _calculate_completeness_score(self, gaps: List[CompletenessGap], 
                                    srs_document: Dict[str, Any],
                                    requirements: List[Dict[str, Any]]) -> float:
        """Calculate completeness score based on gaps."""
        if not gaps:
            return 1.0
        
        # Calculate weighted penalty based on gap severity
        total_penalty = 0.0
        for gap in gaps:
            penalty = self.severity_weights.get(gap.severity, 0.5)
            total_penalty += penalty
        
        # Normalize by expected content size
        expected_sections = 10  # Approximate number of expected sections
        expected_requirements = len(requirements) if requirements else 5
        total_expected = expected_sections + expected_requirements
        
        normalized_penalty = total_penalty / total_expected
        
        # Calculate score
        score = max(0.0, 1.0 - normalized_penalty)
        return round(score, 3)
    
    def _calculate_traceability_score(self, issues: List[TraceabilityIssue], 
                                    traceability_matrix: Dict[str, Any]) -> float:
        """Calculate traceability score based on issues."""
        if not issues:
            return 1.0
        
        # Calculate weighted penalty based on issue severity
        total_penalty = 0.0
        for issue in issues:
            penalty = self.severity_weights.get(issue.severity, 0.5)
            total_penalty += penalty
        
        # Normalize by total number of expected links
        total_links = len(traceability_matrix.get('links', [])) if traceability_matrix else 1
        normalized_penalty = total_penalty / total_links
        
        # Calculate score
        score = max(0.0, 1.0 - normalized_penalty)
        return round(score, 3)
    
    def _group_violations_by_type(self, violations: List[ConsistencyViolation]) -> Dict[str, int]:
        """Group violations by type for summary."""
        type_counts = {}
        for violation in violations:
            type_counts[violation.violation_type] = type_counts.get(violation.violation_type, 0) + 1
        return type_counts
    
    def _analyze_requirement_coverage(self, srs_document: Dict[str, Any], 
                                    requirements: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze requirement coverage in the document."""
        total_requirements = len(requirements)
        covered_requirements = 0
        
        # Simple coverage analysis - in production would be more sophisticated
        document_content = str(srs_document)
        for req in requirements:
            req_id = req.get('id', '')
            if req_id and req_id in document_content:
                covered_requirements += 1
        
        coverage_percentage = (covered_requirements / total_requirements * 100) if total_requirements > 0 else 0
        
        return {
            "total_requirements": total_requirements,
            "covered_requirements": covered_requirements,
            "uncovered_requirements": total_requirements - covered_requirements,
            "coverage_percentage": round(coverage_percentage, 2)
        }
    
    def _create_traceability_coverage_matrix(self, srs_document: Dict[str, Any], 
                                           traceability_matrix: Dict[str, Any]) -> Dict[str, Any]:
        """Create traceability coverage matrix."""
        links = traceability_matrix.get('links', [])
        
        # Analyze link coverage
        forward_links = len([link for link in links if link.get('link_type') == 'derives_from'])
        backward_links = len([link for link in links if link.get('link_type') == 'implements'])
        total_links = len(links)
        
        return {
            "total_links": total_links,
            "forward_links": forward_links,
            "backward_links": backward_links,
            "bidirectional_coverage": min(forward_links, backward_links),
            "link_types": self._analyze_link_types(links)
        }
    
    def _analyze_link_types(self, links: List[Dict[str, Any]]) -> Dict[str, int]:
        """Analyze distribution of link types."""
        type_counts = {}
        for link in links:
            link_type = link.get('link_type', 'unknown')
            type_counts[link_type] = type_counts.get(link_type, 0) + 1
        return type_counts
    
    def _create_consistency_report_artifact(self, report: ConsistencyReport) -> Artifact:
        """Create artifact for consistency report."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REPORT,
            content=report.to_dict(),
            metadata=ArtifactMetadata(
                title=f"Consistency Report - {report.document_id}",
                description="Document consistency validation report",
                tags=["consistency", "validation", "quality"],
                created_by=self.name
            ),
            status=ArtifactStatus.COMPLETED
        )
    
    def _create_completeness_report_artifact(self, report: CompletenessReport) -> Artifact:
        """Create artifact for completeness report."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REPORT,
            content=report.to_dict(),
            metadata=ArtifactMetadata(
                title=f"Completeness Report - {report.document_id}",
                description="Document completeness validation report",
                tags=["completeness", "validation", "quality"],
                created_by=self.name
            ),
            status=ArtifactStatus.COMPLETED
        )
    
    def _create_traceability_report_artifact(self, report: TraceabilityReport) -> Artifact:
        """Create artifact for traceability report."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REPORT,
            content=report.to_dict(),
            metadata=ArtifactMetadata(
                title=f"Traceability Report - {report.document_id}",
                description="Requirements traceability validation report",
                tags=["traceability", "validation", "quality"],
                created_by=self.name
            ),
            status=ArtifactStatus.COMPLETED
        )  
  def assess_quality_metrics(self, srs_document: Dict[str, Any]) -> QualityMetrics:
        """
        Assess overall quality metrics for SRS document.
        
        Args:
            srs_document: SRS document to assess
            
        Returns:
            Comprehensive quality metrics
        """
        logger.info(f"Assessing quality metrics for document: {srs_document.get('id', 'Unknown')}")
        
        # Apply quality assessment methodology
        quality_methodology = self.apply_methodology("quality_assessment")
        
        # Assess quality using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "assess_quality",
            context={
                "document_id": srs_document.get('id', 'Unknown'),
                "consistency_report": "available",
                "completeness_report": "available",
                "traceability_report": "available"
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "document": srs_document,
                "methodology_guide": quality_methodology,
                "quality_thresholds": self.quality_thresholds,
                "severity_weights": self.severity_weights
            },
            reasoning_template="quality_assessment"
        )
        
        # Calculate individual quality scores
        consistency_score = self._assess_consistency_score(srs_document)
        completeness_score = self._assess_completeness_score(srs_document)
        traceability_score = self._assess_traceability_score(srs_document)
        clarity_score = self._assess_clarity_score(srs_document, cot_result)
        verifiability_score = self._assess_verifiability_score(srs_document, cot_result)
        
        # Calculate overall score
        overall_score = self._calculate_overall_quality_score(
            consistency_score, completeness_score, traceability_score,
            clarity_score, verifiability_score
        )
        
        # Calculate defect density
        defect_density = self._calculate_defect_density(srs_document)
        
        # Calculate improvement potential
        improvement_potential = self._calculate_improvement_potential(
            overall_score, consistency_score, completeness_score, traceability_score
        )
        
        # Create quality metrics
        quality_metrics = QualityMetrics(
            document_id=srs_document.get('id', 'unknown'),
            overall_score=overall_score,
            consistency_score=consistency_score,
            completeness_score=completeness_score,
            traceability_score=traceability_score,
            clarity_score=clarity_score,
            verifiability_score=verifiability_score,
            defect_density=defect_density,
            improvement_potential=improvement_potential
        )
        
        # Store quality metrics
        self.quality_metrics[quality_metrics.document_id] = quality_metrics
        
        # Create artifact for quality metrics
        if self.event_bus and self.session_id:
            artifact = self._create_quality_metrics_artifact(quality_metrics)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Quality assessment completed with overall score: {overall_score:.2f}")
        return quality_metrics
    
    def identify_quality_defects(self, srs_document: Dict[str, Any]) -> List[QualityDefect]:
        """
        Identify quality defects in SRS document.
        
        Args:
            srs_document: SRS document to analyze
            
        Returns:
            List of identified quality defects
        """
        logger.info(f"Identifying quality defects in document: {srs_document.get('id', 'Unknown')}")
        
        # Apply defect identification methodology
        defect_methodology = self.apply_methodology("defect_identification")
        
        # Identify defects using CoT reasoning
        cot_result = self.generate_with_cot(
            prompt="Identify quality defects including ambiguity, inconsistency, and unverifiability",
            context={
                "document": srs_document,
                "methodology_guide": defect_methodology,
                "quality_thresholds": self.quality_thresholds
            },
            reasoning_template="defect_identification"
        )
        
        # Parse defects from response
        defects = self._parse_quality_defects(cot_result["response"], srs_document)
        
        logger.info(f"Identified {len(defects)} quality defects")
        return defects
    
    def generate_improvement_recommendations(self, srs_document: Dict[str, Any],
                                           quality_metrics: QualityMetrics,
                                           defects: List[QualityDefect]) -> List[ImprovementRecommendation]:
        """
        Generate improvement recommendations based on quality analysis.
        
        Args:
            srs_document: SRS document analyzed
            quality_metrics: Quality metrics for the document
            defects: List of identified defects
            
        Returns:
            List of improvement recommendations
        """
        logger.info(f"Generating improvement recommendations for document: {srs_document.get('id', 'Unknown')}")
        
        # Apply improvement recommendation methodology
        improvement_methodology = self.apply_methodology("improvement_recommendations")
        
        # Generate recommendations using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "generate_recommendations",
            context={
                "issues": [defect.to_dict() for defect in defects],
                "quality_metrics": quality_metrics.to_dict()
            }
        )
        
        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "document": srs_document,
                "quality_metrics": quality_metrics.to_dict(),
                "defects": [defect.to_dict() for defect in defects],
                "methodology_guide": improvement_methodology,
                "quality_thresholds": self.quality_thresholds
            },
            reasoning_template="improvement_recommendations"
        )
        
        # Parse recommendations from response
        recommendations = self._parse_improvement_recommendations(cot_result["response"], quality_metrics, defects)
        
        # Store recommendations
        document_id = srs_document.get('id', 'unknown')
        self.improvement_recommendations[document_id] = recommendations
        
        # Create artifact for recommendations
        if self.event_bus and self.session_id:
            artifact = self._create_improvement_recommendations_artifact(recommendations, document_id)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Generated {len(recommendations)} improvement recommendations")
        return recommendations
    
    def perform_comprehensive_review(self, srs_document: Dict[str, Any],
                                   requirements: List[Dict[str, Any]],
                                   traceability_matrix: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform comprehensive review of SRS document.
        
        Args:
            srs_document: SRS document to review
            requirements: List of system requirements
            traceability_matrix: Traceability matrix
            
        Returns:
            Comprehensive review report
        """
        logger.info(f"Performing comprehensive review of document: {srs_document.get('id', 'Unknown')}")
        
        # Perform all validation checks
        consistency_report = self.validate_consistency(srs_document)
        completeness_report = self.check_completeness(srs_document, requirements)
        traceability_report = self.verify_traceability(srs_document, traceability_matrix)
        
        # Assess quality metrics
        quality_metrics = self.assess_quality_metrics(srs_document)
        
        # Identify defects
        defects = self.identify_quality_defects(srs_document)
        
        # Generate improvement recommendations
        recommendations = self.generate_improvement_recommendations(srs_document, quality_metrics, defects)
        
        # Create comprehensive review report
        review_report = {
            "document_id": srs_document.get('id', 'unknown'),
            "review_date": datetime.now().isoformat(),
            "reviewer": self.name,
            "consistency_report": consistency_report.to_dict(),
            "completeness_report": completeness_report.to_dict(),
            "traceability_report": traceability_report.to_dict(),
            "quality_metrics": quality_metrics.to_dict(),
            "defects": [defect.to_dict() for defect in defects],
            "improvement_recommendations": [rec.to_dict() for rec in recommendations],
            "overall_assessment": self._create_overall_assessment(
                consistency_report, completeness_report, traceability_report, quality_metrics
            )
        }
        
        # Create artifact for comprehensive review
        if self.event_bus and self.session_id:
            artifact = self._create_comprehensive_review_artifact(review_report)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info("Comprehensive review completed")
        return review_report
    
    def _assess_consistency_score(self, srs_document: Dict[str, Any]) -> float:
        """Assess consistency score for the document."""
        # Check if we have a recent consistency report
        document_id = srs_document.get('id', 'unknown')
        for report in self.consistency_reports.values():
            if report.document_id == document_id:
                return report.consistency_score
        
        # Default assessment if no report available
        return 0.8
    
    def _assess_completeness_score(self, srs_document: Dict[str, Any]) -> float:
        """Assess completeness score for the document."""
        # Check if we have a recent completeness report
        document_id = srs_document.get('id', 'unknown')
        for report in self.completeness_reports.values():
            if report.document_id == document_id:
                return report.completeness_score
        
        # Default assessment if no report available
        return 0.75
    
    def _assess_traceability_score(self, srs_document: Dict[str, Any]) -> float:
        """Assess traceability score for the document."""
        # Check if we have a recent traceability report
        document_id = srs_document.get('id', 'unknown')
        for report in self.traceability_reports.values():
            if report.document_id == document_id:
                return report.traceability_score
        
        # Default assessment if no report available
        return 0.7
    
    def _assess_clarity_score(self, srs_document: Dict[str, Any], cot_result: Dict[str, Any]) -> float:
        """Assess clarity score based on document analysis."""
        # Simple clarity assessment - in production would be more sophisticated
        sections = srs_document.get('sections', [])
        if not sections:
            return 0.5
        
        # Check for clear structure and content
        clarity_indicators = 0
        total_indicators = 5
        
        # Check for proper section structure
        if len(sections) >= 3:
            clarity_indicators += 1
        
        # Check for glossary
        if srs_document.get('glossary'):
            clarity_indicators += 1
        
        # Check for references
        if srs_document.get('references'):
            clarity_indicators += 1
        
        # Check for clear requirements format
        document_content = str(srs_document)
        if 'shall' in document_content.lower():
            clarity_indicators += 1
        
        # Check for numbered requirements
        if re.search(r'REQ-\d+|FUNC-\d+|\d+\.\d+', document_content):
            clarity_indicators += 1
        
        return round(clarity_indicators / total_indicators, 3)
    
    def _assess_verifiability_score(self, srs_document: Dict[str, Any], cot_result: Dict[str, Any]) -> float:
        """Assess verifiability score based on document analysis."""
        # Simple verifiability assessment
        document_content = str(srs_document).lower()
        
        verifiability_indicators = 0
        total_indicators = 4
        
        # Check for acceptance criteria
        if 'acceptance criteria' in document_content or 'test' in document_content:
            verifiability_indicators += 1
        
        # Check for measurable requirements
        if any(word in document_content for word in ['seconds', 'minutes', 'percent', 'number', 'count']):
            verifiability_indicators += 1
        
        # Check for specific conditions
        if any(word in document_content for word in ['when', 'if', 'given', 'provided']):
            verifiability_indicators += 1
        
        # Check for clear success criteria
        if any(word in document_content for word in ['success', 'complete', 'valid', 'correct']):
            verifiability_indicators += 1
        
        return round(verifiability_indicators / total_indicators, 3)
    
    def _calculate_overall_quality_score(self, consistency: float, completeness: float,
                                       traceability: float, clarity: float, verifiability: float) -> float:
        """Calculate overall quality score from individual scores."""
        # Weighted average of quality dimensions
        weights = {
            'consistency': 0.25,
            'completeness': 0.25,
            'traceability': 0.20,
            'clarity': 0.15,
            'verifiability': 0.15
        }
        
        overall_score = (
            consistency * weights['consistency'] +
            completeness * weights['completeness'] +
            traceability * weights['traceability'] +
            clarity * weights['clarity'] +
            verifiability * weights['verifiability']
        )
        
        return round(overall_score, 3)
    
    def _calculate_defect_density(self, srs_document: Dict[str, Any]) -> float:
        """Calculate defect density for the document."""
        # Simple defect density calculation
        sections = srs_document.get('sections', [])
        document_size = len(sections) if sections else 1
        
        # Count defects from all reports
        total_defects = 0
        document_id = srs_document.get('id', 'unknown')
        
        for report in self.consistency_reports.values():
            if report.document_id == document_id:
                total_defects += len(report.violations)
        
        for report in self.completeness_reports.values():
            if report.document_id == document_id:
                total_defects += len(report.gaps)
        
        for report in self.traceability_reports.values():
            if report.document_id == document_id:
                total_defects += len(report.issues)
        
        return round(total_defects / document_size, 3)
    
    def _calculate_improvement_potential(self, overall_score: float, consistency: float,
                                       completeness: float, traceability: float) -> float:
        """Calculate improvement potential based on current scores."""
        # Improvement potential is higher when scores are lower
        max_possible_improvement = 1.0 - overall_score
        
        # Consider individual dimension scores
        dimension_gaps = [
            1.0 - consistency,
            1.0 - completeness,
            1.0 - traceability
        ]
        
        avg_gap = sum(dimension_gaps) / len(dimension_gaps)
        improvement_potential = min(max_possible_improvement, avg_gap)
        
        return round(improvement_potential, 3)    def _
parse_quality_defects(self, response: str, srs_document: Dict[str, Any]) -> List[QualityDefect]:
        """Parse quality defects from CoT response."""
        defects = []
        
        # Simple parsing logic
        lines = response.split('\n')
        current_defect = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('DEFECT:') or line.startswith('Type:'):
                if current_defect:
                    defect = self._create_quality_defect_from_dict(current_defect)
                    if defect:
                        defects.append(defect)
                current_defect = {'defect_type': line.split(':', 1)[1].strip()}
            elif line.startswith('Description:'):
                current_defect['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Severity:'):
                current_defect['severity'] = line.split(':', 1)[1].strip()
            elif line.startswith('Location:'):
                current_defect['location'] = line.split(':', 1)[1].strip()
            elif line.startswith('Impact:'):
                current_defect['impact'] = line.split(':', 1)[1].strip()
            elif line.startswith('Root Cause:'):
                current_defect['root_cause'] = line.split(':', 1)[1].strip()
            elif line.startswith('Recommendation:'):
                current_defect['recommendation'] = line.split(':', 1)[1].strip()
        
        # Handle last defect
        if current_defect:
            defect = self._create_quality_defect_from_dict(current_defect)
            if defect:
                defects.append(defect)
        
        # Create default defects if parsing failed
        if not defects:
            defects = self._create_default_quality_defects(srs_document)
        
        return defects
    
    def _parse_improvement_recommendations(self, response: str, quality_metrics: QualityMetrics,
                                         defects: List[QualityDefect]) -> List[ImprovementRecommendation]:
        """Parse improvement recommendations from CoT response."""
        recommendations = []
        
        # Simple parsing logic
        lines = response.split('\n')
        current_rec = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('RECOMMENDATION:') or line.startswith('Title:'):
                if current_rec:
                    rec = self._create_improvement_recommendation_from_dict(current_rec)
                    if rec:
                        recommendations.append(rec)
                current_rec = {'title': line.split(':', 1)[1].strip()}
            elif line.startswith('Category:'):
                current_rec['category'] = line.split(':', 1)[1].strip()
            elif line.startswith('Priority:'):
                current_rec['priority'] = line.split(':', 1)[1].strip()
            elif line.startswith('Description:'):
                current_rec['description'] = line.split(':', 1)[1].strip()
            elif line.startswith('Rationale:'):
                current_rec['rationale'] = line.split(':', 1)[1].strip()
            elif line.startswith('Effort:'):
                current_rec['implementation_effort'] = line.split(':', 1)[1].strip()
            elif line.startswith('Benefit:'):
                current_rec['expected_benefit'] = line.split(':', 1)[1].strip()
            elif line.startswith('Actions:'):
                current_rec['action_items'] = [line.split(':', 1)[1].strip()]
        
        # Handle last recommendation
        if current_rec:
            rec = self._create_improvement_recommendation_from_dict(current_rec)
            if rec:
                recommendations.append(rec)
        
        # Create default recommendations if parsing failed
        if not recommendations:
            recommendations = self._create_default_improvement_recommendations(quality_metrics, defects)
        
        return recommendations
    
    def _create_quality_defect_from_dict(self, defect_dict: Dict[str, Any]) -> Optional[QualityDefect]:
        """Create QualityDefect object from parsed dictionary."""
        try:
            return QualityDefect(
                id=str(uuid.uuid4()),
                defect_type=defect_dict.get('defect_type', 'unknown'),
                description=defect_dict.get('description', 'Quality defect detected'),
                severity=defect_dict.get('severity', 'medium'),
                location=defect_dict.get('location', 'unknown'),
                impact=defect_dict.get('impact', 'Potential impact on document quality'),
                root_cause=defect_dict.get('root_cause', ''),
                recommendation=defect_dict.get('recommendation', 'Address the quality defect')
            )
        except Exception as e:
            logger.warning(f"Failed to create quality defect from dict: {e}")
            return None
    
    def _create_improvement_recommendation_from_dict(self, rec_dict: Dict[str, Any]) -> Optional[ImprovementRecommendation]:
        """Create ImprovementRecommendation object from parsed dictionary."""
        try:
            return ImprovementRecommendation(
                id=str(uuid.uuid4()),
                category=rec_dict.get('category', 'quality'),
                priority=rec_dict.get('priority', 'medium'),
                title=rec_dict.get('title', 'Improvement Recommendation'),
                description=rec_dict.get('description', 'Recommendation for document improvement'),
                rationale=rec_dict.get('rationale', 'Based on quality analysis'),
                implementation_effort=rec_dict.get('implementation_effort', 'medium'),
                expected_benefit=rec_dict.get('expected_benefit', 'Improved document quality'),
                action_items=rec_dict.get('action_items', ['Review and implement recommendation'])
            )
        except Exception as e:
            logger.warning(f"Failed to create improvement recommendation from dict: {e}")
            return None
    
    def _create_default_quality_defects(self, srs_document: Dict[str, Any]) -> List[QualityDefect]:
        """Create default quality defects when parsing fails."""
        return [
            QualityDefect(
                id=str(uuid.uuid4()),
                defect_type="ambiguity",
                description="Some requirements may contain ambiguous language",
                severity="medium",
                location="requirements sections",
                impact="May lead to misinterpretation during implementation",
                recommendation="Review and clarify ambiguous requirements"
            )
        ]
    
    def _create_default_improvement_recommendations(self, quality_metrics: QualityMetrics,
                                                  defects: List[QualityDefect]) -> List[ImprovementRecommendation]:
        """Create default improvement recommendations when parsing fails."""
        recommendations = []
        
        # Recommend improvements based on low scores
        if quality_metrics.consistency_score < self.quality_thresholds.get('consistency', 0.9):
            recommendations.append(ImprovementRecommendation(
                id=str(uuid.uuid4()),
                category="consistency",
                priority="high",
                title="Improve Document Consistency",
                description="Address consistency issues in terminology and formatting",
                rationale=f"Consistency score ({quality_metrics.consistency_score:.2f}) is below threshold",
                implementation_effort="medium",
                expected_benefit="Improved document clarity and professional appearance",
                action_items=["Review terminology usage", "Standardize formatting", "Update style guide"]
            ))
        
        if quality_metrics.completeness_score < self.quality_thresholds.get('completeness', 0.85):
            recommendations.append(ImprovementRecommendation(
                id=str(uuid.uuid4()),
                category="completeness",
                priority="high",
                title="Address Completeness Gaps",
                description="Add missing sections and requirements",
                rationale=f"Completeness score ({quality_metrics.completeness_score:.2f}) is below threshold",
                implementation_effort="high",
                expected_benefit="Complete coverage of all requirements",
                action_items=["Identify missing sections", "Add missing requirements", "Review against standards"]
            ))
        
        if quality_metrics.traceability_score < self.quality_thresholds.get('traceability', 0.8):
            recommendations.append(ImprovementRecommendation(
                id=str(uuid.uuid4()),
                category="traceability",
                priority="medium",
                title="Improve Requirements Traceability",
                description="Establish complete traceability links",
                rationale=f"Traceability score ({quality_metrics.traceability_score:.2f}) is below threshold",
                implementation_effort="medium",
                expected_benefit="Better change impact analysis and requirement tracking",
                action_items=["Create traceability matrix", "Link all requirements", "Verify traceability"]
            ))
        
        return recommendations
    
    def _create_overall_assessment(self, consistency_report: ConsistencyReport,
                                 completeness_report: CompletenessReport,
                                 traceability_report: TraceabilityReport,
                                 quality_metrics: QualityMetrics) -> Dict[str, Any]:
        """Create overall assessment summary."""
        # Determine overall quality level
        overall_score = quality_metrics.overall_score
        if overall_score >= 0.9:
            quality_level = "Excellent"
        elif overall_score >= 0.8:
            quality_level = "Good"
        elif overall_score >= 0.7:
            quality_level = "Acceptable"
        elif overall_score >= 0.6:
            quality_level = "Needs Improvement"
        else:
            quality_level = "Poor"
        
        # Count total issues
        total_issues = (
            len(consistency_report.violations) +
            len(completeness_report.gaps) +
            len(traceability_report.issues)
        )
        
        # Identify key strengths and weaknesses
        strengths = []
        weaknesses = []
        
        if consistency_report.consistency_score >= 0.9:
            strengths.append("Excellent consistency")
        elif consistency_report.consistency_score < 0.7:
            weaknesses.append("Consistency issues")
        
        if completeness_report.completeness_score >= 0.9:
            strengths.append("Comprehensive coverage")
        elif completeness_report.completeness_score < 0.7:
            weaknesses.append("Completeness gaps")
        
        if traceability_report.traceability_score >= 0.9:
            strengths.append("Strong traceability")
        elif traceability_report.traceability_score < 0.7:
            weaknesses.append("Traceability issues")
        
        return {
            "overall_quality_level": quality_level,
            "overall_score": overall_score,
            "total_issues": total_issues,
            "critical_issues": sum([
                len([v for v in consistency_report.violations if v.severity == "critical"]),
                len([g for g in completeness_report.gaps if g.severity == "critical"]),
                len([i for i in traceability_report.issues if i.severity == "critical"])
            ]),
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendation_summary": "Focus on addressing critical issues first, then work on improving overall quality scores."
        }
    
    def _create_quality_metrics_artifact(self, quality_metrics: QualityMetrics) -> Artifact:
        """Create artifact for quality metrics."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REPORT,
            content=quality_metrics.to_dict(),
            metadata=ArtifactMetadata(
                title=f"Quality Metrics - {quality_metrics.document_id}",
                description="Comprehensive quality metrics assessment",
                tags=["quality", "metrics", "assessment"],
                created_by=self.name
            ),
            status=ArtifactStatus.COMPLETED
        )
    
    def _create_improvement_recommendations_artifact(self, recommendations: List[ImprovementRecommendation],
                                                   document_id: str) -> Artifact:
        """Create artifact for improvement recommendations."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REPORT,
            content={
                "document_id": document_id,
                "recommendations": [rec.to_dict() for rec in recommendations],
                "total_recommendations": len(recommendations),
                "priority_breakdown": self._analyze_recommendation_priorities(recommendations)
            },
            metadata=ArtifactMetadata(
                title=f"Improvement Recommendations - {document_id}",
                description="Prioritized improvement recommendations",
                tags=["improvement", "recommendations", "quality"],
                created_by=self.name
            ),
            status=ArtifactStatus.COMPLETED
        )
    
    def _create_comprehensive_review_artifact(self, review_report: Dict[str, Any]) -> Artifact:
        """Create artifact for comprehensive review report."""
        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.REPORT,
            content=review_report,
            metadata=ArtifactMetadata(
                title=f"Comprehensive Review - {review_report['document_id']}",
                description="Complete quality review and assessment report",
                tags=["review", "comprehensive", "quality", "assessment"],
                created_by=self.name
            ),
            status=ArtifactStatus.COMPLETED
        )
    
    def _analyze_recommendation_priorities(self, recommendations: List[ImprovementRecommendation]) -> Dict[str, int]:
        """Analyze priority distribution of recommendations."""
        priority_counts = {}
        for rec in recommendations:
            priority_counts[rec.priority] = priority_counts.get(rec.priority, 0) + 1
        return priority_counts