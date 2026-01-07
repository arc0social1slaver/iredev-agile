"""
Web routes for monitoring and visualization features.

Provides REST API endpoints and WebSocket handlers for real-time
monitoring data, charts, and dashboard visualizations.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from flask import Blueprint, jsonify, request, render_template
from flask_socketio import emit, join_room, leave_room

from ..visualizer.monitoring import MonitoringSystem, VisualizationDataProvider, MetricType

logger = logging.getLogger(__name__)

# Create blueprint for monitoring routes
monitoring_bp = Blueprint('monitoring', __name__, url_prefix='/monitoring')

# Global monitoring system instance (will be set by app initialization)
monitoring_system: Optional[MonitoringSystem] = None
visualization_provider: Optional[VisualizationDataProvider] = None


def init_monitoring_routes(monitoring_sys: MonitoringSystem):
    """Initialize monitoring routes with system instance."""
    global monitoring_system, visualization_provider
    monitoring_system = monitoring_sys
    visualization_provider = VisualizationDataProvider(monitoring_sys)


# Dashboard Routes

@monitoring_bp.route('/dashboard')
def monitoring_dashboard():
    """Main monitoring dashboard page."""
    if not monitoring_system:
        return render_template('error.html', error='Monitoring system not initialized'), 500
    
    return render_template('monitoring/dashboard.html')


@monitoring_bp.route('/process/<session_id>')
def process_monitoring(session_id):
    """Process-specific monitoring page."""
    if not monitoring_system:
        return render_template('error.html', error='Monitoring system not initialized'), 500
    
    process_metrics = monitoring_system.get_process_metrics(session_id)
    if not process_metrics:
        return render_template('error.html', error='Process not found'), 404
    
    return render_template('monitoring/process_detail.html', 
                         session_id=session_id,
                         process_metrics=process_metrics)


@monitoring_bp.route('/quality')
def quality_dashboard():
    """Quality metrics dashboard."""
    if not monitoring_system:
        return render_template('error.html', error='Monitoring system not initialized'), 500
    
    return render_template('monitoring/quality_dashboard.html')


@monitoring_bp.route('/agents')
def agent_monitoring():
    """Agent utilization and performance monitoring."""
    if not monitoring_system:
        return render_template('error.html', error='Monitoring system not initialized'), 500
    
    return render_template('monitoring/agent_monitoring.html')


# API Routes

@monitoring_bp.route('/api/dashboard')
def api_dashboard_data():
    """Get comprehensive dashboard data."""
    if not visualization_provider:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        data = visualization_provider.get_dashboard_data()
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/metrics/<metric_type>')
def api_time_series_data(metric_type):
    """Get time series data for a specific metric."""
    if not visualization_provider:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        # Parse metric type
        try:
            metric_enum = MetricType(metric_type)
        except ValueError:
            return jsonify({'error': f'Invalid metric type: {metric_type}'}), 400
        
        # Get time window from query params
        hours = request.args.get('hours', 6, type=int)
        hours = max(1, min(168, hours))  # Limit to 1 hour - 1 week
        
        data = visualization_provider.get_time_series_chart_data(metric_enum, hours)
        return jsonify(data)
    
    except Exception as e:
        logger.error(f"Error getting time series data: {e}")
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/process/<session_id>/timeline')
def api_process_timeline(session_id):
    """Get process timeline data."""
    if not visualization_provider:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        data = visualization_provider.get_process_timeline_data(session_id)
        if not data:
            return jsonify({'error': 'Process not found'}), 404
        
        return jsonify(data)
    
    except Exception as e:
        logger.error(f"Error getting process timeline: {e}")
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/quality/heatmap')
def api_quality_heatmap():
    """Get quality heatmap data."""
    if not visualization_provider:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        data = visualization_provider.get_quality_heatmap_data()
        return jsonify(data)
    
    except Exception as e:
        logger.error(f"Error getting quality heatmap: {e}")
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/agents/performance')
def api_agent_performance():
    """Get agent performance radar chart data."""
    if not visualization_provider:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        data = visualization_provider.get_agent_performance_radar_data()
        return jsonify(data)
    
    except Exception as e:
        logger.error(f"Error getting agent performance data: {e}")
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/agents/utilization')
def api_agent_utilization():
    """Get detailed agent utilization data."""
    if not monitoring_system:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        data = monitoring_system.get_agent_utilization_data()
        return jsonify(data)
    
    except Exception as e:
        logger.error(f"Error getting agent utilization: {e}")
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/artifacts/changes')
def api_artifact_changes():
    """Get recent artifact changes."""
    if not monitoring_system:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        hours = request.args.get('hours', 24, type=int)
        hours = max(1, min(168, hours))  # Limit to 1 hour - 1 week
        
        changes = monitoring_system.get_artifact_changes(hours)
        
        # Convert datetime objects to ISO strings for JSON serialization
        for change in changes:
            if isinstance(change['timestamp'], datetime):
                change['timestamp'] = change['timestamp'].isoformat()
        
        return jsonify({
            'time_window_hours': hours,
            'changes': changes,
            'total_changes': len(changes)
        })
    
    except Exception as e:
        logger.error(f"Error getting artifact changes: {e}")
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/performance/summary')
def api_performance_summary():
    """Get performance summary."""
    if not monitoring_system:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        hours = request.args.get('hours', 24, type=int)
        hours = max(1, min(168, hours))  # Limit to 1 hour - 1 week
        
        summary = monitoring_system.get_performance_summary(hours)
        return jsonify(summary)
    
    except Exception as e:
        logger.error(f"Error getting performance summary: {e}")
        return jsonify({'error': str(e)}), 500


@monitoring_bp.route('/api/system/status')
def api_system_status():
    """Get current system status."""
    if not monitoring_system:
        return jsonify({'error': 'Monitoring system not initialized'}), 500
    
    try:
        system_metrics = monitoring_system.get_system_metrics()
        
        # Add system health indicators
        health_status = 'healthy'
        if system_metrics.total_errors > 10:
            health_status = 'degraded'
        if system_metrics.average_response_time > 30:
            health_status = 'slow'
        
        return jsonify({
            'status': health_status,
            'metrics': system_metrics.to_dict(),
            'timestamp': datetime.now().isoformat(),
            'uptime_hours': 24  # Placeholder - would need actual uptime tracking
        })
    
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return jsonify({'error': str(e)}), 500


# WebSocket Events for Real-time Updates

def setup_monitoring_websocket_handlers(socketio):
    """Set up WebSocket handlers for real-time monitoring updates."""
    
    @socketio.on('join_monitoring')
    def handle_join_monitoring(data):
        """Join monitoring room for real-time updates."""
        room = data.get('room', 'general_monitoring')
        join_room(room)
        emit('joined_monitoring', {'room': room})
        logger.info(f"Client joined monitoring room: {room}")
    
    @socketio.on('leave_monitoring')
    def handle_leave_monitoring(data):
        """Leave monitoring room."""
        room = data.get('room', 'general_monitoring')
        leave_room(room)
        emit('left_monitoring', {'room': room})
        logger.info(f"Client left monitoring room: {room}")
    
    @socketio.on('request_dashboard_update')
    def handle_dashboard_update_request():
        """Handle request for dashboard data update."""
        if visualization_provider:
            try:
                data = visualization_provider.get_dashboard_data()
                emit('dashboard_update', data)
            except Exception as e:
                logger.error(f"Error sending dashboard update: {e}")
                emit('error', {'message': 'Failed to get dashboard data'})
    
    @socketio.on('request_metric_update')
    def handle_metric_update_request(data):
        """Handle request for specific metric update."""
        if not visualization_provider:
            emit('error', {'message': 'Monitoring system not initialized'})
            return
        
        try:
            metric_type = data.get('metric_type')
            hours = data.get('hours', 1)
            
            if not metric_type:
                emit('error', {'message': 'Metric type required'})
                return
            
            try:
                metric_enum = MetricType(metric_type)
            except ValueError:
                emit('error', {'message': f'Invalid metric type: {metric_type}'})
                return
            
            chart_data = visualization_provider.get_time_series_chart_data(metric_enum, hours)
            emit('metric_update', {
                'metric_type': metric_type,
                'data': chart_data
            })
            
        except Exception as e:
            logger.error(f"Error sending metric update: {e}")
            emit('error', {'message': 'Failed to get metric data'})


# Utility Functions

def broadcast_metric_update(metric_type: MetricType, data: Dict[str, Any], socketio):
    """Broadcast metric update to all monitoring clients."""
    try:
        socketio.emit('metric_update', {
            'metric_type': metric_type.value,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }, room='general_monitoring')
    except Exception as e:
        logger.error(f"Error broadcasting metric update: {e}")


def broadcast_system_alert(alert_type: str, message: str, data: Dict[str, Any], socketio):
    """Broadcast system alert to monitoring clients."""
    try:
        socketio.emit('system_alert', {
            'type': alert_type,
            'message': message,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }, room='general_monitoring')
    except Exception as e:
        logger.error(f"Error broadcasting system alert: {e}")


def setup_monitoring_callbacks(socketio):
    """Set up monitoring system callbacks for real-time updates."""
    if not monitoring_system:
        return
    
    # Set up metric update callback
    def on_metric_updated(metric_type, metric_point):
        """Handle metric update for real-time broadcasting."""
        if visualization_provider:
            try:
                chart_data = visualization_provider.get_time_series_chart_data(metric_type, 1)
                broadcast_metric_update(metric_type, chart_data, socketio)
            except Exception as e:
                logger.error(f"Error handling metric update: {e}")
    
    # Set up alert callback
    def on_alert_triggered(alert_type, alert_data):
        """Handle system alert for real-time broadcasting."""
        message = alert_data.get('message', f'{alert_type} alert triggered')
        broadcast_system_alert(alert_type, message, alert_data, socketio)
    
    monitoring_system.on_metric_updated = on_metric_updated
    monitoring_system.on_alert_triggered = on_alert_triggered