"""Tests for health check endpoints and graceful shutdown configuration."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from centurion.api.router import _build_recommended_actions, health_router, router
from centurion.api.schemas import ComponentStatus, HealthResponse, ReadinessResponse
from centurion.config import CenturionConfig
from centurion.core.session_registry import SessionRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(**state_attrs) -> FastAPI:
    """Create a minimal FastAPI app with health_router and optional state."""
    app = FastAPI()
    app.include_router(health_router)
    for key, value in state_attrs.items():
        setattr(app.state, key, value)
    return app


def _mock_engine(
    *,
    shutting_down: bool = False,
    legions: dict | None = None,
    active_agents: int = 0,
    recommended_max: int = 10,
    subscribers: int = 0,
    history_size: int = 0,
    has_db: bool = False,
) -> MagicMock:
    """Build a MagicMock that satisfies the readiness probe checks."""
    from centurion.core.scheduler import MemoryPressureLevel, SystemResources

    engine = MagicMock()
    engine._shutting_down = shutting_down
    engine.legions = legions if legions is not None else {}

    # Scheduler — return a real SystemResources so the readiness endpoint
    # can access .memory_pressure.value and the new RAM fields.
    engine.scheduler.probe_system.return_value = SystemResources(
        cpu_count=8,
        ram_total_mb=16384,
        ram_available_mb=8192,
        ram_available_conservative_mb=7680,
        ram_compressor_mb=512,
        memory_pressure=MemoryPressureLevel.NORMAL,
    )
    engine.scheduler.active_agents = active_agents
    engine.scheduler.recommended_max_agents.return_value = recommended_max

    # EventBus
    engine.event_bus._subscribers = [None] * subscribers
    engine.event_bus._history = [None] * history_size

    # Database
    if has_db:
        engine.db = MagicMock()
    else:
        engine.db = None

    return engine


# ---------------------------------------------------------------------------
# 1. Liveness — GET /health
# ---------------------------------------------------------------------------


class TestHealthLiveness:
    def test_health_returns_ok(self):
        """GET /health returns 200 with {"status": "ok"}."""
        app = _make_app()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"

    def test_health_response_model(self):
        """HealthResponse defaults to status='ok'."""
        h = HealthResponse()
        assert h.status == "ok"


# ---------------------------------------------------------------------------
# 2. Readiness — GET /health/ready (no engine)
# ---------------------------------------------------------------------------


class TestHealthReadinessNoEngine:
    def test_health_ready_without_engine(self):
        """GET /health/ready returns 503 when no engine is set on app.state."""
        app = _make_app()  # no centurion attribute
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        # Engine component should report an error
        assert body["components"]["engine"]["status"] == "error"
        assert "not initialized" in body["components"]["engine"]["error"].lower()

    def test_ready_without_engine_reports_all_errors(self):
        """When no engine is present, all components report errors."""
        app = _make_app()
        client = TestClient(app)
        body = client.get("/health/ready").json()
        for name in ("engine", "scheduler", "event_bus", "database"):
            assert body["components"][name]["status"] == "error", (
                f"Component {name!r} should be 'error' when engine is absent"
            )


# ---------------------------------------------------------------------------
# 3. Readiness — GET /health/ready (engine present)
# ---------------------------------------------------------------------------


class TestHealthReadinessWithEngine:
    def test_health_ready_with_engine(self):
        """GET /health/ready returns 200 when a fully mocked engine is set."""
        engine = _mock_engine(has_db=True)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["components"]["engine"]["status"] == "ok"
        assert body["components"]["scheduler"]["status"] == "ok"
        assert body["components"]["event_bus"]["status"] == "ok"
        assert body["components"]["database"]["status"] == "ok"

    def test_ready_engine_shutting_down(self):
        """Readiness returns 503 when the engine is shutting down."""
        engine = _mock_engine(shutting_down=True, has_db=True)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["components"]["engine"]["status"] == "error"
        assert body["components"]["engine"]["shutting_down"] is True

    def test_ready_reports_active_agents(self):
        """Readiness includes scheduler active_agents and recommended_max."""
        engine = _mock_engine(active_agents=5, recommended_max=20, has_db=True)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/health/ready").json()
        assert body["components"]["scheduler"]["active_agents"] == 5
        assert body["components"]["scheduler"]["recommended_max"] == 20

    def test_ready_reports_event_bus_stats(self):
        """Readiness includes event_bus subscriber and history counts."""
        engine = _mock_engine(subscribers=3, history_size=42, has_db=True)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/health/ready").json()
        assert body["components"]["event_bus"]["subscribers"] == 3
        assert body["components"]["event_bus"]["history_size"] == 42

    def test_ready_no_database(self):
        """Readiness returns 503 when engine has no database attached."""
        engine = _mock_engine(has_db=False)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["components"]["database"]["status"] == "error"

    def test_ready_scheduler_probe_failure(self):
        """Readiness reports scheduler error when probe_system() raises."""
        engine = _mock_engine(has_db=True)
        engine.scheduler.probe_system.side_effect = RuntimeError("CPU on fire")
        app = _make_app(centurion=engine)
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["components"]["scheduler"]["status"] == "error"
        assert "CPU on fire" in body["components"]["scheduler"]["error"]


# ---------------------------------------------------------------------------
# 4. Config — shutdown_timeout and event_buffer_size
# ---------------------------------------------------------------------------


class TestConfigEnvVars:
    def test_shutdown_timeout_default(self):
        """CenturionConfig.shutdown_timeout defaults to 60."""
        config = CenturionConfig()
        assert config.shutdown_timeout == 60.0

    def test_shutdown_timeout_configurable(self, monkeypatch):
        """CENTURION_SHUTDOWN_TIMEOUT env var overrides the default."""
        monkeypatch.setenv("CENTURION_SHUTDOWN_TIMEOUT", "120")
        config = CenturionConfig()
        assert config.shutdown_timeout == 120.0

    def test_event_buffer_size_default(self):
        """CenturionConfig.event_buffer_size defaults to 1000."""
        config = CenturionConfig()
        assert config.event_buffer_size == 1000

    def test_event_buffer_size_configurable(self, monkeypatch):
        """CENTURION_EVENT_BUFFER_SIZE env var overrides the default."""
        monkeypatch.setenv("CENTURION_EVENT_BUFFER_SIZE", "5000")
        config = CenturionConfig()
        assert config.event_buffer_size == 5000


# ---------------------------------------------------------------------------
# 5. Engine — _shutting_down flag
# ---------------------------------------------------------------------------


class TestEngineShuttingDownFlag:
    def test_engine_has_shutting_down_flag(self):
        """Centurion.__init__ sets _shutting_down = False."""
        from centurion.core.engine import Centurion

        engine = Centurion()
        assert hasattr(engine, "_shutting_down")
        assert engine._shutting_down is False

    def test_engine_shutdown_timeout_from_config(self):
        """Engine uses config.shutdown_timeout during shutdown."""
        CenturionConfig()
        config_with_timeout = CenturionConfig()
        # Verify the engine stores the config and the timeout is accessible
        from centurion.core.engine import Centurion

        engine = Centurion(config=config_with_timeout)
        assert engine.config.shutdown_timeout == config_with_timeout.shutdown_timeout


# ---------------------------------------------------------------------------
# 6. Schema models
# ---------------------------------------------------------------------------


class TestSchemaModels:
    def test_component_status_ok(self):
        """ComponentStatus with status='ok' has no error by default."""
        cs = ComponentStatus(status="ok")
        assert cs.status == "ok"
        assert cs.error is None

    def test_component_status_error(self):
        """ComponentStatus with status='error' can carry an error message."""
        cs = ComponentStatus(status="error", error="Something broke")
        assert cs.status == "error"
        assert cs.error == "Something broke"

    def test_readiness_response_model(self):
        """ReadinessResponse can be constructed with component dict."""
        r = ReadinessResponse(
            status="ready",
            components={"engine": ComponentStatus(status="ok")},
        )
        assert r.status == "ready"
        assert r.components["engine"].status == "ok"

    def test_component_status_has_ram_conservative_field(self):
        """ComponentStatus has ram_available_conservative_mb optional field."""
        cs = ComponentStatus(status="ok", ram_available_conservative_mb=5000)
        assert cs.ram_available_conservative_mb == 5000

    def test_component_status_has_ram_compressor_field(self):
        """ComponentStatus has ram_compressor_mb optional field."""
        cs = ComponentStatus(status="ok", ram_compressor_mb=1024)
        assert cs.ram_compressor_mb == 1024

    def test_component_status_has_memory_pressure_field(self):
        """ComponentStatus has memory_pressure optional field."""
        cs = ComponentStatus(status="ok", memory_pressure="normal")
        assert cs.memory_pressure == "normal"

    def test_component_status_new_fields_default_none(self):
        """New fields default to None and are excluded with exclude_none."""
        cs = ComponentStatus(status="ok")
        assert cs.ram_available_conservative_mb is None
        assert cs.ram_compressor_mb is None
        assert cs.memory_pressure is None
        dumped = cs.model_dump(exclude_none=True)
        assert "ram_available_conservative_mb" not in dumped
        assert "ram_compressor_mb" not in dumped
        assert "memory_pressure" not in dumped


# ---------------------------------------------------------------------------
# 7. Readiness endpoint includes new scheduler fields
# ---------------------------------------------------------------------------


class TestReadinessSchedulerNewFields:
    """GET /health/ready scheduler component includes new RAM fields."""

    def _mock_engine_with_probe(
        self,
        *,
        ram_available_conservative_mb=5000,
        ram_compressor_mb=512,
        memory_pressure_value="normal",
    ):
        from centurion.core.scheduler import MemoryPressureLevel, SystemResources

        engine = _mock_engine(has_db=True, active_agents=2, recommended_max=10)
        # Make probe_system return a real SystemResources with new fields
        resources = SystemResources(
            cpu_count=8,
            ram_total_mb=16384,
            ram_available_mb=8192,
            ram_available_conservative_mb=ram_available_conservative_mb,
            ram_compressor_mb=ram_compressor_mb,
            memory_pressure=MemoryPressureLevel(memory_pressure_value),
        )
        engine.scheduler.probe_system.return_value = resources
        return engine

    def test_scheduler_includes_ram_conservative(self):
        engine = self._mock_engine_with_probe(ram_available_conservative_mb=5000)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/health/ready").json()
        assert body["components"]["scheduler"]["ram_available_conservative_mb"] == 5000

    def test_scheduler_includes_ram_compressor(self):
        engine = self._mock_engine_with_probe(ram_compressor_mb=512)
        app = _make_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/health/ready").json()
        assert body["components"]["scheduler"]["ram_compressor_mb"] == 512

    def test_scheduler_includes_memory_pressure(self):
        engine = self._mock_engine_with_probe(memory_pressure_value="warn")
        app = _make_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/health/ready").json()
        assert body["components"]["scheduler"]["memory_pressure"] == "warn"


# ---------------------------------------------------------------------------
# 8. Hardware endpoint — recommended_actions
# ---------------------------------------------------------------------------


def _make_hardware_app(**state_attrs) -> FastAPI:
    """Create a FastAPI app with both health_router and router for hardware endpoint."""
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(router)
    for key, value in state_attrs.items():
        setattr(app.state, key, value)
    return app


class TestBuildRecommendedActions:
    """Unit tests for the _build_recommended_actions helper."""

    def test_normal_pressure_returns_empty(self):
        from centurion.core.scheduler import MemoryPressureLevel

        actions = _build_recommended_actions(MemoryPressureLevel.NORMAL, session_registry=None, scheduler=None)
        assert actions == []

    def test_warn_pressure_no_registry_returns_batch_suggestion(self):
        from centurion.core.scheduler import MemoryPressureLevel

        actions = _build_recommended_actions(MemoryPressureLevel.WARN, session_registry=None, scheduler=None)
        # Should have at least a reduce batch size suggestion
        texts = [a for a in actions if "batch" in a.lower()]
        assert len(texts) >= 1

    def test_warn_pressure_with_closeable_sessions(self):
        from centurion.core.scheduler import MemoryPressureLevel

        registry = SessionRegistry()
        registry.register_session("s1", parent_id=None, session_type="interactive")
        registry.session_meta["s1"].last_active = time.time() - 600
        actions = _build_recommended_actions(MemoryPressureLevel.WARN, session_registry=registry, scheduler=None)
        close_actions = [a for a in actions if "s1" in a]
        assert len(close_actions) >= 1, f"Expected action for session s1, got: {actions}"

    def test_warn_pressure_skips_pinned_sessions(self):
        from centurion.core.scheduler import MemoryPressureLevel

        registry = SessionRegistry()
        registry.register_session("pinned-1", parent_id=None, session_type="interactive", pinned=True)
        registry.session_meta["pinned-1"].last_active = time.time() - 600
        actions = _build_recommended_actions(MemoryPressureLevel.WARN, session_registry=registry, scheduler=None)
        close_actions = [a for a in actions if "pinned-1" in a]
        assert len(close_actions) == 0, "Pinned sessions should not appear in recommendations"

    def test_warn_pressure_skips_sessions_with_bg_children(self):
        from centurion.core.scheduler import MemoryPressureLevel

        registry = SessionRegistry()
        registry.register_session("parent-1", parent_id=None, session_type="interactive")
        registry.register_session("child-1", parent_id="parent-1", session_type="background")
        registry.session_meta["parent-1"].last_active = time.time() - 600
        actions = _build_recommended_actions(MemoryPressureLevel.WARN, session_registry=registry, scheduler=None)
        parent_actions = [a for a in actions if "parent-1" in a]
        assert len(parent_actions) == 0, "Sessions with bg children should not appear"

    def test_critical_pressure_includes_purge(self):
        from centurion.core.scheduler import MemoryPressureLevel

        actions = _build_recommended_actions(MemoryPressureLevel.CRITICAL, session_registry=None, scheduler=None)
        purge_actions = [a for a in actions if "purge" in a.lower()]
        assert len(purge_actions) >= 1

    def test_critical_pressure_includes_background_tasks_warning(self):
        from centurion.core.scheduler import MemoryPressureLevel

        actions = _build_recommended_actions(MemoryPressureLevel.CRITICAL, session_registry=None, scheduler=None)
        bg_actions = [a for a in actions if "background" in a.lower()]
        assert len(bg_actions) >= 1

    def test_critical_pressure_includes_batch_reduction(self):
        from centurion.core.scheduler import MemoryPressureLevel

        actions = _build_recommended_actions(MemoryPressureLevel.CRITICAL, session_registry=None, scheduler=None)
        batch_actions = [a for a in actions if "batch" in a.lower()]
        assert len(batch_actions) >= 1

    def test_closeable_session_action_includes_idle_seconds(self):
        from centurion.core.scheduler import MemoryPressureLevel

        registry = SessionRegistry()
        registry.register_session("idle-sess", parent_id=None, session_type="interactive")
        registry.session_meta["idle-sess"].last_active = time.time() - 1800
        actions = _build_recommended_actions(MemoryPressureLevel.WARN, session_registry=registry, scheduler=None)
        idle_actions = [a for a in actions if "idle-sess" in a]
        assert len(idle_actions) == 1
        # Should mention idle time
        assert "idle" in idle_actions[0].lower()


class TestHardwareRecommendedActions:
    """Integration tests: GET /api/centurion/hardware includes recommended_actions."""

    def _mock_engine_with_pressure(self, pressure_value="normal", registry=None):
        from centurion.core.scheduler import MemoryPressureLevel, SystemResources

        engine = MagicMock()
        engine._shutting_down = False
        engine.legions = {}

        resources = SystemResources(
            cpu_count=8,
            ram_total_mb=16384,
            ram_available_mb=8192,
            ram_available_conservative_mb=7680,
            ram_compressor_mb=512,
            memory_pressure=MemoryPressureLevel(pressure_value),
        )
        engine.scheduler.probe_system.return_value = resources
        engine.scheduler.active_agents = 2
        engine.scheduler.recommended_max_agents.return_value = 10

        # hardware_report returns scheduler.to_dict()
        engine.hardware_report.return_value = {
            "system": {
                "memory_pressure": pressure_value,
                "ram_total_mb": 16384,
                "ram_available_mb": 8192,
            },
            "allocated": {"active_agents": 2},
            "recommended_max_agents": 10,
        }

        if registry is not None:
            engine.session_registry = registry
        else:
            # No session_registry attribute
            del engine.session_registry

        return engine

    def test_hardware_normal_has_empty_recommended_actions(self):
        engine = self._mock_engine_with_pressure("normal")
        app = _make_hardware_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/api/centurion/hardware").json()
        assert "recommended_actions" in body
        assert body["recommended_actions"] == []

    def test_hardware_warn_has_recommended_actions(self):
        registry = SessionRegistry()
        registry.register_session("s-idle", parent_id=None, session_type="interactive")
        registry.session_meta["s-idle"].last_active = time.time() - 900
        engine = self._mock_engine_with_pressure("warn", registry=registry)
        app = _make_hardware_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/api/centurion/hardware").json()
        assert "recommended_actions" in body
        assert len(body["recommended_actions"]) > 0
        # Should include session close recommendation
        all_text = " ".join(body["recommended_actions"])
        assert "s-idle" in all_text

    def test_hardware_critical_has_purge_action(self):
        engine = self._mock_engine_with_pressure("critical")
        app = _make_hardware_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/api/centurion/hardware").json()
        assert "recommended_actions" in body
        purge = [a for a in body["recommended_actions"] if "purge" in a.lower()]
        assert len(purge) >= 1

    def test_hardware_response_preserves_existing_fields(self):
        engine = self._mock_engine_with_pressure("normal")
        app = _make_hardware_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/api/centurion/hardware").json()
        # Original fields from hardware_report should still be present
        assert "system" in body
        assert "allocated" in body
        assert "recommended_max_agents" in body

    def test_hardware_warn_empty_registry(self):
        """Under warn pressure with empty registry, still get batch suggestion but no session actions."""
        registry = SessionRegistry()
        engine = self._mock_engine_with_pressure("warn", registry=registry)
        app = _make_hardware_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/api/centurion/hardware").json()
        assert "recommended_actions" in body
        assert len(body["recommended_actions"]) > 0
        # Should have batch reduction but no session-close actions
        for action in body["recommended_actions"]:
            assert "Close idle session" not in action

    def test_hardware_warn_many_closeable_sessions(self):
        """All closeable sessions should appear in recommended_actions."""
        registry = SessionRegistry()
        for i in range(10):
            sid = f"sess-{i}"
            registry.register_session(sid, parent_id=None, session_type="interactive")
            registry.session_meta[sid].last_active = time.time() - (100 * (i + 1))
        engine = self._mock_engine_with_pressure("warn", registry=registry)
        app = _make_hardware_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/api/centurion/hardware").json()
        close_actions = [a for a in body["recommended_actions"] if "Close idle session" in a]
        assert len(close_actions) == 10

    def test_hardware_critical_no_registry(self):
        """Critical pressure without registry still returns purge and batch actions."""
        engine = self._mock_engine_with_pressure("critical")
        app = _make_hardware_app(centurion=engine)
        client = TestClient(app)
        body = client.get("/api/centurion/hardware").json()
        actions = body["recommended_actions"]
        assert any("purge" in a.lower() for a in actions)
        assert any("batch" in a.lower() for a in actions)
        assert any("background" in a.lower() for a in actions)


# ---------------------------------------------------------------------------
# 9. Integration: session registration -> pressure -> recommended_actions
# ---------------------------------------------------------------------------


class TestIntegrationSessionPressureActions:
    """Full flow: register sessions, simulate pressure, check actions."""

    def test_full_flow_register_then_pressure(self):
        from centurion.core.scheduler import MemoryPressureLevel

        # 1. Create registry and register sessions
        registry = SessionRegistry()
        registry.register_session("parent-1", parent_id=None, session_type="interactive")
        registry.register_session("bg-child-1", parent_id="parent-1", session_type="background")
        registry.register_session("idle-solo", parent_id=None, session_type="interactive")
        registry.session_meta["idle-solo"].last_active = time.time() - 300

        # 2. Under normal pressure: no actions
        actions = _build_recommended_actions(MemoryPressureLevel.NORMAL, session_registry=registry, scheduler=None)
        assert actions == []

        # 3. Under warn pressure: idle-solo recommended, parent-1 is not (has bg child)
        actions = _build_recommended_actions(MemoryPressureLevel.WARN, session_registry=registry, scheduler=None)
        action_text = " ".join(actions)
        assert "idle-solo" in action_text
        assert "parent-1" not in action_text
        # bg-child-1 is closeable (no children of its own)
        assert "bg-child-1" in action_text

        # 4. Terminate bg-child-1 -> now parent-1 becomes closeable
        registry.terminate_session("bg-child-1")
        actions = _build_recommended_actions(MemoryPressureLevel.WARN, session_registry=registry, scheduler=None)
        action_text = " ".join(actions)
        assert "parent-1" in action_text

    def test_pressure_transitions(self):
        """Actions change appropriately as pressure escalates."""
        from centurion.core.scheduler import MemoryPressureLevel

        registry = SessionRegistry()
        registry.register_session("s1", parent_id=None, session_type="interactive")
        registry.session_meta["s1"].last_active = time.time() - 600

        # Normal: empty
        actions = _build_recommended_actions(MemoryPressureLevel.NORMAL, session_registry=registry, scheduler=None)
        assert actions == []

        # Warn: has close + batch
        actions = _build_recommended_actions(MemoryPressureLevel.WARN, session_registry=registry, scheduler=None)
        assert any("s1" in a for a in actions)
        assert any("batch" in a.lower() for a in actions)
        assert not any("purge" in a.lower() for a in actions)

        # Critical: has close + batch=1 + purge + background warning
        actions = _build_recommended_actions(MemoryPressureLevel.CRITICAL, session_registry=registry, scheduler=None)
        assert any("s1" in a for a in actions)
        assert any("batch" in a.lower() and "1" in a for a in actions)
        assert any("purge" in a.lower() for a in actions)
        assert any("background" in a.lower() for a in actions)
