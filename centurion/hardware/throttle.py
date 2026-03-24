"""Hardware throttle — monitors resource usage and emits warning events."""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import TYPE_CHECKING

from centurion.core.scheduler import MemoryPressureLevel

if TYPE_CHECKING:
    from centurion.core.events import EventBus
    from centurion.core.scheduler import CenturionScheduler

logger = logging.getLogger(__name__)


class Throttle:
    """Watches allocated-vs-recommended resource ratios and emits events.

    Three-level memory alerts based on ratio and real memory pressure:

    - Yellow  (70 % ratio or WARN pressure):   emits ``memory_caution``
    - Orange  (85 % ratio or WARN + high ratio): emits ``memory_warning``
    - Red     (95 % ratio or CRITICAL pressure): emits ``memory_critical``
    """

    # Ratio thresholds for each alert level.
    _YELLOW_RATIO = 0.70
    _ORANGE_RATIO = 0.85
    _RED_RATIO = 0.95

    def __init__(self, scheduler: CenturionScheduler, event_bus: EventBus) -> None:
        self.scheduler = scheduler
        self.event_bus = event_bus

    async def check(self) -> MemoryPressureLevel:
        """Evaluate current resource pressure and emit events if thresholds are breached.

        Returns the current :class:`MemoryPressureLevel` for callers to use.
        """
        recommended = self.scheduler.recommended_max_agents()
        if recommended <= 0:
            return MemoryPressureLevel.NORMAL

        active = self.scheduler.active_agents
        ratio = active / recommended

        # Query real memory pressure from the scheduler.
        pressure = self.scheduler._memory_pressure_level()

        # Gather payload data from a system probe.
        system = self.scheduler.probe_system()
        headroom_mb = int(self.scheduler.config.ram_headroom_gb * 1024)

        payload = {
            "active_agents": active,
            "recommended_max": recommended,
            "ratio": round(ratio, 2),
            "rss_total_mb": getattr(system, "rss_total_mb", 0),
            "ram_available_mb": system.ram_available_mb,
            "pressure_level": pressure.value,
            "headroom_mb": headroom_mb,
        }

        # Determine the effective alert level.
        # Red: 95% ratio or CRITICAL pressure.
        if ratio >= self._RED_RATIO or pressure == MemoryPressureLevel.CRITICAL:
            await self.event_bus.emit(
                "memory_critical",
                entity_type="hardware",
                entity_id="throttle",
                payload=payload,
            )
            self._attempt_purge()
            return MemoryPressureLevel.CRITICAL

        # Orange: 85% ratio, or WARN pressure combined with a high ratio (>=70%).
        if ratio >= self._ORANGE_RATIO or (
            pressure in (MemoryPressureLevel.WARN, MemoryPressureLevel.CRITICAL) and ratio >= self._YELLOW_RATIO
        ):
            await self.event_bus.emit(
                "memory_warning",
                entity_type="hardware",
                entity_id="throttle",
                payload=payload,
            )
            return MemoryPressureLevel.WARN

        # Yellow: 70% ratio or WARN pressure.
        if ratio >= self._YELLOW_RATIO or pressure == MemoryPressureLevel.WARN:
            await self.event_bus.emit(
                "memory_caution",
                entity_type="hardware",
                entity_id="throttle",
                payload=payload,
            )
            return MemoryPressureLevel.WARN

        return MemoryPressureLevel.NORMAL

    # ------------------------------------------------------------------
    # Auto-purge (best-effort, macOS only)
    # ------------------------------------------------------------------

    def _attempt_purge(self) -> None:
        """Run ``sudo -n purge`` on macOS to reclaim cached memory.

        This is purely best-effort: it never raises and never blocks for
        more than 5 seconds.  If the host is not macOS or the user lacks
        passwordless sudo, the call simply logs a warning and returns.
        """
        if platform.system() != "Darwin":
            return
        try:
            result = subprocess.run(
                ["sudo", "-n", "purge"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("Auto-purge succeeded (memory_critical)")
            else:
                stderr = result.stderr.decode(errors="replace").strip()
                logger.warning(
                    "Auto-purge exited with code %d: %s",
                    result.returncode,
                    stderr,
                )
        except Exception:
            logger.warning("Auto-purge failed", exc_info=True)
