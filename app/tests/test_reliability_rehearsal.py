from app.services.reliability_rehearsal import (
    RequestSample,
    classify_status,
    evaluate_gates,
    summarize_samples,
)


def test_classify_status_groups_transient_and_hard_failures():
    assert classify_status(201) == "success"
    assert classify_status(429) == "transient_failure"
    assert classify_status(503) == "transient_failure"
    assert classify_status(401) == "hard_failure"
    assert classify_status(None) == "hard_failure"


def test_summarize_samples_calculates_rates_and_latencies():
    summary = summarize_samples(
        [
            RequestSample(status_code=201, latency_ms=100),
            RequestSample(status_code=429, latency_ms=200, recovered_by_retry=True),
            RequestSample(status_code=503, latency_ms=300, recovered_by_retry=False),
            RequestSample(status_code=401, latency_ms=400),
        ]
    )
    assert summary["total"] == 4
    assert summary["success"] == 1
    assert summary["transient_failure"] == 2
    assert summary["hard_failure"] == 1
    assert summary["recovered_by_retry"] == 1
    assert summary["success_rate_pct"] == 25.0
    assert summary["hard_failure_rate_pct"] == 25.0
    assert summary["transient_recovery_rate_pct"] == 50.0
    assert summary["latency_ms"]["p50"] == 250.0
    assert summary["latency_ms"]["p95"] >= 300.0


def test_evaluate_gates_requires_zero_duplicates():
    passing = evaluate_gates(
        success_rate_pct=99.0,
        transient_recovery_rate_pct=95.0,
        hard_failure_rate_pct=1.0,
        duplicate_writes=0,
    )
    assert passing["passed"] is True

    failing = evaluate_gates(
        success_rate_pct=99.0,
        transient_recovery_rate_pct=95.0,
        hard_failure_rate_pct=1.0,
        duplicate_writes=2,
    )
    assert failing["passed"] is False
    assert failing["checks"]["duplicate_writes"] is False
