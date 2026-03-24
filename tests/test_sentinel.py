"""Tests for the Sentinel stale session reaper."""

from __future__ import annotations

import asyncio
import time

import pytest

from centurion.core.events import EventBus
from centurion.core.sentinel import (
    Sentinel,
    SentinelConfig,
    SentinelKillRecord,
    SentinelMetrics,
    _kill_priority,
)
from centurion.core.session_registry import SessionRegistry

# ---------------------------------------------------------------------------
# Unit tests: SentinelMetrics
# ---------------------------------------------------------------------------


class TestSentinelMetrics:
    def test_initial_state(self):
        metrics = SentinelMetrics()
        assert metrics.total_kills == 0
        d = metrics.to_dict()
        assert d["total_kills"] == 0
        assert d["dry_run_kills"] == 0
        assert d["scans_completed"] == 0
        assert d["last_kill"] is None
        assert d["recent_kills"] == []

    def test_record_kill(self):
        metrics = SentinelMetrics()
        record = SentinelKillRecord(
            session_id="sess-1",
            session_type="interactive",
            reason="idle too long",
            idle_seconds=2000.0,
            runtime_seconds=3000.0,
            timestamp=time.time(),
        )
        metrics.record_kill(record)
        assert metrics.total_kills == 1
        d = metrics.to_dict()
        assert d["total_kills"] == 1
        assert d["last_kill"]["session_id"] == "sess-1"
        assert d["kills_by_type"]["interactive"] == 1

    def test_record_dry_run_kill(self):
        metrics = SentinelMetrics()
        record = SentinelKillRecord(
            session_id="sess-1",
            session_type="interactive",
            reason="idle",
            idle_seconds=100.0,
            runtime_seconds=200.0,
            timestamp=time.time(),
            dry_run=True,
        )
        metrics.record_kill(record)
        assert metrics.total_kills == 0
        assert metrics.to_dict()["dry_run_kills"] == 1

    def test_record_scan(self):
        metrics = SentinelMetrics()
        metrics.record_scan()
        assert metrics.to_dict()["scans_completed"] == 1
        assert metrics.to_dict()["last_scan_at"] is not None

    def test_recent_kills_limited(self):
        metrics = SentinelMetrics()
        for i in range(60):
            record = SentinelKillRecord(
                session_id=f"sess-{i}",
                session_type="interactive",
                reason="test",
                idle_seconds=100.0,
                runtime_seconds=200.0,
                timestamp=time.time(),
            )
            metrics.record_kill(record)
        # Internal list capped at 50, to_dict shows last 10
        d = metrics.to_dict()
        assert len(d["recent_kills"]) == 10
        assert metrics.total_kills == 60


# ---------------------------------------------------------------------------
# Unit tests: kill priority
# ---------------------------------------------------------------------------


class TestKillPriority:
    def test_interactive_killed_first(self):
        assert _kill_priority("interactive") < _kill_priority("background")

    def test_unknown_type_defaults_to_zero(self):
        assert _kill_priority("unknown") == 0


# ---------------------------------------------------------------------------
# Sentinel scan_once tests
# ---------------------------------------------------------------------------


@pytest.fixture
def registry_with_sessions():
    """Create a session registry with a mix of sessions."""
    registry = SessionRegistry()
    now = time.time()

    # Stale interactive session (idle 2000s)
    registry.register_session("interactive-stale", None, "interactive")
    meta = registry.get_session_meta("interactive-stale")
    meta.last_active = now - 2000
    meta.created_at = now - 3000

    # Fresh interactive session (idle 10s)
    registry.register_session("interactive-fresh", None, "interactive")
    meta = registry.get_session_meta("interactive-fresh")
    meta.last_active = now - 10

    # Stale background session (idle 2000s)
    registry.register_session("background-stale", None, "background")
    meta = registry.get_session_meta("background-stale")
    meta.last_active = now - 2000
    meta.created_at = now - 3000

    # Long-running background (not idle, but runtime > max)
    registry.register_session("background-long", None, "background")
    meta = registry.get_session_meta("background-long")
    meta.last_active = now - 5  # recently active
    meta.created_at = now - 8000  # running for 8000s

    # Pinned session (should never be killed)
    registry.register_session("pinned-session", None, "interactive", pinned=True)
    meta = registry.get_session_meta("pinned-session")
    meta.last_active = now - 5000

    return registry


async def test_scan_once_kills_stale_sessions(registry_with_sessions):
    """Sentinel should identify and kill stale sessions."""
    config = SentinelConfig(
        scan_interval_seconds=1.0,
        idle_threshold_seconds=1800.0,
        max_runtime_seconds=7200.0,
        dry_run=False,
    )
    sentinel = Sentinel(config=config, session_registry=registry_with_sessions)
    kills = await sentinel.scan_once()

    killed_ids = [k.session_id for k in kills]

    # Should kill stale interactive and background, plus long-running
    assert "interactive-stale" in killed_ids
    assert "background-stale" in killed_ids
    assert "background-long" in killed_ids

    # Should NOT kill fresh or pinned
    assert "interactive-fresh" not in killed_ids
    assert "pinned-session" not in killed_ids


async def test_scan_once_respects_priority_ordering(registry_with_sessions):
    """Interactive sessions should be killed before background sessions."""
    config = SentinelConfig(
        idle_threshold_seconds=1800.0,
        max_runtime_seconds=7200.0,
        dry_run=False,
    )
    sentinel = Sentinel(config=config, session_registry=registry_with_sessions)
    kills = await sentinel.scan_once()

    # Find positions of interactive vs background kills
    interactive_positions = [
        i for i, k in enumerate(kills) if k.session_type == "interactive"
    ]
    background_positions = [
        i for i, k in enumerate(kills) if k.session_type == "background"
    ]

    if interactive_positions and background_positions:
        assert max(interactive_positions) < min(background_positions), (
            "Interactive sessions should be killed before background sessions"
        )


async def test_scan_once_dry_run(registry_with_sessions):
    """In dry-run mode, sessions should NOT be terminated."""
    config = SentinelConfig(
        idle_threshold_seconds=1800.0,
        max_runtime_seconds=7200.0,
        dry_run=True,
    )
    sentinel = Sentinel(config=config, session_registry=registry_with_sessions)
    kills = await sentinel.scan_once()

    assert len(kills) > 0
    for k in kills:
        assert k.dry_run is True

    # Sessions should still be active (not terminated)
    meta = registry_with_sessions.get_session_meta("interactive-stale")
    assert meta.status == "active"


async def test_scan_once_terminates_sessions(registry_with_sessions):
    """In live mode, sessions should be terminated after kill."""
    config = SentinelConfig(
        idle_threshold_seconds=1800.0,
        max_runtime_seconds=7200.0,
        dry_run=False,
    )
    sentinel = Sentinel(config=config, session_registry=registry_with_sessions)
    await sentinel.scan_once()

    # Stale sessions should be terminated
    meta = registry_with_sessions.get_session_meta("interactive-stale")
    assert meta.status == "terminated"

    meta = registry_with_sessions.get_session_meta("background-stale")
    assert meta.status == "terminated"


async def test_scan_once_emits_events(registry_with_sessions):
    """Sentinel should emit sentinel_kill events."""
    event_bus = EventBus()
    config = SentinelConfig(
        idle_threshold_seconds=1800.0,
        max_runtime_seconds=7200.0,
        dry_run=False,
    )
    sentinel = Sentinel(
        config=config,
        session_registry=registry_with_sessions,
        event_bus=event_bus,
    )

    queue = event_bus.subscribe()
    kills = await sentinel.scan_once()

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    sentinel_events = [e for e in events if e.event_type == "sentinel_kill"]
    assert len(sentinel_events) == len(kills)

    for event in sentinel_events:
        assert event.entity_type == "session"
        assert "reason" in event.payload
        assert "session_type" in event.payload


async def test_scan_once_updates_metrics(registry_with_sessions):
    """Sentinel should update metrics after scan."""
    config = SentinelConfig(
        idle_threshold_seconds=1800.0,
        max_runtime_seconds=7200.0,
        dry_run=False,
    )
    sentinel = Sentinel(config=config, session_registry=registry_with_sessions)
    kills = await sentinel.scan_once()

    assert sentinel.metrics.total_kills == len(kills)
    d = sentinel.metrics.to_dict()
    assert d["scans_completed"] == 1
    assert d["last_scan_at"] is not None


async def test_scan_once_no_registry():
    """If no session registry, scan should return empty."""
    sentinel = Sentinel(config=SentinelConfig(), session_registry=None)
    kills = await sentinel.scan_once()
    assert kills == []
    assert sentinel.metrics.to_dict()["scans_completed"] == 1


async def test_scan_once_skips_sessions_with_bg_children():
    """Sessions with active background children should not be killed."""
    registry = SessionRegistry()
    now = time.time()

    # Parent interactive session (stale)
    registry.register_session("parent-sess", None, "interactive")
    meta = registry.get_session_meta("parent-sess")
    meta.last_active = now - 5000

    # Active background child
    registry.register_session("child-bg", "parent-sess", "background")

    config = SentinelConfig(
        idle_threshold_seconds=1800.0,
        max_runtime_seconds=7200.0,
        dry_run=False,
    )
    sentinel = Sentinel(config=config, session_registry=registry)
    kills = await sentinel.scan_once()

    killed_ids = [k.session_id for k in kills]
    assert "parent-sess" not in killed_ids


# ---------------------------------------------------------------------------
# Sentinel start/stop lifecycle
# ---------------------------------------------------------------------------


async def test_sentinel_start_stop():
    """Sentinel should start and stop cleanly."""
    config = SentinelConfig(scan_interval_seconds=0.1, enabled=True)
    sentinel = Sentinel(config=config)

    assert not sentinel.is_running
    await sentinel.start()
    assert sentinel.is_running

    await asyncio.sleep(0.05)
    await sentinel.stop()
    assert not sentinel.is_running


async def test_sentinel_disabled():
    """Sentinel should not start if disabled."""
    config = SentinelConfig(enabled=False)
    sentinel = Sentinel(config=config)

    await sentinel.start()
    assert not sentinel.is_running


async def test_sentinel_double_start():
    """Starting sentinel twice should not create duplicate tasks."""
    config = SentinelConfig(scan_interval_seconds=0.1, enabled=True)
    sentinel = Sentinel(config=config)

    await sentinel.start()
    await sentinel.start()  # should warn, not crash
    assert sentinel.is_running

    await sentinel.stop()


# ---------------------------------------------------------------------------
# Sentinel scan with idle threshold only
# ---------------------------------------------------------------------------


async def test_scan_only_idle_threshold():
    """Test that sessions idle beyond threshold are killed."""
    registry = SessionRegistry()
    now = time.time()

    registry.register_session("idle-sess", None, "interactive")
    meta = registry.get_session_meta("idle-sess")
    meta.last_active = now - 2000
    meta.created_at = now - 2500

    # Very high max_runtime so only idle triggers
    config = SentinelConfig(
        idle_threshold_seconds=1800.0,
        max_runtime_seconds=999999.0,
        dry_run=False,
    )
    sentinel = Sentinel(config=config, session_registry=registry)
    kills = await sentinel.scan_once()

    assert len(kills) == 1
    assert "idle" in kills[0].reason


async def test_scan_only_runtime_threshold():
    """Test that sessions exceeding max runtime are killed."""
    registry = SessionRegistry()
    now = time.time()

    registry.register_session("long-sess", None, "background")
    meta = registry.get_session_meta("long-sess")
    meta.last_active = now - 5  # recently active
    meta.created_at = now - 8000  # running a long time

    # Very high idle threshold so only runtime triggers
    config = SentinelConfig(
        idle_threshold_seconds=999999.0,
        max_runtime_seconds=7200.0,
        dry_run=False,
    )
    sentinel = Sentinel(config=config, session_registry=registry)
    kills = await sentinel.scan_once()

    assert len(kills) == 1
    assert "running" in kills[0].reason


# ---------------------------------------------------------------------------
# Integration: Sentinel in Engine
# ---------------------------------------------------------------------------


async def test_engine_has_sentinel():
    """Engine should have a sentinel attribute after init."""
    from centurion.config import CenturionConfig
    from centurion.core.engine import Centurion

    config = CenturionConfig(sentinel_enabled=False)
    engine = Centurion(config=config)

    assert hasattr(engine, "sentinel")
    assert engine.sentinel is not None
    assert engine.sentinel.config.enabled is False
    assert engine.sentinel.session_registry is engine.session_registry
