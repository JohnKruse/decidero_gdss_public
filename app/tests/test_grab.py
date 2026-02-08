import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
from jinja2 import Environment
import pytest

from grab_extension import GrabExtension


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _template_path(name: str) -> Path:
    return _project_root() / "app" / "templates" / name


def _line_number(path: Path, needle: str) -> int:
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in line:
            return idx
    raise AssertionError(f"Failed to find '{needle}' in {path}")


def test_grab_extension_renders_meta():
    env = Environment(extensions=[GrabExtension])
    template = env.from_string("{% grab id='hero' %}<p>Hello</p>{% endgrab %}")
    template.name = "inline.html"
    rendered = template.render()
    assert 'data-grab-id="hero"' in rendered
    script_match = re.search(
        r'<script type="application/json" data-grab-meta[^>]*>(.*?)</script>',
        rendered,
        flags=re.DOTALL,
    )
    assert script_match, "Meta script block missing"
    payload = json.loads(script_match.group(1))
    assert payload["template"] == "inline.html"
    assert payload["start_line"] == 1
    assert payload["id"] == "hero"


def test_grab_endpoint_returns_excerpt(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
):
    monkeypatch.setenv("GRAB_ENABLED", "true")
    template_name = "home.html"
    marker_line = _line_number(_template_path(template_name), '{% grab id="hero" %}')
    payload = {
        "items": [{"template": template_name, "start_line": marker_line}],
        "selection_bbox": {"left": 0, "top": 0, "width": 100, "height": 50},
        "url": "http://testserver/home",
        "html_sample": "<section class='hero'></section>",
    }
    response = client.post("/__grab", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["template"] == template_name
    assert "Collaborate with clarity" in data["items"][0]["snippet"]


def test_grab_endpoint_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
):
    monkeypatch.setenv("GRAB_ENABLED", "true")
    payload = {
        "items": [{"template": "../secrets.txt", "start_line": 1}],
        "selection_bbox": {},
    }
    response = client.post("/__grab", json=payload)
    assert response.status_code == 403
