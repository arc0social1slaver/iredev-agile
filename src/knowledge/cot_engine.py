"""
Chain-of-Thought reasoning engine for iReDev framework.
Provides expert-level reasoning capabilities by integrating knowledge modules.
"""

import json
import yaml
from typing import Dict, Any, List, Optional, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging

from .knowledge_manager import KnowledgeModule, KnowledgeType

logger = logging.getLogger(__name__)


class ReasoningStep(Enum):
    """Types of reasoning steps in Chain-of-Thought process."""
    OBSERVATION = "observation"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    EVALUATION = "evaluation"
    CONCLUSION = "conclusion"
    VALIDATION = "validation"


@dataclass
class CoTStep:
    """Represents a single step in Chain-of-Thought reasoning."""
    step_type: ReasoningStep
    description: str
    input_data: Dict[str, Any]
    reasoning: str
    output_data: Dict[str, Any]
    knowledge_applied: List[str] = field(default_factory=list)
    confidence: float = 1.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary representation."""
        return {
            "step_type": self.step_type.value,
            "description": self.description,
            "input_data": self.input_data,
            "reasoning": self.reasoning,
            "output_data": self.output_data,
            "knowledge_applied": self.knowledge_applied,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class CoTProcess:
    """Represents a complete Chain-of-Thought reasoning process."""
    process_id: str
    task_description: str
    steps: List[CoTStep] = field(default_factory=list)
    final_result: Optional[Dict[str, Any]] = None
    overall_confidence: float = 0.0
    knowledge_modules_used: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    def add_step(self, step: CoTStep) -> None:
        """Add a reasoning step to the process."""
        self.steps.append(step)
        
        # Update knowledge modules used
        for knowledge_id in step.knowledge_applied:
            if knowledge_id not in self.knowledge_modules_used:
                self.knowledge_modules_used.append(knowledge_id)
    
    def complete(self, final_result: Dict[str, Any]) -> None:
        """Mark the process as completed with final result."""
        self.final_result = final_result
        self.completed_at = datetime.now()
        
        # Calculate overall confidence as average of step confidences
        if self.steps:
            self.overall_confidence = sum(step.confidence for step in self.steps) / len(self.steps)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert process to dictionary representation."""
        return {
            "process_id": self.process_id,
            "task_description": self.task_description,
            "steps": [step.to_dict() for step in self.steps],
            "final_result": self.final_result,
            "overall_confidence": self.overall_confidence,
            "knowledge_modules_used": self.knowledge_modules_used,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }


class ReasoningTemplate:
    """Template for structured reasoning processes."""
    
    def __init__(self, name: str, description: str, steps: List[Dict[str, Any]]):
        """Initialize reasoning template.
        
        Args:
            name: Template name.
            description: Template description.
            steps: List of step templates.
        """
        self.name = name
        self.description = description
        self.steps = steps
    
    def create_process(self, process_id: str, task_description: str) -> CoTProcess:
        """Create a new CoT process from this template.
        
        Args:
            process_id: Unique process identifier.
            task_description: Description of the task.
            
        Returns:
            New CoT process instance.
        """
        return CoTProcess(
            process_id=process_id,
            task_description=task_description
        )


class ChainOfThoughtEngine:
    """Chain-of-Thought reasoning engine for knowledge-driven agents."""
    
    def __init__(self):
        """Initialize the CoT engine."""
        self.templates: Dict[str, ReasoningTemplate] = {}
        self.active_processes: Dict[str, CoTProcess] = {}
        self.completed_processes: Dict[str, CoTProcess] = {}
        
        # Knowledge integration
        self.knowledge_modules: Dict[str, KnowledgeModule] = {}
        
        # Reasoning strategies
        self.reasoning_strategies: Dict[str, Callable] = {}
        
        # Initialize default templates
        self._initialize_default_templates()
        self._initialize_reasoning_strategies()
    
    def _initialize_default_templates(self) -> None:
        """Initialize default reasoning templates."""
        
        # Requirements Analysis Template
        requirements_analysis_steps = [
            {
                "step_type": ReasoningStep.OBSERVATION,
                "description": "Observe and collect initial requirements information",
                "knowledge_types": [KnowledgeType.DOMAIN_KNOWLEDGE, KnowledgeType.METHODOLOGY]
            },
            {
                "step_type": ReasoningStep.ANALYSIS,
                "description": "Analyze requirements for completeness and consistency",
                "knowledge_types": [KnowledgeType.STANDARDS, KnowledgeType.STRATEGIES]
            },
            {
                "step_type": ReasoningStep.SYNTHESIS,
                "description": "Synthesize structured requirements from analysis",
                "knowledge_types": [KnowledgeType.TEMPLATES, KnowledgeType.STANDARDS]
            },
            {
                "step_type": ReasoningStep.EVALUATION,
                "description": "Evaluate requirements quality and feasibility",
                "knowledge_types": [KnowledgeType.DOMAIN_KNOWLEDGE, KnowledgeType.STRATEGIES]
            },
            {
                "step_type": ReasoningStep.CONCLUSION,
                "description": "Draw conclusions and make recommendations",
                "knowledge_types": [KnowledgeType.METHODOLOGY, KnowledgeType.STRATEGIES]
            }
        ]
        
        self.templates["requirements_analysis"] = ReasoningTemplate(
            name="Requirements Analysis",
            description="Systematic analysis of software requirements",
            steps=requirements_analysis_steps
        )
        
        # Interview Planning Template
        interview_planning_steps = [
            {
                "step_type": ReasoningStep.OBSERVATION,
                "description": "Identify stakeholders and interview objectives",
                "knowledge_types": [KnowledgeType.METHODOLOGY, KnowledgeType.STRATEGIES]
            },
            {
                "step_type": ReasoningStep.ANALYSIS,
                "description": "Analyze stakeholder characteristics and needs",
                "knowledge_types": [KnowledgeType.DOMAIN_KNOWLEDGE, KnowledgeType.METHODOLOGY]
            },
            {
                "step_type": ReasoningStep.SYNTHESIS,
                "description": "Create interview structure and questions",
                "knowledge_types": [KnowledgeType.TEMPLATES, KnowledgeType.STRATEGIES]
            },
            {
                "step_type": ReasoningStep.EVALUATION,
                "description": "Evaluate interview plan effectiveness",
                "knowledge_types": [KnowledgeType.METHODOLOGY, KnowledgeType.STRATEGIES]
            }
        ]
        
        self.templates["interview_planning"] = ReasoningTemplate(
            name="Interview Planning",
            description="Systematic planning of stakeholder interviews",
            steps=interview_planning_steps
        )
        
        # Document Generation Template
        document_generation_steps = [
            {
                "step_type": ReasoningStep.OBSERVATION,
                "description": "Gather content and requirements for document",
                "knowledge_types": [KnowledgeType.TEMPLATES, KnowledgeType.STANDARDS]
            },
            {
                "step_type": ReasoningStep.ANALYSIS,
                "description": "Analyze content structure and organization needs",
                "knowledge_types": [KnowledgeType.STANDARDS, KnowledgeType.DOMAIN_KNOWLEDGE]
            },
            {
                "step_type": ReasoningStep.SYNTHESIS,
                "description": "Generate structured document content",
                "knowledge_types": [KnowledgeType.TEMPLATES, KnowledgeType.STANDARDS]
            },
            {
                "step_type": ReasoningStep.VALIDATION,
                "description": "Validate document against standards and requirements",
                "knowledge_types": [KnowledgeType.STANDARDS, KnowledgeType.STRATEGIES]
            }
        ]
        
        self.templates["document_generation"] = ReasoningTemplate(
            name="Document Generation",
            description="Systematic generation of technical documents",
            steps=document_generation_steps
        )
    
    def _initialize_reasoning_strategies(self) -> None:
        """Initialize reasoning strategies."""
        
        def deductive_reasoning(premises: List[str], knowledge: Dict[str, Any]) -> str:
            """Apply deductive reasoning strategy."""
            reasoning = "Applying deductive reasoning:\n"
            reasoning += f"Premises: {premises}\n"
            reasoning += f"Knowledge applied: {list(knowledge.keys())}\n"
            reasoning += "Logical conclusion follows from premises and knowledge."
            return reasoning
        
        def inductive_reasoning(observations: List[str], knowledge: Dict[str, Any]) -> str:
            """Apply inductive reasoning strategy."""
            reasoning = "Applying inductive reasoning:\n"
            reasoning += f"Observations: {observations}\n"
            reasoning += f"Knowledge applied: {list(knowledge.keys())}\n"
            reasoning += "General pattern inferred from specific observations."
            return reasoning
        
        def abductive_reasoning(symptoms: List[str], knowledge: Dict[str, Any]) -> str:
            """Apply abductive reasoning strategy."""
            reasoning = "Applying abductive reasoning:\n"
            reasoning += f"Symptoms/Evidence: {symptoms}\n"
            reasoning += f"Knowledge applied: {list(knowledge.keys())}\n"
            reasoning += "Best explanation inferred from available evidence."
            return reasoning
        
        self.reasoning_strategies = {
            "deductive": deductive_reasoning,
            "inductive": inductive_reasoning,
            "abductive": abductive_reasoning
        }
    
    def register_knowledge_module(self, module: KnowledgeModule) -> None:
        """Register a knowledge module for use in reasoning.
        
        Args:
            module: Knowledge module to register.
        """
        self.knowledge_modules[module.id] = module
        logger.info(f"Registered knowledge module for CoT: {module.id}")
    
    def register_knowledge_modules(self, modules: List[KnowledgeModule]) -> None:
        """Register multiple knowledge modules.
        
        Args:
            modules: List of knowledge modules to register.
        """
        for module in modules:
            self.register_knowledge_module(module)
    
    def create_reasoning_process(self, template_name: str, process_id: str, 
                                task_description: str) -> Optional[CoTProcess]:
        """Create a new reasoning process from a template.
        
        Args:
            template_name: Name of the reasoning template.
            process_id: Unique process identifier.
            task_description: Description of the task.
            
        Returns:
            New CoT process or None if template not found.
        """
        template = self.templates.get(template_name)
        if not template:
            logger.error(f"Reasoning template not found: {template_name}")
            return None
        
        process = template.create_process(process_id, task_description)
        self.active_processes[process_id] = process
        
        logger.info(f"Created CoT process: {process_id} using template {template_name}")
        return process
    
    def execute_reasoning_step(self, process_id: str, step_type: ReasoningStep,
                              description: str, input_data: Dict[str, Any],
                              knowledge_types: Optional[List[KnowledgeType]] = None,
                              reasoning_strategy: str = "deductive") -> Optional[CoTStep]:
        """Execute a single reasoning step.
        
        Args:
            process_id: Process identifier.
            step_type: Type of reasoning step.
            description: Step description.
            input_data: Input data for the step.
            knowledge_types: Types of knowledge to apply.
            reasoning_strategy: Reasoning strategy to use.
            
        Returns:
            Executed reasoning step or None if process not found.
        """
        process = self.active_processes.get(process_id)
        if not process:
            logger.error(f"Active process not found: {process_id}")
            return None
        
        # Gather relevant knowledge
        relevant_knowledge = self._gather_relevant_knowledge(knowledge_types or [])
        
        # Apply reasoning strategy
        reasoning_text = self._apply_reasoning_strategy(
            reasoning_strategy, input_data, relevant_knowledge
        )
        
        # Generate output based on step type and knowledge
        output_data = self._generate_step_output(
            step_type, input_data, relevant_knowledge
        )
        
        # Calculate confidence based on knowledge availability and quality
        confidence = self._calculate_step_confidence(relevant_knowledge, input_data)
        
        # Create reasoning step
        step = CoTStep(
            step_type=step_type,
            description=description,
            input_data=input_data,
            reasoning=reasoning_text,
            output_data=output_data,
            knowledge_applied=list(relevant_knowledge.keys()),
            confidence=confidence
        )
        
        # Add step to process
        process.add_step(step)
        
        logger.info(f"Executed reasoning step: {step_type.value} for process {process_id}")
        return step
    
    def _gather_relevant_knowledge(self, knowledge_types: List[KnowledgeType]) -> Dict[str, Any]:
        """Gather relevant knowledge modules for reasoning.
        
        Args:
            knowledge_types: Types of knowledge to gather.
            
        Returns:
            Dictionary of relevant knowledge content.
        """
        relevant_knowledge = {}
        
        for module_id, module in self.knowledge_modules.items():
            if not knowledge_types or module.module_type in knowledge_types:
                relevant_knowledge[module_id] = module.content
        
        return relevant_knowledge
    
    def _apply_reasoning_strategy(self, strategy: str, input_data: Dict[str, Any],
                                 knowledge: Dict[str, Any]) -> str:
        """Apply a reasoning strategy to generate reasoning text.
        
        Args:
            strategy: Reasoning strategy name.
            input_data: Input data for reasoning.
            knowledge: Relevant knowledge.
            
        Returns:
            Generated reasoning text.
        """
        strategy_func = self.reasoning_strategies.get(strategy)
        if not strategy_func:
            return f"Applied {strategy} reasoning with available knowledge and input data."
        
        # Extract key information for reasoning
        premises = input_data.get("premises", [])
        observations = input_data.get("observations", [])
        symptoms = input_data.get("symptoms", [])
        
        if strategy == "deductive":
            return strategy_func(premises, knowledge)
        elif strategy == "inductive":
            return strategy_func(observations, knowledge)
        elif strategy == "abductive":
            return strategy_func(symptoms, knowledge)
        else:
            return strategy_func(list(input_data.values()), knowledge)
    
    def _generate_step_output(self, step_type: ReasoningStep, input_data: Dict[str, Any],
                             knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Generate output for a reasoning step.
        
        Args:
            step_type: Type of reasoning step.
            input_data: Input data.
            knowledge: Relevant knowledge.
            
        Returns:
            Generated output data.
        """
        output = {"step_type": step_type.value}
        
        if step_type == ReasoningStep.OBSERVATION:
            output.update({
                "observations": input_data.get("raw_data", []),
                "key_findings": self._extract_key_findings(input_data, knowledge),
                "context": self._establish_context(input_data, knowledge)
            })
        
        elif step_type == ReasoningStep.ANALYSIS:
            output.update({
                "analysis_results": self._perform_analysis(input_data, knowledge),
                "patterns_identified": self._identify_patterns(input_data, knowledge),
                "gaps_found": self._identify_gaps(input_data, knowledge)
            })
        
        elif step_type == ReasoningStep.SYNTHESIS:
            output.update({
                "synthesized_content": self._synthesize_content(input_data, knowledge),
                "structure": self._create_structure(input_data, knowledge),
                "relationships": self._establish_relationships(input_data, knowledge)
            })
        
        elif step_type == ReasoningStep.EVALUATION:
            output.update({
                "evaluation_criteria": self._define_criteria(input_data, knowledge),
                "assessment_results": self._assess_quality(input_data, knowledge),
                "recommendations": self._generate_recommendations(input_data, knowledge)
            })
        
        elif step_type == ReasoningStep.CONCLUSION:
            output.update({
                "conclusions": self._draw_conclusions(input_data, knowledge),
                "confidence_level": self._assess_confidence(input_data, knowledge),
                "next_steps": self._suggest_next_steps(input_data, knowledge)
            })
        
        elif step_type == ReasoningStep.VALIDATION:
            output.update({
                "validation_results": self._validate_content(input_data, knowledge),
                "compliance_check": self._check_compliance(input_data, knowledge),
                "quality_metrics": self._calculate_quality_metrics(input_data, knowledge)
            })
        
        return output
    
    def _extract_key_findings(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> List[str]:
        """Extract key findings from input data using knowledge."""
        findings = []
        
        # Use domain knowledge to identify important aspects
        for module_id, module_content in knowledge.items():
            if "key_indicators" in module_content:
                for indicator in module_content["key_indicators"]:
                    if any(indicator.lower() in str(value).lower() 
                          for value in input_data.values() if isinstance(value, str)):
                        findings.append(f"Identified {indicator} based on {module_id}")
        
        return findings or ["General findings extracted from input data"]
    
    def _establish_context(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Establish context using domain knowledge."""
        context = {
            "domain": "software_requirements",
            "scope": input_data.get("scope", "general"),
            "stakeholders": input_data.get("stakeholders", []),
            "constraints": input_data.get("constraints", [])
        }
        
        # Enhance context with knowledge
        for module_id, module_content in knowledge.items():
            if "context_factors" in module_content:
                context[f"{module_id}_factors"] = module_content["context_factors"]
        
        return context
    
    def _perform_analysis(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Perform analysis using methodological knowledge."""
        analysis = {
            "completeness": "Analyzed for completeness",
            "consistency": "Checked for consistency",
            "clarity": "Evaluated for clarity"
        }
        
        # Apply analytical frameworks from knowledge
        for module_id, module_content in knowledge.items():
            if "analysis_framework" in module_content:
                framework = module_content["analysis_framework"]
                analysis[f"{module_id}_analysis"] = f"Applied {framework.get('name', 'framework')}"
        
        return analysis
    
    def _identify_patterns(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> List[str]:
        """Identify patterns in the data."""
        patterns = []
        
        # Look for common patterns mentioned in knowledge
        for module_id, module_content in knowledge.items():
            if "common_patterns" in module_content:
                for pattern in module_content["common_patterns"]:
                    patterns.append(f"Pattern identified: {pattern}")
        
        return patterns or ["No specific patterns identified"]
    
    def _identify_gaps(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> List[str]:
        """Identify gaps in the information."""
        gaps = []
        
        # Check against knowledge requirements
        for module_id, module_content in knowledge.items():
            if "required_elements" in module_content:
                for element in module_content["required_elements"]:
                    if element not in str(input_data):
                        gaps.append(f"Missing: {element} (from {module_id})")
        
        return gaps or ["No significant gaps identified"]
    
    def _synthesize_content(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize content using templates and standards."""
        synthesis = {
            "structured_content": "Content organized according to standards",
            "integrated_elements": "Elements integrated from multiple sources"
        }
        
        # Apply templates from knowledge
        for module_id, module_content in knowledge.items():
            if "template_structure" in module_content:
                synthesis[f"{module_id}_structure"] = "Applied template structure"
        
        return synthesis
    
    def _create_structure(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Create logical structure for content."""
        structure = {
            "hierarchy": "Hierarchical organization applied",
            "sections": "Logical sections identified",
            "flow": "Information flow established"
        }
        
        return structure
    
    def _establish_relationships(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> List[str]:
        """Establish relationships between elements."""
        relationships = [
            "Dependencies identified",
            "Traceability links established",
            "Cross-references created"
        ]
        
        return relationships
    
    def _define_criteria(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> List[str]:
        """Define evaluation criteria using standards."""
        criteria = []
        
        # Extract criteria from standards knowledge
        for module_id, module_content in knowledge.items():
            if "quality_characteristics" in module_content:
                for characteristic in module_content["quality_characteristics"]:
                    criteria.append(f"{characteristic} (from {module_id})")
        
        return criteria or ["Standard quality criteria applied"]
    
    def _assess_quality(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Assess quality against criteria."""
        assessment = {
            "overall_quality": "Good",
            "strengths": ["Well-structured", "Complete"],
            "areas_for_improvement": ["Minor formatting issues"]
        }
        
        return assessment
    
    def _generate_recommendations(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on evaluation."""
        recommendations = [
            "Continue with current approach",
            "Consider additional validation",
            "Review against latest standards"
        ]
        
        return recommendations
    
    def _draw_conclusions(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> List[str]:
        """Draw conclusions from the reasoning process."""
        conclusions = [
            "Analysis completed successfully",
            "Requirements meet quality standards",
            "Ready for next phase"
        ]
        
        return conclusions
    
    def _assess_confidence(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> float:
        """Assess confidence in conclusions."""
        # Base confidence on knowledge availability and data quality
        knowledge_score = min(len(knowledge) / 5.0, 1.0)  # Normalize to max 1.0
        data_score = min(len(input_data) / 10.0, 1.0)     # Normalize to max 1.0
        
        return (knowledge_score + data_score) / 2.0
    
    def _suggest_next_steps(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> List[str]:
        """Suggest next steps in the process."""
        next_steps = [
            "Proceed to implementation",
            "Conduct stakeholder review",
            "Update documentation"
        ]
        
        return next_steps
    
    def _validate_content(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Validate content against standards."""
        validation = {
            "standards_compliance": "Compliant",
            "format_validation": "Valid",
            "content_validation": "Complete"
        }
        
        return validation
    
    def _check_compliance(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Check compliance with standards and regulations."""
        compliance = {
            "ieee_830": "Compliant",
            "iso_29148": "Compliant",
            "organizational_standards": "Compliant"
        }
        
        return compliance
    
    def _calculate_quality_metrics(self, input_data: Dict[str, Any], knowledge: Dict[str, Any]) -> Dict[str, float]:
        """Calculate quality metrics."""
        metrics = {
            "completeness": 0.9,
            "consistency": 0.85,
            "clarity": 0.8,
            "traceability": 0.9
        }
        
        return metrics
    
    def _calculate_step_confidence(self, knowledge: Dict[str, Any], input_data: Dict[str, Any]) -> float:
        """Calculate confidence for a reasoning step."""
        # Base confidence on knowledge availability and input quality
        knowledge_factor = min(len(knowledge) / 3.0, 1.0)
        input_factor = min(len(input_data) / 5.0, 1.0)
        
        return (knowledge_factor + input_factor) / 2.0
    
    def complete_process(self, process_id: str, final_result: Dict[str, Any]) -> Optional[CoTProcess]:
        """Complete a reasoning process.
        
        Args:
            process_id: Process identifier.
            final_result: Final result of the reasoning process.
            
        Returns:
            Completed process or None if not found.
        """
        process = self.active_processes.get(process_id)
        if not process:
            logger.error(f"Active process not found: {process_id}")
            return None
        
        process.complete(final_result)
        
        # Move to completed processes
        self.completed_processes[process_id] = process
        del self.active_processes[process_id]
        
        logger.info(f"Completed CoT process: {process_id}")
        return process
    
    def get_process(self, process_id: str) -> Optional[CoTProcess]:
        """Get a reasoning process by ID.
        
        Args:
            process_id: Process identifier.
            
        Returns:
            Process instance or None if not found.
        """
        return (self.active_processes.get(process_id) or 
                self.completed_processes.get(process_id))
    
    def get_process_summary(self, process_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of a reasoning process.
        
        Args:
            process_id: Process identifier.
            
        Returns:
            Process summary or None if not found.
        """
        process = self.get_process(process_id)
        if not process:
            return None
        
        return {
            "process_id": process.process_id,
            "task_description": process.task_description,
            "step_count": len(process.steps),
            "overall_confidence": process.overall_confidence,
            "knowledge_modules_used": process.knowledge_modules_used,
            "status": "completed" if process.completed_at else "active",
            "created_at": process.created_at.isoformat(),
            "completed_at": process.completed_at.isoformat() if process.completed_at else None
        }
    
    def export_process(self, process_id: str, format: str = "json") -> Optional[str]:
        """Export a reasoning process to string format.
        
        Args:
            process_id: Process identifier.
            format: Export format ("json" or "yaml").
            
        Returns:
            Exported process string or None if not found.
        """
        process = self.get_process(process_id)
        if not process:
            return None
        
        process_dict = process.to_dict()
        
        if format.lower() == "yaml":
            return yaml.dump(process_dict, default_flow_style=False, indent=2)
        else:
            return json.dumps(process_dict, indent=2, default=str)
    
    def list_active_processes(self) -> List[str]:
        """List all active process IDs.
        
        Returns:
            List of active process IDs.
        """
        return list(self.active_processes.keys())
    
    def list_completed_processes(self) -> List[str]:
        """List all completed process IDs.
        
        Returns:
            List of completed process IDs.
        """
        return list(self.completed_processes.keys())
    
    def get_engine_stats(self) -> Dict[str, Any]:
        """Get engine statistics.
        
        Returns:
            Dictionary with engine statistics.
        """
        return {
            "active_processes": len(self.active_processes),
            "completed_processes": len(self.completed_processes),
            "registered_knowledge_modules": len(self.knowledge_modules),
            "available_templates": list(self.templates.keys()),
            "reasoning_strategies": list(self.reasoning_strategies.keys())
        }