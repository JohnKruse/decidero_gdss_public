from pathlib import Path

import app.config.loader as loader


def _write_config(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_ui_refresh_defaults_when_missing(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_ui_refresh_settings()

    assert settings["enabled"] is True
    assert settings["dashboard_interval_seconds"] == 20
    assert settings["admin_users_interval_seconds"] == 15
    assert settings["hidden_interval_seconds"] == 20
    assert settings["failure_backoff_seconds"] == 90


def test_ui_refresh_coercion(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "\n".join(
            [
                "ui_refresh:",
                "  enabled: \"false\"",
                "  dashboard_interval_seconds: \"0\"",
                "  admin_users_interval_seconds: \"25\"",
                "  hidden_interval_seconds: \"abc\"",
                "  failure_backoff_seconds: 10",
            ]
        ),
    )
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_ui_refresh_settings()

    assert settings["enabled"] is False
    assert settings["dashboard_interval_seconds"] == 20
    assert settings["admin_users_interval_seconds"] == 25
    assert settings["hidden_interval_seconds"] == 20
    assert settings["failure_backoff_seconds"] == 10


def test_meeting_refresh_defaults_when_missing(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_meeting_refresh_settings()

    assert settings["enabled"] is True
    assert settings["interval_seconds"] == 8
    assert settings["hidden_interval_seconds"] == 45
    assert settings["failure_backoff_seconds"] == 60
    assert settings["write_priority_backoff_seconds"] == 8
    assert settings["overload_backoff_seconds"] == 12
    assert settings["jitter_ratio"] == 0.2


def test_meeting_refresh_coercion(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "\n".join(
            [
                "meeting_refresh:",
                "  enabled: \"yes\"",
                "  interval_seconds: -5",
                "  hidden_interval_seconds: 20",
                "  failure_backoff_seconds: \"120\"",
                "  write_priority_backoff_seconds: \"0\"",
                "  overload_backoff_seconds: \"11\"",
                "  jitter_ratio: \"9\"",
            ]
        ),
    )
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_meeting_refresh_settings()

    assert settings["enabled"] is True
    assert settings["interval_seconds"] == 8
    assert settings["hidden_interval_seconds"] == 20
    assert settings["failure_backoff_seconds"] == 120
    assert settings["write_priority_backoff_seconds"] == 8
    assert settings["overload_backoff_seconds"] == 11
    assert settings["jitter_ratio"] == 1.0


def test_frontend_reliability_defaults_when_missing(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_frontend_reliability_settings()

    assert settings["write_default"]["retryable_statuses"] == [429, 502, 503, 504]
    assert settings["write_default"]["max_retries"] == 2
    assert settings["write_default"]["base_delay_ms"] == 350
    assert settings["write_default"]["max_delay_ms"] == 1800
    assert settings["write_default"]["jitter_ratio"] == 0.2
    assert settings["write_default"]["idempotency_header"] == "X-Idempotency-Key"
    assert settings["login"]["retryable_statuses"] == [429, 503]
    assert settings["registration"]["max_retries"] == 0
    assert "idempotency_header" not in settings["login"]


def test_frontend_reliability_coercion(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "\n".join(
            [
                "frontend_reliability:",
                "  write_default:",
                "    retryable_statuses: [429, \"500\", \"x\", 700]",
                "    max_retries: \"-2\"",
                "    base_delay_ms: \"0\"",
                "    max_delay_ms: \"20\"",
                "    jitter_ratio: \"-1\"",
                "    idempotency_header: \"  \"",
                "  login:",
                "    retryable_statuses: [429, \"abc\", 503]",
                "    max_retries: \"3\"",
                "    base_delay_ms: \"250\"",
                "    max_delay_ms: \"100\"",
                "    jitter_ratio: \"0.4\"",
                "    idempotency_header: \"X-Ignore-Me\"",
                "  registration:",
                "    max_retries: \"2\"",
            ]
        ),
    )
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_frontend_reliability_settings()

    assert settings["write_default"]["retryable_statuses"] == [429, 500]
    assert settings["write_default"]["max_retries"] == 2
    assert settings["write_default"]["base_delay_ms"] == 1
    assert settings["write_default"]["max_delay_ms"] == 20
    assert settings["write_default"]["jitter_ratio"] == 0.0
    assert settings["write_default"]["idempotency_header"] == "X-Idempotency-Key"
    assert settings["login"]["retryable_statuses"] == [429, 503]
    assert settings["login"]["max_retries"] == 3
    assert settings["login"]["base_delay_ms"] == 250
    assert settings["login"]["max_delay_ms"] == 250
    assert settings["login"]["jitter_ratio"] == 0.4
    assert "idempotency_header" not in settings["login"]
    assert settings["registration"]["max_retries"] == 2


def test_ai_provider_defaults_when_missing(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    defaults = loader.get_ai_provider_defaults()

    assert defaults["anthropic"]["endpoint_url"] == "https://api.anthropic.com"
    assert defaults["anthropic"]["api_version"] == "2023-06-01"
    assert defaults["openai"]["endpoint_url"] == "https://api.openai.com/v1"
    assert defaults["openrouter"]["endpoint_url"] == "https://openrouter.ai/api/v1"
    assert (
        defaults["google"]["openai_compat_endpoint_url"]
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert defaults["google"]["api_base_url"] == "https://generativelanguage.googleapis.com/v1beta"


def test_ai_provider_defaults_coercion(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "\n".join(
            [
                "ai:",
                "  provider_defaults:",
                "    anthropic:",
                "      endpoint_url: \"\"",
                "      api_version: \"2024-01-01\"",
                "    openai:",
                "      endpoint_url: \"https://example.openai.local/v1\"",
                "    openrouter:",
                "      endpoint_url: 1234",
                "    google:",
                "      openai_compat_endpoint_url: \"https://google.test/openai\"",
                "      api_base_url: \"https://google.test\"",
            ]
        ),
    )
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    defaults = loader.get_ai_provider_defaults()

    # Empty/invalid values fall back safely.
    assert defaults["anthropic"]["endpoint_url"] == "https://api.anthropic.com"
    assert defaults["anthropic"]["api_version"] == "2024-01-01"
    assert defaults["openai"]["endpoint_url"] == "https://example.openai.local/v1"
    assert defaults["openrouter"]["endpoint_url"] == "1234"
    assert defaults["google"]["openai_compat_endpoint_url"] == "https://google.test/openai"
    assert defaults["google"]["api_base_url"] == "https://google.test"


def test_ai_http_settings_defaults_when_missing(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_ai_http_settings()

    assert settings["provider_client"] == {
        "connect": 10.0,
        "read": 90.0,
        "write": 30.0,
        "pool": 5.0,
    }
    assert settings["settings_test_client"] == {
        "connect": 8.0,
        "read": 30.0,
        "write": 10.0,
        "pool": 5.0,
    }


def test_ai_http_settings_coercion(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "\n".join(
            [
                "ai:",
                "  http:",
                "    timeouts:",
                "      provider_client:",
                "        connect: \"11.5\"",
                "        read: 0",
                "        write: \"invalid\"",
                "        pool: \"7\"",
                "      settings_test_client:",
                "        connect: -1",
                "        read: 20",
                "        write: 6",
                "        pool: \"x\"",
            ]
        ),
    )
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_ai_http_settings()

    assert settings["provider_client"] == {
        "connect": 11.5,
        "read": 90.0,
        "write": 30.0,
        "pool": 7.0,
    }
    assert settings["settings_test_client"] == {
        "connect": 8.0,
        "read": 20.0,
        "write": 6.0,
        "pool": 5.0,
    }


def test_meeting_designer_prompt_templates_file_source(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "meeting_designer.yaml").write_text(
        "\n".join(
            [
                "system_prefix: |",
                "  Prefix with {activity_list}",
                "system_suffix: |",
                "  Suffix text",
                "generate_agenda: |",
                "  Generate text",
            ]
        ),
        encoding="utf-8",
    )
    _write_config(
        config_path,
        "\n".join(
            [
                "ai:",
                "  prompts:",
                "    meeting_designer:",
                "      source: file",
                "      file_path: prompts/meeting_designer.yaml",
            ]
        ),
    )
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    templates = loader.get_meeting_designer_prompt_templates()

    # YAML block scalars may or may not preserve the terminal newline depending
    # on file formatting/chomping, so assert semantic content.
    assert templates["system_prefix"].rstrip("\n") == "Prefix with {activity_list}"
    assert templates["system_suffix"].rstrip("\n") == "Suffix text"
    assert templates["generate_agenda"].rstrip("\n") == "Generate text"


def test_meeting_designer_prompt_templates_inline_source(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        "\n".join(
            [
                "ai:",
                "  prompts:",
                "    meeting_designer:",
                "      source: inline",
                "      system_prefix: \"Inline Prefix {activity_list}\"",
                "      system_suffix: \"Inline Suffix\"",
                "      generate_agenda: \"Inline Generate\"",
            ]
        ),
    )
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    templates = loader.get_meeting_designer_prompt_templates()

    assert templates["system_prefix"] == "Inline Prefix {activity_list}"
    assert templates["system_suffix"] == "Inline Suffix"
    assert templates["generate_agenda"] == "Inline Generate"
