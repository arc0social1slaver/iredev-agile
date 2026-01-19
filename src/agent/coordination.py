"""
Agent coordination framework for iReDev system.
Provides agent registration, discovery, task allocation, load balancing, and conflict resolution.
"""

import asyncio
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Set, Tuple
import logging

from .communication import (
    CommunicationProtocol,
    Message,
    MessageType,
    MessagePriority,
    AgentState,
)

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of tasks in the coordination system."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Priority levels for tasks."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class ConflictType(Enum):
    """Types of conflicts that can occur."""

    RESOURCE_CONFLICT = "resource_conflict"
    TASK_DEPENDENCY = "task_dependency"
    AGENT_OVERLOAD = "agent_overload"
    DEADLINE_CONFLICT = "deadline_conflict"
    CAPABILITY_MISMATCH = "capability_mismatch"


@dataclass
class Task:
    """Represents a task in the coordination system."""

    id: str
    type: str
    description: str
    requirements: List[str]  # Required capabilities
    priority: TaskPriority
    estimated_duration: timedelta
    deadline: Optional[datetime] = None
    dependencies: List[str] = field(
        default_factory=list
    )  # Task IDs this task depends on
    assigned_agent: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    assigned_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3

    def __post_init__(self):
        """Ensure ID is set if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "requirements": self.requirements,
            "priority": self.priority.value,
            "estimated_duration": self.estimated_duration.total_seconds(),
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "dependencies": self.dependencies,
            "assigned_agent": self.assigned_agent,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "metadata": self.metadata,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create task from dictionary."""
        return cls(
            id=data["id"],
            type=data["type"],
            description=data["description"],
            requirements=data["requirements"],
            priority=TaskPriority(data["priority"]),
            estimated_duration=timedelta(seconds=data["estimated_duration"]),
            deadline=(
                datetime.fromisoformat(data["deadline"])
                if data.get("deadline")
                else None
            ),
            dependencies=data.get("dependencies", []),
            assigned_agent=data.get("assigned_agent"),
            status=TaskStatus(data.get("status", "pending")),
            created_at=datetime.fromisoformat(data["created_at"]),
            assigned_at=(
                datetime.fromisoformat(data["assigned_at"])
                if data.get("assigned_at")
                else None
            ),
            started_at=(
                datetime.fromisoformat(data["started_at"])
                if data.get("started_at")
                else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            metadata=data.get("metadata", {}),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
        )

    def can_be_assigned(self, completed_tasks: Set[str]) -> bool:
        """Check if task can be assigned (all dependencies completed)."""
        return all(dep_id in completed_tasks for dep_id in self.dependencies)

    def is_overdue(self) -> bool:
        """Check if task is overdue."""
        return self.deadline is not None and datetime.now() > self.deadline

    def can_retry(self) -> bool:
        """Check if task can be retried."""
        return self.retry_count < self.max_retries


@dataclass
class Conflict:
    """Represents a conflict in the coordination system."""

    id: str
    type: ConflictType
    description: str
    involved_agents: List[str]
    involved_tasks: List[str]
    severity: int  # 1-10 scale
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    resolution: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure ID is set if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def is_resolved(self) -> bool:
        """Check if conflict is resolved."""
        return self.resolved_at is not None

    def to_dict(self) -> Dict[str, Any]:
        """Convert conflict to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "involved_agents": self.involved_agents,
            "involved_tasks": self.involved_tasks,
            "severity": self.severity,
            "detected_at": self.detected_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution": self.resolution,
            "metadata": self.metadata,
        }


class LoadBalancer(ABC):
    """Abstract base class for load balancing strategies."""

    @abstractmethod
    def select_agent(
        self, task: Task, available_agents: Dict[str, AgentState]
    ) -> Optional[str]:
        """
        Select the best agent for a task.

        Args:
            task: Task to assign
            available_agents: Available agents and their states

        Returns:
            Selected agent name or None if no suitable agent
        """
        pass


class RoundRobinLoadBalancer(LoadBalancer):
    """Round-robin load balancing strategy."""

    def __init__(self):
        self._last_assigned: Dict[str, int] = {}  # task_type -> agent_index

    def select_agent(
        self, task: Task, available_agents: Dict[str, AgentState]
    ) -> Optional[str]:
        """Select agent using round-robin strategy."""
        # Filter agents that can handle this task
        suitable_agents = []
        for agent_name, agent_state in available_agents.items():
            if self._can_handle_task(task, agent_state):
                suitable_agents.append(agent_name)

        if not suitable_agents:
            return None

        # Round-robin selection
        task_type = task.type
        last_index = self._last_assigned.get(task_type, -1)
        next_index = (last_index + 1) % len(suitable_agents)

        self._last_assigned[task_type] = next_index
        return suitable_agents[next_index]

    def _can_handle_task(self, task: Task, agent_state: AgentState) -> bool:
        """Check if agent can handle the task."""
        # Check if agent has required capabilities
        for requirement in task.requirements:
            if requirement not in agent_state.capabilities:
                return False

        # Check if agent is not overloaded
        if agent_state.load_level > 0.8:
            return False

        return True


class LeastLoadedLoadBalancer(LoadBalancer):
    """Least loaded load balancing strategy."""

    def select_agent(
        self, task: Task, available_agents: Dict[str, AgentState]
    ) -> Optional[str]:
        """Select agent with lowest load."""
        suitable_agents = []

        for agent_name, agent_state in available_agents.items():
            if self._can_handle_task(task, agent_state):
                suitable_agents.append((agent_name, agent_state.load_level))

        if not suitable_agents:
            return None

        # Sort by load level (ascending)
        suitable_agents.sort(key=lambda x: x[1])
        return suitable_agents[0][0]

    def _can_handle_task(self, task: Task, agent_state: AgentState) -> bool:
        """Check if agent can handle the task."""
        # Check if agent has required capabilities
        for requirement in task.requirements:
            if requirement not in agent_state.capabilities:
                return False

        # Check if agent is not overloaded
        if agent_state.load_level > 0.9:
            return False

        return True


class PriorityLoadBalancer(LoadBalancer):
    """Priority-based load balancing strategy."""

    def select_agent(
        self, task: Task, available_agents: Dict[str, AgentState]
    ) -> Optional[str]:
        """Select best agent based on task priority and agent capabilities."""
        suitable_agents = []

        for agent_name, agent_state in available_agents.items():
            if self._can_handle_task(task, agent_state):
                # Calculate agent score based on load and capabilities
                capability_score = self._calculate_capability_score(task, agent_state)
                load_score = 1.0 - agent_state.load_level
                overall_score = (capability_score * 0.7) + (load_score * 0.3)

                suitable_agents.append((agent_name, overall_score))

        if not suitable_agents:
            return None

        # Sort by score (descending)
        suitable_agents.sort(key=lambda x: x[1], reverse=True)
        return suitable_agents[0][0]

    def _can_handle_task(self, task: Task, agent_state: AgentState) -> bool:
        """Check if agent can handle the task."""
        # Check if agent has required capabilities
        for requirement in task.requirements:
            if requirement not in agent_state.capabilities:
                return False

        # Allow higher load for urgent tasks
        max_load = 0.95 if task.priority == TaskPriority.URGENT else 0.8
        if agent_state.load_level > max_load:
            return False

        return True

    def _calculate_capability_score(self, task: Task, agent_state: AgentState) -> float:
        """Calculate how well agent capabilities match task requirements."""
        if not task.requirements:
            return 1.0

        matched_capabilities = 0
        for requirement in task.requirements:
            if requirement in agent_state.capabilities:
                matched_capabilities += 1

        return matched_capabilities / len(task.requirements)


class ConflictResolver:
    """Handles conflict detection and resolution."""

    def __init__(self):
        self.resolution_strategies: Dict[
            ConflictType, Callable[[Conflict, Dict[str, Any]], str]
        ] = {
            ConflictType.RESOURCE_CONFLICT: self._resolve_resource_conflict,
            ConflictType.TASK_DEPENDENCY: self._resolve_dependency_conflict,
            ConflictType.AGENT_OVERLOAD: self._resolve_overload_conflict,
            ConflictType.DEADLINE_CONFLICT: self._resolve_deadline_conflict,
            ConflictType.CAPABILITY_MISMATCH: self._resolve_capability_conflict,
        }

    def detect_conflicts(
        self, tasks: Dict[str, Task], agents: Dict[str, AgentState]
    ) -> List[Conflict]:
        """Detect conflicts in the current system state."""
        conflicts = []

        # Detect agent overload conflicts
        conflicts.extend(self._detect_overload_conflicts(tasks, agents))

        # Detect deadline conflicts
        conflicts.extend(self._detect_deadline_conflicts(tasks))

        # Detect dependency conflicts
        conflicts.extend(self._detect_dependency_conflicts(tasks))

        # Detect capability mismatches
        conflicts.extend(self._detect_capability_conflicts(tasks, agents))

        return conflicts

    def resolve_conflict(self, conflict: Conflict, context: Dict[str, Any]) -> str:
        """Resolve a conflict using appropriate strategy."""
        resolver = self.resolution_strategies.get(conflict.type)
        if resolver:
            resolution = resolver(conflict, context)
            conflict.resolved_at = datetime.now()
            conflict.resolution = resolution
            return resolution
        else:
            return f"No resolution strategy for conflict type: {conflict.type.value}"

    def _detect_overload_conflicts(
        self, tasks: Dict[str, Task], agents: Dict[str, AgentState]
    ) -> List[Conflict]:
        """Detect agent overload conflicts."""
        conflicts = []

        for agent_name, agent_state in agents.items():
            if agent_state.load_level > 0.9:
                # Find tasks assigned to this overloaded agent
                assigned_tasks = [
                    task_id
                    for task_id, task in tasks.items()
                    if task.assigned_agent == agent_name
                    and task.status in [TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS]
                ]

                if assigned_tasks:
                    conflict = Conflict(
                        id=str(uuid.uuid4()),
                        type=ConflictType.AGENT_OVERLOAD,
                        description=f"Agent {agent_name} is overloaded (load: {agent_state.load_level:.2f})",
                        involved_agents=[agent_name],
                        involved_tasks=assigned_tasks,
                        severity=min(10, int(agent_state.load_level * 10)),
                        detected_at=datetime.now(),
                    )
                    conflicts.append(conflict)

        return conflicts

    def _detect_deadline_conflicts(self, tasks: Dict[str, Task]) -> List[Conflict]:
        """Detect deadline conflicts."""
        conflicts = []

        for task_id, task in tasks.items():
            if task.is_overdue() and task.status not in [
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
            ]:
                conflict = Conflict(
                    id=str(uuid.uuid4()),
                    type=ConflictType.DEADLINE_CONFLICT,
                    description=f"Task {task_id} is overdue (deadline: {task.deadline})",
                    involved_agents=(
                        [task.assigned_agent] if task.assigned_agent else []
                    ),
                    involved_tasks=[task_id],
                    severity=8,
                    detected_at=datetime.now(),
                )
                conflicts.append(conflict)

        return conflicts

    def _detect_dependency_conflicts(self, tasks: Dict[str, Task]) -> List[Conflict]:
        """Detect task dependency conflicts."""
        conflicts = []

        for task_id, task in tasks.items():
            if task.status == TaskStatus.ASSIGNED:
                # Check if dependencies are satisfied
                for dep_id in task.dependencies:
                    dep_task = tasks.get(dep_id)
                    if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                        conflict = Conflict(
                            id=str(uuid.uuid4()),
                            type=ConflictType.TASK_DEPENDENCY,
                            description=f"Task {task_id} depends on incomplete task {dep_id}",
                            involved_agents=(
                                [task.assigned_agent] if task.assigned_agent else []
                            ),
                            involved_tasks=[task_id, dep_id],
                            severity=6,
                            detected_at=datetime.now(),
                        )
                        conflicts.append(conflict)

        return conflicts

    def _detect_capability_conflicts(
        self, tasks: Dict[str, Task], agents: Dict[str, AgentState]
    ) -> List[Conflict]:
        """Detect capability mismatch conflicts."""
        conflicts = []

        for task_id, task in tasks.items():
            if task.assigned_agent:
                agent_state = agents.get(task.assigned_agent)
                if agent_state:
                    missing_capabilities = []
                    for requirement in task.requirements:
                        if requirement not in agent_state.capabilities:
                            missing_capabilities.append(requirement)

                    if missing_capabilities:
                        conflict = Conflict(
                            id=str(uuid.uuid4()),
                            type=ConflictType.CAPABILITY_MISMATCH,
                            description=f"Agent {task.assigned_agent} lacks capabilities: {missing_capabilities}",
                            involved_agents=[task.assigned_agent],
                            involved_tasks=[task_id],
                            severity=7,
                            detected_at=datetime.now(),
                            metadata={"missing_capabilities": missing_capabilities},
                        )
                        conflicts.append(conflict)

        return conflicts

    def _resolve_resource_conflict(
        self, conflict: Conflict, context: Dict[str, Any]
    ) -> str:
        """Resolve resource conflicts."""
        return "Redistributed resources among conflicting agents"

    def _resolve_dependency_conflict(
        self, conflict: Conflict, context: Dict[str, Any]
    ) -> str:
        """Resolve dependency conflicts."""
        return "Reordered task execution to satisfy dependencies"

    def _resolve_overload_conflict(
        self, conflict: Conflict, context: Dict[str, Any]
    ) -> str:
        """Resolve agent overload conflicts."""
        return "Redistributed tasks to balance agent load"

    def _resolve_deadline_conflict(
        self, conflict: Conflict, context: Dict[str, Any]
    ) -> str:
        """Resolve deadline conflicts."""
        return "Escalated task priority and reallocated resources"

    def _resolve_capability_conflict(
        self, conflict: Conflict, context: Dict[str, Any]
    ) -> str:
        """Resolve capability mismatch conflicts."""
        return "Reassigned task to agent with required capabilities"


class AgentCoordinator:
    """
    Central coordinator for agent registration, discovery, and task management.
    """

    def __init__(self, session_id: str, load_balancer: Optional[LoadBalancer] = None):
        """
        Initialize the agent coordinator.

        Args:
            session_id: Session identifier
            load_balancer: Load balancing strategy
        """
        from .knowledge_driven_agent import KnowledgeDrivenAgent

        self.session_id = session_id
        self.load_balancer = load_balancer or PriorityLoadBalancer()
        self.conflict_resolver = ConflictResolver()

        # Agent registry
        self.registered_agents: Dict[str, AgentState] = {}
        self.agent_capabilities: Dict[str, List[str]] = {}

        # Task management
        self.tasks: Dict[str, Task] = {}
        self.task_queue: List[str] = []  # Task IDs in priority order
        self.completed_tasks: Set[str] = set()

        # Conflict management
        self.active_conflicts: Dict[str, Conflict] = {}
        self.resolved_conflicts: List[Conflict] = []
        self.agent_instances: Dict[str, KnowledgeDrivenAgent] = {}

        # Coordination state
        self._running = False
        self._coordination_task: Optional[asyncio.Task] = None
        self._lock = threading.RLock()

        # Callbacks
        self.on_task_assigned: Optional[Callable[[str, str], None]] = (
            None  # task_id, agent_name
        )
        self.on_task_completed: Optional[Callable[[str, str], None]] = (
            None  # task_id, agent_name
        )
        self.on_conflict_detected: Optional[Callable[[Conflict], None]] = None
        self.on_conflict_resolved: Optional[Callable[[Conflict], None]] = None

        logger.info(f"Initialized agent coordinator for session: {session_id}")

    def register_agent(
        self,
        agent_name: str,
        capabilities: List[str],
        agent_instance: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Register an agent with the coordinator.

        Args:
            agent_name: Name of the agent
            capabilities: List of agent capabilities
            metadata: Optional metadata

        Returns:
            True if registration successful
        """
        with self._lock:
            if agent_name in self.registered_agents:
                logger.warning(f"Agent {agent_name} already registered")
                return False

            agent_state = AgentState(
                agent_name=agent_name,
                status="available",
                current_task=None,
                capabilities=capabilities,
                load_level=0.0,
                last_heartbeat=datetime.now(),
                metadata=metadata or {},
            )

            self.registered_agents[agent_name] = agent_state
            self.agent_capabilities[agent_name] = capabilities
            self.agent_instances[agent_name] = agent_instance

            logger.info(
                f"Registered agent: {agent_name} with capabilities: {capabilities}, instance: {agent_instance}"
            )
            return True

    def unregister_agent(self, agent_name: str) -> bool:
        """
        Unregister an agent from the coordinator.

        Args:
            agent_name: Name of the agent

        Returns:
            True if unregistration successful
        """
        with self._lock:
            if agent_name not in self.registered_agents:
                return False

            # Reassign tasks from this agent
            self._reassign_agent_tasks(agent_name)

            # Remove from registry
            del self.registered_agents[agent_name]
            del self.agent_capabilities[agent_name]
            del self.agent_instances[agent_name]

            logger.info(f"Unregistered agent: {agent_name}")
            return True

    def update_agent_state(
        self,
        agent_name: str,
        status: str,
        current_task: Optional[str] = None,
        load_level: Optional[float] = None,
        **metadata,
    ) -> bool:
        """
        Update agent state information.

        Args:
            agent_name: Name of the agent
            status: Agent status
            current_task: Current task
            load_level: Load level
            **metadata: Additional metadata

        Returns:
            True if update successful
        """
        with self._lock:
            if agent_name not in self.registered_agents:
                return False

            agent_state = self.registered_agents[agent_name]
            agent_state.status = status
            if current_task is not None:
                agent_state.current_task = current_task
            if load_level is not None:
                agent_state.load_level = max(0.0, min(1.0, load_level))

            agent_state.metadata.update(metadata)
            agent_state.last_heartbeat = datetime.now()

            return True

    def submit_task(self, task: Task) -> bool:
        """
        Submit a task for execution.

        Args:
            task: Task to submit

        Returns:
            True if task submitted successfully
        """
        with self._lock:
            if task.id in self.tasks:
                logger.warning(f"Task {task.id} already exists")
                return False

            self.tasks[task.id] = task
            self._insert_task_in_queue(task.id)

            logger.info(f"Submitted task: {task.id} ({task.type})")
            return True

    def _insert_task_in_queue(self, task_id: str) -> None:
        """Insert task in queue based on priority."""
        task = self.tasks[task_id]

        # Find insertion point based on priority
        insert_index = len(self.task_queue)
        for i, queued_task_id in enumerate(self.task_queue):
            queued_task = self.tasks[queued_task_id]
            if task.priority.value > queued_task.priority.value:
                insert_index = i
                break

        self.task_queue.insert(insert_index, task_id)

    async def assign_tasks(self) -> List[Tuple[str, str]]:
        """
        Assign pending tasks to available agents.

        Returns:
            List of (task_id, agent_name) assignments
        """
        assignments = []

        with self._lock:
            # Get available agents
            available_agents = {
                name: state
                for name, state in self.registered_agents.items()
                if state.status == "available" and state.load_level < 0.8
            }

            if not available_agents:
                logger.info(f"Registered agents: {self.registered_agents}")
                return assignments

            # Process task queue
            remaining_tasks = []

            for task_id in self.task_queue:
                task = self.tasks[task_id]

                # Skip if already assigned or not ready
                if task.status != TaskStatus.PENDING:
                    continue

                # Check if dependencies are satisfied
                if not task.can_be_assigned(self.completed_tasks):
                    remaining_tasks.append(task_id)
                    continue

                # Try to assign task
                selected_agent = self.load_balancer.select_agent(task, available_agents)

                if selected_agent:

                    agent_instance = self.agent_instances.get(selected_agent)

                    if not agent_instance:
                        logger.error(f"No agent instance found for {selected_agent}")
                        remaining_tasks.append(task_id)
                        continue

                    # Assign task
                    task.assigned_agent = selected_agent
                    task.status = TaskStatus.ASSIGNED
                    task.assigned_at = datetime.now()

                    # Update agent state
                    agent_state = available_agents[selected_agent]
                    agent_state.current_task = task_id
                    agent_state.load_level = min(1.0, agent_state.load_level + 0.2)

                    assignments.append((task_id, selected_agent))

                    # Remove from available agents if overloaded
                    if agent_state.load_level >= 0.8:
                        del available_agents[selected_agent]

                    # Callback
                    if self.on_task_assigned:
                        self.on_task_assigned(task_id, selected_agent)

                    logger.info(f"Assigned task {task_id} to agent {selected_agent}")
                else:
                    remaining_tasks.append(task_id)

            # Update task queue
            self.task_queue = remaining_tasks

        return assignments

    def complete_task(
        self, task_id: str, agent_name: str, result: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Mark a task as completed.

        Args:
            task_id: Task identifier
            agent_name: Agent that completed the task
            result: Optional task result

        Returns:
            True if task marked as completed
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.assigned_agent != agent_name:
                return False

            # Update task
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            if result:
                task.metadata.update(result)

            # Update agent state
            agent_state = self.registered_agents.get(agent_name)
            if agent_state:
                agent_state.current_task = None
                agent_state.load_level = max(0.0, agent_state.load_level - 0.2)

            # Add to completed tasks
            self.completed_tasks.add(task_id)

            # Callback
            if self.on_task_completed:
                self.on_task_completed(task_id, agent_name)

            logger.info(f"Task {task_id} completed by agent {agent_name}")
            return True

    def fail_task(self, task_id: str, agent_name: str, error: str) -> bool:
        """
        Mark a task as failed.

        Args:
            task_id: Task identifier
            agent_name: Agent that failed the task
            error: Error description

        Returns:
            True if task marked as failed
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.assigned_agent != agent_name:
                return False

            # Update task
            task.status = TaskStatus.FAILED
            task.metadata["error"] = error
            task.retry_count += 1

            # Update agent state
            agent_state = self.registered_agents.get(agent_name)
            if agent_state:
                agent_state.current_task = None
                agent_state.load_level = max(0.0, agent_state.load_level - 0.2)

            # Retry if possible
            if task.can_retry():
                task.status = TaskStatus.PENDING
                task.assigned_agent = None
                task.assigned_at = None
                self._insert_task_in_queue(task_id)
                logger.info(
                    f"Task {task_id} failed, retrying (attempt {task.retry_count})"
                )
            else:
                logger.error(f"Task {task_id} failed permanently: {error}")

            return True

    def _reassign_agent_tasks(self, agent_name: str) -> None:
        """Reassign tasks from a disconnected agent."""
        for task_id, task in self.tasks.items():
            if task.assigned_agent == agent_name and task.status in [
                TaskStatus.ASSIGNED,
                TaskStatus.IN_PROGRESS,
            ]:
                task.status = TaskStatus.PENDING
                task.assigned_agent = None
                task.assigned_at = None
                self._insert_task_in_queue(task_id)
                logger.info(
                    f"Reassigned task {task_id} due to agent {agent_name} disconnection"
                )

    async def start_coordination(self) -> None:
        """Start the coordination loop."""
        if self._running:
            return

        self._running = True
        self._coordination_task = asyncio.create_task(self._coordination_loop())
        logger.info("Started agent coordination")

    async def stop_coordination(self) -> None:
        """Stop the coordination loop."""
        self._running = False

        if self._coordination_task:
            self._coordination_task.cancel()
            try:
                await self._coordination_task
            except asyncio.CancelledError:
                pass

        logger.info("Stopped agent coordination")

    async def _coordination_loop(self) -> None:
        """Main coordination loop."""
        while self._running:
            try:
                # Assign pending tasks
                assignments = self.assign_tasks()

                # Detect and resolve conflicts
                conflicts = self.conflict_resolver.detect_conflicts(
                    self.tasks, self.registered_agents
                )

                for conflict in conflicts:
                    if conflict.id not in self.active_conflicts:
                        self.active_conflicts[conflict.id] = conflict

                        # Callback
                        if self.on_conflict_detected:
                            self.on_conflict_detected(conflict)

                        # Try to resolve
                        context = {
                            "tasks": self.tasks,
                            "agents": self.registered_agents,
                            "coordinator": self,
                        }

                        resolution = self.conflict_resolver.resolve_conflict(
                            conflict, context
                        )

                        # Move to resolved conflicts
                        del self.active_conflicts[conflict.id]
                        self.resolved_conflicts.append(conflict)

                        # Callback
                        if self.on_conflict_resolved:
                            self.on_conflict_resolved(conflict)

                        logger.info(f"Resolved conflict {conflict.id}: {resolution}")

                # Clean up old agents (no heartbeat for 2 minutes)
                current_time = datetime.now()
                disconnected_agents = []

                for agent_name, agent_state in self.registered_agents.items():
                    time_since_heartbeat = current_time - agent_state.last_heartbeat
                    if time_since_heartbeat > timedelta(minutes=2):
                        disconnected_agents.append(agent_name)

                for agent_name in disconnected_agents:
                    self.unregister_agent(agent_name)
                    logger.warning(f"Removed disconnected agent: {agent_name}")

                await asyncio.sleep(5)  # Coordination cycle every 5 seconds

            except Exception as e:
                logger.error(f"Error in coordination loop: {e}")
                await asyncio.sleep(1)

    def get_coordination_status(self) -> Dict[str, Any]:
        """Get current coordination status."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "registered_agents": len(self.registered_agents),
                "total_tasks": len(self.tasks),
                "pending_tasks": len(
                    [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
                ),
                "assigned_tasks": len(
                    [t for t in self.tasks.values() if t.status == TaskStatus.ASSIGNED]
                ),
                "in_progress_tasks": len(
                    [
                        t
                        for t in self.tasks.values()
                        if t.status == TaskStatus.IN_PROGRESS
                    ]
                ),
                "completed_tasks": len(self.completed_tasks),
                "active_conflicts": len(self.active_conflicts),
                "resolved_conflicts": len(self.resolved_conflicts),
                "is_running": self._running,
            }

    def get_agent_list(self) -> List[Dict[str, Any]]:
        """Get list of registered agents."""
        with self._lock:
            return [
                {
                    "name": agent_name,
                    "status": agent_state.status,
                    "current_task": agent_state.current_task,
                    "load_level": agent_state.load_level,
                    "capabilities": agent_state.capabilities,
                    "last_heartbeat": agent_state.last_heartbeat.isoformat(),
                }
                for agent_name, agent_state in self.registered_agents.items()
            ]

    def get_task_list(
        self, status_filter: Optional[TaskStatus] = None
    ) -> List[Dict[str, Any]]:
        """Get list of tasks."""
        with self._lock:
            tasks = list(self.tasks.values())

            if status_filter:
                tasks = [t for t in tasks if t.status == status_filter]

            return [task.to_dict() for task in tasks]
