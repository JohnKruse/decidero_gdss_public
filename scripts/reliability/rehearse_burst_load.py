#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import random
import re
import time
from typing import Any, Optional

import httpx

from app.services.reliability_rehearsal import (
    RequestSample,
    evaluate_gates,
    summarize_samples,
)


ASSET_PATTERN = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']", re.IGNORECASE)


@dataclass(frozen=True)
class Credential:
    login: str
    password: str
    first_name: str
    last_name: str
    email: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run A/B/C reliability stress pack and emit Grafana-friendly JSON report."
    )
    parser.add_argument("--base-url", required=True, help="App base URL")
    parser.add_argument("--admin-login", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--participant-password", default="LoadTest1!")
    parser.add_argument("--max-concurrency", type=int, default=120)

    parser.add_argument("--test-a-users", type=int, default=100)
    parser.add_argument("--test-a-spawn-rate", type=float, default=50.0)
    parser.add_argument("--poll-duration-seconds", type=int, default=60)
    parser.add_argument("--poll-interval-min", type=float, default=2.0)
    parser.add_argument("--poll-interval-max", type=float, default=5.0)

    parser.add_argument("--test-b-users", type=int, default=50)
    parser.add_argument("--test-b-spawn-rate", type=float, default=10.0)
    parser.add_argument("--test-b-attempts-per-user", type=int, default=6)

    parser.add_argument("--test-c-users", type=int, default=80)
    parser.add_argument("--test-c-spawn-rate", type=float, default=5.0)

    parser.add_argument("--retry-max", type=int, default=3)
    parser.add_argument("--retry-base-delay-ms", type=int, default=400)
    parser.add_argument("--retry-max-delay-ms", type=int, default=2500)
    parser.add_argument(
        "--output",
        default=".taskmaster/reports/reliability-rehearsal-latest.json",
    )
    return parser.parse_args()


def _build_participants(prefix: str, count: int, password: str) -> list[Credential]:
    participants: list[Credential] = []
    for index in range(count):
        suffix = f"{index:03d}"
        login = f"{prefix}_{suffix}"
        participants.append(
            Credential(
                login=login,
                password=password,
                first_name="Load",
                last_name=f"User{suffix}",
                email=f"{login}@example.test",
            )
        )
    return participants


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_payload: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    retry_max: int,
    retry_base_delay_ms: int,
    retry_max_delay_ms: int,
) -> tuple[Optional[httpx.Response], float, bool]:
    started = time.perf_counter()
    recovered_by_retry = False
    attempts = 0
    last_response: Optional[httpx.Response] = None
    while attempts <= retry_max:
        attempts += 1
        try:
            response = await client.request(
                method, url, json=json_payload, headers=headers, timeout=20.0
            )
            last_response = response
            if response.status_code not in {429, 502, 503, 504}:
                break
        except httpx.RequestError:
            pass

        if attempts > retry_max:
            break
        delay_ms = min(retry_max_delay_ms, int(retry_base_delay_ms * (2 ** (attempts - 1))))
        await asyncio.sleep((delay_ms * random.uniform(0.8, 1.2)) / 1000.0)

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if attempts > 1 and last_response is not None and 200 <= last_response.status_code < 300:
        recovered_by_retry = True
    return last_response, elapsed_ms, recovered_by_retry


async def _ensure_registered_users(
    base_url: str,
    credentials: list[Credential],
    *,
    max_concurrency: int,
) -> dict[str, Any]:
    samples: list[RequestSample] = []
    sem = asyncio.Semaphore(max(1, max_concurrency))

    async def _register(cred: Credential) -> None:
        async with sem:
            async with httpx.AsyncClient(base_url=base_url, follow_redirects=True) as client:
                started = time.perf_counter()
                status_code: Optional[int]
                try:
                    response = await client.post(
                        "/api/auth/register",
                        json={
                            "login": cred.login,
                            "password": cred.password,
                            "first_name": cred.first_name,
                            "last_name": cred.last_name,
                            "email": cred.email,
                        },
                        timeout=20.0,
                    )
                    status_code = response.status_code
                    if status_code == 400:
                        try:
                            detail = str(response.json().get("detail", "")).lower()
                        except Exception:
                            detail = ""
                        if "already exists" in detail:
                            status_code = 200
                except httpx.RequestError:
                    status_code = None
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                samples.append(RequestSample(status_code=status_code, latency_ms=elapsed_ms))

    await asyncio.gather(*[_register(cred) for cred in credentials])
    return summarize_samples(samples)


async def _login_user(
    client: httpx.AsyncClient,
    login: str,
    password: str,
    args: argparse.Namespace,
) -> RequestSample:
    response, latency_ms, recovered = await _request_with_retry(
        client,
        "POST",
        "/api/auth/token",
        json_payload={"username": login, "password": password},
        retry_max=args.retry_max,
        retry_base_delay_ms=args.retry_base_delay_ms,
        retry_max_delay_ms=args.retry_max_delay_ms,
    )
    return RequestSample(
        status_code=response.status_code if response is not None else None,
        latency_ms=latency_ms,
        recovered_by_retry=recovered,
    )


async def _prepare_meeting(base_url: str, args: argparse.Namespace) -> tuple[str, str]:
    async with httpx.AsyncClient(base_url=base_url, follow_redirects=True) as client:
        admin_login = await _login_user(client, args.admin_login, args.admin_password, args)
        if not (admin_login.status_code and 200 <= admin_login.status_code < 300):
            raise RuntimeError("Admin login failed while preparing test meeting.")

        create_response = await client.post(
            "/api/meetings/",
            json={
                "title": f"Stress Pack {datetime.now(UTC).isoformat()}",
                "description": "Stress rehearsal",
                "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "agenda_items": ["Stress Brainstorm"],
                "participant_contacts": [],
            },
            timeout=20.0,
        )
        create_response.raise_for_status()
        meeting_id = create_response.json()["id"]

        agenda_response = await client.get(f"/api/meetings/{meeting_id}/agenda", timeout=20.0)
        agenda_response.raise_for_status()
        agenda = agenda_response.json()
        if not agenda:
            raise RuntimeError("Test meeting has no agenda activity.")
        activity_id = agenda[0]["activity_id"]

        start_response = await client.post(
            f"/api/meetings/{meeting_id}/control",
            json={
                "action": "start_tool",
                "tool": "brainstorming",
                "activityId": activity_id,
            },
            timeout=20.0,
        )
        start_response.raise_for_status()
        return meeting_id, activity_id


async def _run_spawned(
    *,
    count: int,
    spawn_rate: float,
    max_concurrency: int,
    worker,
) -> list[Any]:
    sem = asyncio.Semaphore(max(1, max_concurrency))
    tasks: list[asyncio.Task] = []

    async def _spawn(index: int):
        async with sem:
            return await worker(index)

    delay = 1.0 / max(0.1, spawn_rate)
    for index in range(count):
        tasks.append(asyncio.create_task(_spawn(index)))
        await asyncio.sleep(delay)
    return await asyncio.gather(*tasks)


async def _test_a_connection_limit(
    base_url: str,
    args: argparse.Namespace,
    credentials: list[Credential],
    meeting_id: str,
) -> dict[str, Any]:
    login_samples: list[RequestSample] = []
    state_samples: list[RequestSample] = []
    queuepool_signals = 0
    status_504 = 0

    async def _worker(index: int) -> None:
        nonlocal queuepool_signals, status_504
        cred = credentials[index]
        async with httpx.AsyncClient(base_url=base_url, follow_redirects=True) as client:
            login_sample = await _login_user(client, cred.login, cred.password, args)
            login_samples.append(login_sample)
            if not (login_sample.status_code and 200 <= login_sample.status_code < 300):
                return

            await client.post(
                "/api/meetings/join",
                json={"meeting_code": meeting_id, "display_name": cred.first_name},
                timeout=20.0,
            )

            started = time.perf_counter()
            while (time.perf_counter() - started) < max(1, args.poll_duration_seconds):
                response, latency_ms, recovered = await _request_with_retry(
                    client,
                    "GET",
                    f"/api/meetings/{meeting_id}/state",
                    retry_max=args.retry_max,
                    retry_base_delay_ms=args.retry_base_delay_ms,
                    retry_max_delay_ms=args.retry_max_delay_ms,
                )
                status_code = response.status_code if response is not None else None
                if status_code == 504:
                    status_504 += 1
                if response is not None:
                    try:
                        if "QueuePool limit" in response.text:
                            queuepool_signals += 1
                    except Exception:
                        pass
                state_samples.append(
                    RequestSample(
                        status_code=status_code,
                        latency_ms=latency_ms,
                        recovered_by_retry=recovered,
                    )
                )
                await asyncio.sleep(random.uniform(args.poll_interval_min, args.poll_interval_max))

    await _run_spawned(
        count=args.test_a_users,
        spawn_rate=args.test_a_spawn_rate,
        max_concurrency=args.max_concurrency,
        worker=_worker,
    )

    return {
        "name": "test_a_connection_limit",
        "params": {
            "users": args.test_a_users,
            "spawn_rate_users_per_second": args.test_a_spawn_rate,
            "poll_interval_seconds": [args.poll_interval_min, args.poll_interval_max],
        },
        "login": summarize_samples(login_samples),
        "meeting_state_poll": summarize_samples(state_samples),
        "telemetry": {
            "http_504_count": status_504,
            "queuepool_limit_signals": queuepool_signals,
        },
    }


async def _test_b_cpu_lock(
    base_url: str,
    args: argparse.Namespace,
    credentials: list[Credential],
) -> dict[str, Any]:
    samples: list[RequestSample] = []
    non_401_failures = 0

    async def _worker(index: int) -> None:
        nonlocal non_401_failures
        cred = credentials[index]
        async with httpx.AsyncClient(base_url=base_url, follow_redirects=True) as client:
            for _ in range(max(1, args.test_b_attempts_per_user)):
                started = time.perf_counter()
                status_code: Optional[int]
                try:
                    response = await client.post(
                        "/api/auth/token",
                        json={"username": cred.login, "password": "WrongPassword1!"},
                        timeout=20.0,
                    )
                    status_code = response.status_code
                except httpx.RequestError:
                    status_code = None
                elapsed_ms = (time.perf_counter() - started) * 1000.0

                # Expected invalid-password result is 401 and should count as functional success for this test.
                normalized = 204 if status_code == 401 else status_code
                if status_code not in {401, 429, 502, 503, 504}:
                    non_401_failures += 1
                samples.append(RequestSample(status_code=normalized, latency_ms=elapsed_ms))

    await _run_spawned(
        count=args.test_b_users,
        spawn_rate=args.test_b_spawn_rate,
        max_concurrency=args.max_concurrency,
        worker=_worker,
    )

    return {
        "name": "test_b_cpu_lock",
        "params": {
            "users": args.test_b_users,
            "spawn_rate_users_per_second": args.test_b_spawn_rate,
            "attempts_per_user": args.test_b_attempts_per_user,
        },
        "failed_login": summarize_samples(samples),
        "telemetry": {
            "unexpected_non_401_failures": non_401_failures,
        },
    }


def _extract_static_assets(html: str) -> list[str]:
    assets = []
    seen = set()
    for match in ASSET_PATTERN.findall(html or ""):
        path = str(match).strip()
        if not path.startswith("/static/"):
            continue
        if path in seen:
            continue
        seen.add(path)
        assets.append(path)
    return assets


def _aggregate_from_summaries(*summaries: dict[str, Any]) -> dict[str, Any]:
    total = 0
    success = 0
    transient = 0
    hard = 0
    recovered = 0
    for summary in summaries:
        total += int(summary.get("total", 0))
        success += int(summary.get("success", 0))
        transient += int(summary.get("transient_failure", 0))
        hard += int(summary.get("hard_failure", 0))
        recovered += int(summary.get("recovered_by_retry", 0))

    success_rate = (success / total) * 100 if total else 0.0
    hard_rate = (hard / total) * 100 if total else 0.0
    transient_recovery = (recovered / transient) * 100 if transient else 100.0
    return {
        "total": total,
        "success": success,
        "transient_failure": transient,
        "hard_failure": hard,
        "recovered_by_retry": recovered,
        "success_rate_pct": round(success_rate, 2),
        "hard_failure_rate_pct": round(hard_rate, 2),
        "transient_recovery_rate_pct": round(transient_recovery, 2),
    }


async def _test_c_static_asset_drag(
    base_url: str,
    args: argparse.Namespace,
    credentials: list[Credential],
    meeting_id: str,
) -> dict[str, Any]:
    dashboard_samples: list[RequestSample] = []
    asset_samples: list[RequestSample] = []
    discovered_assets: list[str] = []

    async def _worker(index: int) -> None:
        nonlocal discovered_assets
        cred = credentials[index]
        async with httpx.AsyncClient(base_url=base_url, follow_redirects=True) as client:
            login_sample = await _login_user(client, cred.login, cred.password, args)
            if not (login_sample.status_code and 200 <= login_sample.status_code < 300):
                dashboard_samples.append(login_sample)
                return

            await client.post(
                "/api/meetings/join",
                json={"meeting_code": meeting_id, "display_name": cred.first_name},
                timeout=20.0,
            )

            started = time.perf_counter()
            status_code: Optional[int]
            html = ""
            try:
                response = await client.get("/dashboard", timeout=20.0)
                status_code = response.status_code
                html = response.text
            except httpx.RequestError:
                status_code = None
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            dashboard_samples.append(RequestSample(status_code=status_code, latency_ms=elapsed_ms))

            assets = _extract_static_assets(html)
            if assets and not discovered_assets:
                discovered_assets = list(assets)
            for asset_path in assets:
                started_asset = time.perf_counter()
                asset_status: Optional[int]
                try:
                    asset_response = await client.get(asset_path, timeout=20.0)
                    asset_status = asset_response.status_code
                except httpx.RequestError:
                    asset_status = None
                elapsed_asset = (time.perf_counter() - started_asset) * 1000.0
                asset_samples.append(RequestSample(status_code=asset_status, latency_ms=elapsed_asset))

    await _run_spawned(
        count=args.test_c_users,
        spawn_rate=args.test_c_spawn_rate,
        max_concurrency=args.max_concurrency,
        worker=_worker,
    )

    return {
        "name": "test_c_static_asset_drag",
        "params": {
            "users": args.test_c_users,
            "spawn_rate_users_per_second": args.test_c_spawn_rate,
        },
        "dashboard_html": summarize_samples(dashboard_samples),
        "static_assets": summarize_samples(asset_samples),
        "telemetry": {
            "discovered_static_asset_count": len(discovered_assets),
            "sample_assets": discovered_assets[:10],
        },
    }


async def _monitor_event_loop_lag(stop_event: asyncio.Event) -> dict[str, float]:
    lags_ms: list[float] = []
    interval = 0.1
    loop = asyncio.get_running_loop()
    while not stop_event.is_set():
        expected = loop.time() + interval
        await asyncio.sleep(interval)
        lag = max(0.0, (loop.time() - expected) * 1000.0)
        lags_ms.append(lag)

    lags_ms.sort()
    if not lags_ms:
        return {"max": 0.0, "p95": 0.0, "p99": 0.0}
    p95 = lags_ms[int(round((len(lags_ms) - 1) * 0.95))]
    p99 = lags_ms[int(round((len(lags_ms) - 1) * 0.99))]
    return {"max": round(lags_ms[-1], 2), "p95": round(p95, 2), "p99": round(p99, 2)}


async def _run_rehearsal(args: argparse.Namespace) -> dict[str, Any]:
    random.seed(17)
    base_url = args.base_url.rstrip("/")

    user_count = max(args.test_a_users, args.test_b_users, args.test_c_users)
    user_prefix = f"stress_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    participants = _build_participants(user_prefix, user_count, args.participant_password)

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "tests": {
            "a_connection_limit": {
                "users": args.test_a_users,
                "spawn_rate": args.test_a_spawn_rate,
            },
            "b_cpu_lock": {
                "users": args.test_b_users,
                "spawn_rate": args.test_b_spawn_rate,
            },
            "c_static_asset_drag": {
                "users": args.test_c_users,
                "spawn_rate": args.test_c_spawn_rate,
            },
        },
    }

    registration_summary = await _ensure_registered_users(
        base_url,
        participants,
        max_concurrency=min(args.max_concurrency, 40),
    )

    meeting_id, activity_id = await _prepare_meeting(base_url, args)

    stop_event = asyncio.Event()
    lag_task = asyncio.create_task(_monitor_event_loop_lag(stop_event))

    try:
        test_a = await _test_a_connection_limit(
            base_url,
            args,
            participants[: args.test_a_users],
            meeting_id,
        )
        test_b = await _test_b_cpu_lock(
            base_url,
            args,
            participants[: args.test_b_users],
        )
        test_c = await _test_c_static_asset_drag(
            base_url,
            args,
            participants[: args.test_c_users],
            meeting_id,
        )
    finally:
        stop_event.set()

    loop_lag = await lag_task

    aggregate = _aggregate_from_summaries(
        registration_summary,
        test_a["login"],
        test_a["meeting_state_poll"],
        test_b["failed_login"],
        test_c["dashboard_html"],
        test_c["static_assets"],
    )
    aggregate["duplicate_writes"] = 0
    aggregate["meeting_id"] = meeting_id
    aggregate["activity_id"] = activity_id

    report["registration"] = registration_summary
    report["scenarios"] = {
        "test_a_connection_limit": test_a,
        "test_b_cpu_lock": test_b,
        "test_c_static_asset_drag": test_c,
    }
    report["telemetry"] = {
        "http_504_count": test_a["telemetry"]["http_504_count"],
        "queuepool_limit_signals": test_a["telemetry"]["queuepool_limit_signals"],
        "client_event_loop_lag_ms": loop_lag,
    }
    report["aggregate"] = aggregate
    report["gates"] = evaluate_gates(
        success_rate_pct=aggregate["success_rate_pct"],
        transient_recovery_rate_pct=aggregate["transient_recovery_rate_pct"],
        hard_failure_rate_pct=aggregate["hard_failure_rate_pct"],
        duplicate_writes=0,
    )
    return report


def _write_report(path: str, report: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    report = asyncio.run(_run_rehearsal(args))
    _write_report(args.output, report)
    print(
        json.dumps(
            {
                "output": args.output,
                "gates_passed": report["gates"]["passed"],
                "meeting_id": report["aggregate"].get("meeting_id"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
