import asyncio
import os
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.data.meeting_manager import MeetingManager
from app.data.user_manager import UserManager
from app.models.user import UserRole
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services import meeting_state_manager
from app.utils.security import get_password_hash


def _create_rank_order_meeting(db_session, owner, participant_ids=None, config_override=None):
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=1)
    config = {
        "ideas": ["Improve UX", "Scale infra", "Launch beta"],
        "show_results_immediately": False,
        "allow_reset": True,
        "randomize_order": True,
    }
    config.update(config_override or {})
    agenda = [
        AgendaActivityCreate(
            tool_type="rank_order_voting",
            title="Rank priorities",
            instructions="Rank ideas from strongest to weakest.",
            config=config,
        )
    ]
    meeting_payload = MeetingCreate(
        title="Rank Order Session",
        description="Ranking workshop",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=60),
        duration_minutes=60,
        publicity=PublicityType.PRIVATE,
        owner_id=owner.user_id,
        participant_ids=participant_ids or [],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager.create_meeting(
        meeting_payload,
        facilitator_id=owner.user_id,
        agenda_items=agenda,
    )
    return meeting, meeting.agenda_activities[0].activity_id


def test_rank_order_summary_visible_to_facilitator_when_inactive(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    meeting, activity_id = _create_rank_order_meeting(db_session, admin_user)

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/rank-order-voting/summary",
        params={"activity_id": activity_id},
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["activity_id"] == activity_id
    assert payload["is_active"] is False
    assert payload["can_view_results"] is True
    assert len(payload["options"]) == 3


def test_rank_order_submit_and_aggregate_results_for_facilitator(
    client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    participant_password = "RankUser1!"
    participant = user_manager_with_admin.add_user(
        first_name="Rank",
        last_name="Participant",
        email="rank.participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="rank_participant",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting, activity_id = _create_rank_order_meeting(
        db_session,
        admin_user,
        participant_ids=[participant.user_id],
    )

    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "rank_order_voting",
                "status": "in_progress",
                "participants": [participant.user_id],
            },
        )
    )

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.json()

    participant_summary = client.get(
        f"/api/meetings/{meeting.meeting_id}/rank-order-voting/summary",
        params={"activity_id": activity_id},
    )
    assert participant_summary.status_code == 200, participant_summary.json()
    participant_payload = participant_summary.json()
    assert participant_payload["can_view_results"] is False

    option_ids = [entry["option_id"] for entry in participant_payload["options"]]
    submit_response = client.post(
        f"/api/meetings/{meeting.meeting_id}/rank-order-voting/rankings",
        json={"activity_id": activity_id, "ordered_option_ids": option_ids},
    )
    assert submit_response.status_code == 200, submit_response.json()

    admin_login = os.getenv("ADMIN_LOGIN", admin_email.split("@")[0])
    admin_password = os.getenv("ADMIN_PASSWORD", "Admin@123!")
    admin_login_response = client.post(
        "/api/auth/token",
        json={"username": admin_login, "password": admin_password},
    )
    assert admin_login_response.status_code == 200, admin_login_response.json()

    facilitator_summary = client.get(
        f"/api/meetings/{meeting.meeting_id}/rank-order-voting/summary",
        params={"activity_id": activity_id},
    )
    assert facilitator_summary.status_code == 200, facilitator_summary.json()
    payload = facilitator_summary.json()
    assert payload["submission_count"] == 1
    assert payload["active_participant_count"] == 1
    assert payload["can_view_results"] is True
    assert len(payload["results"]) == 3
    top = payload["results"][0]
    assert top["borda_score"] == 2.0
    assert top["avg_rank"] == 1.0


def test_rank_order_reset_honors_allow_reset(
    client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    participant_password = "RankReset1!"
    participant = user_manager_with_admin.add_user(
        first_name="Reset",
        last_name="Participant",
        email="rank.reset@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="rank_reset_user",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting, activity_id = _create_rank_order_meeting(
        db_session,
        admin_user,
        participant_ids=[participant.user_id],
        config_override={"allow_reset": False},
    )

    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "rank_order_voting",
                "status": "in_progress",
            },
        )
    )

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.json()

    summary = client.get(
        f"/api/meetings/{meeting.meeting_id}/rank-order-voting/summary",
        params={"activity_id": activity_id},
    )
    option_ids = [entry["option_id"] for entry in summary.json()["options"]]
    submit = client.post(
        f"/api/meetings/{meeting.meeting_id}/rank-order-voting/rankings",
        json={"activity_id": activity_id, "ordered_option_ids": option_ids},
    )
    assert submit.status_code == 200, submit.json()

    reset = client.post(
        f"/api/meetings/{meeting.meeting_id}/rank-order-voting/reset",
        json={"activity_id": activity_id},
    )
    assert reset.status_code == 400, reset.json()
    assert "disabled" in reset.json()["detail"].lower()


def test_rank_order_empty_config_does_not_break_meeting_payload(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    meeting, activity_id = _create_rank_order_meeting(
        db_session,
        admin_user,
        config_override={"ideas": []},
    )

    summary_resp = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/rank-order-voting/summary",
        params={"activity_id": activity_id},
    )
    assert summary_resp.status_code == 200, summary_resp.json()
    assert summary_resp.json().get("options") == []

    meeting_resp = authenticated_client.get(f"/api/meetings/{meeting.meeting_id}")
    assert meeting_resp.status_code == 200, meeting_resp.json()
    agenda = meeting_resp.json().get("agenda", [])
    rank_activity = next(item for item in agenda if item["activity_id"] == activity_id)
    assert rank_activity.get("transfer_count") == 0
