"""Realtime helpers for orchestration-engine mutations.

Loquacious Pelican: engine-driven agenda mutations reuse the same
`agenda_update` and `meeting_state` envelopes that facilitator-driven actions
already emit. The orchestration strategy remains synchronous; callers invoke
these async helpers from router or service boundaries after an engine mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.data.meeting_manager import MeetingManager
from app.models.meeting import AgendaActivity
from app.schemas.meeting import AgendaActivityResponse
from app.services import meeting_state_manager
from app.utils.websocket_manager import websocket_manager


def _serialize_agenda_item(activity: AgendaActivity) -> Dict[str, Any]:
    return AgendaActivityResponse.model_validate(activity).model_dump()


def _active_activity_patch(activity: AgendaActivity) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    activity_state = {
        "activityId": activity.activity_id,
        "tool": activity.tool_type,
        "status": "in_progress",
        "metadata": {},
        "participantIds": [],
        "startedAt": now,
        "stoppedAt": None,
        "elapsedTime": activity.elapsed_duration or 0,
    }
    return {
        "currentActivity": activity.activity_id,
        "agendaItemId": activity.activity_id,
        "currentTool": activity.tool_type,
        "status": "in_progress",
        "activeActivities": {activity.activity_id: activity_state},
    }


async def broadcast_engine_agenda_mutation(
    *,
    meeting_id: str,
    initiator_id: str,
    meeting_manager: MeetingManager,
    active_activity: Optional[AgendaActivity] = None,
    state_patch: Optional[Dict[str, Any]] = None,
    action: str = "engine_agenda_update",
) -> Dict[str, Any]:
    """Broadcast an engine mutation through existing realtime envelopes.

    The agenda envelope intentionally matches the facilitator-driven
    `app.routers.meetings._broadcast_agenda_update` shape: message type
    `agenda_update`, serialized agenda payload, and `meta.initiatorId`.

    When `active_activity` or `state_patch` is supplied, this also emits the
    existing `meeting_state` envelope used by facilitator control actions. This
    is the Phase 5 Step 1 hook for activity materialization and
    facilitator-decision resumption without adding a new websocket message type.
    """
    meeting_manager.db.expire_all()
    agenda_items = meeting_manager.list_agenda(meeting_id)
    agenda_payload = [_serialize_agenda_item(item) for item in agenda_items]

    # Loquacious Pelican: reuse the facilitator agenda_update envelope.
    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "agenda_update",
            "payload": agenda_payload,
            "meta": {
                "initiatorId": initiator_id,
            },
        },
    )

    snapshot = None
    patch: Dict[str, Any] = {}
    if active_activity is not None:
        patch.update(_active_activity_patch(active_activity))
    if state_patch:
        patch.update(state_patch)

    if patch:
        _, snapshot = await meeting_state_manager.apply_patch(meeting_id, patch)
        # Loquacious Pelican: reuse the facilitator meeting_state envelope.
        await websocket_manager.broadcast(
            meeting_id,
            {
                "type": "meeting_state",
                "payload": snapshot,
                "meta": {
                    "initiatorId": initiator_id,
                    "action": action,
                    "activityId": (
                        active_activity.activity_id if active_activity is not None else None
                    ),
                },
            },
        )

    return {"agenda": agenda_payload, "state": snapshot}
