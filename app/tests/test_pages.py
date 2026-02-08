from fastapi.testclient import TestClient
from app.tests.conftest import (
    ADMIN_EMAIL_FOR_TEST,
    ADMIN_PASSWORD_FOR_TEST,
    ADMIN_LOGIN_FOR_TEST,
)  # Import admin credentials if needed for login setup


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


# Add more tests for other GETtable pages if needed (e.g., /meeting/create, /admin/users)
# ensuring to handle authentication state appropriately.

# Note: POST handlers for /login and /register in pages.py were removed.
# Client-side JS now directly calls API endpoints (/api/auth/token and /api/auth/register).
# Tests for that functionality are primarily in test_auth.py.
