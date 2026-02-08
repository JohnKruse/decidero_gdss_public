from fastapi.testclient import TestClient


def test_admin_users_page_loads(authenticated_client: TestClient):
    resp = authenticated_client.get("/admin/users")
    assert resp.status_code == 200
    assert "Manage Users" in resp.text


def test_admin_users_api_includes_avatar_color(authenticated_client: TestClient):
    resp = authenticated_client.get("/api/users/")
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, list)
    assert payload
    assert "avatar_color" in payload[0]
