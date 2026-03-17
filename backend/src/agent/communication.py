"""
Agent communication protocol for iReDev framework.
Provides message passing, async communication, and state synchronization.
"""

import asyncio
import json
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Union
import logging

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Types of messages in agent communication."""

    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    BROADCAST = "broadcast"
    STATE_SYNC = "state_sync"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    TASK_PROCESS = "task_process"


class MessagePriority(Enum):
    """Message priority levels."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class Message:
    """Represents a message between agents."""

    id: str
    type: MessageType
    sender: str
    recipient: Optional[str]  # None for broadcast messages
    payload: Dict[str, Any]
    timestamp: datetime
    session_id: str
    correlation_id: Optional[str] = None
    priority: MessagePriority = MessagePriority.NORMAL
    expires_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3

    def __post_init__(self):
        """Ensure ID is set if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "priority": self.priority.value,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create message from dictionary."""
        return cls(
            id=data["id"],
            type=MessageType(data["type"]),
            sender=data["sender"],
            recipient=data.get("recipient"),
            payload=data["payload"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            session_id=data["session_id"],
            correlation_id=data.get("correlation_id"),
            priority=MessagePriority(data.get("priority", 1)),
            expires_at=(
                datetime.fromisoformat(data["expires_at"])
                if data.get("expires_at")
                else None
            ),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
        )

    def is_expired(self) -> bool:
        """Check if message has expired."""
        return self.expires_at is not None and datetime.now() > self.expires_at

    def can_retry(self) -> bool:
        """Check if message can be retried."""
        return self.retry_count < self.max_retries

    def increment_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1


@dataclass
class AgentState:
    """Represents the state of an agent."""

    agent_name: str
    status: str
    current_task: Optional[str]
    capabilities: List[str]
    load_level: float  # 0.0 to 1.0
    last_heartbeat: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "agent_name": self.agent_name,
            "status": self.status,
            "current_task": self.current_task,
            "capabilities": self.capabilities,
            "load_level": self.load_level,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentState":
        """Create state from dictionary."""
        return cls(
            agent_name=data["agent_name"],
            status=data["status"],
            current_task=data.get("current_task"),
            capabilities=data["capabilities"],
            load_level=data["load_level"],
            last_heartbeat=datetime.fromisoformat(data["last_heartbeat"]),
            metadata=data.get("metadata", {}),
        )


class MessageHandler(ABC):
    """Abstract base class for message handlers."""

    @abstractmethod
    async def handle_message(self, message: Message) -> Optional[Message]:
        """
        Handle a message and optionally return a response.

        Args:
            message: Message to handle

        Returns:
            Optional response message
        """
        pass

    @abstractmethod
    def can_handle(self, message_type: MessageType) -> bool:
        """
        Check if this handler can handle the given message type.

        Args:
            message_type: Type of message

        Returns:
            True if handler can handle this message type
        """
        pass


class CallableMessageHandler(MessageHandler):
    """Message handler that wraps a callable function."""

    def __init__(
        self,
        handler_func: Callable[[Message], Optional[Message]],
        message_types: List[MessageType],
    ):
        self.handler_func = handler_func
        self.message_types = set(message_types)

    async def handle_message(self, message: Message) -> Optional[Message]:
        """Handle message by calling the wrapped function."""
        if asyncio.iscoroutinefunction(self.handler_func):
            return await self.handler_func(message)
        else:
            return self.handler_func(message)

    def can_handle(self, message_type: MessageType) -> bool:
        """Check if this handler can handle the given message type."""
        return message_type in self.message_types


class MessageQueue:
    """Thread-safe message queue with priority support."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._queues: Dict[MessagePriority, List[Message]] = {
            priority: [] for priority in MessagePriority
        }
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)

    def put(self, message: Message) -> bool:
        """
        Put a message in the queue.

        Args:
            message: Message to queue

        Returns:
            True if message was queued, False if queue is full
        """
        with self._condition:
            total_size = sum(len(queue) for queue in self._queues.values())

            if total_size >= self.max_size:
                # Remove oldest low priority message if possible
                if self._queues[MessagePriority.LOW]:
                    self._queues[MessagePriority.LOW].pop(0)
                else:
                    return False

            self._queues[message.priority].append(message)
            self._condition.notify()
            return True

    def get(self, timeout: Optional[float] = None) -> Optional[Message]:
        """
        Get the highest priority message from the queue.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Message or None if timeout occurred
        """
        with self._condition:
            end_time = None
            if timeout is not None:
                end_time = datetime.now().timestamp() + timeout

            while True:
                # Check for messages in priority order
                for priority in reversed(list(MessagePriority)):
                    if self._queues[priority]:
                        message = self._queues[priority].pop(0)
                        # Check if message is expired
                        if not message.is_expired():
                            return message

                # No messages available, wait
                if timeout is not None and end_time is not None:
                    remaining = end_time - datetime.now().timestamp()
                    if remaining <= 0:
                        return None
                    self._condition.wait(remaining)
                else:
                    self._condition.wait()

    def size(self) -> int:
        """Get total number of messages in queue."""
        with self._lock:
            return sum(len(queue) for queue in self._queues.values())

    def clear(self) -> None:
        """Clear all messages from queue."""
        with self._condition:
            for queue in self._queues.values():
                queue.clear()
            self._condition.notify_all()


class CommunicationProtocol:
    """
    Communication protocol for agent message passing and coordination.
    """

    def __init__(self, agent_name: str, session_id: str, coordinator):
        """
        Initialize communication protocol.

        Args:
            agent_name: Name of the agent
            session_id: Session identifier
        """
        from .coordination import AgentCoordinator
        from .knowledge_driven_agent import KnowledgeDrivenAgent

        self.agent_name = agent_name
        self.session_id = session_id
        self.coordinator: AgentCoordinator = coordinator

        # Agent management
        self.agent_instances: Dict[str, KnowledgeDrivenAgent] = {}

        # Message handling
        self.message_queue = MessageQueue()
        self.message_handlers: Dict[MessageType, List[MessageHandler]] = {}
        self.pending_requests: Dict[str, asyncio.Future] = {}

        # State management
        self.agent_state = AgentState(
            agent_name=agent_name,
            status="initialized",
            current_task=None,
            capabilities=[],
            load_level=0.0,
            last_heartbeat=datetime.now(),
        )

        # Communication state
        self.known_agents: Dict[str, AgentState] = {}
        self.message_history: List[Message] = []

        # Async processing
        self._running = False
        self._message_processor_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Callbacks
        self.on_agent_discovered: Optional[Callable[[str, AgentState], None]] = None
        self.on_agent_lost: Optional[Callable[[str], None]] = None
        self.on_message_failed: Optional[Callable[[Message, Exception], None]] = None

        logger.info(f"Initialized communication protocol for session: {session_id}")

    def register_agent_instance(self, agent_name: str, agent_instance):
        self.agent_instances[agent_name] = agent_instance
        self.coordinator.register_agent(
            agent_name=agent_name,
            capabilities=[agent_name],
            agent_instance=agent_instance,
            metadata={"instance": True},
        )
        logger.info(f"Registered agent instance: {agent_name}")

    def register_handler(
        self, message_type: MessageType, handler: MessageHandler
    ) -> None:
        """
        Register a message handler.

        Args:
            message_type: Type of message to handle
            handler: Message handler instance
        """
        if message_type not in self.message_handlers:
            self.message_handlers[message_type] = []

        self.message_handlers[message_type].append(handler)
        logger.debug(f"Registered handler for message type: {message_type.value}")

    def register_callable_handler(
        self,
        message_types: List[MessageType],
        handler_func: Callable[[Message], Optional[Message]],
    ) -> MessageHandler:
        """
        Register a callable function as a message handler.

        Args:
            message_types: List of message types to handle
            handler_func: Handler function

        Returns:
            Created message handler
        """
        handler = CallableMessageHandler(handler_func, message_types)

        for message_type in message_types:
            self.register_handler(message_type, handler)

        return handler

    def update_state(
        self,
        status: str,
        current_task: Optional[str] = None,
        load_level: Optional[float] = None,
        **metadata,
    ) -> None:
        """
        Update agent state.

        Args:
            status: Agent status
            current_task: Current task description
            load_level: Load level (0.0 to 1.0)
            **metadata: Additional metadata
        """
        self.agent_state.status = status
        if current_task is not None:
            self.agent_state.current_task = current_task
        if load_level is not None:
            self.agent_state.load_level = max(0.0, min(1.0, load_level))

        self.agent_state.metadata.update(metadata)
        self.agent_state.last_heartbeat = datetime.now()

        # Broadcast state update
        self.broadcast_state_sync()

    def send_message(
        self,
        recipient: str,
        message_type: MessageType,
        payload: Dict[str, Any],
        priority: MessagePriority = MessagePriority.NORMAL,
        correlation_id: Optional[str] = None,
    ) -> str:
        """
        Send a message to another agent.

        Args:
            recipient: Recipient agent name
            message_type: Type of message
            payload: Message payload
            priority: Message priority
            correlation_id: Optional correlation ID

        Returns:
            Message ID
        """
        message = Message(
            id=str(uuid.uuid4()),
            type=message_type,
            sender=self.agent_name,
            recipient=recipient,
            payload=payload,
            timestamp=datetime.now(),
            session_id=self.session_id,
            correlation_id=correlation_id,
            priority=priority,
        )

        # Add to message history
        self.message_history.append(message)

        # Queue for delivery (in real implementation, this would go to message broker)
        self._deliver_message(message)

        logger.debug(f"Sent {message_type.value} message to {recipient}: {message.id}")
        return message.id

    def broadcast_message(
        self,
        message_type: MessageType,
        payload: Dict[str, Any],
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> str:
        """
        Broadcast a message to all known agents.

        Args:
            message_type: Type of message
            payload: Message payload
            priority: Message priority

        Returns:
            Message ID
        """
        message = Message(
            id=str(uuid.uuid4()),
            type=message_type,
            sender=self.agent_name,
            recipient=None,  # Broadcast
            payload=payload,
            timestamp=datetime.now(),
            session_id=self.session_id,
            priority=priority,
        )

        # Add to message history
        self.message_history.append(message)

        # Deliver to all known agents
        for agent_name in self.known_agents:
            if agent_name != self.agent_name:
                self._deliver_message(message)

        logger.debug(f"Broadcast {message_type.value} message: {message.id}")
        return message.id

    def broadcast_state_sync(self) -> None:
        """Broadcast current agent state to all known agents."""
        self.broadcast_message(
            MessageType.STATE_SYNC,
            {"agent_state": self.agent_state.to_dict()},
            MessagePriority.LOW,
        )

    async def send_request(
        self, recipient: str, payload: Dict[str, Any], timeout: float = 30.0
    ) -> Optional[Message]:
        """
        Send a request and wait for response.

        Args:
            recipient: Recipient agent name
            payload: Request payload
            timeout: Response timeout in seconds

        Returns:
            Response message or None if timeout
        """
        correlation_id = str(uuid.uuid4())

        # Create future for response
        response_future = asyncio.Future()
        self.pending_requests[correlation_id] = response_future

        try:
            # Send request
            self.send_message(
                recipient=recipient,
                message_type=MessageType.REQUEST,
                payload=payload,
                correlation_id=correlation_id,
                priority=MessagePriority.HIGH,
            )

            # Wait for response
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            logger.warning(f"Request to {recipient} timed out after {timeout}s")
            return None
        finally:
            # Clean up
            self.pending_requests.pop(correlation_id, None)

    def send_response(self, original_message: Message, payload: Dict[str, Any]) -> str:
        """
        Send a response to a request message.

        Args:
            original_message: Original request message
            payload: Response payload

        Returns:
            Response message ID
        """
        return self.send_message(
            recipient=original_message.sender,
            message_type=MessageType.RESPONSE,
            payload=payload,
            correlation_id=original_message.id,
            priority=MessagePriority.HIGH,
        )

    def send_notification(self, recipient: str, payload: Dict[str, Any]) -> str:
        """
        Send a notification message.

        Args:
            recipient: Recipient agent name
            payload: Notification payload

        Returns:
            Message ID
        """
        return self.send_message(
            recipient=recipient,
            message_type=MessageType.NOTIFICATION,
            payload=payload,
            priority=MessagePriority.NORMAL,
        )

    def send_task_process(self, recipient: str, payload: Dict[str, Any]) -> str:
        return self.send_message(
            recipient=recipient,
            message_type=MessageType.TASK_PROCESS,
            payload=payload,
            priority=MessagePriority.HIGH,
        )

    def _deliver_message(self, message: Message) -> None:
        """
        Deliver a message (simulate message broker).
        In real implementation, this would send to message broker.

        Args:
            message: Message to deliver
        """
        # For now, just queue it locally for processing
        # In real implementation, this would go to a message broker
        if message.recipient == self.agent_name or message.recipient is None:
            self.message_queue.put(message)

    async def start_async_processing(self) -> None:
        """Start async message processing."""
        if self._running:
            return

        self._running = True

        # Start message processor
        self._message_processor_task = asyncio.create_task(self._process_messages())

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._send_heartbeats())

        logger.info(f"Started async processing for agent: {self.agent_name}")

    async def stop_async_processing(self) -> None:
        """Stop async message processing."""
        self._running = False

        # Cancel tasks
        if self._message_processor_task:
            self._message_processor_task.cancel()
            try:
                await self._message_processor_task
            except asyncio.CancelledError:
                pass

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        logger.info(f"Stopped async processing for agent: {self.agent_name}")

    async def _process_messages(self) -> None:
        """Process messages from the queue."""
        while self._running:
            try:
                # Get message with timeout
                await asyncio.sleep(0.1)
                message = self.message_queue.get(timeout=1.0)
                if message is None:
                    continue

                await self._handle_message(message)

            except Exception as e:
                logger.error(f"Error processing message: {e}")
                await asyncio.sleep(0.1)

    async def _handle_message(self, message: Message) -> None:
        """
        Handle a received message.

        Args:
            message: Message to handle
        """
        try:
            # Handle special message types
            if message.type == MessageType.STATE_SYNC:
                await self._handle_state_sync(message)
                return

            elif message.type == MessageType.HEARTBEAT:
                await self._handle_heartbeat(message)
                return

            elif message.type == MessageType.RESPONSE:
                await self._handle_response(message)
                return

            # Find handlers for this message type
            handlers = self.message_handlers.get(message.type, [])

            for handler in handlers:
                if handler.can_handle(message.type):
                    try:
                        response = await handler.handle_message(message)

                        # Send response if provided and original was a request
                        if response and message.type == MessageType.REQUEST:
                            self.send_response(message, response.payload)

                    except Exception as e:
                        logger.error(f"Error in message handler: {e}")

                        # Send error response for requests
                        if message.type == MessageType.REQUEST:
                            self.send_response(
                                message,
                                {"error": str(e), "error_type": type(e).__name__},
                            )

        except Exception as e:
            logger.error(f"Error handling message {message.id}: {e}")
            if self.on_message_failed:
                self.on_message_failed(message, e)

    async def _handle_state_sync(self, message: Message) -> None:
        """Handle state synchronization message."""
        agent_state_data = message.payload.get("agent_state")
        if agent_state_data:
            agent_state = AgentState.from_dict(agent_state_data)

            # Update known agents
            old_state = self.known_agents.get(agent_state.agent_name)
            self.known_agents[agent_state.agent_name] = agent_state

            # Notify if new agent discovered
            if not old_state and self.on_agent_discovered:
                self.on_agent_discovered(agent_state.agent_name, agent_state)

    async def _handle_heartbeat(self, message: Message) -> None:
        """Handle heartbeat message."""
        sender = message.sender
        if sender in self.known_agents:
            self.known_agents[sender].last_heartbeat = message.timestamp

    async def _handle_response(self, message: Message) -> None:
        """Handle response message."""
        correlation_id = message.correlation_id
        if correlation_id and correlation_id in self.pending_requests:
            future = self.pending_requests[correlation_id]
            if not future.done():
                future.set_result(message)

    async def _send_heartbeats(self) -> None:
        """Send periodic heartbeat messages."""
        while self._running:
            try:
                self.broadcast_message(
                    MessageType.HEARTBEAT,
                    {"timestamp": datetime.now().isoformat()},
                    MessagePriority.LOW,
                )

                # Check for lost agents
                current_time = datetime.now()
                lost_agents = []

                for agent_name, agent_state in self.known_agents.items():
                    time_since_heartbeat = current_time - agent_state.last_heartbeat
                    if time_since_heartbeat.total_seconds() > 60:  # 1 minute timeout
                        lost_agents.append(agent_name)

                # Remove lost agents
                for agent_name in lost_agents:
                    del self.known_agents[agent_name]
                    if self.on_agent_lost:
                        self.on_agent_lost(agent_name)

                await asyncio.sleep(30)  # Send heartbeat every 30 seconds

            except Exception as e:
                logger.error(f"Error sending heartbeat: {e}")
                await asyncio.sleep(5)

    def get_known_agents(self) -> Dict[str, AgentState]:
        """Get dictionary of known agents and their states."""
        return self.known_agents.copy()

    def get_message_history(self, limit: Optional[int] = None) -> List[Message]:
        """
        Get message history.

        Args:
            limit: Optional limit on number of messages

        Returns:
            List of messages
        """
        messages = self.message_history.copy()
        messages.sort(key=lambda m: m.timestamp, reverse=True)

        if limit:
            messages = messages[:limit]

        return messages

    def clear_message_history(self) -> None:
        """Clear message history."""
        self.message_history.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """Get communication statistics."""
        return {
            "agent_name": self.agent_name,
            "session_id": self.session_id,
            "known_agents": len(self.known_agents),
            "message_queue_size": self.message_queue.size(),
            "pending_requests": len(self.pending_requests),
            "message_history_size": len(self.message_history),
            "is_running": self._running,
            "agent_state": self.agent_state.to_dict(),
        }
