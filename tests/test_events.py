"""Tests for the EventBus pub-sub system (the Aquilifer)."""

from __future__ import annotations

import asyncio

import pytest

from centurion.core.events import CenturionEvent, EventBus


@pytest.mark.asyncio
async def test_emit_and_subscribe():
    """Subscribe to the bus, emit an event, verify the subscriber queue receives it."""
    bus = EventBus()
    queue = bus.subscribe()

    event = await bus.emit("task.started", entity_type="legionary", entity_id="leg-1", payload={"task": "build"})

    assert not queue.empty()
    received = queue.get_nowait()
    assert received is event
    assert received.event_type == "task.started"
    assert received.entity_type == "legionary"
    assert received.entity_id == "leg-1"
    assert received.payload == {"task": "build"}


@pytest.mark.asyncio
async def test_ring_buffer_overflow():
    """With max_history=5, emitting 10 events should keep only the last 5."""
    bus = EventBus(max_history=5)

    events = []
    for i in range(10):
        ev = await bus.emit(f"evt-{i}")
        events.append(ev)

    assert len(bus._history) == 5
    # The retained events should be the last 5 emitted (indices 5-9)
    for idx, stored in enumerate(bus._history):
        assert stored.event_type == f"evt-{idx + 5}"


@pytest.mark.asyncio
async def test_slow_subscriber_drops_event():
    """A subscriber with maxsize=1 silently drops events when full (no error raised)."""
    bus = EventBus()
    # Manually create a bounded queue and register it as a subscriber
    small_queue: asyncio.Queue[CenturionEvent] = asyncio.Queue(maxsize=1)
    bus._subscribers.append(small_queue)

    # Emit 3 events; the first fills the queue, the rest are silently dropped
    for i in range(3):
        await bus.emit(f"flood-{i}")

    # Queue should contain exactly 1 event (the first one)
    assert small_queue.qsize() == 1
    received = small_queue.get_nowait()
    assert received.event_type == "flood-0"
    # Queue should now be empty (the other 2 were dropped)
    assert small_queue.empty()


@pytest.mark.asyncio
async def test_unsubscribe():
    """After unsubscribing, the subscriber list should no longer contain that queue."""
    bus = EventBus()
    queue = bus.subscribe()
    assert len(bus._subscribers) == 1

    bus.unsubscribe(queue)
    assert len(bus._subscribers) == 0

    # Unsubscribing the same queue again should not raise
    bus.unsubscribe(queue)
    assert len(bus._subscribers) == 0


@pytest.mark.asyncio
async def test_recent_events():
    """recent_events() returns events in reverse chronological order."""
    bus = EventBus()

    for i in range(7):
        await bus.emit(f"evt-{i}")

    recent = bus.recent_events(limit=5)
    assert len(recent) == 5
    # Most recent first
    assert recent[0].event_type == "evt-6"
    assert recent[1].event_type == "evt-5"
    assert recent[4].event_type == "evt-2"


@pytest.mark.asyncio
async def test_event_to_json():
    """CenturionEvent.to_json() produces valid JSON with expected fields."""
    import json

    event = CenturionEvent(event_type="test", entity_type="agent", entity_id="a-1", payload={"key": "val"})
    data = json.loads(event.to_json())

    assert data["event_type"] == "test"
    assert data["entity_type"] == "agent"
    assert data["entity_id"] == "a-1"
    assert data["payload"] == {"key": "val"}
    assert "timestamp" in data
