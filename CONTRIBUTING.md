# Contributing to Centurion

## 1. Welcome

Welcome to Centurion! We're building the infrastructure layer for AI agent orchestration.

Whether you're fixing a bug, adding a new agent type, or improving documentation, we appreciate your contribution. This guide will help you get set up and submitting pull requests quickly.

- **GitHub repo**: [github.com/spacelobster88/centurion](https://github.com/spacelobster88/centurion)
- **Issues**: [github.com/spacelobster88/centurion/issues](https://github.com/spacelobster88/centurion/issues)

## 2. Getting Started

### Prerequisites

- Python 3.12+
- Git

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
```

### Verify your setup

```bash
centurion --help
pytest tests/ -v
```

Both commands should complete without errors.

## 3. Development Workflow

1. **Fork** the repo on GitHub.
2. **Create a branch** for your work:
   ```bash
   git checkout -b feature/your-feature
   ```
3. **Make your changes** following the code style guidelines below.
4. **Run linting**:
   ```bash
   ruff check centurion/ tests/
   ruff format centurion/ tests/
   ```
5. **Run type checking**:
   ```bash
   mypy centurion/
   ```
6. **Run tests**:
   ```bash
   pytest tests/ -v --cov=centurion
   ```
7. **Submit a pull request** using the PR template.

## 4. Code Style

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **ruff** | Linting | Line length 120, Python 3.12 target |
| **ruff format** | Formatting | Consistent style across the codebase |
| **mypy** | Type checking | Strict mode for `centurion/` |

Additional conventions:

- Follow PEP 8.
- Use type hints for all function signatures.
- Write all comments, docstrings, and documentation in English.
- Write descriptive docstrings for public classes and methods.
- Keep functions focused and concise.

Pre-commit hooks are available to catch issues before they reach CI:

```bash
pre-commit install
```

## 5. Testing

- **Framework**: pytest + pytest-asyncio
- **Run the full suite**:
  ```bash
  pytest tests/ -v --cov=centurion --cov-report=term-missing
  ```
- **Coverage requirement**: 90% on new lines, enforced by CI via diff-cover.
- Add tests for every new feature or bug fix.
- Use the `MockAgentType` fixture from `conftest.py` for agent tests.

## 6. Pull Request Guidelines

- **One thing per PR** — don't mix unrelated concerns.
- **Use the PR template** (summary, change type, scope, security impact, evidence).
- **Describe the what AND why** — reviewers need context, not just a diff.
- **Include evidence** — test output, screenshots, or logs that show your change works.
- **Keep PRs small and focused** — smaller PRs get reviewed faster and merged sooner.
- **Respond to review comments promptly** — we aim for short feedback cycles.

## 7. AI-Assisted PRs Welcome! 🤖

Built your contribution with Claude, Copilot, or another AI tool? That's great — just be transparent about it.

Include the following in your PR:

- **Mark it as AI-assisted** in the PR description.
- **Note the testing level**: untested, lightly tested, or fully tested.
- **Include prompts or session logs** if possible — they help reviewers understand the intent.
- **Confirm you understand what the code does** — you're still the author.

AI-assisted PRs are first-class citizens. We want transparency so reviewers know what to look for, not to discourage the use of AI tools.

## 8. Security

- **Prompt-related changes get extra scrutiny** — an automated static scan runs on every PR.
- **CODEOWNERS enforces review** for sensitive files: `skill.py`, `claude_api.py`, `config.py`, and `.github/`.
- **Never commit secrets, API keys, or tokens.** Use environment variables and `.env` files (which are gitignored).
- **Report vulnerabilities privately** via [GitHub Security Advisories](https://github.com/spacelobster88/centurion/security/advisories).

## 9. Areas for Contribution

- **New Agent Types**: Subclass `AgentType` in `centurion/agent_types/` — e.g., OpenAI, Ollama, llama.cpp.
- **Hardware Support**: Extend hardware detection for Linux, Windows, and cloud VMs.
- **Integrations**: New MCP tools, A2A protocol extensions.
- **Documentation**: Guides, tutorials, examples.
- **Testing**: More edge cases, integration tests, load testing.

## 10. Naming Convention

Centurion uses Roman military terminology throughout the codebase:

| Term | Meaning | K8s Equivalent |
|------|---------|----------------|
| **Centurion** | Engine / control plane | Control plane |
| **Legion** | Deployment group | Namespace |
| **Century** | Agent squad | ReplicaSet |
| **Legionary** | Individual agent | Pod |
| **Optio** | Auto-scaler | HPA |
| **Aquilifer** | Event bus | — |

When writing code or documentation, use these terms consistently to keep the project vocabulary clear.

## 11. Maintainer

- **Eddie** ([@spacelobster88](https://github.com/spacelobster88)) — project creator and maintainer.

---

By contributing, you agree that your contributions will be licensed under the MIT License.
