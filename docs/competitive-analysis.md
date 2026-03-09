# Centurion vs. The Field: Competitive Analysis

## AI Agent Orchestration Landscape (2025-2026)

The demand for multi-agent AI systems has exploded, but most frameworks were designed for small-scale coordination — typically 2-5 agents collaborating on a single task. Centurion was built for a fundamentally different problem: **fleet-scale orchestration of 100+ agents with hardware-aware scheduling, fault tolerance, and real-time observability.**

This document compares Centurion against the three most prominent agent orchestration frameworks.

---

## 1. CrewAI

### Architecture Overview

CrewAI uses a **role-based multi-agent paradigm** where each agent is assigned a specific role (e.g., "Researcher", "Writer", "Reviewer") and agents collaborate through a sequential or hierarchical task pipeline. Crews are defined declaratively with fixed agent configurations.

```
Crew
├── Agent (role: Researcher)
├── Agent (role: Writer)
└── Agent (role: Reviewer)
    └── Tasks flow sequentially or hierarchically
```

### Max Practical Scale

- **Designed for:** 2-8 agents per crew
- **Practical ceiling:** ~10-15 agents before coordination overhead dominates
- **Bottleneck:** Single-process execution; all agents share one event loop and memory space

### Resource Management

- **None.** No hardware detection, no memory budgeting, no CPU-aware scheduling
- Agent count is manually configured; no admission control
- No autoscaling — if you define 5 agents, you get 5 agents regardless of available resources

### Key Limitations at Scale

| Limitation | Impact |
|-----------|--------|
| No resource awareness | Agents compete for CPU/RAM unchecked; OOM kills at scale |
| Fixed agent topology | Cannot dynamically add/remove agents based on workload |
| No fault isolation | One agent crash can poison the entire crew pipeline |
| Sequential bottlenecks | Hierarchical mode creates single points of failure |
| No real-time observability | Limited to log parsing; no event streaming |
| Single-process only | Cannot distribute across machines or containers |

---

## 2. AutoGen (Microsoft)

### Architecture Overview

AutoGen models agents as **conversational participants** in group chats. Agents communicate by sending messages to each other, with configurable reply patterns. The framework supports "nested chats" and "teachable agents" but is fundamentally conversation-centric.

```
GroupChat
├── AssistantAgent
├── UserProxyAgent
├── Agent C
└── GroupChatManager (orchestrates turn-taking)
```

### Max Practical Scale

- **Designed for:** 2-6 agents in conversation
- **Practical ceiling:** ~10-20 agents before conversation management becomes unwieldy
- **Bottleneck:** GroupChatManager must track and route all messages; token costs scale quadratically with agent count as context windows fill up

### Resource Management

- **Minimal.** AutoGen focuses on conversation flow, not compute management
- No hardware probing or resource budgeting
- LLM API costs scale unpredictably with group size (more agents = more messages = more tokens)
- No admission control — adding agents always succeeds regardless of system capacity

### Key Limitations at Scale

| Limitation | Impact |
|-----------|--------|
| Conversation-centric model | Forces all coordination through message passing; inefficient for parallel workloads |
| Quadratic token scaling | Group chats with N agents generate O(N²) message interactions |
| No task queuing | No built-in work queue; each agent must be explicitly addressed |
| No horizontal scaling | Single-process architecture; no distribution story |
| Manual orchestration | Developer must define conversation flow and termination conditions |
| No autoscaling | Cannot dynamically adjust agent count based on workload or hardware |

---

## 3. LangGraph (LangChain)

### Architecture Overview

LangGraph models agent workflows as **directed graphs** where nodes are computation steps (LLM calls, tool use, decisions) and edges define control flow. It supports cycles (loops), conditional branching, and persistent state. LangGraph Cloud adds deployment and scaling capabilities.

```
StateGraph
├── Node: classify_input
├── Node: research (can loop)
├── Node: generate_response
├── Edge: conditional routing
└── Checkpointer: state persistence
```

### Max Practical Scale

- **Designed for:** Complex single-agent or few-agent workflows with sophisticated control flow
- **Practical ceiling:** ~5-15 concurrent graph executions (via LangGraph Cloud); not designed for fleet management
- **Bottleneck:** Each graph execution is independent; no cross-graph coordination or shared scheduling

### Resource Management

- **LangGraph Cloud** provides managed infrastructure with thread-level concurrency
- No hardware-aware scheduling on self-hosted deployments
- No admission control or resource budgeting at the agent level
- Scaling is at the graph-execution level, not the agent level

### Key Limitations at Scale

| Limitation | Impact |
|-----------|--------|
| Graph = workflow, not fleet | Optimized for complex single-agent logic, not managing many agents |
| No fleet management primitives | No concept of agent pools, squads, or hierarchical organization |
| LangGraph Cloud lock-in | Scaling features require paid cloud service |
| State overhead | Checkpoint persistence adds latency per step |
| No autoscaling of agent count | Cannot dynamically spawn/terminate agents based on demand |
| Vendor coupling | Tightly integrated with LangChain ecosystem |

---

## Centurion: Purpose-Built for Fleet Scale

Centurion was designed from day one to answer the question: **"How do you manage 100+ AI agents on real hardware without everything falling over?"**

### Architecture Overview

```
         Centurion Engine (Control Plane)
         ├── Scheduler (admission control)
         ├── EventBus / Aquilifer (real-time events)
         └── HardwareProbe
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
  Legion α  Legion β  Legion γ
  (Quota:50) (Quota:20) (Quota:30)
    │
  ┌─┼──────┐
  ▼ ▼      ▼
Century   Century   Century
(Claude   (Shell)   (Claude
 CLI×10)   ×5)      API×20)
  │││      ││        ││││...
  LLL      LL        LLLL    ← Legionaries (individual agents)
```

### Advantage 1: True Horizontal Scaling (100+ Agents)

While competitors max out at 10-20 agents, Centurion is architected for **hundreds of concurrent agents**:

- **Async-native:** Built on `asyncio` with non-blocking subprocess management — no GIL contention
- **Hierarchical grouping:** Legions contain Centuries contain Legionaries — management overhead stays O(log N) not O(N²)
- **Task queuing per Century:** Each Century has its own PriorityQueue, so agents pull work independently without contention
- **Tested under load:** Stress tests validate 50+ concurrent tasks with autoscaling, failure recovery, and graceful shutdown

### Advantage 2: K8s-Inspired Resource Scheduling

Centurion borrows Kubernetes' proven admission control pattern:

```python
# Every agent type declares resource requirements
ResourceSpec(cpu_millicores=500, memory_mb=250)  # Claude CLI
ResourceSpec(cpu_millicores=100, memory_mb=50)    # Claude API

# Before every spawn, the Scheduler checks:
# 1. Does the system have physical capacity? (CPU + RAM)
# 2. Is the Legion under its quota?
# 3. Allocate → Spawn → Release on terminate
```

**No other agent framework does this.** CrewAI, AutoGen, and LangGraph all let you spawn agents until the system crashes.

| Feature | CrewAI | AutoGen | LangGraph | Centurion |
|---------|--------|---------|-----------|-----------|
| Hardware detection | No | No | No | Yes |
| Resource budgeting per agent | No | No | No | Yes |
| Admission control | No | No | No | Yes |
| Quota enforcement per group | No | No | No | Yes |
| Recommended max calculation | No | No | No | Yes |

### Advantage 3: Hardware-Aware Autoscaling (Optio)

Each Century has an embedded autoscaler called **Optio** (the Roman second-in-command):

- **Scale up:** Queue depth exceeds idle agents × threshold → spawn more agents (if Scheduler allows)
- **Scale down:** Queue empty for 60 seconds → gracefully terminate idle agents down to minimum
- **Cooldown:** 15-second minimum between scaling events to prevent thrashing
- **Self-healing:** 3 consecutive agent failures → auto-replace the Legionary

No manual intervention. No external monitoring required. The fleet manages itself.

### Advantage 4: Three Deployment Modes

```python
# 1. Standalone service — run it independently
python -m centurion --port 8100

# 2. Embedded — mount inside your existing FastAPI app
app.include_router(centurion_router, prefix="/api/centurion")

# 3. Library — import and use programmatically
engine = Centurion()
legion = await engine.raise_legion("research")
century = await legion.add_century("squad", config)
results = await asyncio.gather(*[century.submit_task(p) for p in prompts])
```

No other framework offers this flexibility. CrewAI and AutoGen are library-only. LangGraph requires their cloud platform for deployment features.

### Advantage 5: Real-Time Event Streaming

WebSocket endpoint streams every fleet event in real time:

```
legionary_spawned, legionary_terminated, legionary_replaced
century_scaled_up, century_scaled_down
task_submitted, task_started, task_completed, task_failed
hardware_warning, resource_exhausted, scheduler_rejected
```

Build dashboards, alerting systems, or automated responses on top of the event stream. Competitors offer log files at best.

### Advantage 6: Roman Military Hierarchy for Intuitive Fleet Management

The naming convention is not just thematic — it maps directly to operational concepts:

| Concept | Centurion Term | What It Means |
|---------|---------------|---------------|
| Control plane | **Centurion** | The engine that commands everything |
| Deployment group | **Legion** | Isolated group with its own resource quota |
| Agent pool | **Century** | Same-type agents sharing a task queue |
| Individual agent | **Legionary** | Single worker instance |
| Autoscaler | **Optio** | Second-in-command that adjusts squad size |
| Priority task | **Praetorian** | Tasks that jump the queue |
| Event bus | **Aquilifer** | The standard-bearer broadcasting fleet events |

This hierarchy makes it natural to reason about fleet operations: "Raise a Legion with three Centuries of 10 Claude agents each" is immediately understandable.

### Advantage 7: Circuit Breaker Pattern for Fault Tolerance

Centurion implements multi-level fault tolerance:

- **Agent level:** Legionary tracks consecutive failures; 3 strikes and it is automatically replaced with a fresh instance
- **Century level:** Optio monitors squad health; maintains minimum headcount even under failures
- **Legion level:** Quota enforcement prevents runaway spawning from cascading across the fleet
- **Engine level:** Graceful shutdown drains in-progress tasks before terminating; pending tasks are cancelled cleanly
- **Scheduler level:** Resource exhaustion triggers `scheduler_rejected` events instead of silent failures

---

## Summary Comparison Matrix

| Capability | CrewAI | AutoGen | LangGraph | **Centurion** |
|-----------|--------|---------|-----------|---------------|
| **Max practical agents** | ~10 | ~20 | ~15 | **100+** |
| **Scaling model** | Fixed roles | Conversation | Graph execution | **Fleet hierarchy** |
| **Hardware awareness** | None | None | None | **Full (CPU/RAM/load)** |
| **Admission control** | None | None | None | **K8s-inspired** |
| **Autoscaling** | None | None | Cloud only | **Per-Century (Optio)** |
| **Task queuing** | Sequential | Message-based | State graph | **PriorityQueue per Century** |
| **Fault tolerance** | None | None | Checkpoints | **Circuit breaker + auto-replace** |
| **Real-time events** | None | Callbacks | LangSmith | **WebSocket stream** |
| **Deployment modes** | Library | Library | Library + Cloud | **Standalone / Embedded / Library** |
| **Resource scheduling** | None | None | None | **Request/Limit per agent type** |
| **Open source** | Yes (MIT) | Yes (CC-BY-4.0) | Yes (MIT) | **Yes (MIT)** |

---

## When to Use What

| Use Case | Best Choice |
|----------|-------------|
| Simple 3-5 agent pipeline with fixed roles | CrewAI |
| Conversational multi-agent reasoning | AutoGen |
| Complex single-agent workflow with loops and branches | LangGraph |
| **Running 50+ agents on real hardware with resource management** | **Centurion** |
| **Dynamic fleet scaling based on workload** | **Centurion** |
| **Production deployment with fault tolerance and observability** | **Centurion** |
| **Mixed agent types (CLI, API, shell) in one fleet** | **Centurion** |

---

## Conclusion

CrewAI, AutoGen, and LangGraph solve the problem of *"how do I get a few AI agents to collaborate?"* Centurion solves a different and harder problem: *"how do I operate a fleet of AI agents in production, at scale, on real hardware, without it falling over?"*

If you need 3 agents to have a conversation, use AutoGen. If you need 100 agents processing tasks with hardware-aware scheduling, autoscaling, fault tolerance, and real-time observability — **raise a Legion.**
