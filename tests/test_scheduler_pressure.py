"""TDD RED phase: tests for memory pressure detection (eng-1)."""

import time
from unittest.mock import patch, MagicMock

import pytest

from centurion.config import CenturionConfig
from centurion.core.scheduler import CenturionScheduler, SystemResources


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
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="4\n", returncode=0)
            result = sched._memory_pressure_level()
            assert result == MemoryPressureLevel.NORMAL

    def test_returns_warn_for_level_2(self):
        from centurion.core.scheduler import MemoryPressureLevel
        sched = CenturionScheduler(config=CenturionConfig())
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="2\n", returncode=0)
            result = sched._memory_pressure_level()
            assert result == MemoryPressureLevel.WARN

    def test_returns_critical_for_level_1(self):
        from centurion.core.scheduler import MemoryPressureLevel
        sched = CenturionScheduler(config=CenturionConfig())
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="1\n", returncode=0)
            result = sched._memory_pressure_level()
            assert result == MemoryPressureLevel.CRITICAL

    def test_returns_normal_on_failure(self):
        from centurion.core.scheduler import MemoryPressureLevel
        sched = CenturionScheduler(config=CenturionConfig())
        with patch("subprocess.run", side_effect=Exception("fail")):
            result = sched._memory_pressure_level()
            assert result == MemoryPressureLevel.NORMAL


class TestRamAvailableIncludesInactivePurgeable:
    def test_includes_inactive_and_purgeable(self):
        vm_stat_output = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                              100.
Pages active:                            500.
Pages inactive:                          200.
Pages speculative:                        50.
Pages throttled:                           0.
Pages wired down:                        300.
Pages purgeable:                          80.
Pages stored in compressor:              100.
"""
        sched = CenturionScheduler(config=CenturionConfig())
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=vm_stat_output, returncode=0)
            with patch("platform.system", return_value="Darwin"):
                result = sched._ram_available_mb()
                # (100 + 50 + 200 + 80) * 16384 / (1024*1024) = 430 * 16384 / 1048576 = 6.71875 ~= 6 MB
                # Actually: 430 * 16384 = 7045120 / 1048576 = 6.71875... => int division = 6
                expected = (100 + 50 + 200 + 80) * 16384 // (1024 * 1024)
                assert result == expected


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
