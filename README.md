# iReDev - Intelligent Requirements Development Framework

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**iReDev** (Intelligent Requirements Development) is an automated requirement engineering system that transforms coarse-grained, unstructured natural language requirement descriptions into high-quality user requirement lists, requirement models, and ISO/IEC/IEEE 29148-compliant Software Requirements Specifications (SRS) through multi-agent collaboration powered by Large Language Models (LLMs).

## 🌟 Key Features

### 🤖 Multi-Agent Collaboration
- **6 Specialized Agents**: Interviewer, End User, Deployer, Analyst, Archivist, and Reviewer
- **Clear Role Division**: Each agent simulates a different professional role in real requirement engineering
- **Event-Driven Architecture**: Agents collaborate through a shared artifact pool rather than direct dialogue

### 🧠 Knowledge-Driven Approach
- **5 Knowledge Types**: Domain knowledge, methodologies, standards, templates, and strategies
- **Explicit Knowledge Injection**: Agents apply expert knowledge explicitly rather than relying on implicit model knowledge
- **Reusable Knowledge Base**: Modular knowledge management system

### 🔄 Chain-of-Thought Reasoning
- **CoT Engine**: Multi-step reasoning process instead of direct results
- **Explainability**: Provides intermediate derivation logic and reasoning steps
- **Reasoning Templates**: Specialized reasoning templates for different task types

### 📦 Shared Artifact Pool
- **Centralized State Storage**: Unified management of all intermediate and final requirement artifacts
- **Version Control**: Complete version history and change tracking
- **Event-Triggered**: Artifact changes automatically trigger relevant agents

### 👤 Human-in-the-Loop
- **Critical Review Points**: Pauses for human review after generating user requirement lists, requirement models, and SRS documents
- **Feedback-Driven Revision**: Human feedback is written back to the artifact pool, driving agents to re-analyze and revise
- **Iterative Improvement**: Supports multiple rounds of iteration and revision

### 📋 Standards Compliance
- **ISO/IEC/IEEE 29148**: Compliant with international requirement engineering standards
- **IEEE 830**: Supports IEEE 830 SRS document structure
- **Automatic Compliance Checking**: Automatically validates document compliance with standard requirements

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- An API key for one of the supported LLM providers:
  - OpenAI (GPT-4, GPT-4 Turbo, etc.)
  - Anthropic Claude (Claude 3.5 Sonnet, Claude 3 Opus, etc.)
  - Google Gemini (Gemini 1.5 Pro, etc.)
  - HuggingFace (for local models)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/iReDev.git
cd iReDev
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure LLM**

Copy the example configuration file and add your API key:

```bash
cp config/agent_config.yaml.example config/agent_config.yaml
```

Then edit `config/agent_config.yaml`:

```yaml
llm:
  type: "openai"  # or "claude", "gemini", "huggingface"
  model: "gpt-4o"
  api_key: "your-api-key-here"
  temperature: 0.1
  max_output_tokens: 4096
```

**⚠️ Important**: Never commit your `config/agent_config.yaml` file with API keys. It's already in `.gitignore`.

### Running Examples

**Complete workflow example:**
```bash
python examples/complete_workflow_example.py
```

**Individual agent examples:**
```bash
# Analyst agent
python examples/analyst_agent_example.py

# End User agent
python examples/enduser_agent_example.py

# Deployer agent
python examples/deployer_agent_example.py

# Archivist agent
python examples/archivist_agent_example.py

# Reviewer agent
python examples/reviewer_agent_example.py

# Orchestrator example
python examples/orchestrator_example.py
```

### Using the Command Line Interface

```bash
# Start a new requirement development process
python run_iReDev.py start --project "My Project" --domain web

# View process status
python run_iReDev.py status --all

# List pending reviews
python run_iReDev.py review --list

# Submit review feedback
python run_iReDev.py review --submit <review_id> --feedback "Your feedback here"
```

## 🏗️ System Architecture

```
Initial Requirement Description (coarse-grained, unstructured)
    ↓
[Interviewer Agent] → Interview Records
    ↓
[End User Agent] → User Personas, Scenarios, Pain Points
    ↓
[Deployer Agent] → Deployment Constraints, Security Requirements
    ↓
[Analyst Agent] → System Requirements, Requirement Models
    ↓
[Human Review] ⏸ → Feedback
    ↓
[Archivist Agent] → SRS Document
    ↓
[Human Review] ⏸ → Feedback
    ↓
[Reviewer Agent] → Quality Validation
    ↓
Final SRS Document (ISO/IEC/IEEE 29148 compliant)
```

## 📚 Core Components

### Agents

- **InterviewerAgent**: Conducts requirement interviews using 5W1H and Socratic questioning
- **EndUserAgent**: Creates user personas, scenarios, and pain point analysis
- **DeployerAgent**: Analyzes deployment constraints and security requirements
- **AnalystAgent**: Performs requirement analysis and modeling
- **ArchivistAgent**: Generates standard SRS documents
- **ReviewerAgent**: Performs quality validation and review

### Core Systems

- **RequirementOrchestrator**: Process orchestrator managing the entire workflow
- **ArtifactPool**: Shared artifact pool for centralized state management
- **EventBus**: Event bus for asynchronous agent communication
- **KnowledgeManager**: Knowledge management system with dynamic loading
- **HumanReviewManager**: Human-in-the-loop review management
- **ChainOfThoughtEngine**: Multi-step reasoning engine

## 🛠️ Technology Stack

- **Python 3.8+**: Core programming language
- **Asyncio**: Asynchronous programming for agent coordination
- **PyYAML**: Configuration management
- **Flask**: Web interface (optional)
- **Multiple LLM Providers**: OpenAI, Anthropic, Google, HuggingFace

## 📖 Documentation

- [中文文档 (Chinese Documentation)](README_CN.md)
- [Contributing Guide](CONTRIBUTING.md): Guidelines for contributing to the project
- [Examples](examples/): Comprehensive usage examples
- [Configuration Guide](config/): Configuration file documentation

## 🔧 Configuration

The system uses YAML configuration files:

- `config/agent_config.yaml`: LLM provider and agent settings
- `config/iredev_config.yaml`: System-wide configuration

See the configuration files for detailed options and examples.

## 💡 Use Cases

- **Software Requirements Engineering**: Automate the creation of SRS documents from initial requirements
- **Requirements Analysis**: Transform unstructured requirements into structured models
- **Compliance Documentation**: Generate standards-compliant requirement documents
- **Requirements Review**: Automated quality assurance and consistency checking

## 📁 Project Structure

```
iReDev/
├── src/                    # Source code
│   ├── agent/             # Agent implementations
│   │   ├── llm/          # LLM provider integrations
│   │   └── tool/         # Agent tools
│   ├── artifact/         # Artifact pool and storage
│   ├── config/           # Configuration management
│   ├── knowledge/        # Knowledge base system
│   ├── orchestrator/     # Process orchestration
│   ├── visualizer/       # Status visualization
│   └── web/              # Web interface
├── config/               # Configuration files
│   ├── agent_config.yaml # LLM and agent settings
│   └── iredev_config.yaml # System configuration
├── knowledge/            # Knowledge base
│   ├── domains/          # Domain knowledge
│   ├── methodologies/    # Methodologies
│   ├── standards/        # Standards definitions
│   ├── strategies/       # Strategies
│   └── templates/        # Document templates
├── prompts/              # Agent prompts and profiles
├── examples/             # Usage examples
├── run_iReDev.py        # CLI interface
└── requirements.txt     # Python dependencies
```

## 🤝 Contributing

Contributions are welcome! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

For major changes, please open an issue first to discuss what you would like to change.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with modern LLM technologies
- Inspired by ISO/IEC/IEEE 29148 and IEEE 830 standards
- Designed following software engineering best practices

## 📧 Contact

For questions, issues, or suggestions, please open an issue on GitHub.

---

**Note**: This project requires API keys for LLM providers. Make sure to keep your API keys secure and never commit them to version control.
