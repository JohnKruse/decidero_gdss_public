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
import os
import signal
import time
from typing import Any, Dict, List, Optional

import re

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.auth import get_current_user
from app.config.loader import (
    get_ai_http_settings,
    get_restart_enabled,
    get_ai_provider_defaults,
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
    get_setting,
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
        # Active provider selection
        "ai.active_provider",
        # Per-provider API keys, models, and endpoints
        "ai.anthropic.api_key",
        "ai.anthropic.model",
        "ai.openai.api_key",
        "ai.openai.model",
        "ai.google.api_key",
        "ai.google.model",
        "ai.openrouter.api_key",
        "ai.openrouter.model",
        "ai.openai_compatible.api_key",
        "ai.openai_compatible.model",
        "ai.openai_compatible.endpoint_url",
        # Shared AI generation parameters
        "ai.max_tokens",
        "ai.temperature",
        # Legacy single-key settings (kept for backward compatibility)
        "ai.provider",
        "ai.api_key",
        "ai.endpoint_url",
        "ai.model",
        # Meetings
        "meetings.max_participants",
        "meetings.recording_enabled",
        "meetings.activity_participant_exclusivity",
        "meetings.default_user_password",
        "meetings.allow_guest_join",
        "meetings.access_token_expire_minutes",
        # Security
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


def _get_user_role(user_manager: UserManager, login: str) -> UserRole:
    user = user_manager.get_user_by_login(login)
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


_PROVIDER_SLUGS = ("anthropic", "openai", "google", "openrouter", "openai_compatible")


def _build_settings_response(is_admin: bool) -> Dict[str, Any]:
    """Assemble the full settings payload from the layered loader functions."""
    ai = get_meeting_designer_settings()
    meetings_defaults = get_default_meeting_settings()
    brainstorm_limits = get_brainstorming_limits()
    brainstorm_defaults = get_brainstorming_defaults()
    rate_limit = get_auth_login_rate_limit_settings()

    raw_password = get_default_user_password()
    password_set = bool(raw_password)
    password_preview = _mask_api_key(raw_password) if password_set else ""

    # Build per-provider card data
    providers_data: Dict[str, Any] = {}
    for slug in _PROVIDER_SLUGS:
        raw_key = str(get_setting(f"ai.{slug}.api_key") or "")
        model = str(get_setting(f"ai.{slug}.model") or "")
        entry: Dict[str, Any] = {
            "api_key_set": bool(raw_key),
            "api_key_preview": _mask_api_key(raw_key) if raw_key else "",
            "model": model,
        }
        if slug == "openai_compatible":
            entry["endpoint_url"] = str(get_setting("ai.openai_compatible.endpoint_url") or "")
        providers_data[slug] = entry

    return {
        "ai": {
            "active_provider": ai["provider"],
            "max_tokens": ai["max_tokens"],
            "temperature": ai["temperature"],
            "enabled": ai["enabled"],
            "providers": providers_data,
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
    api_key: str = Field(default="")   # accepts literal key or the sentinel "__stored__"
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
    api_key = _resolve_api_key(body.api_key.strip(), provider)
    model = body.model.strip()
    endpoint_url = (body.endpoint_url or "").strip()

    if not api_key:
        return TestAIResponse(success=False, error="No API key configured. Save an API key first.")

    _KNOWN_PROVIDERS = {"anthropic", "openai", "openai_compatible", "google", "openrouter"}
    if provider not in _KNOWN_PROVIDERS:
        return TestAIResponse(success=False, error=f"Unknown provider: {provider!r}")

    start = time.monotonic()
    try:
        if provider == "anthropic":
            result_text = await _test_anthropic(api_key, endpoint_url, model)
        elif provider == "google":
            result_text = await _test_google(api_key, model)
        elif provider == "openrouter":
            openrouter_base = _ai_defaults()["openrouter"]["endpoint_url"]
            result_text = await _test_openai(api_key, openrouter_base, model)
        else:
            # openai or openai_compatible
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


def _ai_defaults() -> Dict[str, Dict[str, str]]:
    return get_ai_provider_defaults()


def _test_timeout() -> httpx.Timeout:
    settings = get_ai_http_settings().get("settings_test_client", {})
    return httpx.Timeout(
        connect=float(settings.get("connect", 8.0)),
        read=float(settings.get("read", 30.0)),
        write=float(settings.get("write", 10.0)),
        pool=float(settings.get("pool", 5.0)),
    )


def _resolve_api_key(raw: str, provider: str = "") -> str:
    """Resolve the ``__stored__`` sentinel to the DB-stored API key.

    The browser sends ``'__stored__'`` when it wants the backend to use
    the key that is already saved, rather than sending the actual value.
    Looks up ``ai.<provider>.api_key`` first; falls back to the legacy
    ``ai.api_key`` key.  Returns an empty string if no key is stored.
    """
    if raw != "__stored__":
        return raw
    try:
        # Per-provider key takes priority
        if provider:
            val = get_setting(f"ai.{provider}.api_key")
            if val:
                return str(val)
        # Legacy single-key fallback
        val = get_setting("ai.api_key")
        return str(val) if val else ""
    except Exception:  # noqa: BLE001
        return ""


async def _test_anthropic(api_key: str, endpoint_url: str, model: str) -> str:
    defaults = _ai_defaults()
    base = (endpoint_url or defaults["anthropic"]["endpoint_url"]).rstrip("/")
    url = f"{base}/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": defaults["anthropic"]["api_version"],
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    async with httpx.AsyncClient(timeout=_test_timeout()) as client:
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
    defaults = _ai_defaults()
    if endpoint_url:
        base = endpoint_url.rstrip("/")
        if "chat/completions" in base:
            url = base
        else:
            url = f"{base}/chat/completions"
    else:
        url = f"{defaults['openai']['endpoint_url'].rstrip('/')}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        # Use max_completion_tokens — works for all current OpenAI models including
        # o1/o3/o4 reasoning models that reject the older max_tokens parameter.
        "max_completion_tokens": 8,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    async with httpx.AsyncClient(timeout=_test_timeout()) as client:
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


async def _test_google(api_key: str, model: str) -> str:
    """Test Google Gemini by making a minimal generateContent call."""
    base = _ai_defaults()["google"]["api_base_url"].rstrip("/")
    url = f"{base}/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": "Hi"}]}],
        "generationConfig": {"maxOutputTokens": 8},
    }
    async with httpx.AsyncClient(timeout=_test_timeout()) as client:
        try:
            resp = await client.post(url, json=body)
        except httpx.TimeoutException:
            raise _TestError("Connection timed out.")
        except httpx.RequestError as exc:
            raise _TestError(f"Network error: {exc}")

    if resp.status_code in {401, 403}:
        raise _TestError("Invalid API key — authentication failed.")
    if resp.status_code == 404:
        raise _TestError(f"Model {model!r} not found. Check the model ID.")
    if resp.status_code == 400:
        detail = resp.json().get("error", {}).get("message", resp.text[:200])
        raise _TestError(f"Bad request: {detail}")
    if resp.status_code != 200:
        raise _TestError(f"Google API returned HTTP {resp.status_code}: {resp.text[:200]}")
    return "ok"


# ── Model listing ─────────────────────────────────────────────────────────────

@router.get("/models", summary="Fetch available chat models from provider")
async def get_provider_models(
    provider: str,
    api_key: str = "",
    endpoint_url: str = "",
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Dict[str, Any]:
    """Return a filtered, ranked list of chat-capable models for the given provider.

    Pass ``api_key=__stored__`` to use the API key already saved in the database.
    Supported providers: ``anthropic``, ``openai``, ``google``, ``openrouter``.
    """
    _require_admin(user_manager, current_user)

    provider = provider.lower().strip()
    resolved_key = _resolve_api_key(api_key.strip(), provider)
    if not resolved_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key required. Save a key first or paste one in the field.",
        )

    try:
        if provider == "anthropic":
            models = await _fetch_anthropic_models(resolved_key, endpoint_url)
        elif provider == "openai":
            models = await _fetch_openai_models(resolved_key, endpoint_url)
        elif provider == "google":
            models = await _fetch_google_models(resolved_key)
        elif provider == "openrouter":
            models = await _fetch_openrouter_models(resolved_key)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model listing is not supported for provider {provider!r}. "
                       "For OpenAI-Compatible endpoints, enter the model ID manually.",
            )
    except _TestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Model fetch error for provider %r: %s", provider, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve models from provider. Check API key and try again.",
        )

    return {"provider": provider, "models": models}


# ── Per-provider model-fetch helpers ─────────────────────────────────────────

_TIER_SCORE: Dict[str, int] = {"opus": 3, "sonnet": 2, "haiku": 1}


async def _fetch_anthropic_models(api_key: str, endpoint_url: str = "") -> List[str]:
    defaults = _ai_defaults()
    base = (endpoint_url or defaults["anthropic"]["endpoint_url"]).rstrip("/")
    url = f"{base}/v1/models"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": defaults["anthropic"]["api_version"],
    }
    async with httpx.AsyncClient(timeout=_test_timeout()) as client:
        try:
            resp = await client.get(url, headers=headers)
        except httpx.RequestError as exc:
            raise _TestError(f"Network error: {exc}")

    if resp.status_code == 401:
        raise _TestError("Invalid API key.")
    if not resp.is_success:
        raise _TestError(f"Anthropic API returned HTTP {resp.status_code}.")

    raw = resp.json().get("data", [])
    model_ids = [m["id"] for m in raw if str(m.get("id", "")).startswith("claude-")]

    def _sort_key(mid: str) -> tuple:
        # Major version: claude-3, claude-4 …
        vm = re.search(r"claude-(\d+)", mid)
        major = int(vm.group(1)) if vm else 0
        # Minor version: claude-3-5, claude-4-5 …
        sm = re.search(r"claude-\d+-(\d+)", mid)
        minor = int(sm.group(1)) if sm else 0
        # Tier (opus > sonnet > haiku)
        low = mid.lower()
        tier = max((_TIER_SCORE.get(t, 0) for t in _TIER_SCORE if t in low), default=0)
        # Date suffix YYYYMMDD
        dm = re.search(r"(\d{8})", mid)
        date_val = int(dm.group(1)) if dm else 0
        return (major, minor, tier, date_val)

    model_ids.sort(key=_sort_key, reverse=True)
    return model_ids[:10]


async def _fetch_openai_models(api_key: str, endpoint_url: str = "") -> List[str]:
    defaults = _ai_defaults()
    base = (endpoint_url or defaults["openai"]["endpoint_url"]).rstrip("/")
    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=_test_timeout()) as client:
        try:
            resp = await client.get(url, headers=headers)
        except httpx.RequestError as exc:
            raise _TestError(f"Network error: {exc}")

    if resp.status_code == 401:
        raise _TestError("Invalid API key.")
    if not resp.is_success:
        raise _TestError(f"OpenAI API returned HTTP {resp.status_code}.")

    raw = resp.json().get("data", [])

    _CHAT_PREFIXES = ("gpt-4o", "gpt-4", "gpt-3.5-turbo", "o1", "o3", "o4")
    _EXCLUDE_TOKENS = (
        "dall-e", "whisper", "tts", "embedding", "moderation",
        "babbage", "davinci", "curie", "instruct", "search",
        "similarity", "transcribe", "realtime",
    )

    def _is_chat(mid: str) -> bool:
        low = mid.lower()
        if not any(low.startswith(p) for p in _CHAT_PREFIXES):
            return False
        return not any(x in low for x in _EXCLUDE_TOKENS)

    def _priority(mid: str) -> int:
        low = mid.lower()
        if low.startswith("o4"):          return 100
        if low.startswith("o3"):          return 90
        if low.startswith("o1"):          return 80
        if "gpt-4o" in low and "mini" not in low: return 70
        if "gpt-4o-mini" in low:         return 60
        if "gpt-4-turbo" in low:         return 50
        if low.startswith("gpt-4"):       return 40
        if "gpt-3.5-turbo" in low:       return 30
        return 10

    model_ids = [m["id"] for m in raw if _is_chat(m.get("id", ""))]
    model_ids.sort(key=_priority, reverse=True)
    return model_ids[:10]


async def _fetch_google_models(api_key: str) -> List[str]:
    base = _ai_defaults()["google"]["api_base_url"].rstrip("/")
    url = f"{base}/models?key={api_key}"
    async with httpx.AsyncClient(timeout=_test_timeout()) as client:
        try:
            resp = await client.get(url)
        except httpx.RequestError as exc:
            raise _TestError(f"Network error: {exc}")

    if resp.status_code in {401, 403}:
        raise _TestError("Invalid API key.")
    if not resp.is_success:
        raise _TestError(f"Google API returned HTTP {resp.status_code}.")

    raw = resp.json().get("models", [])

    def _is_chat(m: dict) -> bool:
        name = m.get("name", "")
        mid = name.replace("models/", "")
        if not mid.startswith("gemini"):
            return False
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            return False
        low = mid.lower()
        return not any(x in low for x in ("embed", "aqa", "retrieval", "grounding"))

    def _gen_sort(mid: str) -> tuple:
        low = mid.lower()
        # Generation (higher = newer)
        gen = 0
        if "2.5" in mid: gen = 4
        elif "2.0" in mid: gen = 3
        elif "1.5" in mid: gen = 2
        elif "1.0" in mid: gen = 1
        # Tier within generation
        tier = 0
        if "ultra" in low:   tier = 5
        elif "pro" in low and "thinking" in low: tier = 4
        elif "pro" in low:   tier = 3
        elif "flash" in low and "thinking" in low: tier = 2
        elif "flash" in low: tier = 1
        # Prefer stable over experimental/preview
        stable = 0 if any(x in low for x in ("exp", "preview")) else 1
        return (gen, tier, stable)

    model_ids = [m["name"].replace("models/", "") for m in raw if _is_chat(m)]
    model_ids.sort(key=_gen_sort, reverse=True)
    return model_ids[:10]


async def _fetch_openrouter_models(api_key: str) -> List[str]:
    base = _ai_defaults()["openrouter"]["endpoint_url"].rstrip("/")
    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=_test_timeout()) as client:
        try:
            resp = await client.get(url, headers=headers)
        except httpx.RequestError as exc:
            raise _TestError(f"Network error: {exc}")

    if resp.status_code == 401:
        raise _TestError("Invalid API key.")
    if not resp.is_success:
        raise _TestError(f"OpenRouter returned HTTP {resp.status_code}.")

    raw = resp.json().get("data", [])

    _EXCLUDE_TOKENS = ("embed", "tts", "dall-e", "transcribe", "rerank", "moderation")
    _PRIORITY_PROVIDERS = {
        "anthropic", "openai", "google", "mistralai",
        "meta-llama", "qwen", "deepseek", "x-ai",
    }

    def _is_chat(m: dict) -> bool:
        mid = m.get("id", "").lower()
        ctx = m.get("context_length") or 0
        if ctx < 8000:
            return False
        return not any(x in mid for x in _EXCLUDE_TOKENS)

    def _sort_key(m: dict) -> tuple:
        mid = m.get("id", "")
        provider = mid.split("/")[0] if "/" in mid else ""
        prio = 1 if provider in _PRIORITY_PROVIDERS else 0
        ctx = m.get("context_length") or 0
        return (prio, ctx)

    chat = [m for m in raw if _is_chat(m)]
    chat.sort(key=_sort_key, reverse=True)
    return [m["id"] for m in chat[:10]]


# ── System restart/shutdown ───────────────────────────────────────────────────

def _delayed_self_terminate() -> None:
    """Send SIGTERM to this process after a short delay so the HTTP response flushes."""
    time.sleep(1.0)
    os.killpg(os.getpgid(0), signal.SIGINT)


@router.post("/restart")
async def restart_server(
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Dict[str, Any]:
    """Terminate this process.  When supervised (DECIDERO_RESTART_ENABLED=true) the
    process supervisor restarts it automatically; otherwise it shuts down."""
    _require_admin(user_manager, user_id)
    background_tasks.add_task(_delayed_self_terminate)
    return {"status": "ok", "supervised": get_restart_enabled()}
