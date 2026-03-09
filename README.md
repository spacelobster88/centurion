# Centurion

**Spawn and command an army of AI agents with Roman military precision.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-298%20passing-brightgreen.svg)]()
[![MCP Tools](https://img.shields.io/badge/MCP%20tools-18-purple.svg)]()
[![A2A Protocol](https://img.shields.io/badge/A2A-compatible-orange.svg)](https://google.github.io/A2A/)
[![OpenClaw Compatible](https://img.shields.io/badge/OpenClaw-compatible-red.svg)]()
[![Claude Code](https://img.shields.io/badge/Claude%20Code-native-blueviolet.svg)]()

---

## Overview

Centurion is an AI agent orchestration engine that manages fleets of AI agents at scale. While most frameworks stop at 1-2 agents, Centurion scales to **100+ concurrent agents** with hardware-aware scheduling, real-time broadcasting, and five integration methods.

```
                          +-----------------------+
                          |      CENTURION        |
                          |    Control Plane       |
                          +----------+------------+
                                     |
              +----------------------+----------------------+
              |                      |                      |
     +--------v--------+   +--------v--------+   +---------v-------+
     |   Scheduler      |   |   Broadcaster    |   |   EventBus      |
     | (K8s-inspired    |   | (all/legion/     |   |  (Aquilifer)     |
     |  admission ctrl) |   |  century scope)  |   |  WebSocket pub-  |
     +--------+---------+   +--------+---------+   |  sub events      |
              |                      |              +---------+-------+
              +----------------------+                        |
                          |                                   |
         +----------------+----------------+                  |
         |                                 |                  |
+--------v---------+            +----------v--------+        |
|  Legion "alpha"   |            |  Legion "beta"     |        |
|  (Research Ops)   |            |  (Build Ops)       |        |
+--------+---------+            +----------+---------+        |
         |                                 |                  |
    +----+--------+                   +----+----+             |
    |             |                   |         |             |
+---v----+  +----v---+          +----v---+ +---v----+        |
|Century |  |Century |          |Century | |Century |        |
|claude  |  |claude  |          |shell   | |claude  |        |
|_cli x5 |  |_api x3 |          |  x10   | |_api x8 |        |
+---+----+  +---+----+          +---+----+ +---+----+        |
    |           |                   |          |              |
  L L L L L  L L L              L L L L..  L L L L..         |
  | | | | |  | | |              | | | |    | | | |           |
  v v v v v  v v v              v v v v    v v v v           |
  Legionaries (individual agent instances)     <-- events ---+
```

### Why Centurion?

| Feature | CrewAI | AutoGen | LangGraph | Centurion |
|---------|--------|---------|-----------|-----------|
| Max practical agents | 2-5 | 2-10 | 2-5 | **100+** |
| Hardware-aware scheduling | :x: | :x: | :x: | :white_check_mark: |
| Auto-scaling (Optio) | :x: | :x: | :x: | :white_check_mark: |
| Admission control (K8s-style) | :x: | :x: | :x: | :white_check_mark: |
| Real-time event streaming | :x: | :x: | :x: | :white_check_mark: |
| Fleet broadcasting | :x: | :x: | :x: | :white_check_mark: |
| MCP server integration | :x: | :x: | :x: | :white_check_mark: |
| Claude Code native | :x: | :x: | :x: | :white_check_mark: |
| OpenClaw compatible | :x: | :x: | :x: | :white_check_mark: |
| A2A protocol (Google) | :x: | :x: | :x: | :white_check_mark: |
| REST API | :x: | :x: | partial | :white_check_mark: |
| Circuit breaker / fault tolerance | :x: | :x: | :x: | :white_check_mark: |
| Multiple agent types | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| Python library mode | :white_check_mark: | :white_check_mark: | :white_check_mark: | :white_check_mark: |
| Task queuing with priority | :x: | :x: | :x: | :white_check_mark: |

> **CrewAI / AutoGen / LangGraph** are excellent for workflows with 1-5 specialized agents in fixed roles. **Centurion** is built for when you need to scale — 10, 50, or 100+ agents executing tasks in parallel with real-time fleet management.

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

The fastest way to get Centurion running. It automatically probes your hardware, recommends the optimal number of agents, and launches with a pre-configured fleet:

```bash
# Install
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

Available MCP tools: `fleet_status`, `hardware_status`, `raise_legion`, `list_legions`, `get_legion`, `disband_legion`, `add_century`, `get_century`, `scale_century`, `remove_century`, `submit_task`, `submit_batch`, `get_task`, `cancel_task`, `list_legionaries`, `get_legionary`, `list_agent_types`, `broadcast`.

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
| `ANTHROPIC_API_KEY`           | (none)                     | Anthropic API key for `claude_api` agent type    |

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
