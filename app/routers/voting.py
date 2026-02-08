from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, Set
from app.services import meeting_state_manager

from app.auth.auth import get_current_user
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.services.voting_manager import VotingManager
from app.data.user_manager import UserManager, get_user_manager
from app.models.user import User, UserRole
from app.schemas.voting import (
    VoteCastRequest,
    VoteCastResponse,
    VotingOptionsResponse,
)
from app.utils.websocket_manager import websocket_manager


router = APIRouter(prefix="/api/meetings/{meeting_id}/voting", tags=["voting"])


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


async def _resolve_voting_scope(
    meeting_id: str,
    activity_id: str,
    activity,
) -> tuple[Optional[Set[str]], bool]:
    """
    Derive the allowed participant IDs for a voting activity, preferring the live meeting state
    metadata (so facilitators can launch with ad-hoc scopes) and falling back to the stored config.
    """
    allowed: Optional[Set[str]] = None
    is_active = False
    snapshot = await meeting_state_manager.snapshot(meeting_id)
    if snapshot:
        active_entries = snapshot.get("activeActivities") or []
        if isinstance(active_entries, dict):
            active_entries = active_entries.values()
        for entry in active_entries:
            if not isinstance(entry, dict):
                continue
            if (
                str(entry.get("tool") or "").lower() == "voting"
                and (entry.get("activityId") or entry.get("activity_id")) == activity_id
            ):
                status = str(entry.get("status") or "").lower()
                if status in {"in_progress", "paused"}:
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
            if current_tool == "voting" and current_activity == activity_id:
                status = str(snapshot.get("status") or "").lower()
                if status in {"in_progress", "paused"}:
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
    return allowed, is_active


@router.get("/options", response_model=VotingOptionsResponse)
async def get_voting_options(
    meeting_id: str,
    activity_id: str = Query(
        ..., description="Agenda activity identifier (e.g., VOTING-0001)"
    ),
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

    allowed_participant_ids, is_active = await _resolve_voting_scope(
        meeting_id, activity_id, activity
    )
    _, is_facilitator = _ensure_user_access(meeting, user, allowed_participant_ids)
    if not is_active and not is_facilitator:
        raise HTTPException(
            status_code=403, detail="This activity is not open for voting."
        )

    voting_manager = VotingManager(meeting_manager.db)
    summary = voting_manager.build_summary(
        meeting,
        activity_id=activity_id,
        user=user,
        force_results=False,
        is_active_state=is_active,
    )
    return VotingOptionsResponse(**summary)


@router.post("/votes", response_model=VoteCastResponse)
async def cast_vote(
    meeting_id: str,
    vote_request: VoteCastRequest,
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
            if item.activity_id == vote_request.activity_id
        ),
        None,
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Agenda activity not found")

    allowed_participant_ids, is_active = await _resolve_voting_scope(
        meeting_id, vote_request.activity_id, activity
    )
    _ensure_user_access(meeting, user, allowed_participant_ids)
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for voting."
        )

    voting_manager = VotingManager(meeting_manager.db)
    summary = voting_manager.cast_vote(
        meeting,
        vote_request.activity_id,
        user,
        vote_request.option_id,
        action=vote_request.action,
    )

    # Broadcast update to trigger refresh for other users
    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "voting_update",
            "payload": {"activity_id": vote_request.activity_id},
            "meta": {"initiatorId": user.user_id},
        },
    )

    return VoteCastResponse(**summary)
