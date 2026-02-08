import logging
from datetime import datetime, UTC
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.services import meeting_state_manager
from app.utils.websocket_manager import ConnectionInfo, websocket_manager
from app.models.meeting import AgendaActivity
from app.services.meeting_state import JSONCompatibleDict

router = APIRouter(prefix="/ws", tags=["realtime"])

logger = logging.getLogger(__name__)


def _serialize_connection(connection: ConnectionInfo) -> Dict[str, str]:
    """Helper to convert connection metadata into a JSON-friendly shape."""
    return {
        "connectionId": connection.id,
        "userId": connection.user_id or connection.id,
    }


def _format_agenda_activity(activity: AgendaActivity) -> JSONCompatibleDict:
    return {
        "activity_id": activity.activity_id,
        "order_index": activity.order_index,
        "title": activity.title,
        "tool_type": activity.tool_type,
        "instructions": activity.instructions,
        "config": activity.config,
        "started_at": activity.started_at.isoformat() if activity.started_at else None,
        "stopped_at": activity.stopped_at.isoformat() if activity.stopped_at else None,
    }


@router.websocket("/meetings/{meeting_id}")
async def meeting_socket(
    websocket: WebSocket,
    meeting_id: str,
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> None:
    """
    General-purpose WebSocket endpoint for meeting-specific real-time updates.
    """
    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        logger.error("Meeting %s not found for WebSocket connection", meeting_id)
        await websocket.close(code=1008, reason="Meeting not found")
        return

    formatted_agenda = [
        _format_agenda_activity(a)
        for a in sorted(meeting.agenda_activities, key=lambda x: x.order_index)
    ]

    client_hint = websocket.query_params.get("clientId") or websocket.query_params.get(
        "userId"
    )
    connection_id = await websocket_manager.connect(
        websocket,
        meeting_id,
        user_id=client_hint,
    )
    user_identifier = client_hint or connection_id
    if client_hint is None:
        websocket_manager.update_user(
            meeting_id, connection_id, user_id=user_identifier
        )

    # Ensure the meeting state manager has the latest agenda from the database
    current_meeting_state = await meeting_state_manager.get_or_create(meeting_id)
    current_meeting_state.agenda = formatted_agenda
    state_snapshot = await meeting_state_manager.register_participant(
        meeting_id, user_identifier
    )
    participants = state_snapshot.get("participants", [])

    await websocket_manager.send_personal_message(
        meeting_id,
        connection_id,
        {
            "type": "connection_ack",
            "payload": {
                "meetingId": meeting_id,
                "connectionId": connection_id,
                "userId": user_identifier,
                "participants": participants,
                "state": state_snapshot,
            },
        },
    )

    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "participant_joined",
            "payload": {
                "meetingId": meeting_id,
                "connectionId": connection_id,
                "userId": user_identifier,
                "state": state_snapshot,
            },
        },
        skip_connection=connection_id,
    )

    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            payload = message.get("payload", {})

            if message_type == "ping":
                await websocket_manager.send_personal_message(
                    meeting_id,
                    connection_id,
                    {
                        "type": "pong",
                        "payload": {
                            "meetingId": meeting_id,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    },
                )
            elif message_type == "identify":
                requested_user_id = payload.get("userId")
                new_identifier = requested_user_id or user_identifier
                websocket_manager.update_user(
                    meeting_id, connection_id, user_id=requested_user_id
                )
                state_snapshot = await meeting_state_manager.rename_participant(
                    meeting_id,
                    user_identifier,
                    new_identifier,
                )
                user_identifier = new_identifier
                await websocket_manager.broadcast(
                    meeting_id,
                    {
                        "type": "participant_identified",
                        "payload": {
                            "meetingId": meeting_id,
                            "connectionId": connection_id,
                            "userId": user_identifier,
                            "state": state_snapshot,
                        },
                    },
                )
            elif message_type == "state_request":
                # Ensure the meeting state manager has the latest agenda from the database
                current_meeting_state = await meeting_state_manager.get_or_create(
                    meeting_id
                )
                current_meeting_state.agenda = formatted_agenda
                snapshot = await meeting_state_manager.snapshot(meeting_id)
                await websocket_manager.send_personal_message(
                    meeting_id,
                    connection_id,
                    {
                        "type": "meeting_state",
                        "payload": snapshot,
                    },
                )
            elif message_type == "state_update":
                patch = payload if isinstance(payload, dict) else {}
                # Ensure the meeting state manager has the latest agenda from the database
                current_meeting_state = await meeting_state_manager.get_or_create(
                    meeting_id
                )
                current_meeting_state.agenda = formatted_agenda
                _, snapshot = await meeting_state_manager.apply_patch(meeting_id, patch)
                await websocket_manager.broadcast(
                    meeting_id,
                    {
                        "type": "meeting_state",
                        "payload": snapshot,
                        "meta": {
                            "connectionId": connection_id,
                            "userId": user_identifier,
                        },
                    },
                )
            elif message_type == "broadcast":
                event_type = payload.get("type", "broadcast")
                event_payload = payload.get("payload")
                await websocket_manager.broadcast(
                    meeting_id,
                    {
                        "type": event_type,
                        "payload": event_payload,
                        "meta": {
                            "connectionId": connection_id,
                            "userId": user_identifier,
                        },
                    },
                )
            else:
                await websocket_manager.send_personal_message(
                    meeting_id,
                    connection_id,
                    {
                        "type": "error",
                        "payload": {
                            "message": f"Unknown message type '{message_type}'",
                        },
                    },
                )
    except WebSocketDisconnect:
        logger.debug(
            "WebSocketDisconnect: meeting_id=%s connection_id=%s",
            meeting_id,
            connection_id,
        )
    finally:
        websocket_manager.disconnect(meeting_id, connection_id)
        state_snapshot = await meeting_state_manager.unregister_participant(
            meeting_id,
            user_identifier,
        )
        await websocket_manager.broadcast(
            meeting_id,
            {
                "type": "participant_left",
                "payload": {
                    "meetingId": meeting_id,
                    "connectionId": connection_id,
                    "userId": user_identifier,
                    "state": state_snapshot,
                },
            },
        )
