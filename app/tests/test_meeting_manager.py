import asyncio
import pytest
import re
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.data.activity_bundle_manager import ActivityBundleManager
import app.data.meeting_manager as meeting_manager_module
from app.data.meeting_manager import MeetingManager
from app.models.activity_bundle import ActivityBundle
from app.services.meeting_authorization import resolve_meeting_capabilities
from app.services.agenda_strategy import (
    LinearAgendaStrategy,
    PriorActivityReference,
    get_agenda_strategy,
)
from app.services import meeting_state_manager
from app.schemas.meeting import (
    MeetingCreate,
    AgendaActivityCreate,
    AgendaActivityUpdate,
    PublicityType,
)
from app.models.user import User, UserRole
from app.models.meeting import Meeting
from app.models.idea import Idea
from app.models.categorization import (
    CategorizationAuditEvent,
    CategorizationBallot,
    CategorizationBucket,
    CategorizationItem,
)
from app.models.voting import VotingVote
from app.utils.security import get_password_hash  # For creating test users
from datetime import datetime, timedelta, UTC
from app.utils.identifiers import generate_user_id


@pytest.fixture
def meeting_manager_instance(db_session: Session):
    return MeetingManager(db=db_session)


@pytest.fixture
def test_facilitator(db_session: Session) -> User:
    user_id = generate_user_id(db_session, "Facilitator", "Main")
    user = User(
        user_id=user_id,
        email="facilitator.m@example.com",
        login="facilitator_main",
        hashed_password=get_password_hash("FacilitatorPass1!"),
        first_name="Facilitator",
        last_name="Main",
        role=UserRole.FACILITATOR.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def co_facilitator(db_session: Session) -> User:
    user_id = generate_user_id(db_session, "Co", "Facilitator")
    user = User(
        user_id=user_id,
        email="cofacilitator.m@example.com",
        login="facilitator_co",
        hashed_password=get_password_hash("CoFacilitatorPass1!"),
        first_name="Co",
        last_name="Facilitator",
        role=UserRole.FACILITATOR.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def other_user(db_session: Session) -> User:
    user_id = generate_user_id(db_session, "Participant", "One")
    user = User(
        user_id=user_id,
        email="participant.m@example.com",
        login="participant_one",
        hashed_password=get_password_hash("ParticipantPass1!"),
        first_name="Participant",
        last_name="One",
        role=UserRole.PARTICIPANT.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_temp_user(
    db_session: Session,
    first: str,
    last: str,
    login: str,
    role: UserRole = UserRole.PARTICIPANT,
) -> User:
    user_id = generate_user_id(db_session, first, last)
    user = User(
        user_id=user_id,
        email=f"{login}@example.com",
        login=login,
        hashed_password=get_password_hash("TempPass1!"),
        first_name=first,
        last_name=last,
        role=role.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _assert_linear_agenda_strategy_parity(
    db_session: Session,
    meeting: Meeting,
) -> None:
    strategy = get_agenda_strategy(meeting)
    assert isinstance(strategy, LinearAgendaStrategy)

    direct_agenda = sorted(meeting.agenda_activities, key=lambda item: item.order_index)
    strategy_agenda = strategy.list_agenda(meeting)
    assert [item.activity_id for item in strategy_agenda] == [
        item.activity_id for item in direct_agenda
    ]

    for index, activity in enumerate(direct_agenda):
        expected_prior = direct_agenda[index - 1] if index else None
        actual_resolution = strategy.resolve_prior_activity(
            meeting,
            PriorActivityReference.for_consumer(activity),
        )
        actual_prior = actual_resolution.activity if actual_resolution else None
        assert (actual_prior.activity_id if actual_prior else None) == (
            expected_prior.activity_id if expected_prior else None
        )
        if expected_prior is not None:
            explicit_resolution = strategy.resolve_prior_activity(
                meeting,
                PriorActivityReference(
                    consumer_activity_id=activity.activity_id,
                    donor_activity_id=expected_prior.activity_id,
                    logical_step_id="linear-parity",
                    round_index=1,
                ),
            )
            assert explicit_resolution is not None
            assert explicit_resolution.activity.activity_id == expected_prior.activity_id
            assert explicit_resolution.logical_step_id == "linear-parity"
            assert explicit_resolution.round_index == 1

    if not direct_agenda:
        expected_complete = True
    else:
        latest_activity = direct_agenda[-1]
        expected_complete = (
            db_session.query(ActivityBundle.id)
            .filter(
                ActivityBundle.meeting_id == meeting.meeting_id,
                ActivityBundle.activity_id == latest_activity.activity_id,
                ActivityBundle.kind == "output",
            )
            .first()
            is not None
        )
    assert strategy.is_complete(meeting) is expected_complete


def test_resolve_meeting_capabilities_for_all_phase1_postures(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    other_user: User,
):
    """Gravy Parachute: the canonical backend capability model derives all meeting authority from role, ownership, and roster membership only."""
    roster_facilitator = _create_temp_user(
        db_session,
        "Roster",
        "Facilitator",
        "roster_facilitator",
        role=UserRole.FACILITATOR,
    )
    off_roster_facilitator = _create_temp_user(
        db_session,
        "Off",
        "Roster",
        "off_roster_facilitator",
        role=UserRole.FACILITATOR,
    )
    admin_user = _create_temp_user(
        db_session,
        "Admin",
        "Power",
        "admin_power",
        role=UserRole.ADMIN,
    )
    outsider = _create_temp_user(
        db_session,
        "Outside",
        "Viewer",
        "outside_viewer",
        role=UserRole.PARTICIPANT,
    )

    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Capability Matrix Meeting",
        description="Validate the canonical capability model",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[other_user.user_id, roster_facilitator.user_id],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Kickoff")],
    )
    assert meeting is not None

    owner_caps = resolve_meeting_capabilities(meeting, test_facilitator)
    assert owner_caps["is_owner"] is True
    assert owner_caps["is_facilitator"] is True
    assert owner_caps["can_manage"] is True
    assert owner_caps["can_edit_meeting"] is True
    assert owner_caps["can_manage_roster"] is True
    assert owner_caps["can_control_activity"] is True
    assert owner_caps["can_manage_activity_roster"] is True
    assert owner_caps["can_delete"] is True

    admin_caps = resolve_meeting_capabilities(meeting, admin_user)
    assert admin_caps["is_admin"] is True
    assert admin_caps["is_facilitator"] is True
    assert admin_caps["can_view"] is True
    assert admin_caps["can_manage"] is True
    assert admin_caps["can_delete"] is True

    roster_facilitator_caps = resolve_meeting_capabilities(meeting, roster_facilitator)
    assert roster_facilitator_caps["has_facilitator_role"] is True
    assert roster_facilitator_caps["is_roster_participant"] is True
    assert roster_facilitator_caps["is_facilitator"] is True
    assert roster_facilitator_caps["can_manage"] is True
    assert roster_facilitator_caps["can_delete"] is False

    participant_caps = resolve_meeting_capabilities(meeting, other_user)
    assert participant_caps["is_roster_participant"] is True
    assert participant_caps["is_facilitator"] is False
    assert participant_caps["can_view"] is True
    assert participant_caps["can_manage"] is False
    assert participant_caps["can_edit_meeting"] is False

    off_roster_caps = resolve_meeting_capabilities(meeting, off_roster_facilitator)
    assert off_roster_caps["has_facilitator_role"] is True
    assert off_roster_caps["is_roster_participant"] is False
    assert off_roster_caps["is_facilitator"] is False
    assert off_roster_caps["can_view"] is False
    assert off_roster_caps["can_manage"] is False

    outsider_caps = resolve_meeting_capabilities(meeting, outsider)
    assert outsider_caps["can_view"] is False
    assert outsider_caps["can_manage"] is False
    assert outsider_caps["can_delete"] is False

    anonymous_caps = resolve_meeting_capabilities(meeting, None)
    assert anonymous_caps["can_view"] is False
    assert anonymous_caps["can_manage"] is False
    assert anonymous_caps["can_delete"] is False


def test_phase4_step2_removes_persistent_facilitator_orm_model():
    """Noodle Catapult: the active ORM no longer exposes persisted facilitator assignments."""
    import app.models as registered_models
    from app.models.meeting import Meeting
    from app.models.user import User

    assert not hasattr(registered_models, "MeetingFacilitator")
    assert not hasattr(Meeting, "facilitator_links")
    assert not hasattr(Meeting, "facilitators")
    assert not hasattr(User, "facilitator_links")
    assert not hasattr(User, "facilitated_meetings")
    assert "meeting_facilitators" not in Meeting.metadata.tables


def test_phase4_step3_removes_facilitator_runtime_dependencies():
    """Noodle Catapult: runtime and boot code no longer manage facilitator rows."""
    runtime_paths = [
        Path(__file__).resolve().parents[1] / "data" / "meeting_manager.py",
        Path(__file__).resolve().parents[1] / "main.py",
        Path(__file__).resolve().parents[1] / "utils" / "identifiers.py",
        Path(__file__).resolve().parents[1] / "routers" / "pages.py",
    ]
    forbidden_markers = [
        "meeting_facilitators_table",
        "generate_facilitator_id",
        "_ensure_facilitator_assignment",
        "_should_auto_facilitate",
        "_collect_facilitator_assignments",
        "facilitated_meetings",
    ]

    combined_runtime = "\n".join(
        path.read_text(encoding="utf-8") for path in runtime_paths
    )
    for marker in forbidden_markers:
        assert marker not in combined_runtime


def test_phase4_step4_prunes_legacy_facilitator_assumptions_from_active_code():
    """Noodle Catapult: active code must not read removed facilitator persistence fields."""
    active_paths = [
        Path(__file__).resolve().parents[1] / "data" / "data_access.py",
        Path(__file__).resolve().parents[1] / "schemas" / "meeting.py",
    ]
    forbidden_markers = [
        'meeting.get("facilitator_user_ids"',
        "facilitator_links",
        "getattr(item, \"facilitator_id\"",
    ]

    combined_active_code = "\n".join(
        path.read_text(encoding="utf-8") for path in active_paths
    )
    for marker in forbidden_markers:
        assert marker not in combined_active_code


def test_add_meeting(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    other_user: User,
    co_facilitator: User,
):
    meeting_data_dict = {
        "title": "Test Meeting Alpha",
        "description": "This is a test meeting for addition.",
        "start_time": datetime.now(UTC) + timedelta(days=1),
        # 'duration_minutes' is in MeetingManager.create_meeting but not MeetingCreate schema in meeting.py
        # Let's assume it should be part of the schema or the manager handles its absence.
        # For MeetingManager.add_meeting, it uses .get('start_time') etc from a dict.
    }
    # The add_meeting method expects a dictionary, not a Pydantic model
    # and also participant_ids separately
    participant_ids_list = [other_user.user_id]

    created_meeting = meeting_manager_instance.add_meeting(
        meeting_data=meeting_data_dict,
        facilitator_id=test_facilitator.user_id,
        participant_ids=participant_ids_list,
        co_facilitator_ids=[co_facilitator.user_id],
    )
    assert created_meeting is not None
    assert created_meeting.meeting_id is not None
    assert created_meeting.title == meeting_data_dict["title"]
    assert created_meeting.owner_id == test_facilitator.user_id
    participant_user_ids = {
        participant.user_id for participant in created_meeting.participants
    }
    assert participant_user_ids == {other_user.user_id, co_facilitator.user_id}
    assert re.match(r"^MTG\d{8}-[0-9A-Z]{4}$", created_meeting.meeting_id)
    co_facilitator_caps = resolve_meeting_capabilities(created_meeting, co_facilitator)
    assert co_facilitator_caps["can_manage"] is True


def test_create_meeting_assigns_agenda_activities(
    meeting_manager_instance: MeetingManager,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Agenda Enabled Meeting",
        description="Test agenda creation",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )

    agenda_items = [
        AgendaActivityCreate(tool_type="brainstorming", title="Warm ups"),
        AgendaActivityCreate(tool_type="voting", title="Priorities"),
    ]

    created_meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=agenda_items,
    )

    assert created_meeting is not None
    assert len(created_meeting.agenda_activities) == 2
    activity_ids = [
        activity.activity_id for activity in created_meeting.agenda_activities
    ]
    assert "-BRAINS-" in activity_ids[0]
    assert "-RANKVT-" in activity_ids[1]
    for activity in created_meeting.agenda_activities:
        assert activity.tool_config_id.startswith(
            f"TL-{activity.activity_id}"
        )


@pytest.mark.asyncio
async def test_linear_agenda_strategy_matches_direct_order_index_walks(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    mocker,
):
    """Convergent Yak: LinearAgendaStrategy parity survives explicit donor requests."""
    mocker.patch(
        "app.data.meeting_manager.meeting_state_manager.snapshot",
        return_value={"currentActivity": None},
    )
    bundle_manager = ActivityBundleManager(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=1)

    def create_meeting(title: str, agenda_items: list[AgendaActivityCreate]) -> Meeting:
        meeting = meeting_manager_instance.create_meeting(
            MeetingCreate(
                title=title,
                description="Strategy parity fixture",
                start_time=start_time,
                end_time=start_time + timedelta(minutes=45),
                duration_minutes=45,
                publicity=PublicityType.PUBLIC,
                owner_id=test_facilitator.user_id,
                participant_ids=[],
                additional_facilitator_ids=[],
            ),
            facilitator_id=test_facilitator.user_id,
            agenda_items=agenda_items,
        )
        assert meeting is not None
        return meeting

    single = create_meeting(
        "Single Activity Strategy Parity",
        [AgendaActivityCreate(tool_type="brainstorming", title="Only")],
    )
    _assert_linear_agenda_strategy_parity(db_session, single)
    bundle_manager.finalize_output_bundle(
        single.meeting_id,
        single.agenda_activities[0].activity_id,
        [{"content": "single output"}],
    )
    db_session.refresh(single)
    _assert_linear_agenda_strategy_parity(db_session, single)

    two_activity = create_meeting(
        "Two Activity Strategy Parity",
        [
            AgendaActivityCreate(tool_type="brainstorming", title="First"),
            AgendaActivityCreate(tool_type="voting", title="Second"),
        ],
    )
    bundle_manager.finalize_output_bundle(
        two_activity.meeting_id,
        two_activity.agenda_activities[0].activity_id,
        [{"content": "prior only"}],
    )
    db_session.refresh(two_activity)
    _assert_linear_agenda_strategy_parity(db_session, two_activity)
    bundle_manager.finalize_output_bundle(
        two_activity.meeting_id,
        two_activity.agenda_activities[-1].activity_id,
        [{"content": "final output"}],
    )
    db_session.refresh(two_activity)
    _assert_linear_agenda_strategy_parity(db_session, two_activity)

    delete_readd = create_meeting(
        "Delete Readd Strategy Parity",
        [
            AgendaActivityCreate(tool_type="brainstorming", title="Original"),
            AgendaActivityCreate(tool_type="voting", title="Delete Me"),
        ],
    )
    deleted_id = delete_readd.agenda_activities[-1].activity_id
    await meeting_manager_instance.delete_agenda_activity(
        delete_readd.meeting_id,
        deleted_id,
    )
    replacement = meeting_manager_instance.add_agenda_activity(
        delete_readd.meeting_id,
        AgendaActivityCreate(tool_type="categorization", title="Replacement"),
    )
    assert replacement.activity_id != deleted_id
    db_session.refresh(delete_readd)
    _assert_linear_agenda_strategy_parity(db_session, delete_readd)

    reordered = create_meeting(
        "Reordered Strategy Parity",
        [
            AgendaActivityCreate(tool_type="brainstorming", title="One"),
            AgendaActivityCreate(tool_type="voting", title="Two"),
            AgendaActivityCreate(tool_type="categorization", title="Three"),
        ],
    )
    new_order = [
        reordered.agenda_activities[2].activity_id,
        reordered.agenda_activities[0].activity_id,
        reordered.agenda_activities[1].activity_id,
    ]
    meeting_manager_instance.reorder_agenda_activities(reordered.meeting_id, new_order)
    db_session.refresh(reordered)
    _assert_linear_agenda_strategy_parity(db_session, reordered)

    strategy = get_agenda_strategy(reordered)
    created = strategy.create_activity(
        reordered,
        AgendaActivityCreate(tool_type="brainstorming", title="Strategy Created"),
        meeting_manager_instance,
    )
    list_strategy_spy = mocker.spy(meeting_manager_module, "get_agenda_strategy")
    listed = meeting_manager_instance.list_agenda(reordered.meeting_id)
    assert created.activity_id in {
        activity.activity_id
        for activity in listed
    }
    assert list_strategy_spy.call_count == 1


def test_mid_meeting_creation_safe_via_manager_and_strategy(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    """Smug Otter: running meetings admit manager and strategy activity insertion safely."""
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting = meeting_manager_instance.create_meeting(
        MeetingCreate(
            title="Mid Meeting Creation Safety",
            description="Validate running agenda insertion paths",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=60),
            duration_minutes=60,
            publicity=PublicityType.PUBLIC,
            owner_id=test_facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Open"),
            AgendaActivityCreate(tool_type="categorization", title="Group"),
        ],
    )
    assert meeting is not None
    running_activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": running_activity_id,
                    "agendaItemId": running_activity_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )

        manager_created = meeting_manager_instance.add_agenda_activity(
            meeting.meeting_id,
            AgendaActivityCreate(
                tool_type="voting",
                title="Inserted by Manager",
                order_index=2,
            ),
        )
        assert manager_created.activity_id.startswith(f"{meeting.meeting_id}-RANKVT-")

        strategy = get_agenda_strategy(meeting)
        strategy_created = strategy.create_activity(
            meeting,
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Inserted by Strategy",
                order_index=3,
            ),
            meeting_manager_instance,
        )
        assert strategy_created.activity_id.startswith(f"{meeting.meeting_id}-BRAINS-")
        assert strategy_created.activity_id != running_activity_id

        refreshed = meeting_manager_instance.get_meeting(meeting.meeting_id)
        assert refreshed is not None
        agenda = get_agenda_strategy(refreshed).list_agenda(refreshed)
        assert [activity.order_index for activity in agenda] == [1, 2, 3, 4]
        assert [activity.title for activity in agenda] == [
            "Open",
            "Inserted by Manager",
            "Inserted by Strategy",
            "Group",
        ]
        assert len({activity.activity_id for activity in agenda}) == 4
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_get_meeting(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    meeting_data = {
        "title": "Test Meeting Beta",
        "description": "Meeting to be fetched.",
    }
    added_meeting = meeting_manager_instance.add_meeting(
        meeting_data, test_facilitator.user_id
    )
    assert added_meeting is not None

    fetched_meeting = meeting_manager_instance.get_meeting(added_meeting.meeting_id)
    assert fetched_meeting is not None
    assert fetched_meeting.meeting_id == added_meeting.meeting_id
    assert fetched_meeting.title == "Test Meeting Beta"
    assert fetched_meeting.owner_id == test_facilitator.user_id


def test_activity_ids_unique_across_meetings(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    meeting_payload = MeetingCreate(
        title="Meeting One",
        description="First meeting",
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    agenda_items = [
        AgendaActivityCreate(tool_type="brainstorming", title="Brainstorm"),
        AgendaActivityCreate(tool_type="voting", title="Vote"),
    ]
    meeting_one = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=agenda_items,
    )

    meeting_payload_two = MeetingCreate(
        title="Meeting Two",
        description="Second meeting",
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting_two = meeting_manager_instance.create_meeting(
        meeting_payload_two,
        facilitator_id=test_facilitator.user_id,
        agenda_items=agenda_items,
    )

    ids_one = {activity.activity_id for activity in meeting_one.agenda_activities}
    ids_two = {activity.activity_id for activity in meeting_two.agenda_activities}
    assert ids_one.isdisjoint(ids_two)
    for activity in meeting_one.agenda_activities:
        assert activity.activity_id.startswith(f"{meeting_one.meeting_id}-")
    for activity in meeting_two.agenda_activities:
        assert activity.activity_id.startswith(f"{meeting_two.meeting_id}-")
    tool_ids = {
        activity.tool_config_id
        for activity in meeting_one.agenda_activities + meeting_two.agenda_activities
    }
    assert len(tool_ids) == len(meeting_one.agenda_activities) + len(
        meeting_two.agenda_activities
    )


def test_update_meeting(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    other_user: User,
    co_facilitator: User,
):
    original_data = {
        "title": "Original Title Gamma",
        "description": "Original description.",
    }
    meeting_to_update = meeting_manager_instance.add_meeting(
        original_data, test_facilitator.user_id
    )
    assert meeting_to_update is not None

    updated_data_payload = {
        "title": "Updated Title Gamma",
        "description": "Updated description for Gamma.",
        "status": "paused",
        "participant_ids": [other_user.user_id],  # Test updating participants
        "facilitator_ids": [test_facilitator.user_id, co_facilitator.user_id],
    }
    updated_meeting = meeting_manager_instance.update_meeting(
        meeting_to_update.meeting_id, updated_data_payload
    )
    assert updated_meeting is not None
    assert updated_meeting.title == "Updated Title Gamma"
    assert updated_meeting.description == "Updated description for Gamma."
    assert updated_meeting.status == "paused"
    assert len(updated_meeting.participants) == 1
    assert updated_meeting.participants[0].user_id == other_user.user_id
    assert resolve_meeting_capabilities(updated_meeting, test_facilitator)["can_manage"]
    assert not resolve_meeting_capabilities(updated_meeting, co_facilitator)[
        "can_manage"
    ]


@pytest.mark.asyncio
async def test_add_update_delete_agenda_activity(
    meeting_manager_instance: MeetingManager,
    test_facilitator: User,
    mocker,
):
    # Mock meeting_state_manager.snapshot for this test since delete_agenda_activity is async
    mocker.patch(
        "app.data.meeting_manager.meeting_state_manager.snapshot",
        return_value={"currentActivity": None},
    )

    start_time = datetime.now(UTC) + timedelta(hours=2)
    meeting_payload = MeetingCreate(
        title="Agenda CRUD Meeting",
        description="Testing agenda mutations",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )

    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Opening")],
    )
    assert meeting is not None

    new_activity = meeting_manager_instance.add_agenda_activity(
        meeting.meeting_id,
        AgendaActivityCreate(tool_type="voting", title="Final vote"),
    )
    assert new_activity.tool_type == "voting"

    updated_activity = meeting_manager_instance.update_agenda_activity(
        meeting.meeting_id,
        new_activity.activity_id,
        AgendaActivityUpdate(order_index=1, config={"max_votes": 6}),
    )
    assert updated_activity.order_index == 1
    assert updated_activity.config["max_votes"] == 6

    await meeting_manager_instance.delete_agenda_activity(
        meeting.meeting_id, new_activity.activity_id
    )
    refreshed = meeting_manager_instance.get_meeting(meeting.meeting_id)
    assert refreshed is not None
    assert all(
        act.activity_id != new_activity.activity_id
        for act in refreshed.agenda_activities
    )


def test_update_categorization_config_reseeds_runtime_state(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=2)
    meeting_payload = MeetingCreate(
        title="Categorization Config Reseed",
        description="Ensure settings changes rebuild categorization runtime state",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Categorize",
                config={"items": ["Original idea"], "buckets": ["Old bucket"]},
            )
        ],
    )
    activity = meeting.agenda_activities[0]

    updated = meeting_manager_instance.update_agenda_activity(
        meeting.meeting_id,
        activity.activity_id,
        AgendaActivityUpdate(
            config={
                "items": ["New idea A", "New idea B"],
                "buckets": ["New bucket"],
            }
        ),
    )
    assert updated is not None

    seeded_items = (
        db_session.query(CategorizationItem)
        .filter(
            CategorizationItem.meeting_id == meeting.meeting_id,
            CategorizationItem.activity_id == activity.activity_id,
        )
        .all()
    )
    assert len(seeded_items) == 2
    assert {row.content for row in seeded_items} == {"New idea A", "New idea B"}

    seeded_buckets = (
        db_session.query(CategorizationBucket)
        .filter(
            CategorizationBucket.meeting_id == meeting.meeting_id,
            CategorizationBucket.activity_id == activity.activity_id,
        )
        .all()
    )
    titles = {row.title for row in seeded_buckets}
    assert "Unsorted Ideas" in titles
    assert "New bucket" in titles


def test_update_voting_config_blocks_locked_fields_after_votes(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Voting Lock Policy",
        description="Lock selected voting fields once votes exist",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="voting",
                title="Dot Vote",
                config={"options": ["Alpha", "Beta"], "max_votes": 2},
            )
        ],
    )
    activity = meeting.agenda_activities[0]
    db_session.add(
        VotingVote(
            meeting_id=meeting.meeting_id,
            activity_id=activity.activity_id,
            user_id=test_facilitator.user_id,
            option_id=f"{activity.activity_id}:alpha",
            option_label="Alpha",
            weight=1,
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        meeting_manager_instance.update_agenda_activity(
            meeting.meeting_id,
            activity.activity_id,
            AgendaActivityUpdate(config={"options": ["Alpha", "Beta", "Gamma"]}),
        )
    assert exc.value.status_code == 409
    assert "options" in str(exc.value.detail)

    with pytest.raises(HTTPException) as exc:
        meeting_manager_instance.update_agenda_activity(
            meeting.meeting_id,
            activity.activity_id,
            AgendaActivityUpdate(config={"max_votes": 3}),
        )
    assert exc.value.status_code == 409
    assert "max_votes" in str(exc.value.detail)

    updated = meeting_manager_instance.update_agenda_activity(
        meeting.meeting_id,
        activity.activity_id,
        AgendaActivityUpdate(config={"show_results_immediately": True}),
    )
    assert updated.config["show_results_immediately"] is True


def test_update_brainstorming_config_allows_changes_with_live_data(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Brainstorming Lock Policy",
        description="Brainstorming config should remain editable with live ideas",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Ideas")],
    )
    activity = meeting.agenda_activities[0]
    db_session.add(
        Idea(
            meeting_id=meeting.meeting_id,
            activity_id=activity.activity_id,
            user_id=test_facilitator.user_id,
            content="Live idea",
        )
    )
    db_session.commit()

    updated = meeting_manager_instance.update_agenda_activity(
        meeting.meeting_id,
        activity.activity_id,
        AgendaActivityUpdate(config={"allow_subcomments": True}),
    )
    assert updated.config["allow_subcomments"] is True


def test_update_categorization_seed_fields_blocked_after_activity_started(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=2)
    meeting_payload = MeetingCreate(
        title="Categorization Seed Lock Policy",
        description="Seed fields should lock once categorization has live data",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Categorize",
                config={"items": ["Original"], "buckets": ["Existing"]},
            )
        ],
    )
    activity = meeting.agenda_activities[0]
    activity.stopped_at = datetime.now(UTC)
    db_session.add(activity)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        meeting_manager_instance.update_agenda_activity(
            meeting.meeting_id,
            activity.activity_id,
            AgendaActivityUpdate(config={"items": ["Updated item"]}),
        )
    assert exc.value.status_code == 409
    assert "items" in str(exc.value.detail)

    updated = meeting_manager_instance.update_agenda_activity(
        meeting.meeting_id,
        activity.activity_id,
        AgendaActivityUpdate(config={"allow_unsorted_submission": False}),
    )
    assert updated.config["allow_unsorted_submission"] is False


def test_update_categorization_parallel_fields_blocked_after_submitted_ballots(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=2)
    meeting_payload = MeetingCreate(
        title="Categorization Ballot Lock Policy",
        description="Parallel interpretation fields lock after ballot submit",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Categorize",
                config={"mode": "PARALLEL_BALLOT", "items": ["Alpha"], "buckets": ["One"]},
            )
        ],
    )
    activity = meeting.agenda_activities[0]
    db_session.add(
        CategorizationBallot(
            meeting_id=meeting.meeting_id,
            activity_id=activity.activity_id,
            user_id=test_facilitator.user_id,
            item_key=f"{activity.activity_id}:item-1",
            category_id="UNSORTED",
            submitted=True,
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        meeting_manager_instance.update_agenda_activity(
            meeting.meeting_id,
            activity.activity_id,
            AgendaActivityUpdate(config={"agreement_threshold": 0.8}),
        )
    assert exc.value.status_code == 409
    assert "agreement_threshold" in str(exc.value.detail)


def test_update_rank_order_config_rejects_object_placeholder_lines(
    meeting_manager_instance: MeetingManager,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Rank Config Validation",
        description="Reject object placeholder lines in rank-order ideas.",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="rank_order_voting",
                title="Rank",
                config={"ideas": ["Idea A"]},
            )
        ],
    )
    activity = meeting.agenda_activities[0]

    with pytest.raises(HTTPException) as exc:
        meeting_manager_instance.update_agenda_activity(
            meeting.meeting_id,
            activity.activity_id,
            AgendaActivityUpdate(config={"ideas": ["[object Object]", "Idea B"]}),
        )
    assert exc.value.status_code == 422
    assert "object" in str(exc.value.detail).lower()


def test_add_voting_config_rejects_object_placeholder_lines(
    meeting_manager_instance: MeetingManager,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Voting Config Validation",
        description="Reject object placeholder lines in voting options.",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Ideas")],
    )

    with pytest.raises(HTTPException) as exc:
        meeting_manager_instance.add_agenda_activity(
            meeting.meeting_id,
            AgendaActivityCreate(
                tool_type="voting",
                title="Vote",
                config={"options": ["[object Object]", "Idea B"]},
            ),
        )
    assert exc.value.status_code == 422
    assert "object" in str(exc.value.detail).lower()


def test_update_meeting_configuration_seeds_categorization_with_items_only(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=2)
    meeting_payload = MeetingCreate(
        title="Categorization Config Save",
        description="Settings save path should seed categorization state",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Ideas")],
    )

    updated = meeting_manager_instance.update_meeting_configuration(
        meeting.meeting_id,
        title=meeting.title,
        description=meeting.description,
        start_time=meeting.started_at,
        end_time=meeting.end_time,
        participant_ids=[],
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Ideas"),
            AgendaActivityCreate(
                tool_type="categorization",
                title="Bucketing - Facilitator",
                config={"items": ["Alpha", "Beta"], "buckets": []},
            ),
        ],
    )
    assert updated is not None

    cat_activity = next(
        item for item in updated.agenda_activities if item.tool_type == "categorization"
    )
    seeded_items = (
        db_session.query(CategorizationItem)
        .filter(
            CategorizationItem.meeting_id == meeting.meeting_id,
            CategorizationItem.activity_id == cat_activity.activity_id,
        )
        .all()
    )
    assert len(seeded_items) == 2
    assert {row.content for row in seeded_items} == {"Alpha", "Beta"}

    seeded_buckets = (
        db_session.query(CategorizationBucket)
        .filter(
            CategorizationBucket.meeting_id == meeting.meeting_id,
            CategorizationBucket.activity_id == cat_activity.activity_id,
        )
        .all()
    )
    assert len(seeded_buckets) == 1
    assert seeded_buckets[0].category_id == "UNSORTED"


def test_get_activity_data_flags_includes_categorization_runtime_changes(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=2)
    meeting_payload = MeetingCreate(
        title="Categorization Data Flag",
        description="Categorization edits should mark activity as having data",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=45),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Categorize",
                config={"items": [], "buckets": []},
            )
        ],
    )
    activity = meeting.agenda_activities[0]
    db_session.add(
        CategorizationAuditEvent(
            meeting_id=meeting.meeting_id,
            activity_id=activity.activity_id,
            actor_user_id=test_facilitator.user_id,
            event_type="bucket_created",
            payload={"category_id": f"{activity.activity_id}:bucket-1"},
        )
    )
    db_session.commit()

    flags = meeting_manager_instance.get_activity_data_flags(meeting.meeting_id)
    assert flags.get(activity.activity_id) is True


def test_activity_participant_scope_management(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    other_user: User,
):
    """Noodle Catapult: activity participant scoping stays roster-bound after facilitator persistence removal."""
    second_participant_id = generate_user_id(db_session, "Participant", "Two")
    second_participant = User(
        user_id=second_participant_id,
        email="participant.two@example.com",
        login="participant_two",
        hashed_password=get_password_hash("ParticipantPass2!"),
        first_name="Participant",
        last_name="Two",
        role=UserRole.PARTICIPANT.value,
    )
    db_session.add(second_participant)
    db_session.commit()

    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Roster Control Meeting",
        description="Validate activity participant scope",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[other_user.user_id, second_participant.user_id],
        additional_facilitator_ids=[],
    )

    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="voting", title="Prioritise"),
        ],
    )
    assert meeting is not None
    activity = meeting.agenda_activities[0]

    updated = meeting_manager_instance.set_activity_participants(
        meeting.meeting_id,
        activity.activity_id,
        [other_user.user_id],
    )
    assert updated.config.get("participant_ids") == [other_user.user_id]

    refreshed = meeting_manager_instance.get_meeting(meeting.meeting_id)
    assert refreshed is not None
    reloaded_activity = next(
        act
        for act in refreshed.agenda_activities
        if act.activity_id == activity.activity_id
    )
    assert reloaded_activity.config.get("participant_ids") == [other_user.user_id]

    meeting_manager_instance.remove_participant(meeting.meeting_id, other_user.user_id)
    after_removal = meeting_manager_instance.get_meeting(meeting.meeting_id)
    assert after_removal is not None
    remaining_activity = next(
        act
        for act in after_removal.agenda_activities
        if act.activity_id == activity.activity_id
    )
    assert "participant_ids" not in remaining_activity.config


def test_activity_participant_scope_rejects_unknown_users(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    other_user: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Invalid Scope Meeting",
        description="Ensure non-roster users cannot be assigned",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[other_user.user_id],
        additional_facilitator_ids=[],
    )

    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Ideate"),
        ],
    )
    assert meeting is not None
    activity = meeting.agenda_activities[0]

    rogue_user_id = generate_user_id(db_session, "Rogue", "Participant")

    with pytest.raises(HTTPException) as exc_info:
        meeting_manager_instance.set_activity_participants(
            meeting.meeting_id,
            activity.activity_id,
            [rogue_user_id],
        )
    assert exc_info.value.status_code == 400


def test_set_activity_participants_empty_list_pops_key(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    client,
    test_facilitator: User,
    other_user: User,
):
    """Roster Rodeo / Payload Polka — empty participant lists collapse to inherit-all and the router reports mode='all'."""
    second_participant = _create_temp_user(
        db_session, "Participant", "Three", "participant_three"
    )
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Empty List Pops Key",
        description="Ensure empty iterable falls back to inherit-all",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[other_user.user_id, second_participant.user_id],
        additional_facilitator_ids=[],
    )

    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="voting", title="Prioritise")],
    )
    activity = meeting.agenda_activities[0]

    meeting_manager_instance.set_activity_participants(
        meeting.meeting_id,
        activity.activity_id,
        [other_user.user_id],
    )

    updated = meeting_manager_instance.set_activity_participants(
        meeting.meeting_id,
        activity.activity_id,
        [],
    )
    assert "participant_ids" not in updated.config

    login_response = client.post(
        "/api/auth/token",
        json={"username": test_facilitator.login, "password": "FacilitatorPass1!"},
    )
    assert login_response.status_code == 200

    response = client.get(
        f"/api/meetings/{meeting.meeting_id}/agenda/{activity.activity_id}/participants"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "all"
    assert payload["participant_ids"] == []


def test_remove_meeting_participant_pops_empty_custom(
    meeting_manager_instance: MeetingManager,
    test_facilitator: User,
    other_user: User,
):
    """Roster Rodeo / Payload Polka — pruning the last scoped participant pops the config key instead of persisting an empty list."""
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Prune Empty Custom",
        description="Ensure removal fallback pops scoped config key",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[other_user.user_id],
        additional_facilitator_ids=[],
    )

    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Ideate")],
    )
    activity = meeting.agenda_activities[0]

    meeting_manager_instance.set_activity_participants(
        meeting.meeting_id,
        activity.activity_id,
        [other_user.user_id],
    )
    meeting_manager_instance.remove_participant(meeting.meeting_id, other_user.user_id)

    refreshed = meeting_manager_instance.get_meeting(meeting.meeting_id)
    assert refreshed is not None
    updated_activity = next(
        act
        for act in refreshed.agenda_activities
        if act.activity_id == activity.activity_id
    )
    assert "participant_ids" not in updated_activity.config


def test_bulk_update_participants_adds_and_removes_users(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    other_user: User,
):
    """Muffin Tractor: bulk roster updates remain valid under the collapsed contract without auto-granting meeting authority."""
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Bulk Update Meeting",
        description="Exercises the aggregated participant update flow",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=40),
        duration_minutes=40,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[other_user.user_id],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Discuss"),
        ],
    )
    assert meeting is not None
    activity_id = meeting.agenda_activities[0].activity_id

    # Seed users that will be added through the bulk operation
    roster_one = _create_temp_user(db_session, "Bulk", "One", "bulk_one")
    roster_two = _create_temp_user(db_session, "Bulk", "Two", "bulk_two")

    # Existing activity scope targets the original participant
    meeting_manager_instance.set_activity_participants(
        meeting.meeting_id,
        activity_id,
        [other_user.user_id],
    )

    updated_meeting, summary = meeting_manager_instance.bulk_update_participants(
        meeting.meeting_id,
        add_user_ids=[roster_one.user_id, roster_two.user_id],
        remove_user_ids=[other_user.user_id],
    )

    assert updated_meeting is not None
    assert summary["added_user_ids"] == [roster_one.user_id, roster_two.user_id]
    assert summary["removed_user_ids"] == [other_user.user_id]
    assert summary["missing_user_ids"] == []

    refreshed = meeting_manager_instance.get_meeting(meeting.meeting_id)
    assert refreshed is not None
    participant_ids = {p.user_id for p in refreshed.participants}
    assert participant_ids == {roster_one.user_id, roster_two.user_id}

    activity = next(
        act for act in refreshed.agenda_activities if act.activity_id == activity_id
    )
    # Since the scoped participant was removed, the activity should fall back to meeting-wide mode
    assert "participant_ids" not in activity.config


def test_reorder_agenda_activities(
    meeting_manager_instance: MeetingManager,
    test_facilitator: User,
):
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Reorder Meeting",
        description="Testing agenda reordering",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=60),
        duration_minutes=60,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )

    agenda_items = [
        AgendaActivityCreate(
            tool_type="brainstorming", title="Activity 1", order_index=1
        ),
        AgendaActivityCreate(tool_type="voting", title="Activity 2", order_index=2),
        AgendaActivityCreate(
            tool_type="brainstorming", title="Activity 3", order_index=3
        ),
    ]

    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=agenda_items,
    )
    assert meeting is not None
    assert len(meeting.agenda_activities) == 3
    assert meeting.agenda_activities[0].title == "Activity 1"
    assert meeting.agenda_activities[1].title == "Activity 2"
    assert meeting.agenda_activities[2].title == "Activity 3"

    # Reorder activities: 3, 1, 2
    new_order_ids = [
        meeting.agenda_activities[2].activity_id,  # Activity 3
        meeting.agenda_activities[0].activity_id,  # Activity 1
        meeting.agenda_activities[1].activity_id,  # Activity 2
    ]

    reordered_agenda = meeting_manager_instance.reorder_agenda_activities(
        meeting.meeting_id,
        new_order_ids,
    )

    assert len(reordered_agenda) == 3
    assert reordered_agenda[0].activity_id == new_order_ids[0]
    assert reordered_agenda[0].title == "Activity 3"
    assert reordered_agenda[0].order_index == 1

    assert reordered_agenda[1].activity_id == new_order_ids[1]
    assert reordered_agenda[1].title == "Activity 1"
    assert reordered_agenda[1].order_index == 2

    assert reordered_agenda[2].activity_id == new_order_ids[2]
    assert reordered_agenda[2].title == "Activity 2"
    assert reordered_agenda[2].order_index == 3

    # Test with invalid activity_id list length
    with pytest.raises(HTTPException) as exc_info:
        meeting_manager_instance.reorder_agenda_activities(
            meeting.meeting_id, [new_order_ids[0]]
        )
    assert exc_info.value.status_code == 400
    assert (
        "Provided activity_ids list size does not match existing agenda size."
        in exc_info.value.detail
    )

    # Test with unknown activity_id
    with pytest.raises(HTTPException) as exc_info:
        meeting_manager_instance.reorder_agenda_activities(
            meeting.meeting_id, [new_order_ids[0], new_order_ids[1], "UNKNOWN_ID"]
        )
    assert exc_info.value.status_code == 404
    assert (
        "Activity with ID 'UNKNOWN_ID' not found in meeting agenda."
        in exc_info.value.detail
    )


@pytest.mark.asyncio  # Mark as async because delete_agenda_activity is now async
async def test_cannot_delete_active_agenda_activity(
    meeting_manager_instance: MeetingManager,
    test_facilitator: User,
    mocker,
):
    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Active Delete Meeting",
        description="Test deleting active agenda",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=60),
        duration_minutes=60,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[],
        additional_facilitator_ids=[],
    )

    agenda_items = [
        AgendaActivityCreate(tool_type="brainstorming", title="Active Activity"),
        AgendaActivityCreate(tool_type="voting", title="Inactive Activity"),
    ]

    meeting = meeting_manager_instance.create_meeting(
        meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=agenda_items,
    )
    assert meeting is not None
    active_activity_id = meeting.agenda_activities[0].activity_id
    inactive_activity_id = meeting.agenda_activities[1].activity_id

    # Mock meeting_state_manager.snapshot to simulate an active activity
    mocker.patch(
        "app.data.meeting_manager.meeting_state_manager.snapshot",
        return_value={"currentActivity": active_activity_id, "status": "in_progress"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await meeting_manager_instance.delete_agenda_activity(
            meeting.meeting_id, active_activity_id
        )
    assert exc_info.value.status_code == 400
    assert (
        "Cannot delete an active activity. Please stop it first."
        in exc_info.value.detail
    )

    # Test deleting an inactive activity (should succeed)
    mocker.patch(
        "app.data.meeting_manager.meeting_state_manager.snapshot",
        return_value={
            "currentActivity": None
        },  # No activity active, so inactive can be deleted
    )
    # The actual delete_agenda_activity uses the current state of the meeting in the db
    # We need to explicitly refresh the meeting object from the database so that its agenda_activities
    # list is updated before trying to delete the inactive activity.
    meeting_manager_instance.db.refresh(meeting)
    await meeting_manager_instance.delete_agenda_activity(
        meeting.meeting_id, inactive_activity_id
    )
    refreshed_meeting = meeting_manager_instance.get_meeting(meeting.meeting_id)
    assert refreshed_meeting is not None
    assert all(
        a.activity_id != inactive_activity_id
        for a in refreshed_meeting.agenda_activities
    )

    # Test deleting the originally active activity after it's no longer current
    mocker.patch(
        "app.data.meeting_manager.meeting_state_manager.snapshot",
        return_value={"currentActivity": None},  # No activity active
    )
    # Again, refresh the meeting object to get the latest agenda_activities
    meeting_manager_instance.db.refresh(meeting)
    await meeting_manager_instance.delete_agenda_activity(
        meeting.meeting_id, active_activity_id
    )
    refreshed_meeting = meeting_manager_instance.get_meeting(meeting.meeting_id)
    assert refreshed_meeting is not None
    assert all(
        a.activity_id != active_activity_id for a in refreshed_meeting.agenda_activities
    )


@pytest.mark.asyncio
async def test_check_participant_collisions_with_multiple_active(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    mocker,
):
    participant_one = _create_temp_user(
        db_session, "Overlap", "One", "overlap_one"
    )
    participant_two = _create_temp_user(
        db_session, "Overlap", "Two", "overlap_two"
    )

    start_time = datetime.now(UTC) + timedelta(hours=1)
    meeting_payload = MeetingCreate(
        title="Collision Meeting",
        description="Test participant exclusivity across concurrent activities",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=test_facilitator.user_id,
        participant_ids=[participant_one.user_id, participant_two.user_id],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager_instance.create_meeting(
        meeting_data=meeting_payload,
        facilitator_id=test_facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="A1"),
            AgendaActivityCreate(tool_type="voting", title="A2"),
        ],
    )
    active_activity_id = meeting.agenda_activities[0].activity_id
    next_activity_id = meeting.agenda_activities[1].activity_id

    mocker.patch(
        "app.data.meeting_manager.meeting_state_manager.snapshot",
        return_value={
            "activeActivities": [
                {
                    "activityId": active_activity_id,
                    "tool": "brainstorming",
                    "status": "in_progress",
                    "participantIds": [participant_one.user_id],
                }
            ]
        },
    )

    conflict = await meeting_manager_instance.check_participant_collisions(
        meeting.meeting_id,
        next_activity_id,
        {participant_one.user_id, participant_two.user_id},
    )
    assert conflict == []

    # Non-overlapping participants should pass
    no_conflict = await meeting_manager_instance.check_participant_collisions(
        meeting.meeting_id,
        next_activity_id,
        {participant_two.user_id},
    )
    assert no_conflict == []


def test_update_meeting_owner_updates_owner_link_only(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    co_facilitator: User,
):
    meeting_to_update = meeting_manager_instance.add_meeting(
        {"title": "Primary Swap", "description": "Swap owner authority"},
        test_facilitator.user_id,
    )
    assert meeting_to_update is not None
    assert meeting_to_update.owner_id == test_facilitator.user_id
    assert resolve_meeting_capabilities(meeting_to_update, test_facilitator)[
        "is_owner"
    ]

    updated_meeting = meeting_manager_instance.update_meeting(
        meeting_to_update.meeting_id,
        {"owner_id": co_facilitator.user_id},
    )

    assert updated_meeting is not None
    assert updated_meeting.owner_id == co_facilitator.user_id
    assert resolve_meeting_capabilities(updated_meeting, co_facilitator)["is_owner"]
    assert not resolve_meeting_capabilities(updated_meeting, test_facilitator)[
        "is_owner"
    ]


def test_archive_meeting(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    meeting_data = {
        "title": "Meeting to Archive Delta",
        "description": "Active meeting.",
    }
    meeting_to_archive = meeting_manager_instance.add_meeting(
        meeting_data, test_facilitator.user_id
    )
    assert meeting_to_archive is not None
    assert (
        meeting_to_archive.status != "completed"
    )  # Or 'archived' depending on definition

    archived_meeting = meeting_manager_instance.archive_meeting(
        meeting_to_archive.meeting_id
    )
    assert archived_meeting is not None
    # The `archive_meeting` method in MeetingManager sets status to 'archived'.
    # Let's use the string 'archived' as per the manager's implementation.
    assert archived_meeting.status == "archived"


def test_delete_meeting_permanently(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    meeting_data = {
        "title": "Meeting to Delete Epsilon",
        "description": "Ephemeral meeting.",
    }
    meeting_to_delete = meeting_manager_instance.add_meeting(
        meeting_data, test_facilitator.user_id
    )
    assert meeting_to_delete is not None
    meeting_id_to_delete = meeting_to_delete.meeting_id

    delete_result = meeting_manager_instance.delete_meeting_permanently(
        meeting_id_to_delete
    )
    assert delete_result is True

    deleted_meeting_check = (
        db_session.query(Meeting)
        .filter(Meeting.meeting_id == meeting_id_to_delete)
        .first()
    )
    assert deleted_meeting_check is None


def test_get_all_meetings_and_counts(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
):
    meeting_manager_instance.add_meeting(
        {"title": "M1", "description": "D1"}, test_facilitator.user_id
    )
    meeting_manager_instance.add_meeting(
        {"title": "M2", "description": "D2", "status": "active"},
        test_facilitator.user_id,
    )
    m3 = meeting_manager_instance.add_meeting(
        {"title": "M3", "description": "D3"}, test_facilitator.user_id
    )
    meeting_manager_instance.archive_meeting(m3.meeting_id)  # Archive one

    all_meetings = meeting_manager_instance.get_all_meetings()
    assert len(all_meetings) == 3

    active_meetings = meeting_manager_instance.get_active_meetings()
    # Default status is 'active' for add_meeting if not specified, archive_meeting sets 'archived'
    # Based on current add_meeting, status defaults to 'active'.
    # M1 -> active, M2 -> active, M3 -> archived.
    # So, active_meetings should be 2.
    assert len(active_meetings) == 2
    assert all(m.status == "active" or m.status == "paused" for m in active_meetings)

    archived_meetings = meeting_manager_instance.get_archived_meetings()
    assert len(archived_meetings) == 1
    assert archived_meetings[0].status == "archived"

    meeting_count = meeting_manager_instance.get_meeting_count()
    assert meeting_count == 3


def test_dashboard_meetings_scoped_and_classified(
    meeting_manager_instance: MeetingManager,
    db_session: Session,
    test_facilitator: User,
    other_user: User,
):
    now = datetime.now(UTC)

    never_started_meeting = meeting_manager_instance.add_meeting(
        {
            "title": "Never Started Session",
            "description": "No participant activity yet",
        },
        test_facilitator.user_id,
        participant_ids=[other_user.user_id],
    )

    not_running_meeting = meeting_manager_instance.add_meeting(
        {
            "title": "Not Running Workshop",
            "description": "Ideas submitted but no activities started",
        },
        test_facilitator.user_id,
        participant_ids=[other_user.user_id],
    )

    running_meeting = meeting_manager_instance.add_meeting(
        {
            "title": "Running Retrospective",
            "description": "Currently active meeting",
        },
        test_facilitator.user_id,
        participant_ids=[other_user.user_id],
    )

    stopped_meeting = meeting_manager_instance.add_meeting(
        {
            "title": "Stopped Huddle",
            "description": "Activities ran previously",
            "end_time": now - timedelta(hours=1),
        },
        test_facilitator.user_id,
        participant_ids=[other_user.user_id],
    )

    assert never_started_meeting is not None
    assert not_running_meeting is not None
    assert running_meeting is not None
    assert stopped_meeting is not None

    db_session.add(
        Idea(
            content="Initial idea",
            meeting_id=not_running_meeting.meeting_id,
            user_id=other_user.user_id,
        )
    )
    db_session.commit()

    running_activity = meeting_manager_instance.add_agenda_activity(
        running_meeting.meeting_id,
        AgendaActivityCreate(tool_type="brainstorming", title="Brainstorming", config={}),
    )
    running_activity.started_at = now
    db_session.commit()

    stopped_activity = meeting_manager_instance.add_agenda_activity(
        stopped_meeting.meeting_id,
        AgendaActivityCreate(tool_type="voting", title="Voting", config={}),
    )
    stopped_activity.stopped_at = now
    stopped_activity.elapsed_duration = 120
    db_session.commit()

    payload = meeting_manager_instance.get_dashboard_meetings(user=other_user)

    assert payload["summary"]["total"] == 4
    assert all(item["meeting_authorities"] for item in payload["items"])
    assert all(item["authority_names"] for item in payload["items"])
    assert all("viewer_capabilities" in item for item in payload["items"])
    assert all(item["viewer_capabilities"]["can_view"] is True for item in payload["items"])
    assert all(item["viewer_capabilities"]["can_manage"] is False for item in payload["items"])
    assert all(item["viewer_capabilities"]["can_delete"] is False for item in payload["items"])
    assert all(item["owner"]["user_id"] for item in payload["items"])
    assert all(
        any(a["user_id"] == test_facilitator.user_id for a in item["meeting_authorities"])
        for item in payload["items"]
    )
    assert all("facilitators" not in item for item in payload["items"])
    assert all("facilitator_names" not in item for item in payload["items"])

    facilitator_payload = meeting_manager_instance.get_dashboard_meetings(
        user=test_facilitator,
        role_scope="facilitator",
    )
    assert facilitator_payload["summary"]["total"] == 4
    assert all(
        item["viewer_capabilities"]["can_manage"] is True
        for item in facilitator_payload["items"]
    )
    assert all(
        any(a["user_id"] == test_facilitator.user_id for a in item["meeting_authorities"])
        for item in facilitator_payload["items"]
    )
    statuses = {item["title"]: item["status"] for item in payload["items"]}
    assert statuses["Never Started Session"] == "never_started"
    assert statuses["Not Running Workshop"] == "not_running"
    assert statuses["Running Retrospective"] == "running"
    assert statuses["Stopped Huddle"] == "stopped"

    quick_actions = next(
        item["quick_actions"]
        for item in payload["items"]
        if item["title"] == "Stopped Huddle"
    )
    assert quick_actions["view_results"].endswith("/export")

    notifications = payload["summary"]["notifications"]
    assert notifications["total_unread"] >= 3
