# Contributing to iReDev

Thank you for your interest in contributing to iReDev! This document provides guidelines and instructions for contributing to the project.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/yourusername/iReDev.git
   cd iReDev
   ```
3. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

1. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the project**:
   - Copy `config/agent_config.yaml.example` to `config/agent_config.yaml`
   - Add your LLM API keys (never commit these!)

## Code Style

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Write docstrings for all public functions and classes
- Keep functions focused and single-purpose

## Making Changes

### Before You Start

- Check existing issues and pull requests to avoid duplicate work
- For major changes, open an issue first to discuss the approach

### Commit Messages

- Use clear, descriptive commit messages
- Start with a verb in imperative mood (e.g., "Add", "Fix", "Update")
- Reference issue numbers when applicable: `Fix #123: Description`

### Pull Request Process

1. **Ensure your code works**:
   - Test your changes thoroughly
   - Run any existing tests
   - Check for linting errors

2. **Update documentation**:
   - Update README.md if you've changed installation or usage
   - Add docstrings for new functions/classes
   - Update examples if you've changed APIs

3. **Submit your PR**:
   - Push your branch to your fork
   - Open a Pull Request on GitHub
   - Fill out the PR template with:
     - Description of changes
     - Related issues (if any)
     - Testing performed

## Areas for Contribution

We welcome contributions in the following areas:

- **New Agents**: Adding specialized agents for different requirement engineering tasks
- **Knowledge Base**: Expanding domain knowledge, methodologies, and templates
- **LLM Providers**: Adding support for new LLM providers
- **Documentation**: Improving documentation, examples, and tutorials
- **Testing**: Adding unit tests, integration tests, and test coverage
- **Bug Fixes**: Fixing issues and improving stability
- **Performance**: Optimizing code and reducing API costs

## Questions?

If you have questions or need help, please:
- Open an issue with the `question` label
- Check existing documentation and examples
- Review closed issues and PRs for similar questions

Thank you for contributing to iReDev! 🎉

