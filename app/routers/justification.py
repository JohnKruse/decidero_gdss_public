"""DEPRECATED outlier-justification API.

Superseded by the generic brainstorming comment surface used by the shipped Delphi
method (see `plans/subplans/DELPHI_GENERIC_COMMENT.md`). Retained as a deprecated
reference; `orchestrations/delphi.json` no longer materializes this activity.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.auth import get_current_user
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.data.user_manager import UserManager, get_user_manager
from app.models.user import User
from app.schemas.justification import (
    JustificationStateResponse,
    JustificationSubmitRequest,
)
from app.services import meeting_state_manager
from app.services.meeting_authorization import resolve_meeting_capabilities
from app.services.outlier_justification_manager import (
    JustificationError,
    OutlierJustificationManager,
)
from app.utils.websocket_manager import websocket_manager


router = APIRouter(
    prefix="/api/meetings/{meeting_id}/justification",
    tags=["justification"],
)


def _ensure_user_access(meeting, user: User) -> tuple[bool, bool]:
    capabilities = resolve_meeting_capabilities(meeting, user)
    is_facilitator = bool(capabilities["can_manage"])
    is_participant = bool(capabilities["can_view"])

    if not is_participant:
        raise HTTPException(
            status_code=403, detail="You do not have access to this meeting."
        )
    return is_participant, is_facilitator


def _resolve_activity(meeting, activity_id: str):
    activity = next(
        (
            item
            for item in getattr(meeting, "agenda_activities", [])
            if item.activity_id == activity_id
        ),
        None,
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Agenda activity not found")
    if activity.tool_type != "outlier_justification":
        raise HTTPException(
            status_code=400,
            detail="This agenda activity is not an outlier justification activity.",
        )
    return activity


async def _is_active_justification(meeting_id: str, activity_id: str) -> bool:
    snapshot = await meeting_state_manager.snapshot(meeting_id)
    if not snapshot:
        return False

    active_entries = snapshot.get("activeActivities") or []
    if isinstance(active_entries, dict):
        active_entries = active_entries.values()
    for entry in active_entries:
        if not isinstance(entry, dict):
            continue
        if (
            str(entry.get("tool") or "").lower() == "outlier_justification"
            and (entry.get("activityId") or entry.get("activity_id")) == activity_id
        ):
            status = str(entry.get("status") or "").lower()
            return status in {"in_progress", "paused"}

    current_tool = str(snapshot.get("currentTool") or "").lower()
    current_activity = snapshot.get("currentActivity") or snapshot.get("agendaItemId")
    if current_tool == "outlier_justification" and current_activity == activity_id:
        status = str(snapshot.get("status") or "").lower()
        return status in {"in_progress", "paused"}
    return False


def _resolve_user_meeting_activity(
    meeting_id: str,
    activity_id: str,
    current_user_login: str,
    meeting_manager: MeetingManager,
    user_manager: UserManager,
):
    user = user_manager.get_user_by_login(current_user_login)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    activity = _resolve_activity(meeting, activity_id)
    _, is_facilitator = _ensure_user_access(meeting, user)
    return user, meeting, activity, is_facilitator


@router.get("/state", response_model=JustificationStateResponse)
async def get_justification_state(
    meeting_id: str,
    activity_id: str = Query(..., description="Agenda activity identifier"),
    current_user_login: str = Depends(get_current_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
    user_manager: UserManager = Depends(get_user_manager),
):
    user, meeting, activity, is_facilitator = _resolve_user_meeting_activity(
        meeting_id, activity_id, current_user_login, meeting_manager, user_manager
    )
    is_active = await _is_active_justification(meeting_id, activity_id)
    if not is_active and not is_facilitator:
        raise HTTPException(
            status_code=403,
            detail="This activity is not open for justification.",
        )

    manager = OutlierJustificationManager(meeting_manager.db)
    state = manager.build_state(meeting, activity, user)
    if is_facilitator:
        state["progress"] = manager.facilitator_progress(meeting, activity)
    return JustificationStateResponse(**state)


@router.post("/rationale", response_model=JustificationStateResponse)
async def submit_justification_rationale(
    meeting_id: str,
    payload: JustificationSubmitRequest,
    current_user_login: str = Depends(get_current_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
    user_manager: UserManager = Depends(get_user_manager),
):
    user, meeting, activity, _ = _resolve_user_meeting_activity(
        meeting_id,
        payload.activity_id,
        current_user_login,
        meeting_manager,
        user_manager,
    )
    is_active = await _is_active_justification(meeting_id, payload.activity_id)
    if not is_active:
        raise HTTPException(
            status_code=403,
            detail="This activity is not open for justification.",
        )

    manager = OutlierJustificationManager(meeting_manager.db)
    try:
        manager.submit_rationale(
            meeting,
            activity,
            user,
            payload.option_id,
            payload.rationale,
        )
    except JustificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "justification_update",
            "payload": {"activity_id": payload.activity_id},
            "meta": {"initiatorId": user.user_id},
        },
    )

    state = manager.build_state(meeting, activity, user)
    return JustificationStateResponse(**state)
