"""Tests for the WebSocket event streaming and EventBus."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from centurion.api.router import router
from centurion.api.websocket import websocket_endpoint
from centurion.config import CenturionConfig
from centurion.core.engine import Centurion
from centurion.core.events import CenturionEvent, EventBus
from tests.conftest import MockAgentType


def _make_app_with_engine() -> tuple[FastAPI, Centurion]:
    app = FastAPI()
    app.include_router(router)
    app.add_api_websocket_route("/api/centurion/events", websocket_endpoint)
    config = CenturionConfig()
    engine = Centurion(config=config)
    engine.registry.register("mock", MockAgentType)
    app.state.centurion = engine
    return app, engine


# =========================================================================
# EventBus unit tests
# =========================================================================


@pytest.mark.asyncio
async def test_event_bus_subscribe_receive():
    bus = EventBus()
    queue = bus.subscribe()
    await bus.emit("test_event", entity_type="test", entity_id="1")
    received = queue.get_nowait()
    assert received.event_type == "test_event"
    assert received.entity_id == "1"
    bus.unsubscribe(queue)


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    await bus.emit("broadcast", entity_type="test", entity_id="x")
    assert q1.get_nowait().event_type == "broadcast"
    assert q2.get_nowait().event_type == "broadcast"
    bus.unsubscribe(q1)
    bus.unsubscribe(q2)


@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    await bus.emit("after_unsub")
    assert queue.empty()


@pytest.mark.asyncio
async def test_event_bus_recent_events():
    bus = EventBus()
    for i in range(5):
        await bus.emit(f"evt_{i}")
    recent = bus.recent_events(limit=3)
    assert len(recent) == 3
    assert recent[0].event_type == "evt_4"
    assert recent[2].event_type == "evt_2"


@pytest.mark.asyncio
async def test_event_bus_ring_buffer():
    bus = EventBus()
    bus._max_history = 5
    for i in range(10):
        await bus.emit(f"evt_{i}")
    assert len(bus._history) == 5
    assert bus._history[0].event_type == "evt_5"


# =========================================================================
# CenturionEvent serialization
# =========================================================================


def test_event_to_json():
    event = CenturionEvent(
        event_type="test",
        entity_type="legion",
        entity_id="alpha",
        payload={"key": "value"},
        timestamp=1234567890.0,
    )
    data = json.loads(event.to_json())
    assert data["event_type"] == "test"
    assert data["entity_type"] == "legion"
    assert data["entity_id"] == "alpha"
    assert data["payload"] == {"key": "value"}
    assert data["timestamp"] == 1234567890.0


# =========================================================================
# WebSocket endpoint integration
# =========================================================================


def test_websocket_receives_events():
    """Connect via WS, raise a legion via REST, verify event arrives over the socket."""
    app, engine = _make_app_with_engine()
    client = TestClient(app)

    with client.websocket_connect("/api/centurion/events") as ws:
        # Raise a legion via REST to trigger an event
        resp = client.post(
            "/api/centurion/legions",
            json={"name": "WS Test", "legion_id": "ws-leg"},
        )
        assert resp.status_code == 201

        # The event bus should have pushed "legion_raised"
        data = ws.receive_json()
        assert data["event_type"] == "legion_raised"
        assert data["entity_id"] == "ws-leg"


def test_websocket_multiple_events():
    """Verify multiple sequential events arrive in order."""
    app, engine = _make_app_with_engine()
    client = TestClient(app)

    with client.websocket_connect("/api/centurion/events") as ws:
        client.post(
            "/api/centurion/legions",
            json={"name": "A", "legion_id": "ws-a"},
        )
        client.post(
            "/api/centurion/legions",
            json={"name": "B", "legion_id": "ws-b"},
        )

        evt1 = ws.receive_json()
        evt2 = ws.receive_json()
        assert evt1["entity_id"] == "ws-a"
        assert evt2["entity_id"] == "ws-b"
