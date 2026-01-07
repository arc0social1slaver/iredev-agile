#!/usr/bin/env python3
"""
Example usage of ReviewerAgent for iReDev framework.
Demonstrates quality validation, assessment, and improvement recommendations.
"""

import sys
import os
import json
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.agent.reviewer import ReviewerAgent
from src.knowledge.knowledge_manager import KnowledgeManager
from src.artifact.events import EventBus


def create_sample_srs_document():
    """Create a sample SRS document for testing."""
    return {
        "id": "srs-001",
        "title": "Sample System Software Requirements Specification",
        "version": "1.0",
        "date": datetime.now().isoformat(),
        "authors": ["System Analyst"],
        "project_name": "Sample System",
        "sections": [
            {
                "id": "sec-1",
                "number": "1",
                "title": "Introduction",
                "content": "This document specifies requirements for the sample system.",
                "subsections": [
                    {
                        "id": "sec-1-1",
                        "number": "1.1",
                        "title": "Purpose",
                        "content": "The purpose is to define system requirements."
                    },
                    {
                        "id": "sec-1-2",
                        "number": "1.2",
                        "title": "Scope",
                        "content": "The system shall provide user management functionality."
                    }
                ]
            },
            {
                "id": "sec-2",
                "number": "2",
                "title": "Overall Description",
                "content": "The system is a web-based application.",
                "subsections": [
                    {
                        "id": "sec-2-1",
                        "number": "2.1",
                        "title": "Product Functions",
                        "content": "User registration, login, and profile management."
                    }
                ]
            },
            {
                "id": "sec-3",
                "number": "3",
                "title": "Specific Requirements",
                "content": "Detailed functional and non-functional requirements.",
                "subsections": [
                    {
                        "id": "sec-3-1",
                        "number": "3.1",
                        "title": "Functional Requirements",
                        "content": "FUNC-001: The system shall authenticate users within 3 seconds."
                    }
                ]
            }
        ],
        "glossary": {
            "SRS": "Software Requirements Specification",
            "API": "Application Programming Interface"
        },
        "references": [
            {"id": "IEEE830", "title": "IEEE Std 830-1998", "author": "IEEE", "date": "1998"}
        ]
    }


def create_sample_requirements():
    """Create sample system requirements."""
    return [
        {
            "id": "req-001",
            "title": "User Authentication",
            "description": "System shall provide secure user authentication",
            "category": "functional",
            "priority": "high"
        },
        {
            "id": "req-002",
            "title": "Response Time",
            "description": "System shall respond within 2 seconds",
            "category": "non_functional",
            "priority": "medium"
        },
        {
            "id": "req-003",
            "title": "Data Security",
            "description": "System shall encrypt sensitive data",
            "category": "functional",
            "priority": "high"
        }
    ]


def create_sample_traceability_matrix():
    """Create sample traceability matrix."""
    return {
        "id": "trace-001",
        "links": [
            {
                "id": "link-001",
                "source_id": "user-req-001",
                "target_id": "req-001",
                "link_type": "derives_from",
                "description": "System requirement derives from user requirement"
            },
            {
                "id": "link-002",
                "source_id": "user-req-002",
                "target_id": "req-002",
                "link_type": "derives_from",
                "description": "Performance requirement derives from user need"
            }
        ],
        "coverage_analysis": {
            "total_links": 2,
            "forward_links": 2,
            "backward_links": 0
        }
    }


def demonstrate_consistency_validation(reviewer_agent, srs_document):
    """Demonstrate consistency validation functionality."""
    print("\n" + "="*60)
    print("CONSISTENCY VALIDATION DEMONSTRATION")
    print("="*60)
    
    print("Validating document consistency...")
    consistency_report = reviewer_agent.validate_consistency(srs_document)
    
    print(f"\nConsistency Report:")
    print(f"  Document ID: {consistency_report.document_id}")
    print(f"  Consistency Score: {consistency_report.consistency_score:.2f}")
    print(f"  Total Violations: {len(consistency_report.violations)}")
    
    if consistency_report.violations:
        print(f"\nTop Violations:")
        for i, violation in enumerate(consistency_report.violations[:3]):
            print(f"  {i+1}. {violation.violation_type}: {violation.description}")
            print(f"     Severity: {violation.severity}, Location: {violation.location}")
    
    print(f"\nSummary:")
    for key, value in consistency_report.summary.items():
        print(f"  {key}: {value}")


def demonstrate_completeness_checking(reviewer_agent, srs_document, requirements):
    """Demonstrate completeness checking functionality."""
    print("\n" + "="*60)
    print("COMPLETENESS CHECKING DEMONSTRATION")
    print("="*60)
    
    print("Checking document completeness...")
    completeness_report = reviewer_agent.check_completeness(srs_document, requirements)
    
    print(f"\nCompleteness Report:")
    print(f"  Document ID: {completeness_report.document_id}")
    print(f"  Completeness Score: {completeness_report.completeness_score:.2f}")
    print(f"  Total Gaps: {len(completeness_report.gaps)}")
    
    if completeness_report.gaps:
        print(f"\nTop Gaps:")
        for i, gap in enumerate(completeness_report.gaps[:3]):
            print(f"  {i+1}. {gap.gap_type}: {gap.description}")
            print(f"     Severity: {gap.severity}")
            print(f"     Expected: {gap.expected_content}")
    
    print(f"\nCoverage Analysis:")
    for key, value in completeness_report.coverage_analysis.items():
        print(f"  {key}: {value}")


def demonstrate_traceability_verification(reviewer_agent, srs_document, traceability_matrix):
    """Demonstrate traceability verification functionality."""
    print("\n" + "="*60)
    print("TRACEABILITY VERIFICATION DEMONSTRATION")
    print("="*60)
    
    print("Verifying requirements traceability...")
    traceability_report = reviewer_agent.verify_traceability(srs_document, traceability_matrix)
    
    print(f"\nTraceability Report:")
    print(f"  Document ID: {traceability_report.document_id}")
    print(f"  Traceability Score: {traceability_report.traceability_score:.2f}")
    print(f"  Total Issues: {len(traceability_report.issues)}")
    
    if traceability_report.issues:
        print(f"\nTop Issues:")
        for i, issue in enumerate(traceability_report.issues[:3]):
            print(f"  {i+1}. {issue.issue_type}: {issue.description}")
            print(f"     Severity: {issue.severity}")
            print(f"     Source: {issue.source_id}, Target: {issue.target_id}")
    
    print(f"\nCoverage Matrix:")
    for key, value in traceability_report.coverage_matrix.items():
        print(f"  {key}: {value}")


def demonstrate_quality_assessment(reviewer_agent, srs_document):
    """Demonstrate quality metrics assessment."""
    print("\n" + "="*60)
    print("QUALITY ASSESSMENT DEMONSTRATION")
    print("="*60)
    
    print("Assessing document quality metrics...")
    quality_metrics = reviewer_agent.assess_quality_metrics(srs_document)
    
    print(f"\nQuality Metrics:")
    print(f"  Document ID: {quality_metrics.document_id}")
    print(f"  Overall Score: {quality_metrics.overall_score:.2f}")
    print(f"  Consistency Score: {quality_metrics.consistency_score:.2f}")
    print(f"  Completeness Score: {quality_metrics.completeness_score:.2f}")
    print(f"  Traceability Score: {quality_metrics.traceability_score:.2f}")
    print(f"  Clarity Score: {quality_metrics.clarity_score:.2f}")
    print(f"  Verifiability Score: {quality_metrics.verifiability_score:.2f}")
    print(f"  Defect Density: {quality_metrics.defect_density:.2f}")
    print(f"  Improvement Potential: {quality_metrics.improvement_potential:.2f}")


def demonstrate_defect_identification(reviewer_agent, srs_document):
    """Demonstrate quality defect identification."""
    print("\n" + "="*60)
    print("DEFECT IDENTIFICATION DEMONSTRATION")
    print("="*60)
    
    print("Identifying quality defects...")
    defects = reviewer_agent.identify_quality_defects(srs_document)
    
    print(f"\nIdentified {len(defects)} quality defects:")
    for i, defect in enumerate(defects[:5]):
        print(f"\n  {i+1}. {defect.defect_type.upper()}")
        print(f"     Description: {defect.description}")
        print(f"     Severity: {defect.severity}")
        print(f"     Location: {defect.location}")
        print(f"     Impact: {defect.impact}")
        if defect.recommendation:
            print(f"     Recommendation: {defect.recommendation}")


def demonstrate_improvement_recommendations(reviewer_agent, srs_document, quality_metrics, defects):
    """Demonstrate improvement recommendations generation."""
    print("\n" + "="*60)
    print("IMPROVEMENT RECOMMENDATIONS DEMONSTRATION")
    print("="*60)
    
    print("Generating improvement recommendations...")
    recommendations = reviewer_agent.generate_improvement_recommendations(
        srs_document, quality_metrics, defects
    )
    
    print(f"\nGenerated {len(recommendations)} improvement recommendations:")
    for i, rec in enumerate(recommendations[:5]):
        print(f"\n  {i+1}. {rec.title}")
        print(f"     Category: {rec.category}")
        print(f"     Priority: {rec.priority}")
        print(f"     Description: {rec.description}")
        print(f"     Implementation Effort: {rec.implementation_effort}")
        print(f"     Expected Benefit: {rec.expected_benefit}")
        if rec.action_items:
            print(f"     Action Items: {', '.join(rec.action_items[:2])}")


def demonstrate_comprehensive_review(reviewer_agent, srs_document, requirements, traceability_matrix):
    """Demonstrate comprehensive review functionality."""
    print("\n" + "="*60)
    print("COMPREHENSIVE REVIEW DEMONSTRATION")
    print("="*60)
    
    print("Performing comprehensive document review...")
    review_report = reviewer_agent.perform_comprehensive_review(
        srs_document, requirements, traceability_matrix
    )
    
    print(f"\nComprehensive Review Report:")
    print(f"  Document ID: {review_report['document_id']}")
    print(f"  Review Date: {review_report['review_date']}")
    print(f"  Reviewer: {review_report['reviewer']}")
    
    print(f"\nOverall Assessment:")
    assessment = review_report['overall_assessment']
    print(f"  Quality Level: {assessment['overall_quality_level']}")
    print(f"  Overall Score: {assessment['overall_score']:.2f}")
    print(f"  Total Issues: {assessment['total_issues']}")
    print(f"  Critical Issues: {assessment['critical_issues']}")
    
    if assessment['strengths']:
        print(f"  Strengths: {', '.join(assessment['strengths'])}")
    
    if assessment['weaknesses']:
        print(f"  Weaknesses: {', '.join(assessment['weaknesses'])}")
    
    print(f"  Recommendation: {assessment['recommendation_summary']}")


def main():
    """Main demonstration function."""
    print("ReviewerAgent Demonstration")
    print("="*60)
    
    # Initialize components
    print("Initializing ReviewerAgent...")
    
    # Create knowledge manager
    import os
    knowledge_config = {
        "base_path": os.path.join(os.path.dirname(__file__), '..', 'knowledge'),
        "cache_enabled": True,
        "auto_reload": True
    }
    knowledge_manager = KnowledgeManager(knowledge_config)
    
    # Create event bus
    event_bus = EventBus()
    
    # Initialize ReviewerAgent
    reviewer_agent = ReviewerAgent(
        knowledge_manager=knowledge_manager,
        event_bus=event_bus
    )
    
    # Create sample data
    srs_document = create_sample_srs_document()
    requirements = create_sample_requirements()
    traceability_matrix = create_sample_traceability_matrix()
    
    print(f"Created sample SRS document with {len(srs_document['sections'])} sections")
    print(f"Created {len(requirements)} sample requirements")
    print(f"Created traceability matrix with {len(traceability_matrix['links'])} links")
    
    # Demonstrate individual validation functions
    demonstrate_consistency_validation(reviewer_agent, srs_document)
    demonstrate_completeness_checking(reviewer_agent, srs_document, requirements)
    demonstrate_traceability_verification(reviewer_agent, srs_document, traceability_matrix)
    
    # Demonstrate quality assessment
    demonstrate_quality_assessment(reviewer_agent, srs_document)
    
    # Demonstrate defect identification
    demonstrate_defect_identification(reviewer_agent, srs_document)
    
    # Get quality metrics and defects for recommendations
    quality_metrics = reviewer_agent.assess_quality_metrics(srs_document)
    defects = reviewer_agent.identify_quality_defects(srs_document)
    
    # Demonstrate improvement recommendations
    demonstrate_improvement_recommendations(reviewer_agent, srs_document, quality_metrics, defects)
    
    # Demonstrate comprehensive review
    demonstrate_comprehensive_review(reviewer_agent, srs_document, requirements, traceability_matrix)
    
    print("\n" + "="*60)
    print("DEMONSTRATION COMPLETED")
    print("="*60)
    print("\nThe ReviewerAgent has successfully demonstrated:")
    print("✓ Consistency validation")
    print("✓ Completeness checking")
    print("✓ Traceability verification")
    print("✓ Quality metrics assessment")
    print("✓ Defect identification")
    print("✓ Improvement recommendations")
    print("✓ Comprehensive review")


if __name__ == "__main__":
    main()