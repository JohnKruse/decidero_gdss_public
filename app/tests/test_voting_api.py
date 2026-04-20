import asyncio
import os
from datetime import datetime, timedelta, UTC

from fastapi.testclient import TestClient

from app.data.meeting_manager import MeetingManager
from app.data.user_manager import UserManager
from app.models.user import UserRole
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services import meeting_state_manager
from app.services.voting_manager import VotingManager
from app.utils.security import get_password_hash


def _create_voting_meeting(db_session, owner, participant_ids=None):
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=1)
    config = {
        "options": ["Improve UX", "Scale infra", "Launch beta"],
        "max_votes": 2,
        "show_results_immediately": False,
    }
    agenda = [
        AgendaActivityCreate(
            tool_type="voting",
            title="Select priorities",
            instructions="Vote for the ideas you feel most strongly about.",
            config=config,
        )
    ]
    meeting_payload = MeetingCreate(
        title="Voting Session",
        description="Prioritization workshop",
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


def test_voting_options_visible_to_facilitator(
    authenticated_client: TestClient, user_manager_with_admin: UserManager, db_session
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    meeting, activity_id = _create_voting_meeting(db_session, admin_user)

    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "voting",
                "status": "in_progress",
            },
        )
    )

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": activity_id},
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["activity_id"] == activity_id
    assert payload["show_results"] is False
    assert payload["can_view_results"] is True
    assert payload["remaining_votes"] == payload["max_votes"] == 2
    option_labels = [option["label"] for option in payload["options"]]
    assert option_labels == ["Improve UX", "Scale infra", "Launch beta"]
    assert all(option["votes"] is not None for option in payload["options"])
    assert payload["is_active"] is True


def test_voting_allows_facilitator_view_when_inactive(
    authenticated_client: TestClient, user_manager_with_admin: UserManager, db_session
):
    """
    Facilitators should be able to view the voting configuration (options) even if
    the activity is not yet started, but they should NOT be able to cast votes.
    """
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    meeting, activity_id = _create_voting_meeting(db_session, admin_user)

    try:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))

        # View Options -> Should be Allowed (200)
        response = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/voting/options",
            params={"activity_id": activity_id},
        )
        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["activity_id"] == activity_id
        assert payload["show_results"] is False  # Defaults
        assert payload["can_view_results"] is True
        assert payload["is_active"] is False     # Explicitly verifies logic for UI

        # Cast Vote -> Should be Forbidden (403) - activity is inactive
        option_id = (
            VotingManager(db_session)
            ._extract_options(meeting.agenda_activities[0])[0]
            .option_id
        )
        vote_response = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/voting/votes",
            json={"activity_id": activity_id, "option_id": option_id},
        )
        assert vote_response.status_code == 403
        assert "open for voting" in vote_response.json()["detail"].lower()
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_participant_voting_enforces_limits(
    client: TestClient, user_manager_with_admin: UserManager, db_session
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    participant_password = "VoteUser1!"
    participant = user_manager_with_admin.add_user(
        first_name="Vote",
        last_name="Participant",
        email="vote.participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="vote_participant",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting, activity_id = _create_voting_meeting(
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
                "currentTool": "voting",
                "status": "in_progress",
            },
        )
    )

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.json()

    options_response = client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": activity_id},
    )
    assert options_response.status_code == 200, options_response.json()
    options_payload = options_response.json()
    assert options_payload["show_results"] is False
    first_option = options_payload["options"][0]["option_id"]
    second_option = options_payload["options"][1]["option_id"]

    vote_one = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": first_option},
    )
    assert vote_one.status_code == 200, vote_one.json()
    assert vote_one.json()["remaining_votes"] == 1

    vote_two = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": second_option},
    )
    assert vote_two.status_code == 200, vote_two.json()
    assert vote_two.json()["remaining_votes"] == 0

    vote_three = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": second_option},
    )
    assert vote_three.status_code == 400
    assert "limit" in vote_three.json()["detail"].lower()


def test_participant_can_view_results_after_submit_when_retract_disabled(
    client: TestClient, user_manager_with_admin: UserManager, db_session
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    participant_password = "VoteUserLocked1!"
    participant = user_manager_with_admin.add_user(
        first_name="Locked",
        last_name="Participant",
        email="locked.participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="locked_participant",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=1)
    agenda = [
        AgendaActivityCreate(
            tool_type="voting",
            title="Locked vote",
            instructions="Vote once without retracting.",
            config={
                "options": ["One", "Two"],
                "max_votes": 2,
                "allow_retract": False,
                "show_results_immediately": False,
            },
        )
    ]
    meeting_payload = MeetingCreate(
        title="Voting Locked Session",
        description="Prioritization workshop",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=60),
        duration_minutes=60,
        publicity=PublicityType.PRIVATE,
        owner_id=admin_user.user_id,
        participant_ids=[participant.user_id],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager.create_meeting(
        meeting_payload,
        facilitator_id=admin_user.user_id,
        agenda_items=agenda,
    )
    activity_id = meeting.agenda_activities[0].activity_id

    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "voting",
                "status": "in_progress",
            },
        )
    )

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.json()

    options_before = client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": activity_id},
    )
    assert options_before.status_code == 200, options_before.json()
    before_payload = options_before.json()
    assert before_payload["can_view_results"] is False
    assert all(option["votes"] is None for option in before_payload["options"])

    option_id = before_payload["options"][0]["option_id"]
    vote_response = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": option_id},
    )
    assert vote_response.status_code == 200, vote_response.json()
    vote_payload = vote_response.json()
    assert vote_payload["can_view_results"] is True
    assert any(option["votes"] is not None for option in vote_payload["options"])

    options_after = client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": activity_id},
    )
    assert options_after.status_code == 200, options_after.json()
    after_payload = options_after.json()
    assert after_payload["can_view_results"] is True
    assert any(option["votes"] is not None for option in after_payload["options"])


def test_participant_can_retract_vote_when_enabled(
    client: TestClient, user_manager_with_admin: UserManager, db_session
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    participant_password = "VoteUser2!"
    participant = user_manager_with_admin.add_user(
        first_name="Retract",
        last_name="Participant",
        email="retract.participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="retract_participant",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=1)
    agenda = [
        AgendaActivityCreate(
            tool_type="voting",
            title="Select priorities",
            instructions="Vote for the ideas you feel most strongly about.",
            config={
                "options": ["One", "Two"],
                "max_votes": 2,
                "allow_retract": True,
                "show_results_immediately": False,
            },
        )
    ]
    meeting_payload = MeetingCreate(
        title="Voting Retract Session",
        description="Prioritization workshop",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=60),
        duration_minutes=60,
        publicity=PublicityType.PRIVATE,
        owner_id=admin_user.user_id,
        participant_ids=[participant.user_id],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager.create_meeting(
        meeting_payload,
        facilitator_id=admin_user.user_id,
        agenda_items=agenda,
    )
    activity_id = meeting.agenda_activities[0].activity_id

    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "voting",
                "status": "in_progress",
            },
        )
    )

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.json()

    options_response = client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": activity_id},
    )
    assert options_response.status_code == 200, options_response.json()
    options_payload = options_response.json()
    assert options_payload["allow_retract"] is True
    option_id = options_payload["options"][0]["option_id"]

    vote_one = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": option_id, "action": "add"},
    )
    assert vote_one.status_code == 200, vote_one.json()
    assert vote_one.json()["remaining_votes"] == 1

    retract_one = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": option_id, "action": "retract"},
    )
    assert retract_one.status_code == 200, retract_one.json()
    assert retract_one.json()["remaining_votes"] == 2

    retract_two = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": option_id, "action": "retract"},
    )
    assert retract_two.status_code == 400
    assert "retract" in retract_two.json()["detail"].lower()


def test_voting_enforces_per_option_limit(
    client: TestClient, user_manager_with_admin: UserManager, db_session
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    participant_password = "VoteUser3!"
    participant = user_manager_with_admin.add_user(
        first_name="Cap",
        last_name="Participant",
        email="cap.participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="cap_participant",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=1)
    agenda = [
        AgendaActivityCreate(
            tool_type="voting",
            title="Select priorities",
            instructions="Vote for the ideas you feel most strongly about.",
            config={
                "options": ["One", "Two"],
                "max_votes": 3,
                "max_votes_per_option": 1,
                "show_results_immediately": False,
            },
        )
    ]
    meeting_payload = MeetingCreate(
        title="Voting Cap Session",
        description="Prioritization workshop",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=60),
        duration_minutes=60,
        publicity=PublicityType.PRIVATE,
        owner_id=admin_user.user_id,
        participant_ids=[participant.user_id],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager.create_meeting(
        meeting_payload,
        facilitator_id=admin_user.user_id,
        agenda_items=agenda,
    )
    activity_id = meeting.agenda_activities[0].activity_id

    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "voting",
                "status": "in_progress",
            },
        )
    )

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.json()

    options_response = client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": activity_id},
    )
    assert options_response.status_code == 200, options_response.json()
    options_payload = options_response.json()
    assert options_payload["max_votes_per_option"] == 1
    option_id = options_payload["options"][0]["option_id"]

    vote_one = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": option_id},
    )
    assert vote_one.status_code == 200, vote_one.json()

    vote_two = client.post(
        f"/api/meetings/{meeting.meeting_id}/voting/votes",
        json={"activity_id": activity_id, "option_id": option_id},
    )
    assert vote_two.status_code == 400
    assert "option" in vote_two.json()["detail"].lower()


def test_voting_blocks_participants_outside_activity_scope(
    client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    allowed_user = user_manager_with_admin.add_user(
        first_name="Allowed",
        last_name="Participant",
        email="allowed.participant@example.com",
        hashed_password=get_password_hash("AllowedPass1!"),
        role=UserRole.PARTICIPANT.value,
        login="allowed_participant",
    )
    excluded_user = user_manager_with_admin.add_user(
        first_name="Excluded",
        last_name="Participant",
        email="excluded.participant@example.com",
        hashed_password=get_password_hash("ExcludedPass1!"),
        role=UserRole.PARTICIPANT.value,
        login="excluded_participant",
    )
    db_session.commit()
    db_session.refresh(allowed_user)
    db_session.refresh(excluded_user)

    meeting, activity_id = _create_voting_meeting(
        db_session,
        admin_user,
        participant_ids=[allowed_user.user_id, excluded_user.user_id],
    )

    meeting_manager = MeetingManager(db_session)
    meeting_manager.set_activity_participants(
        meeting.meeting_id,
        activity_id,
        [allowed_user.user_id],
    )

    login_res = client.post(
        "/api/auth/token",
        json={"username": excluded_user.login, "password": "ExcludedPass1!"},
    )
    assert login_res.status_code == 200, login_res.json()

    options_res = client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": activity_id},
    )
    assert options_res.status_code == 403
    assert "assigned" in options_res.json()["detail"].lower()


def test_voting_respects_live_scope_metadata_without_config(
    client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    allowed_password = "VoteAllowed1!"
    waiting_password = "VoteWaiting1!"
    allowed_user = user_manager_with_admin.add_user(
        first_name="Allowed",
        last_name="Vote",
        email="allowed.vote@example.com",
        hashed_password=get_password_hash(allowed_password),
        role=UserRole.PARTICIPANT.value,
        login="allowed_vote_user",
    )
    waiting_user = user_manager_with_admin.add_user(
        first_name="Waiting",
        last_name="Vote",
        email="waiting.vote@example.com",
        hashed_password=get_password_hash(waiting_password),
        role=UserRole.PARTICIPANT.value,
        login="waiting_vote_user",
    )
    db_session.commit()
    db_session.refresh(allowed_user)
    db_session.refresh(waiting_user)

    meeting, activity_id = _create_voting_meeting(
        db_session,
        facilitator,
        participant_ids=[allowed_user.user_id, waiting_user.user_id],
    )

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "voting",
                    "metadata": {
                        "participantScope": "custom",
                        "participantIds": [allowed_user.user_id],
                    },
                    "status": "in_progress",
                },
            )
        )

        login_allowed = client.post(
            "/api/auth/token",
            json={"username": allowed_user.login, "password": allowed_password},
        )
        assert login_allowed.status_code == 200, login_allowed.json()

        allowed_options = client.get(
            f"/api/meetings/{meeting.meeting_id}/voting/options",
            params={"activity_id": activity_id},
        )
        assert allowed_options.status_code == 200, allowed_options.json()

        client.cookies.clear()
        login_waiting = client.post(
            "/api/auth/token",
            json={"username": waiting_user.login, "password": waiting_password},
        )
        assert login_waiting.status_code == 200, login_waiting.json()

        waiting_options = client.get(
            f"/api/meetings/{meeting.meeting_id}/voting/options",
            params={"activity_id": activity_id},
        )
        assert waiting_options.status_code == 403
        assert "assigned" in waiting_options.json()["detail"].lower()
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))
