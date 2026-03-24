"""One-click integration setup for Centurion.

Provides commands to register Centurion as an MCP server, install the
Claude Code skill, or print configuration snippets for API/A2A integration.

Usage:
    python -m centurion.integrations --setup mcp     # Register as MCP server
    python -m centurion.integrations --setup skill   # Install Claude Code skill
    python -m centurion.integrations --setup a2a     # Print A2A config
    python -m centurion.integrations --setup all     # Do all of the above
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def setup_mcp() -> bool:
    """Register Centurion as a Claude Code MCP server."""
    print("[MCP] Registering Centurion as MCP server...")
    try:
        result = subprocess.run(
            ["claude", "mcp", "add", "centurion", "--", sys.executable, "-m", "centurion.mcp"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print("[MCP] Successfully registered. MCP tools are now available in Claude Code.")
            return True
        else:
            # May already be registered
            if "already exists" in result.stderr.lower():
                print("[MCP] Already registered. Use 'claude mcp remove centurion' to re-register.")
                return True
            print(f"[MCP] Registration failed: {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        print("[MCP] Error: 'claude' CLI not found. Install it first: npm install -g @anthropic-ai/claude-code")
        return False
    except subprocess.TimeoutExpired:
        print("[MCP] Registration timed out.")
        return False


def setup_skill() -> bool:
    """Install the Centurion skill for Claude Code."""
    print("[Skill] Installing Centurion skill...")
    home = Path.home()
    skills_dir = home / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    skill_path = skills_dir / "centurion.toml"
    from centurion.skill import SKILL_TOML

    skill_path.write_text(SKILL_TOML)
    print(f"[Skill] Installed to {skill_path}")
    return True


def setup_a2a() -> bool:
    """Print A2A integration configuration."""
    print("[A2A] Agent-to-Agent Protocol Configuration")
    print("=" * 50)
    host = os.getenv("CENTURION_HOST", "localhost")
    port = os.getenv("CENTURION_PORT", "8100")
    base_url = f"http://{host}:{port}"

    print(f"\nAgent Card URL:  {base_url}/.well-known/agent.json")
    print(f"A2A Endpoint:    {base_url}/a2a")
    print("\nTo discover this agent from another A2A client:")
    print(f"  curl {base_url}/.well-known/agent.json")
    print("\nTo send a task via A2A:")
    print(f"  curl -X POST {base_url}/a2a \\")
    print('    -H "Content-Type: application/json" \\')
    print(
        '    -d \'{"id": "1", "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "Analyze this data"}]}}}\''
    )
    return True


def setup_api() -> bool:
    """Print REST API integration quick reference."""
    print("[API] REST API Quick Reference")
    print("=" * 50)
    host = os.getenv("CENTURION_HOST", "localhost")
    port = os.getenv("CENTURION_PORT", "8100")
    base = f"http://{host}:{port}/api/centurion"

    print(f"\nBase URL: {base}")
    print("\nQuick start:")
    print("  # Check fleet status")
    print(f"  curl {base}/status")
    print("")
    print("  # Check hardware")
    print(f"  curl {base}/hardware")
    print("")
    print("  # Raise a legion")
    print(f'  curl -X POST {base}/legions -H "Content-Type: application/json" \\')
    print('    -d \'{"name": "Research Team"}\'')
    print("")
    print("  # Add a century of Claude CLI agents")
    print(f"  curl -X POST {base}/legions/{{legion_id}}/centuries \\")
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"agent_type": "claude_cli", "min_legionaries": 3, "max_legionaries": 10}\'')
    print("")
    print("  # Submit a task")
    print(f"  curl -X POST {base}/centuries/{{century_id}}/tasks \\")
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"prompt": "Analyze the market trends for AI agents"}\'')
    print("")
    print("  # WebSocket events")
    print(f"  wscat -c ws://{host}:{port}/api/centurion/events")
    print("")
    print("  # Broadcast to all agents")
    print(f'  curl -X POST {base}/broadcast -H "Content-Type: application/json" \\')
    print('    -d \'{"message": "Switch to summarization mode", "target": "all"}\'')
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Centurion Integration Setup")
    parser.add_argument(
        "--setup",
        choices=["mcp", "skill", "a2a", "api", "all"],
        required=True,
        help="Which integration to set up",
    )
    args = parser.parse_args()

    results = {}

    if args.setup in ("mcp", "all"):
        results["mcp"] = setup_mcp()
    if args.setup in ("skill", "all"):
        results["skill"] = setup_skill()
    if args.setup in ("api", "all"):
        results["api"] = setup_api()
    if args.setup in ("a2a", "all"):
        results["a2a"] = setup_a2a()

    if args.setup == "all":
        print("\n" + "=" * 50)
        print("Integration Setup Summary:")
        for name, ok in results.items():
            status = "OK" if ok else "FAILED"
            print(f"  {name.upper():8s} [{status}]")


if __name__ == "__main__":
    main()
