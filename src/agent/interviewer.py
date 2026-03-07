from .knowledge_driven_agent import KnowledgeDrivenAgent
from typing import List, Dict, Any, Optional, Tuple
from .customer import Customer
from ..knowledge.base_types import KnowledgeType
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus, ArtifactMetadata
from ..orchestrator.orchestrator import Task
from datetime import datetime
import logging
import uuid
import asyncio

logger = logging.getLogger(__name__)


class BaseInterviewerAgent(KnowledgeDrivenAgent):
    """
    Knowledge-driven interviewer agent for requirements elicitation.

    Integrates 5W1H methodology, Socratic Questioning, and other elicitation techniques
    to conduct structured interviews with stakeholders.
    """

    def __init__(self, config_path: Optional[str] = None, **kwargs):
        # Define required knowledge modules for interviewer
        knowledge_modules = [
            "5w1h_methodology",
            "socratic_questioning",
            "requirements_elicitation",
            "interview_techniques",
            "stakeholder_analysis",
        ]

        super().__init__(
            name="interviewer",
            knowledge_modules=knowledge_modules,
            config_path=config_path,
            **kwargs,
        )
        interview_config = self.config.get("custom_params", {})

        # Interview configuration
        self.completeness_threshold = interview_config.get(

        # Interview state
        self.current_interview_session: Optional[str] = None
        self.interview_records: Dict[str, Dict[str, Any]] = {}
        self.stakeholder_profiles: Dict[str, Dict[str, Any]] = {}

        # Initialize profile prompt
        self.profile_prompt = self._create_profile_prompt()
        self.add_to_memory("system", self.profile_prompt)

    def _create_profile_prompt(self) -> str:
        """Create profile prompt for the interviewer agent."""
        return """You are an experienced requirements interviewer.

Mission:
Elicit, clarify, and document stakeholder requirements with maximum completeness and accuracy.

Personality:
Neutral, empathetic, and inquisitive; fluent in both business and technical terminology.

Workflow:
1. Conduct multi-round dialogue with end users.
2. Produce interview records immediately after dialogues.
3. Write a consolidated user requirements list.
4. Conduct multi-round dialogue with system deployers.
5. Write an operation environment list.

Experience & Preferred Practices:
1. Follow ISO/IEC/IEEE 29148 and BABOK v3 guidance.
2. Use open-ended questions, active listening, and iterative paraphrasing.
3. Apply Socratic Questioning to resolve any ambiguous statements.
4. Limit each question turn to no more than two questions to maintain a natural conversational flow.

Internal Chain of Thought (visible to the agent only):
1. Identify stakeholder type and context.
2. Use 5W1H and targeted probes to surface goals, pain points, and constraints.
3. Map each utterance to 〈Role|Goal|Behaviour|Constraint〉 tuples.
4. Paraphrase key findings and request confirmation before proceeding.
"""

    def _get_action_prompt(self, action: str, context: Dict[str, Any] = None) -> str:
        """Get action-specific prompt for a given action."""
        action_prompts = {
            "conduct_interview": """Action: Conduct structured interview with stakeholder.

Context:
- Stakeholder type: {stakeholder_type}
- Current turn: {turn_count}
- Previous responses: {previous_responses}

Instructions:
1. Generate the next interview question based on the conversation so far.
2. Apply 5W1H framework or Socratic questioning as appropriate.
3. Limit to maximum 2 questions per turn.
4. Structure response as:
   QUESTION: [Your question]
   REASONING: [Why you're asking this]
   METHODOLOGY: [5W1H/Socratic/Other]
   END_CONVERSATION: [true/false]
""",
            "create_interview_record": """Action: Create structured interview record.

Context:
- Interview session: {session_id}
- Total turns: {total_turns}
- Requirements identified: {requirements_count}

Instructions:
1. Organize interview data into structured format.
2. Extract all identified requirements.
3. Identify gaps and inconsistencies.
4. Calculate completeness score.
""",
            "create_user_requirements_list": """Action: Create consolidated user requirements list.

Context:
- Interview records: {interview_records}
- Requirements identified: {requirements}

Instructions:
1. Consolidate requirements from all interviews.
2. Remove duplicates and merge similar requirements.
3. Prioritize requirements.
4. Structure as traceable, sortable list with source, priority, and description.
""",
        }

        base_prompt = action_prompts.get(action, f"Action: {action}")
        if context:
            try:
                return base_prompt.format(**context)
            except:
                return base_prompt
        return base_prompt

    def chat_with_customer(
        self, customer: Customer, stakeholder_type: str = "customer"
    ) -> Dict[str, Any]:
        """
        Conduct a structured interview with a customer using knowledge-driven approach.

        Args:
            customer: Customer object to interview
            stakeholder_type: Type of stakeholder being interviewed

        Returns:
            Interview record dictionary
        """
        # Start new interview session
        session_id = str(uuid.uuid4())
        self.current_interview_session = session_id

        # Initialize interview record
        interview_record = {
            "session_id": session_id,
            "stakeholder_type": stakeholder_type,
            "start_time": datetime.now(),
            "turns": [],
            "requirements_identified": [],
            "gaps_identified": [],
            "completeness_score": 0.0,
            "status": "in_progress",
        }

        self.interview_records[session_id] = interview_record

        # Apply methodology guidance
        methodology_guide = self.apply_methodology(f"interview_{stakeholder_type}")

        # Create enhanced task description with CoT reasoning
        task_description = f"""
        Conduct a structured requirements interview with a {stakeholder_type}.
        
        Apply the following methodologies:
        - 5W1H Framework for systematic exploration
        - Socratic Questioning for deep insights
        - Requirements Elicitation best practices
        
        Interview Objectives:
        1. Understand business context and objectives
        2. Identify functional and non-functional requirements
        3. Discover constraints and assumptions
        4. Validate understanding throughout the process
        5. Assess requirement completeness
        
        Begin with an opening question that establishes context.
        """

        self.add_to_memory("user", task_description)
        turn_count = 0

        logger.info(f"Starting interview session {session_id} with {stakeholder_type}")

        while turn_count < self.max_customer_turns:
            # Generate response using CoT reasoning with action prompt
            action_prompt = self._get_action_prompt(
                "conduct_interview",
                context={
                    "stakeholder_type": stakeholder_type,
                    "turn_count": turn_count,
                    "previous_responses": [
                        turn.get("answer", "")
                        for turn in interview_record["turns"][-3:]
                    ],
                },
            )

            cot_result = self.generate_with_cot(
                prompt=action_prompt,
                context={
                    "stakeholder_type": stakeholder_type,
                    "turn_count": turn_count,
                    "methodology_guide": methodology_guide,
                    "interview_record": interview_record,
                },
                reasoning_template="interview_questioning",
            )

            response = cot_result["response"]
            question, reasoning, methodology, end_conversation = self.parse_response(
                response
            )

            # Record the turn
            turn_data = {
                "turn": turn_count + 1,
                "question": question,
                "reasoning": reasoning,
                "methodology": methodology,
                "timestamp": datetime.now(),
            }

            self.add_to_memory("assistant", question)
            print(f"\n[Interviewer]: {question}")

            # Get customer response
            answer = customer.chat_with_interviewer(question)
            turn_data["answer"] = answer
            turn_data["answer_timestamp"] = datetime.now()

            self.add_to_memory("user", answer)
            interview_record["turns"].append(turn_data)

            # Extract requirements from the answer
            extracted_requirements = self._extract_requirements_from_answer(
                answer, question
            )
            interview_record["requirements_identified"].extend(extracted_requirements)

            # Check if conversation should end
            if end_conversation or self._should_end_conversation(interview_record):
                print(
                    "\n[Interviewer]: Thank you for your time. I have gathered comprehensive information about your requirements."
                )
                self.add_to_memory(
                    "assistant",
                    "Ending conversation - requirements gathering complete.",
                )
                break

            turn_count += 1

        # Finalize interview record
        interview_record["end_time"] = datetime.now()
        interview_record["total_turns"] = len(interview_record["turns"])
        interview_record["completeness_score"] = self.assess_requirement_completeness(
            interview_record["requirements_identified"]
        )
        interview_record["status"] = "completed"

        logger.info(f"Completed interview session {session_id} with {turn_count} turns")

        return interview_record

    def parse_response(self, response: str) -> Tuple[str, str, str, bool]:
        """
        Parse the agent's response to extract question, reasoning, methodology, and end flag.

        Args:
            response: Raw response from the agent

        Returns:
            Tuple of (question, reasoning, methodology, end_conversation)
        """
        question = ""
        reasoning = ""
        methodology = ""
        end_conversation = False

        lines = response.strip().split("\n")

        for line in lines:
            line = line.strip()
            if line.startswith("QUESTION:"):
                question = line.replace("QUESTION:", "").strip()
            elif line.startswith("REASONING:"):
                reasoning = line.replace("REASONING:", "").strip()
            elif line.startswith("METHODOLOGY:"):
                methodology = line.replace("METHODOLOGY:", "").strip()
            elif line.startswith("END_CONVERSATION:"):
                end_value = line.replace("END_CONVERSATION:", "").strip().lower()
                end_conversation = end_value in ["true", "yes", "1"]

        # Fallback: if no structured format, treat entire response as question
        if not question:
            question = response.strip()
            reasoning = "General requirements elicitation"
            methodology = "Open-ended questioning"

        return question, reasoning, methodology, end_conversation

    def _extract_requirements_from_answer(
        self, answer: str, question: str
    ) -> List[Dict[str, Any]]:
        """
        Extract potential requirements from stakeholder's answer.

        Args:
            answer: Stakeholder's response
            question: The question that prompted this answer

        Returns:
            List of extracted requirement dictionaries
        """
        requirements = []

        # Simple keyword-based extraction (can be enhanced with NLP)
        requirement_indicators = [
            "need",
            "require",
            "must",
            "should",
            "want",
            "expect",
            "system should",
            "application must",
            "user needs",
            "business requires",
            "compliance",
            "regulation",
        ]

        answer_lower = answer.lower()

        for indicator in requirement_indicators:
            if indicator in answer_lower:
                # Extract the sentence containing the requirement
                sentences = answer.split(".")
                for sentence in sentences:
                    if indicator in sentence.lower():
                        requirements.append(
                            {
                                "id": str(uuid.uuid4()),
                                "text": sentence.strip(),
                                "source_question": question,
                                "type": "functional",  # Default, can be refined
                                "priority": "medium",  # Default
                                "extracted_at": datetime.now(),
                                "confidence": 0.7,  # Default confidence
                            }
                        )

        return requirements

    def _should_end_conversation(self, interview_record: Dict[str, Any]) -> bool:
        """
        Determine if the conversation should end based on completeness and other factors.

        Args:
            interview_record: Current interview record

        Returns:
            True if conversation should end
        """
        # Check if we have enough requirements
        num_requirements = len(interview_record["requirements_identified"])
        if num_requirements < 3:  # Minimum threshold
            return False

        # Check if recent turns are not yielding new requirements
        recent_turns = (
            interview_record["turns"][-3:]
            if len(interview_record["turns"]) >= 3
            else []
        )
        recent_requirements = [
            req
            for req in interview_record["requirements_identified"]
            if any(
                req["source_question"] in turn.get("question", "")
                for turn in recent_turns
            )
        ]

        if len(recent_requirements) == 0 and len(interview_record["turns"]) > 10:
            return True  # No new requirements in recent turns

        # Check completeness score
        completeness = self.assess_requirement_completeness(
            interview_record["requirements_identified"]
        )
        if completeness >= self.completeness_threshold:
            return True

        return False

    def generate_follow_up_questions(
        self, previous_answers: List[str], context: Dict[str, Any]
    ) -> List[str]:
        """
        Generate intelligent follow-up questions based on previous answers.

        Args:
            previous_answers: List of previous stakeholder responses
            context: Additional context information

        Returns:
            List of follow-up questions
        """
        # Apply 5W1H methodology for systematic follow-up
        w5h1_module = self.knowledge_modules.get("5w1h_methodology")
        follow_up_questions = []

        if w5h1_module:
            framework = w5h1_module.content.get("framework", {})

            # Generate questions for each W/H dimension
            for dimension, info in framework.items():
                if "questions" in info:
                    # Select relevant questions based on context
                    relevant_questions = self._select_relevant_questions(
                        info["questions"], previous_answers, context
                    )
                    follow_up_questions.extend(
                        relevant_questions[:2]
                    )  # Limit to 2 per dimension

        # Apply Socratic questioning for deeper insights
        socratic_questions = self._generate_socratic_questions(
            previous_answers, context
        )
        follow_up_questions.extend(socratic_questions)

        # Remove duplicates and limit total number
        unique_questions = list(dict.fromkeys(follow_up_questions))
        return unique_questions[:8]  # Limit to 8 questions

    def _select_relevant_questions(
        self, questions: List[str], previous_answers: List[str], context: Dict[str, Any]
    ) -> List[str]:
        """Select relevant questions based on previous answers and context."""
        relevant_questions = []

        # Simple relevance scoring based on keyword matching
        answer_text = " ".join(previous_answers).lower()

        for question in questions:
            # Check if question addresses gaps in previous answers
            question_keywords = self._extract_keywords(question.lower())
            if not any(keyword in answer_text for keyword in question_keywords):
                relevant_questions.append(question)

        return relevant_questions

    def _generate_socratic_questions(
        self, previous_answers: List[str], context: Dict[str, Any]
    ) -> List[str]:
        """Generate Socratic-style probing questions."""
        socratic_questions = []

        # Analyze previous answers for assumptions and claims
        for answer in previous_answers:
            if "because" in answer.lower() or "since" in answer.lower():
                socratic_questions.append(f"What evidence supports that assumption?")

            if "always" in answer.lower() or "never" in answer.lower():
                socratic_questions.append(f"Are there any exceptions to that rule?")

            if "should" in answer.lower() or "must" in answer.lower():
                socratic_questions.append(
                    f"What would happen if that requirement wasn't met?"
                )

        # Add general probing questions
        socratic_questions.extend(
            [
                "Can you give me a specific example of that?",
                "What are the implications of that requirement?",
                "How does that relate to your overall business objectives?",
                "What alternatives have you considered?",
            ]
        )

        return socratic_questions[:4]  # Limit to 4 questions

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text for relevance matching."""
        # Simple keyword extraction (can be enhanced with NLP)
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
        }
        words = text.split()
        keywords = [
            word.strip(".,!?")
            for word in words
            if word.lower() not in stop_words and len(word) > 3
        ]
        return keywords

    def assess_requirement_completeness(
        self, requirements: List[Dict[str, Any]]
    ) -> float:
        """
        Assess the completeness of gathered requirements.

        Args:
            requirements: List of requirement dictionaries

        Returns:
            Completeness score between 0.0 and 1.0
        """
        if not requirements:
            return 0.0

        # Define completeness criteria
        completeness_criteria = {
            "functional_requirements": 0.3,
            "non_functional_requirements": 0.2,
            "constraints": 0.15,
            "stakeholder_coverage": 0.15,
            "business_objectives": 0.1,
            "acceptance_criteria": 0.1,
        }

        score = 0.0

        # Check functional requirements coverage
        functional_reqs = [
            req for req in requirements if req.get("type") == "functional"
        ]
        if len(functional_reqs) >= 5:  # Minimum threshold
            score += completeness_criteria["functional_requirements"]
        else:
            score += completeness_criteria["functional_requirements"] * (
                len(functional_reqs) / 5
            )

        # Check non-functional requirements
        nfr_reqs = [req for req in requirements if req.get("type") == "non_functional"]
        if len(nfr_reqs) >= 3:
            score += completeness_criteria["non_functional_requirements"]
        else:
            score += completeness_criteria["non_functional_requirements"] * (
                len(nfr_reqs) / 3
            )

        # Check for constraints
        constraint_keywords = ["must", "cannot", "limited", "restricted", "compliance"]
        constraint_reqs = [
            req
            for req in requirements
            if any(
                keyword in req.get("text", "").lower()
                for keyword in constraint_keywords
            )
        ]
        if len(constraint_reqs) >= 2:
            score += completeness_criteria["constraints"]
        else:
            score += completeness_criteria["constraints"] * (len(constraint_reqs) / 2)

        # Check stakeholder coverage (simplified)
        if (
            len(requirements) >= 10
        ):  # Assume good stakeholder coverage with many requirements
            score += completeness_criteria["stakeholder_coverage"]
        else:
            score += completeness_criteria["stakeholder_coverage"] * (
                len(requirements) / 10
            )

        # Check business objectives coverage
        business_keywords = ["business", "objective", "goal", "value", "benefit", "roi"]
        business_reqs = [
            req
            for req in requirements
            if any(
                keyword in req.get("text", "").lower() for keyword in business_keywords
            )
        ]
        if len(business_reqs) >= 2:
            score += completeness_criteria["business_objectives"]
        else:
            score += completeness_criteria["business_objectives"] * (
                len(business_reqs) / 2
            )

        # Check acceptance criteria
        acceptance_keywords = ["accept", "criteria", "test", "verify", "validate"]
        acceptance_reqs = [
            req
            for req in requirements
            if any(
                keyword in req.get("text", "").lower()
                for keyword in acceptance_keywords
            )
        ]
        if len(acceptance_reqs) >= 1:
            score += completeness_criteria["acceptance_criteria"]

        return min(score, 1.0)  # Cap at 1.0

    def identify_requirement_gaps(
        self, requirements: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Identify gaps in the current requirements set.

        Args:
            requirements: List of current requirements

        Returns:
            List of identified gaps
        """
        gaps = []

        # Check for missing requirement types
        req_types = [req.get("type", "") for req in requirements]

        if "functional" not in req_types:
            gaps.append("Missing functional requirements")

        if "non_functional" not in req_types:
            gaps.append(
                "Missing non-functional requirements (performance, security, usability)"
            )

        # Check for missing 5W1H coverage
        requirement_text = " ".join(
            [req.get("text", "") for req in requirements]
        ).lower()

        w5h1_coverage = {
            "who": ["user", "stakeholder", "actor", "role"],
            "what": ["function", "feature", "capability", "service"],
            "when": ["time", "schedule", "deadline", "frequency"],
            "where": ["location", "environment", "platform", "system"],
            "why": ["purpose", "reason", "objective", "goal", "benefit"],
            "how": ["method", "process", "workflow", "integration"],
        }

        for dimension, keywords in w5h1_coverage.items():
            if not any(keyword in requirement_text for keyword in keywords):
                gaps.append(f"Missing {dimension.upper()} dimension coverage")

        # Check for specific requirement categories
        categories_to_check = [
            ("security", ["security", "authentication", "authorization", "encryption"]),
            ("performance", ["performance", "speed", "response", "throughput"]),
            (
                "usability",
                ["usability", "user experience", "interface", "accessibility"],
            ),
            ("integration", ["integration", "interface", "api", "external"]),
            ("compliance", ["compliance", "regulation", "standard", "audit"]),
        ]

        for category, keywords in categories_to_check:
            if not any(keyword in requirement_text for keyword in keywords):
                gaps.append(f"Missing {category} requirements")

        return gaps

    def get_interview_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a summary of a completed interview session.

        Args:
            session_id: Interview session identifier

        Returns:
            Interview summary dictionary or None if not found
        """
        if session_id not in self.interview_records:
            return None

        record = self.interview_records[session_id]

        summary = {
            "session_id": session_id,
            "stakeholder_type": record["stakeholder_type"],
            "duration_minutes": (
                record["end_time"] - record["start_time"]
            ).total_seconds()
            / 60,
            "total_turns": record["total_turns"],
            "requirements_count": len(record["requirements_identified"]),
            "completeness_score": record["completeness_score"],
            "gaps_identified": self.identify_requirement_gaps(
                record["requirements_identified"]
            ),
            "key_requirements": record["requirements_identified"][
                :5
            ],  # Top 5 requirements
            "status": record["status"],
        }

        return summary

    def create_stakeholder_profile(
        self, stakeholder_type: str, interview_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a stakeholder profile based on interview data.

        Args:
            stakeholder_type: Type of stakeholder
            interview_data: Data from interview session

        Returns:
            Stakeholder profile dictionary
        """
        profile = {
            "stakeholder_type": stakeholder_type,
            "profile_id": str(uuid.uuid4()),
            "created_at": datetime.now(),
            "characteristics": {},
            "requirements_focus": [],
            "communication_style": "",
            "priority_areas": [],
        }

        # Analyze interview turns to build profile
        turns = interview_data.get("turns", [])
        answers = [turn.get("answer", "") for turn in turns]

        # Determine communication style
        total_words = sum(len(answer.split()) for answer in answers)
        avg_words_per_answer = total_words / len(answers) if answers else 0

        if avg_words_per_answer > 50:
            profile["communication_style"] = "detailed"
        elif avg_words_per_answer > 20:
            profile["communication_style"] = "moderate"
        else:
            profile["communication_style"] = "concise"

        # Identify priority areas based on requirements
        requirements = interview_data.get("requirements_identified", [])
        requirement_types = {}

        for req in requirements:
            req_type = req.get("type", "unknown")
            requirement_types[req_type] = requirement_types.get(req_type, 0) + 1

        # Sort by frequency to identify priorities
        sorted_types = sorted(
            requirement_types.items(), key=lambda x: x[1], reverse=True
        )
        profile["priority_areas"] = [req_type for req_type, count in sorted_types[:3]]

        # Store profile
        self.stakeholder_profiles[profile["profile_id"]] = profile

        return profile


# Maintain backward compatibility with existing Interviewer class
class InterviewerAgent(BaseInterviewerAgent):
    """Backward compatibility wrapper for InterviewerAgent."""

    def __init__(self, config_path: Optional[str] = None, *args, **kwargs):
        # Convert old config format if needed
        if isinstance(config_path, dict):
            config = config_path
        else:
            config = {}

        super().__init__(config_path=config_path, *args, **kwargs)

        # Maintain old attribute names for compatibility
        # self.max_customer_turns = config.get("max_customer_turns", 50)
        # self.max_enduser_turns = config.get("max_enduser_turns", 50)

    def conduct_stakeholder_interview(
        self,
        stakeholder_info: Dict[str, Any],
        interview_objectives: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Conduct a comprehensive stakeholder interview with structured approach.

        Args:
            stakeholder_info: Information about the stakeholder (type, role, context)
            interview_objectives: Optional specific objectives for the interview

        Returns:
            Complete interview record with analysis
        """
        stakeholder_type = stakeholder_info.get("type", "stakeholder")
        stakeholder_role = stakeholder_info.get("role", "user")
        business_context = stakeholder_info.get("context", "")

        # Initialize interview session
        session_id = str(uuid.uuid4())
        self.current_interview_session = session_id

        logger.info(
            f"Starting structured interview with {stakeholder_type} ({stakeholder_role})"
        )

        # Create comprehensive interview record
        interview_record = {
            "session_id": session_id,
            "stakeholder_info": stakeholder_info,
            "interview_objectives": interview_objectives
            or self._get_default_objectives(),
            "start_time": datetime.now(),
            "phases": [],
            "current_phase": "preparation",
            "requirements_identified": [],
            "assumptions_identified": [],
            "constraints_identified": [],
            "stakeholder_concerns": [],
            "business_rules": [],
            "success_criteria": [],
            "gaps_identified": [],
            "completeness_assessment": {},
            "next_steps": [],
            "status": "in_progress",
        }

        self.interview_records[session_id] = interview_record

        # Phase 1: Preparation and Context Setting
        self._conduct_preparation_phase(interview_record)

        # Phase 2: Business Context Exploration
        self._conduct_context_exploration_phase(interview_record)

        # Phase 3: Systematic Requirements Elicitation (5W1H)
        self._conduct_systematic_elicitation_phase(interview_record)

        # Phase 4: Deep Dive with Socratic Questioning
        self._conduct_deep_dive_phase(interview_record)

        # Phase 5: Validation and Gap Analysis
        self._conduct_validation_phase(interview_record)

        # Phase 6: Closure and Next Steps
        self._conduct_closure_phase(interview_record)

        # Finalize interview record
        interview_record["end_time"] = datetime.now()
        interview_record["total_duration_minutes"] = (
            interview_record["end_time"] - interview_record["start_time"]
        ).total_seconds() / 60
        interview_record["status"] = "completed"

        # Perform final analysis
        interview_record["completeness_assessment"] = (
            self._assess_interview_completeness(interview_record)
        )
        interview_record["quality_score"] = self._calculate_interview_quality_score(
            interview_record
        )

        logger.info(
            f"Completed structured interview {session_id} with quality score: {interview_record['quality_score']}"
        )

        return interview_record

    def _get_default_objectives(self) -> List[str]:
        """Get default interview objectives."""
        return [
            "Understand business context and objectives",
            "Identify functional requirements",
            "Discover non-functional requirements",
            "Uncover constraints and assumptions",
            "Establish success criteria",
            "Identify key stakeholders and their concerns",
            "Validate understanding and identify gaps",
        ]

    def _conduct_preparation_phase(self, interview_record: Dict[str, Any]) -> None:
        """Conduct the preparation phase of the interview."""
        phase_data = {
            "phase_name": "preparation",
            "start_time": datetime.now(),
            "objectives": ["Establish rapport", "Explain process", "Set expectations"],
            "questions_asked": [],
            "insights_gathered": [],
        }

        interview_record["current_phase"] = "preparation"

        # Use CoT reasoning to generate opening
        opening_context = {
            "stakeholder_info": interview_record["stakeholder_info"],
            "interview_objectives": interview_record["interview_objectives"],
            "phase": "preparation",
        }

        # Use action prompt for opening
        action_prompt = self._get_action_prompt(
            "conduct_interview",
            context={
                "stakeholder_type": interview_record.get("stakeholder_type", "unknown"),
                "turn_count": 0,
                "previous_responses": [],
            },
        )

        opening_result = self.generate_with_cot(
            prompt=action_prompt,
            context=opening_context,
            reasoning_template="interview_opening",
        )

        opening_question = opening_result["response"]
        phase_data["questions_asked"].append(
            {
                "question": opening_question,
                "purpose": "Opening and rapport building",
                "methodology": "Professional communication",
            }
        )

        phase_data["end_time"] = datetime.now()
        interview_record["phases"].append(phase_data)

    def _conduct_context_exploration_phase(
        self, interview_record: Dict[str, Any]
    ) -> None:
        """Conduct business context exploration phase."""
        phase_data = {
            "phase_name": "context_exploration",
            "start_time": datetime.now(),
            "objectives": [
                "Understand business domain",
                "Identify key processes",
                "Discover pain points",
            ],
            "questions_asked": [],
            "insights_gathered": [],
        }

        interview_record["current_phase"] = "context_exploration"

        # Generate context exploration questions
        context_questions = [
            "Can you describe your current business process or workflow?",
            "What are the main challenges you're facing with the current system?",
            "Who are the key stakeholders involved in this process?",
            "What would success look like for this project?",
            "Are there any regulatory or compliance requirements we need to consider?",
        ]

        for question in context_questions:
            phase_data["questions_asked"].append(
                {
                    "question": question,
                    "purpose": "Business context understanding",
                    "methodology": "Open-ended exploration",
                }
            )

        phase_data["end_time"] = datetime.now()
        interview_record["phases"].append(phase_data)

    def _conduct_systematic_elicitation_phase(
        self, interview_record: Dict[str, Any]
    ) -> None:
        """Conduct systematic requirements elicitation using 5W1H framework."""
        phase_data = {
            "phase_name": "systematic_elicitation",
            "start_time": datetime.now(),
            "objectives": ["Apply 5W1H framework", "Systematic requirement discovery"],
            "questions_asked": [],
            "insights_gathered": [],
        }

        interview_record["current_phase"] = "systematic_elicitation"

        # Apply 5W1H methodology
        w5h1_module = self.knowledge_modules.get("5w1h_methodology")
        if w5h1_module:
            framework = w5h1_module.content.get("framework", {})

            for dimension, info in framework.items():
                dimension_questions = info.get("questions", [])[
                    :3
                ]  # Limit to 3 per dimension

                for question in dimension_questions:
                    phase_data["questions_asked"].append(
                        {
                            "question": question,
                            "purpose": f"{dimension.upper()} dimension exploration",
                            "methodology": "5W1H Framework",
                        }
                    )

        phase_data["end_time"] = datetime.now()
        interview_record["phases"].append(phase_data)

    def _conduct_deep_dive_phase(self, interview_record: Dict[str, Any]) -> None:
        """Conduct deep dive phase using Socratic questioning."""
        phase_data = {
            "phase_name": "deep_dive",
            "start_time": datetime.now(),
            "objectives": [
                "Deep exploration of critical areas",
                "Challenge assumptions",
            ],
            "questions_asked": [],
            "insights_gathered": [],
        }

        interview_record["current_phase"] = "deep_dive"

        # Generate Socratic questions based on previous phases
        previous_insights = []
        for phase in interview_record["phases"]:
            previous_insights.extend(phase.get("insights_gathered", []))

        socratic_questions = self._generate_socratic_questions(
            previous_insights,
            {"stakeholder_info": interview_record["stakeholder_info"]},
        )

        for question in socratic_questions[:5]:  # Limit to 5 questions
            phase_data["questions_asked"].append(
                {
                    "question": question,
                    "purpose": "Deep insight exploration",
                    "methodology": "Socratic Questioning",
                }
            )

        phase_data["end_time"] = datetime.now()
        interview_record["phases"].append(phase_data)

    def _conduct_validation_phase(self, interview_record: Dict[str, Any]) -> None:
        """Conduct validation and gap analysis phase."""
        phase_data = {
            "phase_name": "validation",
            "start_time": datetime.now(),
            "objectives": [
                "Validate understanding",
                "Identify gaps",
                "Confirm priorities",
            ],
            "questions_asked": [],
            "insights_gathered": [],
        }

        interview_record["current_phase"] = "validation"

        # Generate validation questions
        validation_questions = [
            "Let me summarize what I've understood so far. Does this accurately reflect your needs?",
            "Are there any important aspects we haven't discussed yet?",
            "What would you consider the highest priority requirements?",
            "Are there any assumptions I've made that might be incorrect?",
            "What concerns do you have about implementing these requirements?",
        ]

        for question in validation_questions:
            phase_data["questions_asked"].append(
                {
                    "question": question,
                    "purpose": "Validation and gap identification",
                    "methodology": "Validation techniques",
                }
            )

        # Identify gaps based on current requirements
        current_requirements = interview_record.get("requirements_identified", [])
        gaps = self.identify_requirement_gaps(current_requirements)
        interview_record["gaps_identified"] = gaps

        phase_data["end_time"] = datetime.now()
        interview_record["phases"].append(phase_data)

    def _conduct_closure_phase(self, interview_record: Dict[str, Any]) -> None:
        """Conduct interview closure phase."""
        phase_data = {
            "phase_name": "closure",
            "start_time": datetime.now(),
            "objectives": [
                "Summarize findings",
                "Define next steps",
                "Thank stakeholder",
            ],
            "questions_asked": [],
            "insights_gathered": [],
        }

        interview_record["current_phase"] = "closure"

        # Generate closure summary
        closure_questions = [
            "Thank you for your time. I'll prepare a summary of our discussion.",
            "Is there anything else you'd like to add or clarify?",
            "What would be the best way to follow up with any additional questions?",
            "When would be a good time for a follow-up session if needed?",
        ]

        for question in closure_questions:
            phase_data["questions_asked"].append(
                {
                    "question": question,
                    "purpose": "Interview closure",
                    "methodology": "Professional closure",
                }
            )

        # Define next steps
        interview_record["next_steps"] = [
            "Analyze and categorize identified requirements",
            "Create requirements traceability matrix",
            "Prepare interview summary report",
            "Schedule follow-up sessions if needed",
            "Validate requirements with other stakeholders",
        ]

        phase_data["end_time"] = datetime.now()
        interview_record["phases"].append(phase_data)

    def _assess_interview_completeness(
        self, interview_record: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Assess the completeness of the interview."""
        assessment = {
            "overall_score": 0.0,
            "dimension_scores": {},
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
        }

        # Assess different dimensions
        dimensions = {
            "functional_requirements": 0.25,
            "non_functional_requirements": 0.20,
            "stakeholder_coverage": 0.15,
            "business_context": 0.15,
            "constraints_and_assumptions": 0.15,
            "validation_and_gaps": 0.10,
        }

        total_score = 0.0

        for dimension, weight in dimensions.items():
            score = self._assess_dimension_completeness(interview_record, dimension)
            assessment["dimension_scores"][dimension] = score
            total_score += score * weight

        assessment["overall_score"] = total_score

        # Generate recommendations
        if total_score < 0.7:
            assessment["recommendations"].append(
                "Consider additional interview sessions"
            )
        if assessment["dimension_scores"].get("non_functional_requirements", 0) < 0.5:
            assessment["recommendations"].append(
                "Focus more on non-functional requirements"
            )
        if assessment["dimension_scores"].get("validation_and_gaps", 0) < 0.6:
            assessment["recommendations"].append("Conduct more thorough validation")

        return assessment

    def _assess_dimension_completeness(
        self, interview_record: Dict[str, Any], dimension: str
    ) -> float:
        """Assess completeness of a specific dimension."""
        requirements = interview_record.get("requirements_identified", [])
        phases = interview_record.get("phases", [])

        if dimension == "functional_requirements":
            functional_reqs = [
                req for req in requirements if req.get("type") == "functional"
            ]
            return min(
                len(functional_reqs) / 8.0, 1.0
            )  # Target: 8 functional requirements

        elif dimension == "non_functional_requirements":
            nfr_reqs = [
                req for req in requirements if req.get("type") == "non_functional"
            ]
            return min(len(nfr_reqs) / 4.0, 1.0)  # Target: 4 NFRs

        elif dimension == "stakeholder_coverage":
            stakeholder_mentions = sum(
                1 for phase in phases if "stakeholder" in str(phase).lower()
            )
            return min(
                stakeholder_mentions / 3.0, 1.0
            )  # Target: 3 stakeholder discussions

        elif dimension == "business_context":
            context_phases = [
                p for p in phases if p.get("phase_name") == "context_exploration"
            ]
            return 1.0 if context_phases else 0.0

        elif dimension == "constraints_and_assumptions":
            constraints = interview_record.get("constraints_identified", [])
            assumptions = interview_record.get("assumptions_identified", [])
            return min(
                (len(constraints) + len(assumptions)) / 4.0, 1.0
            )  # Target: 4 total

        elif dimension == "validation_and_gaps":
            validation_phases = [
                p for p in phases if p.get("phase_name") == "validation"
            ]
            gaps = interview_record.get("gaps_identified", [])
            return 1.0 if validation_phases and gaps else 0.5

        return 0.0

    def _calculate_interview_quality_score(
        self, interview_record: Dict[str, Any]
    ) -> float:
        """Calculate overall interview quality score."""
        completeness = interview_record.get("completeness_assessment", {}).get(
            "overall_score", 0.0
        )

        # Factor in other quality indicators
        phases_completed = len(interview_record.get("phases", []))
        expected_phases = 6
        phase_completion_score = min(phases_completed / expected_phases, 1.0)

        requirements_count = len(interview_record.get("requirements_identified", []))
        requirements_score = min(
            requirements_count / 10.0, 1.0
        )  # Target: 10 requirements

        # Weighted quality score
        quality_score = (
            completeness * 0.5 + phase_completion_score * 0.3 + requirements_score * 0.2
        )

        return round(quality_score, 2)

    def create_interview_artifact(self, interview_record: Dict[str, Any]) -> Artifact:
        """
        Create a structured artifact from interview record for the artifact pool.

        Args:
            interview_record: Complete interview record

        Returns:
            Artifact object for storage in artifact pool
        """
        # Create artifact metadata
        metadata = ArtifactMetadata(
            title=f"Interview Record - {interview_record['stakeholder_info'].get('type', 'Stakeholder')}",
            description=f"Structured interview record with {interview_record['stakeholder_info'].get('type', 'stakeholder')}",
            author=self.name,
            version="1.0",
            tags=[
                "interview",
                "requirements",
                "elicitation",
                interview_record["stakeholder_info"].get("type", "stakeholder"),
            ],
            source="interviewer_agent",
            confidence_score=interview_record.get("quality_score", 0.8),
        )

        # Structure the artifact content
        artifact_content = {
            "interview_metadata": {
                "session_id": interview_record["session_id"],
                "stakeholder_info": interview_record["stakeholder_info"],
                "duration_minutes": interview_record.get("total_duration_minutes", 0),
                "quality_score": interview_record.get("quality_score", 0.0),
                "completeness_score": interview_record.get(
                    "completeness_assessment", {}
                ).get("overall_score", 0.0),
            },
            "interview_process": {
                "objectives": interview_record.get("interview_objectives", []),
                "phases_completed": [
                    phase["phase_name"] for phase in interview_record.get("phases", [])
                ],
                "total_questions_asked": sum(
                    len(phase.get("questions_asked", []))
                    for phase in interview_record.get("phases", [])
                ),
                "methodologies_applied": list(
                    set(
                        [
                            q.get("methodology", "")
                            for phase in interview_record.get("phases", [])
                            for q in phase.get("questions_asked", [])
                        ]
                    )
                ),
            },
            "requirements_discovered": {
                "functional_requirements": [
                    req
                    for req in interview_record.get("requirements_identified", [])
                    if req.get("type") == "functional"
                ],
                "non_functional_requirements": [
                    req
                    for req in interview_record.get("requirements_identified", [])
                    if req.get("type") == "non_functional"
                ],
                "constraints": interview_record.get("constraints_identified", []),
                "assumptions": interview_record.get("assumptions_identified", []),
                "business_rules": interview_record.get("business_rules", []),
            },
            "analysis_results": {
                "gaps_identified": interview_record.get("gaps_identified", []),
                "stakeholder_concerns": interview_record.get(
                    "stakeholder_concerns", []
                ),
                "success_criteria": interview_record.get("success_criteria", []),
                "priority_areas": self._extract_priority_areas(interview_record),
                "risk_factors": self._identify_risk_factors(interview_record),
            },
            "next_steps": interview_record.get("next_steps", []),
            "raw_interview_data": {
                "phases": interview_record.get("phases", []),
                "start_time": (
                    interview_record.get("start_time").isoformat()
                    if interview_record.get("start_time")
                    else None
                ),
                "end_time": (
                    interview_record.get("end_time").isoformat()
                    if interview_record.get("end_time")
                    else None
                ),
            },
        }

        # Create the artifact
        artifact = Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.INTERVIEW_RECORD,
            content=artifact_content,
            metadata=metadata,
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.DRAFT,
        )

        logger.info(
            f"Created interview artifact {artifact.id} for session {interview_record['session_id']}"
        )

        return artifact

    def extract_initial_requirements(
        self, interview_record: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Extract and structure initial requirements from interview record.

        Args:
            interview_record: Complete interview record

        Returns:
            List of structured initial requirements
        """
        initial_requirements = []

        # Process identified requirements
        for req in interview_record.get("requirements_identified", []):
            structured_req = {
                "id": req.get("id", str(uuid.uuid4())),
                "title": self._generate_requirement_title(req.get("text", "")),
                "description": req.get("text", ""),
                "type": req.get("type", "functional"),
                "priority": req.get("priority", "medium"),
                "source": {
                    "type": "interview",
                    "session_id": interview_record["session_id"],
                    "stakeholder": interview_record["stakeholder_info"].get(
                        "type", "unknown"
                    ),
                    "question": req.get("source_question", ""),
                    "extracted_at": (
                        req.get("extracted_at").isoformat()
                        if req.get("extracted_at")
                        else None
                    ),
                },
                "acceptance_criteria": self._generate_acceptance_criteria(
                    req.get("text", "")
                ),
                "business_value": self._assess_business_value(req.get("text", "")),
                "complexity": self._assess_complexity(req.get("text", "")),
                "dependencies": [],
                "assumptions": [],
                "constraints": [],
                "verification_method": self._suggest_verification_method(
                    req.get("text", "")
                ),
                "status": "draft",
                "confidence": req.get("confidence", 0.7),
            }

            initial_requirements.append(structured_req)

        # Add derived requirements from constraints and assumptions
        for constraint in interview_record.get("constraints_identified", []):
            constraint_req = {
                "id": str(uuid.uuid4()),
                "title": f"Constraint: {constraint.get('title', 'System Constraint')}",
                "description": constraint.get("description", ""),
                "type": "constraint",
                "priority": "high",
                "source": {
                    "type": "interview",
                    "session_id": interview_record["session_id"],
                    "stakeholder": interview_record["stakeholder_info"].get(
                        "type", "unknown"
                    ),
                    "derived_from": "constraint_analysis",
                },
                "acceptance_criteria": [
                    f"System must comply with: {constraint.get('description', '')}"
                ],
                "business_value": "compliance",
                "complexity": "medium",
                "verification_method": "inspection",
                "status": "draft",
                "confidence": 0.9,
            }

            initial_requirements.append(constraint_req)

        logger.info(
            f"Extracted {len(initial_requirements)} initial requirements from interview {interview_record['session_id']}"
        )

        return initial_requirements

    def _generate_requirement_title(self, requirement_text: str) -> str:
        """Generate a concise title for a requirement."""
        # Simple title generation - extract first meaningful phrase
        words = requirement_text.split()[:8]  # Limit to first 8 words
        title = " ".join(words)

        # Clean up and capitalize
        title = title.strip(".,!?").capitalize()

        if len(title) > 50:
            title = title[:47] + "..."

        return title or "System Requirement"

    def _generate_acceptance_criteria(self, requirement_text: str) -> List[str]:
        """Generate basic acceptance criteria for a requirement."""
        criteria = []

        # Look for specific verbs and actions
        if "login" in requirement_text.lower():
            criteria.append("User can successfully authenticate with valid credentials")
            criteria.append("System rejects invalid credentials")
        elif "search" in requirement_text.lower():
            criteria.append("User can enter search terms")
            criteria.append("System returns relevant results")
            criteria.append("Results are displayed in a clear format")
        elif "report" in requirement_text.lower():
            criteria.append("Report contains accurate data")
            criteria.append("Report is generated within acceptable time")
            criteria.append("Report can be exported in required formats")
        else:
            # Generic criteria
            criteria.append("Requirement is implemented as specified")
            criteria.append("Functionality works as expected")
            criteria.append("User interface is intuitive and accessible")

        return criteria

    def _assess_business_value(self, requirement_text: str) -> str:
        """Assess business value of a requirement."""
        high_value_keywords = [
            "revenue",
            "cost",
            "efficiency",
            "compliance",
            "security",
            "critical",
        ]
        medium_value_keywords = [
            "user experience",
            "performance",
            "quality",
            "productivity",
        ]

        text_lower = requirement_text.lower()

        if any(keyword in text_lower for keyword in high_value_keywords):
            return "high"
        elif any(keyword in text_lower for keyword in medium_value_keywords):
            return "medium"
        else:
            return "low"

    def _assess_complexity(self, requirement_text: str) -> str:
        """Assess implementation complexity of a requirement."""
        high_complexity_keywords = [
            "integration",
            "algorithm",
            "real-time",
            "distributed",
            "machine learning",
        ]
        medium_complexity_keywords = [
            "database",
            "api",
            "workflow",
            "calculation",
            "validation",
        ]

        text_lower = requirement_text.lower()

        if any(keyword in text_lower for keyword in high_complexity_keywords):
            return "high"
        elif any(keyword in text_lower for keyword in medium_complexity_keywords):
            return "medium"
        else:
            return "low"

    def _suggest_verification_method(self, requirement_text: str) -> str:
        """Suggest appropriate verification method for a requirement."""
        if (
            "performance" in requirement_text.lower()
            or "speed" in requirement_text.lower()
        ):
            return "performance_testing"
        elif (
            "security" in requirement_text.lower()
            or "authentication" in requirement_text.lower()
        ):
            return "security_testing"
        elif (
            "user" in requirement_text.lower()
            or "interface" in requirement_text.lower()
        ):
            return "user_acceptance_testing"
        elif (
            "integration" in requirement_text.lower()
            or "api" in requirement_text.lower()
        ):
            return "integration_testing"
        else:
            return "functional_testing"

    def _extract_priority_areas(self, interview_record: Dict[str, Any]) -> List[str]:
        """Extract priority areas from interview record."""
        priority_areas = []

        # Analyze requirements by type
        requirements = interview_record.get("requirements_identified", [])
        req_types = {}

        for req in requirements:
            req_type = req.get("type", "unknown")
            req_types[req_type] = req_types.get(req_type, 0) + 1

        # Sort by frequency
        sorted_types = sorted(req_types.items(), key=lambda x: x[1], reverse=True)
        priority_areas = [req_type for req_type, count in sorted_types[:3]]

        # Add business-critical areas mentioned in phases
        phases = interview_record.get("phases", [])
        for phase in phases:
            insights = phase.get("insights_gathered", [])
            for insight in insights:
                if isinstance(insight, str):
                    if "critical" in insight.lower() or "important" in insight.lower():
                        priority_areas.append("business_critical")
                        break

        return list(set(priority_areas))  # Remove duplicates

    def _identify_risk_factors(
        self, interview_record: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Identify potential risk factors from interview."""
        risk_factors = []

        # Check for complexity indicators
        requirements = interview_record.get("requirements_identified", [])
        complex_reqs = [
            req
            for req in requirements
            if self._assess_complexity(req.get("text", "")) == "high"
        ]

        if len(complex_reqs) > 3:
            risk_factors.append(
                {
                    "type": "technical_complexity",
                    "description": "High number of complex requirements identified",
                    "impact": "high",
                    "mitigation": "Consider phased implementation approach",
                }
            )

        # Check for integration requirements
        integration_reqs = [
            req for req in requirements if "integration" in req.get("text", "").lower()
        ]
        if integration_reqs:
            risk_factors.append(
                {
                    "type": "integration_risk",
                    "description": "Multiple integration requirements identified",
                    "impact": "medium",
                    "mitigation": "Early integration testing and API design",
                }
            )

        # Check for unclear requirements
        gaps = interview_record.get("gaps_identified", [])
        if len(gaps) > 5:
            risk_factors.append(
                {
                    "type": "requirements_clarity",
                    "description": "Multiple requirement gaps identified",
                    "impact": "medium",
                    "mitigation": "Additional stakeholder interviews needed",
                }
            )

        return risk_factors

    def integrate_with_artifact_pool(
        self, interview_record: Dict[str, Any], artifact_pool=None
    ) -> Dict[str, str]:
        """
        Integrate interview results with the artifact pool.

        Args:
            interview_record: Complete interview record
            artifact_pool: Artifact pool instance (optional)

        Returns:
            Dictionary with created artifact IDs
        """
        created_artifacts = {}

        # Create main interview artifact
        interview_artifact = self.create_interview_artifact(interview_record)

        if artifact_pool:
            interview_artifact_id = artifact_pool.store_artifact(interview_artifact)
            created_artifacts["interview_record"] = interview_artifact_id

            # Publish artifact created event
            if self.event_bus and self.session_id:
                self.event_bus.publish_artifact_created(
                    artifact_id=interview_artifact_id,
                    artifact_type=ArtifactType.INTERVIEW_RECORD,
                    source=self.name,
                    session_id=self.session_id,
                )

        # Create initial requirements artifact
        initial_requirements = self.extract_initial_requirements(interview_record)

        if initial_requirements:
            requirements_metadata = ArtifactMetadata(
                title="Initial Requirements from Interview",
                description=f"Initial requirements extracted from {interview_record['stakeholder_info'].get('type', 'stakeholder')} interview",
                author=self.name,
                version="1.0",
                tags=["requirements", "initial", "extracted"],
                source="interviewer_agent",
                confidence_score=0.8,
            )

            requirements_artifact = Artifact(
                id=str(uuid.uuid4()),
                type=ArtifactType.REQUIREMENTS_LIST,
                content={
                    "requirements": initial_requirements,
                    "source_interview": interview_record["session_id"],
                    "extraction_metadata": {
                        "total_requirements": len(initial_requirements),
                        "functional_count": len(
                            [
                                r
                                for r in initial_requirements
                                if r["type"] == "functional"
                            ]
                        ),
                        "non_functional_count": len(
                            [
                                r
                                for r in initial_requirements
                                if r["type"] == "non_functional"
                            ]
                        ),
                        "constraint_count": len(
                            [
                                r
                                for r in initial_requirements
                                if r["type"] == "constraint"
                            ]
                        ),
                        "extraction_date": datetime.now().isoformat(),
                    },
                },
                metadata=requirements_metadata,
                version="1.0",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                created_by=self.name,
                status=ArtifactStatus.DRAFT,
            )

            if artifact_pool:
                requirements_artifact_id = artifact_pool.store_artifact(
                    requirements_artifact
                )
                created_artifacts["initial_requirements"] = requirements_artifact_id

                # Publish artifact created event
                if self.event_bus and self.session_id:
                    self.event_bus.publish_artifact_created(
                        artifact_id=requirements_artifact_id,
                        artifact_type=ArtifactType.REQUIREMENTS_LIST,
                        source=self.name,
                        session_id=self.session_id,
                    )

        # Create stakeholder profile artifact
        stakeholder_profile = self.create_stakeholder_profile(
            interview_record["stakeholder_info"].get("type", "stakeholder"),
            interview_record,
        )

        profile_metadata = ArtifactMetadata(
            title=f"Stakeholder Profile - {stakeholder_profile['stakeholder_type']}",
            description=f"Profile of {stakeholder_profile['stakeholder_type']} based on interview analysis",
            author=self.name,
            version="1.0",
            tags=["stakeholder", "profile", "analysis"],
            source="interviewer_agent",
            confidence_score=0.7,
        )

        profile_artifact = Artifact(
            id=str(uuid.uuid4()),
            type=ArtifactType.STAKEHOLDER_PROFILE,
            content=stakeholder_profile,
            metadata=profile_metadata,
            version="1.0",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=self.name,
            status=ArtifactStatus.COMPLETED,
        )

        if artifact_pool:
            profile_artifact_id = artifact_pool.store_artifact(profile_artifact)
            created_artifacts["stakeholder_profile"] = profile_artifact_id

            # Publish artifact created event
            if self.event_bus and self.session_id:
                self.event_bus.publish_artifact_created(
                    artifact_id=profile_artifact_id,
                    artifact_type=ArtifactType.STAKEHOLDER_PROFILE,
                    source=self.name,
                    session_id=self.session_id,
                )

        # Update agent's artifacts created list
        self.artifacts_created.extend(created_artifacts.values())

        logger.info(
            f"Integrated interview results with artifact pool: {list(created_artifacts.keys())}"
        )

        return created_artifacts

    def generate_interview_summary_report(
        self, interview_record: Dict[str, Any]
    ) -> str:
        """
        Generate a comprehensive summary report of the interview.

        Args:
            interview_record: Complete interview record

        Returns:
            Formatted summary report as string
        """
        report_lines = []

        # Header
        report_lines.append("=" * 60)
        report_lines.append("REQUIREMENTS INTERVIEW SUMMARY REPORT")
        report_lines.append("=" * 60)
        report_lines.append("")

        # Interview metadata
        report_lines.append("INTERVIEW METADATA")
        report_lines.append("-" * 20)
        report_lines.append(f"Session ID: {interview_record['session_id']}")
        report_lines.append(
            f"Stakeholder Type: {interview_record['stakeholder_info'].get('type', 'Unknown')}"
        )
        report_lines.append(
            f"Stakeholder Role: {interview_record['stakeholder_info'].get('role', 'Unknown')}"
        )
        report_lines.append(
            f"Duration: {interview_record.get('total_duration_minutes', 0):.1f} minutes"
        )
        report_lines.append(
            f"Quality Score: {interview_record.get('quality_score', 0.0):.2f}"
        )
        report_lines.append(
            f"Completeness Score: {interview_record.get('completeness_assessment', {}).get('overall_score', 0.0):.2f}"
        )
        report_lines.append("")

        # Interview process
        report_lines.append("INTERVIEW PROCESS")
        report_lines.append("-" * 17)
        phases = interview_record.get("phases", [])
        report_lines.append(f"Phases Completed: {len(phases)}")
        for phase in phases:
            report_lines.append(
                f"  - {phase['phase_name'].replace('_', ' ').title()}: {len(phase.get('questions_asked', []))} questions"
            )
        report_lines.append("")

        # Requirements discovered
        requirements = interview_record.get("requirements_identified", [])
        report_lines.append("REQUIREMENTS DISCOVERED")
        report_lines.append("-" * 22)
        report_lines.append(f"Total Requirements: {len(requirements)}")

        functional_reqs = [r for r in requirements if r.get("type") == "functional"]
        nfr_reqs = [r for r in requirements if r.get("type") == "non_functional"]

        report_lines.append(f"  - Functional: {len(functional_reqs)}")
        report_lines.append(f"  - Non-Functional: {len(nfr_reqs)}")
        report_lines.append(
            f"  - Constraints: {len(interview_record.get('constraints_identified', []))}"
        )
        report_lines.append(
            f"  - Assumptions: {len(interview_record.get('assumptions_identified', []))}"
        )
        report_lines.append("")

        # Top requirements
        if requirements:
            report_lines.append("TOP REQUIREMENTS")
            report_lines.append("-" * 16)
            for i, req in enumerate(requirements[:5], 1):
                report_lines.append(f"{i}. {req.get('text', 'No description')[:80]}...")
            report_lines.append("")

        # Gaps identified
        gaps = interview_record.get("gaps_identified", [])
        if gaps:
            report_lines.append("GAPS IDENTIFIED")
            report_lines.append("-" * 15)
            for gap in gaps:
                report_lines.append(f"  - {gap}")
            report_lines.append("")

        # Next steps
        next_steps = interview_record.get("next_steps", [])
        if next_steps:
            report_lines.append("NEXT STEPS")
            report_lines.append("-" * 10)
            for i, step in enumerate(next_steps, 1):
                report_lines.append(f"{i}. {step}")
            report_lines.append("")

        # Recommendations
        completeness_assessment = interview_record.get("completeness_assessment", {})
        recommendations = completeness_assessment.get("recommendations", [])
        if recommendations:
            report_lines.append("RECOMMENDATIONS")
            report_lines.append("-" * 15)
            for rec in recommendations:
                report_lines.append(f"  - {rec}")
            report_lines.append("")

        report_lines.append("=" * 60)
        report_lines.append(
            f"Report generated by {self.name} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        report_lines.append("=" * 60)

        return "\n".join(report_lines)

    async def process(self, task: Task) -> Dict:
        logger.info(f"Interviewer {self.name} executing task: {task.description}")

        await asyncio.sleep(5)

        return {
            "artifact_type": "interview_transcript",
            "participants": task.metadata.get("stakeholders", []),
            "key_requirements": [
                "User authentication",
                "Transaction processing",
                "Reporting",
            ],
            "status": "completed",
        }
