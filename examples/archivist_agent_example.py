#!/usr/bin/env python3
"""
Example usage of ArchivistAgent for generating SRS documents.

This example demonstrates how to use the ArchivistAgent to:
1. Generate SRS documents from requirements
2. Apply document templates
3. Check standard compliance
4. Assess document quality
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from datetime import datetime
from src.agent.archivist import ArchivistAgent
from src.knowledge.knowledge_manager import KnowledgeManager
from src.artifact.events import EventBus


def create_sample_requirements():
    """Create sample requirements for demonstration."""
    return [
        {
            "id": "REQ-001",
            "title": "User Authentication",
            "description": "The system shall provide secure user authentication mechanism",
            "category": "functional",
            "priority": "high",
            "acceptance_criteria": ["User can login with valid credentials", "Invalid credentials are rejected"],
            "verification_method": "test"
        },
        {
            "id": "REQ-002", 
            "title": "System Performance",
            "description": "The system shall respond to user requests within 2 seconds",
            "category": "non_functional",
            "priority": "medium",
            "acceptance_criteria": ["Response time < 2 seconds for 95% of requests"],
            "verification_method": "test"
        },
        {
            "id": "REQ-003",
            "title": "Data Security",
            "description": "The system shall encrypt all sensitive data at rest and in transit",
            "category": "non_functional",
            "priority": "critical",
            "acceptance_criteria": ["All data encrypted using AES-256", "TLS 1.3 for data in transit"],
            "verification_method": "inspection"
        }
    ]


def create_sample_requirement_model():
    """Create sample requirement model for demonstration."""
    return {
        "id": "MODEL-001",
        "functional_requirements": [
            {
                "id": "REQ-001",
                "title": "User Authentication",
                "description": "The system shall provide secure user authentication mechanism"
            }
        ],
        "non_functional_requirements": [
            {
                "id": "REQ-002",
                "title": "System Performance", 
                "description": "The system shall respond to user requests within 2 seconds"
            },
            {
                "id": "REQ-003",
                "title": "Data Security",
                "description": "The system shall encrypt all sensitive data at rest and in transit"
            }
        ],
        "constraints": [
            {
                "title": "Technology Constraint",
                "description": "Must use approved technology stack"
            }
        ],
        "assumptions": [
            "Users have basic computer literacy",
            "Network connectivity is available"
        ],
        "dependencies": [
            {
                "source": "REQ-001",
                "target": "REQ-003",
                "type": "depends_on"
            }
        ],
        "stakeholders": [
            {
                "role": "End User",
                "description": "Primary system users with basic technical knowledge"
            },
            {
                "role": "System Administrator", 
                "description": "Technical users responsible for system maintenance"
            }
        ],
        "glossary": {
            "SRS": "Software Requirements Specification",
            "API": "Application Programming Interface",
            "TLS": "Transport Layer Security"
        }
    }


def create_sample_project_info():
    """Create sample project information."""
    return {
        "name": "Sample Management System",
        "version": "1.0",
        "authors": ["Requirements Engineer", "System Analyst"],
        "description": "A comprehensive management system for business operations",
        "domain": "Business Management",
        "template": "srs_template"
    }


def main():
    """Main example function."""
    print("=== ArchivistAgent Example ===\n")
    
    try:
        # Initialize knowledge manager and event bus
        knowledge_config = {
            "base_path": os.path.join(os.path.dirname(__file__), '..', 'knowledge'),
            "cache_enabled": True,
            "auto_reload": True
        }
        knowledge_manager = KnowledgeManager(knowledge_config)
        event_bus = EventBus()
        
        # Initialize ArchivistAgent
        print("1. Initializing ArchivistAgent...")
        archivist = ArchivistAgent(
            knowledge_manager=knowledge_manager,
            event_bus=event_bus
        )
        print(f"   ✓ Agent initialized with {len(archivist.knowledge_modules)} knowledge modules")
        print(f"   ✓ Supported standards: {archivist.supported_standards}")
        print(f"   ✓ Document templates loaded: {len(archivist.document_templates)}")
        
        # Start session
        session_id = "example_session_001"
        archivist.start_session(session_id)
        print(f"   ✓ Session started: {session_id}\n")
        
        # Prepare sample data
        requirements = create_sample_requirements()
        requirement_model = create_sample_requirement_model()
        project_info = create_sample_project_info()
        
        print("2. Sample Data Prepared:")
        print(f"   - Requirements: {len(requirements)}")
        print(f"   - Requirement model sections: {len(requirement_model)}")
        print(f"   - Project: {project_info['name']}\n")
        
        # Generate SRS document
        print("3. Generating SRS Document...")
        srs_document = archivist.generate_srs_document(
            requirements=requirements,
            requirement_model=requirement_model,
            project_info=project_info
        )
        print(f"   ✓ SRS document generated: {srs_document.id}")
        print(f"   ✓ Title: {srs_document.title}")
        print(f"   ✓ Version: {srs_document.version}")
        print(f"   ✓ Sections: {len(srs_document.sections)}")
        print(f"   ✓ Standard compliance: {srs_document.standard_compliance}\n")
        
        # Apply document template
        print("4. Applying Document Template...")
        if archivist.document_templates:
            template_id = list(archivist.document_templates.keys())[0]
            updated_document = archivist.apply_document_template(srs_document, template_id)
            print(f"   ✓ Template applied: {template_id}")
            print(f"   ✓ Updated compliance: {updated_document.standard_compliance}")
        else:
            print("   ! No templates available")
        
        # Organize document structure
        print("\n5. Organizing Document Structure...")
        content = srs_document.to_dict()
        organized_structure = archivist.organize_document_structure(
            content=content,
            standard="IEEE 830"
        )
        print(f"   ✓ Structure organized according to IEEE 830")
        print(f"   ✓ Organization applied: {organized_structure.get('organization_applied', False)}")
        
        # Check standard compliance
        print("\n6. Checking Standard Compliance...")
        compliance_report = archivist.ensure_standard_compliance(
            document=srs_document,
            standard="IEEE 830"
        )
        print(f"   ✓ Compliance report generated: {compliance_report.id}")
        print(f"   ✓ Compliance score: {compliance_report.compliance_score:.2f}")
        print(f"   ✓ Violations found: {len(compliance_report.violations)}")
        print(f"   ✓ Recommendations: {len(compliance_report.recommendations)}")
        
        # Assess document quality
        print("\n7. Assessing Document Quality...")
        quality_metrics = archivist.assess_document_quality(srs_document)
        print("   ✓ Quality metrics:")
        for metric, score in quality_metrics.items():
            print(f"     - {metric.capitalize()}: {score:.2f}")
        
        # Display document structure
        print("\n8. Document Structure Overview:")
        for section in srs_document.sections:
            print(f"   {section.number}. {section.title}")
            for subsection in section.subsections:
                print(f"     {subsection.number}. {subsection.title}")
        
        # Display quality summary
        print(f"\n9. Quality Summary:")
        print(f"   - Document ID: {srs_document.id}")
        print(f"   - Total sections: {len(srs_document.sections)}")
        print(f"   - Completeness: {srs_document.completeness_score:.2f}")
        print(f"   - Consistency: {srs_document.consistency_score:.2f}")
        print(f"   - Traceability: {srs_document.traceability_score:.2f}")
        print(f"   - Compliance score: {compliance_report.compliance_score:.2f}")
        
        # Show agent statistics
        print(f"\n10. Agent Statistics:")
        print(f"    - SRS documents created: {len(archivist.srs_documents)}")
        print(f"    - Compliance reports: {len(archivist.compliance_reports)}")
        print(f"    - Templates available: {len(archivist.document_templates)}")
        print(f"    - Knowledge modules: {len(archivist.knowledge_modules)}")
        
        print("\n=== Example completed successfully! ===")
        
    except Exception as e:
        print(f"Error during example execution: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())