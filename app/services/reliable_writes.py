"""Server-side reliability execution path mirroring client-side runReliableWriteAction.

Canary: Convergent Yak
Normalized policies are supplied by the activity catalog normalization rules at
app/services/activity_catalog.py and mirror client-side write semantics defined
at app/static/js/meeting.js (runReliableWriteAction).
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Dict, Optional
import uuid


def compute_backoff_ms(
    attempt: int, base_delay_ms: int, max_delay_ms: int, jitter_ratio: float
) -> int:
    """Compute exponential backoff with jitter, mirroring client-side logic."""
    exp_delay = min(max_delay_ms, base_delay_ms * (2**attempt))
    jitter = exp_delay * jitter_ratio * random.random()
    return round(exp_delay + jitter)


def run_with_retry(
    task: Callable[[int, str], Any],
    policy: Dict[str, Any],
    idempotency_key: Optional[str] = None,
    should_retry_result: Optional[Callable[[Any], bool]] = None,
    should_retry_exception: Optional[Callable[[Exception], bool]] = None,
    on_retry: Optional[Callable[[Dict[str, Any]], None]] = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> Any:
    """Execute a task with idempotency key and retry policy.

    The task is a callable (attempt, idempotency_key) -> result.
    If the task raises an exception or returns a result that is deemed retryable,
    it sleeps for a computed backoff duration and retries.
    """
    max_retries = int(policy.get("max_retries", 3))
    base_delay_ms = int(policy.get("base_delay_ms", 400))
    max_delay_ms = int(policy.get("max_delay_ms", 4000))
    jitter_ratio = float(policy.get("jitter_ratio", 0.2))

    if not idempotency_key:
        idempotency_key = str(uuid.uuid4())

    retryable_statuses = set(policy.get("retryable_statuses") or [429, 502, 503, 504])

    if should_retry_result is None:
        def default_should_retry_result(res: Any) -> bool:
            # Check status attributes
            for attr in ("status_code", "status"):
                if hasattr(res, attr):
                    val = getattr(res, attr)
                    try:
                        if int(val) in retryable_statuses:
                            return True
                    except (TypeError, ValueError):
                        pass
            if isinstance(res, dict):
                for key in ("status_code", "status"):
                    if key in res:
                        try:
                            if int(res[key]) in retryable_statuses:
                                return True
                        except (TypeError, ValueError):
                            pass
            return False

        should_retry_result = default_should_retry_result

    if should_retry_exception is None:
        def default_should_retry_exception(exc: Exception) -> bool:
            # Check if exception has status code matching retryable statuses
            for attr in ("status_code", "status"):
                if hasattr(exc, attr):
                    val = getattr(exc, attr)
                    try:
                        if int(val) in retryable_statuses:
                            return True
                    except (TypeError, ValueError):
                        pass
            # Check for network/connection errors
            if isinstance(exc, (ConnectionError, TimeoutError)):
                return True
            name = exc.__class__.__name__
            if name in (
                "RequestException",
                "HTTPException",
                "Timeout",
                "ConnectionError",
                "RemoteDisconnected",
            ):
                return True
            return False

        should_retry_exception = default_should_retry_exception

    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            result = task(attempt, idempotency_key)

            # Check if result should trigger retry
            if attempt < max_retries and should_retry_result(result):
                delay_ms = compute_backoff_ms(attempt, base_delay_ms, max_delay_ms, jitter_ratio)
                if on_retry:
                    on_retry(
                        {
                            "attempt": attempt,
                            "idempotency_key": idempotency_key,
                            "delay_ms": delay_ms,
                            "reason": "retryable_result",
                            "result": result,
                        }
                    )
                sleep_func(delay_ms / 1000.0)
                continue

            return result

        except Exception as exc:
            last_exception = exc
            if attempt < max_retries and should_retry_exception(exc):
                delay_ms = compute_backoff_ms(attempt, base_delay_ms, max_delay_ms, jitter_ratio)
                if on_retry:
                    on_retry(
                        {
                            "attempt": attempt,
                            "idempotency_key": idempotency_key,
                            "delay_ms": delay_ms,
                            "reason": "retryable_exception",
                            "exception": exc,
                        }
                    )
                sleep_func(delay_ms / 1000.0)
                continue

            raise exc

    if last_exception:
        raise last_exception
    raise RuntimeError("Retry runner exhausted without result or exception")
