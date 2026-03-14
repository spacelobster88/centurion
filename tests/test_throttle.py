"""Tests for Throttle — three-level memory alerts and auto-purge."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from centurion.core.scheduler import CenturionScheduler, MemoryPressureLevel, SystemResources
from centurion.config import CenturionConfig
from centurion.hardware.throttle import Throttle


def _make_throttle(
    active: int = 0,
    recommended: int = 10,
    pressure: MemoryPressureLevel = MemoryPressureLevel.NORMAL,
) -> tuple[Throttle, MagicMock]:
    """Build a Throttle with a mock scheduler and event bus.

    Returns (throttle, event_bus_mock).
    """
    config = CenturionConfig()
    config.ram_headroom_gb = 2.0

    scheduler = MagicMock(spec=CenturionScheduler)
    scheduler.config = config
    scheduler.active_agents = active
    scheduler.recommended_max_agents.return_value = recommended
    scheduler._memory_pressure_level.return_value = pressure
    scheduler.probe_system.return_value = SystemResources(
        cpu_count=8,
        ram_total_mb=16384,
        ram_available_mb=8192,
        memory_pressure=pressure,
    )

    event_bus = MagicMock()
    event_bus.emit = AsyncMock()

    throttle = Throttle(scheduler=scheduler, event_bus=event_bus)
    return throttle, event_bus


# ---------------------------------------------------------------------------
# Yellow / memory_caution — 70 % ratio threshold
# ---------------------------------------------------------------------------


class TestMemoryCaution:
    @pytest.mark.asyncio
    async def test_emits_memory_caution_at_yellow_ratio(self):
        """check() emits memory_caution when ratio >= 0.70 (but < 0.85)."""
        throttle, bus = _make_throttle(active=7, recommended=10)

        result = await throttle.check()

        bus.emit.assert_called_once()
        event_name = bus.emit.call_args[0][0]
        assert event_name == "memory_caution"
        assert result == MemoryPressureLevel.WARN

    @pytest.mark.asyncio
    async def test_emits_memory_caution_on_warn_pressure_low_ratio(self):
        """check() emits memory_caution when pressure is WARN but ratio < 0.70."""
        throttle, bus = _make_throttle(
            active=3, recommended=10, pressure=MemoryPressureLevel.WARN,
        )

        result = await throttle.check()

        bus.emit.assert_called_once()
        event_name = bus.emit.call_args[0][0]
        assert event_name == "memory_caution"
        assert result == MemoryPressureLevel.WARN


# ---------------------------------------------------------------------------
# Orange / memory_warning — 85 % ratio threshold
# ---------------------------------------------------------------------------


class TestMemoryWarning:
    @pytest.mark.asyncio
    async def test_emits_memory_warning_at_orange_ratio(self):
        """check() emits memory_warning when ratio >= 0.85 (but < 0.95)."""
        # 9/10 = 0.90, which is >= 0.85 but < 0.95
        throttle, bus = _make_throttle(active=9, recommended=10)

        result = await throttle.check()

        bus.emit.assert_called_once()
        event_name = bus.emit.call_args[0][0]
        assert event_name == "memory_warning"
        assert result == MemoryPressureLevel.WARN

    @pytest.mark.asyncio
    async def test_emits_memory_warning_on_warn_pressure_and_high_ratio(self):
        """check() emits memory_warning when WARN pressure + ratio >= 0.70."""
        # 7/10 = 0.70 ratio + WARN pressure => orange level
        throttle, bus = _make_throttle(
            active=7, recommended=10, pressure=MemoryPressureLevel.WARN,
        )

        result = await throttle.check()

        bus.emit.assert_called_once()
        event_name = bus.emit.call_args[0][0]
        assert event_name == "memory_warning"
        assert result == MemoryPressureLevel.WARN


# ---------------------------------------------------------------------------
# Red / memory_critical — 95 % ratio threshold
# ---------------------------------------------------------------------------


class TestMemoryCritical:
    @pytest.mark.asyncio
    async def test_emits_memory_critical_at_red_ratio(self):
        """check() emits memory_critical when ratio >= 0.95."""
        # 10/10 = 1.0
        throttle, bus = _make_throttle(active=10, recommended=10)

        result = await throttle.check()

        bus.emit.assert_called_once()
        event_name = bus.emit.call_args[0][0]
        assert event_name == "memory_critical"
        assert result == MemoryPressureLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_emits_memory_critical_on_critical_pressure(self):
        """check() emits memory_critical when pressure is CRITICAL regardless of ratio."""
        throttle, bus = _make_throttle(
            active=1, recommended=10, pressure=MemoryPressureLevel.CRITICAL,
        )

        result = await throttle.check()

        bus.emit.assert_called_once()
        event_name = bus.emit.call_args[0][0]
        assert event_name == "memory_critical"
        assert result == MemoryPressureLevel.CRITICAL


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------


class TestCheckReturnValue:
    @pytest.mark.asyncio
    async def test_returns_normal_when_below_thresholds(self):
        """check() returns NORMAL when ratio is low and no pressure."""
        throttle, bus = _make_throttle(active=1, recommended=10)

        result = await throttle.check()

        assert result == MemoryPressureLevel.NORMAL
        bus.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_normal_when_recommended_zero(self):
        """check() returns NORMAL when recommended_max_agents is 0."""
        throttle, bus = _make_throttle(active=0, recommended=0)

        result = await throttle.check()

        assert result == MemoryPressureLevel.NORMAL
        bus.emit.assert_not_called()


# ---------------------------------------------------------------------------
# Auto-purge on CRITICAL
# ---------------------------------------------------------------------------


class TestAutoPurge:
    @pytest.mark.asyncio
    @patch("centurion.hardware.throttle.platform")
    @patch("centurion.hardware.throttle.subprocess.run")
    async def test_purge_attempted_on_critical(self, mock_run, mock_platform):
        """Auto-purge via 'sudo -n purge' is attempted when level is CRITICAL."""
        mock_platform.system.return_value = "Darwin"
        mock_run.return_value = MagicMock(returncode=0)

        throttle, _ = _make_throttle(active=10, recommended=10)

        await throttle.check()

        mock_run.assert_called_once_with(
            ["sudo", "-n", "purge"],
            capture_output=True,
            timeout=5,
        )

    @pytest.mark.asyncio
    @patch("centurion.hardware.throttle.platform")
    @patch("centurion.hardware.throttle.subprocess.run")
    async def test_purge_not_attempted_on_non_darwin(self, mock_run, mock_platform):
        """Auto-purge is skipped on non-Darwin platforms."""
        mock_platform.system.return_value = "Linux"

        throttle, _ = _make_throttle(active=10, recommended=10)

        await throttle.check()

        mock_run.assert_not_called()
