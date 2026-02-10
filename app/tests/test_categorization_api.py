from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.data.meeting_manager import MeetingManager
from app.models.user import UserRole
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services.categorization_manager import CategorizationManager
from app.utils.security import get_password_hash


def _create_categorization_meeting(db_session, owner_id: str):
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Categorization API Test",
            description="Categorization API coverage",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=owner_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=owner_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Categorize",
                config={
                    "mode": "FACILITATOR_LIVE",
                    "items": [{"id": "i-1", "content": "Item 1"}],
                    "buckets": ["Bucket A"],
                },
            )
        ],
    )
    return meeting


def test_categorization_state_and_bucket_mutations(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )

    state_resp = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/categorization/state",
        params={"activity_id": activity_id},
    )
    assert state_resp.status_code == 200, state_resp.json()
    state_payload = state_resp.json()
    assert state_payload["unsorted_category_id"] == "UNSORTED"
    assert len(state_payload["items"]) == 1

    create_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/categorization/buckets",
        json={"activity_id": activity_id, "title": "Bucket B"},
    )
    assert create_resp.status_code == 200, create_resp.json()
    created_bucket_id = create_resp.json()["category_id"]

    assign_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/categorization/assignments",
        json={"activity_id": activity_id, "item_key": "i-1", "category_id": created_bucket_id},
    )
    assert assign_resp.status_code == 200, assign_resp.json()
    assert assign_resp.json()["category_id"] == created_bucket_id


def test_categorization_bucket_create_forbidden_for_participant(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    participant = user_manager_with_admin.add_user(
        first_name="Part",
        last_name="User",
        email="participant@decidero.local",
        hashed_password=get_password_hash("Participant@123"),
        role=UserRole.PARTICIPANT.value,
        login="participant",
    )
    meeting.participants.append(participant)
    db_session.add(meeting)
    db_session.commit()

    login_resp = client.post(
        "/api/auth/token",
        json={"username": "participant", "password": "Participant@123"},
    )
    assert login_resp.status_code == 200, login_resp.json()

    create_resp = client.post(
        f"/api/meetings/{meeting.meeting_id}/categorization/buckets",
        json={"activity_id": activity_id, "title": "Not Allowed"},
    )
    assert create_resp.status_code == 403, create_resp.json()
