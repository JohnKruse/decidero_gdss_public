import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from app.data.meeting_manager import MeetingManager
from app.data.user_manager import UserManager
from app.utils.security import get_password_hash
from app.schemas.meeting import MeetingCreate, AgendaActivityCreate
from app.models.user import User
from app.models.meeting import Meeting
from app.services import meeting_state_manager
from sqlalchemy.orm import Session

TEST_PASSWORD = "TestPass123!"


def create_test_user(db: Session, login: str, role: str = "participant") -> User:
    manager = UserManager()
    manager.set_db(db)
    return manager.add_user(
        login=login,
        hashed_password=get_password_hash(TEST_PASSWORD),
        first_name=login,
        last_name="Test",
        email=f"{login}@example.com",
        role=role,
    )


def create_test_meeting(db: Session, owner: User, participants: list[User]) -> Meeting:
    manager = MeetingManager(db)
    agenda_item = AgendaActivityCreate(
        tool_type="voting", title="Test Voting", order_index=1
    )
    return manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Test Meeting",
            description="Test Description",
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc) + timedelta(hours=1),
            duration_minutes=60,
            owner_id=owner.user_id,
            participant_ids=[p.user_id for p in participants],
        ),
        facilitator_id=owner.user_id,
        agenda_items=[agenda_item],
    )


def test_set_activity_participants_custom(db_session: Session):
    owner = create_test_user(db_session, "owner", "facilitator")
    p1 = create_test_user(db_session, "p1")
    p2 = create_test_user(db_session, "p2")
    p3 = create_test_user(db_session, "p3")

    meeting = create_test_meeting(db_session, owner, [p1, p2, p3])
    manager = MeetingManager(db_session)
    activity = meeting.agenda_activities[0]

    # Set custom participants (p1 and p2 only)
    updated_activity = manager.set_activity_participants(
        meeting.meeting_id, activity.activity_id, [p1.user_id, p2.user_id]
    )

    assert updated_activity.config["participant_ids"] == [p1.user_id, p2.user_id]

    # Verify persistence
    db_session.refresh(activity)
    assert activity.config["participant_ids"] == [p1.user_id, p2.user_id]


def test_set_activity_participants_all(db_session: Session):
    owner = create_test_user(db_session, "owner", "facilitator")
    p1 = create_test_user(db_session, "p1")
    meeting = create_test_meeting(db_session, owner, [p1])
    manager = MeetingManager(db_session)
    activity = meeting.agenda_activities[0]

    # First set custom
    manager.set_activity_participants(
        meeting.meeting_id, activity.activity_id, [p1.user_id]
    )

    # Then set back to all (None)
    updated_activity = manager.set_activity_participants(
        meeting.meeting_id, activity.activity_id, None
    )

    assert "participant_ids" not in updated_activity.config


def test_set_activity_participants_invalid_user(db_session: Session):
    owner = create_test_user(db_session, "owner", "facilitator")
    p1 = create_test_user(db_session, "p1")
    outsider = create_test_user(db_session, "outsider")

    meeting = create_test_meeting(db_session, owner, [p1])
    manager = MeetingManager(db_session)
    activity = meeting.agenda_activities[0]

    # Try to assign a user who is not in the meeting
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        manager.set_activity_participants(
            meeting.meeting_id, activity.activity_id, [outsider.user_id]
        )
    assert excinfo.value.status_code == 400


def test_cascade_participant_removal(db_session: Session):
    owner = create_test_user(db_session, "owner", "facilitator")
    p1 = create_test_user(db_session, "p1")
    p2 = create_test_user(db_session, "p2")

    meeting = create_test_meeting(db_session, owner, [p1, p2])
    manager = MeetingManager(db_session)
    activity = meeting.agenda_activities[0]

    # Assign p1 and p2 to activity
    manager.set_activity_participants(
        meeting.meeting_id, activity.activity_id, [p1.user_id, p2.user_id]
    )

    # Remove p1 from the meeting
    manager.remove_participant(meeting.meeting_id, p1.user_id)

    # Verify p1 is removed from activity config
    db_session.refresh(activity)
    assert activity.config["participant_ids"] == [p2.user_id]


def test_api_update_activity_participants(client, db_session: Session):
    # Setup
    owner = create_test_user(db_session, "owner", "facilitator")
    p1 = create_test_user(db_session, "p1")
    meeting = create_test_meeting(db_session, owner, [p1])
    activity = meeting.agenda_activities[0]

    # Login as owner
    client.post(
        "/api/auth/token", json={"username": "owner", "password": TEST_PASSWORD}
    )

    # Test setting custom participants
    response = client.put(
        f"/api/meetings/{meeting.meeting_id}/agenda/{activity.activity_id}/participants",
        json={"mode": "custom", "participant_ids": [p1.user_id]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "custom"
    assert data["participant_ids"] == [p1.user_id]

    # Test setting 'all'
    response = client.put(
        f"/api/meetings/{meeting.meeting_id}/agenda/{activity.activity_id}/participants",
        json={"mode": "all"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "all"
    assert data["participant_ids"] == []


def test_api_update_activity_participants_permissions(client, db_session: Session):
    # Setup
    owner = create_test_user(db_session, "owner", "facilitator")
    p1 = create_test_user(db_session, "p1")
    meeting = create_test_meeting(db_session, owner, [p1])
    activity = meeting.agenda_activities[0]

    # Login as participant (p1)
    client.post("/api/auth/token", json={"username": "p1", "password": TEST_PASSWORD})

    # Try to update participants
    response = client.put(
        f"/api/meetings/{meeting.meeting_id}/agenda/{activity.activity_id}/participants",
        json={"mode": "custom", "participant_ids": [p1.user_id]},
    )
    assert response.status_code == 403


def test_live_roster_update_syncs_meeting_state(client, db_session: Session):
    owner = create_test_user(db_session, "owner", "facilitator")
    p1 = create_test_user(db_session, "p1")
    p2 = create_test_user(db_session, "p2")
    meeting = create_test_meeting(db_session, owner, [p1, p2])
    manager = MeetingManager(db_session)
    activity = meeting.agenda_activities[0]

    asyncio.run(meeting_state_manager.reset(meeting.meeting_id))
    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity.activity_id,
                    "currentTool": activity.tool_type,
                    "status": "in_progress",
                    "metadata": {
                        "participantScope": "custom",
                        "participantIds": [p1.user_id],
                    },
                    "activeActivities": {
                        activity.activity_id: {
                            "activityId": activity.activity_id,
                            "tool": activity.tool_type,
                            "status": "in_progress",
                            "metadata": {
                                "participantScope": "custom",
                                "participantIds": [p1.user_id],
                            },
                            "participantIds": [p1.user_id],
                            "startedAt": datetime.now(timezone.utc).isoformat(),
                            "stoppedAt": None,
                            "elapsedTime": 0,
                        }
                    },
                },
            )
        )

        client.post("/api/auth/token", json={"username": owner.login, "password": TEST_PASSWORD})
        response = client.put(
            f"/api/meetings/{meeting.meeting_id}/agenda/{activity.activity_id}/participants",
            json={"mode": "custom", "participant_ids": [p1.user_id, p2.user_id]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert set(payload.get("participant_ids", [])) == {p1.user_id, p2.user_id}

        snapshot = asyncio.run(meeting_state_manager.snapshot(meeting.meeting_id))
        assert snapshot is not None
        active_entries = snapshot.get("activeActivities") or []
        target_entry = next(
            (
                entry
                for entry in active_entries
                if isinstance(entry, dict)
                and (entry.get("activityId") or entry.get("activity_id")) == activity.activity_id
            ),
            None,
        )
        assert target_entry is not None
        assert set(target_entry.get("participantIds") or []) == {p1.user_id, p2.user_id}
        assert snapshot.get("metadata", {}).get("participantScope") == "custom"
        assert set(snapshot.get("metadata", {}).get("participantIds") or []) == {
            p1.user_id,
            p2.user_id,
        }
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_live_roster_update_allows_overlap(client, db_session: Session):
    owner = create_test_user(db_session, "owner", "facilitator")
    p1 = create_test_user(db_session, "p1")
    p2 = create_test_user(db_session, "p2")

    meeting = create_test_meeting(db_session, owner, [p1, p2])
    manager = MeetingManager(db_session)
    activity_a = meeting.agenda_activities[0]
    activity_b = manager.add_agenda_activity(
        meeting.meeting_id,
        AgendaActivityCreate(tool_type="brainstorming", title="Brainstorm", order_index=2),
    )

    asyncio.run(meeting_state_manager.reset(meeting.meeting_id))
    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_a.activity_id,
                    "currentTool": activity_a.tool_type,
                    "status": "in_progress",
                    "metadata": {
                        "participantScope": "custom",
                        "participantIds": [p1.user_id],
                    },
                    "activeActivities": {
                        activity_a.activity_id: {
                            "activityId": activity_a.activity_id,
                            "tool": activity_a.tool_type,
                            "status": "in_progress",
                            "metadata": {
                                "participantScope": "custom",
                                "participantIds": [p1.user_id],
                            },
                            "participantIds": [p1.user_id],
                            "startedAt": datetime.now(timezone.utc).isoformat(),
                            "stoppedAt": None,
                            "elapsedTime": 0,
                        },
                        activity_b.activity_id: {
                            "activityId": activity_b.activity_id,
                            "tool": activity_b.tool_type,
                            "status": "in_progress",
                            "metadata": {
                                "participantScope": "custom",
                                "participantIds": [p2.user_id],
                            },
                            "participantIds": [p2.user_id],
                            "startedAt": datetime.now(timezone.utc).isoformat(),
                            "stoppedAt": None,
                            "elapsedTime": 0,
                        },
                    },
                },
            )
        )

        client.post("/api/auth/token", json={"username": owner.login, "password": TEST_PASSWORD})
        response = client.put(
            f"/api/meetings/{meeting.meeting_id}/agenda/{activity_a.activity_id}/participants",
            json={"mode": "custom", "participant_ids": [p1.user_id, p2.user_id]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert set(payload.get("participant_ids", [])) == {p1.user_id, p2.user_id}

        snapshot = asyncio.run(meeting_state_manager.snapshot(meeting.meeting_id))
        active_entries = snapshot.get("activeActivities") or []
        target_entry = next(
            (
                entry
                for entry in active_entries
                if isinstance(entry, dict)
                and (entry.get("activityId") or entry.get("activity_id")) == activity_a.activity_id
            ),
            None,
        )
        assert target_entry is not None
        assert set(target_entry.get("participantIds") or []) == {p1.user_id, p2.user_id}
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))
