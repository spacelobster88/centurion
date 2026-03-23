"""MCP server that proxies to the Centurion REST API."""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("centurion")

API_BASE = os.getenv("CENTURION_API_BASE", "http://localhost:8100/api/centurion")
DEFAULT_TIMEOUT = int(os.getenv("CENTURION_MCP_TIMEOUT", "30"))


def _request(method: str, path: str, timeout: int = DEFAULT_TIMEOUT, **kwargs) -> dict | list:
    try:
        r = httpx.request(method, f"{API_BASE}{path}", timeout=timeout, **kwargs)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        return {"error": f"Cannot connect to Centurion API at {API_BASE}. Is it running?"}
    except httpx.TimeoutException:
        return {"error": f"Request to {path} timed out after {timeout}s"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"}


def _get(path: str, params: dict | None = None) -> dict | list:
    return _request("GET", path, params=params)


def _post(path: str, json: dict | None = None) -> dict | list:
    return _request("POST", path, json=json)


def _delete(path: str) -> dict:
    return _request("DELETE", path)


# =========================================================================
# Fleet
# =========================================================================

@mcp.tool()
def fleet_status() -> dict:
    """Get macro-level fleet status including all legions, centuries, and legionary counts.

    Returns an overview of the entire Centurion fleet with legion details,
    century breakdowns, and hardware resource information.
    """
    return _get("/status")


@mcp.tool()
def hardware_status() -> dict:
    """Get hardware resources and scheduling state.

    Returns CPU, memory, and other resource information used by the
    Centurion scheduler for placement decisions.
    """
    return _get("/hardware")


# =========================================================================
# Legions
# =========================================================================

@mcp.tool()
def raise_legion(name: str, legion_id: str | None = None, quota: dict | None = None) -> dict:
    """Create (raise) a new legion.

    Args:
        name: Human-readable name for the legion
        legion_id: Optional explicit ID for the legion (auto-generated if omitted)
        quota: Optional resource quota dict with keys like max_centuries, max_legionaries, etc.
    """
    payload: dict[str, Any] = {"name": name}
    if legion_id is not None:
        payload["legion_id"] = legion_id
    if quota is not None:
        payload["quota"] = quota
    return _post("/legions", json=payload)


@mcp.tool()
def list_legions() -> list[dict]:
    """List all active legions with their status and century information."""
    return _get("/legions")


@mcp.tool()
def get_legion(legion_id: str) -> dict:
    """Get details for a specific legion.

    Args:
        legion_id: The unique identifier of the legion
    """
    return _get(f"/legions/{legion_id}")


@mcp.tool()
def disband_legion(legion_id: str) -> dict:
    """Disband (delete) a legion and terminate all its agents.

    This will stop all centuries and legionaries belonging to the legion.

    Args:
        legion_id: The unique identifier of the legion to disband
    """
    return _delete(f"/legions/{legion_id}")


# =========================================================================
# Centuries
# =========================================================================

@mcp.tool()
def add_century(
    legion_id: str,
    agent_type: str = "claude_cli",
    century_id: str | None = None,
    agent_type_config: dict | None = None,
    min_legionaries: int = 1,
    max_legionaries: int = 10,
    autoscale: bool = True,
    task_timeout: float = 300.0,
) -> dict:
    """Add a century (agent pool) to an existing legion.

    Args:
        legion_id: The legion to add the century to
        agent_type: Agent type name (e.g. 'claude_cli')
        century_id: Optional explicit ID for the century (auto-generated if omitted)
        agent_type_config: Optional configuration dict passed to the agent type
        min_legionaries: Minimum number of agent instances to maintain
        max_legionaries: Maximum number of agent instances allowed
        autoscale: Whether to automatically scale based on queue depth
        task_timeout: Maximum seconds a task may run before being killed
    """
    payload: dict[str, Any] = {
        "agent_type": agent_type,
        "min_legionaries": min_legionaries,
        "max_legionaries": max_legionaries,
        "autoscale": autoscale,
        "task_timeout": task_timeout,
    }
    if century_id is not None:
        payload["century_id"] = century_id
    if agent_type_config is not None:
        payload["agent_type_config"] = agent_type_config
    return _post(f"/legions/{legion_id}/centuries", json=payload)


@mcp.tool()
def get_century(century_id: str) -> dict:
    """Get details for a specific century including legionary counts and queue depth.

    Args:
        century_id: The unique identifier of the century
    """
    return _get(f"/centuries/{century_id}")


@mcp.tool()
def scale_century(century_id: str, target_count: int) -> dict:
    """Manually scale a century to a target legionary count.

    Args:
        century_id: The unique identifier of the century to scale
        target_count: Desired number of legionary instances
    """
    return _post(f"/centuries/{century_id}/scale", json={"target_count": target_count})


@mcp.tool()
def remove_century(century_id: str) -> dict:
    """Remove and dismiss a century, terminating all its legionaries.

    Args:
        century_id: The unique identifier of the century to remove
    """
    return _delete(f"/centuries/{century_id}")


# =========================================================================
# Tasks
# =========================================================================

@mcp.tool()
def submit_task(century_id: str, prompt: str, priority: int = 5, task_id: str | None = None) -> dict:
    """Submit a task to a specific century for execution.

    Args:
        century_id: The century to submit the task to
        prompt: The task prompt or instruction for the agent
        priority: Task priority (1=highest, 10=lowest, default 5)
        task_id: Optional explicit task ID (auto-generated if omitted)
    """
    payload: dict[str, Any] = {"prompt": prompt, "priority": priority}
    if task_id is not None:
        payload["task_id"] = task_id
    return _post(f"/centuries/{century_id}/tasks", json=payload)


@mcp.tool()
def submit_batch(
    legion_id: str,
    prompts: list[str],
    priority: int = 5,
    distribute: str = "round_robin",
) -> list[dict]:
    """Submit a batch of tasks distributed across a legion's centuries.

    Args:
        legion_id: The legion to distribute tasks across
        prompts: List of task prompts to submit
        priority: Task priority for all tasks (1=highest, 10=lowest, default 5)
        distribute: Distribution strategy ('round_robin' or 'least_loaded')
    """
    payload: dict[str, Any] = {
        "prompts": prompts,
        "priority": priority,
        "distribute": distribute,
    }
    return _post(f"/legions/{legion_id}/tasks", json=payload)


@mcp.tool()
def get_task(task_id: str) -> dict:
    """Get details for a specific task by ID.

    Searches across all legions and centuries for the task.

    Args:
        task_id: The unique identifier of the task
    """
    return _get(f"/tasks/{task_id}")


@mcp.tool()
def cancel_task(task_id: str) -> dict:
    """Request cancellation of a task.

    Cancellation is best-effort; running agents cannot be interrupted mid-execution.

    Args:
        task_id: The unique identifier of the task to cancel
    """
    return _post(f"/tasks/{task_id}/cancel")


# =========================================================================
# Legionaries
# =========================================================================

@mcp.tool()
def list_legionaries(century_id: str) -> list[dict]:
    """List all legionaries (agent instances) in a century.

    Args:
        century_id: The century to list legionaries for
    """
    return _get(f"/centuries/{century_id}/legionaries")


@mcp.tool()
def get_legionary(legionary_id: str) -> dict:
    """Get details for a specific legionary by ID.

    Returns status, current task, and performance statistics.

    Args:
        legionary_id: The unique identifier of the legionary
    """
    return _get(f"/legionaries/{legionary_id}")


# =========================================================================
# Agent types
# =========================================================================

@mcp.tool()
def list_agent_types() -> dict:
    """List all registered agent types available for creating centuries.

    Returns names, class names, and module paths for each agent type.
    """
    return _get("/agent-types")


# =========================================================================
# Broadcast
# =========================================================================

@mcp.tool()
def broadcast(message: str, target: str = "all", target_id: str | None = None) -> dict:
    """Broadcast a message/instruction to working agents.

    Supports targeting all agents, a specific legion, or a specific century.

    Args:
        message: The message or instruction to broadcast
        target: Scope of the broadcast ('all', 'legion', or 'century')
        target_id: Required when target is 'legion' or 'century' -- the ID of the target
    """
    payload: dict[str, Any] = {"message": message, "target": target}
    if target_id is not None:
        payload["target_id"] = target_id
    return _post("/broadcast", json=payload)


@mcp.tool()
def recommend() -> dict:
    """Get hardware-aware deployment recommendation.

    Probes the system's CPU, RAM, and load, then returns recommendations
    for how many agents of each type can run concurrently.
    """
    return _get("/recommend")


if __name__ == "__main__":
    mcp.run()
