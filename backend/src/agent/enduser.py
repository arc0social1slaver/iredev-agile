"""
EndUser Agent for iReDev framework.
Simulates end users to generate user personas, scenarios, and non-functional requirements.
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import logging
import uuid

from .knowledge_driven_agent import KnowledgeDrivenAgent
from ..knowledge.base_types import KnowledgeType
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus, ArtifactMetadata
from ..orchestrator.orchestrator import Task
import asyncio


logger = logging.getLogger(__name__)


@dataclass
class UserPersona:
    """Represents a user persona with characteristics and goals."""

    id: str
    name: str
    role: str
    demographics: Dict[str, Any]
    goals: List[str]
    pain_points: List[str]
    technical_proficiency: str  # beginner, intermediate, advanced
    context_of_use: str
    motivations: List[str]
    frustrations: List[str]
    preferred_interaction_style: str
    accessibility_needs: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert persona to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "demographics": self.demographics,
            "goals": self.goals,
            "pain_points": self.pain_points,
            "technical_proficiency": self.technical_proficiency,
            "context_of_use": self.context_of_use,
            "motivations": self.motivations,
            "frustrations": self.frustrations,
            "preferred_interaction_style": self.preferred_interaction_style,
            "accessibility_needs": self.accessibility_needs,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class UserScenario:
    """Represents a user scenario or use case."""

    id: str
    persona_id: str
    title: str
    description: str
    context: str
    preconditions: List[str]
    steps: List[str]
    expected_outcome: str
    success_criteria: List[str]
    frequency: str  # daily, weekly, monthly, rarely
    importance: str  # critical, high, medium, low
    complexity: str  # simple, moderate, complex
    environment: str  # office, home, mobile, public
    time_constraints: Optional[str] = None
    error_scenarios: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert scenario to dictionary."""
        return {
            "id": self.id,
            "persona_id": self.persona_id,
            "title": self.title,
            "description": self.description,
            "context": self.context,
            "preconditions": self.preconditions,
            "steps": self.steps,
            "expected_outcome": self.expected_outcome,
            "success_criteria": self.success_criteria,
            "frequency": self.frequency,
            "importance": self.importance,
            "complexity": self.complexity,
            "environment": self.environment,
            "time_constraints": self.time_constraints,
            "error_scenarios": self.error_scenarios,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class PainPoint:
    """Represents a user pain point or problem."""

    id: str
    persona_id: str
    scenario_id: Optional[str]
    title: str
    description: str
    category: str  # usability, performance, functionality, accessibility
    severity: str  # critical, high, medium, low
    frequency: str  # always, often, sometimes, rarely
    impact: str  # blocks_task, slows_task, frustrates_user, minor_annoyance
    current_workaround: Optional[str] = None
    suggested_solution: Optional[str] = None
    business_impact: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert pain point to dictionary."""
        return {
            "id": self.id,
            "persona_id": self.persona_id,
            "scenario_id": self.scenario_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
            "frequency": self.frequency,
            "impact": self.impact,
            "current_workaround": self.current_workaround,
            "suggested_solution": self.suggested_solution,
            "business_impact": self.business_impact,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class NonFunctionalRequirement:
    """Represents a non-functional requirement."""

    id: str
    category: str  # performance, security, usability, reliability, scalability, etc.
    title: str
    description: str
    rationale: str
    priority: str  # critical, high, medium, low
    measurable_criteria: List[str]
    acceptance_criteria: List[str]
    source_personas: List[str]
    source_scenarios: List[str]
    constraints: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert NFR to dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "priority": self.priority,
            "measurable_criteria": self.measurable_criteria,
            "acceptance_criteria": self.acceptance_criteria,
            "source_personas": self.source_personas,
            "source_scenarios": self.source_scenarios,
            "constraints": self.constraints,
            "assumptions": self.assumptions,
            "risks": self.risks,
            "created_at": self.created_at.isoformat(),
        }


class EndUserAgent(KnowledgeDrivenAgent):
    """
    EndUser Agent for simulating end users and generating user-centered requirements.

    Integrates user experience design knowledge, persona modeling techniques,
    and scenario-based requirement elicitation.
    """

    def __init__(self, config_path: Optional[str] = None, **kwargs):
        # Define required knowledge modules for end user agent
        knowledge_modules = [
            "user_experience_design",
            "persona_modeling",
            "scenario_based_design",
            "accessibility_guidelines",
            "usability_principles",
            "user_research_methods",
        ]

        super().__init__(
            name="enduser",
            knowledge_modules=knowledge_modules,
            config_path=config_path,
            **kwargs,
        )

        # Agent configuration
        self.max_personas_per_domain = self.config.get("max_personas_per_domain", 5)
        self.max_scenarios_per_persona = self.config.get("max_scenarios_per_persona", 8)
        self.nfr_categories = self.config.get(
            "nfr_categories",
            [
                "performance",
                "security",
                "usability",
                "reliability",
                "scalability",
                "accessibility",
                "maintainability",
            ],
        )

        # Agent state
        self.personas_created: Dict[str, UserPersona] = {}
        self.scenarios_created: Dict[str, UserScenario] = {}
        self.pain_points_identified: Dict[str, PainPoint] = {}
        self.nfrs_generated: Dict[str, NonFunctionalRequirement] = {}

        # Initialize profile prompt
        self.profile_prompt = self._create_profile_prompt()
        # self.add_to_memory("system", self.profile_prompt)

        logger.info(
            f"Initialized EndUserAgent with {len(knowledge_modules)} knowledge modules"
        )

    def _create_profile_prompt(self) -> str:
        """Create profile prompt for the end user agent."""
        return """You are a simulated END USER of the target system being discussed. 
You are NOT a developer, business owner, or product manager.
You are simply a regular stakeholder using the system in daily life.

Mission:
Provide authentic goals, frustrations, expectations, and feedback 
in a natural, conversational way — as if you are a real person 
using this system.

Persona Rules:
- Adapt your role dynamically to the system context.
- Never sound like IT staff or management.  
- Your knowledge is limited to everyday user experiences.  

Communication Style:
- Use plain, everyday language.  
- Mention frustrations casually (e.g., "it feels slow", "too many steps").  
- Avoid technical jargon or acronyms unless the interviewer explicitly asks.  
- Sometimes share small anecdotes from daily experience.  
- Vary tone to sound natural. 
"""

    def _get_action_prompt(self, action: str, context: Dict[str, Any] = None) -> str:
        """Get action-specific prompt for a given action."""
        action_prompts = {
            "create_personas": """Action: Create user personas based on domain and context.

Context:
- Domain: {domain}
- Business context: {business_context}
- Target users: {target_users}

Instructions:
1. Identify distinct user types for this domain.
2. For each persona, define: name, role, demographics, goals, pain points, technical proficiency, context of use.
3. Ensure diversity in personas (primary, secondary, edge cases).
4. Base personas on interview data and domain knowledge.
""",
            "generate_scenarios": """Action: Generate user scenarios for personas.

Context:
- Persona: {persona_name}
- System context: {system_context}
- Persona characteristics: {persona_characteristics}

Instructions:
1. Create realistic scenarios covering typical usage patterns.
2. Include: title, description, context, preconditions, steps, expected outcome, success criteria.
3. Consider frequency, importance, and complexity.
4. Cover both happy paths and error scenarios.
""",
            "identify_pain_points": """Action: Identify user pain points from scenarios.

Context:
- Persona: {persona_name}
- Scenarios: {scenarios}
- Current system: {current_system}

Instructions:
1. Analyze scenarios to identify friction points and frustrations.
2. Categorize pain points: usability, performance, functionality, accessibility.
3. Assess severity, frequency, and impact.
4. Suggest solutions where possible.
""",
            "define_nfrs": """Action: Define non-functional requirements from user analysis.

Context:
- Category: {category}
- Relevant scenarios: {scenarios}
- Relevant pain points: {pain_points}

Instructions:
1. Derive measurable NFRs from scenarios and pain points.
2. Define acceptance criteria and measurable criteria.
3. Link NFRs to source personas and scenarios.
4. Prioritize based on user impact.
""",
            "interviewer_asking": """Action: Answer the question as this stakeholder would, but structure your response in the form of user stories. 

Context:
- Question from interviewer: {msg}

HOW TO EXPRESS USER STORIES NATURALLY:

1. DIRECT USER STORY FORMAT (use when describing a need):
   "As a [your_role], I want [specific_functionality] so that [business_benefit]."

2. IMPLIED USER STORY (use when describing what you need):
   "I need to [accomplish_something] so that [benefit]."

3. SYSTEM REQUIREMENT (use when describing what the system should do):
   "The system should [capability] because [reason]."

4. PAIN POINT AS STORY (use when describing current problems):
   "Currently, I have to [manual_process] which is frustrating because [problem]."

5. QUALITY EXPECTATION (use when describing non-functional needs):
   "The system needs to be [quality_attribute] because [reason]."

RESPONSE GUIDELINES:
- Be conversational and authentic to your role
- Sprinkle user stories naturally throughout your responses
- Don't list requirements mechanically - weave them into conversation
- Use specific examples from your work context
- Show emotion when discussing pain points

RESPONSE FORMAT:
[Your response]

Remember: Just respond - don't label your response or add markers. You are not an AI assistant. Answer as this person would in a real conversation, but frame your needs as user stories.
""",
        }

        base_prompt = action_prompts.get(action, f"Action: {action}")
        if context:
            try:
                return base_prompt.format(**context)
            except:
                return base_prompt
        return base_prompt

    def create_user_personas(
        self, domain: str, context: Dict[str, Any]
    ) -> List[UserPersona]:
        """
        Create user personas based on domain and context information.

        Args:
            domain: Business domain (e.g., 'healthcare', 'finance', 'education')
            context: Context information including business objectives, target users, etc.

        Returns:
            List of generated user personas
        """
        logger.info(f"Creating user personas for domain: {domain}")

        # Apply user experience design knowledge
        ux_methodology = self.apply_methodology("persona_creation")

        # Generate personas using CoT reasoning with action prompt
        action_prompt = self._get_action_prompt(
            "create_personas",
            context={
                "domain": domain,
                "business_context": context,
                "target_users": context.get("target_users", []),
            },
        )

        cot_result = self.generate_with_cot(
            prompt=action_prompt,
            context={
                "domain": domain,
                "business_context": context,
                "methodology_guide": ux_methodology,
                "max_personas": self.max_personas_per_domain,
            },
            reasoning_template="persona_modeling",
        )

        # Parse the generated personas
        personas = self._parse_personas_from_response(
            cot_result["response"], domain, context
        )

        # Store personas
        for persona in personas:
            self.personas_created[persona.id] = persona

        # Create artifact for personas
        if self.event_bus and self.session_id:
            artifact = self._create_personas_artifact(personas, domain, context)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id,
            )

        logger.info(f"Created {len(personas)} user personas for domain: {domain}")
        return personas

    def generate_user_scenarios(
        self, personas: List[UserPersona], system_context: Dict[str, Any]
    ) -> List[UserScenario]:
        """
        Generate user scenarios based on personas and system context.

        Args:
            personas: List of user personas
            system_context: System context including features, constraints, etc.

        Returns:
            List of generated user scenarios
        """
        logger.info(f"Generating user scenarios for {len(personas)} personas")

        all_scenarios = []

        for persona in personas:
            # Apply scenario-based design methodology
            scenario_methodology = self.apply_methodology("scenario_generation")

            # Generate scenarios for this persona using CoT reasoning with action prompt
            action_prompt = self._get_action_prompt(
                "generate_scenarios",
                context={
                    "persona_name": persona.name,
                    "system_context": system_context,
                    "persona_characteristics": persona.to_dict(),
                },
            )

            cot_result = self.generate_with_cot(
                prompt=action_prompt,
                context={
                    "persona": persona.to_dict(),
                    "system_context": system_context,
                    "methodology_guide": scenario_methodology,
                    "max_scenarios": self.max_scenarios_per_persona,
                },
                reasoning_template="scenario_generation",
            )

            # Parse scenarios from response
            persona_scenarios = self._parse_scenarios_from_response(
                cot_result["response"], persona.id, system_context
            )

            all_scenarios.extend(persona_scenarios)

        # Store scenarios
        for scenario in all_scenarios:
            self.scenarios_created[scenario.id] = scenario

        # Create artifact for scenarios
        if self.event_bus and self.session_id:
            artifact = self._create_scenarios_artifact(all_scenarios, system_context)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id,
            )

        logger.info(f"Generated {len(all_scenarios)} user scenarios")
        return all_scenarios

    def identify_pain_points(
        self,
        scenarios: List[UserScenario],
        current_system_info: Optional[Dict[str, Any]] = None,
    ) -> List[PainPoint]:
        """
        Identify user pain points from scenarios and current system analysis.

        Args:
            scenarios: List of user scenarios
            current_system_info: Optional information about current system limitations

        Returns:
            List of identified pain points
        """
        logger.info(f"Identifying pain points from {len(scenarios)} scenarios")

        all_pain_points = []

        # Apply user research methodology for pain point identification
        research_methodology = self.apply_methodology("pain_point_analysis")

        # Group scenarios by persona for analysis
        scenarios_by_persona = {}
        for scenario in scenarios:
            if scenario.persona_id not in scenarios_by_persona:
                scenarios_by_persona[scenario.persona_id] = []
            scenarios_by_persona[scenario.persona_id].append(scenario)

        # Analyze pain points for each persona
        for persona_id, persona_scenarios in scenarios_by_persona.items():
            persona = self.personas_created.get(persona_id)
            if not persona:
                continue

            # Generate pain points using CoT reasoning with action prompt
            action_prompt = self._get_action_prompt(
                "identify_pain_points",
                context={
                    "persona_name": persona.name,
                    "scenarios": [s.to_dict() for s in persona_scenarios],
                    "current_system": current_system_info or {},
                },
            )

            cot_result = self.generate_with_cot(
                prompt=action_prompt,
                context={
                    "persona": persona.to_dict(),
                    "scenarios": [s.to_dict() for s in persona_scenarios],
                    "current_system": current_system_info or {},
                    "methodology_guide": research_methodology,
                },
                reasoning_template="pain_point_analysis",
            )

            # Parse pain points from response
            persona_pain_points = self._parse_pain_points_from_response(
                cot_result["response"], persona_id, persona_scenarios
            )

            all_pain_points.extend(persona_pain_points)

        # Store pain points
        for pain_point in all_pain_points:
            self.pain_points_identified[pain_point.id] = pain_point

        # Create artifact for pain points
        if self.event_bus and self.session_id:
            artifact = self._create_pain_points_artifact(all_pain_points)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id,
            )

        logger.info(f"Identified {len(all_pain_points)} pain points")
        return all_pain_points

    def define_non_functional_requirements(
        self,
        scenarios: List[UserScenario],
        pain_points: List[PainPoint],
        system_constraints: Optional[Dict[str, Any]] = None,
    ) -> List[NonFunctionalRequirement]:
        """
        Generate non-functional requirements based on user scenarios and pain points.

        Args:
            scenarios: List of user scenarios
            pain_points: List of identified pain points
            system_constraints: Optional system constraints and context

        Returns:
            List of generated non-functional requirements
        """
        logger.info(
            f"Generating NFRs from {len(scenarios)} scenarios and {len(pain_points)} pain points"
        )

        all_nfrs = []

        # Apply NFR elicitation methodology
        nfr_methodology = self.apply_methodology("nfr_elicitation")

        # Generate NFRs for each category
        for category in self.nfr_categories:
            # Filter relevant scenarios and pain points for this category
            relevant_scenarios = self._filter_scenarios_for_nfr_category(
                scenarios, category
            )
            relevant_pain_points = self._filter_pain_points_for_nfr_category(
                pain_points, category
            )

            if not relevant_scenarios and not relevant_pain_points:
                continue

            # Generate NFRs for this category using CoT reasoning with action prompt
            action_prompt = self._get_action_prompt(
                "define_nfrs",
                context={
                    "category": category,
                    "scenarios": [s.to_dict() for s in relevant_scenarios],
                    "pain_points": [p.to_dict() for p in relevant_pain_points],
                },
            )

            cot_result = self.generate_with_cot(
                prompt=action_prompt,
                context={
                    "category": category,
                    "relevant_scenarios": [s.to_dict() for s in relevant_scenarios],
                    "relevant_pain_points": [p.to_dict() for p in relevant_pain_points],
                    "system_constraints": system_constraints or {},
                    "methodology_guide": nfr_methodology,
                },
                reasoning_template="nfr_generation",
            )

            # Parse NFRs from response
            category_nfrs = self._parse_nfrs_from_response(
                cot_result["response"],
                category,
                relevant_scenarios,
                relevant_pain_points,
            )

            all_nfrs.extend(category_nfrs)

        # Store NFRs
        for nfr in all_nfrs:
            self.nfrs_generated[nfr.id] = nfr

        # Create artifact for NFRs
        if self.event_bus and self.session_id:
            artifact = self._create_nfrs_artifact(all_nfrs, system_constraints)
            self.event_bus.publish_artifact_created(
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                source=self.name,
                session_id=self.session_id,
            )

        logger.info(f"Generated {len(all_nfrs)} non-functional requirements")
        return all_nfrs

    def _parse_personas_from_response(
        self, response: str, domain: str, context: Dict[str, Any]
    ) -> List[UserPersona]:
        """Parse user personas from LLM response."""
        personas = []

        # Simple parsing - in production, this would be more sophisticated
        lines = response.split("\n")
        current_persona = {}

        for line in lines:
            line = line.strip()
            if line.startswith("PERSONA:") or line.startswith("Name:"):
                if current_persona:
                    persona = self._create_persona_from_dict(current_persona, domain)
                    if persona:
                        personas.append(persona)
                current_persona = {"name": line.split(":", 1)[1].strip()}
            elif line.startswith("Role:"):
                current_persona["role"] = line.split(":", 1)[1].strip()
            elif line.startswith("Demographics:"):
                current_persona["demographics"] = line.split(":", 1)[1].strip()
            elif line.startswith("Goals:"):
                current_persona["goals"] = line.split(":", 1)[1].strip()
            elif line.startswith("Pain Points:"):
                current_persona["pain_points"] = line.split(":", 1)[1].strip()
            elif line.startswith("Technical Proficiency:"):
                current_persona["technical_proficiency"] = line.split(":", 1)[1].strip()

        # Handle last persona
        if current_persona:
            persona = self._create_persona_from_dict(current_persona, domain)
            if persona:
                personas.append(persona)

        # If parsing failed, create default personas
        if not personas:
            personas = self._create_default_personas(domain, context)

        return personas[: self.max_personas_per_domain]

    def _create_persona_from_dict(
        self, persona_dict: Dict[str, Any], domain: str
    ) -> Optional[UserPersona]:
        """Create UserPersona object from parsed dictionary."""
        try:
            return UserPersona(
                id=str(uuid.uuid4()),
                name=persona_dict.get("name", "Unknown User"),
                role=persona_dict.get("role", "End User"),
                demographics=self._parse_demographics(
                    persona_dict.get("demographics", "")
                ),
                goals=self._parse_list_field(persona_dict.get("goals", "")),
                pain_points=self._parse_list_field(persona_dict.get("pain_points", "")),
                technical_proficiency=persona_dict.get(
                    "technical_proficiency", "intermediate"
                ),
                context_of_use=f"{domain} domain usage",
                motivations=self._parse_list_field(persona_dict.get("motivations", "")),
                frustrations=self._parse_list_field(
                    persona_dict.get("frustrations", "")
                ),
                preferred_interaction_style=persona_dict.get(
                    "interaction_style", "intuitive"
                ),
                accessibility_needs=self._parse_list_field(
                    persona_dict.get("accessibility_needs", "")
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to create persona from dict: {e}")
            return None

    def _parse_demographics(self, demographics_str: str) -> Dict[str, Any]:
        """Parse demographics string into structured data."""
        demographics = {}
        if demographics_str:
            # Simple parsing - could be enhanced
            parts = demographics_str.split(",")
            for part in parts:
                if ":" in part:
                    key, value = part.split(":", 1)
                    demographics[key.strip()] = value.strip()
        return demographics

    def _parse_list_field(self, field_str: str) -> List[str]:
        """Parse comma-separated string into list."""
        if not field_str:
            return []
        return [item.strip() for item in field_str.split(",") if item.strip()]

    def _create_default_personas(
        self, domain: str, context: Dict[str, Any]
    ) -> List[UserPersona]:
        """Create default personas when parsing fails."""
        return [
            UserPersona(
                id=str(uuid.uuid4()),
                name="Primary User",
                role="Main System User",
                demographics={"experience": "intermediate"},
                goals=["Complete tasks efficiently", "Access information quickly"],
                pain_points=["System complexity", "Slow response times"],
                technical_proficiency="intermediate",
                context_of_use=f"{domain} domain",
                motivations=["Productivity", "Ease of use"],
                frustrations=["Technical difficulties", "Unclear interfaces"],
                preferred_interaction_style="intuitive",
            ),
            UserPersona(
                id=str(uuid.uuid4()),
                name="Power User",
                role="Advanced System User",
                demographics={"experience": "advanced"},
                goals=["Maximize system capabilities", "Customize workflows"],
                pain_points=["Limited customization", "Missing advanced features"],
                technical_proficiency="advanced",
                context_of_use=f"{domain} domain",
                motivations=["Efficiency", "Control"],
                frustrations=["System limitations", "Lack of flexibility"],
                preferred_interaction_style="detailed",
            ),
        ]

    def _parse_scenarios_from_response(
        self, response: str, persona_id: str, system_context: Dict[str, Any]
    ) -> List[UserScenario]:
        """Parse user scenarios from LLM response."""
        scenarios = []

        # Simple parsing logic
        lines = response.split("\n")
        current_scenario = {}

        for line in lines:
            line = line.strip()
            if line.startswith("SCENARIO:") or line.startswith("Title:"):
                if current_scenario:
                    scenario = self._create_scenario_from_dict(
                        current_scenario, persona_id
                    )
                    if scenario:
                        scenarios.append(scenario)
                current_scenario = {"title": line.split(":", 1)[1].strip()}
            elif line.startswith("Description:"):
                current_scenario["description"] = line.split(":", 1)[1].strip()
            elif line.startswith("Context:"):
                current_scenario["context"] = line.split(":", 1)[1].strip()
            elif line.startswith("Steps:"):
                current_scenario["steps"] = line.split(":", 1)[1].strip()
            elif line.startswith("Expected Outcome:"):
                current_scenario["expected_outcome"] = line.split(":", 1)[1].strip()
            elif line.startswith("Frequency:"):
                current_scenario["frequency"] = line.split(":", 1)[1].strip()
            elif line.startswith("Importance:"):
                current_scenario["importance"] = line.split(":", 1)[1].strip()

        # Handle last scenario
        if current_scenario:
            scenario = self._create_scenario_from_dict(current_scenario, persona_id)
            if scenario:
                scenarios.append(scenario)

        # Create default scenarios if parsing failed
        if not scenarios:
            scenarios = self._create_default_scenarios(persona_id, system_context)

        return scenarios[: self.max_scenarios_per_persona]

    def _create_scenario_from_dict(
        self, scenario_dict: Dict[str, Any], persona_id: str
    ) -> Optional[UserScenario]:
        """Create UserScenario object from parsed dictionary."""
        try:
            return UserScenario(
                id=str(uuid.uuid4()),
                persona_id=persona_id,
                title=scenario_dict.get("title", "User Task"),
                description=scenario_dict.get("description", "User performs a task"),
                context=scenario_dict.get("context", "Normal usage context"),
                preconditions=self._parse_list_field(
                    scenario_dict.get("preconditions", "")
                ),
                steps=self._parse_list_field(scenario_dict.get("steps", "")),
                expected_outcome=scenario_dict.get(
                    "expected_outcome", "Task completed successfully"
                ),
                success_criteria=self._parse_list_field(
                    scenario_dict.get("success_criteria", "")
                ),
                frequency=scenario_dict.get("frequency", "weekly"),
                importance=scenario_dict.get("importance", "medium"),
                complexity=scenario_dict.get("complexity", "moderate"),
                environment=scenario_dict.get("environment", "office"),
            )
        except Exception as e:
            logger.warning(f"Failed to create scenario from dict: {e}")
            return None

    def _create_default_scenarios(
        self, persona_id: str, system_context: Dict[str, Any]
    ) -> List[UserScenario]:
        """Create default scenarios when parsing fails."""
        return [
            UserScenario(
                id=str(uuid.uuid4()),
                persona_id=persona_id,
                title="Basic System Access",
                description="User logs in and accesses main functionality",
                context="Daily work routine",
                preconditions=["User has valid credentials"],
                steps=[
                    "Login to system",
                    "Navigate to main dashboard",
                    "Access required features",
                ],
                expected_outcome="User successfully accesses system functionality",
                success_criteria=[
                    "Login successful",
                    "Dashboard loads",
                    "Features accessible",
                ],
                frequency="daily",
                importance="high",
                complexity="simple",
                environment="office",
            )
        ]

    def _parse_pain_points_from_response(
        self, response: str, persona_id: str, scenarios: List[UserScenario]
    ) -> List[PainPoint]:
        """Parse pain points from LLM response."""
        pain_points = []

        # Simple parsing logic
        lines = response.split("\n")
        current_pain_point = {}

        for line in lines:
            line = line.strip()
            if line.startswith("PAIN POINT:") or line.startswith("Title:"):
                if current_pain_point:
                    pain_point = self._create_pain_point_from_dict(
                        current_pain_point, persona_id
                    )
                    if pain_point:
                        pain_points.append(pain_point)
                current_pain_point = {"title": line.split(":", 1)[1].strip()}
            elif line.startswith("Description:"):
                current_pain_point["description"] = line.split(":", 1)[1].strip()
            elif line.startswith("Category:"):
                current_pain_point["category"] = line.split(":", 1)[1].strip()
            elif line.startswith("Severity:"):
                current_pain_point["severity"] = line.split(":", 1)[1].strip()
            elif line.startswith("Frequency:"):
                current_pain_point["frequency"] = line.split(":", 1)[1].strip()
            elif line.startswith("Impact:"):
                current_pain_point["impact"] = line.split(":", 1)[1].strip()

        # Handle last pain point
        if current_pain_point:
            pain_point = self._create_pain_point_from_dict(
                current_pain_point, persona_id
            )
            if pain_point:
                pain_points.append(pain_point)

        return pain_points

    def _create_pain_point_from_dict(
        self, pain_point_dict: Dict[str, Any], persona_id: str
    ) -> Optional[PainPoint]:
        """Create PainPoint object from parsed dictionary."""
        try:
            return PainPoint(
                id=str(uuid.uuid4()),
                persona_id=persona_id,
                scenario_id=None,  # Could be linked to specific scenarios
                title=pain_point_dict.get("title", "User Frustration"),
                description=pain_point_dict.get(
                    "description", "User experiences difficulty"
                ),
                category=pain_point_dict.get("category", "usability"),
                severity=pain_point_dict.get("severity", "medium"),
                frequency=pain_point_dict.get("frequency", "sometimes"),
                impact=pain_point_dict.get("impact", "frustrates_user"),
                current_workaround=pain_point_dict.get("workaround"),
                suggested_solution=pain_point_dict.get("solution"),
                business_impact=pain_point_dict.get("business_impact"),
            )
        except Exception as e:
            logger.warning(f"Failed to create pain point from dict: {e}")
            return None

    def _filter_scenarios_for_nfr_category(
        self, scenarios: List[UserScenario], category: str
    ) -> List[UserScenario]:
        """Filter scenarios relevant to a specific NFR category."""
        relevant_scenarios = []

        category_keywords = {
            "performance": ["fast", "quick", "speed", "response", "load", "time"],
            "security": ["secure", "private", "confidential", "protect", "auth"],
            "usability": ["easy", "intuitive", "user-friendly", "simple", "clear"],
            "reliability": ["reliable", "stable", "available", "uptime", "error"],
            "scalability": ["scale", "growth", "volume", "concurrent", "load"],
            "accessibility": ["accessible", "disability", "screen reader", "keyboard"],
            "maintainability": ["maintain", "update", "modify", "extend", "debug"],
        }

        keywords = category_keywords.get(category, [])

        for scenario in scenarios:
            scenario_text = f"{scenario.description} {scenario.context} {' '.join(scenario.steps)}".lower()
            if any(keyword in scenario_text for keyword in keywords):
                relevant_scenarios.append(scenario)

        return relevant_scenarios

    def _filter_pain_points_for_nfr_category(
        self, pain_points: List[PainPoint], category: str
    ) -> List[PainPoint]:
        """Filter pain points relevant to a specific NFR category."""
        relevant_pain_points = []

        for pain_point in pain_points:
            if pain_point.category == category:
                relevant_pain_points.append(pain_point)

        return relevant_pain_points

    def _parse_nfrs_from_response(
        self,
        response: str,
        category: str,
        scenarios: List[UserScenario],
        pain_points: List[PainPoint],
    ) -> List[NonFunctionalRequirement]:
        """Parse non-functional requirements from LLM response."""
        nfrs = []

        # Simple parsing logic
        lines = response.split("\n")
        current_nfr = {}

        for line in lines:
            line = line.strip()
            if line.startswith("NFR:") or line.startswith("Title:"):
                if current_nfr:
                    nfr = self._create_nfr_from_dict(
                        current_nfr, category, scenarios, pain_points
                    )
                    if nfr:
                        nfrs.append(nfr)
                current_nfr = {"title": line.split(":", 1)[1].strip()}
            elif line.startswith("Description:"):
                current_nfr["description"] = line.split(":", 1)[1].strip()
            elif line.startswith("Rationale:"):
                current_nfr["rationale"] = line.split(":", 1)[1].strip()
            elif line.startswith("Priority:"):
                current_nfr["priority"] = line.split(":", 1)[1].strip()
            elif line.startswith("Measurable Criteria:"):
                current_nfr["measurable_criteria"] = line.split(":", 1)[1].strip()
            elif line.startswith("Acceptance Criteria:"):
                current_nfr["acceptance_criteria"] = line.split(":", 1)[1].strip()

        # Handle last NFR
        if current_nfr:
            nfr = self._create_nfr_from_dict(
                current_nfr, category, scenarios, pain_points
            )
            if nfr:
                nfrs.append(nfr)

        # Create default NFR if parsing failed
        if not nfrs:
            nfrs = self._create_default_nfrs(category, scenarios, pain_points)

        return nfrs

    def _create_nfr_from_dict(
        self,
        nfr_dict: Dict[str, Any],
        category: str,
        scenarios: List[UserScenario],
        pain_points: List[PainPoint],
    ) -> Optional[NonFunctionalRequirement]:
        """Create NonFunctionalRequirement object from parsed dictionary."""
        try:
            return NonFunctionalRequirement(
                id=str(uuid.uuid4()),
                category=category,
                title=nfr_dict.get("title", f"{category.title()} Requirement"),
                description=nfr_dict.get(
                    "description", f"System must meet {category} standards"
                ),
                rationale=nfr_dict.get(
                    "rationale", f"Required for {category} compliance"
                ),
                priority=nfr_dict.get("priority", "medium"),
                measurable_criteria=self._parse_list_field(
                    nfr_dict.get("measurable_criteria", "")
                ),
                acceptance_criteria=self._parse_list_field(
                    nfr_dict.get("acceptance_criteria", "")
                ),
                source_personas=[s.persona_id for s in scenarios],
                source_scenarios=[s.id for s in scenarios],
                constraints=self._parse_list_field(nfr_dict.get("constraints", "")),
                assumptions=self._parse_list_field(nfr_dict.get("assumptions", "")),
                risks=self._parse_list_field(nfr_dict.get("risks", "")),
            )
        except Exception as e:
            logger.warning(f"Failed to create NFR from dict: {e}")
            return None

    def _create_default_nfrs(
        self, category: str, scenarios: List[UserScenario], pain_points: List[PainPoint]
    ) -> List[NonFunctionalRequirement]:
        """Create default NFRs when parsing fails."""
        default_nfrs = {
            "performance": NonFunctionalRequirement(
                id=str(uuid.uuid4()),
                category="performance",
                title="System Response Time",
                description="System must respond to user actions within acceptable time limits",
                rationale="Users expect fast response times for good user experience",
                priority="high",
                measurable_criteria=["Response time < 2 seconds for 95% of requests"],
                acceptance_criteria=[
                    "Page loads within 2 seconds",
                    "Search results appear within 1 second",
                ],
                source_personas=[s.persona_id for s in scenarios],
                source_scenarios=[s.id for s in scenarios],
            ),
            "usability": NonFunctionalRequirement(
                id=str(uuid.uuid4()),
                category="usability",
                title="User Interface Usability",
                description="System must be intuitive and easy to use",
                rationale="Users need to complete tasks efficiently without extensive training",
                priority="high",
                measurable_criteria=[
                    "Task completion rate > 90%",
                    "User satisfaction score > 4/5",
                ],
                acceptance_criteria=[
                    "New users can complete basic tasks within 5 minutes"
                ],
                source_personas=[s.persona_id for s in scenarios],
                source_scenarios=[s.id for s in scenarios],
            ),
            "security": NonFunctionalRequirement(
                id=str(uuid.uuid4()),
                category="security",
                title="Data Security",
                description="System must protect user data and maintain confidentiality",
                rationale="User data must be protected from unauthorized access",
                priority="critical",
                measurable_criteria=[
                    "Zero data breaches",
                    "All data encrypted in transit and at rest",
                ],
                acceptance_criteria=[
                    "User authentication required",
                    "Data access logged",
                ],
                source_personas=[s.persona_id for s in scenarios],
                source_scenarios=[s.id for s in scenarios],
            ),
        }

        return [default_nfrs.get(category)] if category in default_nfrs else []

    def _create_personas_artifact(
        self, personas: List[UserPersona], domain: str, context: Dict[str, Any]
    ) -> Artifact:
        """Create artifact for user personas."""
        artifact_content = {
            "domain": domain,
            "context": context,
            "personas": [persona.to_dict() for persona in personas],
            "generation_metadata": {
                "agent": self.name,
                "timestamp": datetime.now().isoformat(),
                "methodology_applied": "persona_modeling",
                "total_personas": len(personas),
            },
        }

        metadata = ArtifactMetadata(
            tags=["personas", "user_modeling", domain],
            source_agent=self.name,
            custom_properties={
                "name": f"User Personas - {domain}",
                "description": f"Generated user personas for {domain} domain",
            },
        )

        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.USER_PERSONAS,
            content=artifact_content,
            metadata=metadata,
            version="1.0.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT,
        )

    def _create_scenarios_artifact(
        self, scenarios: List[UserScenario], system_context: Dict[str, Any]
    ) -> Artifact:
        """Create artifact for user scenarios."""
        artifact_content = {
            "system_context": system_context,
            "scenarios": [scenario.to_dict() for scenario in scenarios],
            "generation_metadata": {
                "agent": self.name,
                "timestamp": datetime.now().isoformat(),
                "methodology_applied": "scenario_generation",
                "total_scenarios": len(scenarios),
            },
        }

        metadata = ArtifactMetadata(
            tags=["scenarios", "use_cases", "user_modeling"],
            source_agent=self.name,
            custom_properties={
                "name": "User Scenarios",
                "description": "Generated user scenarios and use cases",
            },
        )

        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.USER_SCENARIOS,
            content=artifact_content,
            metadata=metadata,
            version="1.0.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT,
        )

    def _create_pain_points_artifact(self, pain_points: List[PainPoint]) -> Artifact:
        """Create artifact for pain points."""
        artifact_content = {
            "pain_points": [pain_point.to_dict() for pain_point in pain_points],
            "generation_metadata": {
                "agent": self.name,
                "timestamp": datetime.now().isoformat(),
                "methodology_applied": "pain_point_analysis",
                "total_pain_points": len(pain_points),
            },
        }

        metadata = ArtifactMetadata(
            tags=["pain_points", "user_research", "problems"],
            source_agent=self.name,
            custom_properties={
                "name": "User Pain Points",
                "description": "Identified user pain points and frustrations",
            },
        )

        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.PAIN_POINTS,
            content=artifact_content,
            metadata=metadata,
            version="1.0.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT,
        )

    def _create_nfrs_artifact(
        self,
        nfrs: List[NonFunctionalRequirement],
        system_constraints: Optional[Dict[str, Any]],
    ) -> Artifact:
        """Create artifact for non-functional requirements."""
        artifact_content = {
            "system_constraints": system_constraints or {},
            "non_functional_requirements": [nfr.to_dict() for nfr in nfrs],
            "generation_metadata": {
                "agent": self.name,
                "timestamp": datetime.now().isoformat(),
                "methodology_applied": "nfr_elicitation",
                "total_nfrs": len(nfrs),
                "categories_covered": list(set(nfr.category for nfr in nfrs)),
            },
        }

        metadata = ArtifactMetadata(
            tags=["nfr", "requirements", "quality_attributes"],
            source_agent=self.name,
            custom_properties={
                "name": "Non-Functional Requirements",
                "description": "Generated non-functional requirements based on user analysis",
            },
        )

        return Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.NON_FUNCTIONAL_REQUIREMENTS,
            content=artifact_content,
            metadata=metadata,
            version="1.0.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT,
        )

    def get_persona_summary(self, persona_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of a specific persona."""
        persona = self.personas_created.get(persona_id)
        if not persona:
            return None

        # Get related scenarios and pain points
        related_scenarios = [
            s for s in self.scenarios_created.values() if s.persona_id == persona_id
        ]
        related_pain_points = [
            p
            for p in self.pain_points_identified.values()
            if p.persona_id == persona_id
        ]

        return {
            "persona": persona.to_dict(),
            "related_scenarios_count": len(related_scenarios),
            "related_pain_points_count": len(related_pain_points),
            "key_scenarios": [s.title for s in related_scenarios[:3]],
            "main_pain_points": [p.title for p in related_pain_points[:3]],
        }

    def get_nfr_coverage_analysis(self) -> Dict[str, Any]:
        """Analyze NFR coverage across categories."""
        nfr_by_category = {}
        for nfr in self.nfrs_generated.values():
            if nfr.category not in nfr_by_category:
                nfr_by_category[nfr.category] = []
            nfr_by_category[nfr.category].append(nfr)

        coverage_analysis = {
            "total_nfrs": len(self.nfrs_generated),
            "categories_covered": list(nfr_by_category.keys()),
            "categories_missing": [
                cat for cat in self.nfr_categories if cat not in nfr_by_category
            ],
            "category_distribution": {
                cat: len(nfrs) for cat, nfrs in nfr_by_category.items()
            },
            "priority_distribution": {},
        }

        # Analyze priority distribution
        priority_counts = {}
        for nfr in self.nfrs_generated.values():
            priority_counts[nfr.priority] = priority_counts.get(nfr.priority, 0) + 1
        coverage_analysis["priority_distribution"] = priority_counts

        return coverage_analysis

    def classify_nfr_priority(
        self, nfr: NonFunctionalRequirement, business_context: Dict[str, Any]
    ) -> str:
        """
        Classify NFR priority based on business context and impact analysis.

        Args:
            nfr: Non-functional requirement to classify
            business_context: Business context information

        Returns:
            Priority level: critical, high, medium, low
        """
        # Priority scoring based on multiple factors
        priority_score = 0

        # Category-based priority weights
        category_weights = {
            "security": 4,  # Security is typically critical
            "performance": 3,  # Performance affects user experience
            "reliability": 3,  # System stability is important
            "usability": 2,  # User experience matters
            "scalability": 2,  # Future growth consideration
            "accessibility": 2,  # Legal and ethical requirements
            "maintainability": 1,  # Long-term consideration
        }

        priority_score += category_weights.get(nfr.category, 1)

        # Business impact analysis
        business_criticality = business_context.get("criticality", "medium")
        if business_criticality == "high":
            priority_score += 2
        elif business_criticality == "critical":
            priority_score += 3

        # User impact analysis
        affected_personas = len(nfr.source_personas)
        if affected_personas > 3:
            priority_score += 2
        elif affected_personas > 1:
            priority_score += 1

        # Regulatory/compliance requirements
        if any(
            keyword in nfr.description.lower()
            for keyword in [
                "compliance",
                "regulation",
                "legal",
                "audit",
                "gdpr",
                "hipaa",
            ]
        ):
            priority_score += 3

        # Map score to priority level
        if priority_score >= 8:
            return "critical"
        elif priority_score >= 6:
            return "high"
        elif priority_score >= 4:
            return "medium"
        else:
            return "low"

    def generate_nfr_acceptance_criteria(
        self, nfr: NonFunctionalRequirement, related_scenarios: List[UserScenario]
    ) -> List[str]:
        """
        Generate specific acceptance criteria for an NFR based on scenarios.

        Args:
            nfr: Non-functional requirement
            related_scenarios: Related user scenarios

        Returns:
            List of specific acceptance criteria
        """
        acceptance_criteria = []

        # Category-specific criteria generation
        if nfr.category == "performance":
            acceptance_criteria.extend(
                [
                    "System response time shall be less than 2 seconds for 95% of user requests",
                    "Page load time shall not exceed 3 seconds on standard network connections",
                    "System shall handle concurrent users without performance degradation",
                ]
            )

            # Add scenario-specific criteria
            for scenario in related_scenarios:
                if scenario.frequency == "daily":
                    acceptance_criteria.append(
                        f"Daily operations like '{scenario.title}' shall complete within 1 second"
                    )

        elif nfr.category == "usability":
            acceptance_criteria.extend(
                [
                    "New users shall complete basic tasks within 5 minutes without training",
                    "User interface shall follow established design patterns and conventions",
                    "Error messages shall be clear and provide actionable guidance",
                ]
            )

            # Add persona-specific criteria
            for persona_id in nfr.source_personas:
                persona = self.personas_created.get(persona_id)
                if persona and persona.technical_proficiency == "beginner":
                    acceptance_criteria.append(
                        "Interface shall be intuitive for users with beginner technical skills"
                    )

        elif nfr.category == "security":
            acceptance_criteria.extend(
                [
                    "All user data shall be encrypted in transit and at rest",
                    "User authentication shall be required for all system access",
                    "System shall log all security-relevant events for audit purposes",
                    "Password policies shall enforce strong authentication requirements",
                ]
            )

        elif nfr.category == "reliability":
            acceptance_criteria.extend(
                [
                    "System uptime shall be 99.9% or higher",
                    "System shall recover from failures within 5 minutes",
                    "Data backup shall be performed automatically every 24 hours",
                    "System shall handle unexpected shutdowns gracefully",
                ]
            )

        elif nfr.category == "accessibility":
            acceptance_criteria.extend(
                [
                    "System shall comply with WCAG 2.1 Level AA guidelines",
                    "All functionality shall be accessible via keyboard navigation",
                    "Screen reader compatibility shall be maintained throughout",
                    "Color contrast ratios shall meet accessibility standards",
                ]
            )

        elif nfr.category == "scalability":
            acceptance_criteria.extend(
                [
                    "System shall support 10x current user load without architectural changes",
                    "Database performance shall remain stable with 100x data growth",
                    "System shall scale horizontally across multiple servers",
                ]
            )

        elif nfr.category == "maintainability":
            acceptance_criteria.extend(
                [
                    "Code shall maintain minimum 80% test coverage",
                    "System documentation shall be updated with each release",
                    "Code shall follow established coding standards and conventions",
                    "System shall support automated deployment and rollback",
                ]
            )

        return acceptance_criteria

    def assess_nfr_feasibility(
        self, nfr: NonFunctionalRequirement, technical_constraints: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Assess the feasibility of implementing an NFR given technical constraints.

        Args:
            nfr: Non-functional requirement to assess
            technical_constraints: Technical constraints and limitations

        Returns:
            Feasibility assessment dictionary
        """
        assessment = {
            "feasibility_score": 0.0,  # 0.0 to 1.0
            "implementation_complexity": "unknown",
            "estimated_effort": "unknown",
            "technical_risks": [],
            "dependencies": [],
            "recommendations": [],
        }

        # Base feasibility on category and constraints
        budget_constraint = technical_constraints.get("budget", "medium")
        timeline_constraint = technical_constraints.get("timeline", "medium")
        team_size = technical_constraints.get("team_size", "medium")

        # Category-specific feasibility analysis
        if nfr.category == "performance":
            if budget_constraint == "high" and team_size == "large":
                assessment["feasibility_score"] = 0.9
                assessment["implementation_complexity"] = "moderate"
                assessment["estimated_effort"] = "4-6 weeks"
            else:
                assessment["feasibility_score"] = 0.7
                assessment["implementation_complexity"] = "high"
                assessment["estimated_effort"] = "8-12 weeks"
                assessment["technical_risks"].append(
                    "May require infrastructure upgrades"
                )

        elif nfr.category == "security":
            assessment["feasibility_score"] = 0.8
            assessment["implementation_complexity"] = "high"
            assessment["estimated_effort"] = "6-10 weeks"
            assessment["dependencies"].extend(["Security audit", "Compliance review"])
            assessment["technical_risks"].append("Requires security expertise")

        elif nfr.category == "usability":
            assessment["feasibility_score"] = 0.9
            assessment["implementation_complexity"] = "moderate"
            assessment["estimated_effort"] = "3-5 weeks"
            assessment["dependencies"].append("UX design resources")

        elif nfr.category == "reliability":
            if technical_constraints.get("infrastructure", "basic") == "advanced":
                assessment["feasibility_score"] = 0.8
                assessment["implementation_complexity"] = "moderate"
            else:
                assessment["feasibility_score"] = 0.6
                assessment["implementation_complexity"] = "high"
                assessment["technical_risks"].append(
                    "May require infrastructure investment"
                )

        # Add general recommendations
        if assessment["feasibility_score"] < 0.5:
            assessment["recommendations"].append(
                "Consider phased implementation approach"
            )
            assessment["recommendations"].append("Evaluate alternative solutions")
        elif assessment["feasibility_score"] < 0.7:
            assessment["recommendations"].append("Allocate additional resources")
            assessment["recommendations"].append("Plan for extended timeline")

        return assessment

    def generate_nfr_test_scenarios(
        self, nfr: NonFunctionalRequirement
    ) -> List[Dict[str, Any]]:
        """
        Generate test scenarios for validating an NFR.

        Args:
            nfr: Non-functional requirement

        Returns:
            List of test scenario dictionaries
        """
        test_scenarios = []

        if nfr.category == "performance":
            test_scenarios.extend(
                [
                    {
                        "name": "Load Testing",
                        "description": "Test system performance under expected load",
                        "test_type": "load_test",
                        "success_criteria": nfr.measurable_criteria,
                        "tools": ["JMeter", "LoadRunner"],
                        "duration": "2-4 hours",
                    },
                    {
                        "name": "Stress Testing",
                        "description": "Test system behavior under extreme load",
                        "test_type": "stress_test",
                        "success_criteria": [
                            "System degrades gracefully",
                            "No data corruption",
                        ],
                        "tools": ["JMeter", "Artillery"],
                        "duration": "4-8 hours",
                    },
                ]
            )

        elif nfr.category == "usability":
            test_scenarios.extend(
                [
                    {
                        "name": "User Acceptance Testing",
                        "description": "Test with real users performing actual tasks",
                        "test_type": "user_test",
                        "success_criteria": nfr.acceptance_criteria,
                        "participants": "5-10 representative users",
                        "duration": "1-2 days",
                    },
                    {
                        "name": "Accessibility Testing",
                        "description": "Test accessibility compliance and screen reader compatibility",
                        "test_type": "accessibility_test",
                        "success_criteria": [
                            "WCAG 2.1 compliance",
                            "Screen reader compatibility",
                        ],
                        "tools": ["WAVE", "axe", "Screen readers"],
                        "duration": "1-2 days",
                    },
                ]
            )

        elif nfr.category == "security":
            test_scenarios.extend(
                [
                    {
                        "name": "Penetration Testing",
                        "description": "Test system security against common attack vectors",
                        "test_type": "security_test",
                        "success_criteria": [
                            "No critical vulnerabilities",
                            "Data remains secure",
                        ],
                        "tools": ["OWASP ZAP", "Burp Suite"],
                        "duration": "1-2 weeks",
                    },
                    {
                        "name": "Authentication Testing",
                        "description": "Test authentication and authorization mechanisms",
                        "test_type": "auth_test",
                        "success_criteria": [
                            "Strong password enforcement",
                            "Session management",
                        ],
                        "tools": ["Custom scripts", "Security scanners"],
                        "duration": "2-3 days",
                    },
                ]
            )

        return test_scenarios

    def create_nfr_implementation_plan(
        self, nfrs: List[NonFunctionalRequirement], project_constraints: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create an implementation plan for a set of NFRs.

        Args:
            nfrs: List of non-functional requirements
            project_constraints: Project constraints (budget, timeline, resources)

        Returns:
            Implementation plan dictionary
        """
        # Prioritize NFRs
        prioritized_nfrs = sorted(
            nfrs,
            key=lambda x: {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(
                x.priority, 1
            ),
            reverse=True,
        )

        # Group by category for efficient implementation
        nfrs_by_category = {}
        for nfr in prioritized_nfrs:
            if nfr.category not in nfrs_by_category:
                nfrs_by_category[nfr.category] = []
            nfrs_by_category[nfr.category].append(nfr)

        # Create implementation phases
        phases = []
        current_phase = 1

        # Phase 1: Critical and High priority NFRs
        critical_high_nfrs = [
            nfr for nfr in prioritized_nfrs if nfr.priority in ["critical", "high"]
        ]
        if critical_high_nfrs:
            phases.append(
                {
                    "phase": current_phase,
                    "name": "Critical Requirements Implementation",
                    "nfrs": [nfr.id for nfr in critical_high_nfrs],
                    "estimated_duration": "6-10 weeks",
                    "dependencies": [],
                    "deliverables": [
                        "Security framework",
                        "Performance baseline",
                        "Core reliability features",
                    ],
                }
            )
            current_phase += 1

        # Phase 2: Medium priority NFRs
        medium_nfrs = [nfr for nfr in prioritized_nfrs if nfr.priority == "medium"]
        if medium_nfrs:
            phases.append(
                {
                    "phase": current_phase,
                    "name": "Quality Enhancement Implementation",
                    "nfrs": [nfr.id for nfr in medium_nfrs],
                    "estimated_duration": "4-6 weeks",
                    "dependencies": [1] if current_phase > 1 else [],
                    "deliverables": [
                        "Usability improvements",
                        "Accessibility compliance",
                        "Scalability features",
                    ],
                }
            )
            current_phase += 1

        # Phase 3: Low priority NFRs
        low_nfrs = [nfr for nfr in prioritized_nfrs if nfr.priority == "low"]
        if low_nfrs:
            phases.append(
                {
                    "phase": current_phase,
                    "name": "Additional Quality Attributes",
                    "nfrs": [nfr.id for nfr in low_nfrs],
                    "estimated_duration": "2-4 weeks",
                    "dependencies": [current_phase - 1] if current_phase > 1 else [],
                    "deliverables": [
                        "Maintainability improvements",
                        "Additional monitoring",
                    ],
                }
            )

        implementation_plan = {
            "total_nfrs": len(nfrs),
            "phases": phases,
            "estimated_total_duration": "12-20 weeks",
            "resource_requirements": {
                "developers": 3 - 5,
                "security_specialist": 1,
                "ux_designer": 1,
                "qa_engineers": 2,
            },
            "risk_mitigation": [
                "Regular security reviews",
                "Performance monitoring setup",
                "User feedback collection",
                "Automated testing implementation",
            ],
            "success_metrics": [
                "All critical NFRs implemented",
                "Performance benchmarks met",
                "Security audit passed",
                "User satisfaction > 4.0/5.0",
            ],
        }

        return implementation_plan

    async def process(
        self,
        task: Task,
        in_queue_mess: Optional[asyncio.Queue],
        out_queue_mess: Optional[asyncio.Queue],
    ) -> Dict:
        logger.info(f"Agent {self.name} executing task: {task.description}")

        if task.metadata.get("phase") == "interview":
            while True and in_queue_mess and out_queue_mess:
                msg = await in_queue_mess.get()
                if msg == "STOP":
                    break

                action_prompt = self._get_action_prompt(
                    "interviewer_asking",
                    context={"msg": msg},
                )
                cot_result = await asyncio.to_thread(
                    self.generate_with_cot,
                    prompt=action_prompt,
                    context={
                        "msg": msg,
                    },
                    reasoning_template="enduser_response",
                    profile_prompt=self.profile_prompt,
                )
                question = cot_result["response"].strip()
                logger.info(f"[EndUser]: {question}")

                self.add_to_memory("system", msg)
                self.add_to_memory("user", question)

                await out_queue_mess.put(question)
                await asyncio.sleep(1)

                in_queue_mess.task_done()

        return {
            "artifact_type": "requirement_model",
            "models": ["Use Case Diagram", "Activity Diagram", "Class Diagram"],
            "status": "completed",
        }
