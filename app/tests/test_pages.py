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
