from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

_DEFAULT_BRAINSTORMING_LIMITS = {
    "idea_character_limit": 500,
    "max_ideas_per_user": 50,
}
_DEFAULT_MEETING_REFRESH = {
    "enabled": True,
    "interval_seconds": 8,
    "hidden_interval_seconds": 45,
    "failure_backoff_seconds": 60,
    "write_priority_backoff_seconds": 8,
    "overload_backoff_seconds": 12,
    "jitter_ratio": 0.2,
}
_DEFAULT_UI_REFRESH = {
    "enabled": True,
    "dashboard_interval_seconds": 20,
    "admin_users_interval_seconds": 15,
    "hidden_interval_seconds": 20,
    "failure_backoff_seconds": 90,
}
_DEFAULT_MEETING_ACTIVITY_LOG = {
    "max_items": 100,
}
_DEFAULT_AUTOSAVE_SECONDS = 10
_DEFAULT_AUTH_LOGIN_RATE_LIMIT = {
    "enabled": True,
    "window_seconds": 60,
    "max_failures_per_username": 8,
    "max_failures_per_ip": 40,
    "lockout_seconds": 60,
}
_DEFAULT_FRONTEND_RELIABILITY = {
    "write_default": {
        "retryable_statuses": [429, 502, 503, 504],
        "max_retries": 2,
        "base_delay_ms": 350,
        "max_delay_ms": 1800,
        "jitter_ratio": 0.2,
        "idempotency_header": "X-Idempotency-Key",
    },
    "brainstorming_submit": {
        "retryable_statuses": [429, 502, 503, 504],
        "max_retries": 3,
        "base_delay_ms": 400,
        "max_delay_ms": 2500,
        "jitter_ratio": 0.25,
        "idempotency_header": "X-Idempotency-Key",
    },
    "login": {
        "retryable_statuses": [429, 503],
        "max_retries": 2,
        "base_delay_ms": 450,
        "max_delay_ms": 1800,
        "jitter_ratio": 0.2,
    },
    "registration": {
        "retryable_statuses": [429, 503],
        "max_retries": 0,
        "base_delay_ms": 450,
        "max_delay_ms": 1800,
        "jitter_ratio": 0.2,
    },
}


def load_config() -> Dict[str, Any]:
    """Load the application config from YAML, returning an empty mapping on error."""
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
            if isinstance(data, dict):
                return data
            logging.warning(
                "Config file %s is not a mapping; using defaults.", _CONFIG_PATH
            )
            return {}
    except FileNotFoundError:
        logging.warning(
            "Configuration file %s not found; using defaults.", _CONFIG_PATH
        )
        return {}
    except Exception as exc:  # noqa: BLE001
        logging.error("Failed to load configuration from %s: %s", _CONFIG_PATH, exc)
        return {}


def get_brainstorming_limits() -> Dict[str, int]:
    """Return brainstorming limits sourced from config with safe defaults."""
    config = load_config()
    section = config.get("brainstorming") or {}
    limits = dict(_DEFAULT_BRAINSTORMING_LIMITS)

    def _coerce_positive_int(value: Any, fallback: int) -> int:
        try:
            candidate = int(value)
            return candidate if candidate > 0 else fallback
        except Exception:  # noqa: BLE001
            return fallback

    limits["idea_character_limit"] = _coerce_positive_int(
        section.get("idea_character_limit"), limits["idea_character_limit"]
    )
    limits["max_ideas_per_user"] = _coerce_positive_int(
        section.get("max_ideas_per_user"), limits["max_ideas_per_user"]
    )
    return limits


def get_brainstorming_defaults() -> Dict[str, bool]:
    """Return default brainstorming activity config from config file."""
    config = load_config()
    section = config.get("brainstorming") or {}
    return {
        "allow_anonymous": bool(section.get("default_maintain_anonymity", False)),
        "allow_subcomments": bool(section.get("default_allow_subcomments", False)),
        "auto_jump_new_ideas": bool(section.get("default_auto_jump_new_ideas", True)),
    }


def get_activity_participant_exclusivity() -> bool:
    """Return whether participants must be exclusive across concurrent activities."""
    config = load_config()
    value = config.get("activity_participant_exclusivity")
    if value is None:
        return True
    return bool(value)


def get_meeting_refresh_settings() -> Dict[str, Any]:
    """Return meeting refresh polling settings sourced from config with safe defaults."""
    config = load_config()
    section = config.get("meeting_refresh") or {}

    def _coerce_positive_int(value: Any, fallback: int) -> int:
        try:
            candidate = int(value)
            return candidate if candidate > 0 else fallback
        except Exception:  # noqa: BLE001
            return fallback

    def _coerce_bool(value: Any, fallback: bool) -> bool:
        if value is None:
            return fallback
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    defaults = dict(_DEFAULT_MEETING_REFRESH)
    return {
        "enabled": _coerce_bool(section.get("enabled"), defaults["enabled"]),
        "interval_seconds": _coerce_positive_int(
            section.get("interval_seconds"), defaults["interval_seconds"]
        ),
        "hidden_interval_seconds": _coerce_positive_int(
            section.get("hidden_interval_seconds"),
            defaults["hidden_interval_seconds"],
        ),
        "failure_backoff_seconds": _coerce_positive_int(
            section.get("failure_backoff_seconds"),
            defaults["failure_backoff_seconds"],
        ),
        "write_priority_backoff_seconds": _coerce_positive_int(
            section.get("write_priority_backoff_seconds"),
            defaults["write_priority_backoff_seconds"],
        ),
        "overload_backoff_seconds": _coerce_positive_int(
            section.get("overload_backoff_seconds"),
            defaults["overload_backoff_seconds"],
        ),
        "jitter_ratio": _coerce_jitter_ratio(
            section.get("jitter_ratio"),
            defaults["jitter_ratio"],
        ),
    }


def _coerce_jitter_ratio(value: Any, fallback: float) -> float:
    try:
        candidate = float(value)
    except Exception:  # noqa: BLE001
        candidate = fallback
    return max(0.0, min(1.0, candidate))


def _normalise_retry_policy(
    raw_policy: Any,
    defaults: Dict[str, Any],
    *,
    include_idempotency: bool,
) -> Dict[str, Any]:
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    merged = dict(defaults)

    raw_statuses = policy.get("retryable_statuses")
    if isinstance(raw_statuses, list):
        statuses = []
        for value in raw_statuses:
            try:
                status = int(value)
            except Exception:  # noqa: BLE001
                continue
            if 100 <= status <= 599 and status not in statuses:
                statuses.append(status)
        if statuses:
            merged["retryable_statuses"] = statuses

    for key in ("max_retries", "base_delay_ms", "max_delay_ms"):
        try:
            candidate = int(policy.get(key))
        except Exception:  # noqa: BLE001
            continue
        if candidate >= 0:
            merged[key] = candidate

    merged["base_delay_ms"] = max(1, int(merged["base_delay_ms"]))
    merged["max_delay_ms"] = max(merged["base_delay_ms"], int(merged["max_delay_ms"]))
    merged["max_retries"] = max(0, int(merged["max_retries"]))
    merged["jitter_ratio"] = _coerce_jitter_ratio(
        policy.get("jitter_ratio"),
        float(defaults["jitter_ratio"]),
    )

    if include_idempotency:
        header = policy.get("idempotency_header")
        if isinstance(header, str) and header.strip():
            merged["idempotency_header"] = header.strip()
    else:
        merged.pop("idempotency_header", None)

    return merged


def get_frontend_reliability_settings() -> Dict[str, Any]:
    """Return frontend retry/backoff defaults used by auth and meeting UI paths."""
    config = load_config()
    section = config.get("frontend_reliability") or {}
    defaults = _DEFAULT_FRONTEND_RELIABILITY

    return {
        "write_default": _normalise_retry_policy(
            section.get("write_default"),
            defaults["write_default"],
            include_idempotency=True,
        ),
        "brainstorming_submit": _normalise_retry_policy(
            section.get("brainstorming_submit"),
            defaults["brainstorming_submit"],
            include_idempotency=True,
        ),
        "login": _normalise_retry_policy(
            section.get("login"),
            defaults["login"],
            include_idempotency=False,
        ),
        "registration": _normalise_retry_policy(
            section.get("registration"),
            defaults["registration"],
            include_idempotency=False,
        ),
    }


def get_ui_refresh_settings() -> Dict[str, Any]:
    """Return UI refresh polling settings sourced from config with safe defaults."""
    config = load_config()
    section = config.get("ui_refresh") or {}

    def _coerce_positive_int(value: Any, fallback: int) -> int:
        try:
            candidate = int(value)
            return candidate if candidate > 0 else fallback
        except Exception:  # noqa: BLE001
            return fallback

    def _coerce_bool(value: Any, fallback: bool) -> bool:
        if value is None:
            return fallback
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    defaults = dict(_DEFAULT_UI_REFRESH)
    return {
        "enabled": _coerce_bool(section.get("enabled"), defaults["enabled"]),
        "dashboard_interval_seconds": _coerce_positive_int(
            section.get("dashboard_interval_seconds"),
            defaults["dashboard_interval_seconds"],
        ),
        "admin_users_interval_seconds": _coerce_positive_int(
            section.get("admin_users_interval_seconds"),
            defaults["admin_users_interval_seconds"],
        ),
        "hidden_interval_seconds": _coerce_positive_int(
            section.get("hidden_interval_seconds"),
            defaults["hidden_interval_seconds"],
        ),
        "failure_backoff_seconds": _coerce_positive_int(
            section.get("failure_backoff_seconds"),
            defaults["failure_backoff_seconds"],
        ),
    }


def get_meeting_activity_log_settings() -> Dict[str, Any]:
    """Return meeting activity log settings sourced from config with safe defaults."""
    config = load_config()
    section = config.get("meeting_activity_log") or {}

    def _coerce_positive_int(value: Any, fallback: int) -> int:
        try:
            candidate = int(value)
            return candidate if candidate > 0 else fallback
        except Exception:  # noqa: BLE001
            return fallback

    defaults = dict(_DEFAULT_MEETING_ACTIVITY_LOG)
    return {
        "max_items": _coerce_positive_int(section.get("max_items"), defaults["max_items"]),
    }


def get_guest_join_enabled() -> bool:
    """Return whether unauthenticated guest meeting joins are enabled."""
    config = load_config()
    section = config.get("auth") or {}

    def _coerce_bool(value: Any, fallback: bool) -> bool:
        if value is None:
            return fallback
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    return _coerce_bool(section.get("allow_guest_join"), False)


def get_secure_cookies_enabled() -> bool:
    """
    Return whether auth cookies should be marked Secure.

    Priority:
    1) DECIDERO_SECURE_COOKIES env var
    2) config.yaml auth.secure_cookies
    3) default False (local HTTP-friendly)
    """
    env_value = os.getenv("DECIDERO_SECURE_COOKIES")
    if env_value is not None:
        return env_value.strip().lower() in {"1", "true", "yes", "on"}

    config = load_config()
    section = config.get("auth") or {}
    value = section.get("secure_cookies")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def get_auth_login_rate_limit_settings() -> Dict[str, Any]:
    """Return failed-login rate limiting settings with env/config overrides."""
    config = load_config()
    auth_section = config.get("auth") or {}
    section = auth_section.get("login_rate_limit") or {}
    defaults = dict(_DEFAULT_AUTH_LOGIN_RATE_LIMIT)

    def _env_bool(name: str) -> Any:
        value = os.getenv(name)
        if value is None:
            return None
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _env_int(name: str) -> Any:
        value = os.getenv(name)
        if value is None:
            return None
        try:
            return int(value)
        except Exception:  # noqa: BLE001
            return None

    def _coerce_positive_int(value: Any, fallback: int) -> int:
        try:
            candidate = int(value)
            return candidate if candidate > 0 else fallback
        except Exception:  # noqa: BLE001
            return fallback

    def _coerce_bool(value: Any, fallback: bool) -> bool:
        if value is None:
            return fallback
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    enabled = _env_bool("DECIDERO_LOGIN_RATE_LIMIT_ENABLED")
    if enabled is None:
        enabled = section.get("enabled")
    window_seconds = _env_int("DECIDERO_LOGIN_RATE_LIMIT_WINDOW_SECONDS")
    if window_seconds is None:
        window_seconds = section.get("window_seconds")
    max_fail_user = _env_int("DECIDERO_LOGIN_RATE_LIMIT_MAX_FAILURES_PER_USERNAME")
    if max_fail_user is None:
        max_fail_user = section.get("max_failures_per_username")
    max_fail_ip = _env_int("DECIDERO_LOGIN_RATE_LIMIT_MAX_FAILURES_PER_IP")
    if max_fail_ip is None:
        max_fail_ip = section.get("max_failures_per_ip")
    lockout_seconds = _env_int("DECIDERO_LOGIN_RATE_LIMIT_LOCKOUT_SECONDS")
    if lockout_seconds is None:
        lockout_seconds = section.get("lockout_seconds")

    return {
        "enabled": _coerce_bool(enabled, defaults["enabled"]),
        "window_seconds": _coerce_positive_int(
            window_seconds, defaults["window_seconds"]
        ),
        "max_failures_per_username": _coerce_positive_int(
            max_fail_user, defaults["max_failures_per_username"]
        ),
        "max_failures_per_ip": _coerce_positive_int(
            max_fail_ip, defaults["max_failures_per_ip"]
        ),
        "lockout_seconds": _coerce_positive_int(
            lockout_seconds, defaults["lockout_seconds"]
        ),
    }


def get_autosave_seconds() -> int:
    """Return the default autosave interval in seconds."""
    config = load_config()
    value = config.get("autosave_seconds", _DEFAULT_AUTOSAVE_SECONDS)
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        candidate = _DEFAULT_AUTOSAVE_SECONDS
    return candidate
