---
title: "Software Engineering Domain Knowledge"
phases: [elicitation, analysis, specification, validation]
tags: [software_engineering, requirements, domain_knowledge, best_practices]
---

# Software Engineering Domain Knowledge

Core concepts, principles, and practices in software engineering relevant to requirements engineering.

## Software Development Lifecycle

Standard phases every software project moves through:

- Requirements Analysis
- System Design
- Implementation
- Testing
- Deployment
- Maintenance

## Requirements Types

### Functional Requirements

Specify what the system should do.

- Describes observable system behaviour
- Defines functions, inputs, and outputs
- Directly traceable to user or business goals

### Non-Functional Requirements

Specify how the system should perform. Key categories:

- **Performance** — response times, throughput, latency
- **Security** — authentication, authorisation, data protection
- **Usability** — learnability, accessibility, user satisfaction
- **Reliability** — uptime, fault tolerance, failover
- **Scalability** — horizontal/vertical growth capacity
- **Maintainability** — ease of change, modularity, documentation

## Stakeholders

### Primary Stakeholders

- End users
- Customers / clients
- Product owners

### Secondary Stakeholders

- Developers
- Testers
- System administrators
- Maintenance teams

## Quality Attributes

| Attribute | Definition |
|---|---|
| Correctness | System performs its intended functions |
| Reliability | System behaves consistently over time |
| Usability | System is easy to learn and operate |
| Efficiency | System uses resources optimally |
| Maintainability | System can be modified with low effort |
| Portability | System runs on different platforms |

## Requirements Engineering Principles

- **Completeness** — all necessary requirements must be identified
- **Consistency** — requirements must not contradict each other
- **Clarity** — requirements must be unambiguous
- **Verifiability** — every requirement must be testable
- **Traceability** — requirements must be traceable to their source

## Software Design Principles

- **Modularity** — divide the system into cohesive, loosely coupled modules
- **Abstraction** — hide implementation details behind well-defined interfaces
- **Encapsulation** — bundle data with the operations that act on it
- **Separation of Concerns** — each module addresses a distinct responsibility

## Best Practices

### Requirements Gathering

- Involve all stakeholders in elicitation
- Use multiple, complementary elicitation techniques
- Validate requirements with stakeholders before proceeding
- Prioritise requirements by business value
- Maintain bidirectional traceability throughout

### Requirements Documentation

- Use clear, precise, and testable language
- Follow standard templates and formats
- Include acceptance criteria for every requirement
- Apply version control to requirements documents
- Schedule and perform regular reviews

### Quality Assurance

- Conduct peer reviews for all artefacts
- Automate testing where feasible
- Track and report test coverage metrics
- Perform regular quality audits
- Enforce coding standards and style guidelines

## Common Architectural Patterns

- Model-View-Controller (MVC)
- Layered Architecture
- Microservices
- Event-Driven Architecture

## Common Design Patterns

- Singleton, Factory, Observer, Strategy, Command

## Tools and Techniques

### Requirements Tools

- Requirements management systems (e.g. Jira, Azure DevOps)
- Modelling tools: UML, BPMN
- Prototyping and wireframing tools
- Collaboration platforms

### Development Tools

- Integrated Development Environments (IDEs)
- Version control systems (e.g. Git)
- Build automation tools
- Testing frameworks
- Continuous integration / continuous delivery platforms

## Key Metrics

### Requirements Metrics

- Requirements volatility (churn rate)
- Traceability coverage
- Validation coverage
- Defect density in requirements

### Quality Metrics

- Code coverage
- Cyclomatic complexity
- Defect density
- Mean time to failure (MTTF)
- Customer satisfaction score