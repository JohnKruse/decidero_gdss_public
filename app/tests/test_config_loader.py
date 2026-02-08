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
    assert settings["interval_seconds"] == 15
    assert settings["hidden_interval_seconds"] == 45
    assert settings["failure_backoff_seconds"] == 60


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
            ]
        ),
    )
    monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

    settings = loader.get_meeting_refresh_settings()

    assert settings["enabled"] is True
    assert settings["interval_seconds"] == 15
    assert settings["hidden_interval_seconds"] == 20
    assert settings["failure_backoff_seconds"] == 120
