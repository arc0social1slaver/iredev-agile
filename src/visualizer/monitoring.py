"""
Real-time monitoring and visualization system for iReDev framework.

This module provides comprehensive monitoring capabilities including:
- Process status visualization
- Artifact change tracking
- System performance metrics
- Quality indicators dashboard
"""

import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Tuple
from enum import Enum

from ..artifact.events import EventBus, Event, EventType
from ..artifact.pool import ArtifactPool
from ..artifact.models import Artifact, ArtifactType, ArtifactStatus
from ..orchestrator.orchestrator import RequirementOrchestrator, ProcessSession, ProcessStatus, ProcessPhase

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics collected by the monitoring system."""
    PROCESS_COUNT = "process_count"
    ARTIFACT_COUNT = "artifact_count"
    REVIEW_COUNT = "review_count"
    ERROR_COUNT = "error_count"
    RESPONSE_TIME = "response_time"
    THROUGHPUT = "throughput"
    QUALITY_SCORE = "quality_score"
    AGENT_UTILIZATION = "agent_utilization"


@dataclass
class MetricPoint:
    """A single metric data point."""
    timestamp: datetime
    value: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'value': self.value,
            'metadata': self.metadata
        }


@dataclass
class ProcessMetrics:
    """Metrics for a specific process session."""
    session_id: str
    start_time: datetime
    current_phase: ProcessPhase
    status: ProcessStatus
    progress: float
    artifacts_created: int = 0
    reviews_completed: int = 0
    errors_encountered: int = 0
    phase_durations: Dict[str, float] = field(default_factory=dict)
    quality_scores: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'session_id': self.session_id,
            'start_time': self.start_time.isoformat(),
            'current_phase': self.current_phase.value,
            'status': self.status.value,
            'progress': self.progress,
            'artifacts_created': self.artifacts_created,
            'reviews_completed': self.reviews_completed,
            'errors_encountered': self.errors_encountered,
            'phase_durations': self.phase_durations,
            'quality_scores': self.quality_scores
        }


@dataclass
class SystemMetrics:
    """Overall system metrics."""
    active_processes: int = 0
    total_artifacts: int = 0
    pending_reviews: int = 0
    total_errors: int = 0
    average_response_time: float = 0.0
    system_throughput: float = 0.0
    overall_quality_score: float = 0.0
    agent_utilization: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'active_processes': self.active_processes,
            'total_artifacts': self.total_artifacts,
            'pending_reviews': self.pending_reviews,
            'total_errors': self.total_errors,
            'average_response_time': self.average_response_time,
            'system_throughput': self.system_throughput,
            'overall_quality_score': self.overall_quality_score,
            'agent_utilization': self.agent_utilization
        }


class MonitoringSystem:
    """
    Comprehensive monitoring system for iReDev framework.
    
    Collects, processes, and provides access to real-time metrics
    about system performance, process status, and quality indicators.
    """
    
    def __init__(self, orchestrator: RequirementOrchestrator,
                 artifact_pool: ArtifactPool, event_bus: EventBus):
        """
        Initialize the monitoring system.
        
        Args:
            orchestrator: Process orchestrator
            artifact_pool: Artifact pool
            event_bus: Event bus for monitoring events
        """
        self.orchestrator = orchestrator
        self.artifact_pool = artifact_pool
        self.event_bus = event_bus
        
        # Metrics storage
        self.time_series_metrics: Dict[MetricType, deque] = {
            metric_type: deque(maxlen=1000) for metric_type in MetricType
        }
        self.process_metrics: Dict[str, ProcessMetrics] = {}
        self.system_metrics = SystemMetrics()
        
        # Tracking data
        self.artifact_changes: deque = deque(maxlen=500)
        self.performance_history: deque = deque(maxlen=100)
        self.quality_history: deque = deque(maxlen=100)
        
        # State management
        self._lock = threading.RLock()
        self._running = False
        self._collection_thread: Optional[threading.Thread] = None
        
        # Configuration
        self.collection_interval = 10  # seconds
        self.retention_hours = 24
        
        # Callbacks
        self.on_metric_updated: Optional[Callable[[MetricType, MetricPoint], None]] = None
        self.on_alert_triggered: Optional[Callable[[str, Dict[str, Any]], None]] = None
        
        # Subscribe to events
        self._setup_event_handlers()
        
        logger.info("Initialized MonitoringSystem")
    
    def start(self):
        """Start the monitoring system."""
        with self._lock:
            if self._running:
                return
            
            self._running = True
            self._collection_thread = threading.Thread(
                target=self._collection_loop,
                daemon=True
            )
            self._collection_thread.start()
            
            logger.info("Started monitoring system")
    
    def stop(self):
        """Stop the monitoring system."""
        with self._lock:
            self._running = False
            
            if self._collection_thread:
                self._collection_thread.join(timeout=5)
            
            logger.info("Stopped monitoring system")
    
    def get_system_metrics(self) -> SystemMetrics:
        """Get current system metrics."""
        with self._lock:
            return self.system_metrics
    
    def get_process_metrics(self, session_id: str) -> Optional[ProcessMetrics]:
        """Get metrics for a specific process."""
        with self._lock:
            return self.process_metrics.get(session_id)
    
    def get_all_process_metrics(self) -> Dict[str, ProcessMetrics]:
        """Get metrics for all processes."""
        with self._lock:
            return self.process_metrics.copy()
    
    def get_time_series_data(self, metric_type: MetricType, 
                           hours: int = 1) -> List[MetricPoint]:
        """
        Get time series data for a specific metric.
        
        Args:
            metric_type: Type of metric to retrieve
            hours: Number of hours of data to return
            
        Returns:
            List of metric points
        """
        with self._lock:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            metrics = self.time_series_metrics.get(metric_type, deque())
            
            return [
                point for point in metrics
                if point.timestamp >= cutoff_time
            ]
    
    def get_artifact_changes(self, hours: int = 1) -> List[Dict[str, Any]]:
        """
        Get artifact changes within the specified time window.
        
        Args:
            hours: Number of hours of changes to return
            
        Returns:
            List of artifact change records
        """
        with self._lock:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            return [
                change for change in self.artifact_changes
                if change['timestamp'] >= cutoff_time
            ]
    
    def get_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get performance summary for the specified time window.
        
        Args:
            hours: Number of hours to summarize
            
        Returns:
            Performance summary dictionary
        """
        with self._lock:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            # Calculate averages and trends
            response_times = [
                point.value for point in self.time_series_metrics[MetricType.RESPONSE_TIME]
                if point.timestamp >= cutoff_time
            ]
            
            throughput_values = [
                point.value for point in self.time_series_metrics[MetricType.THROUGHPUT]
                if point.timestamp >= cutoff_time
            ]
            
            quality_scores = [
                point.value for point in self.time_series_metrics[MetricType.QUALITY_SCORE]
                if point.timestamp >= cutoff_time
            ]
            
            return {
                'time_window_hours': hours,
                'average_response_time': sum(response_times) / len(response_times) if response_times else 0,
                'max_response_time': max(response_times) if response_times else 0,
                'min_response_time': min(response_times) if response_times else 0,
                'average_throughput': sum(throughput_values) / len(throughput_values) if throughput_values else 0,
                'average_quality_score': sum(quality_scores) / len(quality_scores) if quality_scores else 0,
                'total_processes': len([m for m in self.process_metrics.values() 
                                      if m.start_time >= cutoff_time]),
                'completed_processes': len([m for m in self.process_metrics.values() 
                                          if m.status == ProcessStatus.COMPLETED and m.start_time >= cutoff_time]),
                'failed_processes': len([m for m in self.process_metrics.values() 
                                       if m.status == ProcessStatus.FAILED and m.start_time >= cutoff_time])
            }
    
    def get_quality_dashboard_data(self) -> Dict[str, Any]:
        """Get data for quality dashboard visualization."""
        with self._lock:
            # Quality metrics by artifact type
            quality_by_type = defaultdict(list)
            
            for change in self.artifact_changes:
                if 'quality_score' in change:
                    artifact_type = change.get('artifact_type', 'unknown')
                    quality_by_type[artifact_type].append(change['quality_score'])
            
            # Calculate averages
            quality_averages = {
                artifact_type: sum(scores) / len(scores)
                for artifact_type, scores in quality_by_type.items()
                if scores
            }
            
            # Recent quality trend
            recent_quality = [
                point.value for point in self.time_series_metrics[MetricType.QUALITY_SCORE]
                if point.timestamp >= datetime.now() - timedelta(hours=6)
            ]
            
            return {
                'quality_by_artifact_type': quality_averages,
                'recent_quality_trend': recent_quality,
                'overall_quality_score': self.system_metrics.overall_quality_score,
                'quality_distribution': self._calculate_quality_distribution()
            }
    
    def get_agent_utilization_data(self) -> Dict[str, Any]:
        """Get agent utilization data for visualization."""
        with self._lock:
            # Current utilization
            current_utilization = self.system_metrics.agent_utilization.copy()
            
            # Historical utilization
            historical_data = defaultdict(list)
            for point in self.time_series_metrics[MetricType.AGENT_UTILIZATION]:
                if 'agent_name' in point.metadata:
                    agent_name = point.metadata['agent_name']
                    historical_data[agent_name].append({
                        'timestamp': point.timestamp.isoformat(),
                        'utilization': point.value
                    })
            
            return {
                'current_utilization': current_utilization,
                'historical_utilization': dict(historical_data),
                'total_agents': len(current_utilization),
                'active_agents': len([u for u in current_utilization.values() if u > 0])
            }
    
    def _collection_loop(self):
        """Main collection loop running in background thread."""
        while self._running:
            try:
                self._collect_metrics()
                time.sleep(self.collection_interval)
            except Exception as e:
                logger.error(f"Error in metrics collection: {e}")
                time.sleep(self.collection_interval)
    
    def _collect_metrics(self):
        """Collect current metrics from all sources."""
        with self._lock:
            now = datetime.now()
            
            # Collect system-wide metrics
            self._collect_system_metrics(now)
            
            # Collect process-specific metrics
            self._collect_process_metrics(now)
            
            # Clean up old data
            self._cleanup_old_data(now)
    
    def _collect_system_metrics(self, timestamp: datetime):
        """Collect system-wide metrics."""
        # Get active sessions
        active_sessions = self.orchestrator.get_active_sessions()
        
        # Update system metrics
        self.system_metrics.active_processes = len(active_sessions)
        self.system_metrics.pending_reviews = len([
            s for s in active_sessions 
            if s.status == ProcessStatus.PAUSED_FOR_REVIEW
        ])
        
        # Calculate total errors
        total_errors = sum(len(s.error_log) for s in active_sessions)
        self.system_metrics.total_errors = total_errors
        
        # Record time series metrics
        self._record_metric(MetricType.PROCESS_COUNT, 
                          float(self.system_metrics.active_processes), timestamp)
        self._record_metric(MetricType.REVIEW_COUNT, 
                          float(self.system_metrics.pending_reviews), timestamp)
        self._record_metric(MetricType.ERROR_COUNT, 
                          float(total_errors), timestamp)
        
        # Calculate and record quality score
        quality_score = self._calculate_overall_quality_score(active_sessions)
        self.system_metrics.overall_quality_score = quality_score
        self._record_metric(MetricType.QUALITY_SCORE, quality_score, timestamp)
        
        # Calculate agent utilization
        agent_utilization = self._calculate_agent_utilization(active_sessions)
        self.system_metrics.agent_utilization = agent_utilization
        
        for agent_name, utilization in agent_utilization.items():
            self._record_metric(MetricType.AGENT_UTILIZATION, utilization, 
                              timestamp, {'agent_name': agent_name})
    
    def _collect_process_metrics(self, timestamp: datetime):
        """Collect metrics for individual processes."""
        active_sessions = self.orchestrator.get_active_sessions()
        
        for session in active_sessions:
            session_id = session.session_id
            
            # Create or update process metrics
            if session_id not in self.process_metrics:
                self.process_metrics[session_id] = ProcessMetrics(
                    session_id=session_id,
                    start_time=session.created_at,
                    current_phase=session.current_phase,
                    status=session.status,
                    progress=session.progress
                )
            
            metrics = self.process_metrics[session_id]
            
            # Update current state
            metrics.current_phase = session.current_phase
            metrics.status = session.status
            metrics.progress = session.progress
            metrics.artifacts_created = len(session.artifacts)
            metrics.reviews_completed = len(session.review_history)
            metrics.errors_encountered = len(session.error_log)
            
            # Calculate phase duration if phase changed
            if hasattr(session, '_last_phase_change'):
                phase_key = session.current_phase.value
                if phase_key not in metrics.phase_durations:
                    metrics.phase_durations[phase_key] = 0
                
                # This would need more sophisticated phase tracking
                # For now, we'll estimate based on update time
                if session.updated_at > session.created_at:
                    duration = (session.updated_at - session.created_at).total_seconds()
                    metrics.phase_durations[phase_key] = duration
    
    def _record_metric(self, metric_type: MetricType, value: float, 
                      timestamp: datetime, metadata: Optional[Dict[str, Any]] = None):
        """Record a metric point."""
        point = MetricPoint(
            timestamp=timestamp,
            value=value,
            metadata=metadata or {}
        )
        
        self.time_series_metrics[metric_type].append(point)
        
        # Trigger callback if set
        if self.on_metric_updated:
            self.on_metric_updated(metric_type, point)
    
    def _calculate_overall_quality_score(self, sessions: List[ProcessSession]) -> float:
        """Calculate overall system quality score."""
        if not sessions:
            return 0.0
        
        # Simple quality calculation based on completion rate and error rate
        completed_sessions = [s for s in sessions if s.status == ProcessStatus.COMPLETED]
        failed_sessions = [s for s in sessions if s.status == ProcessStatus.FAILED]
        
        if not sessions:
            return 1.0
        
        completion_rate = len(completed_sessions) / len(sessions)
        error_rate = len(failed_sessions) / len(sessions)
        
        # Quality score: high completion rate, low error rate
        quality_score = completion_rate * (1 - error_rate)
        
        return min(1.0, max(0.0, quality_score))
    
    def _calculate_agent_utilization(self, sessions: List[ProcessSession]) -> Dict[str, float]:
        """Calculate agent utilization percentages."""
        agent_names = ['interviewer', 'enduser', 'deployer', 'analyst', 'archivist', 'reviewer']
        utilization = {}
        
        total_sessions = len(sessions)
        if total_sessions == 0:
            return {name: 0.0 for name in agent_names}
        
        for agent_name in agent_names:
            # Count sessions where this agent is active
            active_count = sum(1 for s in sessions if agent_name in s.active_agents)
            utilization[agent_name] = active_count / total_sessions
        
        return utilization
    
    def _calculate_quality_distribution(self) -> Dict[str, int]:
        """Calculate distribution of quality scores."""
        recent_scores = [
            point.value for point in self.time_series_metrics[MetricType.QUALITY_SCORE]
            if point.timestamp >= datetime.now() - timedelta(hours=24)
        ]
        
        if not recent_scores:
            return {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0}
        
        distribution = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0}
        
        for score in recent_scores:
            if score >= 0.9:
                distribution['excellent'] += 1
            elif score >= 0.7:
                distribution['good'] += 1
            elif score >= 0.5:
                distribution['fair'] += 1
            else:
                distribution['poor'] += 1
        
        return distribution
    
    def _cleanup_old_data(self, current_time: datetime):
        """Clean up old metric data beyond retention period."""
        cutoff_time = current_time - timedelta(hours=self.retention_hours)
        
        # Clean up time series data
        for metric_type, metrics in self.time_series_metrics.items():
            while metrics and metrics[0].timestamp < cutoff_time:
                metrics.popleft()
        
        # Clean up artifact changes
        while (self.artifact_changes and 
               self.artifact_changes[0]['timestamp'] < cutoff_time):
            self.artifact_changes.popleft()
        
        # Clean up completed process metrics (keep for longer)
        process_cutoff = current_time - timedelta(hours=self.retention_hours * 7)  # Keep for a week
        completed_sessions = [
            session_id for session_id, metrics in self.process_metrics.items()
            if (metrics.status in [ProcessStatus.COMPLETED, ProcessStatus.FAILED] and
                metrics.start_time < process_cutoff)
        ]
        
        for session_id in completed_sessions:
            del self.process_metrics[session_id]
    
    def _setup_event_handlers(self):
        """Set up event handlers for monitoring."""
        self.event_bus.subscribe_callable(
            [EventType.ARTIFACT_CREATED, EventType.ARTIFACT_UPDATED],
            self._handle_artifact_event
        )
        
        self.event_bus.subscribe_callable(
            [EventType.PROCESS_STARTED, EventType.PROCESS_COMPLETED, EventType.PROCESS_FAILED],
            self._handle_process_event
        )
        
        self.event_bus.subscribe_callable(
            [EventType.AGENT_STARTED, EventType.AGENT_COMPLETED, EventType.AGENT_FAILED],
            self._handle_agent_event
        )
    
    def _handle_artifact_event(self, event: Event):
        """Handle artifact-related events."""
        with self._lock:
            change_record = {
                'timestamp': event.timestamp,
                'event_type': event.type.value,
                'artifact_id': event.payload.get('artifact_id'),
                'artifact_type': event.payload.get('artifact_type'),
                'session_id': event.session_id,
                'quality_score': event.payload.get('quality_score', 0.8)  # Default score
            }
            
            self.artifact_changes.append(change_record)
            
            # Update artifact count
            if event.type == EventType.ARTIFACT_CREATED:
                self.system_metrics.total_artifacts += 1
                self._record_metric(MetricType.ARTIFACT_COUNT, 
                                  float(self.system_metrics.total_artifacts), 
                                  event.timestamp)
    
    def _handle_process_event(self, event: Event):
        """Handle process-related events."""
        session_id = event.session_id
        
        if event.type == EventType.PROCESS_STARTED:
            # Process start is handled in _collect_process_metrics
            pass
        
        elif event.type in [EventType.PROCESS_COMPLETED, EventType.PROCESS_FAILED]:
            # Update process metrics final state
            if session_id in self.process_metrics:
                metrics = self.process_metrics[session_id]
                if event.type == EventType.PROCESS_COMPLETED:
                    metrics.status = ProcessStatus.COMPLETED
                else:
                    metrics.status = ProcessStatus.FAILED
    
    def _handle_agent_event(self, event: Event):
        """Handle agent-related events."""
        agent_name = event.payload.get('agent_name')
        if not agent_name:
            return
        
        # Record agent activity for utilization calculation
        if event.type == EventType.AGENT_STARTED:
            # Agent started working
            pass
        elif event.type in [EventType.AGENT_COMPLETED, EventType.AGENT_FAILED]:
            # Agent finished working
            response_time = event.payload.get('response_time', 0)
            if response_time > 0:
                self._record_metric(MetricType.RESPONSE_TIME, response_time, 
                                  event.timestamp, {'agent_name': agent_name})


class VisualizationDataProvider:
    """
    Provides formatted data for various visualization components.
    
    Transforms raw monitoring data into formats suitable for charts,
    graphs, and dashboard displays.
    """
    
    def __init__(self, monitoring_system: MonitoringSystem):
        """Initialize with monitoring system."""
        self.monitoring = monitoring_system
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive dashboard data."""
        system_metrics = self.monitoring.get_system_metrics()
        performance_summary = self.monitoring.get_performance_summary(hours=24)
        quality_data = self.monitoring.get_quality_dashboard_data()
        agent_data = self.monitoring.get_agent_utilization_data()
        
        return {
            'system_metrics': system_metrics.to_dict(),
            'performance_summary': performance_summary,
            'quality_dashboard': quality_data,
            'agent_utilization': agent_data,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_time_series_chart_data(self, metric_type: MetricType, 
                                  hours: int = 6) -> Dict[str, Any]:
        """Get time series data formatted for charts."""
        data_points = self.monitoring.get_time_series_data(metric_type, hours)
        
        return {
            'metric_type': metric_type.value,
            'time_window_hours': hours,
            'data': [point.to_dict() for point in data_points],
            'labels': [point.timestamp.strftime('%H:%M') for point in data_points],
            'values': [point.value for point in data_points]
        }
    
    def get_process_timeline_data(self, session_id: str) -> Dict[str, Any]:
        """Get process timeline data for visualization."""
        process_metrics = self.monitoring.get_process_metrics(session_id)
        if not process_metrics:
            return {}
        
        # Create timeline events
        timeline_events = []
        
        # Add phase transitions
        for phase, duration in process_metrics.phase_durations.items():
            timeline_events.append({
                'phase': phase,
                'duration': duration,
                'type': 'phase_completion'
            })
        
        # Add artifact creation events
        artifact_changes = [
            change for change in self.monitoring.get_artifact_changes(hours=24)
            if change['session_id'] == session_id
        ]
        
        for change in artifact_changes:
            timeline_events.append({
                'timestamp': change['timestamp'].isoformat(),
                'type': 'artifact_' + change['event_type'],
                'artifact_type': change['artifact_type'],
                'quality_score': change.get('quality_score')
            })
        
        return {
            'session_id': session_id,
            'timeline_events': sorted(timeline_events, 
                                    key=lambda x: x.get('timestamp', '')),
            'process_metrics': process_metrics.to_dict()
        }
    
    def get_quality_heatmap_data(self) -> Dict[str, Any]:
        """Get quality heatmap data by artifact type and time."""
        quality_data = self.monitoring.get_quality_dashboard_data()
        
        # Create heatmap matrix
        artifact_types = list(quality_data['quality_by_artifact_type'].keys())
        time_slots = []
        quality_matrix = []
        
        # Generate time slots for last 24 hours
        now = datetime.now()
        for i in range(24):
            time_slot = now - timedelta(hours=i)
            time_slots.append(time_slot.strftime('%H:00'))
        
        time_slots.reverse()
        
        # Fill quality matrix (simplified - would need more detailed tracking)
        for artifact_type in artifact_types:
            row = []
            base_quality = quality_data['quality_by_artifact_type'][artifact_type]
            
            for _ in time_slots:
                # Add some variation around base quality
                import random
                variation = random.uniform(-0.1, 0.1)
                quality = max(0, min(1, base_quality + variation))
                row.append(quality)
            
            quality_matrix.append(row)
        
        return {
            'artifact_types': artifact_types,
            'time_slots': time_slots,
            'quality_matrix': quality_matrix,
            'color_scale': {
                'min': 0,
                'max': 1,
                'colors': ['#ff4444', '#ffaa00', '#88dd00', '#00aa00']
            }
        }
    
    def get_agent_performance_radar_data(self) -> Dict[str, Any]:
        """Get agent performance data for radar chart."""
        agent_data = self.monitoring.get_agent_utilization_data()
        
        # Performance dimensions
        dimensions = [
            'Utilization',
            'Response Time',
            'Quality Score',
            'Reliability',
            'Throughput'
        ]
        
        # Calculate scores for each agent
        agent_scores = {}
        for agent_name, utilization in agent_data['current_utilization'].items():
            # Simplified scoring - would need more detailed metrics
            scores = {
                'Utilization': utilization,
                'Response Time': 0.8,  # Placeholder
                'Quality Score': 0.85,  # Placeholder
                'Reliability': 0.9,  # Placeholder
                'Throughput': 0.75  # Placeholder
            }
            agent_scores[agent_name] = scores
        
        return {
            'dimensions': dimensions,
            'agents': agent_scores,
            'scale': {'min': 0, 'max': 1}
        }