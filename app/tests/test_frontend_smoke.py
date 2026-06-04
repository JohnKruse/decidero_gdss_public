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


def test_transfer_panel_uses_new_activity_target_only():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "transferTargetToolType" in js
    assert 'target_activity: { tool_type: targetTool }' in js
    assert "transferTargetMode" not in js
    assert "transferTargetExistingActivity" not in js
    assert "isExistingMode" not in js


def test_transfer_panel_html_has_no_mode_selector():
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert 'id="transferTargetToolType"' in html
    assert 'id="transferTargetMode"' not in html
    assert 'id="transferTargetExistingActivity"' not in html
    assert 'id="transferEligibilityHint"' not in html
    assert "Use existing activity" not in html


def test_agenda_panel_heading_renamed():
    """Roster Rodeo / Finish Fiesta — canonical user-brief task 1 check."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert "Meeting Agenda and Participant Roster" in html
    assert ">Agenda<" not in html


def test_meeting_settings_button_label():
    """Roster Rodeo / Finish Fiesta — canonical user-brief task 2 check."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert 'id="agendaAddActivityButton"' in html
    assert "Meeting Settings" in html
    assert 'id="agendaAddActivityButton">Settings<' not in html


def test_meeting_roster_button_present():
    """Lobster Teacup: UI/backend capability symmetry keeps roster controls tied to backend-derived meeting management authority."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert 'id="openParticipantAdminButton"' in html
    assert "Meeting Roster" in html
    assert "{% if can_manage_meeting %}" in html
    assert html.index("{% if can_manage_meeting %}") < html.index('id="openParticipantAdminButton"')
    assert "'facilitator' if can_manage_meeting else 'participant'" in html
    assert 'data-meeting-can-view="{{ \'true\' if meeting_capabilities.can_view else \'false\' }}"' in html
    assert 'data-meeting-can-manage="{{ \'true\' if meeting_capabilities.can_manage else \'false\' }}"' in html
    assert 'data-meeting-can-delete="{{ \'true\' if meeting_capabilities.can_delete else \'false\' }}"' in html
    assert 'data-meeting-is-facilitator="{{ \'true\' if meeting_capabilities.is_facilitator else \'false\' }}"' in html
    assert 'data-meeting-is-participant="{{ \'true\' if meeting_capabilities.is_participant else \'false\' }}"' in html
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "openParticipantAdminButton" in js
    assert "openParticipantAdminModal" in js
    assert 'setParticipantModalMode("meeting")' in js
    assert "viewer_capabilities" in js
    assert "resolveViewerCapabilities" in js
    assert "applyViewerCapabilities" in js
    assert "root.dataset.meetingCanManage" in js


def test_meeting_js_allows_admin_access_without_roster_membership():
    """Admins can manage meetings through can_view/can_manage even when they are not roster participants."""
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()

    assert "if (!state.canViewMeeting)" in js
    assert "if (!state.isParticipant) {\n                throw new Error(\"You are not registered for this meeting.\");" not in js


def test_activity_modal_simplified():
    """Roster Rodeo / Finish Fiesta — canonical user-brief task 4 check."""
    import re
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()

    # Removed affordances: no tab row, no Apply / IncludeAll / Reuse buttons, no dirty/lastCustomSelection state.
    assert "participant-modal-tabs" not in html
    assert "data-participant-modal-tab" not in html
    for token in ("activityParticipantApply", "activityParticipantIncludeAll", "activityParticipantReuse"):
        assert token not in html, f"{token} still present in meeting.html"
        assert token not in js, f"{token} still present in meeting.js"
    assert "activityParticipantState.dirty" not in js
    assert "activityParticipantState.lastCustomSelection" not in js

    # Kept affordances: the two Select-All buttons remain.
    assert "activityAvailableSelectAllButton" in html
    assert "activitySelectedSelectAllButton" in html

    # Auto-commit: both → / ← handlers must invoke applyActivityParticipantSelection inline.
    for fn_name in ("addActivityParticipantsFromAvailable", "removeActivityParticipantsFromSelected"):
        start = js.find(f"function {fn_name}")
        assert start != -1, f"{fn_name} not found in meeting.js"
        next_fn = js.find("\n        function ", start + 1)
        body = js[start : next_fn if next_fn != -1 else len(js)]
        assert "applyActivityParticipantSelection" in body, (
            f"{fn_name} does not auto-commit via applyActivityParticipantSelection"
        )

    # 409 collision rollback reads current_assignment from the Phase-3-enriched body.
    assert "current_assignment" in js, "meeting.js must reference the Phase-3 current_assignment field"
    assert re.search(r"status\s*===\s*409", js), "meeting.js must branch on HTTP 409 status"


def test_transfer_js_has_commit_button_label_helper():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "updateTransferCommitButtonText" in js
    assert "Create Next Activity" in js


def test_render_transfer_ideas_has_null_guard():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "transferState.items || []" in js


def test_transfer_js_commit_always_creates_new_activity():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "Select a next activity type." in js
    assert "target_activity: { tool_type: targetTool }" in js
    assert "activity_id: transferState.targetActivityId" not in js
    assert "Ideas transferred successfully." not in js
    assert "data.target_activity" in js


def test_meeting_js_redirects_on_unauth():
    with open("app/static/js/page_utils.js", "r", encoding="utf-8") as handle:
        contents = handle.read()
    assert "login_required" in contents


def test_dashboard_js_uses_viewer_capabilities_for_meeting_actions():
    with open("app/static/js/dashboard.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "meeting.viewer_capabilities" in js
    assert "capabilityRecord.can_manage === true" in js
    assert "Meeting Roster" in js
    assert "meeting.quick_actions?.roster" in js


def test_dashboard_create_meeting_choice_surface_copy():
    """Copper Compass: dashboard separates template, AI, manual, and import paths."""
    with open("app/templates/dashboard.html", "r", encoding="utf-8") as handle:
        template = handle.read()
    with open("app/static/css/dashboard.css", "r", encoding="utf-8") as handle:
        css = handle.read()

    assert "CREATE MEETING" in template
    assert "Start from Template" in template
    assert "Design with AI" in template
    assert "Design Yourself" in template
    assert "IMPORT MEETING" in template
    assert "navigateTo('/meeting/templates')" in template
    assert "navigateTo('/meeting/design')" in template
    assert "navigateTo('/meeting/create')" in template
    assert "meeting-create-menu__panel" in css


def test_meeting_page_supports_roster_deep_link():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert 'get("roster") === "1"' in js
    assert "openParticipantAdminModal();" in js


def test_meeting_page_exposes_save_as_template_action():
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()

    assert 'id="saveMeetingTemplateButton"' in html
    assert "Save as Template" in html
    assert "saveMeetingAsTemplate" in js
    assert "/api/meetings/${encodeURIComponent(context.meetingId)}/templates" in js
    assert "Saved template:" in js


def test_meeting_page_renders_agenda_items(authenticated_client: TestClient):
    """Meeting page should load and agenda API should return created items."""
    meeting_payload = {
        "title": "Frontend Agenda Render",
        "description": "Smoke test for agenda rendering",
        "scheduled_datetime": "2099-12-31T12:00:00Z",
        "agenda_items": ["First item", "Second item"],
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


def test_meeting_js_supports_orchestration_round_agenda_rows():
    """Loquacious Pelican: agenda_update accepts engine iteration metadata without new sockets."""
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    with open("app/static/css/meeting.css", "r", encoding="utf-8") as handle:
        css = handle.read()

    assert "function getOrchestrationInfo(item)" in js
    assert "function normalizeAgendaItem(item, previous = null)" in js
    assert "item?.config?._orchestration" in js
    assert "dataset.orchestrationRoundIndex" in js
    assert "agenda-item-round" in js
    assert "renderAgenda(payload);" in js
    assert ".agenda-item-round" in css


def test_meeting_page_has_facilitator_decision_review_surface():
    """Loquacious Pelican: meeting UI exposes the orchestration decision surface."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    with open("app/static/css/meeting.css", "r", encoding="utf-8") as handle:
        css = handle.read()

    assert "data-facilitator-decision-root" in html
    assert "facilitatorDecisionPrompt" in html
    assert "facilitatorDecisionAiReview" in html
    assert "facilitatorDecisionOptions" in html
    assert "loadFacilitatorDecisionDetail" in js
    assert "submitFacilitatorDecision" in js
    assert "facilitator_decision" in js
    assert "/orchestration/facilitator-decisions/" in js
    assert ".facilitator-decision-panel .decision-prompt" in css
    assert ".decision-options" in css


def test_remote_tunnel_script_has_retry_and_log_rotation():
    with open("start_remote_tunnel.sh", "r", encoding="utf-8") as handle:
        script = handle.read()
    assert "DECIDERO_TUNNEL_RETRY_MIN_SECONDS" in script
    assert "DECIDERO_TUNNEL_RETRY_MAX_SECONDS" in script
    assert "rotate_tunnel_logs" in script
    assert "cloudflared.log" in script


def test_meeting_page_includes_orchestration_advance_and_gate_hooks():
    """Deliberate Heron: the orchestration advance control and round-gate panel
    are present so a facilitator can drive the engine and answer cycle gates."""
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert "data-orchestration-advance" in html
    assert "orchestrationAdvanceButton" in html
    assert "facilitatorDecisionGate" in html
    assert "facilitatorDecisionGateRecommendation" in html

    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "advanceOrchestration" in js
    assert "renderRoundGate" in js
    # continue steers to the next round; conclude finishes the method.
    assert "Run another round." in js
    assert "Finish the method and stop here." in js


def test_meeting_templates_page_has_fork_and_tune_hooks():
    """Plainspoken Marmot: orchestration templates expose a fork-and-tune action."""
    with open("app/templates/meeting_templates.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert 'data-template-action="fork"' in html
    assert "FORK &amp; TUNE" in html
    assert "/fork" in html
    assert "What this method will do" in html
