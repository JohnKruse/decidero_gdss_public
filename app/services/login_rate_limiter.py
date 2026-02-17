from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import ceil
from threading import Lock
import time
from typing import Deque, Dict, Tuple

from app.config.loader import get_auth_login_rate_limit_settings


@dataclass(frozen=True)
class LoginRateLimitSettings:
    enabled: bool
    window_seconds: int
    max_failures_per_username: int
    max_failures_per_ip: int
    lockout_seconds: int


class LoginRateLimiter:
    """In-process failed-login limiter for burst protection."""

    def __init__(self, settings: LoginRateLimitSettings):
        self._lock = Lock()
        self._settings = settings
        self._failures_by_username: Dict[str, Deque[float]] = {}
        self._failures_by_ip: Dict[str, Deque[float]] = {}
        self._locked_username_until: Dict[str, float] = {}
        self._locked_ip_until: Dict[str, float] = {}

    def set_settings(self, settings: LoginRateLimitSettings) -> None:
        with self._lock:
            self._settings = settings
            self.reset()

    def reset(self) -> None:
        self._failures_by_username.clear()
        self._failures_by_ip.clear()
        self._locked_username_until.clear()
        self._locked_ip_until.clear()

    def _prune_failures(self, bucket: Dict[str, Deque[float]], key: str, now: float) -> None:
        entries = bucket.get(key)
        if not entries:
            return
        window_start = now - self._settings.window_seconds
        while entries and entries[0] < window_start:
            entries.popleft()
        if not entries:
            bucket.pop(key, None)

    def _prune_lock(self, bucket: Dict[str, float], key: str, now: float) -> None:
        expires_at = bucket.get(key)
        if expires_at is not None and expires_at <= now:
            bucket.pop(key, None)

    def check_limited(self, *, username: str, ip: str) -> Tuple[bool, int]:
        with self._lock:
            if not self._settings.enabled:
                return False, 0
            now = time.monotonic()
            username_key = (username or "").strip().lower() or "unknown"
            ip_key = (ip or "").strip() or "unknown"
            self._prune_lock(self._locked_username_until, username_key, now)
            self._prune_lock(self._locked_ip_until, ip_key, now)

            remaining = 0.0
            username_until = self._locked_username_until.get(username_key)
            ip_until = self._locked_ip_until.get(ip_key)
            if username_until:
                remaining = max(remaining, username_until - now)
            if ip_until:
                remaining = max(remaining, ip_until - now)
            if remaining <= 0:
                return False, 0
            return True, max(1, int(ceil(remaining)))

    def record_failure(self, *, username: str, ip: str) -> None:
        with self._lock:
            if not self._settings.enabled:
                return
            now = time.monotonic()
            username_key = (username or "").strip().lower() or "unknown"
            ip_key = (ip or "").strip() or "unknown"

            self._prune_failures(self._failures_by_username, username_key, now)
            self._prune_failures(self._failures_by_ip, ip_key, now)

            user_failures = self._failures_by_username.setdefault(username_key, deque())
            ip_failures = self._failures_by_ip.setdefault(ip_key, deque())
            user_failures.append(now)
            ip_failures.append(now)

            if len(user_failures) >= self._settings.max_failures_per_username:
                self._locked_username_until[username_key] = (
                    now + self._settings.lockout_seconds
                )
            if len(ip_failures) >= self._settings.max_failures_per_ip:
                self._locked_ip_until[ip_key] = now + self._settings.lockout_seconds

    def record_success(self, *, username: str, ip: str) -> None:
        with self._lock:
            username_key = (username or "").strip().lower() or "unknown"
            ip_key = (ip or "").strip() or "unknown"
            self._failures_by_username.pop(username_key, None)
            self._failures_by_ip.pop(ip_key, None)
            self._locked_username_until.pop(username_key, None)
            self._locked_ip_until.pop(ip_key, None)


def _load_settings() -> LoginRateLimitSettings:
    raw = get_auth_login_rate_limit_settings()
    return LoginRateLimitSettings(
        enabled=bool(raw.get("enabled", True)),
        window_seconds=int(raw.get("window_seconds", 60)),
        max_failures_per_username=int(raw.get("max_failures_per_username", 8)),
        max_failures_per_ip=int(raw.get("max_failures_per_ip", 40)),
        lockout_seconds=int(raw.get("lockout_seconds", 60)),
    )


login_rate_limiter = LoginRateLimiter(_load_settings())
