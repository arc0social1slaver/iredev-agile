"""
Knowledge-driven agent base class for iReDev framework.
Extends BaseAgent with knowledge module integration and CoT reasoning capabilities.
"""

from abc import abstractmethod
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import logging
import uuid

from .base import BaseAgent
from .communication import CommunicationProtocol, Message, MessageType, MessagePriority
from .coordination import AgentCoordinator, Task, TaskStatus, TaskPriority
from ..knowledge.knowledge_manager import KnowledgeManager
from ..knowledge.base_types import KnowledgeModule, KnowledgeType
from ..knowledge.cot_engine import ChainOfThoughtEngine, CoTProcess, ReasoningStep
from ..artifact.events import EventBus, Event, EventType, EventHandler
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus, ArtifactMetadata

logger = logging.getLogger(__name__)


class KnowledgeDrivenAgent(BaseAgent, EventHandler):
    """
    Base class for knowledge-driven agents in the iReDev framework.
    
    Extends BaseAgent with:
    - Knowledge module loading and application
    - Chain-of-Thought reasoning integration
    - Event-driven communication capabilities
    - Artifact pool interaction
    """
    
    def __init__(self, name: str, knowledge_modules: List[str], 
                 config_path: Optional[str] = None,
                 knowledge_manager: Optional[KnowledgeManager] = None,
                 event_bus: Optional[EventBus] = None):
        """
        Initialize the knowledge-driven agent.
        
        Args:
            name: Agent name
            knowledge_modules: List of knowledge module IDs to load
            config_path: Optional path to configuration file
            knowledge_manager: Optional knowledge manager instance
            event_bus: Optional event bus instance
        """
        super().__init__(name, config_path)
        
        # Knowledge system integration
        self.knowledge_manager = knowledge_manager
        self.knowledge_modules: Dict[str, KnowledgeModule] = {}
        self.required_knowledge_modules = knowledge_modules
        
        # Chain-of-Thought reasoning
        self.cot_engine = ChainOfThoughtEngine()
        self.active_reasoning_processes: Dict[str, CoTProcess] = {}
        
        # Event-driven communication
        self.event_bus = event_bus
        self.session_id: Optional[str] = None
        self.handled_event_types: List[EventType] = []
        
        # Agent communication protocol
        self.communication: Optional[CommunicationProtocol] = None
        
        # Agent coordination
        self.coordinator: Optional[AgentCoordinator] = None
        self.assigned_tasks: List[str] = []
        
        # Agent state
        self.agent_status = "initialized"
        self.current_task: Optional[str] = None
        self.artifacts_created: List[str] = []
        
        # Initialize knowledge modules
        if self.knowledge_manager:
            self._load_knowledge_modules()
        
        # Register with event bus
        if self.event_bus:
            self._register_event_handlers()
        
        logger.info(f"Initialized knowledge-driven agent: {self.name}")
    
    def _load_knowledge_modules(self) -> None:
        """Load required knowledge modules."""
        if not self.knowledge_manager:
            logger.warning(f"No knowledge manager available for agent {self.name}")
            return
        
        loaded_modules = self.knowledge_manager.load_modules_for_agent(
            self.name, self.required_knowledge_modules
        )
        
        for module in loaded_modules:
            self.knowledge_modules[module.id] = module
            # Register module with CoT engine
            self.cot_engine.register_knowledge_module(module)
        
        logger.info(f"Loaded {len(loaded_modules)} knowledge modules for agent {self.name}")
    
    def _register_event_handlers(self) -> None:
        """Register event handlers with the event bus."""
        if not self.event_bus:
            return
        
        # Register for events this agent can handle
        for event_type in self.handled_event_types:
            self.event_bus.subscribe(event_type, self)
        
        logger.debug(f"Registered event handlers for agent {self.name}")
    
    def load_knowledge(self, domain: str) -> Optional[KnowledgeModule]:
        """
        Load additional knowledge module by domain.
        
        Args:
            domain: Domain identifier for the knowledge module
            
        Returns:
            Loaded knowledge module or None if not found
        """
        if not self.knowledge_manager:
            logger.warning(f"No knowledge manager available for agent {self.name}")
            return None
        
        module = self.knowledge_manager.load_module(domain)
        if module:
            self.knowledge_modules[module.id] = module
            self.cot_engine.register_knowledge_module(module)
            logger.info(f"Loaded additional knowledge module: {domain}")
        
        return module
    
    def apply_methodology(self, task: str) -> Dict[str, Any]:
        """
        Apply relevant methodology knowledge to a task.
        
        Args:
            task: Task description
            
        Returns:
            Methodology guidance dictionary
        """
        methodology_guide = {
            "task": task,
            "applicable_methodologies": [],
            "recommended_steps": [],
            "best_practices": []
        }
        
        # Find methodology modules
        for module_id, module in self.knowledge_modules.items():
            if module.module_type == KnowledgeType.METHODOLOGY:
                methodology_guide["applicable_methodologies"].append({
                    "module_id": module_id,
                    "name": module.content.get("name", module_id),
                    "description": module.content.get("description", "")
                })
                
                # Extract steps if available
                if "steps" in module.content:
                    methodology_guide["recommended_steps"].extend(
                        module.content["steps"]
                    )
                
                # Extract best practices
                if "best_practices" in module.content:
                    methodology_guide["best_practices"].extend(
                        module.content["best_practices"]
                    )
        
        return methodology_guide
    
    def generate_with_cot(self, prompt: str, context: Dict[str, Any],
                         reasoning_template: str = "requirements_analysis") -> Dict[str, Any]:
        """
        Generate response using Chain-of-Thought reasoning.
        
        Args:
            prompt: Input prompt
            context: Context information
            reasoning_template: CoT reasoning template to use
            
        Returns:
            Dictionary containing response and reasoning process
        """
        # Create reasoning process
        process_id = str(uuid.uuid4())
        process = self.cot_engine.create_reasoning_process(
            reasoning_template, process_id, prompt
        )
        
        if not process:
            logger.error(f"Failed to create reasoning process with template: {reasoning_template}")
            return {
                "response": self.generate_response(),
                "reasoning_process": None
            }
        
        self.active_reasoning_processes[process_id] = process
        
        # Execute reasoning steps based on template
        template = self.cot_engine.templates.get(reasoning_template)
        if template:
            for step_template in template.steps:
                step = self.cot_engine.execute_reasoning_step(
                    process_id=process_id,
                    step_type=step_template["step_type"],
                    description=step_template["description"],
                    input_data=context,
                    knowledge_types=step_template.get("knowledge_types", [])
                )
                
                if step:
                    # Update context with step output
                    context.update(step.output_data)
        
        # Generate final response using LLM with enriched context
        enhanced_prompt = self._create_enhanced_prompt(prompt, context, process)
        response = self.generate_response([
            self.llm.format_message("system", enhanced_prompt),
            self.llm.format_message("user", prompt)
        ])
        
        # Complete the reasoning process
        final_result = {
            "response": response,
            "context": context,
            "confidence": process.overall_confidence
        }
        
        self.cot_engine.complete_process(process_id, final_result)
        
        return {
            "response": response,
            "reasoning_process": process.to_dict(),
            "confidence": process.overall_confidence
        }
    
    def _create_enhanced_prompt(self, original_prompt: str, context: Dict[str, Any],
                               process: CoTProcess) -> str:
        """
        Create enhanced prompt with knowledge and reasoning context.
        
        Args:
            original_prompt: Original user prompt
            context: Reasoning context
            process: CoT reasoning process
            
        Returns:
            Enhanced prompt string
        """
        enhanced_prompt = f"""You are {self.name}, a knowledge-driven agent in the iReDev framework.

Available Knowledge Modules:
"""
        
        for module_id, module in self.knowledge_modules.items():
            enhanced_prompt += f"- {module_id}: {module.content.get('description', 'No description')}\n"
        
        enhanced_prompt += f"""
Reasoning Process Applied:
Task: {process.task_description}
Steps Completed: {len(process.steps)}
Knowledge Modules Used: {', '.join(process.knowledge_modules_used)}

Context Information:
"""
        
        for key, value in context.items():
            if isinstance(value, (str, int, float, bool)):
                enhanced_prompt += f"- {key}: {value}\n"
            elif isinstance(value, (list, dict)):
                enhanced_prompt += f"- {key}: {type(value).__name__} with {len(value)} items\n"
        
        enhanced_prompt += f"""
Please provide a response that:
1. Leverages the available knowledge modules
2. Follows the reasoning process outlined above
3. Addresses the specific requirements of your role as {self.name}
4. Maintains consistency with the context provided

Original Request: {original_prompt}
"""
        
        return enhanced_prompt
    
    def validate_against_standards(self, artifact: Artifact) -> Dict[str, Any]:
        """
        Validate artifact against relevant standards.
        
        Args:
            artifact: Artifact to validate
            
        Returns:
            Validation result dictionary
        """
        validation_result = {
            "artifact_id": artifact.id,
            "artifact_type": artifact.type.value,
            "validation_passed": True,
            "standards_checked": [],
            "violations": [],
            "recommendations": []
        }
        
        # Find standards modules
        for module_id, module in self.knowledge_modules.items():
            if module.module_type == KnowledgeType.STANDARDS:
                validation_result["standards_checked"].append(module_id)
                
                # Apply standard validation rules
                if "validation_rules" in module.content:
                    for rule in module.content["validation_rules"]:
                        if not self._check_validation_rule(artifact, rule):
                            validation_result["violations"].append({
                                "standard": module_id,
                                "rule": rule.get("name", "Unknown rule"),
                                "description": rule.get("description", "")
                            })
                            validation_result["validation_passed"] = False
                
                # Add recommendations
                if "recommendations" in module.content:
                    validation_result["recommendations"].extend(
                        module.content["recommendations"]
                    )
        
        return validation_result
    
    def _check_validation_rule(self, artifact: Artifact, rule: Dict[str, Any]) -> bool:
        """
        Check a specific validation rule against an artifact.
        
        Args:
            artifact: Artifact to check
            rule: Validation rule dictionary
            
        Returns:
            True if rule passes, False otherwise
        """
        # Simple rule checking - can be extended
        rule_type = rule.get("type", "")
        
        if rule_type == "required_field":
            field_path = rule.get("field", "")
            return self._has_field(artifact.content, field_path)
        
        elif rule_type == "min_length":
            field_path = rule.get("field", "")
            min_length = rule.get("value", 0)
            field_value = self._get_field_value(artifact.content, field_path)
            if isinstance(field_value, str):
                return len(field_value) >= min_length
        
        elif rule_type == "format":
            field_path = rule.get("field", "")
            pattern = rule.get("pattern", "")
            field_value = self._get_field_value(artifact.content, field_path)
            if isinstance(field_value, str) and pattern:
                import re
                return bool(re.match(pattern, field_value))
        
        return True
    
    def _has_field(self, content: Dict[str, Any], field_path: str) -> bool:
        """Check if a field exists in content using dot notation."""
        parts = field_path.split('.')
        current = content
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False
        
        return True
    
    def _get_field_value(self, content: Dict[str, Any], field_path: str) -> Any:
        """Get field value from content using dot notation."""
        parts = field_path.split('.')
        current = content
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    
    def start_session(self, session_id: str, coordinator: Optional[AgentCoordinator] = None) -> None:
        """
        Start a new session for this agent.
        
        Args:
            session_id: Session identifier
            coordinator: Optional agent coordinator
        """
        self.session_id = session_id
        self.agent_status = "active"
        self.artifacts_created.clear()
        self.assigned_tasks.clear()
        
        # Initialize communication protocol
        self.communication = CommunicationProtocol(self.name, session_id)
        self._setup_communication_handlers()
        
        # Register with coordinator if provided
        if coordinator:
            self.coordinator = coordinator
            capabilities = self._get_capabilities()
            self.coordinator.register_agent(self.name, capabilities)
            logger.info(f"Registered with coordinator: {self.name}")
        
        # Publish agent started event
        if self.event_bus and self.session_id:
            self.event_bus.publish_agent_started(
                agent_name=self.name,
                session_id=self.session_id,
                source=self.name
            )
        
        logger.info(f"Started session {session_id} for agent {self.name}")
    
    def _setup_communication_handlers(self) -> None:
        """Setup communication message handlers."""
        if not self.communication:
            return
        
        # Register default message handlers
        self.communication.register_callable_handler(
            [MessageType.REQUEST],
            self._handle_request_message
        )
        
        self.communication.register_callable_handler(
            [MessageType.NOTIFICATION],
            self._handle_notification_message
        )
        
        # Setup callbacks
        self.communication.on_agent_discovered = self._on_agent_discovered
        self.communication.on_agent_lost = self._on_agent_lost
        self.communication.on_message_failed = self._on_message_failed
    
    def _handle_request_message(self, message: Message) -> Optional[Message]:
        """
        Handle request messages from other agents.
        
        Args:
            message: Request message
            
        Returns:
            Response message or None
        """
        request_type = message.payload.get("request_type", "unknown")
        
        if request_type == "status":
            return Message(
                id=str(uuid.uuid4()),
                type=MessageType.RESPONSE,
                sender=self.name,
                recipient=message.sender,
                payload={"status": self.get_agent_status()},
                timestamp=datetime.now(),
                session_id=self.session_id
            )
        
        elif request_type == "capabilities":
            return Message(
                id=str(uuid.uuid4()),
                type=MessageType.RESPONSE,
                sender=self.name,
                recipient=message.sender,
                payload={"capabilities": self._get_capabilities()},
                timestamp=datetime.now(),
                session_id=self.session_id
            )
        
        # Default response for unhandled requests
        return Message(
            id=str(uuid.uuid4()),
            type=MessageType.RESPONSE,
            sender=self.name,
            recipient=message.sender,
            payload={"error": f"Unknown request type: {request_type}"},
            timestamp=datetime.now(),
            session_id=self.session_id
        )
    
    def _handle_notification_message(self, message: Message) -> Optional[Message]:
        """
        Handle notification messages from other agents.
        
        Args:
            message: Notification message
            
        Returns:
            None (notifications don't require responses)
        """
        notification_type = message.payload.get("notification_type", "unknown")
        
        if notification_type == "task_completed":
            self._handle_task_completed_notification(message)
        elif notification_type == "artifact_updated":
            self._handle_artifact_updated_notification(message)
        
        return None
    
    def _handle_task_completed_notification(self, message: Message) -> None:
        """Handle task completed notification."""
        task_info = message.payload.get("task_info", {})
        logger.info(f"Agent {message.sender} completed task: {task_info.get('description', 'Unknown')}")
    
    def _handle_artifact_updated_notification(self, message: Message) -> None:
        """Handle artifact updated notification."""
        artifact_id = message.payload.get("artifact_id")
        changes = message.payload.get("changes", {})
        logger.info(f"Artifact {artifact_id} updated by {message.sender}: {changes}")
    
    def _on_agent_discovered(self, agent_name: str, agent_state) -> None:
        """Handle agent discovery."""
        logger.info(f"Discovered agent: {agent_name} (status: {agent_state.status})")
    
    def _on_agent_lost(self, agent_name: str) -> None:
        """Handle agent loss."""
        logger.warning(f"Lost connection to agent: {agent_name}")
    
    def _on_message_failed(self, message: Message, error: Exception) -> None:
        """Handle message delivery failure."""
        logger.error(f"Message delivery failed: {message.id} - {error}")
    
    def _get_capabilities(self) -> List[str]:
        """Get agent capabilities."""
        capabilities = [
            "knowledge_driven_reasoning",
            "chain_of_thought_processing",
            "artifact_validation"
        ]
        
        # Add knowledge module capabilities
        for module_id, module in self.knowledge_modules.items():
            capabilities.append(f"knowledge_{module.module_type.value}_{module_id}")
        
        return capabilities
    
    async def send_request_to_agent(self, recipient: str, request_type: str,
                                   data: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """
        Send a request to another agent and wait for response.
        
        Args:
            recipient: Recipient agent name
            request_type: Type of request
            data: Request data
            timeout: Response timeout
            
        Returns:
            Response data or None if failed
        """
        if not self.communication:
            logger.error("Communication protocol not initialized")
            return None
        
        payload = {
            "request_type": request_type,
            "data": data
        }
        
        response_message = await self.communication.send_request(
            recipient, payload, timeout
        )
        
        if response_message:
            return response_message.payload
        
        return None
    
    def notify_agent(self, recipient: str, notification_type: str, data: Dict[str, Any]) -> None:
        """
        Send a notification to another agent.
        
        Args:
            recipient: Recipient agent name
            notification_type: Type of notification
            data: Notification data
        """
        if not self.communication:
            logger.error("Communication protocol not initialized")
            return
        
        payload = {
            "notification_type": notification_type,
            "data": data
        }
        
        self.communication.send_notification(recipient, payload)
    
    def broadcast_notification(self, notification_type: str, data: Dict[str, Any]) -> None:
        """
        Broadcast a notification to all known agents.
        
        Args:
            notification_type: Type of notification
            data: Notification data
        """
        if not self.communication:
            logger.error("Communication protocol not initialized")
            return
        
        payload = {
            "notification_type": notification_type,
            "data": data
        }
        
        self.communication.broadcast_message(MessageType.NOTIFICATION, payload)
    
    async def start_communication(self) -> None:
        """Start async communication processing."""
        if self.communication:
            await self.communication.start_async_processing()
    
    async def stop_communication(self) -> None:
        """Stop async communication processing."""
        if self.communication:
            await self.communication.stop_async_processing()
    
    def register_with_coordinator(self, coordinator: AgentCoordinator) -> bool:
        """
        Register this agent with a coordinator.
        
        Args:
            coordinator: Agent coordinator instance
            
        Returns:
            True if registration successful
        """
        self.coordinator = coordinator
        capabilities = self._get_capabilities()
        return coordinator.register_agent(self.name, capabilities)
    
    def update_coordinator_state(self, load_level: Optional[float] = None, **metadata) -> None:
        """
        Update agent state in coordinator.
        
        Args:
            load_level: Current load level
            **metadata: Additional metadata
        """
        if self.coordinator:
            self.coordinator.update_agent_state(
                agent_name=self.name,
                status=self.agent_status,
                current_task=self.current_task,
                load_level=load_level,
                **metadata
            )
    
    def accept_task_assignment(self, task_id: str) -> bool:
        """
        Accept a task assignment from coordinator.
        
        Args:
            task_id: Task identifier
            
        Returns:
            True if task accepted
        """
        if not self.coordinator:
            return False
        
        # Get task details
        task_list = self.coordinator.get_task_list()
        task_data = next((t for t in task_list if t["id"] == task_id), None)
        
        if not task_data:
            return False
        
        # Check if we can handle this task
        task_requirements = task_data.get("requirements", [])
        our_capabilities = self._get_capabilities()
        
        if not all(req in our_capabilities for req in task_requirements):
            logger.warning(f"Cannot accept task {task_id}: missing capabilities")
            return False
        
        # Accept the task
        self.assigned_tasks.append(task_id)
        self.current_task = task_id
        self.agent_status = "busy"
        
        # Update coordinator
        self.update_coordinator_state(load_level=len(self.assigned_tasks) * 0.3)
        
        logger.info(f"Accepted task assignment: {task_id}")
        return True
    
    def complete_assigned_task(self, task_id: str, result: Optional[Dict[str, Any]] = None) -> bool:
        """
        Complete an assigned task.
        
        Args:
            task_id: Task identifier
            result: Optional task result
            
        Returns:
            True if task completed successfully
        """
        if task_id not in self.assigned_tasks:
            return False
        
        # Remove from assigned tasks
        self.assigned_tasks.remove(task_id)
        
        # Update status
        if not self.assigned_tasks:
            self.current_task = None
            self.agent_status = "available"
        else:
            self.current_task = self.assigned_tasks[0]
        
        # Notify coordinator
        if self.coordinator:
            success = self.coordinator.complete_task(task_id, self.name, result)
            if success:
                self.update_coordinator_state(load_level=len(self.assigned_tasks) * 0.3)
                logger.info(f"Completed task: {task_id}")
                return True
        
        return False
    
    def fail_assigned_task(self, task_id: str, error: str) -> bool:
        """
        Mark an assigned task as failed.
        
        Args:
            task_id: Task identifier
            error: Error description
            
        Returns:
            True if task marked as failed
        """
        if task_id not in self.assigned_tasks:
            return False
        
        # Remove from assigned tasks
        self.assigned_tasks.remove(task_id)
        
        # Update status
        if not self.assigned_tasks:
            self.current_task = None
            self.agent_status = "available"
        else:
            self.current_task = self.assigned_tasks[0]
        
        # Notify coordinator
        if self.coordinator:
            success = self.coordinator.fail_task(task_id, self.name, error)
            if success:
                self.update_coordinator_state(load_level=len(self.assigned_tasks) * 0.3)
                logger.error(f"Failed task: {task_id} - {error}")
                return True
        
        return False
    
    def submit_task_to_coordinator(self, task_type: str, description: str,
                                  requirements: List[str], priority: TaskPriority = TaskPriority.NORMAL,
                                  estimated_duration_minutes: int = 30,
                                  dependencies: Optional[List[str]] = None) -> Optional[str]:
        """
        Submit a task to the coordinator for assignment.
        
        Args:
            task_type: Type of task
            description: Task description
            requirements: Required capabilities
            priority: Task priority
            estimated_duration_minutes: Estimated duration in minutes
            dependencies: Optional task dependencies
            
        Returns:
            Task ID if submitted successfully
        """
        if not self.coordinator:
            logger.error("No coordinator available for task submission")
            return None
        
        from datetime import timedelta
        
        task = Task(
            id=str(uuid.uuid4()),
            type=task_type,
            description=description,
            requirements=requirements,
            priority=priority,
            estimated_duration=timedelta(minutes=estimated_duration_minutes),
            dependencies=dependencies or []
        )
        
        if self.coordinator.submit_task(task):
            logger.info(f"Submitted task to coordinator: {task.id}")
            return task.id
        
        return None
    
    def complete_task(self, task_description: str, artifacts: List[str]) -> None:
        """
        Mark a task as completed and publish completion event.
        
        Args:
            task_description: Description of completed task
            artifacts: List of artifact IDs created/modified
        """
        self.current_task = None
        self.artifacts_created.extend(artifacts)
        
        # Publish agent completed event
        if self.event_bus and self.session_id:
            self.event_bus.publish_agent_completed(
                agent_name=self.name,
                artifact_ids=artifacts,
                source=self.name,
                session_id=self.session_id
            )
        
        logger.info(f"Agent {self.name} completed task: {task_description}")
    
    def handle_failure(self, error: Exception, context: Dict[str, Any]) -> None:
        """
        Handle agent failure and publish failure event.
        
        Args:
            error: Exception that caused the failure
            context: Context information about the failure
        """
        self.agent_status = "failed"
        
        # Publish agent failed event
        if self.event_bus and self.session_id:
            from ..artifact.events import Event
            event = Event(
                id=str(uuid.uuid4()),
                type=EventType.AGENT_FAILED,
                source=self.name,
                target=None,
                payload={
                    "agent_name": self.name,
                    "error": str(error),
                    "context": context
                },
                timestamp=datetime.now(),
                session_id=self.session_id
            )
            self.event_bus.publish(event)
        
        logger.error(f"Agent {self.name} failed: {error}")
    
    # EventHandler implementation
    def can_handle(self, event_type: EventType) -> bool:
        """
        Check if this agent can handle the given event type.
        
        Args:
            event_type: Type of event
            
        Returns:
            True if agent can handle this event type
        """
        return event_type in self.handled_event_types
    
    def handle(self, event: Event) -> None:
        """
        Handle an event. To be implemented by specific agents.
        
        Args:
            event: Event to handle
        """
        logger.debug(f"Agent {self.name} received event: {event.type.value}")
        # Base implementation - specific agents should override
        pass
    
    def get_agent_status(self) -> Dict[str, Any]:
        """
        Get current agent status information.
        
        Returns:
            Status information dictionary
        """
        status = {
            "name": self.name,
            "status": self.agent_status,
            "session_id": self.session_id,
            "current_task": self.current_task,
            "knowledge_modules_loaded": list(self.knowledge_modules.keys()),
            "artifacts_created": self.artifacts_created,
            "active_reasoning_processes": list(self.active_reasoning_processes.keys())
        }
        
        # Add communication status if available
        if self.communication:
            comm_stats = self.communication.get_statistics()
            status["communication"] = {
                "known_agents": comm_stats["known_agents"],
                "message_queue_size": comm_stats["message_queue_size"],
                "pending_requests": comm_stats["pending_requests"],
                "is_running": comm_stats["is_running"]
            }
        
        return status
    
    @abstractmethod
    def process(self, *args, **kwargs) -> Any:
        """
        Process method to be implemented by specific agents.
        
        This method should implement the core functionality of the agent.
        """
        pass