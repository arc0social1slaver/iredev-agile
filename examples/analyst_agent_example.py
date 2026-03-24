#!/usr/bin/env python3
"""
Example usage of AnalystAgent for requirements analysis and transformation.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.agent.analyst import AnalystAgent, SystemRequirement, RequirementModel, TraceabilityMatrix
from datetime import datetime

def main():
    """Demonstrate AnalystAgent capabilities."""
    print("=== AnalystAgent Example ===\n")
    
    # Initialize the analyst agent
    print("1. Initializing AnalystAgent...")
    agent = AnalystAgent()
    print(f"   Agent name: {agent.name}")
    print(f"   Knowledge modules required: {len(agent.required_knowledge_modules)}")
    print()
    
    # Example user requirements (from interviews)
    print("2. Sample User Requirements:")
    user_requirements = [
        {
            "id": "user-req-1",
            "title": "User Login",
            "description": "As a user, I want to log into the system securely",
            "priority": "high",
            "source": "stakeholder_interview"
        },
        {
            "id": "user-req-2", 
            "title": "Fast Response",
            "description": "As a user, I want the system to respond quickly to my requests",
            "priority": "medium",
            "source": "user_persona_analysis"
        }
    ]
    
    for req in user_requirements:
        print(f"   - {req['title']}: {req['description']}")
    print()
    
    # Example system context
    context = {
        "domain": "web_application",
        "target_users": ["end_users", "administrators"],
        "deployment_environment": "cloud",
        "security_requirements": "standard"
    }
    
    print("3. System Context:")
    for key, value in context.items():
        print(f"   - {key}: {value}")
    print()
    
    # Create sample system requirements (simulating the transformation process)
    print("4. Creating System Requirements...")
    system_requirements = [
        SystemRequirement(
            id="sys-req-1",
            title="Authentication System",
            description="System shall implement secure user authentication with username/password",
            category="functional",
            priority="high",
            source_user_requirements=["user-req-1"],
            rationale="Required for secure user access as specified in user requirements",
            acceptance_criteria=[
                "User can login with valid credentials",
                "Invalid credentials are rejected with appropriate error message",
                "Account lockout after 3 failed attempts"
            ],
            verification_method="test"
        ),
        SystemRequirement(
            id="sys-req-2",
            title="Response Time Performance",
            description="System shall respond to user requests within 2 seconds for 95% of requests",
            category="non_functional",
            priority="medium",
            source_user_requirements=["user-req-2"],
            rationale="Required for acceptable user experience as identified in user analysis",
            acceptance_criteria=[
                "95% of requests complete within 2 seconds",
                "No request takes longer than 5 seconds"
            ],
            verification_method="test"
        )
    ]
    
    for req in system_requirements:
        print(f"   - {req.title} ({req.category})")
        print(f"     Priority: {req.priority}")
        print(f"     Verification: {req.verification_method}")
    print()
    
    # Create requirement model
    print("5. Creating Requirement Model...")
    stakeholder_info = {
        "end_users": {
            "role": "Primary system users",
            "responsibilities": ["Use system features", "Provide feedback"]
        },
        "administrators": {
            "role": "System administrators", 
            "responsibilities": ["Manage users", "Monitor system"]
        }
    }
    
    model = RequirementModel(
        id="model-1",
        functional_requirements=[req for req in system_requirements if req.category == "functional"],
        non_functional_requirements=[req for req in system_requirements if req.category == "non_functional"],
        assumptions=[
            "Users have basic computer literacy",
            "Internet connection is available",
            "Modern web browser is used"
        ],
        stakeholders=[
            {"name": name, **info} for name, info in stakeholder_info.items()
        ],
        glossary={
            "User": "Any person who interacts with the system",
            "Authentication": "Process of verifying user identity",
            "Response Time": "Time taken for system to respond to a request"
        }
    )
    
    print(f"   Model ID: {model.id}")
    print(f"   Functional requirements: {len(model.functional_requirements)}")
    print(f"   Non-functional requirements: {len(model.non_functional_requirements)}")
    print(f"   Stakeholders: {len(model.stakeholders)}")
    print(f"   Glossary terms: {len(model.glossary)}")
    print()
    
    # Demonstrate prioritization
    print("6. Requirements Prioritization:")
    criteria = {
        "business_value": "high",
        "implementation_risk": "medium",
        "user_impact": "high"
    }
    
    # Sort by priority for demonstration
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_reqs = sorted(system_requirements, key=lambda r: priority_order.get(r.priority, 2))
    
    print("   Prioritized requirements:")
    for i, req in enumerate(sorted_reqs, 1):
        print(f"   {i}. {req.title} (Priority: {req.priority})")
    print()
    
    # Show traceability
    print("7. Traceability Matrix:")
    print("   User Requirement -> System Requirement")
    for sys_req in system_requirements:
        for user_req_id in sys_req.source_user_requirements:
            user_req = next((ur for ur in user_requirements if ur["id"] == user_req_id), None)
            if user_req:
                print(f"   {user_req['title']} -> {sys_req.title}")
    print()
    
    print("✅ AnalystAgent example completed successfully!")
    print("\nThe AnalystAgent provides:")
    print("- Requirements transformation from user to system requirements")
    print("- Structured requirement modeling with categorization")
    print("- Traceability matrix establishment")
    print("- Requirements prioritization and conflict detection")
    print("- Change impact analysis capabilities")

if __name__ == "__main__":
    main()