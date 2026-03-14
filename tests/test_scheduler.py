"""Tests for CenturionScheduler — resource tracking and admission control."""

import time
from unittest.mock import patch, MagicMock

import pytest

from centurion.config import CenturionConfig
from centurion.core.scheduler import CenturionScheduler, SystemResources, MemoryPressureLevel

from tests.conftest import MockAgentType


@pytest.fixture
def scheduler():
    """Create a scheduler with default config."""
    return CenturionScheduler(config=CenturionConfig())


@pytest.fixture
def mock_agent():
    """A mock agent type with minimal resource requirements (10m CPU, 10 MB RAM)."""
    return MockAgentType()


async def test_probe_system(scheduler):
    """System probe detects valid CPU count and RAM values."""
    resources = scheduler.probe_system()

    assert resources.cpu_count > 0
    assert resources.ram_total_mb > 0
    assert resources.ram_available_mb > 0
    assert resources.load_avg_1 >= 0
    assert resources.load_avg_5 >= 0
    assert resources.load_avg_15 >= 0


async def test_recommended_max(scheduler):
    """Recommended max agents is a positive number on any real machine."""
    recommended = scheduler.recommended_max_agents()

    assert recommended > 0


async def test_allocate_release(scheduler, mock_agent):
    """Allocating resources increments counters; releasing restores them."""
    assert scheduler.active_agents == 0
    assert scheduler.allocated_cpu == 0
    assert scheduler.allocated_memory == 0

    scheduler.allocate(mock_agent)

    assert scheduler.active_agents == 1
    assert scheduler.allocated_cpu == 10  # MockAgentType requests 10 millicores
    assert scheduler.allocated_memory == 10  # MockAgentType requests 10 MB

    scheduler.allocate(mock_agent)

    assert scheduler.active_agents == 2
    assert scheduler.allocated_cpu == 20
    assert scheduler.allocated_memory == 20

    scheduler.release(mock_agent)

    assert scheduler.active_agents == 1
    assert scheduler.allocated_cpu == 10
    assert scheduler.allocated_memory == 10

    scheduler.release(mock_agent)

    assert scheduler.active_agents == 0
    assert scheduler.allocated_cpu == 0
    assert scheduler.allocated_memory == 0


async def test_can_schedule(mock_agent):
    """After allocating until full, can_schedule returns False."""
    # Use zero RAM headroom so the memory check passes on any machine,
    # and a hard limit to make the test deterministic.
    config = CenturionConfig()
    config.ram_headroom_gb = 0.0
    config.max_agents_hard_limit = 3
    sched = CenturionScheduler(config=config)

    assert sched.can_schedule(mock_agent) is True

    sched.allocate(mock_agent)
    sched.allocate(mock_agent)
    sched.allocate(mock_agent)

    # Hard limit of 3 reached
    assert sched.active_agents == 3
    assert sched.can_schedule(mock_agent) is False

    # Release one and verify scheduling is possible again
    sched.release(mock_agent)
    assert sched.can_schedule(mock_agent) is True


# ---------------------------------------------------------------------------
# Probe cache TTL tests (S9 fix)
# ---------------------------------------------------------------------------

class TestProbeCacheTTL:
    def test_probe_system_returns_system_resources(self, scheduler):
        """probe_system returns a SystemResources dataclass."""
        result = scheduler.probe_system()
        assert isinstance(result, SystemResources)
        assert result.cpu_count > 0
        assert result.ram_total_mb > 0

    def test_probe_system_uses_cache_within_ttl(self, scheduler):
        """Within the 2s TTL, probe_system returns the cached object (same id)."""
        first = scheduler.probe_system()
        second = scheduler.probe_system()
        # Same object means cache was used, no re-probe
        assert first is second

    def test_probe_system_refreshes_after_ttl(self, scheduler):
        """After the 2s TTL expires, probe_system fetches fresh data."""
        first = scheduler.probe_system()
        # Simulate time passing beyond the 2s TTL by backdating the cache timestamp
        scheduler._probe_cache_time = time.monotonic() - 3.0
        second = scheduler.probe_system()
        # A new object should have been created (different identity)
        assert first is not second
        assert isinstance(second, SystemResources)

    def test_probe_cache_respects_exact_boundary(self, scheduler):
        """Cache is still valid at exactly 1.9s but stale at 2.1s."""
        first = scheduler.probe_system()

        # Still within TTL at 1.9s
        scheduler._probe_cache_time = time.monotonic() - 1.9
        within_ttl = scheduler.probe_system()
        assert first is within_ttl

        # Beyond TTL at 2.1s
        scheduler._probe_cache_time = time.monotonic() - 2.1
        beyond_ttl = scheduler.probe_system()
        assert first is not beyond_ttl


# ---------------------------------------------------------------------------
# can_schedule respects hard limits
# ---------------------------------------------------------------------------

class TestCanScheduleHardLimits:
    def test_can_schedule_respects_hard_limit_zero_means_unlimited(self):
        """When max_agents_hard_limit is 0, scheduling is not capped by it."""
        config = CenturionConfig()
        config.max_agents_hard_limit = 0
        config.ram_headroom_gb = 0.0
        sched = CenturionScheduler(config=config)
        agent = MockAgentType()
        # Should be able to schedule with hard limit disabled
        assert sched.can_schedule(agent) is True

    def test_can_schedule_blocks_at_hard_limit(self):
        """When active_agents reaches hard limit, can_schedule returns False."""
        config = CenturionConfig()
        config.max_agents_hard_limit = 2
        config.ram_headroom_gb = 0.0
        sched = CenturionScheduler(config=config)
        agent = MockAgentType()

        sched.allocate(agent)
        sched.allocate(agent)
        assert sched.active_agents == 2
        assert sched.can_schedule(agent) is False


# ---------------------------------------------------------------------------
# available_slots calculation
# ---------------------------------------------------------------------------

class TestAvailableSlots:
    def test_available_slots_with_hard_limit(self):
        """available_slots accounts for the hard limit cap."""
        config = CenturionConfig()
        config.max_agents_hard_limit = 5
        config.ram_headroom_gb = 0.0
        sched = CenturionScheduler(config=config)
        agent = MockAgentType()

        slots_before = sched.available_slots(agent)
        # Hard limit is 5 with 0 active, so hard_slots = 5
        # slots should be min(cpu_slots, mem_slots, hard_slots) and >= 0
        assert slots_before >= 0
        assert slots_before <= 5  # cannot exceed hard limit

        sched.allocate(agent)
        sched.allocate(agent)
        slots_after = sched.available_slots(agent)
        # Used 2, so hard_slots = 3; slots decreased
        assert slots_after <= slots_before
        assert slots_after <= 3

    def test_available_slots_never_negative(self):
        """available_slots returns 0, never a negative number."""
        config = CenturionConfig()
        config.max_agents_hard_limit = 1
        config.ram_headroom_gb = 0.0
        sched = CenturionScheduler(config=config)
        agent = MockAgentType()

        sched.allocate(agent)
        sched.allocate(agent)  # over-allocate beyond hard limit
        slots = sched.available_slots(agent)
        assert slots >= 0


# ---------------------------------------------------------------------------
# MemoryPressureLevel enum tests
# ---------------------------------------------------------------------------

class TestMemoryPressureLevel:
    def test_enum_has_normal(self):
        assert MemoryPressureLevel.NORMAL.value == "normal"

    def test_enum_has_warn(self):
        assert MemoryPressureLevel.WARN.value == "warn"

    def test_enum_has_critical(self):
        assert MemoryPressureLevel.CRITICAL.value == "critical"

    def test_enum_members_count(self):
        """Exactly three members exist."""
        assert set(MemoryPressureLevel) == {
            MemoryPressureLevel.NORMAL,
            MemoryPressureLevel.WARN,
            MemoryPressureLevel.CRITICAL,
        }


# ---------------------------------------------------------------------------
# _memory_pressure_level() tests
# ---------------------------------------------------------------------------

class TestMemoryPressureLevelDetection:
    """Test _memory_pressure_level returns correct enum for sysctl output."""

    def _mock_sysctl(self, level_str: str):
        """Build a MagicMock that simulates sysctl returning level_str."""
        mock_result = MagicMock()
        mock_result.stdout = f"{level_str}\n"
        return mock_result

    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_level_4_is_normal(self, mock_run, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_run.return_value = self._mock_sysctl("4")
        assert CenturionScheduler._memory_pressure_level() == MemoryPressureLevel.NORMAL

    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_level_2_is_warn(self, mock_run, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_run.return_value = self._mock_sysctl("2")
        assert CenturionScheduler._memory_pressure_level() == MemoryPressureLevel.WARN

    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_level_1_is_critical(self, mock_run, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_run.return_value = self._mock_sysctl("1")
        assert CenturionScheduler._memory_pressure_level() == MemoryPressureLevel.CRITICAL

    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_level_0_is_critical(self, mock_run, mock_platform):
        """Level 0 (<=1) should also be CRITICAL."""
        mock_platform.system.return_value = "Darwin"
        mock_run.return_value = self._mock_sysctl("0")
        assert CenturionScheduler._memory_pressure_level() == MemoryPressureLevel.CRITICAL

    @patch("centurion.core.scheduler.platform")
    def test_non_darwin_returns_normal(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        assert CenturionScheduler._memory_pressure_level() == MemoryPressureLevel.NORMAL

    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run", side_effect=Exception("fail"))
    def test_exception_returns_normal(self, mock_run, mock_platform):
        mock_platform.system.return_value = "Darwin"
        assert CenturionScheduler._memory_pressure_level() == MemoryPressureLevel.NORMAL


# ---------------------------------------------------------------------------
# _ram_available_mb() tests — verifies inactive + purgeable pages included
# ---------------------------------------------------------------------------

class TestRamAvailableMb:
    """Test that _ram_available_mb correctly parses vm_stat including inactive and purgeable."""

    VM_STAT_OUTPUT = """\
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               10000.
Pages active:                             50000.
Pages inactive:                            5000.
Pages speculative:                         2000.
Pages throttled:                              0.
Pages wired down:                         30000.
Pages purgeable:                           3000.
"Translation faults":                  123456789.
Pages copy-on-write:                    1234567.
Pages zero filled:                     12345678.
Pages reactivated:                       100000.
Pages purged:                             50000.
"""

    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_includes_inactive_and_purgeable(self, mock_run, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = self.VM_STAT_OUTPUT
        mock_run.return_value = mock_result

        result = CenturionScheduler._ram_available_mb()

        # free=10000, speculative=2000, inactive=5000, purgeable=3000
        # total_pages = 20000, page_size = 16384
        # bytes = 20000 * 16384 = 327,680,000
        # MB = 327680000 // (1024*1024) = 312
        expected = (20000 * 16384) // (1024 * 1024)
        assert result == expected

    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_without_purgeable_line(self, mock_run, mock_platform):
        """If purgeable line is missing, purgeable defaults to 0."""
        mock_platform.system.return_value = "Darwin"
        # Remove purgeable line
        output = "\n".join(
            line for line in self.VM_STAT_OUTPUT.splitlines()
            if "purgeable" not in line.lower()
        )
        mock_result = MagicMock()
        mock_result.stdout = output
        mock_run.return_value = mock_result

        result = CenturionScheduler._ram_available_mb()
        # free=10000 + speculative=2000 + inactive=5000 + purgeable=0 = 17000
        expected = (17000 * 16384) // (1024 * 1024)
        assert result == expected


# ---------------------------------------------------------------------------
# probe_system(force=True) bypasses cache
# ---------------------------------------------------------------------------

class TestProbeForceBypassesCache:
    def test_force_returns_new_object(self, scheduler):
        """probe_system(force=True) returns a fresh object even within TTL."""
        first = scheduler.probe_system()
        forced = scheduler.probe_system(force=True)
        # force=True should create a new SystemResources object
        assert first is not forced
        assert isinstance(forced, SystemResources)


# ---------------------------------------------------------------------------
# Admission gate under memory pressure
# ---------------------------------------------------------------------------

class TestAdmissionGateWithPressure:
    """can_schedule() and available_slots() reject work under memory pressure."""

    @pytest.fixture
    def sched(self):
        config = CenturionConfig()
        config.ram_headroom_gb = 0.0
        config.max_agents_hard_limit = 10
        return CenturionScheduler(config=config)

    @pytest.fixture
    def agent(self):
        return MockAgentType()

    # -- can_schedule ---------------------------------------------------------

    @patch.object(CenturionScheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.WARN)
    def test_can_schedule_false_on_warn(self, _mock, sched, agent):
        """can_schedule returns False when pressure is WARN."""
        assert sched.can_schedule(agent) is False

    @patch.object(CenturionScheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.CRITICAL)
    def test_can_schedule_false_on_critical(self, _mock, sched, agent):
        """can_schedule returns False when pressure is CRITICAL."""
        assert sched.can_schedule(agent) is False

    @patch.object(CenturionScheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.NORMAL)
    def test_can_schedule_true_on_normal(self, _mock, sched, agent):
        """can_schedule returns True when pressure is NORMAL and resources available."""
        assert sched.can_schedule(agent) is True

    # -- available_slots ------------------------------------------------------

    @patch.object(CenturionScheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.WARN)
    def test_available_slots_zero_on_warn(self, _mock, sched, agent):
        """available_slots returns 0 when pressure is WARN."""
        assert sched.available_slots(agent) == 0

    @patch.object(CenturionScheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.CRITICAL)
    def test_available_slots_zero_on_critical(self, _mock, sched, agent):
        """available_slots returns 0 when pressure is CRITICAL."""
        assert sched.available_slots(agent) == 0

    @patch.object(CenturionScheduler, "_memory_pressure_level", return_value=MemoryPressureLevel.NORMAL)
    def test_available_slots_positive_on_normal(self, _mock, sched, agent):
        """available_slots returns > 0 when pressure is NORMAL and resources available."""
        assert sched.available_slots(agent) > 0
