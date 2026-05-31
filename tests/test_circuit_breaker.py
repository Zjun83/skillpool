"""Tests for CircuitBreaker — 3-state circuit breaker."""
import pytest

from skillpool.resolver.circuit_breaker import CircuitBreaker, CircuitState


class TestClosedState:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_allows_requests_when_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_stays_closed_on_success(self) -> None:
        cb = CircuitBreaker()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestOpenState:
    def test_opens_after_threshold_failures(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_rejects_requests_when_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999.0)
        cb.record_failure()
        assert cb.allow_request() is False

    def test_failure_count(self) -> None:
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2


class TestHalfOpenState:
    def test_transitions_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        import time
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_allows_limited_requests_in_half_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=2)
        cb.record_failure()
        import time
        time.sleep(0.02)
        assert cb.allow_request() is True
        assert cb.allow_request() is True
        assert cb.allow_request() is False

    def test_success_in_half_open_closes_circuit(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=1)
        cb.record_failure()
        import time
        time.sleep(0.02)
        cb.allow_request()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=1)
        cb.record_failure()
        import time
        time.sleep(0.02)
        cb.allow_request()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
