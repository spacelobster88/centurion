"""CenturionScheduler — K8s-inspired admission control and resource tracking."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field

from centurion.agent_types.base import AgentType
from centurion.config import CenturionConfig, ResourceSpec

logger = logging.getLogger(__name__)


@dataclass
class SystemResources:
    """Snapshot of current system resources."""

    cpu_count: int = 0
    ram_total_mb: int = 0
    ram_available_mb: int = 0
    load_avg_1: float = 0.0
    load_avg_5: float = 0.0
    load_avg_15: float = 0.0


@dataclass
class CenturionScheduler:
    """Admission control: decides whether a new agent can be spawned.

    Tracks allocated resources across all active legionaries and compares
    against system capacity. Inspired by kube-scheduler.
    """

    config: CenturionConfig = field(default_factory=CenturionConfig)
    allocated_cpu: int = 0  # millicores
    allocated_memory: int = 0  # MB
    active_agents: int = 0
    _probe_cache: SystemResources | None = field(default=None, repr=False)
    _probe_cache_time: float = field(default=0.0, repr=False)

    def probe_system(self) -> SystemResources:
        """Detect current system resources (macOS + Linux)."""
        if self._probe_cache and (time.monotonic() - self._probe_cache_time) < 5.0:
            return self._probe_cache
        cpu_count = os.cpu_count() or 1
        ram_total_mb = self._ram_total_mb()
        ram_available_mb = self._ram_available_mb()
        load_1, load_5, load_15 = os.getloadavg()
        resources = SystemResources(
            cpu_count=cpu_count,
            ram_total_mb=ram_total_mb,
            ram_available_mb=ram_available_mb,
            load_avg_1=round(load_1, 2),
            load_avg_5=round(load_5, 2),
            load_avg_15=round(load_15, 2),
        )
        logger.debug(
            "probe_system: system resources snapshot cpu_count=%d ram_total_mb=%d "
            "ram_available_mb=%d load_avg=%.2f/%.2f/%.2f",
            resources.cpu_count, resources.ram_total_mb, resources.ram_available_mb,
            resources.load_avg_1, resources.load_avg_5, resources.load_avg_15,
        )
        self._probe_cache = resources
        self._probe_cache_time = time.monotonic()
        return resources

    def recommended_max_agents(self, ram_per_agent_mb: int = 250) -> int:
        """Calculate recommended maximum concurrent agents based on hardware."""
        cpu_count = os.cpu_count() or 1
        cpu_limit = cpu_count * 2  # I/O-bound heuristic
        available_mb = self._ram_available_mb() - int(self.config.ram_headroom_gb * 1024)
        ram_limit = max(1, available_mb // ram_per_agent_mb)
        recommended = min(cpu_limit, ram_limit)

        if self.config.max_agents_hard_limit > 0:
            return min(recommended, self.config.max_agents_hard_limit)
        return recommended

    def can_schedule(self, agent_type: AgentType) -> bool:
        """Check if system has capacity for one more agent of this type."""
        req = agent_type.resource_requirements().requests
        available = self._available_resources()
        result = True
        if available.cpu_millicores < req.cpu_millicores:
            result = False
        elif available.memory_mb < req.memory_mb:
            result = False
        elif self.config.max_agents_hard_limit > 0 and self.active_agents >= self.config.max_agents_hard_limit:
            result = False
        logger.debug(
            "can_schedule: agent_type=%s result=%s cpu_available=%d memory_available=%d",
            agent_type.name, result, available.cpu_millicores, available.memory_mb,
        )
        return result

    def available_slots(self, agent_type: AgentType) -> int:
        """How many more agents of this type can fit."""
        req = agent_type.resource_requirements().requests
        available = self._available_resources()
        cpu_slots = available.cpu_millicores // max(req.cpu_millicores, 1)
        mem_slots = available.memory_mb // max(req.memory_mb, 1)
        slots = min(cpu_slots, mem_slots)
        if self.config.max_agents_hard_limit > 0:
            hard_slots = self.config.max_agents_hard_limit - self.active_agents
            slots = min(slots, hard_slots)
        return max(0, slots)

    def allocate(self, agent_type: AgentType) -> None:
        """Reserve resources for a new agent."""
        req = agent_type.resource_requirements().requests
        self.allocated_cpu += req.cpu_millicores
        self.allocated_memory += req.memory_mb
        self.active_agents += 1
        logger.debug(
            "allocate: agent_type=%s allocated_cpu=%d allocated_memory=%d active_agents=%d",
            agent_type.name, self.allocated_cpu, self.allocated_memory, self.active_agents,
        )

    def release(self, agent_type: AgentType) -> None:
        """Free resources when an agent terminates."""
        req = agent_type.resource_requirements().requests
        self.allocated_cpu = max(0, self.allocated_cpu - req.cpu_millicores)
        self.allocated_memory = max(0, self.allocated_memory - req.memory_mb)
        self.active_agents = max(0, self.active_agents - 1)
        logger.debug(
            "release: agent_type=%s allocated_cpu=%d allocated_memory=%d active_agents=%d",
            agent_type.name, self.allocated_cpu, self.allocated_memory, self.active_agents,
        )

    def to_dict(self) -> dict:
        system = self.probe_system()
        return {
            "system": {
                "cpu_count": system.cpu_count,
                "ram_total_mb": system.ram_total_mb,
                "ram_available_mb": system.ram_available_mb,
                "load_avg": [system.load_avg_1, system.load_avg_5, system.load_avg_15],
                "platform": platform.system(),
            },
            "allocated": {
                "cpu_millicores": self.allocated_cpu,
                "memory_mb": self.allocated_memory,
                "active_agents": self.active_agents,
            },
            "recommended_max_agents": self.recommended_max_agents(),
        }

    # --- Private helpers ---

    def _available_resources(self) -> ResourceSpec:
        cpu_count = os.cpu_count() or 1
        total_cpu = cpu_count * 1000  # millicores
        headroom_mb = int(self.config.ram_headroom_gb * 1024)
        available_ram = max(0, self._ram_available_mb() - headroom_mb)
        return ResourceSpec(
            cpu_millicores=max(0, total_cpu - self.allocated_cpu),
            memory_mb=max(0, available_ram - self.allocated_memory),
        )

    @staticmethod
    def _ram_total_mb() -> int:
        if platform.system() == "Darwin":
            try:
                out = subprocess.run(
                    ["/usr/sbin/sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip()
                return int(out) // (1024 * 1024)
            except Exception:
                return 8192  # fallback 8GB
        else:
            try:
                page_size = os.sysconf("SC_PAGE_SIZE")
                pages = os.sysconf("SC_PHYS_PAGES")
                return (page_size * pages) // (1024 * 1024)
            except Exception:
                return 8192

    @staticmethod
    def _ram_available_mb() -> int:
        if platform.system() == "Darwin":
            try:
                out = subprocess.run(
                    ["vm_stat"], capture_output=True, text=True, timeout=5,
                ).stdout
                free = spec = 0
                for line in out.splitlines():
                    if "free" in line.lower():
                        free = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                    elif "speculative" in line.lower():
                        spec = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                page_size = 16384  # Apple Silicon default
                return ((free + spec) * page_size) // (1024 * 1024)
            except Exception:
                return 4096  # fallback 4GB
        else:
            try:
                pages = os.sysconf("SC_AVPHYS_PAGES")
                page_size = os.sysconf("SC_PAGE_SIZE")
                return (page_size * pages) // (1024 * 1024)
            except Exception:
                return 4096
