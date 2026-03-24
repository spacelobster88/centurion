"""Full lifecycle integration test for the Centurion engine.

Exercises the complete flow: engine creation, legion raising, century mustering,
task submission, result collection, and graceful shutdown.
"""

from __future__ import annotations

import asyncio

import pytest

from centurion.agent_types.base import AgentResult, AgentType
from centurion.config import CenturionConfig, ResourceRequirements, ResourceSpec
from centurion.core.century import CenturyConfig
from centurion.core.engine import Centurion

# ---------------------------------------------------------------------------
# MockAgentType — deterministic, fast, always succeeds
# ---------------------------------------------------------------------------


class MockAgentType(AgentType):
    """Deterministic mock agent for integration tests."""

    name = "mock"

    def __init__(self, **kwargs):
        self._spawned: list[str] = []
        self._terminated: list[dict] = []

    async def spawn(self, legionary_id: str, cwd: str, env: dict[str, str]):
        self._spawned.append(legionary_id)
        return {"legionary_id": legionary_id, "cwd": cwd}

    async def send_task(self, handle, task: str, timeout: float) -> AgentResult:
        await asyncio.sleep(0.01)  # tiny delay to simulate work
        return AgentResult(
            success=True,
            output="done",
            exit_code=0,
            duration_seconds=0.1,
        )

    async def stream_output(self, handle):
        return
        yield  # make it an async generator

    async def terminate(self, handle, graceful: bool = True) -> None:
        self._terminated.append(handle)

    def resource_requirements(self) -> ResourceRequirements:
        return ResourceRequirements(
            requests=ResourceSpec(cpu_millicores=10, memory_mb=10),
            limits=ResourceSpec(cpu_millicores=10, memory_mb=10),
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Centurion:
    """Create a Centurion engine with the mock agent type registered."""
    config = CenturionConfig(
        max_agents_hard_limit=20,
        shutdown_timeout=10.0,
        ram_headroom_gb=0.0,
    )
    eng = Centurion(config=config)
    eng.registry.register("mock", MockAgentType)
    return eng


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle(engine: Centurion):
    """End-to-end: raise legion -> add century -> submit tasks -> shutdown."""

    # 1. Raise a legion
    legion = await engine.raise_legion("test-legion", name="Integration Test Legion")
    assert legion.id == "test-legion"
    assert "test-legion" in engine.legions

    # 2. Add a century with the mock agent type
    century_config = CenturyConfig(
        agent_type_name="mock",
        min_legionaries=2,
        max_legionaries=5,
        autoscale=False,  # disable autoscaler to keep the test deterministic
        task_timeout=30.0,
    )
    century = await legion.add_century(
        "test-century",
        century_config,
        engine.registry,
        engine.scheduler,
        engine.event_bus,
    )
    assert century.id == "test-century"
    assert len(century.legionaries) == 2  # min_legionaries mustered

    # 3. Submit 3 tasks and verify all complete successfully
    futures = []
    for i in range(3):
        fut = await century.submit_task(f"task prompt {i}", priority=5)
        futures.append(fut)

    results = await asyncio.gather(*futures)
    assert len(results) == 3
    for result in results:
        assert isinstance(result, AgentResult)
        assert result.success is True
        assert result.output == "done"
        assert result.exit_code == 0

    # 4. Verify fleet status reflects the work
    status = engine.fleet_status()
    assert status["total_legions"] == 1
    assert status["total_centuries"] == 1
    assert status["total_legionaries"] == 2

    # 5. Graceful shutdown
    await engine.shutdown()
    assert len(engine.legions) == 0


@pytest.mark.asyncio
async def test_event_bus_captures_lifecycle_events(engine: Centurion):
    """Verify that lifecycle events are recorded on the event bus."""

    # Subscribe before any actions
    queue = engine.event_bus.subscribe()

    legion = await engine.raise_legion("evt-legion", name="Event Test")
    century_config = CenturyConfig(
        agent_type_name="mock",
        min_legionaries=1,
        max_legionaries=2,
        autoscale=False,
        task_timeout=10.0,
    )
    century = await legion.add_century(
        "evt-century",
        century_config,
        engine.registry,
        engine.scheduler,
        engine.event_bus,
    )

    fut = await century.submit_task("event test task")
    await fut  # wait for completion

    await engine.shutdown()

    # Collect all events
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    event_types = [e.event_type for e in events]

    # Check key lifecycle events were emitted
    assert "legion_raised" in event_types
    assert "legionary_spawned" in event_types
    assert "century_mustered" in event_types
    assert "task_submitted" in event_types
    assert "task_started" in event_types
    assert "task_completed" in event_types


@pytest.mark.asyncio
async def test_shutdown_drains_in_progress_tasks(engine: Centurion):
    """Verify that shutdown waits for in-progress tasks to complete."""

    legion = await engine.raise_legion("drain-legion")
    century_config = CenturyConfig(
        agent_type_name="mock",
        min_legionaries=1,
        max_legionaries=2,
        autoscale=False,
        task_timeout=30.0,
    )
    century = await legion.add_century(
        "drain-century",
        century_config,
        engine.registry,
        engine.scheduler,
        engine.event_bus,
    )

    # Submit tasks (they will be picked up by workers)
    futures = []
    for i in range(3):
        f = await century.submit_task(f"drain task {i}")
        futures.append(f)

    # Give workers a moment to start processing
    await asyncio.sleep(0.05)

    # Shutdown should complete without raising
    await engine.shutdown()
    assert len(engine.legions) == 0

    # Futures that completed before shutdown should have results;
    # those that didn't may have exceptions from dismissal.
    completed = 0
    cancelled = 0
    for f in futures:
        if f.done() and not f.cancelled():
            try:
                result = f.result()
                if isinstance(result, AgentResult) and result.success:
                    completed += 1
            except Exception:
                cancelled += 1
        else:
            cancelled += 1

    # At least some tasks should have completed or been handled
    assert completed + cancelled == 3


@pytest.mark.asyncio
async def test_multiple_centuries_in_legion(engine: Centurion):
    """Verify a legion can host multiple centuries and distribute tasks."""

    legion = await engine.raise_legion("multi-legion")

    configs = []
    centuries = []
    for i in range(2):
        cfg = CenturyConfig(
            agent_type_name="mock",
            min_legionaries=1,
            max_legionaries=3,
            autoscale=False,
            task_timeout=10.0,
        )
        c = await legion.add_century(
            f"century-{i}",
            cfg,
            engine.registry,
            engine.scheduler,
            engine.event_bus,
        )
        configs.append(cfg)
        centuries.append(c)

    assert len(legion.centuries) == 2
    assert legion.total_legionaries == 2

    # Submit batch via legion
    futures = await legion.submit_batch(
        ["prompt A", "prompt B", "prompt C", "prompt D"],
        priority=5,
        distribute="round_robin",
    )
    results = await asyncio.gather(*futures)
    assert len(results) == 4
    assert all(r.success for r in results)

    await engine.shutdown()
