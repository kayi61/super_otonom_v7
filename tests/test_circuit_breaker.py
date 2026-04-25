"""CircuitBreaker isolation (Faz 1)."""
from __future__ import annotations

from unittest import mock

from super_otonom.exchange_async import CircuitBreaker


def test_circuit_breaker_stays_closed_on_success() -> None:
    cb = CircuitBreaker(failure_threshold=3, recovery_time=1.0)
    assert cb.can_proceed() is True
    cb.record_success()
    assert cb.is_open is False
    assert cb.state == "CLOSED"


def test_circuit_breaker_opens_after_threshold_failures() -> None:
    cb = CircuitBreaker(failure_threshold=3, recovery_time=60.0)
    for _ in range(2):
        cb.record_failure()
    assert not cb.is_open
    cb.record_failure()
    assert cb.is_open
    assert cb.can_proceed() is False


def test_circuit_breaker_recovery_allows_probe() -> None:
    t0 = 1000.0
    cb = CircuitBreaker(failure_threshold=1, recovery_time=0.05)
    with mock.patch("super_otonom.exchange_async.time.time", return_value=t0):
        cb.record_failure()
    assert cb.is_open
    with mock.patch("super_otonom.exchange_async.time.time", return_value=t0 + 1.0):
        assert cb.can_proceed() is True
