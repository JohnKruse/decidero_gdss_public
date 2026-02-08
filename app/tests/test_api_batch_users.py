from fastapi.testclient import TestClient
from app.data.user_manager import UserManager


def test_batch_create_by_pattern(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    resp = authenticated_client.post(
        "/api/users/batch/pattern",
        json={
            "prefix": "user_",
            "start": 0,
            "end": 5,
            "email_domain": "example.com",
            "default_password": "ValidPass123!",
        },
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["created_count"] == 6
    assert set(data["created_logins"]) == {f"user_{i:02d}" for i in range(0, 6)}


def test_batch_create_by_emails(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    emails = [f"batch{i}@example.com" for i in range(3)]
    resp = authenticated_client.post(
        "/api/users/batch/emails",
        json={"emails": emails, "default_password": "ValidPass123!"},
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["created_count"] == 3
    # Ensure users exist
    for e in emails:
        u = user_manager_with_admin.get_user_by_email(e)
        assert u is not None
        assert u.login == e
        assert u.first_name == e


def test_reset_password(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    # Create a test user
    manager: UserManager = user_manager_with_admin
    login = "reset_target"
    email = f"{login}@example.com"
    from app.utils.security import get_password_hash

    manager.add_user(
        first_name="Reset",
        last_name="Target",
        email=email,
        hashed_password=get_password_hash("OldPass123!"),
        role="participant",
        login=login,
    )
    manager.db.commit()

    resp = authenticated_client.post(
        f"/api/users/{login}/reset_password",
        json={"new_password": "NewPass123!"},
    )
    assert resp.status_code == 200, resp.json()
    updated = manager.get_user_by_login(login)
    assert updated is not None
    assert updated.password_changed is False
