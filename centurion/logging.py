"""Centurion structured logging — JSON for production, colored ANSI for dev.

Provides two formatters and a single ``setup_logging()`` entry-point that
configures the ``centurion`` logger hierarchy.  No external dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from typing import Any


class CenturionJSONFormatter(logging.Formatter):
    """Emit structured JSON log lines for production environments.

    Each log record produces a single-line JSON object with a fixed schema
    plus optional extra context fields.
    """

    # Fields from LogRecord that are part of the fixed schema and should
    # not appear in the extra context bucket.
    RESERVED_ATTRS = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self._iso_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "message": record.getMessage(),
        }

        # Merge extra context — any attribute on the record that is not
        # part of the standard LogRecord fields.
        extra = {k: v for k, v in record.__dict__.items() if k not in self.RESERVED_ATTRS and not k.startswith("_")}
        if extra:
            log_entry["context"] = extra

        # Exception info
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Stack info (from logger.log(..., stack_info=True))
        if record.stack_info:
            log_entry["stack_info"] = record.stack_info

        return json.dumps(log_entry, default=str, ensure_ascii=False)

    @staticmethod
    def _iso_timestamp(record: logging.LogRecord) -> str:
        """ISO-8601 timestamp with millisecond precision and UTC offset."""
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"


class CenturionDevFormatter(logging.Formatter):
    """Colored single-line formatter for local development.

    Format: ``TIMESTAMP LEVEL LOGGER_SHORT MESSAGE [key=value ...]``
    """

    COLORS = {
        "DEBUG": "\033[36m",  # cyan
        "INFO": "\033[32m",  # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",  # red
        "CRITICAL": "\033[1;31m",  # bold red
    }
    RESET = "\033[0m"
    DIM = "\033[2m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")

        # Shorten logger name: centurion.core.engine -> c.core.engine
        name = record.name
        parts = name.split(".")
        if len(parts) > 1:
            parts[0] = parts[0][0]
            name = ".".join(parts)

        # Collect extra context
        reserved = logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
        extras = {k: v for k, v in record.__dict__.items() if k not in reserved and not k.startswith("_")}
        extra_str = ""
        if extras:
            pairs = " ".join(f"{k}={v}" for k, v in extras.items())
            extra_str = f" {self.DIM}[{pairs}]{self.RESET}"

        # Timestamp: HH:MM:SS.mmm
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        ts = dt.strftime("%H:%M:%S.") + f"{int(record.msecs):03d}"

        line = (
            f"{self.DIM}{ts}{self.RESET} "
            f"{color}{record.levelname:<8}{self.RESET} "
            f"{self.DIM}{name:<28}{self.RESET} "
            f"{record.getMessage()}"
            f"{extra_str}"
        )

        if record.exc_info and record.exc_info[1] is not None:
            line += "\n" + self.formatException(record.exc_info)

        return line


def setup_logging(
    level: str = "INFO",
    json_mode: bool = False,
    log_file: str | None = None,
) -> None:
    """Configure the centurion logger hierarchy.

    Args:
        level: Root log level. One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
               Can also be set via ``CENTURION_LOG_LEVEL`` env var.
        json_mode: If True, use :class:`CenturionJSONFormatter` (production).
                   If False, use :class:`CenturionDevFormatter` (development).
                   Can also be set via ``CENTURION_LOG_JSON=1`` env var.
        log_file: Optional path to a log file. If provided, a second handler
                  is added that always uses JSON format regardless of *json_mode*.
    """
    # Resolve from environment if not explicitly set
    level = os.getenv("CENTURION_LOG_LEVEL", level).upper()
    if os.getenv("CENTURION_LOG_JSON", "").strip() in ("1", "true", "yes"):
        json_mode = True
    log_file = log_file or os.getenv("CENTURION_LOG_FILE")

    # Configure the root centurion logger (not the global root logger)
    root = logging.getLogger("centurion")
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    if json_mode:
        console.setFormatter(CenturionJSONFormatter())
    else:
        console.setFormatter(CenturionDevFormatter())
    root.addHandler(console)

    # Optional file handler (always JSON for machine parsing)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(CenturionJSONFormatter())
        root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    root.debug("Logging initialized", extra={"level": level, "json_mode": json_mode})
