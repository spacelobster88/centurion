"""Claude Code Skill definition for Centurion.

This module generates a Claude Code skill TOML configuration that can be
added to a user's .claude/skills/ directory, enabling Centurion orchestration
directly from Claude Code via slash commands.

Usage:
    python -m centurion.skill > ~/.claude/skills/centurion.toml
"""

SKILL_TOML = """\
# Centurion — AI Agent Orchestration Skill for Claude Code
# Copy this file to ~/.claude/skills/centurion.toml

[skill]
name = "centurion"
description = "Orchestrate an army of AI agents using Centurion"
version = "0.1.0"

# Trigger patterns — when these appear in user messages, this skill activates
triggers = [
    "centurion",
    "raise legion",
    "muster century",
    "fleet status",
    "spawn agents",
    "agent army",
    "broadcast to agents",
    "agent orchestration",
]

[skill.instructions]
text = \"\"\"
You have access to the Centurion AI Agent Orchestration Engine.
Centurion manages fleets of AI agents organized in Roman military hierarchy:

- **Legion**: A deployment group (like a K8s namespace)
- **Century**: A squad of same-type agents with shared task queue
- **Legionary**: An individual agent instance

Available operations via the Centurion MCP server:

Fleet Management:
- `fleet_status` — Get macro-level fleet overview
- `hardware_status` — Check CPU/RAM and recommended agent count

Legion Operations:
- `raise_legion(name)` — Create a new legion
- `list_legions()` — List all active legions
- `disband_legion(legion_id)` — Terminate a legion and all its agents

Century Operations:
- `add_century(legion_id, agent_type, min_legionaries, max_legionaries)` — Add agent squad
- `scale_century(century_id, target_count)` — Scale agents up/down
- `remove_century(century_id)` — Remove a century

Task Operations:
- `submit_task(century_id, prompt)` — Submit a task to a specific century
- `submit_batch(legion_id, prompts)` — Distribute tasks across a legion

Broadcasting:
- `broadcast(message, target="all")` — Broadcast to all agents in the fleet
- `broadcast(message, target="legion", target_id="...")` — Broadcast to a specific legion
- `broadcast(message, target="century", target_id="...")` — Broadcast to a specific century

A2A Integration:
- Centurion supports Google's A2A protocol at `/.well-known/agent.json`
- Other agents can discover and interact with the fleet via `POST /a2a`

When the user asks to orchestrate multiple agents, use Centurion to:
1. Check hardware capacity with `hardware_status`
2. Raise a legion for the campaign
3. Add centuries with appropriate agent types and counts
4. Submit tasks in batch for parallel execution
5. Use `broadcast` to send instructions to working agents
6. Monitor progress via `fleet_status`
\"\"\"
"""


def print_skill() -> None:
    """Print the skill TOML to stdout for piping into a file."""
    print(SKILL_TOML)


if __name__ == "__main__":
    print_skill()
