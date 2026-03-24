"""One-click integration setup for Centurion.

Usage::

    # Setup as MCP server for Claude Code
    centurion-setup mcp

    # Generate OpenAPI spec for API clients
    centurion-setup api

    # Generate A2A agent card
    centurion-setup a2a

    # Generate Claude Code skill definition
    centurion-setup skill

    # Setup all integrations at once
    centurion-setup all
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def setup_mcp() -> None:
    """Register Centurion as an MCP server for Claude Code."""
    print("Setting up MCP integration...")

    # Try using claude CLI to add MCP server
    try:
        result = subprocess.run(
            ["claude", "mcp", "add", "centurion", "--", "python", "-m", "centurion.mcp"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print("  [OK] Registered centurion MCP server via Claude CLI")
            print("  Run 'claude mcp list' to verify")
            return
        else:
            print(f"  [WARN] claude CLI returned: {result.stderr.strip()}")
    except FileNotFoundError:
        print("  [WARN] claude CLI not found, writing config manually")
    except Exception as exc:
        print(f"  [WARN] claude CLI error: {exc}")

    # Fallback: write MCP config manually
    config_dir = Path.home() / ".claude"
    config_dir.mkdir(exist_ok=True)
    mcp_config_path = config_dir / "claude_desktop_config.json"

    config = {}
    if mcp_config_path.exists():
        with open(mcp_config_path) as f:
            config = json.load(f)

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["centurion"] = {
        "command": sys.executable,
        "args": ["-m", "centurion.mcp"],
        "env": {
            "CENTURION_API_BASE": os.getenv("CENTURION_API_BASE", "http://localhost:8100/api/centurion"),
        },
    }

    with open(mcp_config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  [OK] MCP config written to {mcp_config_path}")
    print("  Restart Claude Desktop or Claude Code to activate")


def setup_api() -> None:
    """Generate OpenAPI spec from the FastAPI app."""
    print("Generating OpenAPI specification...")
    try:
        from fastapi import FastAPI

        from centurion.api.router import health_router, router

        app = FastAPI(
            title="Centurion",
            version="0.1.0",
            description="AI Agent Orchestration Engine — spawn and command an army of AI agents",
        )
        app.include_router(health_router)
        app.include_router(router)

        spec = app.openapi()
        output_path = Path("openapi.json")
        with open(output_path, "w") as f:
            json.dump(spec, f, indent=2)
        print(f"  [OK] OpenAPI spec written to {output_path}")
        print("  Use this spec to generate client SDKs in any language:")
        print("    npx @openapitools/openapi-generator-cli generate \\")
        print("      -i openapi.json -g python -o ./sdk/python")
        print("    npx @openapitools/openapi-generator-cli generate \\")
        print("      -i openapi.json -g typescript-fetch -o ./sdk/typescript")
    except Exception as exc:
        print(f"  [ERROR] Failed to generate OpenAPI spec: {exc}")


def setup_a2a() -> None:
    """Generate an Agent-to-Agent (A2A) protocol agent card."""
    print("Generating A2A agent card...")

    agent_card = {
        "name": "Centurion",
        "description": "AI Agent Orchestration Engine — spawn and command an army of AI agents with Roman military precision",
        "url": os.getenv("CENTURION_A2A_URL", "http://localhost:8100"),
        "version": "0.1.0",
        "capabilities": {
            "streaming": True,
            "pushNotifications": True,
        },
        "skills": [
            {
                "id": "orchestrate",
                "name": "Agent Orchestration",
                "description": "Spawn, manage, and coordinate multiple AI agents. Supports legion/century/legionary hierarchy, autoscaling, and batch task distribution.",
                "inputModes": ["text"],
                "outputModes": ["text"],
            },
            {
                "id": "broadcast",
                "name": "Fleet Broadcast",
                "description": "Broadcast messages to groups of agents: a single century (row), a legion (column), or the entire fleet.",
                "inputModes": ["text"],
                "outputModes": ["text"],
            },
            {
                "id": "monitor",
                "name": "Fleet Monitoring",
                "description": "Real-time fleet status, hardware utilization, and agent lifecycle events via WebSocket.",
                "inputModes": ["text"],
                "outputModes": ["text"],
            },
        ],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    }

    output_path = Path(".well-known/agent.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(agent_card, f, indent=2)
    print(f"  [OK] A2A agent card written to {output_path}")
    print("  Serve this at /.well-known/agent.json for A2A discovery")


def setup_skill() -> None:
    """Generate a Claude Code skill definition file."""
    print("Generating Claude Code skill definition...")

    skill_def = {
        "name": "centurion",
        "description": "Orchestrate an army of AI agents. Spawn legions, add centuries, submit tasks, broadcast messages, and monitor fleet status.",
        "instructions": """You have access to the Centurion AI Agent Orchestration Engine.

Use the centurion MCP tools to:
- `fleet_status` / `hardware_status` — check current fleet state and hardware
- `recommend` — get hardware-aware deployment recommendations
- `raise_legion` / `disband_legion` — create/destroy deployment groups
- `add_century` / `scale_century` / `remove_century` — manage agent squads
- `submit_task` / `submit_batch` — assign work to agents
- `broadcast_to_century` / `broadcast_to_legion` / `broadcast_to_fleet` — broadcast messages
- `list_legionaries` / `get_legionary` — inspect individual agents

Typical workflow:
1. Check `recommend()` for how many agents the hardware supports
2. `raise_legion(name="my-project")` to create a deployment group
3. `add_century(legion_id, agent_type="claude_cli", min_legionaries=5)` to add agents
4. `submit_batch(legion_id, prompts=[...])` to distribute work
5. Use `broadcast_to_fleet(message)` for fleet-wide coordination
""",
        "trigger": "centurion|legion|century|agent army|orchestrat",
    }

    output_path = Path("centurion.skill.json")
    with open(output_path, "w") as f:
        json.dump(skill_def, f, indent=2)
    print(f"  [OK] Skill definition written to {output_path}")
    print("  Copy this to your Claude Code skills directory to enable the /centurion skill")


def main() -> None:
    parser = argparse.ArgumentParser(description="One-click integration setup for Centurion")
    parser.add_argument(
        "integration",
        choices=["mcp", "api", "a2a", "skill", "all"],
        help="Which integration to set up",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  Centurion Integration Setup")
    print("=" * 50)

    if args.integration in ("mcp", "all"):
        setup_mcp()
        print()
    if args.integration in ("api", "all"):
        setup_api()
        print()
    if args.integration in ("a2a", "all"):
        setup_a2a()
        print()
    if args.integration in ("skill", "all"):
        setup_skill()
        print()

    print("Done!")


if __name__ == "__main__":
    main()
