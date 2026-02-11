from fastapi import APIRouter, Depends, HTTPException, status, Response, Query
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.schemas.meeting import (
    MeetingCreate,
    MeetingUpdate,
    MeetingResponse,
    MeetingStateSnapshot,
    PublicityType,
    MeetingDashboardResponse,
    DashboardMeetingStatus,
    MeetingControlRequest,
    MeetingControlResponse,
    MeetingControlAction,
    AgendaActivityCreate,
    AgendaActivityUpdate,
    AgendaActivityResponse,
    ActivityCatalogEntry,
    JoinMeetingRequest,
    JoinMeetingResponse,
    AgendaReorderPayload,
)
from app.models.user import User, UserRole
from app.models.meeting import AgendaActivity, Meeting
from app.models.idea import Idea
from app.models.activity_bundle import ActivityBundle
from app.models.voting import VotingVote
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.auth.auth import (
    get_current_user,
    get_optional_user_model_dependency,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    check_permission,
)
from app.config.loader import get_guest_join_enabled, get_secure_cookies_enabled
from app.schemas.schemas import Permission
from app.utils.security import get_password_hash
from fastapi import Request
from typing import List, Optional, Literal, Iterable, Set, Dict
from sqlalchemy import func
from datetime import datetime, timezone
from app.data.user_manager import UserManager, get_user_manager
import logging
from datetime import timedelta, UTC
from pydantic import BaseModel, Field, field_validator, model_validator
from app.services import meeting_state_manager
from app.plugins.context import ActivityContext
from app.plugins.registry import get_activity_registry
from app.services.activity_pipeline import ActivityPipeline
from app.services.transfer_source import get_transfer_count
from app.plugins.autosave import start_autosave, stop_autosave
from app.utils.websocket_manager import websocket_manager
from app.utils.user_colors import get_user_color
import json
import io
import zipfile

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


class MeetingCreatePayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    scheduled_datetime: Optional[datetime] = None
    agenda_items: List[str] = Field(default_factory=list)
    agenda: List[AgendaActivityCreate] = Field(default_factory=list)
    participant_contacts: List[str] = Field(default_factory=list)
    co_facilitator_ids: List[str] = Field(default_factory=list)
    participant_ids: List[str] = Field(default_factory=list)


class ParticipantAssignPayload(BaseModel):
    user_id: Optional[str] = None
    login: Optional[str] = None

    def resolve_login(self) -> Optional[str]:
        return self.login

    def resolve_user_id(self) -> Optional[str]:
        return self.user_id


class ParticipantBulkUpdatePayload(BaseModel):
    add: List[str] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)

    @field_validator("add", "remove", mode="before")
    @classmethod
    def _normalise_bulk_ids(cls, value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("Expected a list of user IDs")
        cleaned = []
        seen = set()
        for raw in value:
            identifier = (raw or "").strip()
            if identifier and identifier not in seen:
                seen.add(identifier)
                cleaned.append(identifier)
        return cleaned


class ActivityParticipantUpdatePayload(BaseModel):
    mode: Literal["all", "custom"] = "custom"
    participant_ids: Optional[List[str]] = Field(default=None)

    @field_validator("participant_ids", mode="before")
    @classmethod
    def _normalise_ids(cls, value):
        if value is None:
            return None
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("participant_ids must be a list")
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned

    @model_validator(mode="after")
    def _validate_mode(
        cls, values: "ActivityParticipantUpdatePayload"
    ) -> "ActivityParticipantUpdatePayload":
        if values.mode == "custom":
            ids = values.participant_ids or []
            if not ids:
                raise ValueError(
                    "participant_ids must include at least one member when mode is 'custom'"
                )
        else:
            values.participant_ids = None
        return values


class ActivityParticipantAssignment(BaseModel):
    activity_id: str
    mode: Literal["all", "custom"] = "all"
    participant_ids: List[str] = Field(default_factory=list)
    available_participants: List[dict] = Field(default_factory=list)


def _build_participant_summary(users: Iterable[User]) -> List[dict]:
    summary = []
    for user in users or []:
        if not getattr(user, "user_id", None):
            continue
        summary.append(
            {
                "user_id": user.user_id,
                "login": getattr(user, "login", None),
                "first_name": getattr(user, "first_name", None),
                "last_name": getattr(user, "last_name", None),
                "avatar_color": getattr(user, "avatar_color", None),
                "avatar_key": getattr(user, "avatar_key", None),
                "avatar_icon_path": getattr(user, "avatar_icon_path", None),
                "role": (
                    getattr(user.role, "value", user.role)
                    if getattr(user, "role", None)
                    else None
                ),
            }
        )
    summary.sort(
        key=lambda row: (
            row.get("first_name") or "",
            row.get("last_name") or "",
            row["user_id"],
        )
    )
    return summary


def _build_activity_participant_assignment(
    meeting, activity
) -> ActivityParticipantAssignment:
    config = dict(getattr(activity, "config", {}) or {})
    configured_ids = config.get("participant_ids")
    participant_ids: List[str] = []
    if isinstance(configured_ids, list):
        participant_ids = [
            str(pid).strip() for pid in configured_ids if str(pid).strip()
        ]

    mode: Literal["all", "custom"] = "custom" if participant_ids else "all"
    available = _build_participant_summary(getattr(meeting, "participants", []) or [])

    return ActivityParticipantAssignment(
        activity_id=activity.activity_id,
        mode=mode,
        participant_ids=participant_ids,
        available_participants=available,
    )


def _assert_meeting_access(
    meeting,
    user,
    require_facilitator: bool = False,
) -> None:
    facilitator_links = getattr(meeting, "facilitator_links", []) or []
    participants = getattr(meeting, "participants", []) or []

    is_admin = user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
    is_owner = meeting.owner_id == user.user_id
    is_facilitator = any(link.user_id == user.user_id for link in facilitator_links)
    is_participant = any(person.user_id == user.user_id for person in participants)

    if require_facilitator:
        if not (is_admin or is_owner or is_facilitator):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only facilitators can modify the meeting agenda.",
            )
        return

    if not (is_admin or is_owner or is_facilitator or is_participant):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to access this meeting",
        )


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    cleaned = str(value).strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _build_user_export(user: Optional[User]) -> Dict[str, Optional[str]]:
    if not user:
        return {}
    return {
        "user_id": user.user_id,
        "login": user.login,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


def _resolve_import_user_id(
    entry: Optional[Dict[str, Optional[str]]], user_manager: UserManager
) -> Optional[str]:
    if not entry:
        return None
    user_id = entry.get("user_id")
    if user_id:
        user = user_manager.get_user_by_id(user_id)
        if user:
            return user.user_id
    email = entry.get("email")
    if email:
        user = user_manager.get_user_by_email(email)
        if user:
            return user.user_id
    login = entry.get("login")
    if login:
        user = user_manager.get_user_by_login(login)
        if user:
            return user.user_id
    return None


def _resolve_import_title(db, base_title: str) -> str:
    trimmed = (base_title or "").strip()
    base = trimmed if trimmed else "Imported Meeting"
    existing = db.query(Meeting).filter(Meeting.title == base).first()
    if not existing:
        return base
    date_suffix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidate = f"{base} (Imported {date_suffix})"
    if not db.query(Meeting).filter(Meeting.title == candidate).first():
        return candidate
    counter = 2
    while True:
        candidate = f"{base} (Imported {date_suffix} {counter})"
        if not db.query(Meeting).filter(Meeting.title == candidate).first():
            return candidate
        counter += 1


async def _broadcast_agenda_update(
    meeting_id: str,
    initiator_id: str,
    meeting_manager: MeetingManager,
) -> None:
    """Helper to fetch the latest agenda and broadcast it."""
    updated_agenda_items = meeting_manager.list_agenda(meeting_id)
    _apply_activity_lock_metadata(meeting_id, meeting_manager, updated_agenda_items)
    _apply_transfer_counts(meeting_id, meeting_manager, updated_agenda_items)
    # Convert to Pydantic models for consistent output
    payload = [
        AgendaActivityResponse.model_validate(item).model_dump()
        for item in updated_agenda_items
    ]
    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "agenda_update",
            "payload": payload,
            "meta": {
                "initiatorId": initiator_id,
            },
        },
    )


def _apply_transfer_counts(
    meeting_id: str,
    meeting_manager: MeetingManager,
    agenda_items: Iterable[AgendaActivity],
) -> None:
    db = meeting_manager.db
    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        return

    idea_counts = {
        activity_id: int(count or 0)
        for activity_id, count in db.query(Idea.activity_id, func.count(Idea.id))
        .filter(
            Idea.meeting_id == meeting_id,
            Idea.activity_id.isnot(None),
            Idea.parent_id.is_(None),
        )
        .group_by(Idea.activity_id)
        .all()
        if activity_id
    }

    bundle_counts: Dict[str, int] = {}
    bundles = (
        db.query(ActivityBundle)
        .filter(
            ActivityBundle.meeting_id == meeting_id,
            ActivityBundle.kind == "output",
        )
        .order_by(ActivityBundle.created_at.desc(), ActivityBundle.id.desc())
        .all()
    )
    for bundle in bundles:
        activity_id = bundle.activity_id
        if not activity_id or activity_id in bundle_counts:
            continue
        items = bundle.items if isinstance(bundle.items, list) else []
        bundle_counts[activity_id] = len(items)

    for item in agenda_items:
        count, source = get_transfer_count(
            db,
            meeting,
            item,
            idea_counts=idea_counts,
            bundle_counts=bundle_counts,
        )
        setattr(item, "transfer_count", int(count or 0))
        setattr(item, "transfer_source", source)
        if count <= 0:
            tool_type = (getattr(item, "tool_type", "") or "").lower()
            reason = (
                "No ideas to transfer yet."
                if tool_type == "brainstorming"
                else "No transferable output yet."
            )
            setattr(item, "transfer_reason", reason)
        else:
            setattr(item, "transfer_reason", None)


def _apply_activity_lock_metadata(
    meeting_id: str,
    meeting_manager: MeetingManager,
    agenda_items: Iterable[AgendaActivity],
) -> None:
    lock_flags = meeting_manager.get_activity_lock_flags(meeting_id)
    parallel_locked_keys = [
        "mode",
        "single_assignment_only",
        "agreement_threshold",
        "margin_threshold",
        "minimum_ballots",
        "tie_policy",
        "missing_vote_handling",
        "private_until_reveal",
        "allow_unsorted_submission",
    ]

    for item in agenda_items:
        activity_id = getattr(item, "activity_id", None)
        flags = lock_flags.get(activity_id or "", {})
        has_live_data = bool(flags.get("has_live_data"))
        has_votes = bool(flags.get("has_votes"))
        has_submitted_ballots = bool(flags.get("has_submitted_ballots"))
        tool_type = str(getattr(item, "tool_type", "") or "").lower()

        locked_config_keys: List[str] = []
        if tool_type == "voting" and has_votes:
            locked_config_keys.extend(["options", "max_votes", "max_votes_per_option"])
        if tool_type == "categorization":
            if has_live_data:
                locked_config_keys.extend(["items", "buckets"])
            if has_submitted_ballots:
                locked_config_keys.extend(parallel_locked_keys)

        deduped = list(dict.fromkeys(locked_config_keys))
        setattr(item, "has_data", has_live_data)
        setattr(item, "has_votes", has_votes)
        setattr(item, "has_submitted_ballots", has_submitted_ballots)
        setattr(item, "locked_config_keys", deduped)


def _format_conflicting_users(user_manager: UserManager, user_ids: Iterable[str]):
    """Build a lightweight descriptor list for conflicting participants."""
    details = []
    for user_id in user_ids:
        user_obj = user_manager.get_user_by_id(user_id)
        if user_obj:
            display_name = (
                f"{(user_obj.first_name or '').strip()} {(user_obj.last_name or '').strip()}".strip()
                or user_obj.login
                or user_id
            )
            details.append(
                {
                    "user_id": user_obj.user_id,
                    "login": user_obj.login,
                    "display_name": display_name,
                }
            )
        else:
            details.append({"user_id": user_id, "display_name": "Unknown User"})
    return details


def _resolve_active_activity_state(snapshot: Optional[dict], activity_id: str):
    """
    Return (active_entry, is_current_activity, status, tool) for the requested activity id.
    """
    active_entry = None
    active_status = None
    active_tool = None
    if snapshot:
        active_entries = snapshot.get("activeActivities") or []
        if isinstance(active_entries, dict):
            active_entries = active_entries.values()
        for entry in active_entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("activityId") or entry.get("activity_id")
            if entry_id != activity_id:
                continue
            status = str(entry.get("status") or "").lower()
            if status in {"in_progress", "paused"}:
                active_entry = entry
                active_status = status
                active_tool = entry.get("tool")
                break
    is_current_activity = False
    if snapshot:
        current_activity_id = snapshot.get("currentActivity") or snapshot.get(
            "agendaItemId"
        )
        current_status = str(snapshot.get("status") or "").lower()
        is_current_activity = (
            current_activity_id == activity_id
            and current_status in {"in_progress", "paused"}
        )
        if not active_tool:
            active_tool = snapshot.get("currentTool")
        if not active_status and is_current_activity:
            active_status = current_status
    return active_entry, is_current_activity, active_status, active_tool


async def _apply_live_roster_patch(
    *,
    meeting_id: str,
    activity_id: str,
    desired_participant_ids: List[str],
    mode: Literal["all", "custom"],
    initiator_id: str,
    activity_tool: str,
    activity_elapsed: Optional[int],
    active_entry: Optional[dict],
    is_current_activity: bool,
    active_status: Optional[str] = None,
    started_at: Optional[datetime] = None,
):
    """
    Update the in-memory meeting state for an active activity roster and broadcast the change.
    """
    desired_ids_sorted = sorted({str(pid).strip() for pid in desired_participant_ids if str(pid).strip()})
    updated_metadata = dict((active_entry or {}).get("metadata") or {})
    updated_metadata["participantScope"] = "custom" if mode == "custom" else "all"
    updated_metadata.pop("participant_scope", None)
    updated_metadata.pop("participant_ids", None)
    updated_metadata["participantIds"] = desired_ids_sorted if mode == "custom" else []

    updated_entry = dict(active_entry or {})
    updated_entry["activityId"] = updated_entry.get("activityId") or activity_id
    updated_entry["tool"] = updated_entry.get("tool") or activity_tool
    updated_entry["participantIds"] = desired_ids_sorted
    updated_entry["metadata"] = updated_metadata

    status_value = str(
        updated_entry.get("status")
        or active_status
        or (active_entry or {}).get("status")
        or "in_progress"
    ).lower()
    updated_entry["status"] = status_value

    if "elapsedTime" not in updated_entry and activity_elapsed is not None:
        updated_entry["elapsedTime"] = activity_elapsed
    if "startedAt" not in updated_entry and started_at:
        started_at_value = started_at
        if started_at_value.tzinfo is None:
            started_at_value = started_at_value.replace(tzinfo=timezone.utc)
        updated_entry["startedAt"] = started_at_value.isoformat()

    patch: dict = {"activeActivities": {activity_id: updated_entry}}
    if is_current_activity:
        patch["metadata"] = updated_metadata

    _, snapshot = await meeting_state_manager.apply_patch(meeting_id, patch)
    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "meeting_state",
            "payload": snapshot,
            "meta": {
                "initiatorId": initiator_id,
                "action": "update_active_roster",
                "activityId": activity_id,
            },
        },
    )
    logger.info(
        "Live roster updated for meeting %s activity %s (mode=%s, count=%d) by %s",
        meeting_id,
        activity_id,
        mode,
        len(desired_ids_sorted),
        initiator_id,
    )
    return snapshot


@router.get("/active", response_model=List[MeetingResponse])
async def get_active_meetings(
    current_user: str = Depends(get_current_user),
    meeting_manager: MeetingManager = Depends(
        get_meeting_manager
    ),  # Inject MeetingManager
):
    """
    Retrieve all active meetings for the current user.
    """
    try:
        logger.debug(f"Fetching active meetings for user: {current_user}")
        # Removed await as get_active_meetings is synchronous
        meetings = meeting_manager.get_active_meetings()
        return [MeetingResponse.model_validate(meeting) for meeting in meetings]
    except Exception as e:
        logger.error(f"Error fetching active meetings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch active meetings",
        )


@router.post("/", response_model=MeetingResponse)
async def create_meeting(
    payload: MeetingCreatePayload,
    current_user: str = Depends(get_current_user),
    _: bool = Depends(check_permission(Permission.CREATE_MEETING)),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    try:
        # Get user info using injected user_manager and email
        user = user_manager.get_user_by_login(
            current_user
        )  # current_user is login extracted from JWT
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        logger.debug(f"Creating new meeting for user: {current_user}")

        start_dt = payload.scheduled_datetime
        end_dt = start_dt + timedelta(minutes=60) if start_dt else None

        agenda_payloads: List[AgendaActivityCreate] = list(payload.agenda or [])
        if not agenda_payloads and payload.agenda_items:
            for idx, title in enumerate(payload.agenda_items, start=1):
                if not title:
                    continue
                cleaned = title.strip()
                if not cleaned:
                    continue
                agenda_payloads.append(
                    AgendaActivityCreate(
                        tool_type="brainstorming",
                        title=cleaned,
                        order_index=idx,
                    )
                )

        participant_ids = []
        if payload.participant_ids:
            participant_ids = [
                pid
                for pid in (str(value).strip() for value in payload.participant_ids)
                if pid
            ]
            # Preserve order while removing duplicates
            seen = set()
            participant_ids = [
                pid for pid in participant_ids if not (pid in seen or seen.add(pid))
            ]

        meeting_request = MeetingCreate(
            title=payload.title,
            description=payload.description or "Meeting",
            start_time=start_dt,
            end_time=end_dt,
            duration_minutes=60,
            publicity=PublicityType.PUBLIC,
            owner_id=user.user_id,
            participant_ids=participant_ids,
            additional_facilitator_ids=[
                str(fid).strip()
                for fid in payload.co_facilitator_ids
                if str(fid).strip()
            ],
        )

        new_meeting = meeting_manager.create_meeting(
            meeting_request,
            user.user_id,
            agenda_items=agenda_payloads,
        )
        return MeetingResponse.model_validate(new_meeting)
    except Exception as e:
        logger.error(f"Error creating meeting: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create meeting",
        )


@router.put("/{meeting_id}/configuration", response_model=MeetingResponse)
async def update_meeting_configuration(
    meeting_id: str,
    payload: MeetingCreatePayload,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    try:
        user = user_manager.get_user_by_login(current_user)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        meeting = meeting_manager.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
            )

        facilitator_links = getattr(meeting, "facilitator_links", []) or []
        is_admin = user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
        is_owner = meeting.owner_id == user.user_id
        is_facilitator = any(link.user_id == user.user_id for link in facilitator_links)

        if not (is_admin or is_owner or is_facilitator):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update this meeting",
            )

        start_dt = payload.scheduled_datetime
        end_dt = start_dt + timedelta(minutes=60) if start_dt else None

        agenda_payloads: List[AgendaActivityCreate] = list(payload.agenda or [])
        if not agenda_payloads and payload.agenda_items:
            for idx, title in enumerate(payload.agenda_items, start=1):
                cleaned = (title or "").strip()
                if not cleaned:
                    continue
                agenda_payloads.append(
                    AgendaActivityCreate(
                        tool_type="brainstorming",
                        title=cleaned,
                        order_index=idx,
                    )
                )

        participant_ids = []
        if payload.participant_ids:
            participant_ids = [
                pid
                for pid in (str(value).strip() for value in payload.participant_ids)
                if pid
            ]
            seen = set()
            participant_ids = [
                pid for pid in participant_ids if not (pid in seen or seen.add(pid))
            ]

        updated_meeting = meeting_manager.update_meeting_configuration(
            meeting_id,
            title=payload.title,
            description=payload.description or "Meeting",
            start_time=start_dt,
            end_time=end_dt,
            participant_ids=participant_ids,
            agenda_items=agenda_payloads,
        )

        if getattr(updated_meeting, "started_at", None) and not getattr(
            updated_meeting, "start_time", None
        ):
            setattr(updated_meeting, "start_time", updated_meeting.started_at)

        return MeetingResponse.model_validate(updated_meeting)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating meeting configuration: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update meeting configuration",
        )


@router.get("/modules", response_model=List[ActivityCatalogEntry])
async def list_agenda_modules(
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> List[ActivityCatalogEntry]:
    """Expose the catalog of available agenda modules."""
    entries = meeting_manager.get_activity_catalog_entries()
    return [ActivityCatalogEntry.model_validate(entry) for entry in entries]


@router.get("/{meeting_id}/agenda", response_model=List[AgendaActivityResponse])
async def get_meeting_agenda(
    meeting_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> List[AgendaActivityResponse]:
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    _assert_meeting_access(meeting, user, require_facilitator=False)
    agenda_items = sorted(meeting.agenda_activities, key=lambda item: item.order_index)
    _apply_activity_lock_metadata(meeting_id, meeting_manager, agenda_items)
    _apply_transfer_counts(meeting_id, meeting_manager, agenda_items)
    return [AgendaActivityResponse.model_validate(item) for item in agenda_items]


@router.post(
    "/{meeting_id}/agenda",
    response_model=AgendaActivityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_meeting_agenda_item(
    meeting_id: str,
    agenda_item: AgendaActivityCreate,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> AgendaActivityResponse:
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    _assert_meeting_access(meeting, user)
    created = meeting_manager.add_agenda_activity(meeting_id, agenda_item)
    _apply_activity_lock_metadata(meeting_id, meeting_manager, [created])
    _apply_transfer_counts(meeting_id, meeting_manager, [created])

    # Broadcast agenda update
    await _broadcast_agenda_update(meeting_id, user.user_id, meeting_manager)

    return AgendaActivityResponse.model_validate(created)


@router.put(
    "/{meeting_id}/agenda/{activity_id}",
    response_model=AgendaActivityResponse,
)
async def update_meeting_agenda_item(
    meeting_id: str,
    activity_id: str,
    agenda_patch: AgendaActivityUpdate,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> AgendaActivityResponse:
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    _assert_meeting_access(meeting, user, require_facilitator=True)
    updated = meeting_manager.update_agenda_activity(
        meeting_id, activity_id, agenda_patch
    )
    _apply_activity_lock_metadata(meeting_id, meeting_manager, [updated])
    _apply_transfer_counts(meeting_id, meeting_manager, [updated])

    # Broadcast agenda update
    await _broadcast_agenda_update(meeting_id, user.user_id, meeting_manager)

    return AgendaActivityResponse.model_validate(updated)


@router.delete(
    "/{meeting_id}/agenda/{activity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_meeting_agenda_item(
    meeting_id: str,
    activity_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> Response:
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    _assert_meeting_access(meeting, user, require_facilitator=True)
    await meeting_manager.delete_agenda_activity(meeting_id, activity_id)  # Added await

    # Broadcast agenda update
    await _broadcast_agenda_update(meeting_id, user.user_id, meeting_manager)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{meeting_id}/agenda-reorder",
    response_model=List[AgendaActivityResponse],
)
async def reorder_meeting_agenda_items(
    meeting_id: str,
    payload: AgendaReorderPayload,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> List[AgendaActivityResponse]:
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    _assert_meeting_access(meeting, user, require_facilitator=True)
    reordered_agenda = meeting_manager.reorder_agenda_activities(
        meeting_id, payload.activity_ids
    )
    _apply_activity_lock_metadata(meeting_id, meeting_manager, reordered_agenda)
    _apply_transfer_counts(meeting_id, meeting_manager, reordered_agenda)

    # Broadcast agenda update
    await _broadcast_agenda_update(meeting_id, user.user_id, meeting_manager)

    return [AgendaActivityResponse.model_validate(item) for item in reordered_agenda]


# Participants administration
@router.get("/{meeting_id}/participants")
async def list_meeting_participants(
    meeting_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )
    _assert_meeting_access(meeting, user, require_facilitator=True)
    participants = meeting_manager.list_participants(meeting_id)
    return [
        {
            "user_id": p.user_id,
            "login": p.login,
            "first_name": getattr(p, "first_name", None),
            "last_name": getattr(p, "last_name", None),
            "role": getattr(p.role, "value", p.role),
        }
        for p in participants
    ]


@router.post("/{meeting_id}/participants", status_code=status.HTTP_200_OK)
async def add_meeting_participant(
    meeting_id: str,
    payload: ParticipantAssignPayload,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )
    _assert_meeting_access(meeting, user, require_facilitator=True)

    target_user: Optional[User] = None
    if payload.user_id:
        target_user = user_manager.get_user_by_id(payload.user_id)
    elif payload.login:
        target_user = user_manager.get_user_by_login(payload.login)
    else:
        raise HTTPException(status_code=400, detail="Provide user_id or login")

    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    updated = meeting_manager.add_participant(meeting_id, target_user)
    return {
        "meeting_id": updated.meeting_id,
        "participants": [
            {
                "user_id": p.user_id,
                "login": p.login,
                "first_name": getattr(p, "first_name", None),
                "last_name": getattr(p, "last_name", None),
                "role": getattr(p.role, "value", p.role),
            }
            for p in (updated.participants or [])
        ],
    }


@router.delete("/{meeting_id}/participants/{user_id}", status_code=status.HTTP_200_OK)
async def remove_meeting_participant(
    meeting_id: str,
    user_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )
    _assert_meeting_access(meeting, user, require_facilitator=True)

    updated = meeting_manager.remove_participant(meeting_id, user_id)
    return {
        "meeting_id": updated.meeting_id,
        "participants": [
            {
                "user_id": p.user_id,
                "login": p.login,
                "first_name": getattr(p, "first_name", None),
                "last_name": getattr(p, "last_name", None),
                "role": getattr(p.role, "value", p.role),
            }
            for p in (updated.participants or [])
        ],
    }


@router.post("/{meeting_id}/participants/bulk", status_code=status.HTTP_200_OK)
async def bulk_update_meeting_participants(
    meeting_id: str,
    payload: ParticipantBulkUpdatePayload,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )
    _assert_meeting_access(meeting, user, require_facilitator=True)

    updated_meeting, summary = meeting_manager.bulk_update_participants(
        meeting_id,
        add_user_ids=payload.add,
        remove_user_ids=payload.remove,
    )
    refreshed = meeting_manager.get_meeting(meeting_id) or updated_meeting
    return {
        "meeting_id": refreshed.meeting_id,
        "participants": _build_participant_summary(
            getattr(refreshed, "participants", []) or []
        ),
        "summary": summary,
    }


@router.get(
    "/{meeting_id}/agenda/{activity_id}/participants",
    response_model=ActivityParticipantAssignment,
)
async def get_activity_participant_assignment(
    meeting_id: str,
    activity_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> ActivityParticipantAssignment:
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    _assert_meeting_access(meeting, user, require_facilitator=True)

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
            status_code=status.HTTP_404_NOT_FOUND, detail="Agenda activity not found"
        )

    return _build_activity_participant_assignment(meeting, activity)


@router.put(
    "/{meeting_id}/agenda/{activity_id}/participants",
    response_model=ActivityParticipantAssignment,
)
async def update_activity_participant_assignment(
    meeting_id: str,
    activity_id: str,
    payload: ActivityParticipantUpdatePayload,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> ActivityParticipantAssignment:
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    _assert_meeting_access(meeting, user, require_facilitator=True)

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
            status_code=status.HTTP_404_NOT_FOUND, detail="Agenda activity not found"
        )

    meeting_participant_ids: Set[str] = {
        participant.user_id
        for participant in getattr(meeting, "participants", []) or []
        if participant.user_id
    }

    cleaned_ids: List[str] = []
    if payload.mode == "custom":
        for raw in payload.participant_ids or []:
            identifier = (raw or "").strip()
            if not identifier:
                continue
            if identifier not in meeting_participant_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User {identifier} is not part of this meeting and cannot be assigned.",
                )
            cleaned_ids.append(identifier)

    desired_set: Set[str] = (
        set(cleaned_ids) if payload.mode == "custom" else set(meeting_participant_ids)
    )

    snapshot = await meeting_state_manager.snapshot(meeting_id)
    active_entry, is_current_activity, active_status, active_tool = (
        _resolve_active_activity_state(snapshot, activity_id)
    )
    is_active = bool(active_entry or is_current_activity)

    # If the DB shows the activity has never started but the in-memory state thinks it is active,
    # treat that as stale state and clear it to avoid false collision blocks in tests/bootstraps.
    if is_active and getattr(activity, "started_at", None) is None:
        entry_started = False
        if isinstance(active_entry, dict):
            entry_started = bool(
                active_entry.get("startedAt")
                or active_entry.get("started_at")
            )
        if not entry_started:
            await meeting_state_manager.reset(meeting_id)
            snapshot = None
            active_entry = None
            is_current_activity = False
            active_status = None
            active_tool = None
            is_active = False

    if is_active and desired_set:
        conflicting_user_ids = await meeting_manager.check_participant_collisions(
            meeting_id,
            activity_id,
            desired_set,
        )
        if conflicting_user_ids:
            conflict_payload = {
                "conflicting_users": _format_conflicting_users(
                    user_manager, conflicting_user_ids
                ),
                "active_activity_id": snapshot.get("currentActivity")
                if snapshot
                else None,
            }
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "Updating this activity roster would create participant conflicts with another active activity.",
                    "conflict_details": conflict_payload,
                },
                headers={"X-Conflict-Details": json.dumps(conflict_payload)},
            )

    participant_ids = cleaned_ids if payload.mode == "custom" else None
    updated_activity = meeting_manager.set_activity_participants(
        meeting_id,
        activity_id,
        participant_ids,
    )
    # Refresh meeting to get latest participants ordering in response
    refreshed_meeting = meeting_manager.get_meeting(meeting_id) or meeting
    assignment = _build_activity_participant_assignment(
        refreshed_meeting, updated_activity
    )

    if is_active:
        desired_ids_sorted = (
            sorted(desired_set)
            if payload.mode == "custom"
            else sorted(meeting_participant_ids)
        )
        await _apply_live_roster_patch(
            meeting_id=meeting_id,
            activity_id=activity_id,
            desired_participant_ids=desired_ids_sorted,
            mode="custom" if payload.mode == "custom" else "all",
            initiator_id=user.user_id,
            activity_tool=active_tool or updated_activity.tool_type,
            activity_elapsed=getattr(updated_activity, "elapsed_duration", None),
            active_entry=active_entry,
            is_current_activity=is_current_activity,
            active_status=active_status,
            started_at=getattr(updated_activity, "started_at", None),
        )

    return assignment


@router.get("/", response_model=MeetingDashboardResponse)
async def list_meetings(
    current_user: str = Depends(get_current_user),
    role_scope: str = Query(
        "participant", enum=["participant", "facilitator", "all"], alias="role"
    ),
    status_filter: Optional[DashboardMeetingStatus] = Query(None, alias="status"),
    sort: str = Query("start_time", enum=["start_time", "status", "created"]),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Return meetings scoped to the authenticated user with dashboard metadata."""
    try:
        user = user_manager.get_user_by_login(current_user)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        status_value = status_filter.value if status_filter else None
        logger.debug(
            "Listing meetings for %s (role_scope=%s, status=%s, sort=%s)",
            current_user,
            role_scope,
            status_value,
            sort,
        )

        dashboard_payload = meeting_manager.get_dashboard_meetings(
            user=user,
            role_scope=role_scope,
            status_filter=status_value,
            sort=sort,
        )
        return MeetingDashboardResponse.model_validate(dashboard_payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing meetings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list meetings",
        )


@router.get("/{meeting_id}/export")
async def export_meeting(
    meeting_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    _assert_meeting_access(meeting, user, require_facilitator=True)

    facilitators = []
    for link in getattr(meeting, "facilitator_links", []) or []:
        payload = _build_user_export(link.user)
        payload["is_owner"] = link.is_owner
        facilitators.append(payload)

    participants = [
        _build_user_export(participant)
        for participant in getattr(meeting, "participants", []) or []
    ]

    agenda = []
    for activity in getattr(meeting, "agenda_activities", []) or []:
        agenda.append(
            {
                "activity_id": activity.activity_id,
                "tool_type": activity.tool_type,
                "title": activity.title,
                "instructions": activity.instructions,
                "order_index": activity.order_index,
                "config": dict(getattr(activity, "config", {}) or {}),
                "started_at": _serialize_datetime(activity.started_at),
                "stopped_at": _serialize_datetime(activity.stopped_at),
                "elapsed_duration": activity.elapsed_duration,
            }
        )

    ideas = meeting_manager.db.query(Idea).filter(Idea.meeting_id == meeting_id).all()
    votes = (
        meeting_manager.db.query(VotingVote)
        .filter(VotingVote.meeting_id == meeting_id)
        .all()
    )

    bundle = {
        "version": 1,
        "exported_at": _serialize_datetime(datetime.now(timezone.utc)),
        "meeting": {
            "meeting_id": meeting.meeting_id,
            "title": meeting.title,
            "description": meeting.description,
            "status": meeting.status,
            "is_public": meeting.is_public,
            "created_at": _serialize_datetime(meeting.created_at),
            "start_time": _serialize_datetime(meeting.started_at),
            "end_time": _serialize_datetime(meeting.end_time),
        },
        "facilitators": facilitators,
        "participants": participants,
        "agenda": agenda,
        "ideas": [
            {
                "id": idea.id,
                "content": idea.content,
                "parent_id": idea.parent_id,
                "timestamp": _serialize_datetime(idea.timestamp),
                "updated_at": _serialize_datetime(idea.updated_at),
                "meeting_id": idea.meeting_id,
                "activity_id": idea.activity_id,
                "user_id": idea.user_id,
                "user_color": get_user_color(user=idea.author),
                "submitted_name": idea.submitted_name,
            }
            for idea in ideas
        ],
        "votes": [
            {
                "vote_id": vote.vote_id,
                "meeting_id": vote.meeting_id,
                "activity_id": vote.activity_id,
                "user_id": vote.user_id,
                "option_id": vote.option_id,
                "option_label": vote.option_label,
                "weight": vote.weight,
                "created_at": _serialize_datetime(vote.created_at),
            }
            for vote in votes
        ],
    }

    payload = json.dumps(bundle, indent=2, ensure_ascii=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("meeting.json", payload)
    buffer.seek(0)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"meeting_{meeting.meeting_id}_{timestamp}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=MeetingResponse)
async def import_meeting(
    request: Request,
    current_user: str = Depends(get_current_user),
    _: bool = Depends(check_permission(Permission.CREATE_MEETING)),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/"):
        try:
            form = await request.form()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="There was an error parsing the body.",
            ) from exc
        uploaded = form.get("file")
        if not uploaded or not hasattr(uploaded, "read"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Import file is missing",
            )
        raw_bytes = await uploaded.read()
    else:
        raw_bytes = await request.body()
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Import file is empty")

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw_bytes))
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid zip file"
        ) from exc

    json_name = next(
        (name for name in archive.namelist() if name.lower().endswith(".json")), None
    )
    if not json_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meeting bundle is missing a JSON export",
        )

    try:
        export_payload = json.loads(archive.read(json_name).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON export"
        ) from exc

    meeting_payload = export_payload.get("meeting", {}) or {}
    base_title = meeting_payload.get("title") or "Imported Meeting"
    title = _resolve_import_title(meeting_manager.db, base_title)
    description = meeting_payload.get("description") or "Meeting"
    is_public = bool(meeting_payload.get("is_public"))

    source_start = _parse_datetime(meeting_payload.get("start_time"))
    source_end = _parse_datetime(meeting_payload.get("end_time"))
    duration_minutes = 60
    if source_start and source_end:
        duration = int((source_end - source_start).total_seconds() // 60)
        if duration > 0:
            duration_minutes = duration

    new_start = datetime.now(UTC)
    new_end = new_start + timedelta(minutes=duration_minutes)

    participants = []
    for entry in export_payload.get("participants", []) or []:
        resolved = _resolve_import_user_id(entry, user_manager)
        if resolved and resolved != user.user_id:
            participants.append(resolved)
    seen_participants = set()
    participant_ids = [
        pid for pid in participants if not (pid in seen_participants or seen_participants.add(pid))
    ]

    facilitators = []
    for entry in export_payload.get("facilitators", []) or []:
        resolved = _resolve_import_user_id(entry, user_manager)
        if resolved and resolved != user.user_id:
            facilitators.append(resolved)
    seen_facilitators = set()
    facilitator_ids = [
        fid for fid in facilitators if not (fid in seen_facilitators or seen_facilitators.add(fid))
    ]

    agenda_payloads: List[AgendaActivityCreate] = []
    for entry in export_payload.get("agenda", []) or []:
        tool_type = (entry.get("tool_type") or "").strip()
        title_text = (entry.get("title") or "").strip()
        if not tool_type or not title_text:
            continue
        agenda_payloads.append(
            AgendaActivityCreate(
                tool_type=tool_type,
                title=title_text,
                instructions=entry.get("instructions"),
                order_index=entry.get("order_index"),
                config=entry.get("config") if isinstance(entry.get("config"), dict) else {},
                started_at=_parse_datetime(entry.get("started_at")),
                stopped_at=_parse_datetime(entry.get("stopped_at")),
            )
        )

    meeting_request = MeetingCreate(
        title=title,
        description=description,
        start_time=new_start,
        end_time=new_end,
        duration_minutes=duration_minutes,
        publicity=PublicityType.PUBLIC if is_public else PublicityType.PRIVATE,
        owner_id=user.user_id,
        participant_ids=participant_ids,
        additional_facilitator_ids=facilitator_ids,
    )

    try:
        new_meeting = meeting_manager.create_meeting(
            meeting_request,
            user.user_id,
            agenda_items=agenda_payloads,
        )

        new_agenda = meeting_manager.list_agenda(new_meeting.meeting_id)
        agenda_by_order = {item.order_index: item.activity_id for item in new_agenda}
        agenda_by_title = {
            (item.title or "").strip().lower(): item.activity_id for item in new_agenda
        }

        activity_map: Dict[str, str] = {}
        for entry in export_payload.get("agenda", []) or []:
            old_id = entry.get("activity_id")
            if not old_id:
                continue
            order_index = entry.get("order_index")
            mapped = agenda_by_order.get(order_index)
            if not mapped:
                title_key = (entry.get("title") or "").strip().lower()
                mapped = agenda_by_title.get(title_key)
            if mapped:
                activity_map[old_id] = mapped

        idea_id_map: Dict[int, int] = {}
        idea_parent_links: List[Dict[str, int]] = []
        for idea in export_payload.get("ideas", []) or []:
            content = (idea.get("content") or "").strip()
            if not content:
                continue
            old_id = idea.get("id")
            old_parent_id = idea.get("parent_id")
            old_activity_id = idea.get("activity_id")
            mapped_activity = activity_map.get(old_activity_id)
            raw_user_id = idea.get("user_id")
            resolved_user_id = None
            if raw_user_id:
                resolved_user = user_manager.get_user_by_id(raw_user_id)
                if resolved_user:
                    resolved_user_id = resolved_user.user_id

            db_idea = Idea(
                content=content,
                parent_id=None,
                meeting_id=new_meeting.meeting_id,
                activity_id=mapped_activity,
                user_id=resolved_user_id,
                submitted_name=idea.get("submitted_name"),
            )
            timestamp = _parse_datetime(idea.get("timestamp"))
            if timestamp:
                db_idea.timestamp = timestamp
            meeting_manager.db.add(db_idea)
            meeting_manager.db.flush()

            if isinstance(old_id, int):
                idea_id_map[old_id] = db_idea.id
            if isinstance(old_parent_id, int):
                idea_parent_links.append(
                    {"child_id": db_idea.id, "parent_id": old_parent_id}
                )

        for link in idea_parent_links:
            parent_new_id = idea_id_map.get(link["parent_id"])
            if not parent_new_id:
                continue
            meeting_manager.db.query(Idea).filter(Idea.id == link["child_id"]).update(
                {"parent_id": parent_new_id}
            )

        for vote in export_payload.get("votes", []) or []:
            old_activity_id = vote.get("activity_id")
            mapped_activity = activity_map.get(old_activity_id)
            if not mapped_activity:
                continue
            raw_user_id = vote.get("user_id")
            if not raw_user_id:
                continue
            resolved_user = user_manager.get_user_by_id(raw_user_id)
            if not resolved_user:
                continue

            db_vote = VotingVote(
                meeting_id=new_meeting.meeting_id,
                activity_id=mapped_activity,
                user_id=resolved_user.user_id,
                option_id=vote.get("option_id") or "",
                option_label=vote.get("option_label") or "",
                weight=int(vote.get("weight") or 1),
            )
            created_at = _parse_datetime(vote.get("created_at"))
            if created_at:
                db_vote.created_at = created_at
            meeting_manager.db.add(db_vote)

        meeting_manager.db.commit()
        refreshed = meeting_manager.get_meeting(new_meeting.meeting_id) or new_meeting
        return MeetingResponse.model_validate(refreshed)
    except HTTPException:
        meeting_manager.db.rollback()
        raise
    except Exception as exc:
        meeting_manager.db.rollback()
        logger.error("Failed to import meeting: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to import meeting",
        ) from exc


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(
        get_user_manager
    ),  # Use get_user_manager dependency
    meeting_manager: MeetingManager = Depends(
        get_meeting_manager
    ),  # Inject MeetingManager
):
    try:
        # Get user info using injected user_manager and email
        user = user_manager.get_user_by_login(current_user)  # Removed db parameter
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Implement meeting fetching logic using injected meeting_manager
        meeting = meeting_manager.get_meeting(meeting_id)  # Removed await
        if not meeting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
            )

        facilitator_links = getattr(meeting, "facilitator_links", []) or []
        participants = getattr(meeting, "participants", []) or []
        is_admin = user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
        is_owner = meeting.owner_id == user.user_id
        is_facilitator = any(link.user_id == user.user_id for link in facilitator_links)
        is_participant = any(person.user_id == user.user_id for person in participants)
        if not (is_admin or is_owner or is_facilitator or is_participant):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions to view this meeting",
            )

        _apply_activity_lock_metadata(
            meeting_id,
            meeting_manager,
            getattr(meeting, "agenda_activities", []) or [],
        )
        _apply_transfer_counts(
            meeting_id, meeting_manager, getattr(meeting, "agenda_activities", []) or []
        )

        return MeetingResponse.model_validate(meeting)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_meeting: unexpected error %s (%s)", e, type(e))
        if isinstance(e, (HTTPException, StarletteHTTPException)):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/{meeting_id}/state", response_model=MeetingStateSnapshot)
async def get_meeting_state(
    meeting_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    _assert_meeting_access(meeting, user, require_facilitator=False)

    state = await meeting_state_manager.get_or_create(meeting_id)
    payload = state.to_payload()
    return MeetingStateSnapshot(**payload)


@router.put("/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(
    meeting_id: str,
    meeting: MeetingUpdate,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(
        get_user_manager
    ),  # Use get_user_manager dependency
    meeting_manager: MeetingManager = Depends(
        get_meeting_manager
    ),  # Inject MeetingManager
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    existing_meeting = meeting_manager.get_meeting(meeting_id)
    if not existing_meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    facilitator_links = getattr(existing_meeting, "facilitator_links", []) or []
    is_admin = user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
    is_owner = existing_meeting.owner_id == user.user_id
    is_facilitator = any(link.user_id == user.user_id for link in facilitator_links)

    if not (is_admin or is_owner or is_facilitator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to update this meeting",
        )

    update_payload = meeting.model_dump(exclude_unset=True)
    if is_facilitator and not (is_admin or is_owner):
        restricted_fields = {"owner_id", "facilitator_ids"}
        attempted = restricted_fields.intersection(update_payload.keys())
        if attempted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Co-facilitators cannot modify meeting ownership or facilitator roster.",
            )

    updated_meeting = meeting_manager.update_meeting(meeting_id, update_payload)
    if not updated_meeting:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update meeting",
        )
    return MeetingResponse.model_validate(updated_meeting)


@router.post("/{meeting_id}/control", response_model=MeetingControlResponse)
async def control_meeting(
    meeting_id: str,
    control: MeetingControlRequest,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    """Allow facilitators to start/stop/pause/resume collaborative tools and broadcast state."""
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )

    facilitator_links = getattr(meeting, "facilitator_links", []) or []
    is_admin = user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
    is_owner = meeting.owner_id == user.user_id
    is_facilitator = any(link.user_id == user.user_id for link in facilitator_links)

    if not (is_admin or is_owner or is_facilitator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only facilitators can control meeting tools.",
        )

    patch: dict = {}
    metadata_patch = dict(control.metadata or {})
    activity_to_control = None  # Will store the AgendaActivity object

    # Helper to find the activity based on control.activityId
    if control.activityId:
        activity_to_control = next(
            (
                a
                for a in meeting.agenda_activities
                if a.activity_id == control.activityId
            ),
            None,
        )
        if not activity_to_control:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Activity with ID '{control.activityId}' not found in meeting agenda.",
            )

    current_time_utc = datetime.now(timezone.utc)
    current_meeting_state = await meeting_state_manager.snapshot(
        meeting_id
    )  # Moved this line

    def _resolve_participant_ids_for_activity(
        activity, default_ids: Optional[Iterable[str]] = None
    ) -> List[str]:
        """Resolve participant ids for an activity, preferring live state metadata, then provided defaults, then config/all."""
        # 1) Live state (preserves custom scopes from previous start)
        if current_meeting_state:
            active_entries = current_meeting_state.get("activeActivities") or []
            if isinstance(active_entries, dict):
                active_entries = active_entries.values()
            for entry in active_entries:
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("activityId") or entry.get("activity_id")
                if entry_id == getattr(activity, "activity_id", None):
                    ids = entry.get("participantIds") or entry.get("participant_ids")
                    if isinstance(ids, list) and ids:
                        cleaned = [str(pid).strip() for pid in ids if str(pid).strip()]
                        if cleaned:
                            return sorted(set(cleaned))
                    break

        # 2) Explicit metadata on the incoming control payload
        meta_ids = metadata_patch.get("participantIds") or metadata_patch.get(
            "participant_ids"
        )
        if isinstance(meta_ids, list) and meta_ids:
            cleaned = [str(pid).strip() for pid in meta_ids if str(pid).strip()]
            if cleaned:
                return sorted(set(cleaned))

        # 3) Default provided by caller (e.g., computed during start)
        if default_ids:
            cleaned = [str(pid).strip() for pid in default_ids if str(pid).strip()]
            if cleaned:
                return sorted(set(cleaned))

        # 4) Activity config
        config = dict(getattr(activity, "config", {}) or {})
        raw_ids = config.get("participant_ids")
        if isinstance(raw_ids, list) and raw_ids:
            cleaned = [str(pid).strip() for pid in raw_ids if str(pid).strip()]
            if cleaned:
                return sorted(set(cleaned))

        # 5) Fall back to all meeting participants
        all_meeting_participants = meeting_manager.list_participants(meeting_id)
        return sorted({p.user_id for p in all_meeting_participants})

    if control.action == MeetingControlAction.START_TOOL:
        if not control.activityId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="activityId must be provided to start a tool.",
            )

        # Determine participants for the activity being started
        activity_config = activity_to_control.config or {}
        new_activity_participant_ids_raw = activity_config.get("participant_ids")
        default_participants: Set[str] = set()
        if new_activity_participant_ids_raw:
            default_participants = {str(pid).strip() for pid in new_activity_participant_ids_raw if str(pid).strip()}
        else:  # "all" mode, so all meeting participants are involved
            all_meeting_participants = meeting_manager.list_participants(meeting_id)
            default_participants = {p.user_id for p in all_meeting_participants}

        resolved_participants = _resolve_participant_ids_for_activity(
            activity_to_control, default_participants
        )
        new_activity_participant_ids: Set[str] = set(resolved_participants)

        # Check for collisions
        conflicting_user_ids = await meeting_manager.check_participant_collisions(
            meeting_id,
            control.activityId,
            new_activity_participant_ids,
        )

        if conflicting_user_ids:
            # Fetch user details for the conflicting IDs
            conflicting_users_details = []
            for user_id in conflicting_user_ids:
                user_obj = user_manager.get_user_by_id(user_id)
                if user_obj:
                    conflicting_users_details.append(
                        {
                            "user_id": user_obj.user_id,
                            "login": user_obj.login,
                            "display_name": f"{user_obj.first_name} {user_obj.last_name}".strip()
                            or user_obj.login,
                        }
                    )
                else:
                    conflicting_users_details.append(
                        {"user_id": user_id, "display_name": "Unknown User"}
                    )

            conflict_payload = {
                "conflicting_users": conflicting_users_details,
                "active_activity_id": current_meeting_state.get("currentActivity"),
            }
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "Starting this activity would create participant conflicts with an already active activity.",
                    "conflict_details": conflict_payload,
                },
                headers={"X-Conflict-Details": json.dumps(conflict_payload)},
            )

        patch["currentTool"] = control.tool
        patch["status"] = "in_progress"  # Always in_progress when starting
        patch["currentActivity"] = control.activityId
        patch["agendaItemId"] = (
            control.activityId
        )  # Redundant but kept for compatibility

        if activity_to_control:
            activity_to_control.started_at = current_time_utc
            activity_to_control.stopped_at = None
            # Preserve any previously accumulated elapsed_duration so multiple runs accumulate
            meeting_manager.db.commit()
            meeting_manager.db.refresh(activity_to_control)
            registry = get_activity_registry()
            plugin = registry.get_plugin(activity_to_control.tool_type)
            if plugin:
                pipeline = ActivityPipeline(meeting_manager.db)
                input_bundle = pipeline.ensure_input_bundle(meeting, activity_to_control)
                context = ActivityContext(
                    db=meeting_manager.db,
                    meeting=meeting,
                    activity=activity_to_control,
                    user=user,
                    logger=logger,
                )
                try:
                    plugin.open_activity(context, input_bundle)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "Failed to open activity plugin %s: %s",
                        activity_to_control.tool_type,
                        exc,
                    )
                try:
                    autosave_seconds = plugin.get_autosave_seconds(
                        dict(activity_to_control.config or {})
                    )
                    if plugin.snapshot_activity(context):
                        start_autosave(
                            plugin,
                            meeting.meeting_id,
                            activity_to_control.activity_id,
                            user.user_id,
                            autosave_seconds,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "Failed to start autosave for %s: %s",
                        activity_to_control.tool_type,
                        exc,
                    )

        # Default scopes to "all" when none are provided so stale custom scopes don't linger
        scope = str(
            metadata_patch.get("participantScope")
            or metadata_patch.get("participant_scope")
            or ""
        ).lower()
        if not scope:
            metadata_patch["participantScope"] = "all"
            metadata_patch.pop("participant_scope", None)
            metadata_patch["participantIds"] = []
            metadata_patch.pop("participant_ids", None)
        elif scope == "custom" and not (
            metadata_patch.get("participantIds")
            or metadata_patch.get("participant_ids")
        ):
            metadata_patch["participantIds"] = []
        elif scope != "custom":
            # Normalise to all when scope is any non-custom value
            metadata_patch["participantScope"] = "all"
            metadata_patch.pop("participant_scope", None)
            metadata_patch["participantIds"] = []
            metadata_patch.pop("participant_ids", None)
        activity_participant_ids_list = sorted(new_activity_participant_ids, key=lambda pid: str(pid))

        activity_state = {
            "activityId": control.activityId,
            "tool": control.tool,
            "status": "in_progress",
            "metadata": dict(metadata_patch),
            "participantIds": activity_participant_ids_list,
            "startedAt": current_time_utc.isoformat(),
            "stoppedAt": None,
            "elapsedTime": activity_to_control.elapsed_duration,
        }
        patch["activeActivities"] = {control.activityId: activity_state}

    elif control.action == MeetingControlAction.PAUSE_TOOL:
        if not activity_to_control: # Must have an active activity to pause
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active activity to pause.")

        if activity_to_control.started_at is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Activity has not been started yet to be paused.")
        
        patch["status"] = "paused"
        # Update stopped_at and accumulate elapsed time
        if activity_to_control.started_at:
            started_at = activity_to_control.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            time_spent = (current_time_utc - started_at).total_seconds()
            activity_to_control.elapsed_duration = (activity_to_control.elapsed_duration or 0) + int(time_spent)
            activity_to_control.stopped_at = current_time_utc # Mark as stopped (paused)
            activity_to_control.started_at = None # Clear started_at to indicate it's not running
            meeting_manager.db.commit()
            meeting_manager.db.refresh(activity_to_control)
            participant_scope_ids = _resolve_participant_ids_for_activity(
                activity_to_control
            )
            patch["activeActivities"] = {
                activity_to_control.activity_id: {
                    "activityId": activity_to_control.activity_id,
                    "tool": control.tool or activity_to_control.tool_type,
                    "status": "paused",
                    "metadata": dict(metadata_patch),
                    "participantIds": participant_scope_ids,
                    "startedAt": None,
                    "stoppedAt": current_time_utc.isoformat(),
                    "elapsedTime": activity_to_control.elapsed_duration,
                }
            }
        stop_autosave(activity_to_control.activity_id)

    elif control.action == MeetingControlAction.RESUME_TOOL:
        if not activity_to_control: # Must have a selected activity to resume
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No activity to resume.")
        
        # Resume means it was paused, so it should have an accumulated elapsed_duration
        patch["status"] = "in_progress"
        activity_to_control.started_at = current_time_utc
        if activity_to_control.started_at.tzinfo is None:
             activity_to_control.started_at = activity_to_control.started_at.replace(tzinfo=timezone.utc)
        activity_to_control.stopped_at = None # Clear stopped_at
        meeting_manager.db.commit()
        meeting_manager.db.refresh(activity_to_control)
        participant_scope_ids = _resolve_participant_ids_for_activity(
            activity_to_control
        )
        patch["activeActivities"] = {
            activity_to_control.activity_id: {
                "activityId": activity_to_control.activity_id,
                "tool": control.tool or activity_to_control.tool_type,
                "status": "in_progress",
                "metadata": dict(metadata_patch),
                "participantIds": participant_scope_ids,
                "startedAt": current_time_utc.isoformat(),
                "stoppedAt": None,
                "elapsedTime": activity_to_control.elapsed_duration,
            }
        }
        registry = get_activity_registry()
        plugin = registry.get_plugin(activity_to_control.tool_type)
        if plugin:
            context = ActivityContext(
                db=meeting_manager.db,
                meeting=meeting,
                activity=activity_to_control,
                user=user,
                logger=logger,
            )
            try:
                autosave_seconds = plugin.get_autosave_seconds(
                    dict(activity_to_control.config or {})
                )
                if plugin.snapshot_activity(context):
                    start_autosave(
                        plugin,
                        meeting.meeting_id,
                        activity_to_control.activity_id,
                        user.user_id,
                        autosave_seconds,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Failed to resume autosave for %s: %s",
                    activity_to_control.tool_type,
                    exc,
                )

    elif control.action == MeetingControlAction.STOP_TOOL:
        # Determine which activity to stop: explicitly provided or currently active
        activity_id_to_stop = control.activityId
        if activity_id_to_stop is None:
            # Get currently active activity from meeting state if not provided
            
            if current_meeting_state: # Use the already fetched state
                activity_id_to_stop = current_meeting_state.get("currentActivity")
        
        if activity_id_to_stop is not None:
            patch["currentActivity"] = None # Clear active tool
            patch["agendaItemId"] = None # Clear active agenda item
            patch["currentTool"] = None # Clear current tool
            patch["status"] = "completed" # Status for a fully stopped activity
            
            activity_to_control = next(
                (a for a in meeting.agenda_activities if a.activity_id == activity_id_to_stop),
                None,
            )
            if activity_to_control:
                if activity_to_control.started_at: # If it was running before stop
                    started_at = activity_to_control.started_at
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    time_spent = (current_time_utc - started_at).total_seconds()
                    activity_to_control.elapsed_duration = (activity_to_control.elapsed_duration or 0) + int(time_spent)
                activity_to_control.stopped_at = current_time_utc
                activity_to_control.started_at = None # Ensure it's not marked as started
                # elapsed_duration is kept for results, not reset here
                meeting_manager.db.commit()
                meeting_manager.db.refresh(activity_to_control)
                registry = get_activity_registry()
                plugin = registry.get_plugin(activity_to_control.tool_type)
                if plugin:
                    context = ActivityContext(
                        db=meeting_manager.db,
                        meeting=meeting,
                        activity=activity_to_control,
                        user=user,
                        logger=logger,
                    )
                    try:
                        plugin.close_activity(context)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception(
                            "Failed to close activity plugin %s: %s",
                            activity_to_control.tool_type,
                            exc,
                        )
                patch["activeActivities"] = {activity_id_to_stop: None}
            stop_autosave(activity_id_to_stop)

        # Clear any lingering participant scope metadata on stop
        if not metadata_patch:
            metadata_patch = {"participantScope": "all", "participantIds": []}
        else:
            metadata_patch.setdefault("participantScope", "all")
            metadata_patch.setdefault("participantIds", [])
            metadata_patch.pop("participant_scope", None)
            metadata_patch.pop("participant_ids", None)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported action '{control.action}'.",
        )

    if metadata_patch:
        patch["metadata"] = metadata_patch

    # Always send elapsed duration in metadata to UI for current activity
    if activity_to_control:
        patch["metadata"] = patch.get("metadata", {})
        patch["metadata"]["elapsedTime"] = activity_to_control.elapsed_duration

    _, snapshot = await meeting_state_manager.apply_patch(meeting_id, patch)

    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "meeting_state",
            "payload": snapshot,
            "meta": {
                "initiatorId": user.user_id,
                "action": control.action.value,
            },
        },
    )

    return MeetingControlResponse(
        meetingId=meeting_id,
        action=control.action,
        state=snapshot,
    )


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(
        get_user_manager
    ),  # Use get_user_manager dependency
    meeting_manager: MeetingManager = Depends(
        get_meeting_manager
    ),  # Inject MeetingManager
):
    try:
        # Get user info using injected user_manager and email
        user = user_manager.get_user_by_login(current_user)  # Removed db parameter
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Implement meeting fetching logic using injected meeting_manager
        existing_meeting = meeting_manager.get_meeting(meeting_id)  # Removed await
        if not existing_meeting:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
            )

        is_admin = user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
        is_owner = existing_meeting.owner_id == user.user_id
        if not (is_admin or is_owner):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions to delete this meeting",
            )

        # Implement meeting deletion logic using injected meeting_manager
        success = meeting_manager.delete_meeting_permanently(
            meeting_id
        )  # Removed await
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete meeting",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/join", response_model=JoinMeetingResponse)
async def join_meeting_by_code(
    payload: JoinMeetingRequest,
    response: Response,
    request: Request,
    optional_user=Depends(get_optional_user_model_dependency),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
) -> JoinMeetingResponse:
    """
    Join a meeting by code. Supports authenticated users as usual.
    If unauthenticated and payload.as_guest is True, create a unique participant
    user (email optional), issue a session cookie, and join.
    """
    # Resolve current user model (optional)
    user = None
    if optional_user:
        # optional_user is a Pydantic schema; fetch full model via manager for consistency, or use minimal fields
        user = user_manager.get_user_by_login(optional_user.login)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
    else:
        # Unauthenticated path
        # Guest join is gated by config to keep meetings auth-only by default.
        if not get_guest_join_enabled():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        if not payload.as_guest:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )

        display_name = (payload.display_name or "Guest").strip()
        email = payload.email.strip().lower() if payload.email else None

        # Derive a unique login; prefer email localpart when provided
        import re
        import random

        def slugify(s: str) -> str:
            base = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
            return base or "guest"

        base_login = slugify(email.split("@")[0]) if email else slugify(display_name)
        candidate = base_login
        # Ensure uniqueness; add numeric suffix if needed
        attempts = 0
        while user_manager.login_exists(candidate):
            attempts += 1
            candidate = f"{base_login}_{random.randint(1000, 9999)}"
            if attempts > 50:
                candidate = f"guest_{random.randint(100000, 999999)}"
                break

        hashed_password = get_password_hash("guest-" + str(random.getrandbits(64)))
        try:
            user = user_manager.add_user(
                first_name=display_name,
                last_name="",
                email=email or None,
                hashed_password=hashed_password,
                role=UserRole.PARTICIPANT.value,
                login=candidate,
            )
            # Issue session cookie to authenticate subsequent requests
            access_token = create_access_token(
                data={"sub": user.login},
                expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            )
            response.set_cookie(
                key="access_token",
                value=f"Bearer {access_token}",
                httponly=True,
                secure=get_secure_cookies_enabled(),
                max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                samesite="lax",
                path="/",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create guest: {str(e)}",
            )

    meeting = meeting_manager.join_meeting_by_code(payload.meeting_code, user)

    # Optionally update display name if provided and empty
    if payload.display_name and not (user.first_name or user.last_name):
        user.first_name = payload.display_name
        user_manager.db.flush()
        user_manager.db.commit()

    redirect_url = f"/meeting/{meeting.meeting_id}"
    return JoinMeetingResponse(
        status="joined",
        meeting_id=meeting.meeting_id,
        redirect=redirect_url,
    )
