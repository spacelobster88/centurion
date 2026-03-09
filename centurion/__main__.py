"""Standalone entrypoint for running Centurion as a service.

Usage::

    # One-click quickstart with auto-recommended agents
    centurion quickstart

    # Quickstart with a specific agent type
    centurion quickstart --agent-type claude_api

    # Dry-run: show hardware recommendation without starting
    centurion quickstart --dry-run

    # One-click startup with auto-recommended agent limits
    centurion up

    # Show hardware recommendation without starting
    centurion recommend

    # Start with explicit options
    centurion up --host 0.0.0.0 --port 8100 --max-agents 20

    # Legacy mode (same as 'up')
    python -m centurion --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from centurion.a2a.router import a2a_router
from centurion.api.router import health_router, router
from centurion.api.websocket import websocket_endpoint
from centurion.config import CenturionConfig
from centurion.core.engine import Centurion
from centurion.core.scheduler import CenturionScheduler


# ---------------------------------------------------------------------------
# ASCII banner
# ---------------------------------------------------------------------------

BANNER = r"""
   ______           __              _
  / ____/__  ____  / /___  _______(_)___  ____
 / /   / _ \/ __ \/ __/ / / / ___/ / __ \/ __ \
/ /___/  __/ / / / /_/ /_/ / /  / / /_/ / / / /
\____/\___/_/ /_/\__/\__,_/_/  /_/\____/_/ /_/
"""

QUICKSTART_HEADER = r"""
  ____        _      _        _             _
 / __ \      (_)    | |      | |           | |
| |  | |_   _ _  ___| | _____| |_ __ _ _ __| |_
| |  | | | | | |/ __| |/ / __| __/ _` | '__| __|
| |__| | |_| | | (__|   <\__ \ || (_| | |  | |_
 \___\_\\__,_|_|\___|_|\_\___/\__\__,_|_|   \__|
"""


# ---------------------------------------------------------------------------
# Hardware probing and recommendation
# ---------------------------------------------------------------------------

def _build_recommendation() -> dict:
    """Probe hardware and return a recommendation dict."""
    scheduler = CenturionScheduler()
    hw = scheduler.to_dict()
    system = hw["system"]
    recommended_max = hw["recommended_max_agents"]

    # Per-agent-type breakdown
    from centurion.agent_types.claude_cli import ClaudeCliAgentType
    from centurion.agent_types.claude_api import ClaudeApiAgentType
    from centurion.agent_types.shell import ShellAgentType

    types = {
        "claude_cli": ClaudeCliAgentType(),
        "claude_api": ClaudeApiAgentType(),
        "shell": ShellAgentType(),
    }
    breakdown = {}
    for name, agent in types.items():
        req = agent.resource_requirements().requests
        slots = scheduler.available_slots(agent)
        breakdown[name] = {
            "max_concurrent": slots,
            "cpu_per_agent_m": req.cpu_millicores,
            "ram_per_agent_mb": req.memory_mb,
        }

    return {
        "system": system,
        "recommended_max_agents": recommended_max,
        "per_type": breakdown,
        "suggestion": _suggest_deployment(system, breakdown),
    }


def _suggest_deployment(system: dict, breakdown: dict) -> str:
    """Generate a human-readable deployment suggestion."""
    ram = system.get("ram_available_mb", 0)
    cpus = system.get("cpu_count", 1)
    cli_max = breakdown["claude_cli"]["max_concurrent"]
    api_max = breakdown["claude_api"]["max_concurrent"]

    if ram < 2048:
        return (
            f"Low memory ({ram} MB available). Recommend max {min(cli_max, 2)} "
            f"claude_cli agents or {min(api_max, 5)} claude_api agents."
        )
    if ram < 8192:
        return (
            f"Moderate resources ({cpus} CPUs, {ram} MB RAM). "
            f"Recommend {min(cli_max, 5)} claude_cli or {min(api_max, 20)} claude_api agents."
        )
    return (
        f"Ample resources ({cpus} CPUs, {ram} MB RAM). "
        f"Recommend up to {cli_max} claude_cli or {api_max} claude_api agents concurrently."
    )


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def _print_hardware_table(rec: dict) -> None:
    """Print a formatted hardware summary table."""
    s = rec["system"]
    w = 60

    print("=" * w)
    print("  HARDWARE SUMMARY")
    print("-" * w)
    print(f"  {'Platform:':<20s} {s['platform']}")
    print(f"  {'CPU cores:':<20s} {s['cpu_count']}")
    print(f"  {'RAM total:':<20s} {s['ram_total_mb']:,} MB")
    print(f"  {'RAM available:':<20s} {s['ram_available_mb']:,} MB")
    print(f"  {'Load avg (1/5/15):':<20s} {s['load_avg']}")
    print("=" * w)


def _print_recommendation_table(rec: dict, agent_type: str) -> None:
    """Print the per-type breakdown and recommended config."""
    w = 60

    print()
    print("=" * w)
    print("  AGENT CAPACITY BY TYPE")
    print("-" * w)
    print(f"  {'Type':<14s} {'Max':>5s}  {'CPU/agent':>10s}  {'RAM/agent':>10s}")
    print(f"  {'-'*14:<14s} {'-----':>5s}  {'----------':>10s}  {'----------':>10s}")
    for name, info in rec["per_type"].items():
        marker = " <--" if name == agent_type else ""
        print(
            f"  {name:<14s} {info['max_concurrent']:5d}  "
            f"{info['cpu_per_agent_m']:>7d} m  "
            f"{info['ram_per_agent_mb']:>7d} MB{marker}"
        )
    print("=" * w)

    chosen = rec["per_type"].get(agent_type, {})
    max_agents = chosen.get("max_concurrent", rec["recommended_max_agents"])
    min_agents = min(3, max_agents)

    print()
    print("=" * w)
    print("  RECOMMENDED CONFIGURATION")
    print("-" * w)
    print(f"  {'Agent type:':<20s} {agent_type}")
    print(f"  {'Max agents:':<20s} {max_agents}")
    print(f"  {'Min agents:':<20s} {min_agents}")
    print(f"  {'Legion:':<20s} default")
    print(f"  {'Century:':<20s} auto")
    print("-" * w)
    print(f"  >> {rec['suggestion']}")
    print("=" * w)


# ---------------------------------------------------------------------------
# Quickstart logic
# ---------------------------------------------------------------------------

async def _quickstart_bootstrap(
    engine: Centurion,
    agent_type: str,
    rec: dict,
) -> None:
    """Create a default legion with one century using the recommended config."""
    from centurion.core.century import CenturyConfig

    chosen = rec["per_type"].get(agent_type, {})
    max_agents = chosen.get("max_concurrent", rec["recommended_max_agents"])
    min_agents = min(3, max_agents)

    legion = await engine.raise_legion("default", name="Default Legion")
    century_config = CenturyConfig(
        agent_type_name=agent_type,
        min_legionaries=min_agents,
        max_legionaries=max_agents,
    )
    await legion.add_century(
        None,
        century_config,
        engine.registry,
        engine.scheduler,
        engine.event_bus,
    )

    print()
    print(f"  Legion 'default' raised with 1 century of {agent_type} agents")
    print(f"  Scaling range: {min_agents} - {max_agents} agents")
    print()


def cmd_quickstart(args: argparse.Namespace) -> None:
    """One-click quickstart: probe hardware, recommend, and launch."""
    agent_type: str = args.agent_type
    dry_run: bool = args.dry_run

    # Print banner
    print(QUICKSTART_HEADER)

    # Probe and display
    rec = _build_recommendation()
    _print_hardware_table(rec)
    _print_recommendation_table(rec, agent_type)

    if dry_run:
        print()
        print("  [DRY RUN] No server started. Use without --dry-run to launch.")
        print()
        return

    # Set max agents from recommendation
    chosen = rec["per_type"].get(agent_type, {})
    max_agents = chosen.get("max_concurrent", rec["recommended_max_agents"])
    if max_agents:
        os.environ["CENTURION_MAX_AGENTS"] = str(max_agents)

    # Build the app with quickstart lifespan
    def _make_quickstart_lifespan(agent_type_name: str, recommendation: dict):
        @asynccontextmanager
        async def quickstart_lifespan(app: FastAPI) -> AsyncIterator[None]:
            config = CenturionConfig()
            engine = Centurion(config=config)
            app.state.centurion = engine

            # Auto-create the default legion
            await _quickstart_bootstrap(engine, agent_type_name, recommendation)

            print(BANNER)
            print(f"  Centurion is ONLINE  [quickstart mode]")
            print(f"  Listening on http://{args.host}:{args.port}")
            print(f"  Agent type: {agent_type_name}  |  Max agents: {max_agents}")
            print()

            yield
            await engine.shutdown()

        return quickstart_lifespan

    app = FastAPI(
        title="Centurion",
        version="0.1.0",
        lifespan=_make_quickstart_lifespan(agent_type, rec),
    )
    app.include_router(health_router)
    app.include_router(router)
    app.include_router(a2a_router)
    app.add_api_websocket_route("/api/centurion/events", websocket_endpoint)
    uvicorn.run(app, host=args.host, port=args.port)


# ---------------------------------------------------------------------------
# Existing commands
# ---------------------------------------------------------------------------

def cmd_recommend(args: argparse.Namespace) -> None:
    """Print hardware recommendation and exit."""
    rec = _build_recommendation()
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        s = rec["system"]
        print("=" * 60)
        print("  Centurion Hardware Recommendation")
        print("=" * 60)
        print(f"  Platform:       {s['platform']}")
        print(f"  CPU cores:      {s['cpu_count']}")
        print(f"  RAM total:      {s['ram_total_mb']} MB")
        print(f"  RAM available:  {s['ram_available_mb']} MB")
        print(f"  Load avg:       {s['load_avg']}")
        print()
        print(f"  Recommended max agents: {rec['recommended_max_agents']}")
        print()
        print("  Per-type breakdown:")
        for name, info in rec["per_type"].items():
            print(
                f"    {name:12s}  max={info['max_concurrent']:3d}  "
                f"(cpu={info['cpu_per_agent_m']}m, ram={info['ram_per_agent_mb']}MB each)"
            )
        print()
        print(f"  >> {rec['suggestion']}")
        print("=" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = CenturionConfig()
    engine = Centurion(config=config)
    app.state.centurion = engine

    rec = _build_recommendation()
    print(f"\n  Centurion is ready. Recommended max agents: {rec['recommended_max_agents']}")
    print(f"  >> {rec['suggestion']}\n")

    yield
    await engine.shutdown()


def cmd_up(args: argparse.Namespace) -> None:
    """Start the Centurion server."""
    if args.max_agents:
        os.environ["CENTURION_MAX_AGENTS"] = str(args.max_agents)

    app = FastAPI(title="Centurion", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(router)
    app.include_router(a2a_router)
    app.add_api_websocket_route("/api/centurion/events", websocket_endpoint)
    uvicorn.run(app, host=args.host, port=args.port)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Centurion AI Agent Orchestration Engine"
    )
    sub = parser.add_subparsers(dest="command")

    # centurion quickstart
    qs_parser = sub.add_parser(
        "quickstart",
        help="One-click mode: probe hardware, auto-configure, and launch",
    )
    qs_parser.add_argument("--host", default="0.0.0.0")
    qs_parser.add_argument("--port", type=int, default=8100)
    qs_parser.add_argument(
        "--agent-type",
        default="claude_cli",
        choices=["claude_cli", "claude_api", "shell"],
        help="Agent type to deploy (default: claude_cli)",
    )
    qs_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show recommendation only, do not start the server",
    )

    # centurion up
    up_parser = sub.add_parser("up", help="Start the Centurion server (one-click)")
    up_parser.add_argument("--host", default="0.0.0.0")
    up_parser.add_argument("--port", type=int, default=8100)
    up_parser.add_argument(
        "--max-agents", type=int, default=0,
        help="Hard limit on concurrent agents (0 = auto from hardware)",
    )
    up_parser.add_argument(
        "--quickstart",
        action="store_true",
        help="Enable quickstart mode (same as 'centurion quickstart')",
    )
    up_parser.add_argument(
        "--agent-type",
        default="claude_cli",
        choices=["claude_cli", "claude_api", "shell"],
        help="Agent type for quickstart mode (default: claude_cli)",
    )
    up_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show recommendation only, do not start the server",
    )

    # centurion recommend
    rec_parser = sub.add_parser("recommend", help="Show hardware recommendation")
    rec_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Legacy: no subcommand = same as 'up'
    parser.add_argument("--host", default="0.0.0.0", dest="legacy_host")
    parser.add_argument("--port", type=int, default=8100, dest="legacy_port")
    parser.add_argument(
        "--quickstart",
        action="store_true",
        dest="legacy_quickstart",
        help="Enable quickstart mode",
    )
    parser.add_argument(
        "--agent-type",
        default="claude_cli",
        dest="legacy_agent_type",
        help="Agent type for quickstart mode (default: claude_cli)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="legacy_dry_run",
        help="Show recommendation only, do not start the server",
    )

    args = parser.parse_args()

    if args.command == "quickstart":
        cmd_quickstart(args)
    elif args.command == "recommend":
        cmd_recommend(args)
    elif args.command == "up":
        # If --quickstart flag is set on 'up', delegate to quickstart handler
        if args.quickstart or args.dry_run:
            cmd_quickstart(args)
        else:
            cmd_up(args)
    else:
        # Legacy mode: no subcommand
        if getattr(args, "legacy_quickstart", False) or getattr(args, "legacy_dry_run", False):
            args.host = args.legacy_host
            args.port = args.legacy_port
            args.agent_type = args.legacy_agent_type
            args.dry_run = args.legacy_dry_run
            cmd_quickstart(args)
        else:
            args.host = args.legacy_host
            args.port = args.legacy_port
            args.max_agents = 0
            cmd_up(args)


if __name__ == "__main__":
    main()
