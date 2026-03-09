"""Pydantic request/response models for the Centurion REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RaiseLegionRequest(BaseModel):
    """Create a new legion."""
    legion_id: str | None = None
    name: str
    quota: dict[str, Any] | None = None


class AddCenturyRequest(BaseModel):
    """Add a century to a legion."""
    century_id: str | None = None
    agent_type: str = "claude_cli"
    agent_type_config: dict[str, Any] = Field(default_factory=dict)
    min_legionaries: int = 1
    max_legionaries: int = 10
    autoscale: bool = True
    task_timeout: float = 300.0


class SubmitTaskRequest(BaseModel):
    """Submit a single task to a century."""
    prompt: str
    priority: int = 5
    task_id: str | None = None


class SubmitBatchRequest(BaseModel):
    """Submit multiple tasks to a legion for distribution."""
    prompts: list[str]
    priority: int = 5
    distribute: str = "round_robin"


class BroadcastRequest(BaseModel):
    """Broadcast a message to agents."""
    message: str
    target: Literal["all", "legion", "century"] = "all"
    target_id: str | None = None


class ScaleRequest(BaseModel):
    """Manually scale a century."""
    target_count: int


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TaskResponse(BaseModel):
    """A single task."""
    task_id: str
    century_id: str
    legion_id: str | None = None
    legionary_id: str | None = None
    prompt: str = ""
    priority: int = 5
    status: str = "pending"
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    duration_seconds: float | None = None
    submitted_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] | None = None


class LegionaryResponse(BaseModel):
    """Status of a single legionary (agent instance)."""
    id: str
    century_id: str
    agent_type: str | None = None
    status: str
    current_task_id: str | None = None
    created_at: float
    last_active: float
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_duration: float = 0.0
    consecutive_failures: int = 0


class CenturyResponse(BaseModel):
    """Status of a century."""
    century_id: str
    agent_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    legionaries_count: int = 0
    idle: int = 0
    busy: int = 0
    failed: int = 0
    queue_depth: int = 0
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0


class LegionResponse(BaseModel):
    """Status of a legion."""
    legion_id: str
    name: str
    quota: dict[str, Any] = Field(default_factory=dict)
    centuries_count: int = 0
    total_legionaries: int = 0
    centuries: dict[str, CenturyResponse] = Field(default_factory=dict)


class BroadcastResponse(BaseModel):
    """Result of a broadcast operation."""
    target: str
    target_id: str | None = None
    total_delivered: int = 0
    total_failed: int = 0


class FleetStatusResponse(BaseModel):
    """Top-level fleet status."""
    total_legions: int = 0
    total_centuries: int = 0
    total_legionaries: int = 0
    legions: dict[str, LegionResponse] = Field(default_factory=dict)
    hardware: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Health check response models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Liveness probe response."""
    status: Literal["ok"] = "ok"


class ComponentStatus(BaseModel):
    """Status of a single subsystem component."""
    status: Literal["ok", "error"]
    error: str | None = None
    # Optional diagnostic fields (component-specific, ignored if absent)
    latency_ms: float | None = None
    active_agents: int | None = None
    recommended_max: int | None = None
    subscribers: int | None = None
    history_size: int | None = None
    legions: int | None = None
    shutting_down: bool | None = None


class ReadinessResponse(BaseModel):
    """Readiness probe response."""
    status: Literal["ready", "not_ready"]
    components: dict[str, ComponentStatus]
