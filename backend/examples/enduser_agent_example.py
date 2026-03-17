#!/usr/bin/env python3
"""
Example usage of EndUserAgent for generating user personas, scenarios, and NFRs.
This demonstrates the complete workflow of the EndUserAgent.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.agent.enduser import EndUserAgent
import json
from datetime import datetime

def demonstrate_enduser_agent():
    """Demonstrate EndUserAgent capabilities with a healthcare system example."""
    
    print("🏥 EndUserAgent Demo: Healthcare Management System")
    print("=" * 60)
    
    # Initialize the EndUserAgent
    agent = EndUserAgent()
    
    # Define the domain and context
    domain = "healthcare"
    context = {
        "business_objectives": [
            "Improve patient care quality",
            "Reduce administrative burden on staff",
            "Ensure HIPAA compliance",
            "Streamline appointment scheduling"
        ],
        "target_users": [
            "doctors", "nurses", "administrators", 
            "patients", "reception_staff"
        ],
        "system_type": "electronic health records and patient management",
        "criticality": "high",
        "regulatory_requirements": ["HIPAA", "FDA", "State medical board"]
    }
    
    print(f"\n📋 Domain: {domain}")
    print(f"🎯 Business Objectives: {', '.join(context['business_objectives'])}")
    
    # Step 1: Create User Personas
    print("\n" + "="*60)
    print("STEP 1: Creating User Personas")
    print("="*60)
    
    personas = agent.create_user_personas(domain, context)
    
    print(f"\n✅ Created {len(personas)} user personas:")
    for i, persona in enumerate(personas, 1):
        print(f"\n{i}. {persona.name} ({persona.role})")
        print(f"   Technical Proficiency: {persona.technical_proficiency}")
        print(f"   Key Goals: {', '.join(persona.goals[:2])}")
        print(f"   Main Pain Points: {', '.join(persona.pain_points[:2])}")
    
    # Step 2: Generate User Scenarios
    print("\n" + "="*60)
    print("STEP 2: Generating User Scenarios")
    print("="*60)
    
    system_context = {
        "features": [
            "patient records management",
            "appointment scheduling",
            "billing and insurance",
            "prescription management",
            "lab results tracking",
            "patient communication"
        ],
        "constraints": [
            "HIPAA compliance required",
            "24/7 system availability",
            "Integration with existing systems",
            "Mobile device support"
        ],
        "performance_requirements": [
            "Sub-2 second response times",
            "Support for 500+ concurrent users"
        ]
    }
    
    scenarios = agent.generate_user_scenarios(personas, system_context)
    
    print(f"\n✅ Generated {len(scenarios)} user scenarios:")
    scenario_summary = {}
    for scenario in scenarios:
        persona_name = next((p.name for p in personas if p.id == scenario.persona_id), "Unknown")
        if persona_name not in scenario_summary:
            scenario_summary[persona_name] = []
        scenario_summary[persona_name].append(scenario)
    
    for persona_name, persona_scenarios in scenario_summary.items():
        print(f"\n👤 {persona_name}:")
        for scenario in persona_scenarios[:2]:  # Show first 2 scenarios per persona
            print(f"   • {scenario.title} ({scenario.frequency}, {scenario.importance} priority)")
            print(f"     Context: {scenario.context}")
    
    # Step 3: Identify Pain Points
    print("\n" + "="*60)
    print("STEP 3: Identifying Pain Points")
    print("="*60)
    
    current_system_info = {
        "legacy_system": "Paper-based records with some digital components",
        "known_issues": [
            "Slow data entry",
            "Difficult to find patient information",
            "No mobile access",
            "Frequent system crashes"
        ],
        "user_complaints": [
            "Too many clicks to complete tasks",
            "System is not intuitive",
            "Poor search functionality"
        ]
    }
    
    pain_points = agent.identify_pain_points(scenarios, current_system_info)
    
    print(f"\n✅ Identified {len(pain_points)} pain points:")
    pain_by_category = {}
    for pain in pain_points:
        if pain.category not in pain_by_category:
            pain_by_category[pain.category] = []
        pain_by_category[pain.category].append(pain)
    
    for category, pains in pain_by_category.items():
        print(f"\n🔴 {category.title()} Issues:")
        for pain in pains[:2]:  # Show first 2 per category
            print(f"   • {pain.title} ({pain.severity} severity)")
            print(f"     Impact: {pain.impact}")
    
    # Step 4: Generate Non-Functional Requirements
    print("\n" + "="*60)
    print("STEP 4: Generating Non-Functional Requirements")
    print("="*60)
    
    system_constraints = {
        "budget": "high",
        "timeline": "medium",
        "team_size": "large",
        "infrastructure": "advanced",
        "compliance_requirements": ["HIPAA", "SOC 2", "FDA 21 CFR Part 11"]
    }
    
    nfrs = agent.define_non_functional_requirements(scenarios, pain_points, system_constraints)
    
    print(f"\n✅ Generated {len(nfrs)} non-functional requirements:")
    nfr_by_category = {}
    for nfr in nfrs:
        if nfr.category not in nfr_by_category:
            nfr_by_category[nfr.category] = []
        nfr_by_category[nfr.category].append(nfr)
    
    for category, category_nfrs in nfr_by_category.items():
        print(f"\n⚡ {category.title()} Requirements:")
        for nfr in category_nfrs:
            # Classify priority using the new method
            priority = agent.classify_nfr_priority(nfr, context)
            print(f"   • {nfr.title} ({priority} priority)")
            print(f"     Rationale: {nfr.rationale}")
            if nfr.measurable_criteria:
                print(f"     Criteria: {nfr.measurable_criteria[0]}")
    
    # Step 5: Advanced Analysis
    print("\n" + "="*60)
    print("STEP 5: Advanced Analysis & Planning")
    print("="*60)
    
    # NFR Coverage Analysis
    coverage = agent.get_nfr_coverage_analysis()
    print(f"\n📊 NFR Coverage Analysis:")
    print(f"   Total NFRs: {coverage['total_nfrs']}")
    print(f"   Categories Covered: {', '.join(coverage['categories_covered'])}")
    if coverage['categories_missing']:
        print(f"   Categories Missing: {', '.join(coverage['categories_missing'])}")
    print(f"   Priority Distribution: {coverage['priority_distribution']}")
    
    # Feasibility Assessment for critical NFRs
    print(f"\n🔍 Feasibility Assessment (Critical NFRs):")
    critical_nfrs = [nfr for nfr in nfrs if agent.classify_nfr_priority(nfr, context) == 'critical']
    
    for nfr in critical_nfrs[:2]:  # Assess first 2 critical NFRs
        assessment = agent.assess_nfr_feasibility(nfr, system_constraints)
        print(f"\n   {nfr.title}:")
        print(f"   • Feasibility Score: {assessment['feasibility_score']:.1f}/1.0")
        print(f"   • Implementation Complexity: {assessment['implementation_complexity']}")
        print(f"   • Estimated Effort: {assessment['estimated_effort']}")
        if assessment['technical_risks']:
            print(f"   • Risks: {', '.join(assessment['technical_risks'])}")
    
    # Implementation Plan
    print(f"\n📋 Implementation Plan:")
    impl_plan = agent.create_nfr_implementation_plan(nfrs, system_constraints)
    print(f"   Total Duration: {impl_plan['estimated_total_duration']}")
    print(f"   Number of Phases: {len(impl_plan['phases'])}")
    
    for phase in impl_plan['phases']:
        print(f"\n   Phase {phase['phase']}: {phase['name']}")
        print(f"   • Duration: {phase['estimated_duration']}")
        print(f"   • NFRs: {len(phase['nfrs'])} requirements")
        print(f"   • Key Deliverables: {', '.join(phase['deliverables'][:2])}")
    
    # Persona Summaries
    print(f"\n👥 Persona Summaries:")
    for persona in personas[:2]:  # Show summary for first 2 personas
        summary = agent.get_persona_summary(persona.id)
        if summary:
            print(f"\n   {summary['persona']['name']}:")
            print(f"   • Related Scenarios: {summary['related_scenarios_count']}")
            print(f"   • Related Pain Points: {summary['related_pain_points_count']}")
            if summary['key_scenarios']:
                print(f"   • Key Scenarios: {', '.join(summary['key_scenarios'])}")
    
    print("\n" + "="*60)
    print("✅ EndUserAgent Demo Completed Successfully!")
    print("="*60)
    
    # Return summary statistics
    return {
        "personas_created": len(personas),
        "scenarios_generated": len(scenarios),
        "pain_points_identified": len(pain_points),
        "nfrs_generated": len(nfrs),
        "implementation_phases": len(impl_plan['phases'])
    }

if __name__ == "__main__":
    try:
        results = demonstrate_enduser_agent()
        
        print(f"\n📈 Summary Statistics:")
        print(f"   • Personas Created: {results['personas_created']}")
        print(f"   • Scenarios Generated: {results['scenarios_generated']}")
        print(f"   • Pain Points Identified: {results['pain_points_identified']}")
        print(f"   • NFRs Generated: {results['nfrs_generated']}")
        print(f"   • Implementation Phases: {results['implementation_phases']}")
        
        print(f"\n🎉 Demo completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)