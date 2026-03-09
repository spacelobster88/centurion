# Centurion: Contributor Invitation Email Template

---

## Subject Line Options

1. **Join me in building Centurion — an open-source AI Agent Orchestration Engine**
2. **Looking for contributors: orchestrate 100+ AI agents with Kubernetes-inspired scheduling**
3. **Open source project invite: Centurion needs experienced devs like you**

---

## Email Body

Subject: [Pick one from above]

---

Hey [Name],

Hope you're doing well! I'm reaching out because I've been working on something I think you'd find interesting — and I'd love your help.

It's called **Centurion** — an open-source AI Agent Orchestration Engine. The short version: it lets you spawn and coordinate 100+ AI agents with Kubernetes-inspired scheduling and a Roman military hierarchy.

### Why this matters

Right now, most agent frameworks work fine with 1-2 agents. But as soon as you need real scale — 50 agents researching, 10 agents coding, 20 agents reviewing, all coordinating across different hardware — everything falls apart. There's no scheduler. No autoscaling. No health checks. You're basically wiring things together by hand.

Centurion treats AI agents the way Kubernetes treats containers. It has a hardware-aware scheduler that places agents on the right hardware (GPU vs CPU, VRAM-aware), autoscales based on workload, and organizes everything in a command hierarchy: Centurion (orchestrator) > Optio (sub-commanders) > Legionary (worker agents).

It supports 5 integration methods — REST API, MCP protocol, Skill interface, A2A (agent-to-agent) protocol, and direct Python library import — so it fits into whatever stack you're running.

### What contributions are welcome

There's a ton of surface area and I'd genuinely value your expertise. Some areas where help would make a big difference:

- **New agent types** — subclass Legionary to create specialized agents (researcher, coder, reviewer, etc.)
- **Tests** — we're pushing toward 80%+ coverage and need help getting there
- **Documentation** — tutorials, API docs, architecture guides
- **Integrations** — new MCP tools, A2A protocol adapters, LangChain/LlamaIndex bridges
- **Frontend dashboard** — a web UI for visualizing the agent hierarchy, scheduling, and metrics
- **Bug reports and feedback** — even just trying it and telling me what's confusing is incredibly helpful

Issues labeled `good first issue` and `help wanted` are ready to go if you want a quick entry point.

### Quick start

```bash
git clone https://github.com/spacelobster88/centurion.git
cd centurion
pip install -e ".[dev]"
pytest
```

That's it. If the tests pass, you're ready to hack.

### The repo

**GitHub:** https://github.com/spacelobster88/centurion

Take a look at the README and the CONTRIBUTING.md for the full picture. If anything is unclear or you have ideas for the project direction, I'm all ears.

No pressure at all — even a star on the repo or sharing it with someone who might be interested would mean a lot. But if you want to dive in and build something, I'd be thrilled to have you on board.

Let me know what you think!

Cheers,
Eddie

P.S. If you know anyone else who might be into this, feel free to forward this along. The more Legionaries, the stronger the army.
