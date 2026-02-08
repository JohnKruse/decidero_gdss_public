from fastapi.testclient import TestClient
from app.data.user_manager import UserManager
from app.utils.security import get_password_hash


def _add_user(
    user_manager: UserManager,
    login: str,
    email: str = None,
    first_name: str = None,
    last_name: str = None,
):
    user = user_manager.add_user(
        first_name=first_name or "Test",
        last_name=last_name or "User",
        email=email or f"{login}@example.com",
        hashed_password=get_password_hash("SearchPass1!"),
        role="participant",
        login=login,
    )
    user_manager.db.commit()
    user_manager.db.refresh(user)
    return user


def test_search_requires_auth(client: TestClient):
    # Middleware now returns 401 responses for unauthenticated API access
    resp = client.get("/api/users/search", params={"q": "al"})
    assert resp.status_code == 401


def test_search_min_length_validation(authenticated_client: TestClient):
    resp = authenticated_client.get("/api/users/search", params={"q": "a"})
    assert resp.status_code == 400
    assert "Query must be at least 2 characters" in resp.text


def test_search_returns_matching_users(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    # Seed users
    _ = _add_user(
        user_manager_with_admin, login="alice", first_name="Alice", last_name="Wonder"
    )
    _ = _add_user(
        user_manager_with_admin, login="alina", first_name="Alina", last_name="Marks"
    )
    _ = _add_user(
        user_manager_with_admin, login="bob", first_name="Bob", last_name="Builder"
    )

    resp = authenticated_client.get(
        "/api/users/search", params={"q": "ali", "limit": 10}
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()
    logins = {u.get("login") for u in results}
    assert "alice" in logins
    assert "alina" in logins
    assert "bob" not in logins
    # Ensure expected fields are present
    assert all("login" in u and "user_id" in u for u in results)


def test_search_limit(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    # Ensure enough users exist with prefix 'al'
    _ = _add_user(
        user_manager_with_admin, login="albert", first_name="Albert", last_name="T"
    )
    _ = _add_user(
        user_manager_with_admin, login="alexa", first_name="Alexa", last_name="V"
    )

    resp = authenticated_client.get("/api/users/search", params={"q": "al", "limit": 1})
    assert resp.status_code == 200
    results = resp.json()
    assert isinstance(results, list)
    assert len(results) == 1
