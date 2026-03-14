# Centurion — Design Document

## Architecture

```
         Centurion (Engine/Control Plane)
         ├── Scheduler (admission control)
         ├── EventBus (Aquilifer)
         └── HardwareProbe
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
  Legion α  Legion β  Legion γ
  (Quota:50) (Quota:20)
    │
  ┌─┼──────┐
  ▼ ▼      ▼
Century   Century   Century
(Claude   (Shell)   (Claude
 CLI×10)   ×5)      API×20)
  │││      ││        ││││...
  LLL      LL        LLLL    ← Legionaries
```

## Hierarchy Mapping

| Roman | Centurion | K8s |
|-------|-----------|-----|
| Centurion | Engine singleton | Control Plane |
| Legion | Deployment group | Namespace |
| Century | Same-type agent squad + queue | ReplicaSet + HPA |
| Legionary | Individual agent | Pod |
| Optio | Century's autoscaler | HPA |
| Praetorian | Priority task class | PriorityClass |
| Aquilifer | EventBus | Event Controller |

## Module Layout

```
centurion/
├── __init__.py          # Public API exports
├── __main__.py          # Standalone server
├── config.py            # Configuration
├── core/
│   ├── engine.py        # Centurion orchestrator
│   ├── century.py       # Agent squads + Optio autoscaler
│   ├── legion.py        # Deployment groups + quotas
│   ├── legionary.py     # Individual agents
│   ├── scheduler.py     # K8s-style admission control
│   └── events.py        # EventBus (Aquilifer)
├── agent_types/
│   ├── base.py          # AgentType ABC
│   ├── claude_cli.py    # Claude CLI subprocess
│   ├── claude_api.py    # Anthropic API
│   ├── shell.py         # Shell commands
│   └── registry.py      # Plugin registry
├── api/
│   ├── router.py        # REST endpoints
│   ├── schemas.py       # Pydantic models
│   └── websocket.py     # WebSocket events
├── db/
│   ├── repository.py    # Async SQLite
│   └── schema.py        # DDL
├── hardware/
│   ├── probe.py         # System resource detection
│   └── throttle.py      # Pressure monitoring
└── mcp/
    └── tools.py         # MCP tool definitions (TO BE IMPLEMENTED)
```

## MCP Tools Design (remaining work)

The MCP tools module should follow the same pattern as mini-claude-bot's `mcp_server.py`:
- Use `mcp.server.fastmcp.FastMCP`
- Proxy to Centurion REST API via httpx
- Expose key operations: fleet status, raise/disband legions, add/remove centuries, submit tasks, scale, hardware info

## Status: APPROVED
