"""
Event system for the iReDev artifact pool.

This module provides event-driven communication mechanisms for artifact
changes and system coordination.
"""

import json
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path


class EventType(Enum):
    """Types of events in the iReDev system."""
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_UPDATED = "artifact_updated"
    ARTIFACT_DELETED = "artifact_deleted"
    ARTIFACT_STATUS_CHANGED = "artifact_status_changed"
    VERSION_CREATED = "version_created"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_COMPLETED = "review_completed"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    PROCESS_PAUSED = "process_paused"
    PROCESS_RESUMED = "process_resumed"
    HUMAN_FEEDBACK_RECEIVED = "human_feedback_received"


@dataclass
class Event:
    """Represents an event in the system."""
    id: str
    type: EventType
    source: str
    target: Optional[str]
    payload: Dict[str, Any]
    timestamp: datetime
    session_id: str
    correlation_id: Optional[str] = None
    
    def __post_init__(self):
        """Ensure ID is set if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            'id': self.id,
            'type': self.type.value,
            'source': self.source,
            'target': self.target,
            'payload': self.payload,
            'timestamp': self.timestamp.isoformat(),
            'session_id': self.session_id,
            'correlation_id': self.correlation_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """Create event from dictionary."""
        return cls(
            id=data['id'],
            type=EventType(data['type']),
            source=data['source'],
            target=data.get('target'),
            payload=data['payload'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            session_id=data['session_id'],
            correlation_id=data.get('correlation_id')
        )
    
    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Event':
        """Create event from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


class EventHandler(ABC):
    """Abstract base class for event handlers."""
    
    @abstractmethod
    def handle(self, event: Event) -> None:
        """Handle an event."""
        pass
    
    @abstractmethod
    def can_handle(self, event_type: EventType) -> bool:
        """Check if this handler can handle the given event type."""
        pass


class CallableEventHandler(EventHandler):
    """Event handler that wraps a callable function."""
    
    def __init__(self, handler_func: Callable[[Event], None], event_types: List[EventType]):
        self.handler_func = handler_func
        self.event_types = set(event_types)
    
    def handle(self, event: Event) -> None:
        """Handle an event by calling the wrapped function."""
        self.handler_func(event)
    
    def can_handle(self, event_type: EventType) -> bool:
        """Check if this handler can handle the given event type."""
        return event_type in self.event_types


class EventBus:
    """Event bus for publishing and subscribing to events."""
    
    def __init__(self, enable_persistence: bool = False, persistence_path: str = "events"):
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._event_history: List[Event] = []
        self._lock = threading.RLock()
        self._enable_persistence = enable_persistence
        self._persistence_path = Path(persistence_path) if enable_persistence else None
        
        if self._enable_persistence and self._persistence_path:
            self._persistence_path.mkdir(parents=True, exist_ok=True)
            self._load_persisted_events()
    
    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe a handler to an event type."""
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            
            if handler not in self._handlers[event_type]:
                self._handlers[event_type].append(handler)
    
    def subscribe_callable(self, event_types: List[EventType], 
                          handler_func: Callable[[Event], None]) -> EventHandler:
        """Subscribe a callable function to event types."""
        handler = CallableEventHandler(handler_func, event_types)
        
        for event_type in event_types:
            self.subscribe(event_type, handler)
        
        return handler
    
    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type."""
        with self._lock:
            if event_type in self._handlers and handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)
                
                # Clean up empty handler lists
                if not self._handlers[event_type]:
                    del self._handlers[event_type]
    
    def publish(self, event: Event) -> None:
        """Publish an event to all subscribed handlers."""
        with self._lock:
            # Add to history
            self._event_history.append(event)
            
            # Persist if enabled
            if self._enable_persistence:
                self._persist_event(event)
            
            # Notify handlers
            handlers = self._handlers.get(event.type, [])
            
            for handler in handlers:
                try:
                    if handler.can_handle(event.type):
                        handler.handle(event)
                except Exception as e:
                    # Log error but don't stop other handlers
                    print(f"Error in event handler: {e}")
    
    def publish_artifact_created(self, artifact_id: str, artifact_type: str, 
                                source: str, session_id: str) -> None:
        """Convenience method to publish artifact created event."""
        event = Event(
            id=str(uuid.uuid4()),
            type=EventType.ARTIFACT_CREATED,
            source=source,
            target=None,
            payload={
                'artifact_id': artifact_id,
                'artifact_type': artifact_type
            },
            timestamp=datetime.now(),
            session_id=session_id
        )
        self.publish(event)
    
    def publish_artifact_updated(self, artifact_id: str, changes: Dict[str, Any],
                                source: str, session_id: str) -> None:
        """Convenience method to publish artifact updated event."""
        event = Event(
            id=str(uuid.uuid4()),
            type=EventType.ARTIFACT_UPDATED,
            source=source,
            target=None,
            payload={
                'artifact_id': artifact_id,
                'changes': changes
            },
            timestamp=datetime.now(),
            session_id=session_id
        )
        self.publish(event)
    
    def publish_review_requested(self, artifact_id: str, reviewer: str,
                                source: str, session_id: str) -> None:
        """Convenience method to publish review requested event."""
        event = Event(
            id=str(uuid.uuid4()),
            type=EventType.REVIEW_REQUESTED,
            source=source,
            target=reviewer,
            payload={
                'artifact_id': artifact_id
            },
            timestamp=datetime.now(),
            session_id=session_id
        )
        self.publish(event)
    
    def publish_agent_started(self, agent_name: str, session_id: str, source: str) -> None:
        """Convenience method to publish agent started event."""
        event = Event(
            id=str(uuid.uuid4()),
            type=EventType.AGENT_STARTED,
            source=source,
            target=None,
            payload={
                'agent_name': agent_name
            },
            timestamp=datetime.now(),
            session_id=session_id
        )
        self.publish(event)
    
    def publish_agent_completed(self, agent_name: str, artifact_ids: List[str],
                               source: str, session_id: str) -> None:
        """Convenience method to publish agent completed event."""
        event = Event(
            id=str(uuid.uuid4()),
            type=EventType.AGENT_COMPLETED,
            source=source,
            target=None,
            payload={
                'agent_name': agent_name,
                'artifact_ids': artifact_ids
            },
            timestamp=datetime.now(),
            session_id=session_id
        )
        self.publish(event)
    
    def get_event_history(self, session_id: Optional[str] = None, 
                         event_type: Optional[EventType] = None,
                         limit: Optional[int] = None) -> List[Event]:
        """Get event history with optional filtering."""
        with self._lock:
            events = self._event_history.copy()
            
            # Filter by session
            if session_id:
                events = [e for e in events if e.session_id == session_id]
            
            # Filter by type
            if event_type:
                events = [e for e in events if e.type == event_type]
            
            # Sort by timestamp (newest first)
            events.sort(key=lambda e: e.timestamp, reverse=True)
            
            # Apply limit
            if limit:
                events = events[:limit]
            
            return events
    
    def replay_events(self, session_id: str, from_timestamp: Optional[datetime] = None) -> None:
        """Replay events for a session."""
        with self._lock:
            events = self.get_event_history(session_id)
            
            if from_timestamp:
                events = [e for e in events if e.timestamp >= from_timestamp]
            
            # Sort by timestamp (oldest first for replay)
            events.sort(key=lambda e: e.timestamp)
            
            for event in events:
                # Create a new event with current timestamp for replay
                replay_event = Event(
                    id=str(uuid.uuid4()),
                    type=event.type,
                    source=f"replay_{event.source}",
                    target=event.target,
                    payload=event.payload.copy(),
                    timestamp=datetime.now(),
                    session_id=session_id,
                    correlation_id=event.id
                )
                
                # Publish without adding to history again
                handlers = self._handlers.get(replay_event.type, [])
                for handler in handlers:
                    try:
                        if handler.can_handle(replay_event.type):
                            handler.handle(replay_event)
                    except Exception as e:
                        print(f"Error in event replay handler: {e}")
    
    def clear_history(self, session_id: Optional[str] = None) -> None:
        """Clear event history."""
        with self._lock:
            if session_id:
                self._event_history = [e for e in self._event_history if e.session_id != session_id]
            else:
                self._event_history.clear()
    
    def _persist_event(self, event: Event) -> None:
        """Persist an event to disk."""
        if not self._persistence_path:
            return
        
        try:
            # Create session directory
            session_dir = self._persistence_path / event.session_id
            session_dir.mkdir(exist_ok=True)
            
            # Write event to file
            event_file = session_dir / f"{event.timestamp.isoformat()}_{event.id}.json"
            with open(event_file, 'w', encoding='utf-8') as f:
                json.dump(event.to_dict(), f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"Failed to persist event {event.id}: {e}")
    
    def _load_persisted_events(self) -> None:
        """Load persisted events from disk."""
        if not self._persistence_path or not self._persistence_path.exists():
            return
        
        try:
            for session_dir in self._persistence_path.iterdir():
                if not session_dir.is_dir():
                    continue
                
                for event_file in session_dir.glob("*.json"):
                    try:
                        with open(event_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        event = Event.from_dict(data)
                        self._event_history.append(event)
                        
                    except Exception as e:
                        print(f"Failed to load event from {event_file}: {e}")
            
            # Sort by timestamp
            self._event_history.sort(key=lambda e: e.timestamp)
            
        except Exception as e:
            print(f"Failed to load persisted events: {e}")


# Global event bus instance
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def set_event_bus(event_bus: EventBus) -> None:
    """Set the global event bus instance."""
    global _global_event_bus
    _global_event_bus = event_bus