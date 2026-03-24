"""Centurion configuration — environment-aware with sensible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResourceSpec:
    """Resource specification for a single agent instance."""

    cpu_millicores: int = 500  # 1000 = 1 full core
    memory_mb: int = 250


@dataclass(frozen=True)
class ResourceRequirements:
    """K8s-inspired resource requests and limits per agent."""

    requests: ResourceSpec = field(default_factory=ResourceSpec)
    limits: ResourceSpec = field(default_factory=lambda: ResourceSpec(cpu_millicores=1000, memory_mb=500))


@dataclass
class CenturionConfig:
    """Top-level engine configuration. Reads from env vars with fallbacks."""

    # Database
    db_path: str = field(default_factory=lambda: os.getenv("CENTURION_DB_PATH", "data/centurion.db"))

    # Session directories
    session_base_dir: str = field(default_factory=lambda: os.getenv("CENTURION_SESSION_DIR", "/tmp/centurion-sessions"))

    # Hardware limits
    max_agents_hard_limit: int = field(
        default_factory=lambda: int(os.getenv("CENTURION_MAX_AGENTS", "0"))  # 0 = auto
    )
    ram_headroom_gb: float = field(
        default_factory=lambda: float(os.getenv("CENTURION_RAM_HEADROOM_GB", "2.0"))
    )  # Used as base value for dynamic headroom scaling under memory pressure

    # Autoscaling
    autoscale_check_interval: float = 10.0
    scale_down_idle_threshold: float = 60.0

    # Timeouts
    default_task_timeout: float = field(default_factory=lambda: float(os.getenv("CENTURION_TASK_TIMEOUT", "300")))
    agent_spawn_timeout: float = 30.0

    # Monitoring
    hardware_snapshot_interval: float = 60.0
    event_retention_days: int = 7

    # Claude CLI
    claude_binary: str = field(default_factory=lambda: os.getenv("CENTURION_CLAUDE_BIN", "claude"))
    claude_skip_permissions: bool = True

    # Claude API
    claude_model: str = field(default_factory=lambda: os.getenv("CENTURION_CLAUDE_MODEL", "claude-sonnet-4-6"))

    # Shutdown
    shutdown_timeout: float = field(default_factory=lambda: float(os.getenv("CENTURION_SHUTDOWN_TIMEOUT", "60")))

    # Event buffer
    event_buffer_size: int = field(default_factory=lambda: int(os.getenv("CENTURION_EVENT_BUFFER_SIZE", "1000")))

    # Sentinel (stale session reaper)
    sentinel_enabled: bool = field(default_factory=lambda: os.getenv("CENTURION_SENTINEL_ENABLED", "1") != "0")
    sentinel_scan_interval: float = field(
        default_factory=lambda: float(os.getenv("CENTURION_SENTINEL_INTERVAL", "300"))
    )
    sentinel_idle_threshold: float = field(
        default_factory=lambda: float(os.getenv("CENTURION_SENTINEL_IDLE_THRESHOLD", "1800"))
    )
    sentinel_max_runtime: float = field(
        default_factory=lambda: float(os.getenv("CENTURION_SENTINEL_MAX_RUNTIME", "7200"))
    )
    sentinel_dry_run: bool = field(default_factory=lambda: os.getenv("CENTURION_SENTINEL_DRY_RUN", "0") == "1")

    # Server
    host: str = "0.0.0.0"
    port: int = field(default_factory=lambda: int(os.getenv("CENTURION_PORT", "8100")))
