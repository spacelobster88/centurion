"""Hardware throttle — monitors resource usage and emits warning events."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from centurion.core.events import EventBus
    from centurion.core.scheduler import CenturionScheduler


class Throttle:
    """Watches allocated-vs-recommended resource ratios and emits events.

    - Above 80 %: emits ``hardware_warning``
    - At 100 %:   emits ``resource_exhausted``
    """

    def __init__(self, scheduler: CenturionScheduler, event_bus: EventBus) -> None:
        self.scheduler = scheduler
        self.event_bus = event_bus

    async def check(self) -> None:
        """Evaluate current resource pressure and emit events if thresholds are breached."""
        recommended = self.scheduler.recommended_max_agents()
        if recommended <= 0:
            return

        active = self.scheduler.active_agents
        ratio = active / recommended

        if ratio >= 1.0:
            await self.event_bus.emit(
                "resource_exhausted",
                entity_type="hardware",
                entity_id="throttle",
                payload={
                    "active_agents": active,
                    "recommended_max": recommended,
                    "ratio": round(ratio, 2),
                },
            )
        elif ratio >= 0.8:
            await self.event_bus.emit(
                "hardware_warning",
                entity_type="hardware",
                entity_id="throttle",
                payload={
                    "active_agents": active,
                    "recommended_max": recommended,
                    "ratio": round(ratio, 2),
                },
            )
