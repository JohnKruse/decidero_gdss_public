import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from app.tests.conftest import ADMIN_LOGIN_FOR_TEST


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to lint meeting.js syntax")
def test_meeting_js_has_valid_syntax():
    """Ensure meeting.js parses, so the meeting page can't ship with broken JS."""
    result = subprocess.run(
        ["node", "--check", "app/static/js/meeting.js"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_meeting_js_includes_voting_dot_rail():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        contents = handle.read()
    assert "voting-dot-rail" in contents


def test_meeting_page_includes_categorization_panel_hooks():
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert "data-categorization-root" in html
    assert "categorizationItemsList" in html

    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "categorization_update" in js
    assert "loadCategorizationState" in js


def test_meeting_js_redirects_on_unauth():
    with open("app/static/js/page_utils.js", "r", encoding="utf-8") as handle:
        contents = handle.read()
    assert "login_required" in contents


def test_meeting_page_renders_agenda_items(authenticated_client: TestClient):
    """Meeting page should load and agenda API should return created items."""
    meeting_payload = {
        "title": "Frontend Agenda Render",
        "description": "Smoke test for agenda rendering",
        "scheduled_datetime": "2099-12-31T12:00:00Z",
        "agenda_items": ["First item", "Second item"],
        "participant_contacts": [ADMIN_LOGIN_FOR_TEST],
    }
    create_res = authenticated_client.post("/api/meetings/", json=meeting_payload)
    assert create_res.status_code == 200, create_res.json()
    meeting_id = create_res.json()["id"]

    page = authenticated_client.get(f"/meeting/{meeting_id}")
    assert page.status_code == 200
    agenda_res = authenticated_client.get(f"/api/meetings/{meeting_id}/agenda")
    assert agenda_res.status_code == 200, agenda_res.json()
    agenda_items = agenda_res.json()
    titles = [row["title"] for row in agenda_items]
    assert "First item" in titles
    assert "Second item" in titles


def test_remote_tunnel_script_has_retry_and_log_rotation():
    with open("start_remote_tunnel.sh", "r", encoding="utf-8") as handle:
        script = handle.read()
    assert "DECIDERO_TUNNEL_RETRY_MIN_SECONDS" in script
    assert "DECIDERO_TUNNEL_RETRY_MAX_SECONDS" in script
    assert "rotate_tunnel_logs" in script
    assert "cloudflared.log" in script
