# Contributing to Centurion

Thank you for your interest in contributing to Centurion! This document provides guidelines and instructions for contributing.

## Getting Started

### Prerequisites

- Python 3.12 or later
- Git
- A Claude API key (optional, for `claude_api` agent type testing)

### Setup

```bash
# Clone the repository
git clone https://github.com/spacelobster88/centurion.git
cd centurion

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install in development mode with all dependencies
pip install -e ".[dev]"

# Run tests to verify setup
pytest tests/ -v
```

## Development Workflow

1. **Create a branch** for your work:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the code style guidelines below.

3. **Run tests** to ensure nothing is broken:
   ```bash
   pytest tests/ -v --cov=centurion --cov-report=term-missing
   ```

4. **Submit a pull request** with a clear description of your changes.

## Code Style

- All code comments, docstrings, and documentation must be in **English**
- Follow PEP 8 conventions
- Use type hints for all function signatures
- Write descriptive docstrings for public classes and methods
- Keep functions focused and concise

## Project Structure

```
centurion/
├── agent_types/       # Agent type implementations (claude_cli, claude_api, shell)
├── api/               # FastAPI REST API (router, schemas, websocket)
├── a2a/               # A2A protocol adapter (agent card, router)
├── core/              # Core engine (century, legion, legionary, scheduler, events)
├── db/                # Database persistence (schema, repository)
├── hardware/          # Hardware probing and throttling
├── mcp/               # MCP server tools
├── __init__.py        # Public API exports
├── __main__.py        # CLI entrypoint (quickstart, up, recommend)
├── config.py          # Configuration with env var support
├── logging.py         # Structured logging setup
└── skill.py           # Claude Code skill definition
```

## Areas for Contribution

### New Agent Types
Add new agent types by subclassing `AgentType` in `centurion/agent_types/`:
- OpenAI API agents
- Local LLM agents (Ollama, llama.cpp)
- Specialized tool-use agents

### Testing
- Increase test coverage
- Add integration tests for the A2A protocol
- Add stress tests for broadcast at scale

### Documentation
- Tutorials and guides
- Architecture deep-dives
- Deployment guides (Docker, cloud)

### Features
- Dashboard UI for fleet monitoring
- Persistent task history and analytics
- Multi-node distributed scheduling
- Agent communication channels (inter-agent messaging)

## Commit Messages

Write clear, descriptive commit messages:
- `feat: add OpenAI agent type`
- `fix: resolve race condition in autoscaler`
- `docs: add deployment guide`
- `test: add broadcast integration tests`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
