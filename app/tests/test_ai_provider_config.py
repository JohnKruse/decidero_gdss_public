import httpx

import app.services.ai_provider as ai_provider


def test_resolve_openai_url_uses_config_default(monkeypatch):
    monkeypatch.setattr(
        ai_provider,
        "get_ai_provider_defaults",
        lambda: {
            "anthropic": {"endpoint_url": "https://anthropic.example", "api_version": "2023-06-01"},
            "openai": {"endpoint_url": "https://openai.example/v1"},
            "openrouter": {"endpoint_url": "https://openrouter.example/v1"},
            "google": {
                "openai_compat_endpoint_url": "https://google.example/openai",
                "api_base_url": "https://google.example",
            },
        },
    )

    assert ai_provider._resolve_openai_url(None) == "https://openai.example/v1/chat/completions"


def test_resolve_openai_url_preserves_full_chat_completions_path():
    full = "https://azure.example/openai/deployments/x/chat/completions?api-version=2024-02-01"
    assert ai_provider._resolve_openai_url(full) == full


def test_build_anthropic_headers_uses_configured_api_version(monkeypatch):
    monkeypatch.setattr(
        ai_provider,
        "get_ai_provider_defaults",
        lambda: {
            "anthropic": {"endpoint_url": "https://anthropic.example", "api_version": "2025-01-01"},
            "openai": {"endpoint_url": "https://openai.example/v1"},
            "openrouter": {"endpoint_url": "https://openrouter.example/v1"},
            "google": {
                "openai_compat_endpoint_url": "https://google.example/openai",
                "api_base_url": "https://google.example",
            },
        },
    )

    headers = ai_provider._build_anthropic_headers("secret")

    assert headers["x-api-key"] == "secret"
    assert headers["anthropic-version"] == "2025-01-01"


def test_http_timeout_uses_loader_profile(monkeypatch):
    monkeypatch.setattr(
        ai_provider,
        "get_ai_http_settings",
        lambda: {
            "provider_client": {"connect": 1.5, "read": 2.5, "write": 3.5, "pool": 4.5},
            "settings_test_client": {"connect": 8.0, "read": 30.0, "write": 10.0, "pool": 5.0},
        },
    )

    timeout = ai_provider._http_timeout()

    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 1.5
    assert timeout.read == 2.5
    assert timeout.write == 3.5
    assert timeout.pool == 4.5
