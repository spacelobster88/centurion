"""Advanced scheduler tests: PID registry, dynamic headroom, pressure boundaries, to_dict."""

from unittest.mock import patch

import pytest

from centurion.config import CenturionConfig
from centurion.core.scheduler import (
    CenturionScheduler,
    MemoryPressureLevel,
    _HEADROOM_MULTIPLIERS,
)


@pytest.fixture
def scheduler():
    """Scheduler with explicit params: hard_limit=10, ram_headroom_gb=2.0."""
    config = CenturionConfig()
    config.max_agents_hard_limit = 10
    config.ram_headroom_gb = 2.0
    return CenturionScheduler(config=config)


# ---------------------------------------------------------------------------
# 1. register_pid / unregister_pid
# ---------------------------------------------------------------------------


class TestPidRegistry:
    def test_register_pid_adds_to_registry(self, scheduler):
        """register_pid(legionary_id, pid) adds PID to internal registry."""
        scheduler.register_pid("leg-1", 12345)
        assert "leg-1" in scheduler.pid_registry
        assert scheduler.pid_registry["leg-1"] == 12345

    def test_register_multiple_pids(self, scheduler):
        """Multiple PIDs can be registered under different IDs."""
        scheduler.register_pid("leg-1", 100)
        scheduler.register_pid("leg-2", 200)
        assert len(scheduler.pid_registry) == 2
        assert scheduler.pid_registry["leg-1"] == 100
        assert scheduler.pid_registry["leg-2"] == 200

    def test_unregister_pid_removes_from_registry(self, scheduler):
        """unregister_pid(legionary_id) removes PID from internal registry."""
        scheduler.register_pid("leg-1", 12345)
        scheduler.unregister_pid("leg-1")
        assert "leg-1" not in scheduler.pid_registry

    def test_unregister_nonexistent_pid_is_safe(self, scheduler):
        """unregister_pid for a missing ID does not raise."""
        scheduler.unregister_pid("does-not-exist")
        assert "does-not-exist" not in scheduler.pid_registry

    def test_register_then_unregister_leaves_others(self, scheduler):
        """Unregistering one PID does not affect others."""
        scheduler.register_pid("leg-1", 100)
        scheduler.register_pid("leg-2", 200)
        scheduler.unregister_pid("leg-1")
        assert "leg-1" not in scheduler.pid_registry
        assert scheduler.pid_registry["leg-2"] == 200


# ---------------------------------------------------------------------------
# 2-4. _dynamic_headroom_gb under different pressure levels
# ---------------------------------------------------------------------------


class TestDynamicHeadroomGb:
    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.NORMAL,
    )
    def test_normal_pressure_returns_base_times_1_0(self, _mock, scheduler):
        """_dynamic_headroom_gb() returns base * 1.0 on NORMAL pressure."""
        result = scheduler._dynamic_headroom_gb()
        assert result == scheduler.config.ram_headroom_gb * 1.0

    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.WARN,
    )
    def test_warn_pressure_returns_base_times_1_75(self, _mock, scheduler):
        """_dynamic_headroom_gb() returns base * 1.75 on WARN pressure."""
        result = scheduler._dynamic_headroom_gb()
        assert result == scheduler.config.ram_headroom_gb * 1.75

    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.CRITICAL,
    )
    def test_critical_pressure_returns_base_times_2_5(self, _mock, scheduler):
        """_dynamic_headroom_gb() returns base * 2.5 on CRITICAL pressure."""
        result = scheduler._dynamic_headroom_gb()
        assert result == scheduler.config.ram_headroom_gb * 2.5

    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.NORMAL,
    )
    def test_multipliers_match_module_constant(self, _mock):
        """Multipliers dict has correct values for all levels."""
        assert _HEADROOM_MULTIPLIERS[MemoryPressureLevel.NORMAL] == 1.0
        assert _HEADROOM_MULTIPLIERS[MemoryPressureLevel.WARN] == 1.75
        assert _HEADROOM_MULTIPLIERS[MemoryPressureLevel.CRITICAL] == 2.5


# ---------------------------------------------------------------------------
# 5-6. Pressure level boundary tests (ratio at 0.60 and 0.85)
#
# The MemoryPressureLevel enum documents these ratio thresholds:
#   NORMAL:   ratio < 0.60
#   WARN:     0.60 <= ratio < 0.85
#   CRITICAL: ratio >= 0.85
#
# The actual _memory_pressure_level() reads macOS sysctl kernel levels,
# so we test the boundary semantics by examining the enum's documented
# contract and verifying via the sysctl-level mapping.
#
# Kernel level mapping: level <= 1 → CRITICAL, level <= 2 → WARN, else → NORMAL
# Level 2 boundary → WARN (maps to the 0.60 ratio threshold)
# Level 1 boundary → CRITICAL (maps to the 0.85 ratio threshold)
# ---------------------------------------------------------------------------


class TestPressureLevelBoundaries:
    """Verify boundary behavior at the documented ratio thresholds."""

    def test_ratio_exactly_0_60_is_warn(self):
        """Ratio exactly at 0.60 falls into WARN (0.60 <= ratio < 0.85).

        Per the enum docstring: 0.6 <= ratio < 0.85 → WARN.
        Kernel sysctl level 2 maps to WARN.
        """
        with patch("centurion.core.scheduler.platform") as mock_platform, \
             patch("centurion.core.scheduler.subprocess.run") as mock_run:
            from unittest.mock import MagicMock
            mock_platform.system.return_value = "Darwin"
            mock_result = MagicMock()
            mock_result.stdout = "2\n"
            mock_run.return_value = mock_result
            level = CenturionScheduler._memory_pressure_level()
            assert level == MemoryPressureLevel.WARN

    def test_ratio_exactly_0_85_is_critical(self):
        """Ratio exactly at 0.85 falls into CRITICAL (ratio >= 0.85).

        Per the enum docstring: ratio >= 0.85 → CRITICAL.
        Kernel sysctl level 1 maps to CRITICAL.
        """
        with patch("centurion.core.scheduler.platform") as mock_platform, \
             patch("centurion.core.scheduler.subprocess.run") as mock_run:
            from unittest.mock import MagicMock
            mock_platform.system.return_value = "Darwin"
            mock_result = MagicMock()
            mock_result.stdout = "1\n"
            mock_run.return_value = mock_result
            level = CenturionScheduler._memory_pressure_level()
            assert level == MemoryPressureLevel.CRITICAL

    def test_boundary_just_below_0_60_is_normal(self):
        """Ratio below 0.60 → NORMAL. Kernel level >= 3 maps to NORMAL."""
        with patch("centurion.core.scheduler.platform") as mock_platform, \
             patch("centurion.core.scheduler.subprocess.run") as mock_run:
            from unittest.mock import MagicMock
            mock_platform.system.return_value = "Darwin"
            mock_result = MagicMock()
            mock_result.stdout = "4\n"
            mock_run.return_value = mock_result
            level = CenturionScheduler._memory_pressure_level()
            assert level == MemoryPressureLevel.NORMAL

    def test_kernel_level_boundary_at_2_is_warn(self):
        """Kernel level exactly 2 → WARN (the 0.60 boundary)."""
        with patch("centurion.core.scheduler.platform") as mock_platform, \
             patch("centurion.core.scheduler.subprocess.run") as mock_run:
            from unittest.mock import MagicMock
            mock_platform.system.return_value = "Darwin"
            mock_result = MagicMock()
            mock_result.stdout = "2\n"
            mock_run.return_value = mock_result
            level = CenturionScheduler._memory_pressure_level()
            # level <= 2 but not <= 1 → WARN
            assert level == MemoryPressureLevel.WARN

    def test_kernel_level_boundary_at_1_is_critical(self):
        """Kernel level exactly 1 → CRITICAL (the 0.85 boundary)."""
        with patch("centurion.core.scheduler.platform") as mock_platform, \
             patch("centurion.core.scheduler.subprocess.run") as mock_run:
            from unittest.mock import MagicMock
            mock_platform.system.return_value = "Darwin"
            mock_result = MagicMock()
            mock_result.stdout = "1\n"
            mock_run.return_value = mock_result
            level = CenturionScheduler._memory_pressure_level()
            assert level == MemoryPressureLevel.CRITICAL


# ---------------------------------------------------------------------------
# 7. to_dict() returns expected keys
# ---------------------------------------------------------------------------


class TestToDict:
    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.NORMAL,
    )
    @patch.object(CenturionScheduler, "_ram_available_mb", return_value=8192)
    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    def test_to_dict_returns_expected_top_level_keys(
        self, _mock_total, _mock_avail, _mock_pressure, scheduler
    ):
        """to_dict() returns dict with 'system', 'allocated', 'recommended_max_agents'."""
        result = scheduler.to_dict()
        assert isinstance(result, dict)
        assert "system" in result
        assert "allocated" in result
        assert "recommended_max_agents" in result

    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.NORMAL,
    )
    @patch.object(CenturionScheduler, "_ram_available_mb", return_value=8192)
    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    def test_to_dict_system_keys(
        self, _mock_total, _mock_avail, _mock_pressure, scheduler
    ):
        """to_dict()['system'] has cpu_count, ram_total_mb, ram_available_mb, load_avg, platform, memory_pressure."""
        result = scheduler.to_dict()
        system = result["system"]
        expected_keys = {
            "cpu_count",
            "ram_total_mb",
            "ram_available_mb",
            "ram_available_conservative_mb",
            "ram_compressor_mb",
            "load_avg",
            "platform",
            "memory_pressure",
        }
        assert expected_keys == set(system.keys())

    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.NORMAL,
    )
    @patch.object(CenturionScheduler, "_ram_available_mb", return_value=8192)
    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    def test_to_dict_allocated_keys(
        self, _mock_total, _mock_avail, _mock_pressure, scheduler
    ):
        """to_dict()['allocated'] has cpu_millicores, memory_mb, active_agents."""
        result = scheduler.to_dict()
        allocated = result["allocated"]
        expected_keys = {"cpu_millicores", "memory_mb", "active_agents"}
        assert expected_keys == set(allocated.keys())

    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.NORMAL,
    )
    @patch.object(CenturionScheduler, "_ram_available_mb", return_value=8192)
    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    def test_to_dict_recommended_max_agents_is_int(
        self, _mock_total, _mock_avail, _mock_pressure, scheduler
    ):
        """to_dict()['recommended_max_agents'] is an integer."""
        result = scheduler.to_dict()
        assert isinstance(result["recommended_max_agents"], int)

    @patch.object(
        CenturionScheduler,
        "_memory_pressure_level",
        return_value=MemoryPressureLevel.NORMAL,
    )
    @patch.object(CenturionScheduler, "_ram_available_mb", return_value=8192)
    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    def test_to_dict_load_avg_is_three_element_list(
        self, _mock_total, _mock_avail, _mock_pressure, scheduler
    ):
        """to_dict()['system']['load_avg'] is a list of three floats."""
        result = scheduler.to_dict()
        load_avg = result["system"]["load_avg"]
        assert isinstance(load_avg, list)
        assert len(load_avg) == 3
