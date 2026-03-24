"""Legion — a deployment group (collection of centuries).

Equivalent to a K8s Namespace with ResourceQuota.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from centurion.core.century import Century, CenturyConfig

if TYPE_CHECKING:
    import asyncio

    from centurion.agent_types.base import AgentResult
    from centurion.agent_types.registry import AgentTypeRegistry
    from centurion.core.events import EventBus
    from centurion.core.scheduler import CenturionScheduler


@dataclass
class LegionQuota:
    """Resource quota for a legion (like K8s ResourceQuota)."""

    max_centuries: int = 10
    max_legionaries: int = 100
    max_cpu_millicores: int = 0  # 0 = unlimited
    max_memory_mb: int = 0  # 0 = unlimited


class Legion:
    """A deployment group — collection of centuries for a campaign."""

    def __init__(
        self,
        legion_id: str,
        name: str = "",
        quota: LegionQuota | None = None,
    ) -> None:
        self.id = legion_id
        self.name = name or legion_id
        self.quota = quota or LegionQuota()
        self.centuries: dict[str, Century] = {}
        self.created_at: float = time.time()

    async def add_century(
        self,
        century_id: str | None,
        config: CenturyConfig,
        registry: AgentTypeRegistry,
        scheduler: CenturionScheduler | None = None,
        event_bus: EventBus | None = None,
    ) -> Century:
        """Create and add a new century to this legion."""
        century_id = century_id or f"cent-{uuid.uuid4().hex[:8]}"

        # Quota check
        if len(self.centuries) >= self.quota.max_centuries:
            raise ValueError(f"Legion {self.id} quota exceeded: max {self.quota.max_centuries} centuries")
        total_legs = sum(len(c.legionaries) for c in self.centuries.values())
        if total_legs + config.min_legionaries > self.quota.max_legionaries:
            raise ValueError(f"Legion {self.id} quota exceeded: max {self.quota.max_legionaries} legionaries")

        agent_type = registry.create(config.agent_type_name, **config.agent_type_config)
        century = Century(
            century_id=century_id,
            config=config,
            agent_type=agent_type,
            scheduler=scheduler,
            event_bus=event_bus,
        )
        await century.muster()
        await century.start()
        self.centuries[century_id] = century

        if event_bus:
            await event_bus.emit(
                "century_mustered",
                entity_type="century",
                entity_id=century_id,
                payload={
                    "legion_id": self.id,
                    "agent_type": config.agent_type_name,
                    "legionaries": len(century.legionaries),
                },
            )
        return century

    async def remove_century(self, century_id: str) -> None:
        century = self.centuries.pop(century_id, None)
        if century:
            await century.dismiss()

    async def dismiss_all(self) -> None:
        """Dismiss all centuries in this legion."""
        for century in list(self.centuries.values()):
            await century.dismiss()
        self.centuries.clear()

    async def broadcast(self, message: str) -> dict:
        """Broadcast to all centuries in this legion."""
        total_delivered = 0
        total_failed = 0
        century_results = {}
        for century_id, century in self.centuries.items():
            results = await century.broadcast(message)
            delivered = sum(1 for r in results if r.get("delivered"))
            failed = len(results) - delivered
            total_delivered += delivered
            total_failed += failed
            century_results[century_id] = results
        return {
            "legion_id": self.id,
            "total_delivered": total_delivered,
            "total_failed": total_failed,
            "centuries": century_results,
        }

    async def submit_batch(
        self,
        prompts: list[str],
        priority: int = 5,
        distribute: str = "round_robin",
    ) -> list[asyncio.Future[AgentResult]]:
        """Distribute tasks across this legion's centuries."""
        centuries = list(self.centuries.values())
        if not centuries:
            raise ValueError(f"Legion {self.id} has no centuries")

        futures: list[asyncio.Future[AgentResult]] = []

        if distribute == "round_robin":
            for i, prompt in enumerate(prompts):
                century = centuries[i % len(centuries)]
                f = await century.submit_task(prompt, priority)
                futures.append(f)

        elif distribute == "least_loaded":
            for prompt in prompts:
                century = min(centuries, key=lambda c: c.task_queue.qsize())
                f = await century.submit_task(prompt, priority)
                futures.append(f)

        elif distribute == "random":
            for prompt in prompts:
                century = random.choice(centuries)
                f = await century.submit_task(prompt, priority)
                futures.append(f)

        else:
            raise ValueError(f"Unknown distribution strategy: {distribute!r}")

        return futures

    @property
    def total_legionaries(self) -> int:
        return sum(len(c.legionaries) for c in self.centuries.values())

    def status_report(self) -> dict:
        return {
            "legion_id": self.id,
            "name": self.name,
            "quota": {
                "max_centuries": self.quota.max_centuries,
                "max_legionaries": self.quota.max_legionaries,
            },
            "centuries_count": len(self.centuries),
            "total_legionaries": self.total_legionaries,
            "centuries": {cid: c.status_report() for cid, c in self.centuries.items()},
        }
