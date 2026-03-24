"""Tests for the CircuitBreaker state machine."""

from unittest.mock import patch

from centurion.core.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreakerInitialState:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    def test_closed_allows_execution(self):
        cb = CircuitBreaker("test")
        assert cb.can_execute() is True


class TestClosedToOpen:
    def test_transitions_to_open_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        for _ in range(5):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_configurable_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestOpenState:
    def test_open_blocks_execution(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.can_execute() is False

    def test_transitions_to_half_open_after_cooldown(self):
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=10.0)
        # Record a failure to go OPEN
        fake_time = 1000.0
        with patch("centurion.core.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = fake_time
            cb.record_failure()
            assert cb._state == CircuitState.OPEN

            # Advance past cooldown
            mock_time.monotonic.return_value = fake_time + 10.0
            assert cb.state == CircuitState.HALF_OPEN


class TestHalfOpenTransitions:
    def _make_half_open(self, cb: CircuitBreaker) -> None:
        """Helper: drive the breaker into HALF_OPEN state."""
        fake_time = 1000.0
        with patch("centurion.core.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = fake_time
            for _ in range(cb.failure_threshold):
                cb.record_failure()
            # Advance past cooldown so state property returns HALF_OPEN
            mock_time.monotonic.return_value = fake_time + cb.cooldown_seconds
            _ = cb.state  # trigger transition
        assert cb._state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=1.0)
        self._make_half_open(cb)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=1.0)
        self._make_half_open(cb)
        cb.record_failure()
        assert cb._state == CircuitState.OPEN

    def test_half_open_allows_execution(self):
        cb = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=1.0)
        self._make_half_open(cb)
        assert cb.can_execute() is True


class TestReset:
    def test_reset_returns_to_closed(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb._state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_reset_clears_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        cb.reset()
        # One more failure should NOT trip the breaker
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_reset_allows_execution(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.can_execute() is False
        cb.reset()
        assert cb.can_execute() is True


class TestSuccessResetsFailureCount:
    def test_success_resets_failure_count_in_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # After success the count resets, so one more failure shouldn't trip it
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
