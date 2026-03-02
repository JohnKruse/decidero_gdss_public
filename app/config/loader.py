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


# ── DB settings overlay ──────────────────────────────────────────────────────
# Each public getter below checks the runtime settings DB before falling back
# to config.yaml.  The import is lazy to avoid a circular dependency:
#   database.py → load_config (in loader.py) → settings_store → database.py
#
# Priority: DB override  →  config.yaml  →  hardcoded default

def _db_get(key: str) -> Any:
    """Return the DB-stored override for *key*, or ``None`` if not set.

    Never raises; logs and returns ``None`` on any error so that callers
    always fall through to their config.yaml / hardcoded fallback.
    """
    try:
        from app.config.settings_store import get_setting  # noqa: PLC0415
        return get_setting(key)
    except Exception as exc:  # noqa: BLE001
        logging.debug("_db_get(%r) skipped (DB not ready?): %s", key, exc)
        return None


# ── YAML loader ──────────────────────────────────────────────────────────────

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


# ── Shared coercion helpers ───────────────────────────────────────────────────

def _coerce_jitter_ratio(value: Any, fallback: float) -> float:
    try:
        candidate = float(value)
    except Exception:  # noqa: BLE001
        candidate = fallback
    return max(0.0, min(1.0, candidate))


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


# ── Public getters ────────────────────────────────────────────────────────────

def get_brainstorming_limits() -> Dict[str, int]:
    """Return brainstorming limits. DB overrides take priority over config.yaml."""
    config = load_config()
    section = config.get("brainstorming") or {}
    limits = dict(_DEFAULT_BRAINSTORMING_LIMITS)

    limits["idea_character_limit"] = _coerce_positive_int(
        section.get("idea_character_limit"), limits["idea_character_limit"]
    )
    limits["max_ideas_per_user"] = _coerce_positive_int(
        section.get("max_ideas_per_user"), limits["max_ideas_per_user"]
    )

    # DB overlays (Settings UI → highest priority)
    db_char = _db_get("brainstorming.idea_character_limit")
    if db_char is not None:
        limits["idea_character_limit"] = _coerce_positive_int(
            db_char, limits["idea_character_limit"]
        )
    db_max = _db_get("brainstorming.max_ideas_per_user")
    if db_max is not None:
        limits["max_ideas_per_user"] = _coerce_positive_int(
            db_max, limits["max_ideas_per_user"]
        )

    return limits


def get_brainstorming_defaults() -> Dict[str, bool]:
    """Return default brainstorming activity config. DB overrides take priority."""
    config = load_config()
    section = config.get("brainstorming") or {}

    allow_anonymous = _coerce_bool(section.get("default_maintain_anonymity"), False)
    allow_subcomments = _coerce_bool(section.get("default_allow_subcomments"), False)
    auto_jump = _coerce_bool(section.get("default_auto_jump_new_ideas"), True)

    # DB overlays
    db_anon = _db_get("brainstorming.default_maintain_anonymity")
    if db_anon is not None:
        allow_anonymous = _coerce_bool(db_anon, allow_anonymous)
    db_sub = _db_get("brainstorming.default_allow_subcomments")
    if db_sub is not None:
        allow_subcomments = _coerce_bool(db_sub, allow_subcomments)
    db_jump = _db_get("brainstorming.default_auto_jump_new_ideas")
    if db_jump is not None:
        auto_jump = _coerce_bool(db_jump, auto_jump)

    return {
        "allow_anonymous": allow_anonymous,
        "allow_subcomments": allow_subcomments,
        "auto_jump_new_ideas": auto_jump,
    }


def get_activity_participant_exclusivity() -> bool:
    """Return whether participants must be exclusive across concurrent activities."""
    config = load_config()
    yaml_value = config.get("activity_participant_exclusivity")
    base = True if yaml_value is None else _coerce_bool(yaml_value, True)

    db_val = _db_get("meetings.activity_participant_exclusivity")
    if db_val is not None:
        return _coerce_bool(db_val, base)
    return base


def get_meeting_refresh_settings() -> Dict[str, Any]:
    """Return meeting refresh polling settings sourced from config with safe defaults.

    These are infrastructure-level settings not exposed in the Settings UI.
    """
    config = load_config()
    section = config.get("meeting_refresh") or {}
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
    """Return frontend retry/backoff defaults used by auth and meeting UI paths.

    Infrastructure-level settings; not exposed in the Settings UI.
    """
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
    """Return UI refresh polling settings sourced from config with safe defaults.

    Infrastructure-level settings; not exposed in the Settings UI.
    """
    config = load_config()
    section = config.get("ui_refresh") or {}
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
    defaults = dict(_DEFAULT_MEETING_ACTIVITY_LOG)
    return {
        "max_items": _coerce_positive_int(section.get("max_items"), defaults["max_items"]),
    }


def get_guest_join_enabled() -> bool:
    """Return whether unauthenticated guest meeting joins are enabled."""
    config = load_config()
    section = config.get("auth") or {}
    base = _coerce_bool(section.get("allow_guest_join"), False)

    db_val = _db_get("meetings.allow_guest_join")
    if db_val is not None:
        return _coerce_bool(db_val, base)
    return base


def get_secure_cookies_enabled() -> bool:
    """
    Return whether auth cookies should be marked Secure.

    Priority:
    1) DECIDERO_SECURE_COOKIES env var  (infrastructure — not in Settings UI)
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
    """Return failed-login rate limiting settings.

    Priority: env vars → DB override → config.yaml → hardcoded defaults.
    """
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

    # Env vars (highest priority for security settings)
    enabled = _env_bool("DECIDERO_LOGIN_RATE_LIMIT_ENABLED")
    window_seconds = _env_int("DECIDERO_LOGIN_RATE_LIMIT_WINDOW_SECONDS")
    max_fail_user = _env_int("DECIDERO_LOGIN_RATE_LIMIT_MAX_FAILURES_PER_USERNAME")
    max_fail_ip = _env_int("DECIDERO_LOGIN_RATE_LIMIT_MAX_FAILURES_PER_IP")
    lockout_seconds = _env_int("DECIDERO_LOGIN_RATE_LIMIT_LOCKOUT_SECONDS")

    # DB overlays (when env var is not set)
    if enabled is None:
        db_en = _db_get("security.login_rate_limit_enabled")
        enabled = db_en if db_en is not None else section.get("enabled")
    if window_seconds is None:
        db_ws = _db_get("security.login_rate_limit_window_seconds")
        window_seconds = db_ws if db_ws is not None else section.get("window_seconds")
    if max_fail_user is None:
        db_mfu = _db_get("security.login_rate_limit_max_failures_per_username")
        max_fail_user = db_mfu if db_mfu is not None else section.get("max_failures_per_username")
    if max_fail_ip is None:
        db_mfi = _db_get("security.login_rate_limit_max_failures_per_ip")
        max_fail_ip = db_mfi if db_mfi is not None else section.get("max_failures_per_ip")
    if lockout_seconds is None:
        db_ls = _db_get("security.login_rate_limit_lockout_seconds")
        lockout_seconds = db_ls if db_ls is not None else section.get("lockout_seconds")

    return {
        "enabled": _coerce_bool(enabled, defaults["enabled"]),
        "window_seconds": _coerce_positive_int(window_seconds, defaults["window_seconds"]),
        "max_failures_per_username": _coerce_positive_int(
            max_fail_user, defaults["max_failures_per_username"]
        ),
        "max_failures_per_ip": _coerce_positive_int(max_fail_ip, defaults["max_failures_per_ip"]),
        "lockout_seconds": _coerce_positive_int(lockout_seconds, defaults["lockout_seconds"]),
    }


_PROVIDER_SLUGS = ("anthropic", "openai", "google", "openrouter", "openai_compatible")
_OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"
_GOOGLE_OPENAI_COMPAT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai"


def get_meeting_designer_settings() -> Dict[str, Any]:
    """Return Meeting Designer AI model settings.

    Priority: per-provider DB keys (new) → legacy single-key DB/config.yaml → disabled.
    The feature is enabled only when provider, api_key, and model are all non-empty.
    The return dict shape is always:
        {enabled, provider, api_key, endpoint_url, model, max_tokens, temperature}
    """
    config = load_config()
    section = config.get("meeting_designer_model") or {}

    # ── Shared numeric fields (same regardless of provider path) ──
    db_max_tokens = _db_get("ai.max_tokens")
    max_tokens = _coerce_positive_int(
        db_max_tokens if db_max_tokens is not None else section.get("max_tokens"),
        2048,
    )
    db_temp = _db_get("ai.temperature")
    temperature = _coerce_jitter_ratio(
        db_temp if db_temp is not None else section.get("temperature"),
        0.7,
    )

    # ── New per-provider path (used once admin saves from the new UI) ──
    active = _db_get("ai.active_provider")
    if active and active in _PROVIDER_SLUGS:
        api_key = str(_db_get(f"ai.{active}.api_key") or "")
        model = str(_db_get(f"ai.{active}.model") or "")

        if active == "openai_compatible":
            endpoint_url = str(_db_get("ai.openai_compatible.endpoint_url") or "")
        elif active == "openrouter":
            endpoint_url = _OPENROUTER_ENDPOINT
        elif active == "google":
            endpoint_url = _GOOGLE_OPENAI_COMPAT_ENDPOINT
        else:
            endpoint_url = ""

        return {
            "enabled": bool(api_key and model),
            "provider": active,
            "api_key": api_key,
            "endpoint_url": endpoint_url,
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    # ── Legacy single-key path (backward compat) ──
    def _str_field(yaml_key: str, db_key: str) -> str:
        db_val = _db_get(db_key)
        if db_val is not None:
            return str(db_val).strip()
        value = section.get(yaml_key)
        return str(value).strip() if value is not None else ""

    provider = _str_field("provider", "ai.provider").lower()
    api_key = _str_field("api_key", "ai.api_key")
    model = _str_field("model", "ai.model")
    endpoint_url = _str_field("endpoint_url", "ai.endpoint_url")

    return {
        "enabled": bool(provider and api_key and model),
        "provider": provider,
        "api_key": api_key,
        "endpoint_url": endpoint_url,
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }


def get_default_user_password() -> str:
    """Return the default password for newly created users.

    Priority: DB override → config.yaml → empty string.
    """
    db_val = _db_get("meetings.default_user_password")
    if db_val is not None:
        return str(db_val)
    config = load_config()
    return str(config.get("default_user_password", "") or "")


def get_default_meeting_settings() -> Dict[str, Any]:
    """Return default meeting creation settings with DB overrides applied."""
    config = load_config()
    section = config.get("default_meeting_settings") or {}

    max_participants = _coerce_positive_int(section.get("max_participants"), 100)
    recording_enabled = _coerce_bool(section.get("recording_enabled"), True)

    db_mp = _db_get("meetings.max_participants")
    if db_mp is not None:
        max_participants = _coerce_positive_int(db_mp, max_participants)
    db_rec = _db_get("meetings.recording_enabled")
    if db_rec is not None:
        recording_enabled = _coerce_bool(db_rec, recording_enabled)

    return {
        "max_participants": max_participants,
        "recording_enabled": recording_enabled,
    }


def get_session_expire_minutes() -> int:
    """Return the access token lifetime in minutes with DB override support."""
    config = load_config()
    section = config.get("auth") or {}
    base = _coerce_positive_int(section.get("access_token_expire_minutes"), 2880)

    db_val = _db_get("meetings.access_token_expire_minutes")
    if db_val is not None:
        return _coerce_positive_int(db_val, base)
    return base


def get_autosave_seconds() -> int:
    """Return the default autosave interval in seconds."""
    config = load_config()
    value = config.get("autosave_seconds", _DEFAULT_AUTOSAVE_SECONDS)
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        candidate = _DEFAULT_AUTOSAVE_SECONDS
    return candidate
