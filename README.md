# Centurion

**Spawn and command an army of AI agents with Roman military precision.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-382%20passing-brightgreen.svg)]()
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-19-purple.svg)]()
[![A2A Protocol](https://img.shields.io/badge/A2A-compatible-orange.svg)](https://google.github.io/A2A/)
[![OpenClaw Compatible](https://img.shields.io/badge/OpenClaw-compatible-red.svg)]()
[![Claude Code](https://img.shields.io/badge/Claude%20Code-native-blueviolet.svg)]()
[![Docs](https://img.shields.io/badge/docs-website-blue.svg)](https://spacelobster88.github.io/centurion/)

---

## Where Centurion Fits

AI coding agents operate at three distinct layers. Understanding this hierarchy is key to choosing the right tool — and knowing when you need Centurion.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Layer 1: Raw Agentic Loop (built-in to Claude Code)                 │
│                                                                      │
│  The inner loop. think → tool → observe → repeat.                    │
│  One agent works on one task sequentially.                           │
│  ✦ Scope: single file edit, bug fix, quick question                  │
│  ✦ No parallelism — one tool call at a time                          │
│  ✦ No persistent state across sessions                               │
│  ✦ This is what you get out of the box with Claude Code.             │
├──────────────────────────────────────────────────────────────────────┤
│  Layer 2: Claude Code Subagent Mode                                  │
│                                                                      │
│  Spawns background agents via the Agent tool. Multiple tasks run     │
│  concurrently, but with zero resource awareness.                     │
│  ✦ Scope: parallel subtasks within one session                       │
│  ✦ Unlimited spawning — no memory or CPU checks                      │
│  ✦ No scheduling, no queuing, no backpressure                        │
│  ✦ Can OOM-kill the system (120 GB leaks documented)                 │
│  ✦ maxParallelAgents requested but closed NOT_PLANNED (#15487)       │
├──────────────────────────────────────────────────────────────────────┤
│  Layer 3: Centurion + Harness Loop                    ◀── THIS REPO  │
│                                                                      │
│  The managed layer. Centurion provides fleet-level resource mgmt.    │
│  Harness Loop provides project-level task orchestration.             │
│  Together they enable safe, structured parallel execution.           │
│  ✦ Scope: entire machine — multiple projects simultaneously          │
│  ✦ Hardware-aware scheduling prevents OOM (K8s-style admission)      │
│  ✦ DAG-based task decomposition with phase progression               │
│  ✦ Real-time broadcasting + event streaming (Aquilifer)              │
│  ✦ Auto-scaling (Optio) adjusts fleet size based on resources        │
│  ✦ pip install centurion installs both Centurion + Harness Loop      │
└──────────────────────────────────────────────────────────────────────┘
```

| | Raw Agentic Loop | Claude Code Subagents | Centurion + Harness Loop |
|---|---|---|---|
| **Scope** | Single task | Parallel subtasks | **Multiple projects / fleets** |
| **Parallelism** | 1 (sequential) | Unlimited (dangerous) | **100+ agents, managed** |
| **Resource awareness** | None | None | **RAM/CPU probing, admission control** |
| **Memory safety** | N/A | OOM risk ([#4953](https://github.com/anthropics/claude-code/issues/4953)) | **Pressure detection + backpressure** |
| **Scheduling** | None | None | **K8s-style, hardware-aware** |
| **Task decomposition** | Manual | Manual | **Automatic DAG with phases** |
| **State persistence** | In-memory only | None | **`.harness/` + SQLite** |
| **Cross-project coordination** | No | No | **Yes** |
| **Auto-scaling** | No | No | **Yes (Optio)** |
| **Broadcasting** | No | No | **Yes (all/legion/century)** |
| **When to use** | Quick fixes | Simple parallel tasks | **Structured projects at scale** |

> **Centurion and Harness Loop ship together.** `pip install centurion` installs both. Harness Loop handles project-level task orchestration (decompose → schedule → execute → review), while Centurion handles fleet-level resource management (how many agents, on what hardware, with what limits). Together they solve the problem that Claude Code subagents create: unmanaged parallelism that crashes your machine.

> **Getting started?** Use [Auspex](https://github.com/spacelobster88/auspex) to set up the full stack (Centurion + Harness Loop + Claude gateway) on a fresh Mac in one command.

---

## Overview

Centurion is an AI agent orchestration engine that manages fleets of AI agents at scale. While most frameworks stop at 1-2 agents, Centurion scales to **100+ concurrent agents** with hardware-aware scheduling, real-time broadcasting, and five integration methods.

```
                        +-----------------------+
                        |      CENTURION        |
                        |    Control Plane      |
                        +----------+------------+
                                   |
            +----------------------+----------------------+
            |                      |                      |
   +--------v--------+   +--------v--------+   +---------v--------+
   |    Scheduler     |   |   Broadcaster   |   |    EventBus      |
   |  (K8s-inspired   |   |  (all/legion/   |   |   (Aquilifer)    |
   |  admission ctrl) |   |  century scope) |   |  WebSocket pub-  |
   +--------+---------+   +--------+--------+   |  sub events      |
            |                      |             +---------+--------+
            +----------------------+                       |
                        |                                  |
       +----------------+----------------+                 |
       |                                 |                 |
+------v-----------+          +----------v--------+        |
|  Legion "alpha"  |          |  Legion "beta"    |        |
|  (Research Ops)  |          |  (Build Ops)      |        |
+------+-----------+          +----------+--------+        |
       |                                 |                 |
  +----+--------+                   +----+----+            |
  |             |                   |         |            |
+-v------+ +---v-----+        +----v---+ +---v-----+      |
|Century | |Century  |        |Century | |Century  |      |
|claude  | |claude   |        |shell   | |claude   |      |
|_cli x5 | |_api x3  |        |  x10   | |_api x8  |      |
+---+----+ +---+-----+        +---+----+ +---+-----+      |
    |          |                   |          |             |
  L L L L L  L L L             L L L L..  L L L L..        |
  | | | | |  | | |             | | | |    | | | |          |
  v v v v v  v v v             v v v v    v v v v          |
  Legionaries (individual agent instances)    <-- events --+
```

### Why Centurion?

**Claude Code has zero resource management.** It has no RAM awareness, no parallel agent limits, and no memory pressure detection. Spawning 20+ subagents on a constrained machine can OOM-kill the entire system ([#4953](https://github.com/anthropics/claude-code/issues/4953), [#21403](https://github.com/anthropics/claude-code/issues/21403), [#25926](https://github.com/anthropics/claude-code/issues/25926)). A community request for a `maxParallelAgents` setting ([#15487](https://github.com/anthropics/claude-code/issues/15487)) was **closed NOT_PLANNED** by Anthropic -- they view resource scheduling as outside their application boundary.

Centurion fills this permanent gap. It operates at the **infrastructure layer** (OS, RAM, CPU, process management), not the model layer. It probes your hardware, enforces admission control before every agent spawn, detects memory pressure in real time, and scales fleets up or down automatically. No other tool in the ecosystem does this.

| Feature | Raw Agentic Loop | Claude Code Subagents | Centurion |
|---------|-------------------|----------------------|-----------|
| Parallel agents | 1 | Unlimited (unmanaged) | **100+ (managed)** |
| Memory pressure detection | :x: | :x: | :white_check_mark: |
| Hardware-aware scheduling | :x: | :x: | :white_check_mark: |
| Admission control (K8s-style) | :x: | :x: | :white_check_mark: |
| Auto-scaling | :x: | :x: | :white_check_mark: (Optio) |
| Task DAG orchestration | :x: | :x: | :white_check_mark: (Harness Loop) |
| Cross-session coordination | :x: | :x: | :white_check_mark: |
| Circuit breaker / fault tolerance | :x: | :x: | :white_check_mark: |
| Real-time event streaming | :x: | :x: | :white_check_mark: |
| Fleet broadcasting | :x: | :x: | :white_check_mark: |
| MCP server integration | N/A | :x: | :white_check_mark: |
| REST API | :x: | :x: | :white_check_mark: (21 endpoints) |
| A2A protocol (Google) | :x: | :x: | :white_check_mark: |
| Model-independent | :x: | :x: | :white_check_mark: |

> **The raw agentic loop** is fine for single tasks. **Claude Code subagents** add parallelism but with zero safety — no resource checks, no limits, no scheduling. Anthropic closed the `maxParallelAgents` feature request as [NOT_PLANNED](https://github.com/anthropics/claude-code/issues/15487). **Centurion** fills this permanent infrastructure gap. It is model-independent: the same scheduler works for Claude, GPT, Gemini, or shell scripts.

## Concepts

| Roman Term    | Centurion Concept           | Description                                      |
|---------------|-----------------------------|--------------------------------------------------|
| Centurion     | Engine                      | The top-level orchestrator and control plane      |
| Legion        | Deployment group            | Collection of centuries with a shared quota       |
| Century       | Agent squad                 | Group of same-type agents with a shared task queue|
| Legionary     | Individual agent            | A single agent instance (equivalent to a K8s Pod) |
| Optio         | Autoscaler                  | Per-century autoscaling loop                      |
| Praetorian    | Priority task               | High-priority task (lower priority number = first)|
| Aquilifer     | Event bus                   | Real-time pub-sub event system via WebSocket      |

## One-Click Quickstart

The fastest way to get Centurion running. Installing Centurion automatically installs [Harness Loop](https://github.com/spacelobster88/harness-loop) as a bundled Claude Code skill for project-level task orchestration.

```bash
# Install (includes Harness Loop)
pip install centurion

# One-click launch (probes hardware, auto-configures, starts server)
centurion quickstart

# Preview the recommendation without starting
centurion quickstart --dry-run

# Choose a specific agent type
centurion quickstart --agent-type claude_api

# Just see what your hardware can handle
centurion recommend
centurion recommend --json
```

Example output:

```
============================================================
  HARDWARE SUMMARY
------------------------------------------------------------
  Platform:            Darwin
  CPU cores:           10
  RAM total:           32,768 MB
  RAM available:       18,432 MB
============================================================

============================================================
  AGENT CAPACITY BY TYPE
------------------------------------------------------------
  Type           Max   CPU/agent   RAM/agent
  claude_cli      20      500 m      250 MB  <--
  claude_api     120      100 m       50 MB
  shell           60      200 m       50 MB
============================================================

============================================================
  RECOMMENDED CONFIGURATION
------------------------------------------------------------
  Agent type:          claude_cli
  Max agents:          20
  Min agents:          3
  Legion:              default
  Century:             auto
------------------------------------------------------------
  >> Ample resources (10 CPUs, 18432 MB RAM).
  >> Recommend up to 20 claude_cli agents concurrently.
============================================================
```

## Programmatic Usage

Use Centurion as a library in ten lines:

```python
import asyncio
from centurion import Centurion, CenturyConfig

async def main():
    engine = Centurion()
    legion = await engine.raise_legion("research", name="Research Team")
    century = await legion.add_century(
        None,
        CenturyConfig(agent_type_name="claude_cli", min_legionaries=3),
        engine.registry, engine.scheduler, engine.event_bus,
    )
    futures = [await century.submit_task(p) for p in ["Summarize X", "Analyze Y", "Compare Z"]]
    results = await asyncio.gather(*futures)
    for r in results:
        print(r.output)
    await engine.shutdown()

asyncio.run(main())
```

## Three Deployment Modes

### Standalone Server

```bash
centurion up
# or: python -m centurion --host 0.0.0.0 --port 8100
```

### Embedded (FastAPI Router)

```python
from fastapi import FastAPI
from centurion.api import router as centurion_router
from centurion.a2a.router import a2a_router

app = FastAPI()
app.include_router(centurion_router, prefix="/centurion")
app.include_router(a2a_router)  # A2A protocol support
```

### Library (Programmatic)

Import the engine directly in Python code. See the Programmatic Usage example above.

---

## Integration Guide

Centurion supports **five integration methods**. Pick the one that fits your setup.

### 1. REST API

The full-featured HTTP interface. Start the server and call endpoints directly:

```bash
# Start server
centurion quickstart

# Check fleet status
curl http://localhost:8100/api/centurion/status

# Raise a legion
curl -X POST http://localhost:8100/api/centurion/legions \
  -H "Content-Type: application/json" \
  -d '{"name": "Research Team"}'

# Add a century of agents
curl -X POST http://localhost:8100/api/centurion/legions/{legion_id}/centuries \
  -H "Content-Type: application/json" \
  -d '{"agent_type": "claude_cli", "min_legionaries": 3, "max_legionaries": 10}'

# Submit batch tasks
curl -X POST http://localhost:8100/api/centurion/legions/{legion_id}/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompts": ["Research topic A", "Research topic B", "Research topic C"]}'

# Broadcast to all agents
curl -X POST http://localhost:8100/api/centurion/broadcast \
  -H "Content-Type: application/json" \
  -d '{"message": "Switch to summarization mode", "target": "all"}'
```

### 2. MCP Server (Claude Code / Claude Desktop)

Register Centurion as an MCP server to orchestrate agents directly from Claude:

```bash
# Register the MCP server
claude mcp add centurion -- python -m centurion.mcp

# Or in claude_desktop_config.json:
{
  "mcpServers": {
    "centurion": {
      "command": "python",
      "args": ["-m", "centurion.mcp"],
      "env": {
        "CENTURION_API_BASE": "http://localhost:8100/api/centurion"
      }
    }
  }
}
```

Available MCP tools (19): `fleet_status`, `hardware_status`, `raise_legion`, `list_legions`, `get_legion`, `disband_legion`, `add_century`, `get_century`, `scale_century`, `remove_century`, `submit_task`, `submit_batch`, `get_task`, `cancel_task`, `list_legionaries`, `get_legionary`, `list_agent_types`, `broadcast`, `recommend`.

### 3. Claude Code Skill

Install Centurion as a Claude Code slash command:

```bash
# Generate the skill definition
python -m centurion.skill > ~/.claude/skills/centurion.toml

# Now use in Claude Code:
# /centurion raise a legion of 10 research agents
```

### 4. A2A Protocol (Agent-to-Agent)

Centurion implements [Google's A2A protocol](https://google.github.io/A2A/) for interoperability with other AI agents:

```bash
# Discovery: other agents find Centurion via the Agent Card
curl http://localhost:8100/.well-known/agent.json

# Submit a task via A2A JSON-RPC
curl -X POST http://localhost:8100/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "id": "req-001",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Analyze market trends for Q1 2026"}]
      }
    }
  }'
```

The A2A endpoint automatically routes tasks to the first available legion and century.

### 5. Python Library

For direct programmatic integration without any HTTP layer:

```python
from centurion import Centurion, CenturyConfig

engine = Centurion()
legion = await engine.raise_legion("alpha", name="Alpha Team")
century = await legion.add_century(
    None,
    CenturyConfig(agent_type_name="claude_cli", min_legionaries=5, max_legionaries=20),
    engine.registry, engine.scheduler, engine.event_bus,
)

# Submit tasks
futures = [await century.submit_task(prompt) for prompt in prompts]
results = await asyncio.gather(*futures)

# Broadcast instructions to all agents
await engine.broadcast("Prioritize accuracy over speed", target="all")

# Shutdown
await engine.shutdown()
```

---

## Broadcasting

Send real-time instructions to working agents. Broadcasts are delivered to each legionary's message inbox.

```bash
# Broadcast to ALL agents in the fleet
curl -X POST http://localhost:8100/api/centurion/broadcast \
  -d '{"message": "Switch to JSON output format", "target": "all"}'

# Broadcast to a specific legion (row)
curl -X POST http://localhost:8100/api/centurion/broadcast \
  -d '{"message": "Focus on financial data", "target": "legion", "target_id": "legion-abc123"}'

# Broadcast to a specific century (column)
curl -X POST http://localhost:8100/api/centurion/broadcast \
  -d '{"message": "Increase verbosity", "target": "century", "target_id": "century-xyz789"}'
```

Via MCP: `broadcast(message="Switch modes", target="all")`

Via Python: `await engine.broadcast("Switch modes", target="legion", target_id="alpha")`

## Agent Types

| Name          | Backend                    | Flags / Notes                           | RAM per Agent |
|---------------|----------------------------|-----------------------------------------|---------------|
| `claude_cli`  | Claude CLI subprocess      | `--dangerously-skip-permissions`        | ~250 MB       |
| `claude_api`  | Anthropic Python SDK       | Requires `ANTHROPIC_API_KEY`            | ~50 MB        |
| `shell`       | System shell subprocess    | Runs arbitrary shell commands           | ~50 MB        |

Each agent type declares its own resource requirements (CPU millicores and memory) used by the scheduler for admission control.

## API Reference

All endpoints are served under `/api/centurion/` (default port 8100).

| Method   | Endpoint                                         | Description                             |
|----------|--------------------------------------------------|-----------------------------------------|
| `GET`    | `/status`                                        | Fleet-wide status overview              |
| `GET`    | `/hardware`                                      | Hardware resources and scheduling state |
| `POST`   | `/legions`                                       | Raise a new legion                      |
| `GET`    | `/legions`                                       | List all legions                        |
| `GET`    | `/legions/{legion_id}`                           | Get legion details                      |
| `DELETE` | `/legions/{legion_id}`                           | Disband a legion                        |
| `POST`   | `/legions/{legion_id}/centuries`                 | Add a century to a legion               |
| `GET`    | `/centuries/{century_id}`                        | Get century details                     |
| `DELETE` | `/centuries/{century_id}`                        | Remove a century                        |
| `POST`   | `/centuries/{century_id}/scale`                  | Scale a century                         |
| `POST`   | `/centuries/{century_id}/tasks`                  | Submit a task to a century              |
| `POST`   | `/legions/{legion_id}/tasks`                     | Submit batch tasks                      |
| `GET`    | `/tasks/{task_id}`                               | Get task details                        |
| `POST`   | `/tasks/{task_id}/cancel`                        | Cancel a task                           |
| `POST`   | `/broadcast`                                     | Broadcast to all/legion/century         |
| `GET`    | `/centuries/{century_id}/legionaries`            | List agents in a century                |
| `GET`    | `/legionaries/{legionary_id}`                    | Get agent details                       |
| `GET`    | `/agent-types`                                   | List registered agent types             |
| `WS`     | `/ws/events`                                     | Real-time event stream                  |
| `GET`    | `/.well-known/agent.json`                        | A2A Agent Card                          |
| `POST`   | `/a2a`                                           | A2A task submission                     |

## Hardware-Aware Scheduling

The scheduler probes available CPU and RAM, then performs admission control before spawning agents:

- **Auto-detection**: Reads CPU cores and available RAM at startup
- **Headroom reservation**: Keeps `CENTURION_RAM_HEADROOM_GB` (default 2 GB) free for the OS
- **Throttling**: Automatically pauses agent spawning when resources are tight
- **Per-agent budgets**: Each agent type declares its CPU/RAM requirements
- **Circuit breaker**: Protects against cascading failures with automatic recovery

## Configuration

Centurion reads configuration from environment variables with sensible defaults.

| Variable                      | Default                    | Description                                      |
|-------------------------------|----------------------------|--------------------------------------------------|
| `CENTURION_DB_PATH`           | `data/centurion.db`        | Path to the SQLite database file                 |
| `CENTURION_SESSION_DIR`       | `/tmp/centurion-sessions`  | Base directory for agent working directories      |
| `CENTURION_MAX_AGENTS`        | `0` (auto)                 | Hard limit on concurrent agents (0 = auto-detect)|
| `CENTURION_PORT`              | `8100`                     | HTTP server port                                 |
| `CENTURION_RAM_HEADROOM_GB`   | `2.0`                      | RAM headroom reserved for the OS (GB)            |
| `CENTURION_TASK_TIMEOUT`      | `300`                      | Default task timeout in seconds                  |
| `CENTURION_CLAUDE_BIN`        | `claude`                   | Path to the Claude CLI binary                    |
| `CENTURION_CLAUDE_MODEL`      | `claude-sonnet-4-6`        | Default model for Claude API agent type          |
| `CENTURION_AUTH_TOKEN`         | (none)                     | API authentication token (see [Authentication](#authentication)) |
| `ANTHROPIC_API_KEY`           | (none)                     | Anthropic API key for `claude_api` agent type    |

## Authentication

By default, all Centurion endpoints are unauthenticated. To enable token-based authentication, set the `CENTURION_AUTH_TOKEN` environment variable:

```bash
export CENTURION_AUTH_TOKEN="your-secret-token-here"
centurion up
```

When enabled, every request to a protected endpoint must include the `X-Centurion-Token` header:

```bash
# Authenticated request
curl -H "X-Centurion-Token: your-secret-token-here" \
     http://localhost:8100/api/centurion/status

# Returns 401 without the header
curl http://localhost:8100/api/centurion/status
# {"detail": "Missing X-Centurion-Token header"}
```

**Public endpoints** (no token required):
- `GET /health` — liveness probe
- `GET /health/ready` — readiness probe

All other endpoints (`/api/centurion/*`, `/a2a`, `/.well-known/agent.json`) require a valid token when `CENTURION_AUTH_TOKEN` is set.

## Success Stories

Real projects orchestrated by Centurion. Every number comes from actual task logs and commit history.

| # | Project | Result | Key Metric |
|---|---------|--------|------------|
| 01 | **OpenClaw Bug Fixes** | 8 PRs merged in 30 min | 7,000+ Rust tests per PR, zero OOM kills |
| 02 | **PlugMate Research** | 8 research tasks in 34 min | 4 peak parallel agents, zero retries |
| 03 | **20-Agent Fleet** | 20+ agents on a single Mac Mini | Zero OOM kills, zero process starvation |
| 04 | **Enterprise DevOps** *(projected)* | 12 microservices, ~75% time reduction | 3 hrs sequential → ~45 min parallel |
| 05 | **Research Automation** *(projected)* | 30 papers in ~4 hrs | 8-10 researcher-days → single afternoon |
| 06 | **CI Pipeline Build** | 10 tasks, 13 files, 4 orphans cleaned | QA agent found hanging tests, gateway cleaned leaked processes |

**Story 06 highlight — Orphan Process Lifecycle:** During CI pipeline construction, a QA subagent ran `pytest` against the full test suite. Two websocket tests hung due to asyncio threading issues, spawning 4 background processes that never terminated. Claude Code's subagent completed and returned, but the orphaned OS processes kept running. Centurion's gateway session manager detected the leaked processes at session boundary, terminated all 4 cleanly, and sent status notifications — zero data loss, zero manual intervention.

→ [View all stories on the website](https://spacelobster88.github.io/centurion/)

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
# Clone and set up development environment
git clone https://github.com/spacelobster88/centurion.git
cd centurion
pip install -e ".[dev]"

# Run tests
pytest tests/ -v --cov=centurion
```

## License

MIT License. See [LICENSE](LICENSE) for details.

---

**[Documentation & Website](https://spacelobster88.github.io/centurion/)** | **[GitHub](https://github.com/spacelobster88/centurion)** | **[Auspex (full-stack installer)](https://github.com/spacelobster88/auspex)**
