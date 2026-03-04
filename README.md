# Centurion

Spawn and command an army of AI agents with Roman military precision.

---

## Overview

Centurion is an AI agent orchestration engine that manages fleets of AI agents at scale. It provides a structured framework for spawning, scheduling, and coordinating multiple AI agents -- whether they are Claude CLI processes, Anthropic API calls, or plain shell commands -- under a unified control plane.

The engine draws its organizational model from the Roman military hierarchy. Agents are grouped into Centuries (squads of the same type sharing a task queue), which belong to Legions (deployment groups with resource quotas). A built-in scheduler inspired by Kubernetes resource management handles admission control, hardware-aware autoscaling, and capacity planning. Each Century includes an Optio (autoscaler) that monitors queue depth and adjusts the number of active agents in real time.

Centurion supports three deployment modes -- standalone server, embedded FastAPI router, and pure library -- so it fits into existing Python applications without imposing architectural constraints. A WebSocket-based event bus (the Aquilifer) streams lifecycle events in real time, enabling dashboards, logging pipelines, and programmatic reactions to agent activity.

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

## Project Stats

| Metric | Value |
|--------|-------|
| Source files | 31 |
| Source lines | ~2,880 |
| Test files | 22 |
| Test count | 154+ passing |
| Test lines | ~3,860 |
| Agent types | 3 (claude_cli, claude_api, shell) |
| MCP tools | 17 |
| REST endpoints | 13 |

## Quickstart

Install from PyPI:

```bash
pip install centurion
```

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

## Three Modes

Centurion can run in three different modes depending on your use case.

### Standalone Server

Run Centurion as an independent HTTP server with a full REST API and WebSocket event stream:

```bash
python -m centurion
# Starts on http://0.0.0.0:8100 by default
```

### Embedded (FastAPI Router)

Mount Centurion into an existing FastAPI application:

```python
from fastapi import FastAPI
from centurion.api import router as centurion_router

app = FastAPI()
app.include_router(centurion_router, prefix="/centurion")
```

### Library (Programmatic)

Use Centurion directly in Python code without any HTTP layer. Import the engine, create legions and centuries, and submit tasks programmatically. See the Quickstart example above.

## Agent Types

| Name          | Backend                    | Flags / Notes                           | RAM per Agent |
|---------------|----------------------------|-----------------------------------------|---------------|
| `claude_cli`  | Claude CLI subprocess      | `--dangerously-skip-permissions`        | ~250 MB       |
| `claude_api`  | Anthropic Python SDK       | Requires `ANTHROPIC_API_KEY`            | ~50 MB        |
| `shell`       | System shell subprocess    | Runs arbitrary shell commands           | ~50 MB        |

Each agent type declares its own resource requirements (CPU millicores and memory) used by the scheduler for admission control.

## API Reference

All endpoints are served under the configured host and port (default `0.0.0.0:8100`).

| Method   | Endpoint                                         | Description                             |
|----------|--------------------------------------------------|-----------------------------------------|
| `GET`    | `/status`                                        | Fleet-wide status overview              |
| `GET`    | `/hardware`                                      | Hardware resources and scheduling state |
| `POST`   | `/legions`                                       | Raise a new legion                      |
| `GET`    | `/legions`                                       | List all legions                        |
| `GET`    | `/legions/{legion_id}`                           | Get legion details                      |
| `DELETE` | `/legions/{legion_id}`                           | Disband a legion                        |
| `POST`   | `/legions/{legion_id}/centuries`                 | Add a century to a legion               |
| `GET`    | `/legions/{legion_id}/centuries`                 | List centuries in a legion              |
| `DELETE` | `/legions/{legion_id}/centuries/{century_id}`    | Remove a century                        |
| `POST`   | `/legions/{legion_id}/centuries/{century_id}/tasks` | Submit a task to a century           |
| `POST`   | `/legions/{legion_id}/batch`                     | Submit a batch of tasks across centuries|
| `POST`   | `/legions/{legion_id}/centuries/{century_id}/scale` | Scale a century to a target size     |
| `GET`    | `/events`                                        | Recent events (JSON)                    |
| `WS`     | `/ws/events`                                     | Real-time event stream via WebSocket    |

## MCP Integration

Centurion exposes 17 MCP tools, allowing Claude Code to orchestrate agents directly:

```bash
# Register as MCP server
claude mcp add centurion -- python -m centurion.mcp
```

Key MCP tools: `raise_legion`, `add_century`, `submit_task`, `submit_batch`, `fleet_status`, `scale_century`, `get_hardware`, `disband_legion`, and more.

## Hardware-Aware Scheduling

The scheduler probes available CPU and RAM, then performs admission control before spawning agents. Features:

- **Auto-detection**: Reads CPU cores and available RAM at startup
- **Headroom reservation**: Keeps `CENTURION_RAM_HEADROOM_GB` (default 2 GB) free for the OS
- **Throttling**: Automatically pauses agent spawning when resources are tight
- **Per-agent budgets**: Each agent type declares its CPU/RAM requirements

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

## Architecture

```
Centurion (Engine)
 +-- CenturionScheduler (admission control + resource tracking)
 +-- AgentTypeRegistry (claude_cli, claude_api, shell)
 +-- EventBus (Aquilifer -- pub-sub for lifecycle events)
 +-- Legion "alpha"
 |    +-- Century "search-squad" (claude_cli x 5)
 |    |    +-- Legionary leg-a1b2c3d4 [IDLE]
 |    |    +-- Legionary leg-e5f6g7h8 [BUSY]
 |    |    +-- ...
 |    +-- Century "analysis-squad" (claude_api x 3)
 +-- Legion "beta"
      +-- Century "build-squad" (shell x 10)
```

## License

MIT License. See [LICENSE](LICENSE) for details.
