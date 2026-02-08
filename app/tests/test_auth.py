from sqlalchemy.orm import Session
import pytest
from fastapi.testclient import TestClient
from app.data.user_manager import UserManager
from app.models.user import UserRole
from app.schemas.schemas import Permission
from app.auth.auth import has_permission, ROLE_PERMISSIONS
import os

# client = TestClient(app) # Removed module-level client

# Use the same admin credentials as in startup_event for consistency
ADMIN_EMAIL_FOR_TEST = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
ADMIN_PASSWORD_FOR_TEST = os.getenv("ADMIN_PASSWORD", "Admin@123!")
ADMIN_LOGIN_FOR_TEST = os.getenv("ADMIN_LOGIN", ADMIN_EMAIL_FOR_TEST.split("@")[0])


@pytest.fixture(scope="function")
def user_manager_fixture(user_manager_with_admin: UserManager):  # Use the new fixture
    """Provides a user manager instance where the default admin already exists."""
    return user_manager_with_admin


def test_initial_admin_creation_on_startup(
    user_manager_fixture: UserManager,
):  # Fixture name kept for test compatibility
    """Test that admin user (from startup variables) exists."""
    user = user_manager_fixture.get_user_by_email(ADMIN_EMAIL_FOR_TEST)
    assert user is not None, f"Admin user {ADMIN_EMAIL_FOR_TEST} not found by fixture."
    assert user.email == ADMIN_EMAIL_FOR_TEST
    assert user.role.upper() == "ADMIN"


def test_role_permission_inheritance():
    """Ensure facilitator and admin inherit lower-role permissions."""
    assert Permission.VIEW_MEETING in ROLE_PERMISSIONS[UserRole.PARTICIPANT]
    assert Permission.VIEW_MEETING in ROLE_PERMISSIONS[UserRole.FACILITATOR]
    assert Permission.CREATE_MEETING in ROLE_PERMISSIONS[UserRole.FACILITATOR]
    assert Permission.CREATE_MEETING in ROLE_PERMISSIONS[UserRole.ADMIN]
    assert Permission.MANAGE_USERS in ROLE_PERMISSIONS[UserRole.ADMIN]
    assert Permission.MANAGE_USERS not in ROLE_PERMISSIONS[UserRole.FACILITATOR]


def test_has_permission_respects_hierarchy():
    """Admins have all perms; participants cannot manage/administer."""
    assert has_permission(UserRole.ADMIN, Permission.MANAGE_ROLES)
    assert has_permission(UserRole.FACILITATOR, Permission.CREATE_MEETING)
    assert not has_permission(UserRole.PARTICIPANT, Permission.CREATE_MEETING)
    assert not has_permission(UserRole.FACILITATOR, Permission.MANAGE_USERS)


def test_login_with_admin(
    user_manager_fixture: UserManager, client: TestClient
):  # Added client fixture
    """Test admin login, token cookie setting, and response structure"""
    # Send JSON payload
    login_data = {"username": ADMIN_LOGIN_FOR_TEST, "password": ADMIN_PASSWORD_FOR_TEST}
    response = client.post("/api/auth/token", json=login_data)  # Send as JSON
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("login_successful") is True
    assert (
        data.get("role") == UserRole.ADMIN.value
    )  # Ensure role is correct in response
    assert "access_token" in response.cookies

    # Cookies are often stored as "value"; the quotes are part of the string representation
    # So, we check if the actual value (stripping quotes) starts with "Bearer "
    cookie_value = response.cookies["access_token"]
    if cookie_value.startswith('"') and cookie_value.endswith('"'):
        cookie_value = cookie_value[1:-1]  # Strip surrounding quotes
    assert cookie_value.startswith("Bearer ")


def test_invalid_login(
    user_manager_fixture: UserManager, client: TestClient
):  # Added client fixture
    """Test login with invalid credentials"""
    login_data = {"username": ADMIN_LOGIN_FOR_TEST, "password": "wrongpassword"}
    response = client.post("/api/auth/token", json=login_data)  # Send as JSON
    assert response.status_code == 401, response.text
    data = response.json()
    # For an invalid login, login_successful might not be present or false, or detail provided
    assert (
        data.get("detail") == "Incorrect email or password"
    )  # Based on /api/auth/token endpoint
    assert "access_token" not in response.cookies


def test_protected_endpoint_requires_auth(
    client: TestClient, db_session: Session
):  # Added client and db_session fixture
    """Test accessing a protected endpoint without token redirects."""
    response = client.get(
        "/dashboard", follow_redirects=False
    )  # Middleware will try to access DB, follow_redirects is preferred
    assert response.status_code == 307  # Expect redirect to /login


def test_protected_endpoint_with_auth(
    user_manager_fixture: UserManager, client: TestClient
):  # Added client fixture
    """Test accessing a protected endpoint with token cookie."""
    # Perform login to set the cookie in the test client's session
    login_data = {"username": ADMIN_LOGIN_FOR_TEST, "password": ADMIN_PASSWORD_FOR_TEST}
    login_response = client.post("/api/auth/token", json=login_data)  # Send as JSON
    assert login_response.status_code == 200, login_response.text
    assert "access_token" in login_response.cookies

    # Now access the protected endpoint, TestClient will use the cookie
    response = client.get("/dashboard")
    assert response.status_code == 200, response.text
    assert (
        "DECIDERO GDSS - Dashboard" in response.text
    )  # Check for some dashboard content

    client.cookies.clear()


def test_register_first_user_is_admin(
    db_session: Session, user_manager_fixture: UserManager, client: TestClient
):  # Added client fixture
    """Test that the first registered user gets the SUPER_ADMIN role if no admin exists."""
    all_users = user_manager_fixture.get_all_users()
    for u in all_users:
        user_manager_fixture.delete_user(u.email)
    db_session.commit()  # Ensure deletions are committed before checking has_admin_user

    assert (
        not user_manager_fixture.has_admin_user()
    ), "Database was not cleared of admins properly."

    response = client.post(
        "/api/auth/register",
        json={
            "login": "firstadmin",
            "first_name": "First",
            "last_name": "Admin",
            "email": "firstadmin@example.com",
            "password": "FirstAdmin@123!",
        },
    )
    assert (
        response.status_code == 200
    ), response.text  # Endpoint returns 200 and a message
    assert response.json()["message"] == "User registered successfully. Please log in."

    user = user_manager_fixture.get_user_by_email("firstadmin@example.com")
    assert user is not None
    assert user.role.upper() == "SUPER_ADMIN"


def test_register_second_user_is_participant(
    user_manager_with_admin: UserManager, client: TestClient
):  # Added client fixture
    """Test that subsequent registered users get the PARTICIPANT role."""
    assert (
        user_manager_with_admin.has_admin_user()
    ), "Admin user should exist from fixture."

    participant_email = "seconduser@example.com"
    if user_manager_with_admin.get_user_by_email(participant_email):
        user_manager_with_admin.delete_user(participant_email)
        user_manager_with_admin.db.commit()

    response = client.post(
        "/api/auth/register",
        json={
            "login": "seconduser",
            "first_name": "Second",
            "last_name": "User",
            "email": participant_email,
            "password": "Participant@123!",
        },
    )
    assert response.status_code == 200, response.text

    user = user_manager_with_admin.get_user_by_email(participant_email)
    assert user is not None
    assert user.role.upper() == "PARTICIPANT"


def test_register_duplicate_email(
    user_manager_fixture: UserManager, client: TestClient
):
    """Test registration with a duplicate email"""
    initial_email = "duplicate.email.test@example.com"
    user_data_initial = {
        "login": "duplicate1",
        "first_name": "Duplicate",
        "last_name": "User",
        "email": initial_email,
        "password": "Testuser@123!",
    }
    if user_manager_fixture.get_user_by_email(initial_email):
        user_manager_fixture.delete_user(initial_email)
        user_manager_fixture.db.commit()

    response_initial = client.post("/api/auth/register", json=user_data_initial)
    assert response_initial.status_code == 200, response_initial.text

    user_data_duplicate = {
        "login": "duplicate2",
        "first_name": "Duplicate2",
        "last_name": "User2",
        "email": initial_email,
        "password": "Another@123!",
    }
    response_duplicate = client.post("/api/auth/register", json=user_data_duplicate)
    assert (
        response_duplicate.status_code == 400
    ), response_duplicate.text  # Changed from 409 to 400 as per add_user logic
    assert (
        response_duplicate.json()["detail"]
        == f"User with email {initial_email} already exists."
    )


def test_register_weak_password_too_short(
    user_manager_fixture: UserManager, client: TestClient
):  # Added client fixture
    """Test registration with a password that's too short (fails Pydantic min_length)."""
    response = client.post(
        "/api/auth/register",
        json={
            "login": "weakpwuser",
            "first_name": "WeakPw",
            "last_name": "User",
            "email": "weakpword.short@example.com",
            "password": "weak",  # Fails min_length=8 in UserCreate schema
        },
    )
    assert response.status_code == 422, response.text  # Pydantic validation error
    error_details = response.json().get("detail", [])  # This is now a list of strings
    assert isinstance(error_details, list)
    password_error_found = False
    expected_error_msg_part = (
        "String should have at least 8 characters"  # Pydantic's default message
    )
    for error_msg in error_details:
        if expected_error_msg_part in error_msg:
            password_error_found = True
            break
    assert (
        password_error_found
    ), f"Pydantic min_length error '{expected_error_msg_part}' not found in {error_details}."


def test_register_password_fails_complexity_handled_by_pydantic(
    user_manager_fixture: UserManager, client: TestClient
):  # Added client fixture
    """Test registration with a password that meets length but fails complexity (via Pydantic validator)."""
    response = client.post(
        "/api/auth/register",
        json={
            "login": "complexpwfail",
            "first_name": "ComplexPwFail",
            "last_name": "User",
            "email": "complexpwfail.pydantic@example.com",
            "password": "password",  # Meets length (8), fails complexity (no uppercase, digit, special)
        },
    )
    # The /api/auth/register endpoint directly calls validate_password and raises HTTPException(400)
    assert response.status_code == 400, response.text
    error_detail = response.json().get("detail")
    # This message comes from app.utils.password_validation.validate_password via the endpoint
    assert (
        "Password must contain at least one uppercase letter" in error_detail
    ), f"Unexpected error detail: {error_detail}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
