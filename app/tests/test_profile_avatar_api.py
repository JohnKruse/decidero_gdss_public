from fastapi.testclient import TestClient

from app.data.user_manager import UserManager
from app.tests.conftest import ADMIN_LOGIN_FOR_TEST, ADMIN_PASSWORD_FOR_TEST


def _login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/token",
        json={"username": ADMIN_LOGIN_FOR_TEST, "password": ADMIN_PASSWORD_FOR_TEST},
    )
    assert response.status_code == 200, response.text


def test_avatar_catalog_available(
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    _login_admin(client)
    response = client.get("/api/users/avatars/catalog")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] >= 100
    assert isinstance(payload["avatars"], list)
    first = payload["avatars"][0]
    assert first["path"].startswith("/static/avatars/fluent/icons/")


def test_regenerate_avatar_endpoint_updates_seed(
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    _login_admin(client)
    profile_before = client.get("/api/users/me/profile")
    assert profile_before.status_code == 200, profile_before.text
    user_before = profile_before.json()

    regenerate = client.post("/api/users/me/avatar/regenerate")
    assert regenerate.status_code == 200, regenerate.text
    user_after = regenerate.json()
    assert user_after["avatar_seed"] == user_before["avatar_seed"] + 1
    assert user_after["avatar_key"]
    assert user_after["avatar_icon_path"].startswith("/static/avatars/fluent/icons/")


def test_profile_patch_rejects_invalid_avatar_key(
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    _login_admin(client)
    response = client.patch(
        "/api/users/me/profile",
        json={"avatar_key": "not-a-valid-avatar-key"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Invalid avatar key"


def test_regenerate_avatar_color_endpoint_updates_color(
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    _login_admin(client)
    profile_before = client.get("/api/users/me/profile")
    assert profile_before.status_code == 200, profile_before.text
    user_before = profile_before.json()
    color_before = user_before.get("avatar_color")
    assert isinstance(color_before, str)
    assert color_before.startswith("#")
    assert len(color_before) == 7

    regenerate = client.post("/api/users/me/avatar/regenerate_color")
    assert regenerate.status_code == 200, regenerate.text
    user_after = regenerate.json()
    color_after = user_after.get("avatar_color")
    assert isinstance(color_after, str)
    assert color_after.startswith("#")
    assert len(color_after) == 7
    assert color_after != color_before
