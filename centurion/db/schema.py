"""SQL schema definitions for Centurion persistence layer."""

from __future__ import annotations

import sqlite3
from typing import Any

# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

CREATE_CENTURION_LEGIONS = """\
CREATE TABLE IF NOT EXISTS centurion_legions (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    quota_json  TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    disbanded_at TEXT
);
"""

CREATE_CENTURION_CENTURIES = """\
CREATE TABLE IF NOT EXISTS centurion_centuries (
    id                TEXT PRIMARY KEY,
    legion_id         TEXT NOT NULL,
    agent_type        TEXT NOT NULL,
    agent_type_config TEXT,
    min_legionaries   INTEGER NOT NULL DEFAULT 1,
    max_legionaries   INTEGER NOT NULL DEFAULT 10,
    autoscale         INTEGER NOT NULL DEFAULT 1,
    task_timeout      REAL NOT NULL DEFAULT 300.0,
    status            TEXT NOT NULL DEFAULT 'active',
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

CREATE_CENTURION_TASKS = """\
CREATE TABLE IF NOT EXISTS centurion_tasks (
    id               TEXT PRIMARY KEY,
    century_id       TEXT NOT NULL,
    legion_id        TEXT NOT NULL,
    legionary_id     TEXT,
    prompt           TEXT NOT NULL,
    priority         INTEGER NOT NULL DEFAULT 5,
    status           TEXT NOT NULL DEFAULT 'pending',
    output           TEXT,
    error            TEXT,
    exit_code        INTEGER,
    duration_seconds REAL,
    submitted_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at       TEXT,
    completed_at     TEXT,
    metadata         TEXT
);
"""

CREATE_CENTURION_EVENTS = """\
CREATE TABLE IF NOT EXISTS centurion_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    payload     TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

CREATE_CENTURION_HARDWARE_SNAPSHOTS = """\
CREATE TABLE IF NOT EXISTS centurion_hardware_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    cpu_count               INTEGER,
    ram_total_gb            REAL,
    ram_available_gb        REAL,
    cpu_usage_percent       REAL,
    load_avg                TEXT,
    active_agents           INTEGER,
    allocated_cpu_millicores INTEGER,
    allocated_memory_mb     INTEGER,
    recommended_max         INTEGER,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_centuries_legion_id ON centurion_centuries (legion_id);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_century_id ON centurion_tasks (century_id);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON centurion_tasks (status);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_legion_id ON centurion_tasks (legion_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_event_type ON centurion_events (event_type);",
    "CREATE INDEX IF NOT EXISTS idx_events_entity ON centurion_events (entity_type, entity_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_created_at ON centurion_events (created_at);",
]

# ---------------------------------------------------------------------------
# Convenience list of all table-creation statements
# ---------------------------------------------------------------------------

TABLES: list[str] = [
    CREATE_CENTURION_LEGIONS,
    CREATE_CENTURION_CENTURIES,
    CREATE_CENTURION_TASKS,
    CREATE_CENTURION_EVENTS,
    CREATE_CENTURION_HARDWARE_SNAPSHOTS,
]


def init_db(conn: sqlite3.Connection | Any) -> None:
    """Create all tables and indexes. Works with both sqlite3.Connection and aiosqlite proxies."""
    cursor = conn.cursor() if hasattr(conn, "cursor") else conn
    for ddl in TABLES:
        conn.execute(ddl)
    for idx in CREATE_INDEXES:
        conn.execute(idx)
    conn.commit()
