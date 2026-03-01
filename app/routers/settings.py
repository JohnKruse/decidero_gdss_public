"""
Settings API — runtime-configurable application settings.

Routes
------
GET  /api/settings              Return current settings (API keys masked)
PUT  /api/settings              Save one or more settings (role-gated per section)
POST /api/settings/test-ai      Test AI provider connection without saving
DELETE /api/settings/{key}      Reset a single setting to its config.yaml default

Permission model
----------------
  Admin / Super-Admin   full read + write on ALL sections
  Facilitator           read on all sections; write on brainstorming.* only
  Participant           403 on all routes
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.auth import get_current_user
from app.config.loader import (
    get_auth_login_rate_limit_settings,
    get_brainstorming_defaults,
    get_brainstorming_limits,
    get_default_meeting_settings,
    get_guest_join_enabled,
    get_meeting_designer_settings,
    get_session_expire_minutes,
    get_activity_participant_exclusivity,
    get_default_user_password,
)
from app.config.settings_store import (
    SENSITIVE_KEYS,
    delete_settings_bulk,
    has_setting,
    save_settings_bulk,
    delete_setting,
)
from app.data.user_manager import UserManager, get_user_manager
from app.models.user import UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# ── Role helpers ──────────────────────────────────────────────────────────────

_ADMIN_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}
_FACILITATOR_ROLES = {UserRole.FACILITATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN}

# Settings keys that only admins may write
_ADMIN_ONLY_WRITE_KEYS: frozenset[str] = frozenset(
    {
        "ai.provider",
        "ai.api_key",
        "ai.endpoint_url",
        "ai.model",
        "ai.max_tokens",
        "ai.temperature",
        "meetings.max_participants",
        "meetings.recording_enabled",
        "meetings.activity_participant_exclusivity",
        "meetings.default_user_password",
        "meetings.allow_guest_join",
        "meetings.access_token_expire_minutes",
        "security.login_rate_limit_enabled",
        "security.login_rate_limit_window_seconds",
        "security.login_rate_limit_max_failures_per_username",
        "security.login_rate_limit_max_failures_per_ip",
        "security.login_rate_limit_lockout_seconds",
    }
)

# Settings keys that facilitators may also write
_FACILITATOR_WRITE_KEYS: frozenset[str] = frozenset(
    {
        "brainstorming.idea_character_limit",
        "brainstorming.max_ideas_per_user",
        "brainstorming.default_maintain_anonymity",
        "brainstorming.default_allow_subcomments",
        "brainstorming.default_auto_jump_new_ideas",
    }
)

_ALL_KNOWN_KEYS = _ADMIN_ONLY_WRITE_KEYS | _FACILITATOR_WRITE_KEYS


def _get_user_role(user_manager: UserManager, user_id: str) -> UserRole:
    user = user_manager.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return UserRole(user.role)


def _require_facilitator_or_admin(user_manager: UserManager, user_id: str) -> UserRole:
    role = _get_user_role(user_manager, user_id)
    if role not in _FACILITATOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Settings require Facilitator or Administrator access.",
        )
    return role


def _require_admin(user_manager: UserManager, user_id: str) -> UserRole:
    role = _get_user_role(user_manager, user_id)
    if role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This setting requires Administrator access.",
        )
    return role


# ── Response helpers ──────────────────────────────────────────────────────────

def _mask_api_key(key: str) -> str:
    """Return a safely-masked preview of an API key string."""
    if not key:
        return ""
    visible = key[:6]
    return visible + "●" * min(10, max(4, len(key) - 6))


def _build_settings_response(is_admin: bool) -> Dict[str, Any]:
    """Assemble the full settings payload from the layered loader functions."""
    ai = get_meeting_designer_settings()
    meetings_defaults = get_default_meeting_settings()
    brainstorm_limits = get_brainstorming_limits()
    brainstorm_defaults = get_brainstorming_defaults()
    rate_limit = get_auth_login_rate_limit_settings()

    raw_api_key = ai.get("api_key", "")
    api_key_set = bool(raw_api_key)
    api_key_preview = _mask_api_key(raw_api_key) if api_key_set else ""

    raw_password = get_default_user_password()
    password_set = bool(raw_password)
    password_preview = _mask_api_key(raw_password) if password_set else ""

    return {
        "ai": {
            "provider": ai["provider"],
            "api_key_set": api_key_set,
            "api_key_preview": api_key_preview,
            "endpoint_url": ai["endpoint_url"],
            "model": ai["model"],
            "max_tokens": ai["max_tokens"],
            "temperature": ai["temperature"],
            "enabled": ai["enabled"],
        },
        "meetings": {
            "max_participants": meetings_defaults["max_participants"],
            "recording_enabled": meetings_defaults["recording_enabled"],
            "activity_participant_exclusivity": get_activity_participant_exclusivity(),
            "default_user_password_set": password_set,
            "default_user_password_preview": password_preview,
            "allow_guest_join": get_guest_join_enabled(),
            "access_token_expire_minutes": get_session_expire_minutes(),
        },
        "security": {
            "login_rate_limit_enabled": rate_limit["enabled"],
            "login_rate_limit_window_seconds": rate_limit["window_seconds"],
            "login_rate_limit_max_failures_per_username": rate_limit["max_failures_per_username"],
            "login_rate_limit_max_failures_per_ip": rate_limit["max_failures_per_ip"],
            "login_rate_limit_lockout_seconds": rate_limit["lockout_seconds"],
        },
        "brainstorming": {
            "idea_character_limit": brainstorm_limits["idea_character_limit"],
            "max_ideas_per_user": brainstorm_limits["max_ideas_per_user"],
            "default_maintain_anonymity": brainstorm_defaults["allow_anonymous"],
            "default_allow_subcomments": brainstorm_defaults["allow_subcomments"],
            "default_auto_jump_new_ideas": brainstorm_defaults["auto_jump_new_ideas"],
        },
        # Tell the UI which keys are overridden in the DB vs. using config.yaml defaults
        "db_overrides": _get_override_flags(),
        "is_admin": is_admin,
    }


def _get_override_flags() -> Dict[str, bool]:
    """Return a map of {key: True} for every key that has a DB override."""
    return {k: has_setting(k) for k in _ALL_KNOWN_KEYS}


# ── Pydantic models ───────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    """A batch of setting key/value pairs to save.

    Clients may send any subset of the known keys.  Unknown keys are rejected.
    """
    settings: Dict[str, Any] = Field(..., description="Map of setting key → new value")


class TestAIRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=1)
    endpoint_url: str = Field(default="")
    model: str = Field(..., min_length=1)


class TestAIResponse(BaseModel):
    success: bool
    latency_ms: Optional[int] = None
    model_confirmed: Optional[str] = None
    error: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", summary="Get current settings")
async def get_settings(
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Dict[str, Any]:
    """Return all runtime settings.  API keys/passwords are masked."""
    role = _require_facilitator_or_admin(user_manager, current_user)
    is_admin = role in _ADMIN_ROLES
    return _build_settings_response(is_admin)


@router.put("", summary="Save settings")
async def save_settings(
    body: SettingsUpdate,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Dict[str, Any]:
    """Upsert one or more settings.

    - Admin/Super-Admin may write any key.
    - Facilitator may only write ``brainstorming.*`` keys.
    - Unknown keys are rejected with 422.
    - Empty-string values for sensitive keys (api_key, password) are treated
      as "clear this override" and will delete the DB row.
    """
    role = _require_facilitator_or_admin(user_manager, current_user)
    is_admin = role in _ADMIN_ROLES

    updates = body.settings
    if not updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No settings provided.")

    # Validate keys
    unknown = set(updates.keys()) - _ALL_KNOWN_KEYS
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown setting key(s): {sorted(unknown)}",
        )

    # Check role permissions
    if not is_admin:
        admin_only_attempted = set(updates.keys()) & _ADMIN_ONLY_WRITE_KEYS
        if admin_only_attempted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Administrator access required to modify: {sorted(admin_only_attempted)}",
            )

    # Separate "clear" operations (empty string for sensitive keys) from saves
    to_save: Dict[str, Any] = {}
    to_delete: List[str] = []

    for key, value in updates.items():
        if key in SENSITIVE_KEYS and value == "":
            # Empty string → delete override (revert to config.yaml)
            to_delete.append(key)
        else:
            to_save[key] = value

    if to_delete:
        delete_settings_bulk(to_delete)
    if to_save:
        save_settings_bulk(to_save, current_user)

    logger.info(
        "Settings saved by %s (role=%s): saved=%s deleted=%s",
        current_user,
        role,
        list(to_save.keys()),
        to_delete,
    )

    return _build_settings_response(is_admin)


@router.delete("/{key}", summary="Reset a setting to its default")
async def reset_setting(
    key: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Dict[str, Any]:
    """Delete a DB override so the setting reverts to its config.yaml / hardcoded default."""
    role = _require_facilitator_or_admin(user_manager, current_user)
    is_admin = role in _ADMIN_ROLES

    if key not in _ALL_KNOWN_KEYS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown setting key: {key!r}",
        )
    if not is_admin and key in _ADMIN_ONLY_WRITE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required to reset this setting.",
        )

    delete_setting(key)
    logger.info("Setting %r reset to default by %s", key, current_user)
    return _build_settings_response(is_admin)


@router.post("/test-ai", response_model=TestAIResponse, summary="Test AI provider connection")
async def test_ai_connection(
    body: TestAIRequest,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> TestAIResponse:
    """Make a minimal live call to verify provider credentials.  Does NOT save anything."""
    _require_admin(user_manager, current_user)

    provider = body.provider.lower().strip()
    api_key = body.api_key.strip()
    model = body.model.strip()
    endpoint_url = (body.endpoint_url or "").strip()

    if provider not in {"anthropic", "openai", "openai_compatible"}:
        return TestAIResponse(success=False, error=f"Unknown provider: {provider!r}")

    start = time.monotonic()
    try:
        if provider == "anthropic":
            result_text = await _test_anthropic(api_key, endpoint_url, model)
        else:
            result_text = await _test_openai(api_key, endpoint_url, model)
        latency_ms = int((time.monotonic() - start) * 1000)
        return TestAIResponse(
            success=True,
            latency_ms=latency_ms,
            model_confirmed=model,
        )
    except _TestError as exc:
        return TestAIResponse(success=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI test-connection unexpected error: %s", exc)
        return TestAIResponse(success=False, error="Unexpected error. Check server logs.")


# ── AI connection test helpers ────────────────────────────────────────────────

class _TestError(Exception):
    """Human-readable error for the test-AI endpoint."""


_TEST_TIMEOUT = httpx.Timeout(connect=8.0, read=30.0, write=10.0, pool=5.0)
_ANTHROPIC_API_VERSION = "2023-06-01"
_DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"
_DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"


async def _test_anthropic(api_key: str, endpoint_url: str, model: str) -> str:
    base = (endpoint_url or _DEFAULT_ANTHROPIC_BASE).rstrip("/")
    url = f"{base}/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    async with httpx.AsyncClient(timeout=_TEST_TIMEOUT) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            raise _TestError("Connection timed out. Check endpoint URL and network.")
        except httpx.RequestError as exc:
            raise _TestError(f"Network error: {exc}")

    if resp.status_code == 401:
        raise _TestError("Invalid API key — authentication failed.")
    if resp.status_code == 400:
        # Model not found typically returns 400 with error detail
        detail = resp.json().get("error", {}).get("message", resp.text[:200])
        raise _TestError(f"Bad request: {detail}")
    if resp.status_code == 404:
        raise _TestError(f"Model {model!r} not found for this provider.")
    if resp.status_code != 200:
        raise _TestError(f"Provider returned HTTP {resp.status_code}: {resp.text[:200]}")
    return "ok"


async def _test_openai(api_key: str, endpoint_url: str, model: str) -> str:
    if endpoint_url:
        base = endpoint_url.rstrip("/")
        if "chat/completions" in base:
            url = base
        else:
            url = f"{base}/chat/completions"
    else:
        url = f"{_DEFAULT_OPENAI_BASE}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    async with httpx.AsyncClient(timeout=_TEST_TIMEOUT) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            raise _TestError("Connection timed out. Check endpoint URL and network.")
        except httpx.RequestError as exc:
            raise _TestError(f"Network error: {exc}")

    if resp.status_code == 401:
        raise _TestError("Invalid API key — authentication failed.")
    if resp.status_code == 404:
        raise _TestError(f"Model {model!r} not found at this endpoint.")
    if resp.status_code not in {200, 201}:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        raise _TestError(f"Provider returned HTTP {resp.status_code}: {detail}")
    return "ok"
