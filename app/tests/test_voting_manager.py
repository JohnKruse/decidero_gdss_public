from datetime import datetime, timedelta, UTC

import pytest
from fastapi import HTTPException

from app.data.meeting_manager import MeetingManager
from app.data.user_manager import UserManager
from app.models.user import UserRole
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services.voting_manager import VotingManager
from app.tests.conftest import ADMIN_EMAIL_FOR_TEST
from app.utils.security import get_password_hash


def _create_participant(user_manager: UserManager, db_session):
    password = "DotRail1!"
    participant = user_manager.add_user(
        first_name="DotRail",
        last_name="Participant",
        email="dotrail.participant@example.com",
        hashed_password=get_password_hash(password),
        role=UserRole.PARTICIPANT.value,
        login=f"dotrail_participant_{int(datetime.now().timestamp())}",
    )
    db_session.commit()
    db_session.refresh(participant)
    return participant


def _build_voting_meeting(db_session, owner, participant_ids, config):
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=1)
    agenda_items = [
        AgendaActivityCreate(
            tool_type="voting",
            title="Dot-Rail Voting",
            instructions="Distribute your dots to highlight important ideas.",
            config=config,
        )
    ]
    payload = MeetingCreate(
        title="Dot-Rail Session",
        description="Testing dot-rail voting behavior.",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PRIVATE,
        owner_id=owner.user_id,
        participant_ids=participant_ids or [],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager.create_meeting(
        payload,
        facilitator_id=owner.user_id,
        agenda_items=agenda_items,
    )
    return meeting, meeting.agenda_activities[0].activity_id


@pytest.mark.usefixtures("db_session")
def test_build_summary_reports_dot_rail_flags(
    db_session, user_manager_with_admin: UserManager
):
    admin_user = user_manager_with_admin.get_user_by_email(ADMIN_EMAIL_FOR_TEST)
    assert admin_user is not None
    participant = _create_participant(user_manager_with_admin, db_session)
    config = {
        "options": ["Confidence", "Impact"],
        "max_votes": 3,
        "max_votes_per_option": 2,
        "vote_label_singular": "dot",
        "vote_label_plural": "dots",
        "allow_retract": True,
        "show_results_immediately": False,
    }
    meeting, activity_id = _build_voting_meeting(
        db_session, admin_user, [participant.user_id], config
    )
    voting_manager = VotingManager(db_session)

    participant_summary = voting_manager.build_summary(
        meeting, activity_id, participant
    )
    assert participant_summary["remaining_votes"] == 3
    assert participant_summary["max_votes"] == 3
    assert participant_summary["vote_label_singular"] == "dot"
    assert participant_summary["vote_label_plural"] == "dots"
    assert participant_summary["show_results"] is False
    assert participant_summary["can_view_results"] is False
    assert participant_summary["allow_retract"] is True
    assert isinstance(participant_summary["options"], list)
    assert all(option["user_votes"] == 0 for option in participant_summary["options"])

    facilitator_summary = voting_manager.build_summary(
        meeting, activity_id, admin_user, force_results=True
    )
    assert facilitator_summary["show_results"] is False
    assert facilitator_summary["can_view_results"] is True
    assert facilitator_summary["remaining_votes"] == 3


def _option_map(summary):
    return {option["option_id"]: option for option in summary.get("options", [])}


@pytest.mark.usefixtures("db_session")
def test_randomized_participant_order_is_deterministic(
    db_session, user_manager_with_admin: UserManager
):
    admin_user = user_manager_with_admin.get_user_by_email(ADMIN_EMAIL_FOR_TEST)
    assert admin_user is not None
    participant = _create_participant(user_manager_with_admin, db_session)
    config = {
        "options": ["Alpha", "Beta", "Gamma", "Delta"],
        "max_votes": 3,
        "allow_retract": True,
        "show_results_immediately": False,
        "randomize_participant_order": True,
    }
    meeting, activity_id = _build_voting_meeting(
        db_session, admin_user, [participant.user_id], config
    )
    voting_manager = VotingManager(db_session)
    activity = next(
        activity
        for activity in meeting.agenda_activities
        if activity.activity_id == activity_id
    )
    option_ids = [
        option.option_id for option in voting_manager._extract_options(activity)
    ]
    expected_order = sorted(
        option_ids,
        key=lambda option_id: voting_manager._participant_order_key(
            meeting.meeting_id, activity_id, participant.user_id, option_id
        ),
    )

    first_summary = voting_manager.build_summary(meeting, activity_id, participant)
    second_summary = voting_manager.build_summary(meeting, activity_id, participant)
    assert [opt["option_id"] for opt in first_summary["options"]] == expected_order
    assert [opt["option_id"] for opt in second_summary["options"]] == expected_order

    facilitator_summary = voting_manager.build_summary(
        meeting, activity_id, admin_user, force_results=True
    )
    assert [opt["option_id"] for opt in facilitator_summary["options"]] == option_ids


@pytest.mark.usefixtures("db_session")
def test_cast_vote_respects_dot_rail_limits(
    db_session, user_manager_with_admin: UserManager
):
    admin_user = user_manager_with_admin.get_user_by_email(ADMIN_EMAIL_FOR_TEST)
    assert admin_user is not None
    participant = _create_participant(user_manager_with_admin, db_session)
    config = {
        "options": ["Dot A", "Dot B", "Dot C"],
        "max_votes": 3,
        "max_votes_per_option": 2,
        "allow_retract": True,
        "show_results_immediately": False,
    }
    meeting, activity_id = _build_voting_meeting(
        db_session, admin_user, [participant.user_id], config
    )
    voting_manager = VotingManager(db_session)
    initial_summary = voting_manager.build_summary(meeting, activity_id, participant)
    option_ids = [option["option_id"] for option in initial_summary["options"]]
    assert len(option_ids) >= 2
    first_option, second_option = option_ids[:2]

    first_response = voting_manager.cast_vote(
        meeting, activity_id, participant, first_option
    )
    first_map = _option_map(first_response)
    assert first_response["remaining_votes"] == 2
    assert first_map[first_option]["user_votes"] == 1

    second_response = voting_manager.cast_vote(
        meeting, activity_id, participant, first_option
    )
    second_map = _option_map(second_response)
    assert second_response["remaining_votes"] == 1
    assert second_map[first_option]["user_votes"] == 2

    with pytest.raises(HTTPException) as per_option_exc:
        voting_manager.cast_vote(meeting, activity_id, participant, first_option)
    assert "limit" in str(per_option_exc.value.detail).lower()

    third_response = voting_manager.cast_vote(
        meeting, activity_id, participant, second_option
    )
    third_map = _option_map(third_response)
    assert third_response["remaining_votes"] == 0
    assert third_map[second_option]["user_votes"] == 1

    with pytest.raises(HTTPException) as total_exc:
        voting_manager.cast_vote(meeting, activity_id, participant, second_option)
    assert "limit" in str(total_exc.value.detail).lower()


@pytest.mark.usefixtures("db_session")
def test_participant_can_view_results_after_locked_submission(
    db_session, user_manager_with_admin: UserManager
):
    admin_user = user_manager_with_admin.get_user_by_email(ADMIN_EMAIL_FOR_TEST)
    assert admin_user is not None
    participant = _create_participant(user_manager_with_admin, db_session)
    config = {
        "options": ["Dot A", "Dot B"],
        "max_votes": 2,
        "allow_retract": False,
        "show_results_immediately": False,
    }
    meeting, activity_id = _build_voting_meeting(
        db_session, admin_user, [participant.user_id], config
    )
    voting_manager = VotingManager(db_session)

    before = voting_manager.build_summary(meeting, activity_id, participant)
    assert before["can_view_results"] is False
    assert all(option["votes"] is None for option in before["options"])

    option_id = before["options"][0]["option_id"]
    after = voting_manager.cast_vote(meeting, activity_id, participant, option_id)
    assert after["can_view_results"] is True
    assert any(option["votes"] is not None for option in after["options"])
