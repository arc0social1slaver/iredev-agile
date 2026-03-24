#!/usr/bin/env python3
"""
Example usage of DeployerAgent for deployment constraint analysis.
Demonstrates how to use the DeployerAgent to analyze deployment requirements,
identify security needs, and define performance criteria.
"""

import sys
import os
import asyncio
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.agent.deployer import DeployerAgent
from src.knowledge.knowledge_manager import KnowledgeManager
from src.artifact.events import EventBus


async def main():
    """Example usage of DeployerAgent."""
    print("DeployerAgent Example Usage")
    print("=" * 40)
    
    # Initialize components
    from src.config.config_manager import get_config_manager
    config_manager = get_config_manager()
    knowledge_config = {
        "base_path": os.path.join(os.path.dirname(__file__), '..', 'knowledge'),
        "cache_enabled": True,
        "auto_reload": True
    }
    knowledge_manager = KnowledgeManager(knowledge_config)
    event_bus = EventBus()
    
    # Create DeployerAgent
    deployer = DeployerAgent(
        knowledge_manager=knowledge_manager,
        event_bus=event_bus
    )
    
    # Start session
    session_id = f"example_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    deployer.start_session(session_id)
    
    print(f"Started session: {session_id}")
    print(f"Agent: {deployer.name}")
    print()
    
    # Example 1: Analyze deployment constraints for cloud environment
    print("1. Analyzing Deployment Constraints")
    print("-" * 35)
    
    cloud_context = {
        "system_type": "microservices_application",
        "expected_load": {
            "concurrent_users": 50000,
            "requests_per_second": 2000,
            "data_volume_gb": 500
        },
        "availability_requirements": "99.99%",
        "geographic_regions": ["North America", "Europe", "Asia"],
        "compliance_needs": ["GDPR", "SOC2"],
        "integration_points": [
            "payment_gateway",
            "email_service", 
            "analytics_platform",
            "third_party_apis"
        ]
    }
    
    constraints = deployer.analyze_deployment_constraints("cloud", cloud_context)
    
    print(f"Identified {len(constraints)} deployment constraints:")
    for constraint in constraints:
        print(f"  • {constraint.title}")
        print(f"    Category: {constraint.category}")
        print(f"    Priority: {constraint.priority}")
        print(f"    Impact: {constraint.impact}")
        print()
    
    # Example 2: Identify security requirements
    print("2. Identifying Security Requirements")
    print("-" * 35)
    
    threat_model = {
        "system_type": "financial_application",
        "assets": [
            "customer_financial_data",
            "transaction_records",
            "authentication_credentials",
            "business_logic",
            "audit_logs"
        ],
        "threat_actors": [
            "external_cybercriminals",
            "nation_state_actors",
            "malicious_insiders",
            "competitors"
        ],
        "attack_vectors": [
            "web_application_vulnerabilities",
            "api_endpoints",
            "database_access",
            "social_engineering",
            "supply_chain_attacks"
        ],
        "existing_controls": [
            "firewall",
            "basic_authentication",
            "ssl_encryption"
        ]
    }
    
    compliance_context = {
        "industry": "financial_services",
        "regulations": ["PCI-DSS", "SOX", "GDPR"],
        "data_classification": "highly_sensitive",
        "geographic_scope": "global"
    }
    
    security_reqs = deployer.identify_security_requirements(
        "financial_application", 
        threat_model, 
        compliance_context
    )
    
    print(f"Identified {len(security_reqs)} security requirements:")
    for req in security_reqs:
        print(f"  • {req.title}")
        print(f"    Category: {req.category}")
        print(f"    Security Level: {req.security_level}")
        print(f"    Risk Level: {req.risk_level}")
        print()
    
    # Example 3: Assess compliance requirements
    print("3. Assessing Compliance Requirements")
    print("-" * 35)
    
    compliance_reqs = deployer.assess_compliance_requirements(
        domain="healthcare",
        region="US",
        data_types=["PHI", "PII", "medical_records", "billing_information"]
    )
    
    print(f"Identified {len(compliance_reqs)} compliance requirements:")
    for req in compliance_reqs:
        print(f"  • {req.title}")
        print(f"    Standard: {req.standard_name}")
        print(f"    Requirement ID: {req.requirement_id}")
        print(f"    Level: {req.compliance_level}")
        print()
    
    # Example 4: Define performance criteria
    print("4. Defining Performance Criteria")
    print("-" * 35)
    
    usage_patterns = [
        {
            "name": "business_hours_peak",
            "description": "Peak usage during business hours",
            "concurrent_users": 10000,
            "requests_per_second": 1500,
            "data_processing_volume": "high",
            "duration_hours": 8,
            "frequency": "daily"
        },
        {
            "name": "off_hours_maintenance",
            "description": "Maintenance window with reduced load",
            "concurrent_users": 100,
            "requests_per_second": 50,
            "data_processing_volume": "low",
            "duration_hours": 4,
            "frequency": "daily"
        },
        {
            "name": "monthly_reporting",
            "description": "Monthly batch processing for reports",
            "concurrent_users": 50,
            "requests_per_second": 10,
            "data_processing_volume": "very_high",
            "duration_hours": 12,
            "frequency": "monthly"
        }
    ]
    
    system_architecture = {
        "architecture_pattern": "microservices",
        "deployment_model": "containerized_cloud",
        "database_architecture": "distributed_with_caching",
        "load_balancing": "intelligent_routing",
        "auto_scaling": "enabled",
        "caching_layers": ["application", "database", "cdn"],
        "monitoring": "comprehensive"
    }
    
    business_requirements = {
        "user_experience": {
            "page_load_time": "< 2 seconds",
            "api_response_time": "< 500ms",
            "search_response_time": "< 1 second"
        },
        "availability": {
            "uptime_sla": "99.95%",
            "planned_downtime": "< 4 hours/month",
            "recovery_time": "< 15 minutes"
        },
        "scalability": {
            "user_growth": "100% annually",
            "data_growth": "200% annually",
            "geographic_expansion": "3 new regions/year"
        }
    }
    
    performance_criteria = deployer.define_performance_criteria(
        usage_patterns,
        system_architecture,
        business_requirements
    )
    
    print(f"Defined {len(performance_criteria)} performance criteria:")
    for criteria in performance_criteria:
        print(f"  • {criteria.metric_name}")
        print(f"    Category: {criteria.category}")
        print(f"    Target: {criteria.target_value} {criteria.measurement_unit}")
        print(f"    Priority: {criteria.priority}")
        print()
    
    # Example 5: Generate comprehensive deployment summary
    print("5. Deployment Analysis Summary")
    print("-" * 35)
    
    summary = deployer.get_deployment_summary()
    
    print("Deployment Analysis Results:")
    print(f"  • Deployment Constraints: {summary['deployment_constraints']['count']}")
    print(f"    - Categories: {', '.join(summary['deployment_constraints']['categories'])}")
    print(f"    - Mandatory: {summary['deployment_constraints']['mandatory_count']}")
    print()
    
    print(f"  • Security Requirements: {summary['security_requirements']['count']}")
    print(f"    - Categories: {', '.join(summary['security_requirements']['categories'])}")
    print(f"    - High Risk: {summary['security_requirements']['high_risk_count']}")
    print()
    
    print(f"  • Compliance Requirements: {summary['compliance_requirements']['count']}")
    print(f"    - Standards: {', '.join(summary['compliance_requirements']['standards'])}")
    print(f"    - Mandatory: {summary['compliance_requirements']['mandatory_count']}")
    print()
    
    print(f"  • Performance Criteria: {summary['performance_criteria']['count']}")
    print(f"    - Categories: {', '.join(summary['performance_criteria']['categories'])}")
    print(f"    - Critical: {summary['performance_criteria']['critical_count']}")
    print()
    
    total_requirements = (
        summary['deployment_constraints']['count'] +
        summary['security_requirements']['count'] +
        summary['compliance_requirements']['count'] +
        summary['performance_criteria']['count']
    )
    
    print(f"Total deployment-related requirements: {total_requirements}")
    print()
    print("✓ DeployerAgent analysis completed successfully!")
    print("The agent has comprehensively analyzed deployment needs and generated")
    print("actionable requirements for system deployment and operation.")


if __name__ == "__main__":
    asyncio.run(main())