from __future__ import annotations

import logging
from typing import Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.auth import get_current_user
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.data.user_manager import UserManager, get_user_manager
from app.models.user import User, UserRole
from app.schemas.rank_order_voting import (
    RankOrderResetRequest,
    RankOrderSubmitRequest,
    RankOrderVotingSummaryResponse,
)
from app.services import meeting_state_manager
from app.services.rank_order_voting_manager import RankOrderVotingManager
from app.utils.websocket_manager import websocket_manager


router = APIRouter(
    prefix="/api/meetings/{meeting_id}/rank-order-voting",
    tags=["rank-order-voting"],
)
logger = logging.getLogger("app")


def _ensure_user_access(
    meeting,
    user: User,
    allowed_participant_ids: Optional[Set[str]] = None,
) -> tuple[bool, bool]:
    facilitator_ids = {
        link.user_id
        for link in getattr(meeting, "facilitator_links", []) or []
        if getattr(link, "user_id", None)
    }
    if getattr(meeting, "owner_id", None):
        facilitator_ids.add(meeting.owner_id)

    participant_ids = {
        getattr(participant, "user_id", None)
        for participant in getattr(meeting, "participants", [])
    }

    role_value = getattr(user, "role", UserRole.PARTICIPANT.value)
    is_admin = role_value in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}
    is_facilitator = is_admin or user.user_id in facilitator_ids
    is_participant = is_facilitator or is_admin or user.user_id in participant_ids

    if not is_participant:
        raise HTTPException(
            status_code=403, detail="You do not have access to this meeting."
        )
    if (
        allowed_participant_ids
        and not is_facilitator
        and not is_admin
        and user.user_id not in allowed_participant_ids
    ):
        raise HTTPException(
            status_code=403, detail="You are not assigned to this activity."
        )
    return is_participant, is_facilitator or is_admin


def _compute_active_participant_count(
    meeting,
    allowed_participant_ids: Optional[Set[str]],
    active_user_ids: Set[str],
) -> int:
    meeting_participants = {
        getattr(participant, "user_id", None)
        for participant in getattr(meeting, "participants", []) or []
        if getattr(participant, "user_id", None)
    }
    if not active_user_ids:
        return 0

    if allowed_participant_ids:
        return sum(
            1
            for user_id in active_user_ids
            if user_id in allowed_participant_ids and user_id in meeting_participants
        )

    return sum(1 for user_id in active_user_ids if user_id in meeting_participants)


async def _resolve_scope(
    meeting_id: str,
    activity_id: str,
    activity,
) -> tuple[Optional[Set[str]], bool, Set[str]]:
    allowed: Optional[Set[str]] = None
    is_active = False
    active_user_ids: Set[str] = set()
    snapshot = await meeting_state_manager.snapshot(meeting_id)

    if snapshot:
        participants = snapshot.get("participants")
        if isinstance(participants, list):
            active_user_ids = {str(pid).strip() for pid in participants if str(pid).strip()}

        active_entries = snapshot.get("activeActivities") or []
        if isinstance(active_entries, dict):
            active_entries = active_entries.values()
        for entry in active_entries:
            if not isinstance(entry, dict):
                continue
            if (
                str(entry.get("tool") or "").lower() == "rank_order_voting"
                and (entry.get("activityId") or entry.get("activity_id")) == activity_id
            ):
                status_value = str(entry.get("status") or "").lower()
                if status_value in {"in_progress", "paused"}:
                    is_active = True
                metadata = entry.get("metadata") or {}
                scope = str(
                    metadata.get("participantScope")
                    or metadata.get("participant_scope")
                    or ""
                ).lower()
                meta_ids = metadata.get("participantIds") or metadata.get(
                    "participant_ids"
                )
                if scope == "custom" and isinstance(meta_ids, list):
                    normalized = {
                        str(pid).strip() for pid in meta_ids if str(pid).strip()
                    }
                    if normalized:
                        allowed = normalized
                break

        if allowed is None:
            current_tool = str(snapshot.get("currentTool") or "").lower()
            current_activity = snapshot.get("currentActivity") or snapshot.get(
                "agendaItemId"
            )
            if current_tool == "rank_order_voting" and current_activity == activity_id:
                status_value = str(snapshot.get("status") or "").lower()
                if status_value in {"in_progress", "paused"}:
                    is_active = True
                metadata = snapshot.get("metadata") or {}
                scope = str(
                    metadata.get("participantScope")
                    or metadata.get("participant_scope")
                    or ""
                ).lower()
                meta_ids = metadata.get("participantIds") or metadata.get(
                    "participant_ids"
                )
                if scope == "custom" and isinstance(meta_ids, list):
                    normalized = {
                        str(pid).strip() for pid in meta_ids if str(pid).strip()
                    }
                    if normalized:
                        allowed = normalized

    if allowed is None and activity:
        config = dict(getattr(activity, "config", {}) or {})
        raw_ids = config.get("participant_ids")
        if isinstance(raw_ids, list) and raw_ids:
            allowed = {str(pid).strip() for pid in raw_ids if str(pid).strip()}

    return allowed, is_active, active_user_ids


@router.get("/summary", response_model=RankOrderVotingSummaryResponse)
async def get_rank_order_summary(
    meeting_id: str,
    activity_id: str = Query(..., description="Agenda activity identifier"),
    current_user_login: str = Depends(get_current_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
    user_manager: UserManager = Depends(get_user_manager),
):
    user = user_manager.get_user_by_login(current_user_login)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

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

    allowed_participant_ids, is_active, active_user_ids = await _resolve_scope(
        meeting_id, activity_id, activity
    )
    _, is_facilitator = _ensure_user_access(meeting, user, allowed_participant_ids)
    if not is_active and not is_facilitator:
        raise HTTPException(
            status_code=403,
            detail="This activity is not open for rank-order voting.",
        )

    active_count = _compute_active_participant_count(
        meeting,
        allowed_participant_ids,
        active_user_ids,
    )

    manager = RankOrderVotingManager(meeting_manager.db)
    summary = manager.build_summary(
        meeting,
        activity_id=activity_id,
        user=user,
        force_results=is_facilitator,
        is_active_state=is_active,
        active_participant_count=active_count,
    )
    return RankOrderVotingSummaryResponse(**summary)


@router.post("/rankings", response_model=RankOrderVotingSummaryResponse)
async def submit_rank_order_ranking(
    meeting_id: str,
    payload: RankOrderSubmitRequest,
    current_user_login: str = Depends(get_current_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
    user_manager: UserManager = Depends(get_user_manager),
):
    user = user_manager.get_user_by_login(current_user_login)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    activity = next(
        (
            item
            for item in getattr(meeting, "agenda_activities", [])
            if item.activity_id == payload.activity_id
        ),
        None,
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Agenda activity not found")

    allowed_participant_ids, is_active, active_user_ids = await _resolve_scope(
        meeting_id, payload.activity_id, activity
    )
    _ensure_user_access(meeting, user, allowed_participant_ids)
    if not is_active:
        raise HTTPException(
            status_code=403,
            detail="This activity is not open for rank-order voting.",
        )

    active_count = _compute_active_participant_count(
        meeting,
        allowed_participant_ids,
        active_user_ids,
    )

    manager = RankOrderVotingManager(meeting_manager.db)
    summary = manager.submit_ranking(
        meeting,
        payload.activity_id,
        user,
        payload.ordered_option_ids,
        is_active_state=True,
        active_participant_count=active_count,
    )

    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "rank_order_voting_update",
            "payload": {"activity_id": payload.activity_id},
            "meta": {"initiatorId": user.user_id},
        },
    )

    return RankOrderVotingSummaryResponse(**summary)


@router.post("/reset", response_model=RankOrderVotingSummaryResponse)
async def reset_rank_order_ranking(
    meeting_id: str,
    payload: RankOrderResetRequest,
    current_user_login: str = Depends(get_current_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
    user_manager: UserManager = Depends(get_user_manager),
):
    user = user_manager.get_user_by_login(current_user_login)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    activity = next(
        (
            item
            for item in getattr(meeting, "agenda_activities", [])
            if item.activity_id == payload.activity_id
        ),
        None,
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Agenda activity not found")

    allowed_participant_ids, is_active, active_user_ids = await _resolve_scope(
        meeting_id, payload.activity_id, activity
    )
    _ensure_user_access(meeting, user, allowed_participant_ids)
    if not is_active:
        raise HTTPException(
            status_code=403,
            detail="This activity is not open for rank-order voting.",
        )

    active_count = _compute_active_participant_count(
        meeting,
        allowed_participant_ids,
        active_user_ids,
    )

    manager = RankOrderVotingManager(meeting_manager.db)
    summary = manager.reset_ranking(
        meeting,
        payload.activity_id,
        user,
        is_active_state=True,
        active_participant_count=active_count,
    )

    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "rank_order_voting_update",
            "payload": {"activity_id": payload.activity_id},
            "meta": {"initiatorId": user.user_id},
        },
    )

    return RankOrderVotingSummaryResponse(**summary)
