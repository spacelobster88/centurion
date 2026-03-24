"""A2A Agent Card — discovery metadata for the Centurion fleet.

Implements the A2A Agent Card specification so other agents can discover
Centurion's capabilities via `/.well-known/agent.json`.
"""

from __future__ import annotations

from typing import Any


def build_agent_card(
    base_url: str = "http://localhost:8100",
    version: str = "0.1.0",
) -> dict[str, Any]:
    """Build the A2A Agent Card for the Centurion fleet.

    Returns a JSON-serializable dict conforming to the A2A Agent Card spec.
    """
    return {
        "name": "Centurion",
        "description": (
            "AI Agent Orchestration Engine — spawn and command an army of "
            "AI agents with Roman military precision. Supports fleet-wide "
            "task distribution, hardware-aware autoscaling, and real-time "
            "event streaming."
        ),
        "url": base_url,
        "version": version,
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "fleet-orchestration",
                "name": "Fleet Orchestration",
                "description": (
                    "Manage legions and centuries of AI agents. Raise legions, muster centuries, and distribute tasks."
                ),
                "tags": ["orchestration", "multi-agent", "fleet"],
                "examples": [
                    "Raise a legion of 10 research agents",
                    "Submit a batch of analysis tasks",
                    "Scale the search squad to 20 agents",
                ],
            },
            {
                "id": "broadcast",
                "name": "Fleet Broadcast",
                "description": ("Broadcast messages to all agents, a specific legion, or a specific century."),
                "tags": ["broadcast", "communication"],
                "examples": [
                    "Broadcast 'switch to summarization mode' to all agents",
                    "Send instruction to legion alpha",
                ],
            },
            {
                "id": "hardware-probe",
                "name": "Hardware Monitoring",
                "description": ("Probe system resources and get scheduling recommendations."),
                "tags": ["monitoring", "hardware"],
                "examples": [
                    "How many agents can this machine support?",
                    "Show current hardware utilization",
                ],
            },
        ],
    }
