from typing import Dict, Set, List
from colorama import Fore, Back, Style, init
import sys
import os

class StatusVisualizer:
    """Visualizes the workflow status of DocAssist agents in the terminal."""

    def __init__(self):
        """Initialize the status visualizer."""
        init()  # Initialize colorama
        self.active_agents = [] # Track only the currently active agents
        self._agent_art = {
            'Interviewer': [
                "┌─────────------┐",
                "│  Interviewer  │",
                "└─────────------┘"
            ],
            'Customer': [
                "┌─────────------┐",
                "│   Customer    │",
                "└─────────------┘"
            ],
            'User': [
                "┌─────────------┐",
                "│     User      │",
                "└─────────------┘"
            ],
            "Developer": [
                "┌─────────------┐",
                "│   Developer   │",
                "└─────────------┘"
            ],
            'Analyst': [
                "┌─────────------┐",
                "│    Analyst    │",
                "└─────────------┘"
            ],
            "Reviewer": [
                "┌─────────------┐",
                "│   Reviewer    │",
                "└─────────------┘"
            ],
            "Archivist": [
                "┌─────────------┐",
                "│   Archivist   │",
                "└─────────------┘"
            ],
        }
        self._status_messages = ""
        self._current_artifact = ""
        self._current_file = ""

    def _clear_screen(self):
        """Clear the terminal screen."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    def _get_agent_color(self, agent: str) -> str:
        """Get the color for an agent based on its state."""
        return Fore.GREEN if agent in self.active_agents else Fore.WHITE
    
    def set_current_artifact(self, repo_dir: str, artifact: str):
        """Set the current artifact being processed."""
        self._current_artifact = artifact
        self._current_file = os.path.join(repo_dir, artifact)
        self._display_artifact_info()

    def _display_artifact_info(self):
        """Display information about the current artifact."""
        print(f"Artifact: {self._current_artifact}")
        print(f"File: {self._current_file}")
    
    def update(self, active_agents: List[str], status_messages: str):
        """Update the visualizer with the current active agents and status messages."""
        self.active_agents = active_agents
        self._status_messages = status_messages
        self._clear_screen()

        # Build the visualization
        lines = []

        # Display current artifact info if available
        if self._current_artifact and self._current_file:
            lines.append(f"Processing Artifact: {self._current_artifact}")
            lines.append(f"File: {self._current_file}")
            lines.append("")

        # First row: Customer
        for i in range(3):
            line = f"        {self._get_agent_color('Customer')}{self._agent_art['Customer'][i]}{Style.RESET_ALL}"
            lines.append(line)

        # Arrows between Customer and Interviewer
        lines.append("              ↕") 
        lines.append("")

        # Second row: User and Interviewer
        for i in range(3):
            user_line = f"{self._get_agent_color('User')}{self._agent_art['User'][i]}{Style.RESET_ALL}"
            interviewer_line = f"{self._get_agent_color('Interviewer')}{self._agent_art['Interviewer'][i]}{Style.RESET_ALL}"
            if i == 2:
                line = f"{user_line}  ←→  {interviewer_line}"
            else:
                line = f"{user_line}       {interviewer_line}"
            lines.append(line)
        
        # Arrows between Interviewer and Analyst/Archivist
        lines.append("    ↙         ↘")
        lines.append("   ↙           ↘")
        lines.append("  ↙             ↘")

        # Third row: Analyst, Archivist, and Reviewer
        for i in range(3):
            analyst_line = f"{self._get_agent_color('Analyst')}{self._agent_art['Analyst'][i]}{Style.RESET_ALL}"
            archivist_line = f"{self._get_agent_color('Archivist')}{self._agent_art['Archivist'][i]}{Style.RESET_ALL}"
            reviewer_line = f"{self._get_agent_color('Reviewer')}{self._agent_art['Reviewer'][i]}{Style.RESET_ALL}"
            if i == 2:
                line = f"{analyst_line}          {archivist_line}  ←→  {reviewer_line}"
            else:
                line = f"{analyst_line}          {archivist_line}       {reviewer_line}"
            lines.append(line)
        
        # Arrows between Analyst/Archivist and Developer
        lines.append("    ↘         ↙")
        lines.append("     ↘       ↙")
        lines.append("      ↘     ↙")

        # Fourth row: Developer
        for i in range(3):
            line = f"        {self._get_agent_color('Developer')}{self._agent_art['Developer'][i]}{Style.RESET_ALL}"
            lines.append(line)
        
        # Add status message
        if self._status_message:
            lines.append("")
            lines.append(f"{Fore.YELLOW}Status: {self._status_message}{Style.RESET_ALL}")
        
        # Print the visualization
        print("\n".join(lines))
        sys.stdout.flush()

    def reset(self):
        """Reset the visualization state."""
        self.active_agent = None
        self._status_message = ""
        self._current_component = ""
        self._current_file = ""
        self._clear_screen() 




        
