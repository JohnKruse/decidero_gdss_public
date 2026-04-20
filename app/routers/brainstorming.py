from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from typing import Any, Dict, List, Optional, Set
import logging

from app.auth import get_current_active_user
from app.database import get_db
from app.data.idempotency_manager import BrainstormingIdempotencyManager
from app.models.meeting import Meeting, MeetingFacilitator
from app.models.user import User, UserRole
from app.schemas.brainstorming import (
    BrainstormingIdeaCreate,
    BrainstormingIdeaResponse,
)
from app.data.ideas_manager import IdeasManager
from app.utils.websocket_manager import websocket_manager
from app.services import meeting_state_manager
from app.config.loader import get_brainstorming_limits

brainstorming_router = APIRouter(prefix="/api/meetings/{meeting_id}/brainstorming")
logger = logging.getLogger(__name__)
BRAINSTORMING_LIMITS = get_brainstorming_limits()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return bool(value)


@brainstorming_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, meeting_id: str):
    """
    WebSocket endpoint for real-time brainstorming updates
    """
    connection_id = await websocket_manager.connect(websocket, meeting_id)
    await websocket_manager.send_personal_message(
        meeting_id,
        connection_id,
        {
            "type": "connection_ack",
            "payload": {
                "meetingId": meeting_id,
                "connectionId": connection_id,
            },
        },
    )
    try:
        while True:
            # Keep the connection alive and handle any incoming messages
            data = await websocket.receive_json()
            # You can add additional message handling logic here if needed
            if data.get("type") == "ping":
                await websocket_manager.send_personal_message(
                    meeting_id,
                    connection_id,
                    {"type": "pong", "payload": {"meetingId": meeting_id}},
                )
    except WebSocketDisconnect:
        pass
    finally:
        websocket_manager.disconnect(meeting_id, connection_id)


def _assert_user_can_participate(
    meeting: Meeting,
    user: User,
    allowed_participant_ids: Optional[Set[str]] = None,
) -> bool:
    facilitator_ids = {
        link.user_id
        for link in getattr(meeting, "facilitator_links", []) or []
        if link.user_id
    }
    participant_ids = {
        participant.user_id
        for participant in getattr(meeting, "participants", []) or []
        if participant.user_id
    }

    is_admin = user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
    is_owner = meeting.owner_id == user.user_id
    is_facilitator = user.user_id in facilitator_ids
    is_participant = user.user_id in participant_ids

    if is_admin or is_owner or is_facilitator:
        return True

    if allowed_participant_ids is not None:
        if user.user_id in allowed_participant_ids:
            return False
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this activity.",
        )

    if is_participant:
        return False

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have access to this meeting's brainstorming session.",
    )


async def _resolve_brainstorming_scope(
    meeting_id: str,
    meeting: Meeting,
    activity_id: Optional[str] = None,
) -> tuple[Optional[Set[str]], Optional[str], bool]:
    """
    Determine whether a brainstorming activity is running and return the allowed participant ids when scoped.
    """
    snapshot = await meeting_state_manager.snapshot(meeting_id)
    active_entries: Dict[str, dict] = {}
    if snapshot:
        raw_entries = snapshot.get("activeActivities") or []
        if isinstance(raw_entries, dict):
            raw_entries = raw_entries.values()
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            tool = str(entry.get("tool") or "").lower()
            status = str(entry.get("status") or "").lower()
            entry_id = entry.get("activityId") or entry.get("activity_id")
            if tool != "brainstorming" or not entry_id:
                continue
            if status and status not in {"in_progress", "paused"}:
                continue
            active_entries[str(entry_id)] = entry

    def _derive_allowed_from_entry(entry: Optional[dict], entry_activity_id: Optional[str]) -> Optional[Set[str]]:
        if entry:
            metadata = entry.get("metadata") or {}
            meta_scope = str(
                metadata.get("participantScope") or metadata.get("participant_scope") or ""
            ).lower()
            meta_ids = metadata.get("participantIds") or metadata.get("participant_ids")
            if meta_scope == "custom" and isinstance(meta_ids, list):
                scoped = {str(pid).strip() for pid in meta_ids if str(pid).strip()}
                if scoped:
                    return scoped
        if entry_activity_id:
            activity = next(
                (
                    item
                    for item in getattr(meeting, "agenda_activities", [])
                    if item.activity_id == entry_activity_id
                ),
                None,
            )
            if activity:
                raw_ids = dict(getattr(activity, "config", {}) or {}).get("participant_ids")
                if isinstance(raw_ids, list) and raw_ids:
                    return {str(pid).strip() for pid in raw_ids if str(pid).strip()}
        return None

    if activity_id:
        entry = active_entries.get(activity_id)
        allowed_ids = _derive_allowed_from_entry(entry, activity_id)
        return allowed_ids, activity_id, entry is not None

    if active_entries:
        resolved_id = None
        for item in getattr(meeting, "agenda_activities", []) or []:
            if item.activity_id in active_entries:
                resolved_id = item.activity_id
                break
        if not resolved_id:
            resolved_id = next(iter(active_entries.keys()))
        entry = active_entries.get(resolved_id)
        allowed_ids = _derive_allowed_from_entry(entry, resolved_id)
        return allowed_ids, resolved_id, True

    if snapshot:
        current_tool = str(snapshot.get("currentTool") or "").lower()
        current_activity = snapshot.get("currentActivity") or snapshot.get("agendaItemId")
        status = str(snapshot.get("status") or "").lower()
        if current_tool == "brainstorming" and current_activity:
            entry = {"metadata": snapshot.get("metadata") or {}}
            allowed_ids = _derive_allowed_from_entry(entry, current_activity)
            is_active = status in {"in_progress", "paused"}
            return allowed_ids, current_activity, is_active

    return None, None, False


def _get_brainstorming_activity_config(
    activity_id: Optional[str], meeting: Meeting
) -> dict:
    """Return the config dict for the given brainstorming activity, if available."""
    if not activity_id:
        return {}
    activity = next(
        (
            item
            for item in getattr(meeting, "agenda_activities", [])
            if item.activity_id == activity_id
        ),
        None,
    )
    if not activity:
        return {}
    config = getattr(activity, "config", {}) or {}
    return dict(config) if isinstance(config, dict) else {}


@brainstorming_router.post(
    "/ideas",
    response_model=BrainstormingIdeaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_idea(
    meeting_id: str,
    payload: BrainstormingIdeaCreate,
    activity_id: Optional[str] = Query(
        None, description="Agenda activity identifier (e.g., BRAINSTORM-0001)"
    ),
    x_idempotency_key: Optional[str] = Header(
        None,
        alias="X-Idempotency-Key",
        description="Optional client-generated key for safe replay of retries.",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.participants),
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
            joinedload(Meeting.agenda_activities),
        )
        .filter(Meeting.meeting_id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    if activity_id:
        activity = next(
            (
                item
                for item in getattr(meeting, "agenda_activities", [])
                if item.activity_id == activity_id
            ),
            None,
        )
        if not activity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agenda activity not found",
            )
        if str(getattr(activity, "tool_type", "") or "").lower() != "brainstorming":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Requested activity is not a brainstorming module.",
            )

    allowed_ids, resolved_activity_id, is_active = await _resolve_brainstorming_scope(
        meeting_id, meeting, activity_id
    )
    if not resolved_activity_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active brainstorming activity found.",
        )
    is_privileged = _assert_user_can_participate(
        meeting, current_user, allowed_ids
    )
    if not is_privileged and not is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This activity is not open yet.",
        )

    activity_config = _get_brainstorming_activity_config(
        resolved_activity_id, meeting
    )
    allow_anonymous = _coerce_bool(activity_config.get("allow_anonymous"))
    allow_subcomments = _coerce_bool(activity_config.get("allow_subcomments"))
    idempotency_key = (x_idempotency_key or "").strip()[:128] or None

    ideas_manager = IdeasManager()
    idempotency_manager = BrainstormingIdempotencyManager()

    # Validate parent_id if provided (subcomment)
    if payload.parent_id is not None:
        if not allow_subcomments:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subcomments are not allowed for this activity.",
            )
        parent_idea = ideas_manager.get_idea(db, payload.parent_id)
        if not parent_idea or parent_idea.activity_id != resolved_activity_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent idea not found in this activity.",
            )

    max_chars = BRAINSTORMING_LIMITS.get("idea_character_limit") or 0
    content = (payload.content or "").strip()
    if max_chars and len(content) > max_chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ideas are limited to {max_chars} characters.",
        )

    effective_submitted_name = None if allow_anonymous else payload.submitted_name
    request_hash = None
    idempotency_entry = None
    if idempotency_key:
        request_hash = idempotency_manager.build_request_hash(
            content=content,
            parent_id=payload.parent_id,
            metadata=payload.metadata,
            submitted_name=effective_submitted_name,
        )
        existing = idempotency_manager.get_existing(
            db,
            meeting_id=meeting_id,
            activity_id=resolved_activity_id,
            user_id=current_user.user_id,
            idempotency_key=idempotency_key,
        )
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key was already used with a different request payload.",
                )
            if existing.response_payload and existing.status_code:
                return JSONResponse(
                    status_code=existing.status_code,
                    content=existing.response_payload,
                )
            idempotency_entry = existing

    max_per_user = BRAINSTORMING_LIMITS.get("max_ideas_per_user") or 0
    if max_per_user > 0:
        submitted = ideas_manager.count_ideas_for_user(
            db, meeting_id, current_user.user_id, resolved_activity_id
        )
        if submitted >= max_per_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"You can submit up to {max_per_user} ideas for this brainstorming session.",
            )

    idea_owner_id = None if allow_anonymous else current_user.user_id
    submitted_name = None if allow_anonymous else payload.submitted_name
    if idempotency_key and idempotency_entry is None:
        try:
            # Opportunistic cleanup keeps the idempotency table bounded.
            idempotency_manager.prune_expired(db)
            idempotency_entry = idempotency_manager.claim(
                db,
                meeting_id=meeting_id,
                activity_id=resolved_activity_id,
                user_id=current_user.user_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        except IntegrityError:
            db.rollback()
            existing = idempotency_manager.get_existing(
                db,
                meeting_id=meeting_id,
                activity_id=resolved_activity_id,
                user_id=current_user.user_id,
                idempotency_key=idempotency_key,
            )
            if existing and existing.request_hash == request_hash and existing.response_payload and existing.status_code:
                return JSONResponse(
                    status_code=existing.status_code,
                    content=existing.response_payload,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A request with this idempotency key is already in progress.",
            )

    idea = ideas_manager.add_idea(
        db,
        meeting_id,
        idea_owner_id,
        {
            "content": content,
            "submitted_name": submitted_name,
            "parent_id": payload.parent_id,
            "metadata": payload.metadata,
        },
        activity_id=resolved_activity_id,
        force_anonymous_name=False,
        commit=False,
    )
    if not idea:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to capture idea"
        )

    idea_response = BrainstormingIdeaResponse.model_validate(idea)
    if allow_anonymous:
        idea_response = idea_response.model_copy(
            update={
                "user_id": None,
                "user_color": None,
                "user_avatar_key": None,
                "user_avatar_icon_path": None,
                "submitted_name": "Anonymous",
            }
        )
    else:
        idea_response = idea_response.model_copy(
            update={
                "user_color": current_user.avatar_color,
                "user_avatar_key": current_user.avatar_key,
                "user_avatar_icon_path": current_user.avatar_icon_path,
            }
        )
    response_payload = idea_response.model_dump(mode="json")
    if idempotency_key and idempotency_entry is not None:
        idempotency_manager.store_success(
            db,
            entry=idempotency_entry,
            status_code=status.HTTP_201_CREATED,
            response_payload=response_payload,
            idea_id=getattr(idea, "id", None),
        )
    db.commit()

    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "new_idea",
            "payload": response_payload,
        },
    )
    if payload.parent_id is None:
        await websocket_manager.broadcast(
            meeting_id,
            {
                "type": "transfer_count_update",
                "payload": {
                    "activity_id": resolved_activity_id,
                    "delta": 1,
                    "source": "brainstorming_idea",
                },
            },
        )

    return idea_response


@brainstorming_router.get("/ideas", response_model=List[BrainstormingIdeaResponse])
async def get_ideas(
    meeting_id: str,
    activity_id: Optional[str] = Query(
        None, description="Agenda activity identifier (e.g., BRAINSTORM-0001)"
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.participants),
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
            joinedload(Meeting.agenda_activities),
        )
        .filter(Meeting.meeting_id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    if activity_id:
        activity = next(
            (
                item
                for item in getattr(meeting, "agenda_activities", [])
                if item.activity_id == activity_id
            ),
            None,
        )
        if not activity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agenda activity not found",
            )
        if str(getattr(activity, "tool_type", "") or "").lower() != "brainstorming":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Requested activity is not a brainstorming module.",
            )

    allowed_ids, resolved_activity_id, is_active = await _resolve_brainstorming_scope(
        meeting_id, meeting, activity_id
    )
    if not resolved_activity_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active brainstorming activity found.",
        )
    is_privileged = _assert_user_can_participate(
        meeting, current_user, allowed_ids
    )
    if not is_privileged and not is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This activity is not open yet.",
        )

    activity_config = _get_brainstorming_activity_config(
        resolved_activity_id, meeting
    )
    allow_anonymous = _coerce_bool(activity_config.get("allow_anonymous"))

    ideas_manager = IdeasManager()
    ideas = ideas_manager.get_ideas_for_activity(
        db, meeting_id, resolved_activity_id
    )
    logger.info(
        "brainstorming ideas fetched meeting=%s activity=%s count=%d",
        meeting_id,
        resolved_activity_id,
        len(ideas),
    )
    responses: List[BrainstormingIdeaResponse] = []
    for idea in ideas:
        idea_response = BrainstormingIdeaResponse.model_validate(idea)
        if allow_anonymous:
            idea_response = idea_response.model_copy(
                update={
                    "user_id": None,
                    "user_color": None,
                    "user_avatar_key": None,
                    "user_avatar_icon_path": None,
                    "submitted_name": "Anonymous",
                }
            )
        else:
            idea_response = idea_response.model_copy(
                update={
                    "user_color": getattr(getattr(idea, "author", None), "avatar_color", None),
                    "user_avatar_key": getattr(getattr(idea, "author", None), "avatar_key", None),
                    "user_avatar_icon_path": getattr(
                        getattr(idea, "author", None),
                        "avatar_icon_path",
                        None,
                    ),
                }
            )
        responses.append(idea_response)
    return responses
