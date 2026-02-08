from datetime import datetime, timedelta, UTC

from fastapi.testclient import TestClient

from app.data.user_manager import UserManager
from app.models.user import UserRole
from app.utils.security import get_password_hash


def _create_meeting(client: TestClient) -> str:
    payload = {
        "title": "Participant Admin",
        "description": "Manage participant assignments",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "agenda_items": ["Intro"],
        "participant_contacts": [],
    }
    res = client.post("/api/meetings/", json=payload)
    assert res.status_code == 200, res.json()
    return res.json()["id"]


def _create_user(
    user_manager: UserManager, login: str, role: UserRole = UserRole.PARTICIPANT
):
    user = user_manager.add_user(
        first_name="Test",
        last_name="User",
        email=f"{login}@example.com",
        hashed_password=get_password_hash("TestPass1!"),
        role=role.value,
        login=login,
    )
    user_manager.db.commit()
    user_manager.db.refresh(user)
    return user


def test_facilitator_can_add_and_remove_participants(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    # Arrange: create meeting and a participant user
    meeting_id = _create_meeting(authenticated_client)
    new_user = _create_user(user_manager_with_admin, login="pool_user")

    # Act: add participant by login
    add_res = authenticated_client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"login": new_user.login},
    )
    assert add_res.status_code == 200, add_res.json()
    payload = add_res.json()
    uids = {p["user_id"] for p in payload.get("participants", [])}
    assert new_user.user_id in uids

    # Verify list endpoint shows assignment
    list_res = authenticated_client.get(f"/api/meetings/{meeting_id}/participants")
    assert list_res.status_code == 200, list_res.json()
    listed = list_res.json()
    assert any(p["user_id"] == new_user.user_id for p in listed)

    # Remove participant
    del_res = authenticated_client.delete(
        f"/api/meetings/{meeting_id}/participants/{new_user.user_id}"
    )
    assert del_res.status_code == 200, del_res.json()
    listed_after = authenticated_client.get(
        f"/api/meetings/{meeting_id}/participants"
    ).json()
    assert all(p["user_id"] != new_user.user_id for p in listed_after)


def test_non_facilitator_cannot_manage_participants(
    client: TestClient,
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    # Arrange: create meeting and a non-facilitator user, add them as participant
    meeting_id = _create_meeting(authenticated_client)
    participant = _create_user(user_manager_with_admin, login="participant_only")

    # Admin assigns the participant initially
    res = authenticated_client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"login": participant.login},
    )
    assert res.status_code == 200

    # Login as participant
    login_res = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": "TestPass1!"},
    )
    assert login_res.status_code == 200, login_res.json()

    # Try to add another participant
    other = _create_user(user_manager_with_admin, login="other_pool")
    add_try = client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"login": other.login},
    )
    # Should be forbidden (403) for non-facilitator roles
    assert add_try.status_code in (403, 401)


def test_facilitator_can_assign_activity_participants(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    meeting_id = _create_meeting(authenticated_client)
    meeting_res = authenticated_client.get(f"/api/meetings/{meeting_id}")
    assert meeting_res.status_code == 200, meeting_res.json()
    activity_id = meeting_res.json()["agenda"][0]["activity_id"]

    roster_one = _create_user(user_manager_with_admin, login="activity_roster_one")
    roster_two = _create_user(user_manager_with_admin, login="activity_roster_two")

    for user in (roster_one, roster_two):
        add_res = authenticated_client.post(
            f"/api/meetings/{meeting_id}/participants",
            json={"login": user.login},
        )
        assert add_res.status_code == 200, add_res.json()

    get_res = authenticated_client.get(
        f"/api/meetings/{meeting_id}/agenda/{activity_id}/participants"
    )
    assert get_res.status_code == 200, get_res.json()
    payload = get_res.json()
    assert payload["mode"] == "all"
    available_ids = {row["user_id"] for row in payload["available_participants"]}
    assert {roster_one.user_id, roster_two.user_id}.issubset(available_ids)
    for row in payload["available_participants"]:
        assert "avatar_color" in row
        assert "avatar_key" in row
        assert "avatar_icon_path" in row

    update_res = authenticated_client.put(
        f"/api/meetings/{meeting_id}/agenda/{activity_id}/participants",
        json={"mode": "custom", "participant_ids": [roster_one.user_id]},
    )
    assert update_res.status_code == 200, update_res.json()
    update_payload = update_res.json()
    assert update_payload["mode"] == "custom"
    assert update_payload["participant_ids"] == [roster_one.user_id]

    authenticated_client.delete(
        f"/api/meetings/{meeting_id}/participants/{roster_one.user_id}"
    )
    assignment_after = authenticated_client.get(
        f"/api/meetings/{meeting_id}/agenda/{activity_id}/participants"
    )
    assert assignment_after.status_code == 200, assignment_after.json()
    assert assignment_after.json()["mode"] == "all"


def test_activity_assignment_rejects_non_roster_user(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    meeting_id = _create_meeting(authenticated_client)
    meeting_res = authenticated_client.get(f"/api/meetings/{meeting_id}")
    assert meeting_res.status_code == 200, meeting_res.json()
    activity_id = meeting_res.json()["agenda"][0]["activity_id"]

    roster_user = _create_user(user_manager_with_admin, login="activity_valid")
    authenticated_client.post(
        f"/api/meetings/{meeting_id}/participants",
        json={"login": roster_user.login},
    )

    rogue_user = _create_user(user_manager_with_admin, login="activity_rogue")

    res = authenticated_client.put(
        f"/api/meetings/{meeting_id}/agenda/{activity_id}/participants",
        json={"mode": "custom", "participant_ids": [rogue_user.user_id]},
    )
    assert res.status_code == 400, res.json()


def test_bulk_participant_endpoint_supports_add_and_remove(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    meeting_id = _create_meeting(authenticated_client)
    roster_one = _create_user(user_manager_with_admin, login="bulk_api_one")
    roster_two = _create_user(user_manager_with_admin, login="bulk_api_two")

    add_res = authenticated_client.post(
        f"/api/meetings/{meeting_id}/participants/bulk",
        json={"add": [roster_one.user_id, roster_two.user_id]},
    )
    assert add_res.status_code == 200, add_res.json()
    payload = add_res.json()
    summary = payload["summary"]
    assert set(summary["added_user_ids"]) == {roster_one.user_id, roster_two.user_id}
    assert summary["removed_user_ids"] == []
    participant_ids = {row["user_id"] for row in payload["participants"]}
    assert participant_ids.issuperset({roster_one.user_id, roster_two.user_id})

    remove_res = authenticated_client.post(
        f"/api/meetings/{meeting_id}/participants/bulk",
        json={"remove": [roster_one.user_id]},
    )
    assert remove_res.status_code == 200, remove_res.json()
    after_payload = remove_res.json()
    assert after_payload["summary"]["removed_user_ids"] == [roster_one.user_id]
    remaining_ids = {row["user_id"] for row in after_payload["participants"]}
    assert roster_one.user_id not in remaining_ids
