"""Tests for centurion.logging — JSON/dev formatters and setup_logging()."""

from __future__ import annotations

import json
import logging
import sys

import pytest

from centurion.logging import (
    CenturionDevFormatter,
    CenturionJSONFormatter,
    setup_logging,
)


def _make_record(
    msg: str = "hello world",
    level: int = logging.INFO,
    name: str = "centurion.test",
    exc_info: tuple | None = None,
    **extras: object,
) -> logging.LogRecord:
    """Helper: build a LogRecord with optional extras and exc_info."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="test_logging.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for k, v in extras.items():
        setattr(record, k, v)
    return record


# ---------- CenturionJSONFormatter ----------


class TestJSONFormatter:
    def test_json_formatter_produces_valid_json(self) -> None:
        """Formatted output must be valid JSON with the fixed-schema keys."""
        fmt = CenturionJSONFormatter()
        record = _make_record()
        output = fmt.format(record)

        parsed = json.loads(output)  # raises on invalid JSON
        for key in ("timestamp", "level", "logger", "module", "message"):
            assert key in parsed, f"Missing required key: {key}"

        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"
        assert parsed["logger"] == "centurion.test"

    def test_json_formatter_includes_exception(self) -> None:
        """When exc_info is present the output must contain an 'exception' key."""
        fmt = CenturionJSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()

        record = _make_record(msg="failure", exc_info=exc_info)
        output = fmt.format(record)

        parsed = json.loads(output)
        assert "exception" in parsed
        assert parsed["exception"]["type"] == "ValueError"
        assert "boom" in parsed["exception"]["message"]
        assert isinstance(parsed["exception"]["traceback"], list)

    def test_json_formatter_includes_extra_context(self) -> None:
        """Extra attributes on the LogRecord should appear under 'context'."""
        fmt = CenturionJSONFormatter()
        record = _make_record(task_id="123", run_id="abc")
        output = fmt.format(record)

        parsed = json.loads(output)
        assert "context" in parsed
        assert parsed["context"]["task_id"] == "123"
        assert parsed["context"]["run_id"] == "abc"

    def test_json_formatter_no_context_when_no_extras(self) -> None:
        """If no extra attributes are set, 'context' should be absent."""
        fmt = CenturionJSONFormatter()
        record = _make_record()
        output = fmt.format(record)

        parsed = json.loads(output)
        assert "context" not in parsed

    def test_json_formatter_timestamp_is_iso8601(self) -> None:
        """Timestamp must look like an ISO-8601 string ending with 'Z'."""
        fmt = CenturionJSONFormatter()
        record = _make_record()
        output = fmt.format(record)

        parsed = json.loads(output)
        ts = parsed["timestamp"]
        assert ts.endswith("Z")
        assert "T" in ts


# ---------- CenturionDevFormatter ----------


class TestDevFormatter:
    def test_dev_formatter_output(self) -> None:
        """Dev formatter should produce a non-empty string containing level and message."""
        fmt = CenturionDevFormatter()
        record = _make_record(msg="starting up", level=logging.WARNING)
        output = fmt.format(record)

        assert isinstance(output, str)
        assert len(output) > 0
        assert "WARNING" in output
        assert "starting up" in output

    def test_dev_formatter_shortens_logger_name(self) -> None:
        """Multi-part logger names should have the first segment abbreviated."""
        fmt = CenturionDevFormatter()
        record = _make_record(name="centurion.core.engine")
        output = fmt.format(record)

        # "centurion.core.engine" should become "c.core.engine"
        assert "c.core.engine" in output


# ---------- setup_logging ----------


class TestSetupLogging:
    def _cleanup_logger(self) -> None:
        """Remove handlers from the centurion logger to avoid test pollution."""
        logger = logging.getLogger("centurion")
        logger.handlers.clear()

    def test_setup_logging_configures_level(self) -> None:
        """setup_logging(level='DEBUG') should set centurion logger to DEBUG."""
        self._cleanup_logger()
        setup_logging(level="DEBUG")
        logger = logging.getLogger("centurion")

        assert logger.level == logging.DEBUG
        self._cleanup_logger()

    def test_setup_logging_json_mode(self) -> None:
        """setup_logging(json_mode=True) should attach a handler using CenturionJSONFormatter."""
        self._cleanup_logger()
        setup_logging(json_mode=True)
        logger = logging.getLogger("centurion")

        assert len(logger.handlers) >= 1
        formatter = logger.handlers[0].formatter
        assert isinstance(formatter, CenturionJSONFormatter)
        self._cleanup_logger()

    def test_setup_logging_dev_mode_default(self) -> None:
        """By default, setup_logging uses CenturionDevFormatter."""
        self._cleanup_logger()
        setup_logging(json_mode=False)
        logger = logging.getLogger("centurion")

        assert len(logger.handlers) >= 1
        formatter = logger.handlers[0].formatter
        assert isinstance(formatter, CenturionDevFormatter)
        self._cleanup_logger()

    def test_setup_logging_file_handler(self, tmp_path) -> None:
        """When log_file is given, a FileHandler with JSON formatter is added."""
        self._cleanup_logger()
        log_path = str(tmp_path / "test.log")
        setup_logging(log_file=log_path)
        logger = logging.getLogger("centurion")

        # Should have console + file = 2 handlers
        assert len(logger.handlers) == 2
        file_handler = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handler) == 1
        assert isinstance(file_handler[0].formatter, CenturionJSONFormatter)

        # Clean up
        for h in logger.handlers:
            h.close()
        self._cleanup_logger()
