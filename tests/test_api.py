"""Integration tests for the Centurion REST API."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from centurion.api.router import router
from centurion.api.websocket import websocket_endpoint
from centurion.config import CenturionConfig
from centurion.core.engine import Centurion
from tests.conftest import MockAgentType


def _make_app_with_engine() -> tuple[FastAPI, Centurion]:
    """Build a test app with engine pre-attached (no lifespan needed)."""
    app = FastAPI()
    app.include_router(router)
    app.add_api_websocket_route("/api/centurion/events", websocket_endpoint)
    config = CenturionConfig()
    engine = Centurion(config=config)
    engine.registry.register("mock", MockAgentType)
    # Bypass real hardware checks in tests — the scheduler would reject
    # spawns on machines with low available RAM.
    engine.scheduler.can_schedule = lambda agent_type: True
    engine.scheduler.available_slots = lambda agent_type: 100
    app.state.centurion = engine
    return app, engine


@pytest.fixture
async def client():
    app, engine = _make_app_with_engine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.shutdown()


# =========================================================================
# Fleet
# =========================================================================


@pytest.mark.asyncio
async def test_fleet_status(client):
    resp = await client.get("/api/centurion/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_legions"] == 0
    assert data["total_centuries"] == 0
    assert "hardware" in data


@pytest.mark.asyncio
async def test_hardware_status(client):
    resp = await client.get("/api/centurion/hardware")
    assert resp.status_code == 200
    data = resp.json()
    assert "system" in data
    assert "cpu_count" in data["system"]


# =========================================================================
# Legions CRUD
# =========================================================================


@pytest.mark.asyncio
async def test_raise_legion(client):
    resp = await client.post(
        "/api/centurion/legions",
        json={"name": "Test Legion", "legion_id": "test-alpha"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["legion_id"] == "test-alpha"
    assert data["name"] == "Test Legion"


@pytest.mark.asyncio
async def test_raise_duplicate_legion(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "First", "legion_id": "dupe-legion"},
    )
    resp = await client.post(
        "/api/centurion/legions",
        json={"name": "Second", "legion_id": "dupe-legion"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_legions(client):
    await client.post("/api/centurion/legions", json={"name": "A", "legion_id": "la"})
    await client.post("/api/centurion/legions", json={"name": "B", "legion_id": "lb"})
    resp = await client.get("/api/centurion/legions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    ids = {l["legion_id"] for l in data}
    assert ids == {"la", "lb"}


@pytest.mark.asyncio
async def test_get_legion(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "Detail", "legion_id": "detail-leg"},
    )
    resp = await client.get("/api/centurion/legions/detail-leg")
    assert resp.status_code == 200
    assert resp.json()["legion_id"] == "detail-leg"


@pytest.mark.asyncio
async def test_get_legion_not_found(client):
    resp = await client.get("/api/centurion/legions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_disband_legion(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "ToDie", "legion_id": "doomed"},
    )
    resp = await client.delete("/api/centurion/legions/doomed")
    assert resp.status_code == 200
    assert resp.json()["status"] == "disbanded"

    resp = await client.get("/api/centurion/legions/doomed")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_disband_nonexistent_legion(client):
    resp = await client.delete("/api/centurion/legions/ghost")
    assert resp.status_code == 404


# =========================================================================
# Centuries CRUD
# =========================================================================


@pytest.mark.asyncio
async def test_add_century(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "CenturyTest", "legion_id": "cent-leg"},
    )
    resp = await client.post(
        "/api/centurion/legions/cent-leg/centuries",
        json={
            "century_id": "mock-squad",
            "agent_type": "mock",
            "min_legionaries": 2,
            "max_legionaries": 5,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["century_id"] == "mock-squad"
    assert data["agent_type"] == "mock"
    assert data["legionaries_count"] == 2


@pytest.mark.asyncio
async def test_add_century_to_nonexistent_legion(client):
    resp = await client.post(
        "/api/centurion/legions/nope/centuries",
        json={"agent_type": "mock"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_century(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "GetCent", "legion_id": "gc-leg"},
    )
    await client.post(
        "/api/centurion/legions/gc-leg/centuries",
        json={"century_id": "gc-cent", "agent_type": "mock", "min_legionaries": 1},
    )
    resp = await client.get("/api/centurion/centuries/gc-cent")
    assert resp.status_code == 200
    assert resp.json()["century_id"] == "gc-cent"


@pytest.mark.asyncio
async def test_get_century_not_found(client):
    resp = await client.get("/api/centurion/centuries/missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_scale_century(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "Scale", "legion_id": "sc-leg"},
    )
    await client.post(
        "/api/centurion/legions/sc-leg/centuries",
        json={
            "century_id": "sc-cent",
            "agent_type": "mock",
            "min_legionaries": 1,
            "max_legionaries": 5,
        },
    )
    resp = await client.post(
        "/api/centurion/centuries/sc-cent/scale",
        json={"target_count": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["legionaries_count"] == 3


@pytest.mark.asyncio
async def test_remove_century(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "Remove", "legion_id": "rm-leg"},
    )
    await client.post(
        "/api/centurion/legions/rm-leg/centuries",
        json={"century_id": "rm-cent", "agent_type": "mock", "min_legionaries": 1},
    )
    resp = await client.delete("/api/centurion/centuries/rm-cent")
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"

    resp = await client.get("/api/centurion/centuries/rm-cent")
    assert resp.status_code == 404


# =========================================================================
# Tasks
# =========================================================================


@pytest.mark.asyncio
async def test_submit_task_to_century(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "TaskLeg", "legion_id": "task-leg"},
    )
    await client.post(
        "/api/centurion/legions/task-leg/centuries",
        json={"century_id": "task-cent", "agent_type": "mock", "min_legionaries": 1},
    )
    resp = await client.post(
        "/api/centurion/centuries/task-cent/tasks",
        json={"prompt": "Hello world", "priority": 3},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["century_id"] == "task-cent"
    assert data["prompt"] == "Hello world"
    assert data["priority"] == 3
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_submit_task_not_found(client):
    resp = await client.post(
        "/api/centurion/centuries/missing/tasks",
        json={"prompt": "Hello"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submit_batch_to_legion(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "Batch", "legion_id": "batch-leg"},
    )
    await client.post(
        "/api/centurion/legions/batch-leg/centuries",
        json={"century_id": "b-cent", "agent_type": "mock", "min_legionaries": 1},
    )
    resp = await client.post(
        "/api/centurion/legions/batch-leg/tasks",
        json={"prompts": ["A", "B", "C"], "priority": 2},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 3


@pytest.mark.asyncio
async def test_submit_batch_to_nonexistent_legion(client):
    resp = await client.post(
        "/api/centurion/legions/nope/tasks",
        json={"prompts": ["test"]},
    )
    assert resp.status_code == 404


# =========================================================================
# Legionaries
# =========================================================================


@pytest.mark.asyncio
async def test_list_legionaries(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "LegList", "legion_id": "ll-leg"},
    )
    await client.post(
        "/api/centurion/legions/ll-leg/centuries",
        json={"century_id": "ll-cent", "agent_type": "mock", "min_legionaries": 3},
    )
    resp = await client.get("/api/centurion/centuries/ll-cent/legionaries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all("id" in leg for leg in data)


@pytest.mark.asyncio
async def test_list_legionaries_not_found(client):
    resp = await client.get("/api/centurion/centuries/ghost/legionaries")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_legionary(client):
    await client.post(
        "/api/centurion/legions",
        json={"name": "LegGet", "legion_id": "lg-leg"},
    )
    await client.post(
        "/api/centurion/legions/lg-leg/centuries",
        json={"century_id": "lg-cent", "agent_type": "mock", "min_legionaries": 1},
    )
    # Get the legionary ID from list
    resp = await client.get("/api/centurion/centuries/lg-cent/legionaries")
    leg_id = resp.json()[0]["id"]

    resp = await client.get(f"/api/centurion/legionaries/{leg_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == leg_id


@pytest.mark.asyncio
async def test_get_legionary_not_found(client):
    resp = await client.get("/api/centurion/legionaries/nobody")
    assert resp.status_code == 404


# =========================================================================
# Agent Types
# =========================================================================


@pytest.mark.asyncio
async def test_list_agent_types(client):
    resp = await client.get("/api/centurion/agent-types")
    assert resp.status_code == 200
    data = resp.json()
    names = {t["name"] for t in data["agent_types"]}
    assert "claude_cli" in names
    assert "claude_api" in names
    assert "shell" in names
    assert "mock" in names


# =========================================================================
# Full lifecycle
# =========================================================================


@pytest.mark.asyncio
async def test_full_lifecycle(client):
    """End-to-end: raise legion -> add century -> submit task -> check status -> disband."""
    # Raise legion
    resp = await client.post(
        "/api/centurion/legions",
        json={"name": "E2E", "legion_id": "e2e-legion"},
    )
    assert resp.status_code == 201

    # Add century
    resp = await client.post(
        "/api/centurion/legions/e2e-legion/centuries",
        json={
            "century_id": "e2e-cent",
            "agent_type": "mock",
            "min_legionaries": 2,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["legionaries_count"] == 2

    # Submit task
    resp = await client.post(
        "/api/centurion/centuries/e2e-cent/tasks",
        json={"prompt": "E2E test task"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"

    # Check fleet status
    resp = await client.get("/api/centurion/status")
    data = resp.json()
    assert data["total_legions"] == 1
    assert data["total_centuries"] == 1
    assert data["total_legionaries"] == 2

    # Scale up
    resp = await client.post(
        "/api/centurion/centuries/e2e-cent/scale",
        json={"target_count": 4},
    )
    assert resp.status_code == 200
    assert resp.json()["legionaries_count"] == 4

    # Disband
    resp = await client.delete("/api/centurion/legions/e2e-legion")
    assert resp.status_code == 200

    # Verify gone
    resp = await client.get("/api/centurion/status")
    assert resp.json()["total_legions"] == 0
