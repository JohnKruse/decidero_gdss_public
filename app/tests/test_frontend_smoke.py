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


def test_meeting_page_includes_report_panel_hooks():
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert "data-report-root" in html
    assert "reportDownloadJson" in html
    assert "reportPreview" in html

    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert 'toolType === "report"' in js
    assert "loadReportPreview" in js
    assert "/report/preview" in js
    assert "reportDownloadUrl" in js

    with open("app/static/css/meeting.css", "r", encoding="utf-8") as handle:
        css = handle.read()
    assert ".report-preview" in css
    assert ".report-actions" in css


def test_meeting_page_includes_outlier_justification_panel_hooks():
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    assert "data-justification-root" in html
    assert "justificationQueue" in html
    assert "Comment on Delphi Feedback" in html
    assert "Nothing needs your comment this round." in html

    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert 'toolType === "outlier_justification"' in js
    assert "loadJustificationState" in js
    assert "justificationUsesSelectedItems" in js
    assert "commented on" in js
    assert "justification_update" in js


def test_brainstorming_comment_surface_hooks():
    """Brainstorming can render as a Delphi comment surface via config: ordered by
    group rank, agreement bands, subdued non-eligible items, comment-only."""
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    with open("app/static/css/meeting.css", "r", encoding="utf-8") as handle:
        css = handle.read()
    assert "group_rank" in js
    assert "comment_scope" in js
    assert "allow_new_ideas" in js
    assert "brainstorming-agreement" in js
    assert "brainstorming-idea-subdued" in js
    assert "brainstorming-idea-subdued" in css
    assert 'Object.prototype.hasOwnProperty.call(meta, "commentable")' in js
    assert 'container.dataset.commentSurface = "true"' in js
    assert 'row.dataset.commentSurface === "true"' in js
    assert "mergeSnapshotAgenda" in js


def test_rank_order_prior_feedback_uses_agreement_badges():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    with open("app/static/css/meeting.css", "r", encoding="utf-8") as handle:
        css = handle.read()

    assert "rankOrderAgreementBand" in js
    assert "rankOrderAgreementLabel" in js
    assert "rank-order-agreement-badge" in js
    assert 'fb.dataset.band = band' in js
    assert "Last round: group median rank" in js
    assert '.rank-order-prior-feedback[data-band="green"]' in css
    assert '.rank-order-prior-feedback[data-band="yellow"]' in css
    assert '.rank-order-prior-feedback[data-band="red"]' in css


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


def test_meeting_js_handles_archive_notice_without_auto_redirect():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert 'case "meeting_archived"' in js
    assert "showArchivedMeetingNotice" in js
    assert "Return to Dashboard" in js
    archive_handler = js.split('case "meeting_archived":', 1)[1].split('case "agenda_update":', 1)[0]
    assert "window.location.href" not in archive_handler
    assert "window.location.assign" not in archive_handler


def test_facilitator_decision_panel_only_enterable_while_active():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert 'const isFacilitatorDecision = toolType === "facilitator_decision"' in js
    assert "canEnter: isFacilitatorDecision ? Boolean(isActive) : true" in js


def test_orchestrated_controls_require_stop_before_advance():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "function updateOrchestrationAdvanceAvailability()" in js
    assert "function refreshOrchestrationAdvancePreview()" in js
    assert "/orchestration/preview" in js
    assert "Stop ${label} before advancing to the next step." in js
    assert "Run and stop ${blockedTitle} before advancing." in js
    assert "Next likely step:" in js
    assert "function isPastOrchestratedActivity(item)" in js
    assert "function isLockedOrchestratedStep(item)" in js
    assert "This orchestrated step is in the past and cannot be restarted." in js
    assert "hasOpenOtherActivity" in js
    assert "selectedIsPastOrchestrated" in js
    assert "gateReportSignature" in js


def test_orchestrated_agenda_hides_transfer_controls():
    with open("app/templates/meeting.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()

    assert "data-meeting-is-orchestration" in html
    assert "function isOrchestrationMeeting()" in js
    assert "if (!isOrchestrationMeeting()) {" in js
    assert "transferState.active && state.isFacilitator && !isOrchestrationMeeting()" in js
    assert "if (!transfer.root || !activity || isOrchestrationMeeting())" in js


def test_brainstorming_selected_comment_surface_has_specific_empty_state():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()

    assert "const selectedCommentSurface =" in js
    assert "No selected ideas are open for comment in this step yet." in js


def test_facilitator_feedback_decision_panel_stays_open_while_editing():
    with open("app/static/js/meeting.js", "r", encoding="utf-8") as handle:
        js = handle.read()
    assert "function hasStickyFacilitatorDecisionPanel()" in js
    assert "const keepDecisionVisible = hasStickyFacilitatorDecisionPanel()" in js
    assert "userEditingFeedbackCount" in js
    assert "input.addEventListener(\"focus\"" in js
    assert "if (!facilitatorDecisionState.userEditingFeedbackCount)" in js


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
    with open("app/static/css/meeting.css", "r", encoding="utf-8") as handle:
        css = handle.read()
    assert "advanceOrchestration" in js
    assert "renderRoundGate" in js
    assert "facilitatorFeedbackCommentCount" in js
    assert "selected_comment_count" in js
    assert "decision-feedback-selector" in css
    # continue steers to the next round; conclude finishes the method.
    assert "Run another round." in js
    assert "Finish the method and stop here." in js
    # Cross-round comments privately flag the viewer's own comment.
    assert "prior-rationale-mine-badge" in js
    assert "Your comment" in js
    assert "prior-rationale-mine" in css
    # Delphi rank-order panel shows "Round N of M" progression.
    assert "delphi_round" in js
    assert "Round ${round.round_number} of ${round.max_rounds}" in js
    # Prior feedback shows median rank, numeric spread, and the viewer's own rank.
    assert "Group median rank" in js
    assert "spread" in js
    assert "your_prior_rank" in js
    assert "You ranked it" in js


def test_meeting_templates_page_uses_horizontal_cards_without_fork_tune():
    """Meeting templates are browsed as horizontal cards; fork/tune stays hidden."""
    with open("app/templates/meeting_templates.html", "r", encoding="utf-8") as handle:
        html = handle.read()
    with open("app/static/css/dashboard.css", "r", encoding="utf-8") as handle:
        css = handle.read()
    assert 'data-template-action="fork"' not in html
    assert "FORK &amp; TUNE" not in html
    assert 'id="templateForkPanel"' not in html
    assert "grid-template-columns: minmax(0, 1fr) minmax(180px, auto);" in css
