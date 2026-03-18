"""
Flask web application for iReDev framework.

Provides a web-based user interface for requirement development process
management, monitoring, and human-in-the-loop interactions.
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
import yaml

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.config.config_manager import get_config_manager, iReDevConfig
from src.orchestrator.orchestrator import RequirementOrchestrator, ProjectConfig, ProcessSession
from src.orchestrator.human_in_loop import HumanReviewManager, HumanFeedback, FeedbackType
from src.artifact.pool import ArtifactPool
from src.artifact.events import EventBus
from src.agent.communication import CommunicationProtocol
from src.visualizer.monitoring import MonitoringSystem
from src.web.monitoring_routes import monitoring_bp, init_monitoring_routes, setup_monitoring_websocket_handlers, setup_monitoring_callbacks

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'iredev-secret-key-change-in-production')
app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

# Initialize SocketIO for real-time updates
socketio = SocketIO(app, cors_allowed_origins="*")

# Global system components
config_manager = None
orchestrator = None
artifact_pool = None
event_bus = None
review_manager = None
monitoring_system = None
system_initialized = False


def initialize_system():
    """Initialize the iReDev system components."""
    global config_manager, orchestrator, artifact_pool, event_bus, review_manager, monitoring_system, system_initialized
    
    if system_initialized:
        return True
    
    try:
        # Load configuration
        config_manager = get_config_manager()
        config = config_manager.load_config()
        
        # Initialize core components
        event_bus = EventBus()
        artifact_pool = ArtifactPool(
            storage_backend=config.artifact_pool.storage_backend,
            storage_path=config.artifact_pool.storage_path
        )
        communication_protocol = CommunicationProtocol()
        
        # Initialize orchestrator
        orchestrator = RequirementOrchestrator(
            config_manager=config_manager,
            artifact_pool=artifact_pool,
            event_bus=event_bus,
            communication_protocol=communication_protocol
        )
        
        # Initialize review manager
        review_manager = HumanReviewManager(
            artifact_pool=artifact_pool,
            event_bus=event_bus
        )
        
        # Initialize monitoring system
        monitoring_system = MonitoringSystem(
            orchestrator=orchestrator,
            artifact_pool=artifact_pool,
            event_bus=event_bus
        )
        monitoring_system.start()
        
        # Initialize monitoring routes
        init_monitoring_routes(monitoring_system)
        
        # Set up callbacks for real-time updates
        orchestrator.on_phase_started = lambda session_id, phase: socketio.emit(
            'phase_started', {'session_id': session_id, 'phase': phase.value}
        )
        orchestrator.on_phase_completed = lambda session_id, phase: socketio.emit(
            'phase_completed', {'session_id': session_id, 'phase': phase.value}
        )
        orchestrator.on_review_required = lambda session_id, artifact_type, artifact_id: socketio.emit(
            'review_required', {
                'session_id': session_id, 
                'artifact_type': artifact_type, 
                'artifact_id': artifact_id
            }
        )
        
        # Set up monitoring callbacks
        setup_monitoring_callbacks(socketio)
        
        system_initialized = True
        logger.info("iReDev system initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize system: {e}")
        return False


@app.before_first_request
def before_first_request():
    """Initialize system before first request."""
    initialize_system()

# Register monitoring blueprint
app.register_blueprint(monitoring_bp)


# Routes

@app.route('/')
def index():
    """Main dashboard page."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return render_template('error.html', error='System initialization failed')
    
    # Get active sessions
    active_sessions = orchestrator.get_active_sessions() if orchestrator else []
    
    # Get pending reviews
    pending_reviews = review_manager.get_pending_reviews() if review_manager else []
    
    return render_template('dashboard.html', 
                         active_sessions=active_sessions,
                         pending_reviews=pending_reviews)


@app.route('/start', methods=['GET', 'POST'])
def start_process():
    """Start a new requirement development process."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            # Get form data
            project_name = request.form.get('project_name', '').strip()
            domain = request.form.get('domain', '').strip()
            stakeholders = [s.strip() for s in request.form.get('stakeholders', '').split(',') if s.strip()]
            target_environment = request.form.get('target_environment', '').strip()
            compliance_requirements = request.form.getlist('compliance_requirements')
            quality_standards = request.form.getlist('quality_standards')
            timeout_minutes = int(request.form.get('timeout_minutes', 1440))
            
            if not project_name:
                flash('Project name is required', 'error')
                return render_template('start_process.html')
            
            # Create project configuration
            project_config = ProjectConfig(
                project_name=project_name,
                domain=domain or 'general',
                stakeholders=stakeholders,
                target_environment=target_environment or 'cloud',
                compliance_requirements=compliance_requirements,
                quality_standards=quality_standards,
                timeout_minutes=timeout_minutes
            )
            
            # Start the process
            session = orchestrator.start_requirement_process(
                project_config=project_config,
                created_by=session.get('user', 'web_user')
            )
            
            flash(f'Process started successfully: {session.session_id}', 'success')
            return redirect(url_for('process_detail', session_id=session.session_id))
            
        except Exception as e:
            logger.error(f"Failed to start process: {e}")
            flash(f'Failed to start process: {str(e)}', 'error')
    
    return render_template('start_process.html')


@app.route('/process/<session_id>')
def process_detail(session_id):
    """Show detailed process information."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return redirect(url_for('index'))
    
    session_data = orchestrator.get_process_status(session_id)
    if not session_data:
        flash('Process not found', 'error')
        return redirect(url_for('index'))
    
    # Get artifacts for this session
    artifacts = artifact_pool.query_artifacts_by_session(session_id) if artifact_pool else []
    
    # Get review history
    review_history = review_manager.get_review_history(session_id) if review_manager else []
    
    return render_template('process_detail.html',
                         session=session_data,
                         artifacts=artifacts,
                         review_history=review_history)


@app.route('/review')
def review_dashboard():
    """Review dashboard showing pending reviews."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return redirect(url_for('index'))
    
    pending_reviews = review_manager.get_pending_reviews() if review_manager else []
    
    return render_template('review_dashboard.html', pending_reviews=pending_reviews)


@app.route('/review/<review_id>')
def review_detail(review_id):
    """Show detailed review interface."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return redirect(url_for('index'))
    
    # Find the review
    pending_reviews = review_manager.get_pending_reviews()
    review = next((r for r in pending_reviews if r.id == review_id), None)
    
    if not review:
        flash('Review not found', 'error')
        return redirect(url_for('review_dashboard'))
    
    # Get the artifact
    artifact = artifact_pool.get_artifact(review.artifact_id)
    
    return render_template('review_detail.html', review=review, artifact=artifact)


@app.route('/review/<review_id>/submit', methods=['POST'])
def submit_review(review_id):
    """Submit review feedback."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return redirect(url_for('index'))
    
    try:
        # Get form data
        feedback_type_str = request.form.get('feedback_type', 'modify')
        content = request.form.get('content', '').strip()
        suggestions = [s.strip() for s in request.form.get('suggestions', '').split('\n') if s.strip()]
        
        if not content:
            flash('Feedback content is required', 'error')
            return redirect(url_for('review_detail', review_id=review_id))
        
        # Map feedback type
        feedback_type_map = {
            'approve': FeedbackType.APPROVAL,
            'reject': FeedbackType.REJECTION,
            'modify': FeedbackType.MODIFICATION_REQUEST,
            'clarify': FeedbackType.CLARIFICATION_REQUEST
        }
        
        feedback_type = feedback_type_map.get(feedback_type_str, FeedbackType.MODIFICATION_REQUEST)
        approval_status = feedback_type == FeedbackType.APPROVAL
        
        # Submit feedback
        feedback = review_manager.submit_feedback(
            review_point_id=review_id,
            reviewer=session.get('user', 'web_user'),
            feedback_type=feedback_type,
            content=content,
            suggestions=suggestions,
            approval_status=approval_status
        )
        
        flash('Feedback submitted successfully', 'success')
        return redirect(url_for('review_dashboard'))
        
    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        flash(f'Failed to submit feedback: {str(e)}', 'error')
        return redirect(url_for('review_detail', review_id=review_id))


@app.route('/artifacts')
def artifacts_list():
    """List all artifacts."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return redirect(url_for('index'))
    
    # Get filter parameters
    session_id = request.args.get('session_id')
    artifact_type = request.args.get('type')
    
    # Query artifacts (this would need to be implemented in artifact pool)
    artifacts = []  # Placeholder
    
    return render_template('artifacts_list.html', artifacts=artifacts)


@app.route('/artifacts/<artifact_id>')
def artifact_detail(artifact_id):
    """Show artifact details."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return redirect(url_for('index'))
    
    artifact = artifact_pool.get_artifact(artifact_id)
    if not artifact:
        flash('Artifact not found', 'error')
        return redirect(url_for('artifacts_list'))
    
    return render_template('artifact_detail.html', artifact=artifact)


@app.route('/config')
def config_management():
    """Configuration management interface."""
    if not initialize_system():
        flash('System initialization failed', 'error')
        return redirect(url_for('index'))
    
    config = config_manager.load_config()
    
    return render_template('config_management.html', config=config)


# API Routes

@app.route('/api/sessions')
def api_sessions():
    """API endpoint to get all sessions."""
    if not initialize_system():
        return jsonify({'error': 'System not initialized'}), 500
    
    sessions = orchestrator.get_active_sessions()
    return jsonify([session.to_dict() for session in sessions])


@app.route('/api/sessions/<session_id>')
def api_session_detail(session_id):
    """API endpoint to get session details."""
    if not initialize_system():
        return jsonify({'error': 'System not initialized'}), 500
    
    session_data = orchestrator.get_process_status(session_id)
    if not session_data:
        return jsonify({'error': 'Session not found'}), 404
    
    return jsonify(session_data.to_dict())


@app.route('/api/sessions/<session_id>/cancel', methods=['POST'])
def api_cancel_session(session_id):
    """API endpoint to cancel a session."""
    if not initialize_system():
        return jsonify({'error': 'System not initialized'}), 500
    
    reason = request.json.get('reason', 'Cancelled via API')
    success = orchestrator.cancel_process(session_id, reason)
    
    if success:
        return jsonify({'message': 'Session cancelled successfully'})
    else:
        return jsonify({'error': 'Failed to cancel session'}), 400


@app.route('/api/reviews')
def api_reviews():
    """API endpoint to get pending reviews."""
    if not initialize_system():
        return jsonify({'error': 'System not initialized'}), 500
    
    session_id = request.args.get('session_id')
    pending_reviews = review_manager.get_pending_reviews(session_id=session_id)
    
    return jsonify([review.to_dict() for review in pending_reviews])


@app.route('/api/artifacts/<artifact_id>')
def api_artifact_detail(artifact_id):
    """API endpoint to get artifact details."""
    if not initialize_system():
        return jsonify({'error': 'System not initialized'}), 500
    
    artifact = artifact_pool.get_artifact(artifact_id)
    if not artifact:
        return jsonify({'error': 'Artifact not found'}), 404
    
    return jsonify({
        'id': artifact.id,
        'type': artifact.type.value,
        'status': artifact.status.value,
        'content': artifact.content,
        'metadata': artifact.metadata.__dict__ if artifact.metadata else {},
        'created_at': artifact.created_at.isoformat(),
        'updated_at': artifact.updated_at.isoformat()
    })


# WebSocket Events

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to iReDev'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    logger.info(f"Client disconnected: {request.sid}")


@socketio.on('join_session')
def handle_join_session(data):
    """Join a session room for real-time updates."""
    session_id = data.get('session_id')
    if session_id:
        join_room(session_id)
        emit('joined_session', {'session_id': session_id})
        logger.info(f"Client {request.sid} joined session {session_id}")


@socketio.on('leave_session')
def handle_leave_session(data):
    """Leave a session room."""
    session_id = data.get('session_id')
    if session_id:
        leave_room(session_id)
        emit('left_session', {'session_id': session_id})
        logger.info(f"Client {request.sid} left session {session_id}")

# Set up monitoring WebSocket handlers
setup_monitoring_websocket_handlers(socketio)


# Error Handlers

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    return render_template('error.html', error='Page not found'), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal error: {error}")
    return render_template('error.html', error='Internal server error'), 500


# Template Filters

@app.template_filter('datetime')
def datetime_filter(dt):
    """Format datetime for templates."""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
    return dt.strftime('%Y-%m-%d %H:%M:%S')


@app.template_filter('json_pretty')
def json_pretty_filter(data):
    """Pretty print JSON for templates."""
    return json.dumps(data, indent=2, default=str)


if __name__ == '__main__':
    # Development server
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting iReDev web interface on port {port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)