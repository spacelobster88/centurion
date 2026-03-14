# Memory Pressure Subsystem — Design Decision Record

**Status:** Proposed
**Date:** 2026-03-09
**Scope:** `centurion.core.scheduler`, `centurion.hardware.throttle`, `centurion.core.century`

---

## 1. Problem Statement

The current scheduler relies on `vm_stat` free+speculative pages to estimate available RAM. This metric is misleading on macOS, where the OS aggressively caches files into "inactive" pages and reports low "free" counts even when memory is plentiful. Additionally:

- The static `ram_headroom_gb` (default 2 GB) does not adapt to actual process memory consumption.
- The `Throttle` class only monitors the agent-count-to-recommended ratio (80% / 100%), but has no awareness of real memory pressure.
- The Optio autoscaler scales down only when the queue is empty, with no feedback loop from memory pressure to scaling decisions.

## 2. MemoryPressureLevel Enum

A new `MemoryPressureLevel` enum will be added to `centurion.core.scheduler`:

```python
from enum import Enum

class MemoryPressureLevel(Enum):
    """Severity levels for memory pressure.

    Thresholds are evaluated against the ratio:
        actual_rss / (ram_available_mb - dynamic_headroom)
    """
    NORMAL   = "normal"    # ratio < 0.6 — no action needed
    WARN     = "warn"      # 0.6 <= ratio < 0.85 — slow down spawning
    CRITICAL = "critical"  # ratio >= 0.85 — halt spawning, begin scale-down
```

**Why three levels instead of two?**  The existing `Throttle` uses a two-level approach (80%/100% of agent slots), but memory exhaustion is a harder cliff than CPU saturation. A WARN level gives the Optio time to stop scaling up before reaching the CRITICAL level where active scale-down is required.

**Threshold rationale:**
- 0.6 is chosen because macOS memory pressure transitions from "green" to "yellow" around this range.
- 0.85 provides a buffer before the OS starts compressing or swapping, which degrades Claude CLI subprocess performance sharply.

## 3. SystemResources Extension

The existing `SystemResources` dataclass gains two new fields:

```python
@dataclass
class SystemResources:
    """Snapshot of current system resources."""

    cpu_count: int = 0
    ram_total_mb: int = 0
    ram_available_mb: int = 0
    load_avg_1: float = 0.0
    load_avg_5: float = 0.0
    load_avg_15: float = 0.0
    # --- new fields ---
    memory_pressure: MemoryPressureLevel = MemoryPressureLevel.NORMAL
    rss_total_mb: int = 0  # sum of RSS for all centurion-managed processes
```

**Backward compatibility:** Both fields have defaults, so existing call sites (including `to_dict()`) continue to work without changes. `to_dict()` should be extended to include the new fields in a follow-up implementation.

## 4. Throttle Event Names

Three new event types are added to the throttle vocabulary. These are emitted by the `Throttle.check()` method based on the `memory_pressure` field in `SystemResources`:

| Event name | Emitted when | Entity type | Payload fields |
|---|---|---|---|
| `memory_caution` | `MemoryPressureLevel.WARN` (first transition) | `"hardware"` | `rss_total_mb`, `ram_available_mb`, `pressure_level`, `headroom_mb` |
| `memory_warning` | `MemoryPressureLevel.WARN` (sustained, every Nth check) | `"hardware"` | same as above + `sustained_seconds` |
| `memory_critical` | `MemoryPressureLevel.CRITICAL` | `"hardware"` | same as above + `recommended_action: "scale_down"` |

**Naming convention:** These follow the existing pattern where `entity_type="hardware"` and `entity_id="throttle"`. The split between `memory_caution` (first occurrence) and `memory_warning` (sustained) prevents event flooding while ensuring visibility.

**Relationship to existing events:**
- `hardware_warning` and `resource_exhausted` remain unchanged and continue to fire based on agent-slot ratios.
- Memory pressure events fire independently; both systems can trigger simultaneously.

**Consumer contract:** Any EventBus subscriber can listen for these events. The Optio autoscaler in `Century` should subscribe and:
- On `memory_caution`: suppress scale-up decisions for the current cooldown cycle.
- On `memory_warning`: suppress scale-up and log a warning.
- On `memory_critical`: trigger immediate scale-down of one idle legionary (if above `min_legionaries`).

## 5. Dynamic Headroom Formula

The current static headroom is:
```
headroom = config.ram_headroom_gb * 1024  # constant, default 2048 MB
```

The new dynamic headroom replaces this with:

```
headroom = base * (1 + pressure_multiplier)
```

Where:
- `base` = `config.ram_headroom_gb * 1024` (the user-configured baseline, unchanged)
- `pressure_multiplier` is derived from the current `MemoryPressureLevel`:

| Pressure level | pressure_multiplier | Effective headroom (base=2 GB) |
|---|---|---|
| `NORMAL` | 0.0 | 2048 MB |
| `WARN` | 0.5 | 3072 MB |
| `CRITICAL` | 1.0 | 4096 MB |

**Effect:** Under memory pressure, the scheduler reserves more RAM as headroom, which reduces `_available_resources().memory_mb` and therefore reduces `available_slots()` and `recommended_max_agents()`. This creates a natural feedback loop: pressure increases headroom, which tightens admission, which reduces pressure.

**Implementation location:** `CenturionScheduler._available_resources()` currently computes `headroom_mb = int(self.config.ram_headroom_gb * 1024)`. This line is replaced with the dynamic formula. The `pressure_multiplier` mapping should be a class-level constant dict:

```python
_PRESSURE_MULTIPLIERS: ClassVar[dict[MemoryPressureLevel, float]] = {
    MemoryPressureLevel.NORMAL: 0.0,
    MemoryPressureLevel.WARN: 0.5,
    MemoryPressureLevel.CRITICAL: 1.0,
}
```

## 6. RSS Audit Interface: `_actual_memory_usage_mb()`

A new static method on `CenturionScheduler` measures real process memory consumption:

```python
@staticmethod
def _actual_memory_usage_mb() -> int:
    """Return total RSS in MB for the centurion process tree.

    Uses ``ps -o rss= -p <pid>`` for the current process, plus all
    child processes discovered via ``ps -o rss= --ppid <pid>`` (Linux)
    or ``ps -o rss= -g <pgid>`` (macOS).

    Returns 0 on any failure (callers must treat 0 as "unknown").
    """
```

**Why `ps -o rss=` instead of `/proc/self/status` or `resource.getrusage()`?**
- `ps -o rss=` works on both macOS and Linux with the same interface.
- It captures child process RSS (the Claude CLI subprocesses), which is the dominant memory consumer. `getrusage` only reports the current process.
- The `=` suffix suppresses the header line, making parsing trivial.

**macOS implementation detail:**
```
ps -o rss= -g <pgid>
```
This captures the entire process group (centurion parent + all spawned Claude CLI children). On Linux, the equivalent is:
```
ps -o rss= --ppid <pid>
```
combined with the parent's own RSS.

**Output format:** `ps -o rss=` returns RSS in kilobytes (one value per line). Sum all lines, divide by 1024, round to int.

**Error handling:** If `subprocess.run()` fails or returns non-zero, return 0. The caller (`probe_system`) must treat 0 as "measurement unavailable" and default to `MemoryPressureLevel.NORMAL` to avoid false positives.

**Probe integration:** `probe_system()` calls `_actual_memory_usage_mb()` and computes the pressure level:

```python
rss = self._actual_memory_usage_mb()
if rss > 0:
    usable = ram_available_mb - dynamic_headroom
    ratio = rss / max(usable, 1)
    if ratio >= 0.85:
        pressure = MemoryPressureLevel.CRITICAL
    elif ratio >= 0.6:
        pressure = MemoryPressureLevel.WARN
    else:
        pressure = MemoryPressureLevel.NORMAL
else:
    pressure = MemoryPressureLevel.NORMAL
```

**Cache interaction:** The existing 5-second probe cache TTL applies. RSS measurement reuses the same cache window. Under CRITICAL pressure, the cache TTL should be reduced to 2 seconds (configurable) to increase responsiveness.

## 7. Data Flow Summary

```
probe_system()
  |
  +-- _ram_available_mb()        # existing: OS-level free memory
  +-- _actual_memory_usage_mb()  # NEW: process-tree RSS via ps
  |
  +-- compute pressure level     # NEW: ratio-based enum
  +-- compute dynamic headroom   # NEW: base * (1 + multiplier)
  |
  v
SystemResources (with pressure + rss_total_mb)
  |
  +---> CenturionScheduler._available_resources()
  |       uses dynamic headroom to compute available slots
  |
  +---> Throttle.check()
          emits memory_caution / memory_warning / memory_critical
          |
          v
        EventBus
          |
          +---> Optio autoscaler (suppress scale-up or trigger scale-down)
          +---> API/SSE subscribers (observability)
```

## 8. Configuration Surface

No new config fields are required. The existing `ram_headroom_gb` serves as the `base` in the dynamic formula. The pressure thresholds (0.6, 0.85) and multipliers (0.0, 0.5, 1.0) are implementation constants, not user-configurable, to keep the config surface small.

**Future consideration:** If operators need to tune thresholds, add `CENTURION_MEMORY_WARN_RATIO` and `CENTURION_MEMORY_CRITICAL_RATIO` environment variables to `CenturionConfig`, following the existing env-var pattern.

## 9. Safety and Edge Cases

| Scenario | Behavior |
|---|---|
| `_actual_memory_usage_mb()` returns 0 | Default to `NORMAL`; no false alarms |
| RSS spikes above CRITICAL between probe cache windows | Detected on next probe (max 5s delay; 2s under CRITICAL) |
| All legionaries are busy when CRITICAL fires | No scale-down possible; event is logged for operator awareness |
| Only `min_legionaries` remain at CRITICAL | Scale-down is suppressed; system operates at minimum capacity |
| macOS `ps` includes non-centurion processes in pgid | Unlikely if centurion starts its own process group; document as known limitation |

## 10. Migration / Rollout

This change is additive:
1. `MemoryPressureLevel` and new `SystemResources` fields are backward-compatible (defaults).
2. `Throttle.check()` gains new event emission alongside existing logic; no breaking change.
3. Dynamic headroom with `pressure_multiplier=0.0` (NORMAL) produces the same value as the current static formula.
4. The Optio gains event subscription in a follow-up; until then, memory events are purely observational.

Recommended implementation order:
1. Add `MemoryPressureLevel` enum and `_actual_memory_usage_mb()` to scheduler.
2. Extend `SystemResources` with new fields and update `probe_system()`.
3. Add dynamic headroom to `_available_resources()`.
4. Add memory pressure events to `Throttle.check()`.
5. Wire Optio to respond to memory pressure events.
