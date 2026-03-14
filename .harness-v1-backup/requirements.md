# Centurion — Requirements

## Project Overview
AI Agent Orchestration Engine inspired by Roman military hierarchy. Spawns and manages armies of AI agents with K8s-inspired resource scheduling.

## Core Requirements
1. **Engine (Centurion)**: Singleton orchestrator managing all legions, scheduling, and events
2. **Hierarchy**: Centurion → Legion → Century → Legionary (mapping to K8s Control Plane → Namespace → ReplicaSet → Pod)
3. **Agent Types**: claude_cli (subprocess), claude_api (Anthropic SDK), shell (command runner)
4. **Resource Scheduling**: K8s-inspired admission control, quota enforcement, hardware-aware limits
5. **Autoscaling (Optio)**: Per-century autoscaler with configurable thresholds
6. **Event System (Aquilifer)**: Pub-sub EventBus with WebSocket streaming
7. **REST API**: Full CRUD for legions, centuries, tasks, legionaries
8. **Database**: SQLite persistence for tasks, events, hardware snapshots
9. **3 Running Modes**: Standalone service, embedded FastAPI router, library
10. **MCP Integration**: Expose engine operations as MCP tools for Claude Code

## Constraints
- Python 3.12+, FastAPI, asyncio
- macOS: Shell agents prefer iTerm2 (FullDiskAccess, Accessibility, Automation)
- claude_cli agents use --dangerously-skip-permissions flag
- Hardware-aware: recommended max = min(cpu_cores * 2, (available_ram - 2GB) / per_agent_mb)

## Status
- Requirements: APPROVED
- Design: APPROVED
- Implementation: 97% complete (37/38 files)
- Remaining: MCP tools implementation + test verification
