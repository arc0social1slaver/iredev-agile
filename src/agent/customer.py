from typing import Optional
from pathlib import Path
import sys

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agent.base import BaseAgent
# REMOVED: from src.agent.interviewer import Interviewer (Moved to __main__ to prevent circular import)

class Customer(BaseAgent):
    """Human Input to provide goal and confirm"""

    def __init__(self, config_path: Optional[str] = None):
        super().__init__("customer", config_path)

    def process(self, *args, **kwargs) -> any:
        """
        Process method to satisfy the abstract base class requirement.
        """
        pass

    def chat_with_interviewer(self, question: str):
        """Chat with the interviewer to provide goal and confirm"""
        answer = input("Customer (You): ")
        return answer

    def receive_artifact(self, artifact) -> None:
        """Receive feedback artifact from Interviewer after the interview concludes"""
        print(f"\n[Customer] Received Feedback Artifact: {artifact.metadata.title}")
        print(f"[Customer] Artifact ID: {artifact.id}")

        # Extract information from artifact content
        metadata = artifact.content.get("interview_metadata", {})
        reqs = artifact.content.get("requirements_discovered", {})

        print(f"  - Interview quality score: {metadata.get('quality_score', 0)}")
        print(f"  - Functional requirements collected: {len(reqs.get('functional_requirements', []))}")
        print(f"  - Non-functional requirements collected: {len(reqs.get('non_functional_requirements', []))}")


# Main block to run communication flow and receive Artifact
if __name__ == "__main__":
    # Import here to avoid circular import with src.agent.interviewer
    from src.agent.interviewer import Interviewer

    # 1. Initialize Agents
    customer = Customer()
    interviewer = Interviewer()

    print("=== STARTING INTERVIEW SESSION ===")

    # 2. Start conversation (Interviewer will continuously call customer.chat_with_interviewer)
    interview_record = interviewer.chat_with_customer(customer, stakeholder_type="customer")

    print("\n=== PROCESSING RESULTS AND CREATING ARTIFACT ===")

    # 3. Package interview results into Artifact
    interview_artifact = interviewer.create_interview_artifact(interview_record)

    # 4. Pass feedback Artifact back to Customer
    customer.receive_artifact(interview_artifact)

    # 5. (Optional) Print detailed summary report to screen
    print("\n" + interviewer.generate_interview_summary_report(interview_record))