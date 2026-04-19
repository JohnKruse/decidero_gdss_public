"""
Multi-provider AI client for the Meeting Designer.

Uses httpx directly (no vendor SDKs required). Supports:
  - anthropic         — Anthropic Messages API
  - openai            — OpenAI Chat Completions API (uses max_completion_tokens)
  - google            — Google Gemini via OpenAI-compatibility endpoint
  - openrouter        — OpenRouter via OpenAI-compatibility endpoint
  - openai_compatible — Any other OpenAI-compatible endpoint (Azure, Ollama, etc.)
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from app.config.loader import get_ai_http_settings, get_ai_provider_defaults

logger = logging.getLogger(__name__)


def _provider_defaults() -> Dict[str, Dict[str, str]]:
    return get_ai_provider_defaults()


def _http_timeout(profile: str = "provider_client") -> httpx.Timeout:
    settings = get_ai_http_settings().get(profile, {})
    return httpx.Timeout(
        connect=float(settings.get("connect", 10.0)),
        read=float(settings.get("read", 90.0)),
        write=float(settings.get("write", 30.0)),
        pool=float(settings.get("pool", 5.0)),
    )


class AIProviderError(Exception):
    """Raised when the AI provider returns an error or is unreachable."""


class AIProviderNotConfiguredError(AIProviderError):
    """Raised when the AI model is not configured in config.yaml."""


# ---------------------------------------------------------------------------
# Anthropic (Messages API)
# ---------------------------------------------------------------------------

def _build_anthropic_headers(api_key: str) -> Dict[str, str]:
    api_version = _provider_defaults()["anthropic"]["api_version"]
    return {
        "x-api-key": api_key,
        "anthropic-version": api_version,
        "content-type": "application/json",
        "accept": "text/event-stream",
    }


def _build_anthropic_body(
    model: str,
    system_prompt: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    stream: bool,
) -> Dict[str, Any]:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_prompt,
        "messages": messages,
        "stream": stream,
    }


async def _anthropic_stream(
    api_key: str,
    endpoint_url: str,
    model: str,
    system_prompt: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> AsyncGenerator[str, None]:
    fallback = _provider_defaults()["anthropic"]["endpoint_url"]
    base = (endpoint_url or fallback).rstrip("/")
    url = f"{base}/v1/messages"
    body = _build_anthropic_body(model, system_prompt, messages, max_tokens, temperature, stream=True)

    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        try:
            async with client.stream(
                "POST", url,
                headers=_build_anthropic_headers(api_key),
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise AIProviderError(
                        f"Anthropic API error {resp.status_code}: {error_body.decode()[:400]}"
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield text
        except httpx.TimeoutException as exc:
            raise AIProviderError(f"Anthropic API timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise AIProviderError(f"Anthropic API connection error: {exc}") from exc


async def _anthropic_complete(
    api_key: str,
    endpoint_url: str,
    model: str,
    system_prompt: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    fallback = _provider_defaults()["anthropic"]["endpoint_url"]
    base = (endpoint_url or fallback).rstrip("/")
    url = f"{base}/v1/messages"
    body = _build_anthropic_body(model, system_prompt, messages, max_tokens, temperature, stream=False)
    headers = _build_anthropic_headers(api_key)
    headers["accept"] = "application/json"

    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code != 200:
                raise AIProviderError(
                    f"Anthropic API error {resp.status_code}: {resp.text[:400]}"
                )
            data = resp.json()
            content = data.get("content", [])
            parts = [block.get("text", "") for block in content if block.get("type") == "text"]
            return "".join(parts)
        except httpx.TimeoutException as exc:
            raise AIProviderError(f"Anthropic API timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise AIProviderError(f"Anthropic API connection error: {exc}") from exc


# ---------------------------------------------------------------------------
# OpenAI / OpenAI-compatible (Chat Completions API)
# ---------------------------------------------------------------------------

def _build_openai_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }


def _build_openai_messages(
    system_prompt: str,
    messages: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Prepend the system prompt as the first message."""
    return [{"role": "system", "content": system_prompt}] + list(messages)


def _build_openai_body(
    model: str,
    system_prompt: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    stream: bool,
    use_completion_tokens: bool = False,
) -> Dict[str, Any]:
    # OpenAI reasoning models (o1, o3, o4-*) require max_completion_tokens and
    # reject max_tokens.  GPT-4o and earlier accept both; we use max_completion_tokens
    # for all OpenAI calls.  Other providers (OpenRouter, Google, custom) still
    # expect the older max_tokens parameter.
    token_key = "max_completion_tokens" if use_completion_tokens else "max_tokens"
    return {
        "model": model,
        "messages": _build_openai_messages(system_prompt, messages),
        token_key: max_tokens,
        "temperature": temperature,
        "stream": stream,
    }


def _resolve_openai_url(endpoint_url: Optional[str]) -> str:
    if endpoint_url:
        base = endpoint_url.rstrip("/")
        # Azure endpoints already contain the full path; detect by checking for
        # "chat/completions" already in the URL.
        if "chat/completions" in base:
            return base
        return f"{base}/chat/completions"
    fallback = _provider_defaults()["openai"]["endpoint_url"].rstrip("/")
    return f"{fallback}/chat/completions"


async def _openai_stream(
    api_key: str,
    endpoint_url: Optional[str],
    model: str,
    system_prompt: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    use_completion_tokens: bool = False,
) -> AsyncGenerator[str, None]:
    url = _resolve_openai_url(endpoint_url)
    body = _build_openai_body(
        model, system_prompt, messages, max_tokens, temperature,
        stream=True, use_completion_tokens=use_completion_tokens,
    )

    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        try:
            async with client.stream(
                "POST", url,
                headers=_build_openai_headers(api_key),
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise AIProviderError(
                        f"OpenAI-compatible API error {resp.status_code}: {error_body.decode()[:400]}"
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield text
        except httpx.TimeoutException as exc:
            raise AIProviderError(f"OpenAI API timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise AIProviderError(f"OpenAI API connection error: {exc}") from exc


async def _openai_complete(
    api_key: str,
    endpoint_url: Optional[str],
    model: str,
    system_prompt: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
    use_completion_tokens: bool = False,
) -> str:
    url = _resolve_openai_url(endpoint_url)
    body = _build_openai_body(
        model, system_prompt, messages, max_tokens, temperature,
        stream=False, use_completion_tokens=use_completion_tokens,
    )
    headers = _build_openai_headers(api_key)
    headers["Accept"] = "application/json"

    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code != 200:
                raise AIProviderError(
                    f"OpenAI-compatible API error {resp.status_code}: {resp.text[:400]}"
                )
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise AIProviderError("OpenAI API returned no choices in response")
            return choices[0].get("message", {}).get("content", "")
        except httpx.TimeoutException as exc:
            raise AIProviderError(f"OpenAI API timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise AIProviderError(f"OpenAI API connection error: {exc}") from exc


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def _is_anthropic(provider: str) -> bool:
    return provider.lower() == "anthropic"


def _is_openai_native(provider: str) -> bool:
    """True only for the official OpenAI provider (requires max_completion_tokens)."""
    return provider.lower() == "openai"


async def chat_stream(
    settings: Dict[str, Any],
    messages: List[Dict[str, str]],
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """Stream text chunks from the configured AI provider.

    Args:
        settings: Dict from get_meeting_designer_settings().
        messages: List of {"role": "user"|"assistant", "content": "..."} dicts.
        system_prompt: System/instruction prompt to prepend.

    Yields:
        Incremental text strings as they arrive from the model.

    Raises:
        AIProviderNotConfiguredError: If settings["enabled"] is False.
        AIProviderError: On API-level errors.
    """
    if not settings.get("enabled"):
        raise AIProviderNotConfiguredError(
            "AI Meeting Designer is not configured. "
            "Set meeting_designer_model in config.yaml."
        )

    provider = settings["provider"]
    api_key = settings["api_key"]
    endpoint_url = settings.get("endpoint_url") or None
    model = settings["model"]
    max_tokens = settings["max_tokens"]
    temperature = settings["temperature"]

    if _is_anthropic(provider):
        async for chunk in _anthropic_stream(
            api_key, endpoint_url or "", model, system_prompt, messages, max_tokens, temperature
        ):
            yield chunk
    else:
        # google, openrouter, openai_compatible all use the OpenAI-compat path.
        # For the native openai provider, use max_completion_tokens (required by o1/o3/o4 models).
        async for chunk in _openai_stream(
            api_key, endpoint_url, model, system_prompt, messages, max_tokens, temperature,
            use_completion_tokens=_is_openai_native(provider),
        ):
            yield chunk


async def chat_complete(
    settings: Dict[str, Any],
    messages: List[Dict[str, str]],
    system_prompt: str,
) -> str:
    """Return the full (non-streaming) response from the AI provider.

    Used for agenda generation where we need the complete JSON output.

    Raises:
        AIProviderNotConfiguredError: If settings["enabled"] is False.
        AIProviderError: On API-level errors.
    """
    if not settings.get("enabled"):
        raise AIProviderNotConfiguredError(
            "AI Meeting Designer is not configured. "
            "Set meeting_designer_model in config.yaml."
        )

    provider = settings["provider"]
    api_key = settings["api_key"]
    endpoint_url = settings.get("endpoint_url") or None
    model = settings["model"]
    max_tokens = settings["max_tokens"]
    temperature = settings["temperature"]

    if _is_anthropic(provider):
        return await _anthropic_complete(
            api_key, endpoint_url or "", model, system_prompt, messages, max_tokens, temperature
        )
    else:
        # google, openrouter, openai_compatible all use the OpenAI-compat path.
        # For the native openai provider, use max_completion_tokens (required by o1/o3/o4 models).
        return await _openai_complete(
            api_key, endpoint_url, model, system_prompt, messages, max_tokens, temperature,
            use_completion_tokens=_is_openai_native(provider),
        )
