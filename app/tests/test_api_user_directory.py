from datetime import datetime, timedelta, UTC
from fastapi.testclient import TestClient

from app.data.user_manager import UserManager
from app.models.user import UserRole
from app.utils.security import get_password_hash


def _seed_user(
    manager: UserManager,
    login: str,
    role: UserRole = UserRole.PARTICIPANT,
    password: str = "DirPass1!",
) -> str:
    user = manager.add_user(
        first_name="Dir",
        last_name=login.title(),
        email=f"{login}@example.com",
        hashed_password=get_password_hash(password),
        role=role.value if isinstance(role, UserRole) else role,
        login=login,
    )
    manager.db.commit()
    manager.db.refresh(user)
    return user.user_id


def _create_meeting(client: TestClient, title: str = "Directory Meeting") -> dict:
    payload = {
        "title": title,
        "description": "Directory test meeting",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "agenda_items": ["Intro"],
        "participant_contacts": [],
    }
    res = client.post("/api/meetings/", json=payload)
    assert res.status_code == 200, res.json()
    return res.json()


def _login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/api/auth/token", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text


def test_facilitator_requires_meeting_context(
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    facilitator_login = "dir_facilitator"
    _seed_user(
        user_manager_with_admin,
        facilitator_login,
        role=UserRole.FACILITATOR,
        password="DirPass1!",
    )
    _login(client, facilitator_login, "DirPass1!")

    resp = client.get("/api/users/directory")
    assert resp.status_code == 403


def test_directory_returns_activity_context_flags(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    meeting_payload = _create_meeting(
        authenticated_client, title="Directory Context Meeting"
    )
    meeting_id = meeting_payload["id"]
    activity_id = meeting_payload["agenda"][0]["activity_id"]

    roster_user_id = _seed_user(user_manager_with_admin, "dir_roster")
    observer_user_id = _seed_user(user_manager_with_admin, "dir_observer")

    # Add roster user to meeting and scope activity to them only
    add_res = authenticated_client.post(
        f"/api/meetings/{meeting_id}/participants/bulk",
        json={"add": [roster_user_id]},
    )
    assert add_res.status_code == 200, add_res.json()

    assign_res = authenticated_client.put(
        f"/api/meetings/{meeting_id}/agenda/{activity_id}/participants",
        json={"mode": "custom", "participant_ids": [roster_user_id]},
    )
    assert assign_res.status_code == 200, assign_res.json()

    directory_res = authenticated_client.get(
        "/api/users/directory",
        params={
            "meeting_id": meeting_id,
            "activity_id": activity_id,
            "page_size": 50,
        },
    )
    assert directory_res.status_code == 200, directory_res.text
    payload = directory_res.json()
    assert payload["context"]["meeting_id"] == meeting_id
    assert payload["context"]["activity_id"] == activity_id
    assert payload["context"]["activity_mode"] == "custom"

    items = {item["user_id"]: item for item in payload["items"]}
    assert roster_user_id in items
    assert observer_user_id in items

    roster_entry = items[roster_user_id]
    assert roster_entry["is_meeting_participant"] is True
    assert roster_entry["is_activity_participant"] is True
    assert roster_entry["disabled_reason"] is None

    observer_entry = items[observer_user_id]
    assert observer_entry["is_meeting_participant"] is False
    assert observer_entry["is_activity_participant"] is False
    assert "meeting" in observer_entry["disabled_reason"].lower()


def test_facilitator_can_use_directory_in_draft_mode(
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    facilitator_login = "dir_draft_fac"
    _seed_user(
        user_manager_with_admin,
        facilitator_login,
        role=UserRole.FACILITATOR,
        password="DraftPass1!",
    )
    _login(client, facilitator_login, "DraftPass1!")

    resp = client.get("/api/users/directory", params={"draft": "true"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["context"]["meeting_id"] is None
    assert payload["context"]["activity_id"] is None
    assert payload["context"]["activity_mode"] == "all"
    assert isinstance(payload["items"], list)


def test_participant_cannot_use_directory_draft_mode(
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    participant_login = "dir_draft_participant"
    _seed_user(
        user_manager_with_admin,
        participant_login,
        role=UserRole.PARTICIPANT,
        password="DraftPass1!",
    )
    _login(client, participant_login, "DraftPass1!")

    resp = client.get("/api/users/directory", params={"draft": "true"})
    assert resp.status_code == 403


def test_profile_name_update_reflects_in_directory_and_activity_roster(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    participant_login = "dir_rename_target"
    participant_password = "RenamePass1!"
    participant_user_id = _seed_user(
        user_manager_with_admin,
        participant_login,
        role=UserRole.PARTICIPANT,
        password=participant_password,
    )

    meeting_payload = _create_meeting(
        authenticated_client, title="Directory Name Refresh Meeting"
    )
    meeting_id = meeting_payload["id"]
    activity_id = meeting_payload["agenda"][0]["activity_id"]

    add_res = authenticated_client.post(
        f"/api/meetings/{meeting_id}/participants/bulk",
        json={"add": [participant_user_id]},
    )
    assert add_res.status_code == 200, add_res.json()

    assign_res = authenticated_client.put(
        f"/api/meetings/{meeting_id}/agenda/{activity_id}/participants",
        json={"mode": "custom", "participant_ids": [participant_user_id]},
    )
    assert assign_res.status_code == 200, assign_res.json()

    # Update profile name as the participant user.
    _login(authenticated_client, participant_login, participant_password)
    patch_res = authenticated_client.patch(
        "/api/users/me/profile",
        json={"first_name": "Renamed"},
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["first_name"] == "Renamed"

    # Switch back to admin and verify participant listings consume current profile data.
    _login(authenticated_client, "admin", "Admin@123!")

    directory_res = authenticated_client.get(
        "/api/users/directory",
        params={
            "meeting_id": meeting_id,
            "activity_id": activity_id,
            "page_size": 50,
        },
    )
    assert directory_res.status_code == 200, directory_res.text
    items = {item["user_id"]: item for item in directory_res.json()["items"]}
    assert participant_user_id in items
    assert items[participant_user_id]["first_name"] == "Renamed"

    roster_res = authenticated_client.get(
        f"/api/meetings/{meeting_id}/agenda/{activity_id}/participants"
    )
    assert roster_res.status_code == 200, roster_res.text
    available = {
        item["user_id"]: item for item in roster_res.json().get("available_participants", [])
    }
    assert participant_user_id in available
    assert available[participant_user_id]["first_name"] == "Renamed"
