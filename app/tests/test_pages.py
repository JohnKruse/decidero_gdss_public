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
    assert "normalizeAvatarPath" in page.text
    assert "avatar_icon_path" in page.text


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
    assert "Iterate rank-order voting rounds." in response.text
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
    assert "Names, logins, or emails separated by commas" in start_page.text
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
            "participant_contacts": [ADMIN_LOGIN_FOR_TEST],
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
            "participant_contacts": [],
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
            "participant_contacts": [],
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
