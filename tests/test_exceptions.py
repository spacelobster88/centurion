"""Tests for the Centurion exception hierarchy."""

import pytest

from centurion.core.exceptions import (
    AgentAPIError,
    AgentProcessError,
    CenturionError,
    ConfigurationError,
    SchedulerError,
    TaskTimeoutError,
)

# ---------------------------------------------------------------------------
# CenturionError base class
# ---------------------------------------------------------------------------


class TestCenturionError:
    def test_is_exception_subclass(self):
        assert issubclass(CenturionError, Exception)

    def test_default_retryable_is_false(self):
        err = CenturionError("boom")
        assert err.retryable is False

    def test_retryable_can_be_set_true(self):
        err = CenturionError("boom", retryable=True)
        assert err.retryable is True

    def test_message_preserved(self):
        err = CenturionError("something went wrong")
        assert str(err) == "something went wrong"


# ---------------------------------------------------------------------------
# TaskTimeoutError
# ---------------------------------------------------------------------------


class TestTaskTimeoutError:
    def test_inherits_from_centurion_error(self):
        assert issubclass(TaskTimeoutError, CenturionError)

    def test_is_retryable(self):
        err = TaskTimeoutError("timed out", timeout_seconds=30.0)
        assert err.retryable is True

    def test_has_timeout_seconds(self):
        err = TaskTimeoutError("timed out", timeout_seconds=42.5)
        assert err.timeout_seconds == 42.5

    def test_default_timeout_seconds_is_zero(self):
        err = TaskTimeoutError("timed out")
        assert err.timeout_seconds == 0.0


# ---------------------------------------------------------------------------
# AgentProcessError
# ---------------------------------------------------------------------------


class TestAgentProcessError:
    def test_inherits_from_centurion_error(self):
        assert issubclass(AgentProcessError, CenturionError)

    def test_transient_exit_code_is_retryable(self):
        err = AgentProcessError("killed", exit_code=-9)
        assert err.retryable is True

    def test_non_transient_exit_code_is_not_retryable(self):
        err = AgentProcessError("bad args", exit_code=2)
        assert err.retryable is False

    def test_exit_code_none_is_not_retryable(self):
        err = AgentProcessError("unknown")
        assert err.retryable is False

    def test_exit_code_stored(self):
        err = AgentProcessError("err", exit_code=137)
        assert err.exit_code == 137

    def test_stderr_stored(self):
        err = AgentProcessError("err", exit_code=1, stderr="segfault")
        assert err.stderr == "segfault"

    @pytest.mark.parametrize("code", [-9, -15, -11, 137, 139])
    def test_all_transient_codes_are_retryable(self, code):
        err = AgentProcessError("err", exit_code=code)
        assert err.retryable is True


# ---------------------------------------------------------------------------
# AgentAPIError
# ---------------------------------------------------------------------------


class TestAgentAPIError:
    def test_inherits_from_centurion_error(self):
        assert issubclass(AgentAPIError, CenturionError)

    def test_429_is_retryable(self):
        err = AgentAPIError("rate limited", status_code=429)
        assert err.retryable is True

    def test_400_is_not_retryable(self):
        err = AgentAPIError("bad request", status_code=400)
        assert err.retryable is False

    def test_status_code_none_is_not_retryable(self):
        err = AgentAPIError("unknown")
        assert err.retryable is False

    @pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
    def test_all_retryable_status_codes(self, code):
        err = AgentAPIError("err", status_code=code)
        assert err.retryable is True


# ---------------------------------------------------------------------------
# SchedulerError & ConfigurationError
# ---------------------------------------------------------------------------


class TestSchedulerError:
    def test_inherits_from_centurion_error(self):
        assert issubclass(SchedulerError, CenturionError)

    def test_is_not_retryable(self):
        err = SchedulerError("scheduling failed")
        assert err.retryable is False


class TestConfigurationError:
    def test_inherits_from_centurion_error(self):
        assert issubclass(ConfigurationError, CenturionError)

    def test_is_not_retryable(self):
        err = ConfigurationError("bad config")
        assert err.retryable is False


# ---------------------------------------------------------------------------
# All exceptions inherit from CenturionError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc_cls",
    [
        TaskTimeoutError,
        AgentProcessError,
        AgentAPIError,
        SchedulerError,
        ConfigurationError,
    ],
)
def test_all_exceptions_inherit_from_centurion_error(exc_cls):
    assert issubclass(exc_cls, CenturionError)
