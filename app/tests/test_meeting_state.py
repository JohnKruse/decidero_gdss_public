import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.services.meeting_state import MeetingStateManager, meeting_state_manager
from app.data.meeting_manager import MeetingManager
from app.data.user_manager import UserManager
from app.schemas.meeting import MeetingCreate, AgendaActivityCreate
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


def test_meeting_state_websocket_flow(db_session, client: TestClient):
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
        with client.websocket_connect(f"/ws/meetings/{meeting_id}") as websocket:
            ack = websocket.receive_json()
            assert ack["type"] == "connection_ack"
            payload = ack["payload"]
            assert payload["meetingId"] == meeting_id
            assert payload["state"]["participants"] == [payload["userId"]]
            assert "status" in payload["state"]
            assert payload["state"]["updatedAt"]

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
