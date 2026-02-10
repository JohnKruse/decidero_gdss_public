from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_active_user
from app.database import get_db
from app.models.meeting import AgendaActivity, Meeting, MeetingFacilitator
from app.models.user import User, UserRole
from app.schemas.categorization import (
    CategorizationAssignmentRequest,
    CategorizationBucketCreateRequest,
    CategorizationBucketDeleteRequest,
    CategorizationBucketReorderRequest,
    CategorizationBucketUpdateRequest,
    CategorizationStateResponse,
)
from app.services.categorization_manager import CategorizationManager
from app.utils.websocket_manager import websocket_manager


router = APIRouter(prefix="/api/meetings/{meeting_id}/categorization", tags=["categorization"])


def _load_meeting(db: Session, meeting_id: str) -> Meeting:
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
            joinedload(Meeting.participants),
            joinedload(Meeting.agenda_activities),
        )
        .filter(Meeting.meeting_id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


def _resolve_activity(meeting: Meeting, activity_id: str) -> AgendaActivity:
    for activity in getattr(meeting, "agenda_activities", []) or []:
        if activity.activity_id == activity_id:
            if str(activity.tool_type or "").lower() != "categorization":
                raise HTTPException(status_code=400, detail="Requested activity is not categorization.")
            return activity
    raise HTTPException(status_code=404, detail="Agenda activity not found")


def _access(meeting: Meeting, user: User) -> tuple[bool, bool]:
    facilitator_ids = {
        link.user_id
        for link in getattr(meeting, "facilitator_links", []) or []
        if getattr(link, "user_id", None)
    }
    if getattr(meeting, "owner_id", None):
        facilitator_ids.add(meeting.owner_id)
    participant_ids = {
        person.user_id for person in getattr(meeting, "participants", []) or []
    }

    role = getattr(user, "role", UserRole.PARTICIPANT.value)
    is_admin = role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}
    is_facilitator = is_admin or user.user_id in facilitator_ids
    is_participant = is_facilitator or is_admin or user.user_id in participant_ids
    if not is_participant:
        raise HTTPException(status_code=403, detail="You do not have access to this meeting.")
    return is_participant, is_facilitator


async def _broadcast_refresh(meeting_id: str, activity_id: str, initiator_id: str) -> None:
    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "categorization_update",
            "payload": {"activity_id": activity_id},
            "meta": {"initiatorId": initiator_id},
        },
    )


@router.get("/state", response_model=CategorizationStateResponse)
async def get_state(
    meeting_id: str,
    activity_id: str = Query(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _access(meeting, current_user)
    _resolve_activity(meeting, activity_id)
    state = CategorizationManager(db).build_state(meeting_id, activity_id)
    return CategorizationStateResponse(**state)


@router.post("/buckets")
async def create_bucket(
    meeting_id: str,
    payload: CategorizationBucketCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage buckets.")
    _resolve_activity(meeting, payload.activity_id)
    manager = CategorizationManager(db)
    bucket = manager.create_bucket(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        title=payload.title,
        category_id=payload.category_id,
        description=payload.description,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {
        "category_id": bucket.category_id,
        "title": bucket.title,
        "description": bucket.description,
        "order_index": bucket.order_index,
        "status": bucket.status,
    }


@router.patch("/buckets/{category_id}")
async def update_bucket(
    meeting_id: str,
    category_id: str,
    payload: CategorizationBucketUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage buckets.")
    _resolve_activity(meeting, payload.activity_id)
    bucket = CategorizationManager(db).update_bucket(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        category_id=category_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {
        "category_id": bucket.category_id,
        "title": bucket.title,
        "description": bucket.description,
        "order_index": bucket.order_index,
        "status": bucket.status,
    }


@router.delete("/buckets/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bucket(
    meeting_id: str,
    category_id: str,
    payload: CategorizationBucketDeleteRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage buckets.")
    _resolve_activity(meeting, payload.activity_id)
    CategorizationManager(db).delete_bucket(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        category_id=category_id,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return None


@router.post("/buckets/reorder")
async def reorder_buckets(
    meeting_id: str,
    payload: CategorizationBucketReorderRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage buckets.")
    _resolve_activity(meeting, payload.activity_id)
    buckets = CategorizationManager(db).reorder_buckets(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        ordered_category_ids=payload.category_ids,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {
        "buckets": [
            {
                "category_id": bucket.category_id,
                "title": bucket.title,
                "order_index": bucket.order_index,
                "status": bucket.status,
            }
            for bucket in buckets
        ]
    }


@router.post("/assignments")
async def set_assignment(
    meeting_id: str,
    payload: CategorizationAssignmentRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can move items in facilitator-live mode.")
    _resolve_activity(meeting, payload.activity_id)
    assignment = CategorizationManager(db).upsert_assignment(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        item_key=payload.item_key,
        category_id=payload.category_id,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {
        "item_key": assignment.item_key,
        "category_id": assignment.category_id,
        "is_unsorted": assignment.is_unsorted,
    }
