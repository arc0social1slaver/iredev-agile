#!/usr/bin/env python3
"""
iReDev Framework Command Line Interface

A comprehensive CLI tool for managing the iReDev knowledge-driven multi-agent
requirement development framework. Provides commands for process management,
monitoring, configuration, and system administration.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

import colorama
from colorama import Fore, Back, Style
import yaml

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config.config_manager import ConfigManager, get_config_manager, iReDevConfig
from src.orchestrator.orchestrator import RequirementOrchestrator, ProjectConfig, ProcessSession, ProcessStatus, ProcessPhase
from src.orchestrator.human_in_loop import HumanReviewManager, ReviewPoint, HumanFeedback, FeedbackType
from src.artifact.pool import ArtifactPool
from src.artifact.events import EventBus
from src.agent.communication import CommunicationProtocol

# Initialize colorama for cross-platform colored output
colorama.init(autoreset=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class iReDevCLI:
    """Main CLI class for iReDev framework."""
    
    def __init__(self):
        """Initialize the CLI."""
        self.config_manager = get_config_manager()
        self.config = None
        self.orchestrator = None
        self.artifact_pool = None
        self.event_bus = None
        self.communication_protocol = None
        self.review_manager = None
        
    def initialize_system(self) -> bool:
        """Initialize the iReDev system components."""
        try:
            # Load configuration
            self.config = self.config_manager.load_config()
            
            # Initialize core components
            self.event_bus = EventBus()
            self.artifact_pool = ArtifactPool(
                storage_backend=self.config.artifact_pool.storage_backend,
                storage_path=self.config.artifact_pool.storage_path
            )
            self.communication_protocol = CommunicationProtocol()
            
            # Initialize orchestrator
            self.orchestrator = RequirementOrchestrator(
                config_manager=self.config_manager,
                artifact_pool=self.artifact_pool,
                event_bus=self.event_bus,
                communication_protocol=self.communication_protocol
            )
            
            # Initialize review manager
            self.review_manager = HumanReviewManager(
                artifact_pool=self.artifact_pool,
                event_bus=self.event_bus
            )
            
            return True
            
        except Exception as e:
            self.print_error(f"Failed to initialize system: {e}")
            return False
    
    def print_header(self, title: str):
        """Print a formatted header."""
        print(f"\n{Fore.CYAN}{Style.BRIGHT}{'=' * 60}")
        print(f"{title:^60}")
        print(f"{'=' * 60}{Style.RESET_ALL}\n")
    
    def print_success(self, message: str):
        """Print a success message."""
        print(f"{Fore.GREEN}✓ {message}{Style.RESET_ALL}")
    
    def print_error(self, message: str):
        """Print an error message."""
        print(f"{Fore.RED}✗ {message}{Style.RESET_ALL}")
    
    def print_warning(self, message: str):
        """Print a warning message."""
        print(f"{Fore.YELLOW}⚠ {message}{Style.RESET_ALL}")
    
    def print_info(self, message: str):
        """Print an info message."""
        print(f"{Fore.BLUE}ℹ {message}{Style.RESET_ALL}")
    
    def format_status(self, status: ProcessStatus) -> str:
        """Format process status with colors."""
        status_colors = {
            ProcessStatus.NOT_STARTED: Fore.WHITE,
            ProcessStatus.RUNNING: Fore.BLUE,
            ProcessStatus.PAUSED_FOR_REVIEW: Fore.YELLOW,
            ProcessStatus.WAITING_FOR_FEEDBACK: Fore.YELLOW,
            ProcessStatus.COMPLETED: Fore.GREEN,
            ProcessStatus.FAILED: Fore.RED,
            ProcessStatus.CANCELLED: Fore.MAGENTA
        }
        color = status_colors.get(status, Fore.WHITE)
        return f"{color}{status.value.upper()}{Style.RESET_ALL}"
    
    def format_phase(self, phase: ProcessPhase) -> str:
        """Format process phase with colors."""
        phase_colors = {
            ProcessPhase.INITIALIZATION: Fore.CYAN,
            ProcessPhase.INTERVIEW: Fore.BLUE,
            ProcessPhase.USER_MODELING: Fore.MAGENTA,
            ProcessPhase.DEPLOYMENT_ANALYSIS: Fore.YELLOW,
            ProcessPhase.REQUIREMENT_ANALYSIS: Fore.GREEN,
            ProcessPhase.URL_REVIEW: Fore.YELLOW,
            ProcessPhase.REQUIREMENT_MODELING: Fore.GREEN,
            ProcessPhase.MODEL_REVIEW: Fore.YELLOW,
            ProcessPhase.SRS_GENERATION: Fore.CYAN,
            ProcessPhase.SRS_REVIEW: Fore.YELLOW,
            ProcessPhase.QUALITY_ASSURANCE: Fore.MAGENTA,
            ProcessPhase.COMPLETED: Fore.GREEN,
            ProcessPhase.FAILED: Fore.RED
        }
        color = phase_colors.get(phase, Fore.WHITE)
        return f"{color}{phase.value.replace('_', ' ').title()}{Style.RESET_ALL}"
    
    def cmd_start(self, args):
        """Start a new requirement development process."""
        self.print_header("Starting New Requirement Development Process")
        
        if not self.initialize_system():
            return 1
        
        # Collect project information
        project_name = args.project or input("Project name: ").strip()
        if not project_name:
            self.print_error("Project name is required")
            return 1
        
        domain = args.domain or input("Domain (e.g., web, mobile, enterprise): ").strip()
        if not domain:
            domain = "general"
        
        # Collect stakeholders
        stakeholders = []
        if args.stakeholders:
            stakeholders = [s.strip() for s in args.stakeholders.split(',')]
        else:
            print("Enter stakeholders (comma-separated, or press Enter to skip):")
            stakeholder_input = input().strip()
            if stakeholder_input:
                stakeholders = [s.strip() for s in stakeholder_input.split(',')]
        
        # Target environment
        target_env = args.environment or input("Target environment (e.g., cloud, on-premise, hybrid): ").strip()
        if not target_env:
            target_env = "cloud"
        
        # Create project configuration
        project_config = ProjectConfig(
            project_name=project_name,
            domain=domain,
            stakeholders=stakeholders,
            target_environment=target_env,
            compliance_requirements=args.compliance or [],
            quality_standards=args.standards or [],
            timeout_minutes=args.timeout or 1440
        )
        
        try:
            # Start the process
            session = self.orchestrator.start_requirement_process(
                project_config=project_config,
                created_by=args.user or "cli_user"
            )
            
            self.print_success(f"Started requirement development process")
            self.print_info(f"Session ID: {session.session_id}")
            self.print_info(f"Project: {project_name}")
            self.print_info(f"Domain: {domain}")
            self.print_info(f"Status: {self.format_status(session.status)}")
            
            # Save session ID for future reference
            self._save_last_session(session.session_id)
            
            if args.monitor:
                return self._monitor_process(session.session_id)
            
            return 0
            
        except Exception as e:
            self.print_error(f"Failed to start process: {e}")
            return 1
    
    def cmd_status(self, args):
        """Show status of requirement development processes."""
        self.print_header("Process Status")
        
        if not self.initialize_system():
            return 1
        
        session_id = args.session_id or self._get_last_session()
        
        if args.all:
            # Show all active sessions
            sessions = self.orchestrator.get_active_sessions()
            if not sessions:
                self.print_info("No active sessions found")
                return 0
            
            for session in sessions:
                self._display_session_status(session)
                print()
        
        elif session_id:
            # Show specific session
            session = self.orchestrator.get_process_status(session_id)
            if not session:
                self.print_error(f"Session {session_id} not found")
                return 1
            
            self._display_session_status(session, detailed=True)
        
        else:
            self.print_error("No session ID provided and no recent session found")
            self.print_info("Use --session-id or --all to specify which session to show")
            return 1
        
        return 0
    
    def cmd_monitor(self, args):
        """Monitor a requirement development process in real-time."""
        session_id = args.session_id or self._get_last_session()
        
        if not session_id:
            self.print_error("No session ID provided and no recent session found")
            return 1
        
        if not self.initialize_system():
            return 1
        
        return self._monitor_process(session_id, args.refresh or 5)
    
    def cmd_review(self, args):
        """Handle human review tasks."""
        self.print_header("Human Review Interface")
        
        if not self.initialize_system():
            return 1
        
        if args.list:
            return self._list_pending_reviews(args.session_id)
        
        elif args.submit:
            return self._submit_review(args)
        
        else:
            # Interactive review mode
            return self._interactive_review(args.session_id)
    
    def cmd_config(self, args):
        """Manage system configuration."""
        self.print_header("Configuration Management")
        
        if args.show:
            return self._show_config(args.section)
        
        elif args.set:
            return self._set_config(args.set[0], args.set[1])
        
        elif args.validate:
            return self._validate_config()
        
        elif args.reset:
            return self._reset_config()
        
        else:
            self.print_error("No configuration action specified")
            return 1
    
    def cmd_artifacts(self, args):
        """Manage artifacts."""
        self.print_header("Artifact Management")
        
        if not self.initialize_system():
            return 1
        
        if args.list:
            return self._list_artifacts(args.session_id, args.type)
        
        elif args.show:
            return self._show_artifact(args.show)
        
        elif args.export:
            return self._export_artifacts(args.session_id, args.export)
        
        else:
            self.print_error("No artifact action specified")
            return 1
    
    def _display_session_status(self, session: ProcessSession, detailed: bool = False):
        """Display session status information."""
        print(f"Session: {Fore.CYAN}{session.session_id}{Style.RESET_ALL}")
        print(f"Project: {session.project_config.project_name}")
        print(f"Status: {self.format_status(session.status)}")
        print(f"Phase: {self.format_phase(session.current_phase)}")
        print(f"Progress: {Fore.GREEN}{session.progress:.1%}{Style.RESET_ALL}")
        print(f"Created: {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Updated: {session.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if detailed:
            print(f"Domain: {session.project_config.domain}")
            print(f"Environment: {session.project_config.target_environment}")
            
            if session.project_config.stakeholders:
                print(f"Stakeholders: {', '.join(session.project_config.stakeholders)}")
            
            if session.active_agents:
                print(f"Active Agents: {', '.join(session.active_agents)}")
            
            if session.artifacts:
                print(f"Artifacts: {len(session.artifacts)} created")
            
            if session.error_log:
                print(f"{Fore.RED}Errors:{Style.RESET_ALL}")
                for error in session.error_log[-3:]:  # Show last 3 errors
                    print(f"  • {error}")
    
    def _monitor_process(self, session_id: str, refresh_interval: int = 5) -> int:
        """Monitor a process in real-time."""
        self.print_header(f"Monitoring Process: {session_id}")
        self.print_info(f"Refreshing every {refresh_interval} seconds (Press Ctrl+C to stop)")
        
        try:
            while True:
                # Clear screen (works on most terminals)
                os.system('cls' if os.name == 'nt' else 'clear')
                
                self.print_header(f"Monitoring Process: {session_id}")
                
                session = self.orchestrator.get_process_status(session_id)
                if not session:
                    self.print_error("Session not found")
                    return 1
                
                self._display_session_status(session, detailed=True)
                
                # Check for pending reviews
                if session.status == ProcessStatus.PAUSED_FOR_REVIEW:
                    print(f"\n{Fore.YELLOW}⏸ Process paused for human review{Style.RESET_ALL}")
                    pending_reviews = self.review_manager.get_pending_reviews(session_id=session_id)
                    if pending_reviews:
                        print(f"Pending reviews: {len(pending_reviews)}")
                        for review in pending_reviews[:3]:  # Show first 3
                            print(f"  • {review.description}")
                
                # Check if process is complete
                if session.status in [ProcessStatus.COMPLETED, ProcessStatus.FAILED, ProcessStatus.CANCELLED]:
                    print(f"\n{Fore.GREEN}Process completed with status: {self.format_status(session.status)}{Style.RESET_ALL}")
                    break
                
                print(f"\n{Fore.CYAN}Last updated: {datetime.now().strftime('%H:%M:%S')}{Style.RESET_ALL}")
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Monitoring stopped{Style.RESET_ALL}")
            return 0
        
        return 0
    
    def _list_pending_reviews(self, session_id: Optional[str] = None) -> int:
        """List pending reviews."""
        pending_reviews = self.review_manager.get_pending_reviews(session_id=session_id)
        
        if not pending_reviews:
            self.print_info("No pending reviews found")
            return 0
        
        print(f"Found {len(pending_reviews)} pending review(s):\n")
        
        for i, review in enumerate(pending_reviews, 1):
            print(f"{i}. {Fore.CYAN}{review.id}{Style.RESET_ALL}")
            print(f"   Description: {review.description}")
            print(f"   Phase: {review.phase}")
            print(f"   Artifact: {review.artifact_type.value}")
            print(f"   Created: {review.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Timeout: {review.timeout_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print()
        
        return 0
    
    def _submit_review(self, args) -> int:
        """Submit review feedback."""
        review_id = args.review_id
        if not review_id:
            self.print_error("Review ID is required")
            return 1
        
        # Get feedback type
        feedback_type_map = {
            'approve': FeedbackType.APPROVAL,
            'reject': FeedbackType.REJECTION,
            'modify': FeedbackType.MODIFICATION_REQUEST,
            'clarify': FeedbackType.CLARIFICATION_REQUEST
        }
        
        feedback_type = feedback_type_map.get(args.type, FeedbackType.MODIFICATION_REQUEST)
        
        # Get feedback content
        content = args.content or input("Feedback content: ").strip()
        if not content:
            self.print_error("Feedback content is required")
            return 1
        
        # Get suggestions if provided
        suggestions = []
        if args.suggestions:
            suggestions = [s.strip() for s in args.suggestions.split(',')]
        
        try:
            feedback = self.review_manager.submit_feedback(
                review_point_id=review_id,
                reviewer=args.reviewer or "cli_user",
                feedback_type=feedback_type,
                content=content,
                suggestions=suggestions,
                approval_status=feedback_type == FeedbackType.APPROVAL
            )
            
            self.print_success(f"Feedback submitted: {feedback.id}")
            return 0
            
        except Exception as e:
            self.print_error(f"Failed to submit feedback: {e}")
            return 1
    
    def _interactive_review(self, session_id: Optional[str] = None) -> int:
        """Interactive review interface."""
        pending_reviews = self.review_manager.get_pending_reviews(session_id=session_id)
        
        if not pending_reviews:
            self.print_info("No pending reviews found")
            return 0
        
        print(f"Found {len(pending_reviews)} pending review(s)")
        
        for review in pending_reviews:
            print(f"\n{Fore.CYAN}Review: {review.description}{Style.RESET_ALL}")
            print(f"Phase: {review.phase}")
            print(f"Artifact Type: {review.artifact_type.value}")
            
            # Get the artifact content
            artifact = self.artifact_pool.get_artifact(review.artifact_id)
            if artifact:
                print(f"\n{Fore.YELLOW}Artifact Content:{Style.RESET_ALL}")
                print(json.dumps(artifact.content, indent=2)[:500] + "..." if len(str(artifact.content)) > 500 else json.dumps(artifact.content, indent=2))
            
            # Get user input
            print(f"\n{Fore.GREEN}Options:{Style.RESET_ALL}")
            print("1. Approve")
            print("2. Request modifications")
            print("3. Reject")
            print("4. Skip this review")
            print("5. Exit")
            
            choice = input("\nYour choice (1-5): ").strip()
            
            if choice == '1':
                # Approve
                try:
                    self.review_manager.submit_feedback(
                        review_point_id=review.id,
                        reviewer="cli_user",
                        feedback_type=FeedbackType.APPROVAL,
                        content="Approved via CLI",
                        approval_status=True
                    )
                    self.print_success("Review approved")
                except Exception as e:
                    self.print_error(f"Failed to approve: {e}")
            
            elif choice == '2':
                # Request modifications
                content = input("Modification request: ").strip()
                if content:
                    try:
                        self.review_manager.submit_feedback(
                            review_point_id=review.id,
                            reviewer="cli_user",
                            feedback_type=FeedbackType.MODIFICATION_REQUEST,
                            content=content,
                            approval_status=False
                        )
                        self.print_success("Modification request submitted")
                    except Exception as e:
                        self.print_error(f"Failed to submit request: {e}")
            
            elif choice == '3':
                # Reject
                reason = input("Rejection reason: ").strip()
                if reason:
                    try:
                        self.review_manager.submit_feedback(
                            review_point_id=review.id,
                            reviewer="cli_user",
                            feedback_type=FeedbackType.REJECTION,
                            content=reason,
                            approval_status=False
                        )
                        self.print_success("Review rejected")
                    except Exception as e:
                        self.print_error(f"Failed to reject: {e}")
            
            elif choice == '4':
                # Skip
                continue
            
            elif choice == '5':
                # Exit
                break
            
            else:
                self.print_warning("Invalid choice")
        
        return 0
    
    def _show_config(self, section: Optional[str] = None) -> int:
        """Show configuration."""
        try:
            config = self.config_manager.load_config()
            
            if section:
                # Show specific section
                if section == 'agents':
                    print(f"{Fore.CYAN}Agent Configurations:{Style.RESET_ALL}")
                    for name, agent_config in config.agents.items():
                        print(f"\n{name}:")
                        print(f"  Enabled: {agent_config.enabled}")
                        print(f"  Max Turns: {agent_config.max_turns}")
                        print(f"  Timeout: {agent_config.timeout_seconds}s")
                        print(f"  Knowledge Modules: {', '.join(agent_config.knowledge_modules)}")
                
                elif section == 'knowledge':
                    print(f"{Fore.CYAN}Knowledge Base Configuration:{Style.RESET_ALL}")
                    for key, value in config.knowledge_base.items():
                        print(f"  {key}: {value}")
                
                elif section == 'human_in_loop':
                    print(f"{Fore.CYAN}Human-in-Loop Configuration:{Style.RESET_ALL}")
                    hil = config.human_in_loop
                    print(f"  Enabled: {hil.enabled}")
                    print(f"  Review Points: {', '.join(hil.review_points)}")
                    print(f"  Timeout: {hil.timeout_minutes} minutes")
                    print(f"  Notification Channels: {', '.join(hil.notification_channels)}")
                
                else:
                    self.print_error(f"Unknown configuration section: {section}")
                    return 1
            
            else:
                # Show all configuration
                print(f"{Fore.CYAN}Full Configuration:{Style.RESET_ALL}")
                config_dict = self.config_manager._config_to_dict(config)
                print(yaml.dump(config_dict, default_flow_style=False, indent=2))
            
            return 0
            
        except Exception as e:
            self.print_error(f"Failed to show configuration: {e}")
            return 1
    
    def _set_config(self, key: str, value: str) -> int:
        """Set configuration value."""
        # This is a simplified implementation
        # In practice, you'd want more sophisticated config setting
        self.print_warning("Configuration setting not yet implemented")
        self.print_info(f"Would set {key} = {value}")
        return 0
    
    def _validate_config(self) -> int:
        """Validate configuration."""
        try:
            config = self.config_manager.load_config()
            self.print_success("Configuration is valid")
            return 0
        except Exception as e:
            self.print_error(f"Configuration validation failed: {e}")
            return 1
    
    def _reset_config(self) -> int:
        """Reset configuration to defaults."""
        confirm = input("Are you sure you want to reset configuration to defaults? (y/N): ").strip().lower()
        if confirm == 'y':
            try:
                default_config = iReDevConfig.get_default_config()
                self.config_manager.save_config(default_config)
                self.print_success("Configuration reset to defaults")
                return 0
            except Exception as e:
                self.print_error(f"Failed to reset configuration: {e}")
                return 1
        else:
            self.print_info("Configuration reset cancelled")
            return 0
    
    def _list_artifacts(self, session_id: Optional[str] = None, artifact_type: Optional[str] = None) -> int:
        """List artifacts."""
        # This would need to be implemented based on artifact pool query capabilities
        self.print_warning("Artifact listing not yet implemented")
        return 0
    
    def _show_artifact(self, artifact_id: str) -> int:
        """Show artifact details."""
        try:
            artifact = self.artifact_pool.get_artifact(artifact_id)
            if not artifact:
                self.print_error(f"Artifact {artifact_id} not found")
                return 1
            
            print(f"{Fore.CYAN}Artifact: {artifact.id}{Style.RESET_ALL}")
            print(f"Type: {artifact.type.value}")
            print(f"Status: {artifact.status.value}")
            print(f"Created: {artifact.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Updated: {artifact.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"\n{Fore.YELLOW}Content:{Style.RESET_ALL}")
            print(json.dumps(artifact.content, indent=2))
            
            return 0
            
        except Exception as e:
            self.print_error(f"Failed to show artifact: {e}")
            return 1
    
    def _export_artifacts(self, session_id: Optional[str] = None, output_path: str = "artifacts_export") -> int:
        """Export artifacts."""
        self.print_warning("Artifact export not yet implemented")
        return 0
    
    def _save_last_session(self, session_id: str):
        """Save the last session ID for convenience."""
        try:
            session_file = Path.home() / ".iredev_last_session"
            session_file.write_text(session_id)
        except Exception:
            pass  # Ignore errors
    
    def _get_last_session(self) -> Optional[str]:
        """Get the last session ID."""
        try:
            session_file = Path.home() / ".iredev_last_session"
            if session_file.exists():
                return session_file.read_text().strip()
        except Exception:
            pass  # Ignore errors
        return None


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        description="iReDev Framework - Knowledge-driven Multi-agent Requirement Development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s start --project "E-commerce Platform" --domain web
  %(prog)s status --all
  %(prog)s monitor --session-id abc123
  %(prog)s review --list
  %(prog)s config --show agents
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start a new requirement development process')
    start_parser.add_argument('--project', help='Project name')
    start_parser.add_argument('--domain', help='Project domain (e.g., web, mobile, enterprise)')
    start_parser.add_argument('--stakeholders', help='Comma-separated list of stakeholders')
    start_parser.add_argument('--environment', help='Target environment (e.g., cloud, on-premise)')
    start_parser.add_argument('--compliance', nargs='*', help='Compliance requirements')
    start_parser.add_argument('--standards', nargs='*', help='Quality standards')
    start_parser.add_argument('--timeout', type=int, help='Process timeout in minutes')
    start_parser.add_argument('--user', help='User starting the process')
    start_parser.add_argument('--monitor', action='store_true', help='Monitor the process after starting')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show process status')
    status_parser.add_argument('--session-id', help='Specific session ID to show')
    status_parser.add_argument('--all', action='store_true', help='Show all active sessions')
    
    # Monitor command
    monitor_parser = subparsers.add_parser('monitor', help='Monitor a process in real-time')
    monitor_parser.add_argument('--session-id', help='Session ID to monitor')
    monitor_parser.add_argument('--refresh', type=int, default=5, help='Refresh interval in seconds')
    
    # Review command
    review_parser = subparsers.add_parser('review', help='Handle human review tasks')
    review_parser.add_argument('--list', action='store_true', help='List pending reviews')
    review_parser.add_argument('--session-id', help='Filter reviews by session ID')
    review_parser.add_argument('--submit', action='store_true', help='Submit review feedback')
    review_parser.add_argument('--review-id', help='Review ID for submission')
    review_parser.add_argument('--type', choices=['approve', 'reject', 'modify', 'clarify'], 
                              default='modify', help='Feedback type')
    review_parser.add_argument('--content', help='Feedback content')
    review_parser.add_argument('--suggestions', help='Comma-separated suggestions')
    review_parser.add_argument('--reviewer', help='Reviewer name')
    
    # Config command
    config_parser = subparsers.add_parser('config', help='Manage system configuration')
    config_parser.add_argument('--show', action='store_true', help='Show configuration')
    config_parser.add_argument('--section', choices=['agents', 'knowledge', 'human_in_loop'], 
                              help='Show specific configuration section')
    config_parser.add_argument('--set', nargs=2, metavar=('KEY', 'VALUE'), help='Set configuration value')
    config_parser.add_argument('--validate', action='store_true', help='Validate configuration')
    config_parser.add_argument('--reset', action='store_true', help='Reset to default configuration')
    
    # Artifacts command
    artifacts_parser = subparsers.add_parser('artifacts', help='Manage artifacts')
    artifacts_parser.add_argument('--list', action='store_true', help='List artifacts')
    artifacts_parser.add_argument('--session-id', help='Filter artifacts by session ID')
    artifacts_parser.add_argument('--type', help='Filter artifacts by type')
    artifacts_parser.add_argument('--show', help='Show specific artifact by ID')
    artifacts_parser.add_argument('--export', help='Export artifacts to directory')
    
    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    cli = iReDevCLI()
    
    # Route to appropriate command handler
    command_handlers = {
        'start': cli.cmd_start,
        'status': cli.cmd_status,
        'monitor': cli.cmd_monitor,
        'review': cli.cmd_review,
        'config': cli.cmd_config,
        'artifacts': cli.cmd_artifacts
    }
    
    handler = command_handlers.get(args.command)
    if handler:
        try:
            return handler(args)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Operation cancelled by user{Style.RESET_ALL}")
            return 1
        except Exception as e:
            print(f"{Fore.RED}Unexpected error: {e}{Style.RESET_ALL}")
            if args.command == 'config' and hasattr(args, 'debug'):
                import traceback
                traceback.print_exc()
            return 1
    else:
        print(f"{Fore.RED}Unknown command: {args.command}{Style.RESET_ALL}")
        return 1


if __name__ == "__main__":
    sys.exit(main())