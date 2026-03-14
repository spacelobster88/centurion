"""CenturionScheduler — K8s-inspired admission control and resource tracking."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum

from centurion.agent_types.base import AgentType
from centurion.config import CenturionConfig, ResourceSpec

logger = logging.getLogger(__name__)


class MemoryPressureLevel(Enum):
    """Severity levels for memory pressure.

    Thresholds are evaluated against the ratio:
        actual_rss / (ram_available_mb - dynamic_headroom)
    """
    NORMAL   = "normal"    # ratio < 0.6 — no action needed
    WARN     = "warn"      # 0.6 <= ratio < 0.85 — slow down spawning
    CRITICAL = "critical"  # ratio >= 0.85 — halt spawning, begin scale-down


@dataclass
class SystemResources:
    """Snapshot of current system resources."""

    cpu_count: int = 0
    ram_total_mb: int = 0
    ram_available_mb: int = 0
    load_avg_1: float = 0.0
    load_avg_5: float = 0.0
    load_avg_15: float = 0.0
    memory_pressure: MemoryPressureLevel = MemoryPressureLevel.NORMAL


# Multipliers for dynamic headroom based on memory pressure.
# normal → base, warn → base*1.75, critical → base*2.5
_HEADROOM_MULTIPLIERS: dict[MemoryPressureLevel, float] = {
    MemoryPressureLevel.NORMAL: 1.0,
    MemoryPressureLevel.WARN: 1.75,
    MemoryPressureLevel.CRITICAL: 2.5,
}


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
    pid_registry: dict[str, int] = field(default_factory=dict)
    _probe_cache: SystemResources | None = field(default=None, repr=False)
    _probe_cache_time: float = field(default=0.0, repr=False)

    def probe_system(self, force: bool = False) -> SystemResources:
        """Detect current system resources (macOS + Linux)."""
        if not force and self._probe_cache and (time.monotonic() - self._probe_cache_time) < 2.0:
            return self._probe_cache
        cpu_count = os.cpu_count() or 1
        ram_total_mb = self._ram_total_mb()
        ram_available_mb = self._ram_available_mb()
        load_1, load_5, load_15 = os.getloadavg()
        pressure = self._memory_pressure_level()
        resources = SystemResources(
            cpu_count=cpu_count,
            ram_total_mb=ram_total_mb,
            ram_available_mb=ram_available_mb,
            load_avg_1=round(load_1, 2),
            load_avg_5=round(load_5, 2),
            load_avg_15=round(load_15, 2),
            memory_pressure=pressure,
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
        available_mb = self._ram_available_mb() - int(self._dynamic_headroom_gb() * 1024)
        ram_limit = max(1, available_mb // ram_per_agent_mb)
        recommended = min(cpu_limit, ram_limit)

        if self.config.max_agents_hard_limit > 0:
            return min(recommended, self.config.max_agents_hard_limit)
        return recommended

    def can_schedule(self, agent_type: AgentType) -> bool:
        """Check if system has capacity for one more agent of this type."""
        pressure = self._memory_pressure_level()
        if pressure != MemoryPressureLevel.NORMAL:
            logger.debug(
                "can_schedule: rejected agent_type=%s reason=memory_pressure level=%s",
                agent_type.name, pressure.value,
            )
            return False
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
        pressure = self._memory_pressure_level()
        if pressure != MemoryPressureLevel.NORMAL:
            logger.debug(
                "available_slots: returning 0 reason=memory_pressure level=%s",
                pressure.value,
            )
            return 0
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
                "memory_pressure": system.memory_pressure.value,
            },
            "allocated": {
                "cpu_millicores": self.allocated_cpu,
                "memory_mb": self.allocated_memory,
                "active_agents": self.active_agents,
            },
            "recommended_max_agents": self.recommended_max_agents(),
        }

    def register_pid(self, legionary_id: str, pid: int) -> None:
        """Register a process ID for a legionary."""
        self.pid_registry[legionary_id] = pid
        logger.debug("register_pid: legionary_id=%s pid=%d", legionary_id, pid)

    def unregister_pid(self, legionary_id: str) -> None:
        """Unregister a process ID for a legionary."""
        removed_pid = self.pid_registry.pop(legionary_id, None)
        logger.debug(
            "unregister_pid: legionary_id=%s pid=%s",
            legionary_id, removed_pid,
        )

    def _actual_memory_usage_mb(self, pids: list[int]) -> int:
        """Return total RSS in MB for the given PIDs.

        Uses ``ps -o rss= -p <pids>`` to get real RSS of agent processes.
        RSS is reported in kilobytes by ps; this method sums all values and
        converts to megabytes.

        Returns 0 on any failure or if no PIDs are provided.
        """
        if not pids:
            return 0
        try:
            pid_arg = ",".join(str(p) for p in pids)
            result = subprocess.run(
                ["ps", "-o", "rss=", "-p", pid_arg],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return 0
            total_kb = 0
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    total_kb += int(line)
            return total_kb // 1024
        except Exception:
            return 0

    def memory_audit(self) -> dict:
        """Compare actual RSS total vs allocated memory and log discrepancies.

        Returns a dict with audit results including actual_mb, allocated_mb,
        and ratio. Logs a WARNING if actual exceeds 1.5x allocated.
        Returns zeroed results gracefully if no PIDs are registered.
        """
        pids = list(self.pid_registry.values())
        actual_mb = self._actual_memory_usage_mb(pids)
        allocated_mb = self.allocated_memory
        ratio = actual_mb / max(allocated_mb, 1) if actual_mb > 0 else 0.0

        audit = {
            "actual_mb": actual_mb,
            "allocated_mb": allocated_mb,
            "ratio": round(ratio, 2),
            "pid_count": len(pids),
        }

        if actual_mb > 0 and allocated_mb > 0 and actual_mb > allocated_mb * 1.5:
            logger.warning(
                "memory_audit: actual RSS (%d MB) exceeds 1.5x allocated (%d MB), "
                "ratio=%.2f pid_count=%d",
                actual_mb, allocated_mb, ratio, len(pids),
            )
        else:
            logger.debug(
                "memory_audit: actual_mb=%d allocated_mb=%d ratio=%.2f pid_count=%d",
                actual_mb, allocated_mb, ratio, len(pids),
            )

        return audit

    # --- Private helpers ---

    def _dynamic_headroom_gb(self) -> float:
        """Return headroom in GB scaled by current memory pressure.

        Uses config.ram_headroom_gb as the base value and multiplies by
        a pressure-dependent factor:
          NORMAL   → base (e.g. 2.0 GB)
          WARN     → base * 1.75 (e.g. 3.5 GB)
          CRITICAL → base * 2.5  (e.g. 5.0 GB)
        """
        pressure = self._memory_pressure_level()
        multiplier = _HEADROOM_MULTIPLIERS.get(pressure, 1.0)
        return self.config.ram_headroom_gb * multiplier

    def _available_resources(self) -> ResourceSpec:
        cpu_count = os.cpu_count() or 1
        total_cpu = cpu_count * 1000  # millicores
        headroom_mb = int(self._dynamic_headroom_gb() * 1024)
        available_ram = max(0, self._ram_available_mb() - headroom_mb)
        return ResourceSpec(
            cpu_millicores=max(0, total_cpu - self.allocated_cpu),
            memory_mb=max(0, available_ram - self.allocated_memory),
        )

    @staticmethod
    def _memory_pressure_level() -> MemoryPressureLevel:
        """Query macOS memory pressure via sysctl kern.memorystatus_level.

        Returns MemoryPressureLevel based on the kernel-reported level:
          4 = NORMAL, 2 = WARN, 1 = CRITICAL.
        Falls back to NORMAL on non-Darwin platforms or any error.
        """
        if platform.system() != "Darwin":
            return MemoryPressureLevel.NORMAL
        try:
            out = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "kern.memorystatus_level"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            level = int(out)
            if level <= 1:
                return MemoryPressureLevel.CRITICAL
            elif level <= 2:
                return MemoryPressureLevel.WARN
            else:
                return MemoryPressureLevel.NORMAL
        except Exception:
            return MemoryPressureLevel.NORMAL

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
                free = spec = inactive = purgeable = 0
                for line in out.splitlines():
                    low = line.lower()
                    if "free" in low:
                        free = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                    elif "speculative" in low:
                        spec = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                    elif "inactive" in low:
                        inactive = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                    elif "purgeable" in low:
                        purgeable = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                page_size = 16384  # Apple Silicon default
                return ((free + spec + inactive + purgeable) * page_size) // (1024 * 1024)
            except Exception:
                return 4096  # fallback 4GB
        else:
            try:
                pages = os.sysconf("SC_AVPHYS_PAGES")
                page_size = os.sysconf("SC_PAGE_SIZE")
                return (page_size * pages) // (1024 * 1024)
            except Exception:
                return 4096
