from fastapi.testclient import TestClient
from app.tests.conftest import (
    ADMIN_EMAIL_FOR_TEST,
    ADMIN_PASSWORD_FOR_TEST,
    ADMIN_LOGIN_FOR_TEST,
)  # Import admin credentials if needed for login setup
from app.data.user_manager import UserManager
from app.models.user import UserRole
from app.utils.security import get_password_hash


# Tests for GET requests to page routes
def test_get_login_page(client: TestClient):
    response = client.get("/login")
    assert response.status_code == 200
    assert "DECIDERO GDSS - Login" in response.text


def test_get_register_page(client: TestClient):
    response = client.get("/register")
    assert response.status_code == 200
    assert "Register" in response.text  # Check for title or key content


def test_get_dashboard_unauthenticated(client: TestClient):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 307  # Should redirect to /login
    assert (
        response.headers["location"]
        == "/login?message=login_required&next=%2Fdashboard"
    )


def test_get_dashboard_authenticated(client: TestClient, user_manager_with_admin):
    # Log in the admin user to get a session cookie
    login_data = {"username": ADMIN_LOGIN_FOR_TEST, "password": ADMIN_PASSWORD_FOR_TEST}
    response = client.post("/api/auth/token", json=login_data)
    assert response.status_code == 200
    assert "access_token" in client.cookies

    # Access dashboard
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "DECIDERO GDSS - Dashboard" in response.text
    assert (
        f"Welcome, {user_manager_with_admin.get_user_by_email(ADMIN_EMAIL_FOR_TEST).first_name}"
        in response.text
    )


def test_get_profile_page_unauthenticated(client: TestClient):
    response = client.get("/profile", follow_redirects=False)
    assert response.status_code == 307
    assert (
        response.headers["location"]
        == "/login?message=login_required&next=%2Fprofile"
    )


def test_get_profile_page_authenticated(client: TestClient, user_manager_with_admin):
    # Log in
    login_data = {"username": ADMIN_LOGIN_FOR_TEST, "password": ADMIN_PASSWORD_FOR_TEST}
    response = client.post("/api/auth/token", json=login_data)
    assert response.status_code == 200

    # Access profile
    response = client.get("/profile")
    assert response.status_code == 200
    assert "My Profile - Decidero" in response.text


def test_create_meeting_page_includes_participant_avatar_rendering(
    client: TestClient, user_manager_with_admin
):
    login_data = {"username": ADMIN_LOGIN_FOR_TEST, "password": ADMIN_PASSWORD_FOR_TEST}
    response = client.post("/api/auth/token", json=login_data)
    assert response.status_code == 200

    page = client.get("/meeting/create")
    assert page.status_code == 200
    # Avatar rendering now lives in the shared participant directory module.
    assert "/static/js/participant_directory.js" in page.text
    assert 'id="participantDirectoryList"' in page.text


def test_meeting_templates_page_lists_builtin_delphi_template(
    authenticated_client: TestClient,
    db_session,
):
    from app.data.meeting_template_manager import seed_builtin_meeting_templates

    [template] = seed_builtin_meeting_templates(db_session)

    response = authenticated_client.get("/meeting/templates")
    assert response.status_code == 200
    assert "Meeting Templates" in response.text
    assert "Classical Delphi" in response.text
    assert "Packaged method" in response.text
    assert "orchestrations/delphi.json" in response.text
    assert "Method outline" in response.text
    assert "Runtime gates" in response.text
    assert "Iterate a round subcycle: review feedback and justify, then re-rank." in response.text
    assert "Additional ranking rounds are materialized only if convergence has not been reached." in response.text
    assert "START FROM TEMPLATE" in response.text
    assert f"/meeting/templates/{template.template_id}/start" in response.text
    assert "/meeting/create?template_id=" not in response.text
    assert "Meeting not found" not in response.text


def test_meeting_templates_page_exposes_custom_template_management(
    authenticated_client: TestClient,
):
    meeting_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Reusable Template Management Source",
            "description": "Save this structure for management.",
            "agenda_items": ["Review"],
        },
    )
    assert meeting_response.status_code == 200, meeting_response.text
    template_response = authenticated_client.post(
        f"/api/meetings/{meeting_response.json()['id']}/templates",
        json={"name": "Managed Custom Template"},
    )
    assert template_response.status_code == 200, template_response.text
    template_id = template_response.json()["template_id"]

    page = authenticated_client.get("/meeting/templates")
    assert page.status_code == 200
    assert "Managed Custom Template" in page.text
    assert f'data-template-id="{template_id}"' in page.text
    assert 'data-template-action="edit"' in page.text
    assert 'data-template-action="archive"' in page.text
    assert 'data-template-action="delete"' in page.text


def test_start_from_orchestration_backed_template_uses_guided_start_page(
    authenticated_client: TestClient,
    db_session,
):
    from app.data.meeting_template_manager import seed_builtin_meeting_templates

    [template] = seed_builtin_meeting_templates(db_session)

    response = authenticated_client.get(
        f"/meeting/create?template_id={template.template_id}",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/meeting/templates/{template.template_id}/start"

    start_page = authenticated_client.get(response.headers["location"])
    assert start_page.status_code == 200
    assert "Start Classical Delphi" in start_page.text
    assert "Session Name" in start_page.text
    assert "Question for the Group" in start_page.text
    assert "Participants" in start_page.text
    # Participants are attached with the shared directory picker (real users by
    # id), not a free-text contacts field.
    assert "/static/js/participant_directory.js" in start_page.text
    assert 'id="participantDirectoryList"' in start_page.text
    assert "Names, logins, or emails separated by commas" not in start_page.text
    assert "What happens next" in start_page.text
    assert "Facilitator role" in start_page.text
    assert "Decidero will show the current evidence and the next available choice" in start_page.text
    assert "Generate candidate Delphi items." in start_page.text
    assert "Runtime gates" in start_page.text
    assert f"/api/meetings/templates/{template.template_id}/meetings" in start_page.text
    assert "agendaItems" not in start_page.text
    assert "addAgendaItem" not in start_page.text


def test_template_creation_api_creates_orchestration_bound_meeting(
    authenticated_client: TestClient,
    db_session,
):
    from app.data.meeting_template_manager import seed_builtin_meeting_templates

    [template] = seed_builtin_meeting_templates(db_session)

    response = authenticated_client.post(
        f"/api/meetings/templates/{template.template_id}/meetings",
        json={
            "title": "API Delphi Run",
            "description": "Create from the packaged method.",
            "participant_ids": [],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["agenda_strategy"] == "orchestration"
    assert payload["orchestration_path"] == "orchestrations/delphi.json"
    assert payload["source_template_id"] == template.template_id
    assert len(payload["agenda"]) == 1
    assert payload["agenda"][0]["tool_type"] == "brainstorming"
    assert payload["agenda"][0]["title"] == "Round 1: Generate Delphi Items"


def test_template_creation_api_attaches_selected_participants(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    """Participant IDs chosen on the template start page must reach the meeting.

    Regression: the start page previously sent a free-text ``participant_contacts``
    field that the backend never consumed, so template meetings were created with
    no participants. The directory picker now submits real ``participant_ids``.
    """
    from app.data.meeting_template_manager import seed_builtin_meeting_templates

    [template] = seed_builtin_meeting_templates(db_session)

    participant = user_manager_with_admin.add_user(
        first_name="Template",
        last_name="Panelist",
        email="template.panelist@example.com",
        hashed_password=get_password_hash("PanelPass1!"),
        role=UserRole.PARTICIPANT.value,
        login="template_panelist",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(participant)

    response = authenticated_client.post(
        f"/api/meetings/templates/{template.template_id}/meetings",
        json={
            "title": "Delphi With Panel",
            "description": "Attach a real panelist to the orchestration meeting.",
            "participant_ids": [participant.user_id],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert participant.user_id in payload.get("participant_ids", [])


def test_orchestration_advance_endpoint_materializes_next_round(
    authenticated_client: TestClient,
    db_session,
):
    """Deliberate Heron (Phase 8 Step 2): the facilitator advance endpoint
    materializes the next engine step, and round 2 carries previous_round_feedback
    — proving the Step 1 rehydration survives the per-request endpoint boundary.
    """
    from app.data.activity_bundle_manager import ActivityBundleManager
    from app.data.meeting_template_manager import seed_builtin_meeting_templates
    from app.models.activity_bundle import ActivityBundle

    [template] = seed_builtin_meeting_templates(db_session)
    create = authenticated_client.post(
        f"/api/meetings/templates/{template.template_id}/meetings",
        json={"title": "Advance Run", "description": "Drive the Delphi loop.",
              "participant_ids": []},
    )
    assert create.status_code == 200, create.text
    meeting_id = create.json()["meeting_id"]
    brainstorm_id = create.json()["agenda"][0]["activity_id"]

    bm = ActivityBundleManager(db_session)
    # Simulate stopping the brainstorm by finalizing its output bundle.
    bm.finalize_output_bundle(
        meeting_id, brainstorm_id,
        [{"content": "idea-a"}, {"content": "idea-b"}], metadata={"source": "test"},
    )

    def _advance_close_justify(expected_round):
        # Delphi subcycle: each round closes with a post-ranking justification
        # step (brainstorming). Advance into it and finalize it.
        adv = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
        assert adv.status_code == 200, adv.text
        jbody = adv.json()
        assert jbody["status"] == "advanced"
        jact = jbody["activity"]
        assert jact["tool_type"] == "brainstorming"
        assert jact["config"]["_orchestration"]["round_index"] == expected_round
        jorch = jact["config"]["_orchestration"]
        bm.finalize_output_bundle(
            meeting_id, jact["activity_id"], [],
            metadata={"source": "test-justify"},
            logical_step_id=jorch["logical_step_id"], round_index=expected_round,
        )

    # Advance -> Round 1 subcycle: rank-order vote first.
    adv1 = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert adv1.status_code == 200, adv1.text
    body1 = adv1.json()
    assert body1["status"] == "advanced"
    act1 = body1["activity"]
    assert act1["tool_type"] == "rank_order_voting"
    assert act1["config"]["_orchestration"]["round_index"] == 0
    # No stale runtime data on the freshly materialized activity.
    assert not act1.get("started_at")
    assert not act1.get("stopped_at")

    orch0 = act1["config"]["_orchestration"]
    bm.finalize_output_bundle(
        meeting_id, act1["activity_id"],
        [{"content": "idea-a", "metadata": {"delphi": {"iqr": 2.0, "median": 1.0}}}],
        metadata={"source": "test"},
        logical_step_id=orch0["logical_step_id"], round_index=0,
    )

    # ... then the post-ranking justification step closes the round.
    _advance_close_justify(0)

    # Advance -> round-gate decision (facilitator continue/conclude).
    gate_adv = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert gate_adv.status_code == 200, gate_adv.text
    gate_body = gate_adv.json()
    assert gate_body["status"] == "paused"
    gate_activity_id = gate_body["pending_decision"]["activity_id"]
    assert gate_body["pending_decision"]["options"] == ["continue", "conclude"]
    # Deliberate Heron: the gate carries recommendation + evidence for the UI.
    assert gate_body["pending_decision"]["is_round_gate"] is True
    assert gate_body["pending_decision"]["recommendation"] in ("continue", "conclude")
    assert gate_body["pending_decision"]["evidence"]["round_number"] == 1

    # The decision-state endpoint exposes the same gate context for rendering.
    state_resp = authenticated_client.get(
        f"/api/meetings/{meeting_id}/orchestration/facilitator-decisions/{gate_activity_id}"
    )
    assert state_resp.status_code == 200, state_resp.text
    state_json = state_resp.json()
    assert state_json["is_round_gate"] is True
    assert state_json["evidence"]["max_rounds"] == 4

    # Choose "continue" to run another round.
    resume = authenticated_client.post(
        f"/api/meetings/{meeting_id}/orchestration/facilitator-decisions/{gate_activity_id}/responses",
        json={"chosen_option": "continue"},
    )
    assert resume.status_code == 200, resume.text

    # Advance -> Round 2 subcycle: rank-order vote, carrying the prior round's
    # feedback. (Its post-ranking justification step would follow.)
    adv2 = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert adv2.status_code == 200, adv2.text
    body2 = adv2.json()
    assert body2["status"] == "advanced"
    act2 = body2["activity"]
    assert act2["tool_type"] == "rank_order_voting"
    assert act2["config"]["_orchestration"]["round_index"] == 1

    input_bundle = (
        db_session.query(ActivityBundle)
        .filter(ActivityBundle.activity_id == act2["activity_id"],
                ActivityBundle.kind == "input")
        .first()
    )
    assert input_bundle is not None
    # Non-empty feedback proves rehydration worked; without it this would be 0.
    assert len(input_bundle.items) >= 1


def test_orchestration_advance_rejects_non_facilitator(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    """Deliberate Heron: advancing the orchestration is facilitator-only."""
    from app.data.meeting_template_manager import seed_builtin_meeting_templates

    [template] = seed_builtin_meeting_templates(db_session)

    # Log in as the admin facilitator and create the orchestration meeting.
    client.post(
        "/api/auth/token",
        json={"username": ADMIN_LOGIN_FOR_TEST, "password": ADMIN_PASSWORD_FOR_TEST},
    )
    create = client.post(
        f"/api/meetings/templates/{template.template_id}/meetings",
        json={"title": "Auth Run", "description": "x", "participant_ids": []},
    )
    assert create.status_code == 200, create.text
    meeting_id = create.json()["meeting_id"]

    # Create a non-facilitator participant and log in as them.
    user_manager_with_admin.add_user(
        first_name="Pan", last_name="El", email="pan.el@example.com",
        hashed_password=get_password_hash("PanelPass1!"),
        role=UserRole.PARTICIPANT.value, login="pan_el",
    )
    user_manager_with_admin.db.commit()
    client.post(
        "/api/auth/token", json={"username": "pan_el", "password": "PanelPass1!"},
    )

    resp = client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert resp.status_code == 403, resp.text


def test_orchestration_meeting_page_sets_facilitator_expectations(
    authenticated_client: TestClient,
    db_session,
):
    from app.data.meeting_template_manager import seed_builtin_meeting_templates

    [template] = seed_builtin_meeting_templates(db_session)

    create_response = authenticated_client.post(
        f"/api/meetings/templates/{template.template_id}/meetings",
        json={
            "title": "Facilitator Delphi Run",
            "description": "Create from the packaged method.",
            "participant_ids": [],
        },
    )
    assert create_response.status_code == 200, create_response.text

    page = authenticated_client.get(f"/meeting/{create_response.json()['id']}")
    assert page.status_code == 200
    assert "Orchestrated Method" in page.text
    assert "Decidero will create later rounds and decision points only when this method reaches them." in page.text
    assert "Method outline" in page.text
    assert "Runtime gates" in page.text
    assert "Generate candidate Delphi items." in page.text
    assert "The process stops when IQR stability fires or the maximum-round bound is reached." in page.text


def test_meeting_page_exposes_backend_capability_data(
    authenticated_client: TestClient,
):
    create_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Capability Inventory Meeting",
            "description": "Expose per-meeting capability state to the page shell",
            "scheduled_datetime": "2099-12-31T12:00:00Z",
            "agenda_items": ["Review"],
        },
    )
    assert create_response.status_code == 200, create_response.json()

    page = authenticated_client.get(f"/meeting/{create_response.json()['id']}")
    assert page.status_code == 200
    assert 'data-meeting-can-view="true"' in page.text
    assert 'data-meeting-can-manage="true"' in page.text
    assert 'data-meeting-can-delete="true"' in page.text
    assert 'data-meeting-is-facilitator="true"' in page.text
    assert 'data-meeting-is-participant="false"' in page.text


def test_off_roster_facilitator_cannot_access_meeting_page_controls(
    client: TestClient,
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    facilitator_password = "PageScope1!"
    facilitator = user_manager_with_admin.add_user(
        first_name="Page",
        last_name="Facilitator",
        email="page.facilitator@example.com",
        hashed_password=get_password_hash(facilitator_password),
        role=UserRole.FACILITATOR.value,
        login="page_facilitator",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(facilitator)

    create_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Page Gate Meeting",
            "description": "Verifies page-route gates use canonical meeting capability",
            "scheduled_datetime": "2099-12-31T12:00:00Z",
            "agenda_items": ["Review"],
        },
    )
    assert create_response.status_code == 200, create_response.json()
    meeting_id = create_response.json()["id"]

    login_response = client.post(
        "/api/auth/token",
        json={"username": facilitator.login, "password": facilitator_password},
    )
    assert login_response.status_code == 200, login_response.text

    settings_response = client.get(f"/meeting/{meeting_id}/settings")
    assert settings_response.status_code == 403

    activity_log_response = client.get(f"/meeting/{meeting_id}/activity-log")
    assert activity_log_response.status_code == 403


def test_rostered_facilitator_can_access_meeting_page_controls(
    client: TestClient,
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    facilitator_password = "RosterPage1!"
    facilitator = user_manager_with_admin.add_user(
        first_name="Rostered",
        last_name="Pagefac",
        email="rostered.pagefac@example.com",
        hashed_password=get_password_hash(facilitator_password),
        role=UserRole.FACILITATOR.value,
        login="rostered_pagefac",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(facilitator)

    create_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Rostered Page Gate Meeting",
            "description": "Verifies rostered facilitators keep page-route control access",
            "scheduled_datetime": "2099-12-31T12:00:00Z",
            "agenda_items": ["Review"],
            "participant_ids": [facilitator.user_id],
            "co_facilitator_ids": [facilitator.user_id],
        },
    )
    assert create_response.status_code == 200, create_response.json()
    meeting_id = create_response.json()["id"]

    login_response = client.post(
        "/api/auth/token",
        json={"username": facilitator.login, "password": facilitator_password},
    )
    assert login_response.status_code == 200, login_response.text

    settings_response = client.get(f"/meeting/{meeting_id}/settings")
    assert settings_response.status_code == 200

    activity_log_response = client.get(f"/meeting/{meeting_id}/activity-log")
    assert activity_log_response.status_code == 200


# Add more tests for other GETtable pages if needed (e.g., /meeting/create, /admin/users)
# ensuring to handle authentication state appropriately.

# Note: POST handlers for /login and /register in pages.py were removed.
# Client-side JS now directly calls API endpoints (/api/auth/token and /api/auth/register).
# Tests for that functionality are primarily in test_auth.py.


def test_fork_orchestration_template_api_returns_summary(
    authenticated_client: TestClient,
    db_session,
):
    """Plainspoken Marmot: the fork endpoint compiles tuning into a custom template
    and returns a plain-language summary."""
    from app.data.meeting_template_manager import seed_builtin_meeting_templates

    [delphi] = seed_builtin_meeting_templates(db_session)
    response = authenticated_client.post(
        f"/api/meetings/templates/{delphi.template_id}/fork",
        json={"name": "Quick Delphi", "max_rounds": 2, "who_decides": "automatic"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["template"]["source"] == "custom"
    assert isinstance(body["summary"], list) and body["summary"]
    # The forked custom template can then be started like any other.
    forked_id = body["template"]["template_id"]
    start = authenticated_client.post(
        f"/api/meetings/templates/{forked_id}/meetings",
        json={"title": "Run Quick Delphi", "description": "x", "participant_ids": []},
    )
    assert start.status_code == 200, start.text
    assert start.json()["agenda_strategy"] == "orchestration"
