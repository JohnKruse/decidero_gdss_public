import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app.routers.realtime as realtime_router
from app.services.meeting_state import MeetingStateManager, meeting_state_manager
from app.data.meeting_manager import MeetingManager
from app.data.user_manager import UserManager
from app.schemas.meeting import MeetingCreate, AgendaActivityCreate
from app.services.agenda_strategy import (
    LinearAgendaStrategy,
    OrchestrationEngineStrategy,
    PriorActivityReference,
    get_agenda_strategy,
)
from app.services.orchestration_loader import load_orchestration_data
from app.services.orchestration_realtime import broadcast_engine_agenda_mutation
from app.utils.security import get_password_hash


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_meeting_state_manager_participant_lifecycle():
    manager = MeetingStateManager()
    snapshot = await manager.register_participant("MTG-1234", "conn-1")
    assert "conn-1" in snapshot["participants"]

    renamed = await manager.rename_participant("MTG-1234", "conn-1", "USR-TEST-001")
    assert "USR-TEST-001" in renamed["participants"]
    assert "conn-1" not in renamed["participants"]

    _, patched_snapshot = await manager.apply_patch(
        "MTG-1234",
        {
            "currentActivity": "agenda-1",
            "currentTool": "brainstorm",
            "metadata": {"phase": "ideation"},
            "status": "in_progress",
            "activeActivities": {
                "agenda-1": {
                    "activityId": "agenda-1",
                    "tool": "brainstorm",
                    "status": "in_progress",
                    "metadata": {"phase": "ideation"},
                    "elapsedTime": 0,
                }
            },
        },
    )
    assert patched_snapshot["currentActivity"] == "agenda-1"
    assert patched_snapshot["metadata"]["phase"] == "ideation"
    assert patched_snapshot["status"] == "in_progress"
    assert patched_snapshot["activeActivities"]
    assert patched_snapshot["activeActivities"][0]["activityId"] == "agenda-1"
    assert patched_snapshot["updatedAt"]
    # Ensure ISO 8601 format
    datetime.fromisoformat(patched_snapshot["updatedAt"])

    await manager.apply_patch(
        "MTG-1234",
        {
            "currentActivity": None,
            "currentTool": None,
            "status": None,
            "activeActivities": {"agenda-1": None},
        },
    )
    removed = await manager.unregister_participant("MTG-1234", "USR-TEST-001")
    assert removed is None  # State is cleared when empty and no additional data


def test_meeting_state_websocket_flow(db_session, client: TestClient, mocker):
    """Smug Otter: realtime initial state preserves agenda behavior through AgendaStrategy."""
    # Create a minimal meeting so the websocket endpoint accepts the connection
    user_manager = UserManager()
    user_manager.set_db(db_session)
    owner = user_manager.add_user(
        first_name="State",
        last_name="Owner",
        email="stateowner@example.com",
        login="stateowner",
        role="facilitator",
        hashed_password=get_password_hash("OwnerPass1!"),
    )

    meeting_manager = MeetingManager(db_session)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="State Test Meeting",
            description="Test meeting for websocket state flow",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_minutes=30,
            owner_id=owner.user_id,
            participant_ids=[],
        ),
        facilitator_id=owner.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Intro")],
    )
    meeting_id = meeting.meeting_id

    try:
        strategy_spy = mocker.spy(realtime_router, "get_agenda_strategy")
        with client.websocket_connect(f"/ws/meetings/{meeting_id}") as websocket:
            ack = websocket.receive_json()
            assert ack["type"] == "connection_ack"
            payload = ack["payload"]
            assert payload["meetingId"] == meeting_id
            assert (
                payload["state"]["agenda"][0]["activity_id"]
                == meeting.agenda_activities[0].activity_id
            )
            assert payload["state"]["participants"] == [payload["userId"]]
            assert "status" in payload["state"]
            assert payload["state"]["updatedAt"]
            assert strategy_spy.call_count == 1

            websocket.send_json(
                {"type": "identify", "payload": {"userId": "USR-WS-001"}}
            )
            identified = websocket.receive_json()
            assert identified["type"] == "participant_identified"
            assert identified["payload"]["userId"] == "USR-WS-001"
            assert "USR-WS-001" in identified["payload"]["state"]["participants"]
            assert identified["payload"]["state"]["updatedAt"]

            websocket.send_json(
                {
                    "type": "state_update",
                    "payload": {
                        "currentActivity": "agenda-item-42",
                        "currentTool": "brainstorming",
                        "metadata": {"step": "intro"},
                    },
                }
            )
            state_msg = websocket.receive_json()
            assert state_msg["type"] == "meeting_state"
            state_payload = state_msg["payload"]
            assert state_payload["currentActivity"] == "agenda-item-42"
            assert state_payload["currentTool"] == "brainstorming"
            assert state_payload["metadata"]["step"] == "intro"
            assert "USR-WS-001" in state_payload["participants"]
            assert state_payload["updatedAt"]
    finally:
        asyncio.run(meeting_state_manager.reset(meeting_id))


def _seed_orchestration_meeting(db_session, title: str = "Engine Realtime"):
    user_manager = UserManager()
    user_manager.set_db(db_session)
    owner = user_manager.add_user(
        first_name="Engine",
        last_name="Owner",
        email=f"{title.lower().replace(' ', '.')}@example.com",
        login=title.lower().replace(" ", "_"),
        role="facilitator",
        hashed_password=get_password_hash("OwnerPass1!"),
    )
    meeting_manager = MeetingManager(db_session)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title=title,
            description="Phase 5 engine realtime witness",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_minutes=30,
            owner_id=owner.user_id,
            participant_ids=[],
        ),
        facilitator_id=owner.user_id,
        agenda_items=[],
    )
    return owner, meeting_manager, meeting


@pytest.mark.anyio("asyncio")
async def test_engine_activity_mutation_reuses_agenda_and_state_broadcasts(
    db_session, mocker
):
    """Loquacious Pelican: engine-created activities reuse existing realtime envelopes."""
    owner, meeting_manager, meeting = _seed_orchestration_meeting(
        db_session, "Engine Activity Broadcast"
    )
    doc = load_orchestration_data({
        "name": "engine-activity-broadcast",
        "version": "1",
        "author": "phase5",
        "citation": "Loquacious Pelican",
        "metadata": {
            "thinklets": ["t"],
            "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 10},
            "notes": "Loquacious Pelican activity mutation fixture",
        },
        "steps": [
            {"type": "activity", "tool_type": "brainstorming", "title": "Engine Seed"}
        ],
    })
    strategy = OrchestrationEngineStrategy(doc)
    activity = strategy.create_activity(meeting, None, None)
    broadcast_mock = mocker.patch(
        "app.services.orchestration_realtime.websocket_manager.broadcast"
    )

    try:
        result = await broadcast_engine_agenda_mutation(
            meeting_id=meeting.meeting_id,
            initiator_id=owner.user_id,
            meeting_manager=meeting_manager,
            active_activity=activity,
            action="engine_create_activity",
        )

        assert broadcast_mock.await_count == 2
        agenda_call, state_call = broadcast_mock.await_args_list
        assert agenda_call.args[0] == meeting.meeting_id
        agenda_message = agenda_call.args[1]
        assert agenda_message["type"] == "agenda_update"
        assert agenda_message["meta"] == {"initiatorId": owner.user_id}
        assert agenda_message["payload"][0]["activity_id"] == activity.activity_id
        assert agenda_message["payload"][0]["tool_type"] == "brainstorming"

        state_message = state_call.args[1]
        assert state_message["type"] == "meeting_state"
        assert state_message["meta"]["initiatorId"] == owner.user_id
        assert state_message["meta"]["action"] == "engine_create_activity"
        assert state_message["payload"]["currentActivity"] == activity.activity_id
        assert state_message["payload"]["currentTool"] == "brainstorming"
        assert result["state"]["activeActivities"][0]["activityId"] == activity.activity_id
    finally:
        await meeting_state_manager.reset(meeting.meeting_id)


@pytest.mark.anyio("asyncio")
async def test_engine_facilitator_decision_resume_reuses_realtime_envelopes(
    db_session, mocker
):
    """Loquacious Pelican: facilitator-decision resume broadcasts through existing shapes."""
    owner, meeting_manager, meeting = _seed_orchestration_meeting(
        db_session, "Engine Decision Broadcast"
    )
    doc = load_orchestration_data({
        "name": "engine-decision-broadcast",
        "version": "1",
        "author": "phase5",
        "citation": "Loquacious Pelican",
        "metadata": {
            "thinklets": ["t"],
            "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 10},
            "notes": "Loquacious Pelican decision mutation fixture",
        },
        "steps": [
            {
                "type": "facilitator-decision",
                "prompt": "Continue?",
                "options": ["continue", "stop"],
                "context_bundle_keys": [],
            }
        ],
    })
    strategy = OrchestrationEngineStrategy(doc)
    decision_activity = strategy.create_activity(meeting, None, None)
    strategy.resume_with_facilitator_decision(
        meeting,
        "continue",
        db=db_session,
        actor_user_id=owner.user_id,
    )
    broadcast_mock = mocker.patch(
        "app.services.orchestration_realtime.websocket_manager.broadcast"
    )

    try:
        await broadcast_engine_agenda_mutation(
            meeting_id=meeting.meeting_id,
            initiator_id=owner.user_id,
            meeting_manager=meeting_manager,
            state_patch={
                "currentActivity": None,
                "agendaItemId": None,
                "currentTool": None,
                "status": "completed",
                "activeActivities": {decision_activity.activity_id: None},
            },
            action="engine_resume_facilitator_decision",
        )

        assert broadcast_mock.await_count == 2
        agenda_message = broadcast_mock.await_args_list[0].args[1]
        assert agenda_message["type"] == "agenda_update"
        assert agenda_message["payload"][0]["activity_id"] == decision_activity.activity_id
        assert agenda_message["payload"][0]["tool_type"] == "facilitator_decision"

        state_message = broadcast_mock.await_args_list[1].args[1]
        assert state_message["type"] == "meeting_state"
        assert state_message["meta"]["action"] == "engine_resume_facilitator_decision"
        assert state_message["payload"]["currentActivity"] is None
        assert state_message["payload"]["status"] == "completed"
    finally:
        await meeting_state_manager.reset(meeting.meeting_id)


def test_agenda_strategy_binding_for_meeting_state_fixture(db_session):
    """Smug Otter: every meeting-state fixture meeting binds a deterministic strategy."""
    user_manager = UserManager()
    user_manager.set_db(db_session)
    owner = user_manager.add_user(
        first_name="Strategy",
        last_name="Owner",
        email="strategyowner@example.com",
        login="strategyowner",
        role="facilitator",
        hashed_password=get_password_hash("OwnerPass1!"),
    )

    meeting_manager = MeetingManager(db_session)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Strategy Binding Meeting",
            description="Test meeting for agenda strategy binding",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_minutes=30,
            owner_id=owner.user_id,
            participant_ids=[],
        ),
        facilitator_id=owner.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Intro"),
            AgendaActivityCreate(tool_type="voting", title="Vote"),
        ],
    )

    strategy = get_agenda_strategy(meeting)
    agenda = strategy.list_agenda(meeting)

    assert isinstance(strategy, LinearAgendaStrategy)
    assert strategy.name == "linear"
    assert [activity.title for activity in agenda] == ["Intro", "Vote"]
    assert (
        strategy.resolve_prior_activity(
            meeting,
            PriorActivityReference.for_consumer(agenda[0]),
        )
        is None
    )
    prior_resolution = strategy.resolve_prior_activity(
        meeting,
        PriorActivityReference.for_consumer(agenda[1]),
    )
    assert prior_resolution is not None
    assert prior_resolution.activity.activity_id == agenda[0].activity_id
    assert strategy.is_complete(meeting) is False
