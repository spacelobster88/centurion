"""TDD RED phase: tests for memory pressure detection (eng-1, eng-3)."""

import time
from unittest.mock import MagicMock, patch

from centurion.config import CenturionConfig
from centurion.core.scheduler import (
    CenturionScheduler,
    MemoryPressureLevel,
    SystemResources,
)


class TestMemoryPressureLevelEnum:
    def test_enum_exists(self):
        from centurion.core.scheduler import MemoryPressureLevel

        assert hasattr(MemoryPressureLevel, "NORMAL")
        assert hasattr(MemoryPressureLevel, "WARN")
        assert hasattr(MemoryPressureLevel, "CRITICAL")

    def test_enum_values(self):
        from centurion.core.scheduler import MemoryPressureLevel

        assert MemoryPressureLevel.NORMAL.value == "normal"
        assert MemoryPressureLevel.WARN.value == "warn"
        assert MemoryPressureLevel.CRITICAL.value == "critical"


class TestSystemResourcesPressureField:
    def test_default_pressure_is_normal(self):
        from centurion.core.scheduler import MemoryPressureLevel

        r = SystemResources()
        assert r.memory_pressure == MemoryPressureLevel.NORMAL

    def test_pressure_field_settable(self):
        from centurion.core.scheduler import MemoryPressureLevel

        r = SystemResources(memory_pressure=MemoryPressureLevel.CRITICAL)
        assert r.memory_pressure == MemoryPressureLevel.CRITICAL


class TestMemoryPressureLevelMethod:
    def test_returns_normal_for_high_level(self):
        from centurion.core.scheduler import MemoryPressureLevel

        sched = CenturionScheduler(config=CenturionConfig())
        with (
            patch("centurion.core.scheduler.platform") as mock_platform,
            patch("subprocess.run") as mock_run,
            patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384),
            patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=0),
        ):
            mock_platform.system.return_value = "Darwin"
            mock_run.return_value = MagicMock(stdout="4\n", returncode=0)
            result = sched._memory_pressure_level()
            assert result == MemoryPressureLevel.NORMAL

    def test_returns_warn_for_level_2(self):
        from centurion.core.scheduler import MemoryPressureLevel

        sched = CenturionScheduler(config=CenturionConfig())
        with (
            patch("centurion.core.scheduler.platform") as mock_platform,
            patch("subprocess.run") as mock_run,
            patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384),
            patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=0),
        ):
            mock_platform.system.return_value = "Darwin"
            mock_run.return_value = MagicMock(stdout="2\n", returncode=0)
            result = sched._memory_pressure_level()
            assert result == MemoryPressureLevel.WARN

    def test_returns_critical_for_level_1(self):
        from centurion.core.scheduler import MemoryPressureLevel

        sched = CenturionScheduler(config=CenturionConfig())
        with (
            patch("centurion.core.scheduler.platform") as mock_platform,
            patch("subprocess.run") as mock_run,
            patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384),
            patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=0),
        ):
            mock_platform.system.return_value = "Darwin"
            mock_run.return_value = MagicMock(stdout="1\n", returncode=0)
            result = sched._memory_pressure_level()
            assert result == MemoryPressureLevel.CRITICAL

    def test_returns_normal_on_failure(self):
        from centurion.core.scheduler import MemoryPressureLevel

        sched = CenturionScheduler(config=CenturionConfig())
        with patch("subprocess.run", side_effect=Exception("fail")):
            result = sched._memory_pressure_level()
            assert result == MemoryPressureLevel.NORMAL


class TestProbeCacheTTLReduced:
    def test_cache_ttl_is_2_seconds(self):
        sched = CenturionScheduler(config=CenturionConfig())
        first = sched.probe_system()
        # At 1.9s, should still be cached
        sched._probe_cache_time = time.monotonic() - 1.9
        cached = sched.probe_system()
        assert first is cached

        # At 2.1s, should refresh
        sched._probe_cache_time = time.monotonic() - 2.1
        refreshed = sched.probe_system()
        assert first is not refreshed


class TestProbeSystemForce:
    def test_force_bypasses_cache(self):
        sched = CenturionScheduler(config=CenturionConfig())
        first = sched.probe_system()
        forced = sched.probe_system(force=True)
        assert first is not forced


class TestToDictIncludesPressure:
    def test_to_dict_has_memory_pressure(self):
        sched = CenturionScheduler(config=CenturionConfig())
        d = sched.to_dict()
        assert "memory_pressure" in d["system"]


# ---------------------------------------------------------------------------
# eng-3: MemoryPressureLevel ordering support
# ---------------------------------------------------------------------------


class TestMemoryPressureLevelOrdering:
    """MemoryPressureLevel supports comparison so max() can pick the worse signal."""

    def test_critical_greater_than_warn(self):
        assert MemoryPressureLevel.CRITICAL > MemoryPressureLevel.WARN

    def test_warn_greater_than_normal(self):
        assert MemoryPressureLevel.WARN > MemoryPressureLevel.NORMAL

    def test_critical_greater_than_normal(self):
        assert MemoryPressureLevel.CRITICAL > MemoryPressureLevel.NORMAL

    def test_normal_less_than_warn(self):
        assert MemoryPressureLevel.NORMAL < MemoryPressureLevel.WARN

    def test_max_picks_worse(self):
        assert max(MemoryPressureLevel.NORMAL, MemoryPressureLevel.CRITICAL) == MemoryPressureLevel.CRITICAL
        assert max(MemoryPressureLevel.WARN, MemoryPressureLevel.NORMAL) == MemoryPressureLevel.WARN

    def test_equal_comparison(self):
        assert MemoryPressureLevel.WARN == MemoryPressureLevel.WARN
        assert not (MemoryPressureLevel.WARN > MemoryPressureLevel.WARN)


# ---------------------------------------------------------------------------
# eng-3: Compressor-aware _memory_pressure_level()
# ---------------------------------------------------------------------------


class TestCompressorAwarePressure:
    """_memory_pressure_level() combines kernel signal with compressor ratio."""

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=9000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_compressor_over_50pct_is_critical(self, mock_run, mock_platform, _comp, _total):
        """Compressor > 50% of total RAM -> at least CRITICAL."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "4\n"  # kernel says NORMAL
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.CRITICAL

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=6000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_compressor_over_30pct_is_warn(self, mock_run, mock_platform, _comp, _total):
        """Compressor > 30% of total RAM -> at least WARN."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "4\n"  # kernel says NORMAL
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.WARN

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=1000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_compressor_under_30pct_stays_normal(self, mock_run, mock_platform, _comp, _total):
        """Compressor <= 30% of total RAM -> compressor signal is NORMAL."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "4\n"  # kernel says NORMAL
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.NORMAL

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=1000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_kernel_critical_wins_over_normal_compressor(self, mock_run, mock_platform, _comp, _total):
        """Kernel CRITICAL beats compressor NORMAL -> CRITICAL."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "1\n"  # kernel says CRITICAL
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.CRITICAL

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=9000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_compressor_critical_wins_over_kernel_warn(self, mock_run, mock_platform, _comp, _total):
        """Compressor CRITICAL beats kernel WARN -> CRITICAL."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "2\n"  # kernel says WARN
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.CRITICAL

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=16384)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=6000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_both_warn_returns_warn(self, mock_run, mock_platform, _comp, _total):
        """Kernel WARN + compressor WARN -> WARN (max of equals)."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "2\n"  # kernel says WARN
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.WARN

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=0)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=5000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_zero_total_ram_no_crash(self, mock_run, mock_platform, _comp, _total):
        """Zero total RAM should not cause division by zero."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "4\n"
        mock_run.return_value = mock_result

        # Should not raise; compressor_ratio defaults to 0.0
        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.NORMAL

    @patch("centurion.core.scheduler.platform")
    def test_non_darwin_still_returns_normal(self, mock_platform):
        """Non-Darwin platforms skip compressor check entirely."""
        mock_platform.system.return_value = "Linux"
        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.NORMAL


# ---------------------------------------------------------------------------
# eng-3: Ordering NotImplemented for non-MemoryPressureLevel comparisons
# ---------------------------------------------------------------------------


class TestMemoryPressureLevelOrderingNotImplemented:
    """Comparisons with non-MemoryPressureLevel types return NotImplemented."""

    def test_lt_returns_not_implemented_for_int(self):
        result = MemoryPressureLevel.NORMAL.__lt__(42)
        assert result is NotImplemented

    def test_le_returns_not_implemented_for_str(self):
        result = MemoryPressureLevel.WARN.__le__("warn")
        assert result is NotImplemented

    def test_gt_returns_not_implemented_for_int(self):
        result = MemoryPressureLevel.CRITICAL.__gt__(2)
        assert result is NotImplemented

    def test_ge_returns_not_implemented_for_none(self):
        result = MemoryPressureLevel.NORMAL.__ge__(None)
        assert result is NotImplemented

    def test_le_works_for_same_type(self):
        assert MemoryPressureLevel.NORMAL <= MemoryPressureLevel.WARN
        assert MemoryPressureLevel.WARN <= MemoryPressureLevel.WARN

    def test_ge_works_for_same_type(self):
        assert MemoryPressureLevel.CRITICAL >= MemoryPressureLevel.WARN
        assert MemoryPressureLevel.WARN >= MemoryPressureLevel.WARN


# ---------------------------------------------------------------------------
# eng-3: Compressor boundary tests (exactly 30%, exactly 50%)
# ---------------------------------------------------------------------------


class TestCompressorBoundaryValues:
    """Test exact boundary conditions for compressor ratio thresholds."""

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=10000)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=3000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_compressor_exactly_30pct_stays_normal(self, mock_run, mock_platform, _comp, _total):
        """Compressor at exactly 30% (not >30%) should be NORMAL."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "4\n"  # kernel NORMAL
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.NORMAL

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=10000)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=3001)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_compressor_just_over_30pct_is_warn(self, mock_run, mock_platform, _comp, _total):
        """Compressor at 30.01% should be WARN."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "4\n"
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.WARN

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=10000)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=5000)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_compressor_exactly_50pct_stays_warn(self, mock_run, mock_platform, _comp, _total):
        """Compressor at exactly 50% (not >50%) should be WARN."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "4\n"
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.WARN

    @patch.object(CenturionScheduler, "_ram_total_mb", return_value=10000)
    @patch.object(CenturionScheduler, "_ram_compressor_mb", return_value=5001)
    @patch("centurion.core.scheduler.platform")
    @patch("centurion.core.scheduler.subprocess.run")
    def test_compressor_just_over_50pct_is_critical(self, mock_run, mock_platform, _comp, _total):
        """Compressor at 50.01% should be CRITICAL."""
        mock_platform.system.return_value = "Darwin"
        mock_result = MagicMock()
        mock_result.stdout = "4\n"
        mock_run.return_value = mock_result

        result = CenturionScheduler._memory_pressure_level()
        assert result == MemoryPressureLevel.CRITICAL
