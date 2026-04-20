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


def test_transfer_panel_has_target_mode_elements():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "transferTargetMode" in js
    assert "transferTargetExistingActivity" in js
    assert 'targetMode: "new"' in js
    assert "targetActivityId: null" in js


def test_transfer_panel_html_has_mode_selector():
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert 'id="transferTargetMode"' in html
    assert 'id="transferTargetExistingActivity"' in html
    assert 'id="transferEligibilityHint"' in html
    assert 'value="new"' in html
    assert 'value="existing"' in html


def test_agenda_panel_heading_text():
    """Phase 1 / Placard Parade — guard the renamed Agenda panel heading."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert "Meeting Agenda and Participant Roster" in html
    assert ">Agenda<" not in html


def test_agenda_settings_button_label():
    """Phase 1 / Placard Parade — guard the renamed Meeting Settings button."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert 'id="agendaAddActivityButton"' in html
    assert "Meeting Settings" in html
    assert 'id="agendaAddActivityButton">Settings<' not in html


def test_agenda_meeting_roster_button_present():
    """Phase 2 / Doorbell Disco — guard the new Meeting Roster entry point in the Agenda panel."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert 'id="openParticipantAdminButton"' in html
    assert "Meeting Roster" in html
    assert html.index("current_user.role in ['admin', 'super_admin', 'facilitator']") < html.index(
        'id="openParticipantAdminButton"'
    )


def test_meeting_roster_button_listener_wired():
    """Phase 2 / Doorbell Disco — guard the pre-existing JS wiring the new button relies on."""
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "openParticipantAdminButton" in js
    assert "openParticipantAdminModal" in js
    assert 'setParticipantModalMode("meeting")' in js


def test_activity_modal_tabs_removed():
    """Phase 4 / Modal Mutiny — the tab row is gone; there is no secondary switcher inside the participant modal."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert "participant-modal-tabs" not in html
    assert "data-participant-modal-tab" not in html


def test_activity_modal_action_buttons_removed():
    """Phase 4 / Modal Mutiny — Include Everyone / Apply Selection / Reuse Last are gone from both template and JS."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    for token in ("activityParticipantIncludeAll", "activityParticipantApply", "activityParticipantReuse"):
        assert token not in html, f"{token} still present in meeting.html"
        assert token not in js, f"{token} still present in meeting.js"


def test_no_dead_apply_button_references():
    """Phase 4 / Modal Mutiny — structural proof of Step 4 cleanup: removed affordances leave no source trace."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    for token in ("activityParticipantApply", "activityParticipantIncludeAll", "activityParticipantReuse"):
        assert token not in html, f"{token} still present in meeting.html"
        assert token not in js, f"{token} still present in meeting.js"
    assert "activityParticipantState.dirty" not in js
    assert "activityParticipantState.lastCustomSelection" not in js


def test_collision_rollback_reads_current_assignment():
    """Phase 4 / Modal Mutiny — structural pin: 409 handler parses current_assignment from the server body.

    Behavioral coverage would require a JS test runner this project does not have; deferred to Phase 5.
    """
    import re
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "current_assignment" in js, "meeting.js must reference the Phase-3 current_assignment field"
    assert re.search(r"status\s*===\s*409", js), "meeting.js must branch on HTTP 409 status"


def test_activity_move_handlers_auto_commit():
    """Phase 4 / Modal Mutiny — → and ← handlers must call applyActivityParticipantSelection inline (auto-commit)."""
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    for fn_name in ("addActivityParticipantsFromAvailable", "removeActivityParticipantsFromSelected"):
        start = js.find(f"function {fn_name}")
        assert start != -1, f"{fn_name} not found in meeting.js"
        next_fn = js.find("\n        function ", start + 1)
        body = js[start : next_fn if next_fn != -1 else len(js)]
        assert "applyActivityParticipantSelection" in body, (
            f"{fn_name} does not auto-commit via applyActivityParticipantSelection"
        )


def test_transfer_css_has_eligibility_hint_style():
    with open("app/static/css/meeting.css", "r", encoding="utf-8") as handle:
        css = handle.read()
    assert "transfer-eligibility-hint" in css


def test_transfer_js_has_mode_change_handler():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "onTransferModeChange" in js
    assert "buildTransferExistingActivityOptions" in js
    assert "updateTransferCommitButtonText" in js


def test_render_transfer_ideas_has_null_guard():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "transferState.items || []" in js


def test_transfer_js_has_existing_activity_builder():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "buildTransferExistingActivityOptions" in js
    assert "transfer_target_eligible" in js
    assert "Already started" in js
    assert "Has participant data" in js
    assert "updateTransferCommitButtonText" in js


def test_transfer_js_commit_handles_both_modes():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "isExistingMode" in js
    assert "Select an existing activity to transfer into." in js
    assert "activity_id: transferState.targetActivityId" in js
    assert "Ideas transferred successfully." in js
    assert "data.target_activity" in js


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
