import asyncio
import os
from datetime import datetime, timedelta, UTC

from fastapi.testclient import TestClient

from app.data.meeting_manager import MeetingManager
from app.data.user_manager import UserManager
from app.models.user import UserRole
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services import meeting_state_manager
from app.utils.security import get_password_hash


def _create_meeting(client: TestClient, cofacilitator_id: str | None = None) -> str:
    payload = {
        "title": "Brainstorm Session",
        "description": "Session focused on creative thinking.",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "agenda_items": ["Intro", "Ideation"],
        "participant_contacts": [],
    }
    if cofacilitator_id:
        payload["co_facilitator_ids"] = [cofacilitator_id]
    response = client.post("/api/meetings/", json=payload)
    assert response.status_code == 200, response.json()
    return response.json()["id"]


def test_brainstorming_idea_submission_broadcast(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    facilitator_user = user_manager_with_admin.add_user(
        first_name="Idea",
        last_name="Facilitator",
        email="idea.facilitator@example.com",
        hashed_password=get_password_hash("IdeaFac1!"),
        role=UserRole.FACILITATOR.value,
        login="idea_facilitator",
    )
    db_session.commit()
    db_session.refresh(facilitator_user)
    meeting_id = _create_meeting(authenticated_client, facilitator_user.user_id)
    meeting = MeetingManager(db_session).get_meeting(meeting_id)
    assert meeting is not None
    activity_id = meeting.agenda_activities[0].activity_id
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "brainstorming",
                "status": "in_progress",
            },
        )
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "brainstorming",
                "status": "in_progress",
            },
        )
    )
    meeting = MeetingManager(db_session).get_meeting(meeting_id)
    assert meeting is not None
    activity_id = meeting.agenda_activities[0].activity_id
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "brainstorming",
                "status": "in_progress",
            },
        )
    )

    with authenticated_client.websocket_connect(
        f"/api/meetings/{meeting_id}/brainstorming/ws"
    ) as websocket:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )
        ack = websocket.receive_json()
        assert ack["type"] == "connection_ack"

        idea_payload = {
            "content": "We should prototype a mobile app",
            "submitted_name": "Lead Facilitator",
        }
        response = authenticated_client.post(
            f"/api/meetings/{meeting_id}/brainstorming/ideas", json=idea_payload
        )
        assert response.status_code == 201, response.json()
        created = response.json()
        assert created["content"] == idea_payload["content"]
        assert created["submitted_name"] == idea_payload["submitted_name"]
        assert isinstance(created["user_color"], str)
        assert created["user_color"].startswith("#")
        assert len(created["user_color"]) == 7
        assert isinstance(created.get("user_avatar_key"), str)
        assert created["user_avatar_key"].startswith("fluent-")
        assert isinstance(created.get("user_avatar_icon_path"), str)
        assert created["user_avatar_icon_path"].startswith("/static/avatars/fluent/icons/")

        broadcast = websocket.receive_json()
        assert broadcast["type"] == "new_idea"
        assert broadcast["payload"]["content"] == idea_payload["content"]
        assert broadcast["payload"]["user_color"] == created["user_color"]
        assert (
            broadcast["payload"]["user_avatar_icon_path"]
            == created["user_avatar_icon_path"]
        )


def test_brainstorming_submit_idempotency_replays_success(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    facilitator_user = user_manager_with_admin.add_user(
        first_name="Idempotent",
        last_name="Facilitator",
        email="idem.facilitator@example.com",
        hashed_password=get_password_hash("IdeaFac1!"),
        role=UserRole.FACILITATOR.value,
        login="idem_facilitator",
    )
    db_session.commit()
    db_session.refresh(facilitator_user)
    meeting_id = _create_meeting(authenticated_client, facilitator_user.user_id)
    meeting = MeetingManager(db_session).get_meeting(meeting_id)
    assert meeting is not None
    activity_id = meeting.agenda_activities[0].activity_id

    headers = {"X-Idempotency-Key": "idem-test-001"}
    payload = {"content": "Idempotency should prevent duplicates."}

    first = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas?activity_id={activity_id}",
        json=payload,
        headers=headers,
    )
    assert first.status_code == 201, first.json()
    second = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas?activity_id={activity_id}",
        json=payload,
        headers=headers,
    )
    assert second.status_code == 201, second.json()
    assert second.json()["id"] == first.json()["id"]

    ideas = authenticated_client.get(
        f"/api/meetings/{meeting_id}/brainstorming/ideas?activity_id={activity_id}"
    )
    assert ideas.status_code == 200
    assert len(ideas.json()) == 1


def test_brainstorming_submit_idempotency_rejects_payload_mismatch(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    facilitator_user = user_manager_with_admin.add_user(
        first_name="Mismatch",
        last_name="Facilitator",
        email="idem.mismatch@example.com",
        hashed_password=get_password_hash("IdeaFac1!"),
        role=UserRole.FACILITATOR.value,
        login="idem_mismatch",
    )
    db_session.commit()
    db_session.refresh(facilitator_user)
    meeting_id = _create_meeting(authenticated_client, facilitator_user.user_id)
    meeting = MeetingManager(db_session).get_meeting(meeting_id)
    assert meeting is not None
    activity_id = meeting.agenda_activities[0].activity_id

    headers = {"X-Idempotency-Key": "idem-test-002"}
    first = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas?activity_id={activity_id}",
        json={"content": "Original content."},
        headers=headers,
    )
    assert first.status_code == 201, first.json()

    second = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas?activity_id={activity_id}",
        json={"content": "Changed content."},
        headers=headers,
    )
    assert second.status_code == 409
    assert "Idempotency key was already used" in second.json().get("detail", "")


def test_brainstorming_ideas_access_control(
    authenticated_client: TestClient,
    client: TestClient,
    db_session,
    user_manager_with_admin: UserManager,
):
    facilitator_user = user_manager_with_admin.add_user(
        first_name="Idea",
        last_name="Facilitator",
        email="idea.facilitator@example.com",
        hashed_password=get_password_hash("IdeaFac1!"),
        role=UserRole.FACILITATOR.value,
        login="idea_facilitator",
    )
    db_session.commit()
    db_session.refresh(facilitator_user)

    meeting_id = _create_meeting(authenticated_client, facilitator_user.user_id)

    idea_resp = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas",
        json={"content": "Encourage asynchronous ideation"},
    )
    assert idea_resp.status_code == 201, idea_resp.json()

    login_response = client.post(
        "/api/auth/token",
        json={"username": facilitator_user.login, "password": "IdeaFac1!"},
    )
    assert login_response.status_code == 200

    facilitator_ideas = client.get(f"/api/meetings/{meeting_id}/brainstorming/ideas")
    assert facilitator_ideas.status_code == 200
    assert len(facilitator_ideas.json()) == 1

    outsider_password = "Part123!"
    outsider_user = user_manager_with_admin.add_user(
        first_name="Outside",
        last_name="Observer",
        email="observer@example.com",
        hashed_password=get_password_hash(outsider_password),
        role=UserRole.PARTICIPANT.value,
        login="observer_user",
    )
    db_session.commit()
    db_session.refresh(outsider_user)

    login_response = client.post(
        "/api/auth/token",
        json={"username": outsider_user.login, "password": outsider_password},
    )
    assert login_response.status_code == 200

    unauthorized_resp = client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas",
        json={"content": "This should not succeed"},
    )
    assert unauthorized_resp.status_code == 403


def test_brainstorming_blocks_participants_outside_live_scope(
    client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    allowed_password = "AllowedIdea1!"
    waiting_password = "WaitingIdea1!"
    allowed_user = user_manager_with_admin.add_user(
        first_name="Allowed",
        last_name="Idea",
        email="allowed.idea@example.com",
        hashed_password=get_password_hash(allowed_password),
        role=UserRole.PARTICIPANT.value,
        login="allowed_idea_user",
    )
    waiting_user = user_manager_with_admin.add_user(
        first_name="Waiting",
        last_name="Idea",
        email="waiting.idea@example.com",
        hashed_password=get_password_hash(waiting_password),
        role=UserRole.PARTICIPANT.value,
        login="waiting_idea_user",
    )
    db_session.commit()
    db_session.refresh(allowed_user)
    db_session.refresh(waiting_user)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Scoped Brainstorming",
            description="Only some participants can join the live round.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[allowed_user.user_id, waiting_user.user_id],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Scoped Ideas",
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "metadata": {
                        "participantScope": "custom",
                        "participantIds": [allowed_user.user_id],
                    },
                    "status": "in_progress",
                    "activeActivities": [
                        {
                            "activityId": activity_id,
                            "tool": "brainstorming",
                            "status": "in_progress",
                            "participantIds": [allowed_user.user_id],
                            "metadata": {
                                "participantScope": "custom",
                                "participantIds": [allowed_user.user_id],
                            },
                        }
                    ],
                },
            )
        )

        login_allowed = client.post(
            "/api/auth/token",
            json={"username": allowed_user.login, "password": allowed_password},
        )
        assert login_allowed.status_code == 200, login_allowed.json()

        allowed_response = client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Scoped idea from allowed user"},
        )
        assert allowed_response.status_code == 201, allowed_response.json()

        client.cookies.clear()
        login_waiting = client.post(
            "/api/auth/token",
            json={"username": waiting_user.login, "password": waiting_password},
        )
        assert login_waiting.status_code == 200, login_waiting.json()

        restricted_response = client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "This should be blocked"},
        )
        assert restricted_response.status_code == 403
        assert "assigned" in restricted_response.json()["detail"]
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_brainstorming_respects_config_limits(
    monkeypatch,
    authenticated_client: TestClient,
    db_session,
):
    from app.routers import brainstorming as brainstorming_router

    monkeypatch.setattr(
        brainstorming_router,
        "BRAINSTORMING_LIMITS",
        {"idea_character_limit": 10, "max_ideas_per_user": 2},
    )

    meeting_id = _create_meeting(authenticated_client)
    meeting = MeetingManager(db_session).get_meeting(meeting_id)
    assert meeting is not None
    activity_id = meeting.agenda_activities[0].activity_id
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "brainstorming",
                "status": "in_progress",
            },
        )
    )

    too_long = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas",
        json={"content": "This idea is definitely too long"},
    )
    assert too_long.status_code == 400
    assert "limited" in too_long.json()["detail"]

    ok_one = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas",
        json={"content": "Idea one"},
    )
    assert ok_one.status_code == 201, ok_one.json()

    ok_two = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas",
        json={"content": "Idea two"},
    )
    assert ok_two.status_code == 201, ok_two.json()

    overflow = authenticated_client.post(
        f"/api/meetings/{meeting_id}/brainstorming/ideas",
        json={"content": "Idea thr"},
    )
    assert overflow.status_code == 400
    assert "submit up to" in overflow.json()["detail"]


def test_brainstorming_ideas_isolated_per_activity(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    """Ideas from different brainstorming activities are isolated."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Multi-Activity Brainstorm",
            description="Two separate brainstorming activities.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=60),
            duration_minutes=60,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Round 1"),
            AgendaActivityCreate(tool_type="brainstorming", title="Round 2"),
        ],
    )
    activity_1_id = meeting.agenda_activities[0].activity_id
    activity_2_id = meeting.agenda_activities[1].activity_id

    try:
        # Start activity 1
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_1_id,
                    "agendaItemId": activity_1_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )

        # Submit ideas to activity 1
        resp_a1 = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Idea for round 1"},
        )
        assert resp_a1.status_code == 201, resp_a1.json()
        assert resp_a1.json()["activity_id"] == activity_1_id

        # Get ideas for activity 1
        get_a1 = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas"
        )
        assert get_a1.status_code == 200
        ideas_a1 = get_a1.json()
        assert len(ideas_a1) == 1
        assert ideas_a1[0]["content"] == "Idea for round 1"

        # Switch to activity 2
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_2_id,
                    "agendaItemId": activity_2_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )

        # Get ideas for activity 2 - should be empty (isolated from activity 1)
        get_a2_before = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas"
        )
        assert get_a2_before.status_code == 200
        assert len(get_a2_before.json()) == 0, "Activity 2 should have no ideas yet"

        # Submit ideas to activity 2
        resp_a2 = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Idea for round 2"},
        )
        assert resp_a2.status_code == 201, resp_a2.json()
        assert resp_a2.json()["activity_id"] == activity_2_id

        # Get ideas for activity 2 - should only have activity 2's idea
        get_a2_after = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas"
        )
        assert get_a2_after.status_code == 200
        ideas_a2 = get_a2_after.json()
        assert len(ideas_a2) == 1
        assert ideas_a2[0]["content"] == "Idea for round 2"

        # Switch back to activity 1 and verify its ideas are still there
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_1_id,
                    "agendaItemId": activity_1_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )
        get_a1_again = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas"
        )
        assert get_a1_again.status_code == 200
        ideas_a1_again = get_a1_again.json()
        assert len(ideas_a1_again) == 1
        assert ideas_a1_again[0]["content"] == "Idea for round 1"

    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_subcomment_submission_when_allowed(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    """Subcomments can be submitted when allow_subcomments is enabled."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Subcomment Test",
            description="Testing subcomments feature.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Subcomment Round",
                config={"allow_subcomments": True},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        # Start activity
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )

        # Submit parent idea
        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Parent idea"},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent_idea = parent_resp.json()
        assert parent_idea["parent_id"] is None

        # Submit subcomment
        subcomment_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "This is a subcomment", "parent_id": parent_idea["id"]},
        )
        assert subcomment_resp.status_code == 201, subcomment_resp.json()
        subcomment = subcomment_resp.json()
        assert subcomment["parent_id"] == parent_idea["id"]
        assert subcomment["content"] == "This is a subcomment"

        # Verify ideas include both
        get_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas"
        )
        assert get_resp.status_code == 200
        ideas = get_resp.json()
        assert len(ideas) == 2

    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_subcomment_rejected_when_disabled(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    """Subcomments are rejected when allow_subcomments is disabled (default)."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="No Subcomment Test",
            description="Subcomments should be blocked.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="No Subcomments",
                config={"allow_subcomments": False},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        # Start activity
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )

        # Submit parent idea
        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Parent idea"},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent_idea = parent_resp.json()

        # Attempt subcomment - should be rejected
        subcomment_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "This should fail", "parent_id": parent_idea["id"]},
        )
        assert subcomment_resp.status_code == 400
        assert "not allowed" in subcomment_resp.json()["detail"]

    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))
