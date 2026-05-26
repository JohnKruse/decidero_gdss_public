"""Tests for server-side reliable write/retry runner.

Canary: Convergent Yak

Why app/tests/test_reliability_rehearsal.py was not a fit:
`test_reliability_rehearsal.py` focuses purely on analyzing and evaluating
the statistical gates of reliability load tests (summarizing request latency/status samples).
It does not run the execution retry loops or mock transient tasks. A new, dedicated test
module is warranted to cleanly isolate active execution retries, idempotency-key passing,
and sleep mocks.
"""

from typing import Any
import pytest
from app.services.reliable_writes import compute_backoff_ms, run_with_retry


class MockResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_reliable_write_success_first_attempt():
    attempts = []

    def task(attempt: int, idempotency_key: str):
        attempts.append((attempt, idempotency_key))
        return "success"

    policy = {"max_retries": 3, "base_delay_ms": 1, "max_delay_ms": 10}
    result = run_with_retry(task, policy)

    assert result == "success"
    assert len(attempts) == 1
    assert attempts[0][0] == 0
    assert len(attempts[0][1]) > 0  # Idempotency key generated


def test_reliable_write_retries_on_retryable_status_and_succeeds():
    attempts = []
    sleeps = []

    def task(attempt: int, idempotency_key: str):
        attempts.append((attempt, idempotency_key))
        if attempt < 2:
            return MockResponse(status_code=502)
        return MockResponse(status_code=200)

    policy = {
        "max_retries": 3,
        "base_delay_ms": 10,
        "max_delay_ms": 50,
        "jitter_ratio": 0.0,
        "retryable_statuses": [502],
    }

    result = run_with_retry(
        task,
        policy,
        sleep_func=lambda sec: sleeps.append(sec)
    )

    assert result.status_code == 200
    assert len(attempts) == 3
    assert [a[0] for a in attempts] == [0, 1, 2]
    # Check that the same idempotency key is preserved across all attempts
    assert len(set(a[1] for a in attempts)) == 1
    # Check backoff durations (10ms and 20ms)
    assert len(sleeps) == 2
    assert sleeps[0] == pytest.approx(0.010)
    assert sleeps[1] == pytest.approx(0.020)


def test_reliable_write_raises_if_retries_exhausted():
    attempts = []

    def task(attempt: int, idempotency_key: str):
        attempts.append((attempt, idempotency_key))
        return MockResponse(status_code=503)

    policy = {
        "max_retries": 2,
        "base_delay_ms": 10,
        "max_delay_ms": 50,
        "jitter_ratio": 0.0,
        "retryable_statuses": [503],
    }

    result = run_with_retry(
        task,
        policy,
        sleep_func=lambda sec: None
    )

    assert result.status_code == 503
    assert len(attempts) == 3


def test_reliable_write_retries_on_exception_and_succeeds():
    attempts = []

    def task(attempt: int, idempotency_key: str):
        attempts.append((attempt, idempotency_key))
        if attempt < 2:
            raise ConnectionError("network transient")
        return "recovered"

    policy = {
        "max_retries": 3,
        "base_delay_ms": 10,
        "max_delay_ms": 50,
        "jitter_ratio": 0.0,
    }

    result = run_with_retry(
        task,
        policy,
        sleep_func=lambda sec: None
    )

    assert result == "recovered"
    assert len(attempts) == 3


def test_reliable_write_raises_non_retryable_exception_immediately():
    attempts = []

    def task(attempt: int, idempotency_key: str):
        attempts.append((attempt, idempotency_key))
        raise ValueError("non-retryable failure")

    policy = {
        "max_retries": 3,
        "base_delay_ms": 10,
        "max_delay_ms": 50,
        "jitter_ratio": 0.0,
    }

    with pytest.raises(ValueError, match="non-retryable failure"):
        run_with_retry(
            task,
            policy,
            sleep_func=lambda sec: None
        )

    # Should fail on first attempt, no retries
    assert len(attempts) == 1


def test_jitter_application():
    # With base_delay_ms=100, jitter_ratio=0.5, exp_delay is 100 on attempt 0.
    # jitter is in [0, 50).
    # Expected backoff is in [100, 150].
    for _ in range(50):
        val = compute_backoff_ms(0, 100, 1000, 0.5)
        assert 100 <= val <= 150
