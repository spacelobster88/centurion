"""FastAPI router for the Centurion REST API."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from centurion.api.schemas import (
    AddCenturyRequest,
    BroadcastRequest,
    BroadcastResponse,
    CenturyResponse,
    CloseableSessionEntry,
    CloseableSessionsResponse,
    ComponentStatus,
    FleetStatusResponse,
    HealthResponse,
    LegionaryResponse,
    LegionResponse,
    RaiseLegionRequest,
    ReadinessResponse,
    ScaleRequest,
    SentinelStatusResponse,
    SubmitBatchRequest,
    SubmitTaskRequest,
    TaskResponse,
)
from centurion.core.century import CenturyConfig
from centurion.core.engine import Centurion
from centurion.core.legion import LegionQuota
from centurion.core.session_registry import SessionRegistry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/centurion", tags=["centurion"])
health_router = APIRouter(tags=["health"])


def _build_recommended_actions(
    pressure,
    *,
    session_registry: SessionRegistry | None = None,
    scheduler: Any | None = None,
) -> list[str]:
    """Build a list of recommended action strings based on memory pressure.

    Returns an empty list when pressure is NORMAL.
    Returns session-close suggestions and operational hints at WARN/CRITICAL.
    """
    from centurion.core.scheduler import MemoryPressureLevel

    if pressure == MemoryPressureLevel.NORMAL:
        return []

    actions: list[str] = []

    # Suggest closing idle sessions that are closeable.
    if session_registry is not None:
        now = time.time()
        all_sessions = session_registry.get_all_sessions()
        for session_id, meta in all_sessions.items():
            info = session_registry.closeable_info(session_id)
            if not info["closeable"]:
                continue
            idle_seconds = int(now - meta.last_active)
            actions.append(
                f"Close idle session {session_id} "
                f"(idle {idle_seconds}s, no bg children)"
            )

    # Batch size reduction.
    if pressure == MemoryPressureLevel.CRITICAL:
        actions.append("Reduce batch size to 1")
    else:
        actions.append("Reduce batch size")

    # Critical-only actions.
    if pressure == MemoryPressureLevel.CRITICAL:
        actions.append("Run 'sudo purge' to reclaim memory")
        actions.append("Consider stopping non-essential background tasks")

    return actions


# =========================================================================
# Health check endpoints (mounted at root, outside /api/centurion)
# =========================================================================

@health_router.get(
    "/health",
    response_model=HealthResponse,
    response_model_exclude_none=True,
)
async def liveness() -> HealthResponse:
    """Liveness probe. Returns 200 if the process is running."""
    return HealthResponse()


@health_router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    response_model_exclude_none=True,
)
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe. Checks all critical subsystems."""
    components: dict[str, ComponentStatus] = {}

    # --- Engine ---
    engine = getattr(request.app.state, "centurion", None)
    if engine is None:
        components["engine"] = ComponentStatus(
            status="error", error="Engine not initialized"
        )
    else:
        shutting_down = getattr(engine, "_shutting_down", False)
        components["engine"] = ComponentStatus(
            status="error" if shutting_down else "ok",
            error="Engine is shutting down" if shutting_down else None,
            legions=len(engine.legions),
            shutting_down=shutting_down,
        )

    # --- Scheduler ---
    scheduler = getattr(engine, "scheduler", None) if engine else None
    if scheduler is None:
        components["scheduler"] = ComponentStatus(
            status="error", error="Scheduler not initialized"
        )
    else:
        try:
            system = scheduler.probe_system()
            components["scheduler"] = ComponentStatus(
                status="ok",
                active_agents=scheduler.active_agents,
                recommended_max=scheduler.recommended_max_agents(),
                ram_available_conservative_mb=system.ram_available_conservative_mb,
                ram_compressor_mb=system.ram_compressor_mb,
                memory_pressure=system.memory_pressure.value,
            )
        except Exception as exc:
            components["scheduler"] = ComponentStatus(
                status="error", error=str(exc)
            )

    # --- EventBus ---
    event_bus = getattr(engine, "event_bus", None) if engine else None
    if event_bus is None:
        components["event_bus"] = ComponentStatus(
            status="error", error="EventBus not initialized"
        )
    else:
        components["event_bus"] = ComponentStatus(
            status="ok",
            subscribers=len(event_bus._subscribers),
            history_size=len(event_bus._history),
        )

    # --- Sentinel ---
    sentinel = getattr(engine, "sentinel", None) if engine else None
    if sentinel is not None:
        components["sentinel"] = ComponentStatus(
            status="ok" if sentinel.config.enabled else "ok",
        )

    # --- Database ---
    db = getattr(engine, "db", None) if engine else None
    if db is None:
        components["database"] = ComponentStatus(
            status="error", error="Database not configured"
        )
    else:
        components["database"] = ComponentStatus(status="ok")

    # --- Aggregate ---
    all_ok = all(c.status == "ok" for c in components.values())
    response = ReadinessResponse(
        status="ready" if all_ok else "not_ready",
        components=components,
    )
    status_code = 200 if all_ok else 503
    return JSONResponse(
        content=response.model_dump(exclude_none=True),
        status_code=status_code,
    )


async def request_logging_middleware(request: Request, call_next):
    """Log every request with method, path, status_code, and duration_ms."""
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(
        log_level,
        "request: method=%s path=%s status=%d duration_ms=%.1f",
        request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


def _engine(request: Request) -> Centurion:
    """Extract the Centurion engine from application state."""
    return request.app.state.centurion


# =========================================================================
# Fleet
# =========================================================================

@router.get("/status", response_model=FleetStatusResponse)
async def fleet_status(request: Request) -> dict[str, Any]:
    """Return macro-level fleet status."""
    engine = _engine(request)
    return engine.fleet_status()


@router.get("/hardware")
async def hardware_status(request: Request) -> dict[str, Any]:
    """Return hardware resources and scheduling state."""
    engine = _engine(request)
    report = engine.hardware_report()

    # Determine memory pressure from the report.
    from centurion.core.scheduler import MemoryPressureLevel
    pressure_str = report.get("system", {}).get("memory_pressure", "normal")
    try:
        pressure = MemoryPressureLevel(pressure_str)
    except ValueError:
        pressure = MemoryPressureLevel.NORMAL

    registry = getattr(engine, "session_registry", None)
    scheduler = getattr(engine, "scheduler", None)

    report["recommended_actions"] = _build_recommended_actions(
        pressure, session_registry=registry, scheduler=scheduler,
    )
    return report


# =========================================================================
# Broadcast
# =========================================================================

@router.post("/broadcast", response_model=BroadcastResponse)
async def broadcast(request: Request, body: BroadcastRequest) -> dict[str, Any]:
    """Broadcast a message to agents. Target all, a specific legion, or a century."""
    engine = _engine(request)
    try:
        result = await engine.broadcast(
            message=body.message,
            target=body.target,
            target_id=body.target_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result


# =========================================================================
# Legions
# =========================================================================

@router.post("/legions", response_model=LegionResponse, status_code=201)
async def raise_legion(request: Request, body: RaiseLegionRequest) -> dict[str, Any]:
    """Create (raise) a new legion."""
    engine = _engine(request)
    quota = LegionQuota(**body.quota) if body.quota else None
    try:
        legion = await engine.raise_legion(
            legion_id=body.legion_id,
            name=body.name,
            quota=quota,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return legion.status_report()


@router.get("/legions", response_model=list[LegionResponse])
async def list_legions(request: Request) -> list[dict[str, Any]]:
    """List all active legions."""
    engine = _engine(request)
    return [legion.status_report() for legion in engine.legions.values()]


@router.get("/legions/{legion_id}", response_model=LegionResponse)
async def get_legion(request: Request, legion_id: str) -> dict[str, Any]:
    """Get details for a specific legion."""
    engine = _engine(request)
    try:
        legion = engine.get_legion(legion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return legion.status_report()


@router.delete("/legions/{legion_id}")
async def disband_legion(request: Request, legion_id: str) -> dict:
    """Disband (delete) a legion and terminate all its agents."""
    engine = _engine(request)
    try:
        await engine.disband_legion(legion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "disbanded", "legion_id": legion_id}


# =========================================================================
# Centuries
# =========================================================================

@router.post(
    "/legions/{legion_id}/centuries",
    response_model=CenturyResponse,
    status_code=201,
)
async def add_century(
    request: Request, legion_id: str, body: AddCenturyRequest
) -> dict[str, Any]:
    """Add a century to an existing legion."""
    engine = _engine(request)
    try:
        legion = engine.get_legion(legion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    config = CenturyConfig(
        agent_type_name=body.agent_type,
        agent_type_config=body.agent_type_config,
        min_legionaries=body.min_legionaries,
        max_legionaries=body.max_legionaries,
        autoscale=body.autoscale,
        task_timeout=body.task_timeout,
    )
    try:
        century = await legion.add_century(
            century_id=body.century_id,
            config=config,
            registry=engine.registry,
            scheduler=engine.scheduler,
            event_bus=engine.event_bus,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return century.status_report()


@router.get("/centuries/{century_id}", response_model=CenturyResponse)
async def get_century(request: Request, century_id: str) -> dict[str, Any]:
    """Get details for a specific century."""
    engine = _engine(request)
    for legion in engine.legions.values():
        if century_id in legion.centuries:
            return legion.centuries[century_id].status_report()
    raise HTTPException(status_code=404, detail=f"Century {century_id!r} not found")


@router.post("/centuries/{century_id}/scale", response_model=CenturyResponse)
async def scale_century(
    request: Request, century_id: str, body: ScaleRequest
) -> dict[str, Any]:
    """Manually scale a century to a target legionary count."""
    engine = _engine(request)
    for legion in engine.legions.values():
        if century_id in legion.centuries:
            century = legion.centuries[century_id]
            await century.scale_to(body.target_count)
            return century.status_report()
    raise HTTPException(status_code=404, detail=f"Century {century_id!r} not found")


@router.delete("/centuries/{century_id}")
async def remove_century(request: Request, century_id: str) -> dict:
    """Remove and dismiss a century."""
    engine = _engine(request)
    for legion in engine.legions.values():
        if century_id in legion.centuries:
            await legion.remove_century(century_id)
            return {"status": "dismissed", "century_id": century_id}
    raise HTTPException(status_code=404, detail=f"Century {century_id!r} not found")


# =========================================================================
# Tasks
# =========================================================================

@router.post(
    "/centuries/{century_id}/tasks",
    response_model=TaskResponse,
    status_code=201,
)
async def submit_task_to_century(
    request: Request, century_id: str, body: SubmitTaskRequest
) -> dict[str, Any]:
    """Submit a task to a specific century."""
    engine = _engine(request)
    for legion in engine.legions.values():
        if century_id in legion.centuries:
            century = legion.centuries[century_id]
            task_id = body.task_id or f"task-{uuid.uuid4().hex[:8]}"
            await century.submit_task(
                prompt=body.prompt,
                priority=body.priority,
                task_id=task_id,
            )
            return {
                "task_id": task_id,
                "century_id": century_id,
                "legion_id": legion.id,
                "prompt": body.prompt,
                "priority": body.priority,
                "status": "pending",
            }
    raise HTTPException(status_code=404, detail=f"Century {century_id!r} not found")


@router.post(
    "/legions/{legion_id}/tasks",
    response_model=list[TaskResponse],
    status_code=201,
)
async def submit_batch_to_legion(
    request: Request, legion_id: str, body: SubmitBatchRequest
) -> list[dict[str, Any]]:
    """Submit a batch of tasks distributed across a legion's centuries."""
    engine = _engine(request)
    try:
        legion = engine.get_legion(legion_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        futures = await legion.submit_batch(
            prompts=body.prompts,
            priority=body.priority,
            distribute=body.distribute,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return [
        {
            "task_id": f"task-{uuid.uuid4().hex[:8]}",
            "century_id": "",
            "legion_id": legion_id,
            "prompt": prompt,
            "priority": body.priority,
            "status": "pending",
        }
        for prompt in body.prompts
    ]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(request: Request, task_id: str) -> dict[str, Any]:
    """Get details for a specific task by ID.

    Searches across all legions/centuries for the task.
    """
    engine = _engine(request)
    # If a DB is attached, query from there
    if hasattr(engine, "db") and engine.db is not None:
        try:
            task = await engine.db.get_task(task_id)
        except Exception as exc:
            logger.error("Database error in get_task: %s", exc)
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")
        if task:
            return task
    raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")


@router.post("/tasks/{task_id}/cancel", status_code=200)
async def cancel_task(request: Request, task_id: str) -> dict[str, str]:
    """Request cancellation of a task."""
    # Task cancellation is best-effort; we mark it cancelled but cannot
    # interrupt an agent mid-execution.
    engine = _engine(request)
    if hasattr(engine, "db") and engine.db is not None:
        try:
            task = await engine.db.get_task(task_id)
        except Exception as exc:
            logger.error("Database error in cancel_task: %s", exc)
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
        if task["status"] in ("completed", "failed", "cancelled"):
            raise HTTPException(
                status_code=409,
                detail=f"Task {task_id!r} is already {task['status']}",
            )
        try:
            await engine.db.update_task(task_id, status="cancelled")
        except Exception as exc:
            logger.error("Database error in cancel_task: %s", exc)
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")
        return {"task_id": task_id, "status": "cancelled"}
    raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")


# =========================================================================
# Legionaries
# =========================================================================

@router.get(
    "/centuries/{century_id}/legionaries",
    response_model=list[LegionaryResponse],
)
async def list_legionaries(
    request: Request, century_id: str
) -> list[dict[str, Any]]:
    """List all legionaries in a century."""
    engine = _engine(request)
    for legion in engine.legions.values():
        if century_id in legion.centuries:
            century = legion.centuries[century_id]
            return [leg.to_dict() for leg in century.legionaries.values()]
    raise HTTPException(status_code=404, detail=f"Century {century_id!r} not found")


@router.get("/legionaries/{legionary_id}", response_model=LegionaryResponse)
async def get_legionary(
    request: Request, legionary_id: str
) -> dict[str, Any]:
    """Get details for a specific legionary by ID."""
    engine = _engine(request)
    for legion in engine.legions.values():
        for century in legion.centuries.values():
            if legionary_id in century.legionaries:
                return century.legionaries[legionary_id].to_dict()
    raise HTTPException(
        status_code=404, detail=f"Legionary {legionary_id!r} not found"
    )


# =========================================================================
# Broadcast
# =========================================================================

@router.post("/broadcast/century/{century_id}", status_code=200)
async def broadcast_to_century(
    request: Request, century_id: str, body: SubmitTaskRequest
) -> dict[str, Any]:
    """Broadcast a message to all legionaries in a century (row)."""
    engine = _engine(request)
    try:
        result = await engine.broadcaster.broadcast_to_century(
            century_id=century_id,
            message=body.prompt,
            wait=False,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result.to_dict()


@router.post("/broadcast/legion/{legion_id}", status_code=200)
async def broadcast_to_legion(
    request: Request, legion_id: str, body: SubmitTaskRequest
) -> dict[str, Any]:
    """Broadcast a message to all legionaries in a legion (column)."""
    engine = _engine(request)
    try:
        result = await engine.broadcaster.broadcast_to_legion(
            legion_id=legion_id,
            message=body.prompt,
            wait=False,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result.to_dict()


@router.post("/broadcast/fleet", status_code=200)
async def broadcast_to_fleet(
    request: Request, body: SubmitTaskRequest
) -> dict[str, Any]:
    """Broadcast a message to all legionaries in the entire fleet."""
    engine = _engine(request)
    result = await engine.broadcaster.broadcast_to_fleet(
        message=body.prompt,
        wait=False,
    )
    return result.to_dict()


# =========================================================================
# Closeable Sessions
# =========================================================================

@router.get(
    "/closeable-sessions",
    response_model=CloseableSessionsResponse,
)
async def closeable_sessions(request: Request) -> CloseableSessionsResponse:
    """Return sessions that are safe to close, sorted by idle_seconds descending."""
    engine = _engine(request)
    registry = getattr(engine, "session_registry", None)

    if registry is None:
        return CloseableSessionsResponse(sessions=[], total=0)

    now = time.time()
    entries: list[CloseableSessionEntry] = []

    all_sessions = registry.get_all_sessions()
    for session_id, meta in all_sessions.items():
        info = registry.closeable_info(session_id)
        if not info["closeable"]:
            continue

        idle_seconds = now - meta.last_active
        entries.append(
            CloseableSessionEntry(
                session_id=session_id,
                idle_seconds=round(idle_seconds, 1),
                reason=info["reason"],
                session_type=meta.session_type,
            )
        )

    # Sort by idle_seconds descending (most idle first).
    entries.sort(key=lambda e: e.idle_seconds, reverse=True)

    return CloseableSessionsResponse(sessions=entries, total=len(entries))


# =========================================================================
# Recommend
# =========================================================================

@router.post("/purge")
async def purge_memory(request: Request) -> dict[str, Any]:
    """Trigger macOS memory purge (sudo -n purge). Best-effort, non-blocking."""
    import platform
    import subprocess as sp

    if platform.system() != "Darwin":
        return {"status": "skipped", "reason": "not macOS"}
    try:
        result = sp.run(["sudo", "-n", "purge"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return {"status": "ok", "message": "Memory purged"}
        return {"status": "failed", "returncode": result.returncode, "stderr": result.stderr.decode()[:200]}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@router.get("/recommend")
async def recommend(request: Request) -> dict[str, Any]:
    """Get hardware-aware deployment recommendation."""
    from centurion.__main__ import _build_recommendation
    return _build_recommendation()


# =========================================================================
# Agent types
# =========================================================================

@router.get("/agent-types")
async def list_agent_types(request: Request) -> dict[str, Any]:
    """List all registered agent types."""
    engine = _engine(request)
    types = engine.registry.list_types()
    return {
        "agent_types": [
            {
                "name": name,
                "class": cls.__name__,
                "module": cls.__module__,
            }
            for name, cls in types.items()
        ]
    }


# =========================================================================
# Sentinel
# =========================================================================

@router.get("/sentinel", response_model=SentinelStatusResponse)
async def sentinel_status(request: Request) -> SentinelStatusResponse:
    """Return sentinel service status and kill metrics."""
    engine = _engine(request)
    sentinel = getattr(engine, "sentinel", None)
    if sentinel is None:
        return SentinelStatusResponse(
            enabled=False, running=False, config={}, metrics={},
        )
    return SentinelStatusResponse(
        enabled=sentinel.config.enabled,
        running=sentinel.is_running,
        config={
            "scan_interval_seconds": sentinel.config.scan_interval_seconds,
            "idle_threshold_seconds": sentinel.config.idle_threshold_seconds,
            "max_runtime_seconds": sentinel.config.max_runtime_seconds,
            "dry_run": sentinel.config.dry_run,
        },
        metrics=sentinel.metrics.to_dict(),
    )


@router.post("/sentinel/scan")
async def sentinel_scan(request: Request) -> dict[str, Any]:
    """Trigger an immediate sentinel scan. Returns kill results."""
    engine = _engine(request)
    sentinel = getattr(engine, "sentinel", None)
    if sentinel is None:
        raise HTTPException(status_code=503, detail="Sentinel not initialized")

    kills = await sentinel.scan_once()
    return {
        "kills": [
            {
                "session_id": k.session_id,
                "session_type": k.session_type,
                "reason": k.reason,
                "idle_seconds": round(k.idle_seconds, 1),
                "runtime_seconds": round(k.runtime_seconds, 1),
                "dry_run": k.dry_run,
            }
            for k in kills
        ],
        "total": len(kills),
    }
