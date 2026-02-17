from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Optional


TRANSIENT_STATUSES = {429, 502, 503, 504}


@dataclass(frozen=True)
class RequestSample:
    status_code: Optional[int]
    latency_ms: float
    recovered_by_retry: bool = False


def classify_status(status_code: Optional[int]) -> str:
    if status_code is None:
        return "hard_failure"
    if 200 <= status_code < 300:
        return "success"
    if status_code in TRANSIENT_STATUSES:
        return "transient_failure"
    return "hard_failure"


def _percentile(sorted_values: list[float], percentile: int) -> float:
    if not sorted_values:
        return 0.0
    if percentile <= 0:
        return sorted_values[0]
    if percentile >= 100:
        return sorted_values[-1]
    index = int(round((percentile / 100.0) * (len(sorted_values) - 1)))
    return sorted_values[index]


def summarize_samples(samples: Iterable[RequestSample]) -> dict:
    materialized = list(samples)
    total = len(materialized)
    success = 0
    transient = 0
    hard = 0
    recovered = 0
    latencies: list[float] = []

    for sample in materialized:
        latencies.append(float(sample.latency_ms))
        outcome = classify_status(sample.status_code)
        if outcome == "success":
            success += 1
        elif outcome == "transient_failure":
            transient += 1
        else:
            hard += 1
        if sample.recovered_by_retry:
            recovered += 1

    latencies.sort()
    success_rate = (success / total) * 100 if total else 0.0
    hard_failure_rate = (hard / total) * 100 if total else 0.0
    transient_recovery_rate = (recovered / transient) * 100 if transient else 100.0

    return {
        "total": total,
        "success": success,
        "transient_failure": transient,
        "hard_failure": hard,
        "recovered_by_retry": recovered,
        "success_rate_pct": round(success_rate, 2),
        "hard_failure_rate_pct": round(hard_failure_rate, 2),
        "transient_recovery_rate_pct": round(transient_recovery_rate, 2),
        "latency_ms": {
            "p50": round(median(latencies), 2) if latencies else 0.0,
            "p95": round(_percentile(latencies, 95), 2),
            "p99": round(_percentile(latencies, 99), 2),
        },
    }


def evaluate_gates(
    *,
    success_rate_pct: float,
    transient_recovery_rate_pct: float,
    hard_failure_rate_pct: float,
    duplicate_writes: int,
    min_success_rate_pct: float = 98.0,
    min_transient_recovery_rate_pct: float = 95.0,
    max_hard_failure_rate_pct: float = 2.0,
) -> dict:
    checks = {
        "success_rate": success_rate_pct >= min_success_rate_pct,
        "transient_recovery": (
            transient_recovery_rate_pct >= min_transient_recovery_rate_pct
        ),
        "hard_failure_rate": hard_failure_rate_pct <= max_hard_failure_rate_pct,
        "duplicate_writes": duplicate_writes == 0,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "thresholds": {
            "min_success_rate_pct": min_success_rate_pct,
            "min_transient_recovery_rate_pct": min_transient_recovery_rate_pct,
            "max_hard_failure_rate_pct": max_hard_failure_rate_pct,
            "required_duplicate_writes": 0,
        },
    }
