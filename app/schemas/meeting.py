from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Iterable, Any, Dict
from datetime import datetime, timedelta
from enum import Enum
from typing import Literal


class MeetingStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class PublicityType(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"


class ToolType(str, Enum):
    WHITEBOARD = "whiteboard"
    POLL = "poll"
    TIMER = "timer"
    CHAT = "chat"


class MeetingControlAction(str, Enum):
    START_TOOL = "start_tool"
    STOP_TOOL = "stop_tool"
    PAUSE_TOOL = "pause_tool"
    RESUME_TOOL = "resume_tool"


class DashboardMeetingStatus(str, Enum):
    NEVER_STARTED = "never_started"
    NOT_RUNNING = "not_running"
    RUNNING = "running"
    STOPPED = "stopped"


class MeetingBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=2000)
    start_time: Optional[datetime] = None
    duration_minutes: int = Field(..., gt=0, json_schema_extra={"example": 60})
    publicity: PublicityType = Field(PublicityType.PUBLIC)


def _format_user_display(user: Any) -> str:
    """Return a user-friendly display name for facilitator metadata."""
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    name = " ".join(part for part in (first, last) if part)
    if name:
        return name
    login = getattr(user, "login", None)
    if login:
        return login
    email = getattr(user, "email", None)
    if email:
        return email
    return "Unknown"


class MeetingCreate(MeetingBase):
    owner_id: str
    participant_ids: Optional[List[str]] = Field(default_factory=list)
    additional_facilitator_ids: Optional[List[str]] = Field(default_factory=list)
    end_time: Optional[datetime] = None

    @field_validator("participant_ids", mode="before")
    @classmethod
    def normalize_participant_ids(cls, value: Optional[Iterable]) -> List[str]:
        if value is None:
            return []
        return [str(pid).strip() for pid in value if str(pid).strip()]

    @field_validator("additional_facilitator_ids", mode="before")
    @classmethod
    def normalize_additional_facilitators(cls, value: Optional[Iterable]) -> List[str]:
        if not value:
            return []
        return [str(fid).strip() for fid in value if str(fid).strip()]

    @model_validator(mode="after")
    def ensure_end_time(cls, values: "MeetingCreate") -> "MeetingCreate":
        if values.end_time is None and values.start_time and values.duration_minutes:
            values.end_time = values.start_time + timedelta(
                minutes=values.duration_minutes
            )
        return values


class MeetingUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1, max_length=2000)
    start_time: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(
        None, gt=0, json_schema_extra={"example": 60}
    )
    publicity: Optional[PublicityType] = None
    participant_ids: Optional[List[str]] = None
    facilitator_ids: Optional[List[str]] = None
    owner_id: Optional[str] = None
    end_time: Optional[datetime] = None

    @field_validator("participant_ids", "facilitator_ids", mode="before")
    @classmethod
    def normalize_id_lists(cls, value: Optional[Iterable]) -> Optional[List[str]]:
        if value is None:
            return None
        normalised = [str(item).strip() for item in value if str(item).strip()]
        return normalised or None


class AgendaActivityBase(BaseModel):
    tool_type: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=200)
    instructions: Optional[str] = Field(None, max_length=2000)
    config: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None

    @field_validator("tool_type")
    @classmethod
    def normalise_tool_type(cls, value: str) -> str:
        trimmed = (value or "").strip().lower()
        if not trimmed:
            raise ValueError("tool_type is required")
        return trimmed

    @field_validator("config", mode="before")
    @classmethod
    def ensure_config_dict(cls, value: Optional[Any]) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise TypeError("config must be an object")

    @field_validator("instructions")
    @classmethod
    def trim_instructions(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class AgendaActivityCreate(AgendaActivityBase):
    order_index: Optional[int] = Field(None, ge=1)


class AgendaActivityUpdate(BaseModel):
    tool_type: Optional[str] = Field(None, min_length=1, max_length=50)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    instructions: Optional[str] = Field(None, max_length=2000)
    order_index: Optional[int] = Field(None, ge=1)
    config: Optional[Dict[str, Any]] = None

    @field_validator("tool_type")
    @classmethod
    def normalise_tool_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip().lower()
        if not trimmed:
            raise ValueError("tool_type cannot be blank")
        return trimmed

    @field_validator("config", mode="before")
    @classmethod
    def ensure_config_dict(cls, value: Optional[Any]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        raise TypeError("config must be an object")


class AgendaActivityResponse(AgendaActivityBase):
    meeting_id: str
    activity_id: str
    tool_config_id: str
    order_index: int = Field(..., ge=1)
    elapsed_duration: int = 0
    has_data: bool = False
    has_votes: bool = False
    has_submitted_ballots: bool = False
    locked_config_keys: List[str] = Field(default_factory=list)
    transfer_count: int = 0
    transfer_source: Optional[str] = None
    transfer_reason: Optional[str] = None

    model_config = {"from_attributes": True}


class AgendaReorderPayload(BaseModel):
    activity_ids: List[str] = Field(..., min_length=1)

    @field_validator("activity_ids", mode="before")
    @classmethod
    def normalise_ids(cls, value: Optional[Iterable]) -> List[str]:
        if value is None:
            raise ValueError("activity_ids cannot be None")
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("activity_ids cannot be empty")
        return cleaned


class MeetingFacilitatorSummary(BaseModel):
    id: Optional[str]
    user_id: Optional[str] = None
    name: str
    is_owner: bool = False


class MeetingResponse(BaseModel):
    meeting_id: str
    id: Optional[str] = None  # Legacy alias mirroring meeting_id
    title: str
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: str
    owner_id: str
    is_public: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    participant_ids: List[str] = Field(default_factory=list)
    facilitator_ids: List[str] = Field(default_factory=list)
    facilitator_user_ids: List[str] = Field(default_factory=list)
    facilitators: List["MeetingFacilitatorSummary"] = Field(default_factory=list)
    facilitator_names: List[str] = Field(default_factory=list)
    agenda: List["AgendaActivityResponse"] = Field(default_factory=list)

    model_config = {"from_attributes": True, "extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _attach_participant_ids(cls, data):
        def extract_ids(source):
            ids = []
            for participant in source or []:
                user_id = getattr(participant, "user_id", None)
                if user_id:
                    ids.append(user_id)
            # Preserve order while removing duplicates
            seen = set()
            return [pid for pid in ids if not (pid in seen or seen.add(pid))]

        if isinstance(data, dict):
            if not data.get("participant_ids"):
                candidate = data.get("participants")
                extracted = extract_ids(candidate)
                if extracted:
                    data["participant_ids"] = extracted
            return data

        participants = getattr(data, "participants", None)
        extracted = extract_ids(participants)
        if extracted:
            setattr(data, "participant_ids", extracted)
        return data

    @field_validator("facilitators", mode="before")
    @classmethod
    def _coerce_facilitators(cls, value: Any) -> List[dict]:
        if not value:
            return []

        coerced: List[dict] = []
        for item in value:
            if isinstance(item, dict):
                coerced.append(item)
                continue

            roster_id = getattr(item, "facilitator_id", None)
            user_id = getattr(item, "user_id", None)
            user_obj = getattr(item, "user", None)
            is_owner = bool(getattr(item, "is_owner", False))

            if user_id is None and hasattr(item, "user_id"):
                user_id = getattr(item, "user_id")

            display_source = user_obj or item
            coerced.append(
                {
                    "id": roster_id,
                    "user_id": user_id,
                    "name": _format_user_display(display_source),
                    "is_owner": is_owner,
                }
            )
        return coerced

    @model_validator(mode="after")
    def extract_relationships(cls, values: "MeetingResponse") -> "MeetingResponse":
        if not values.id:
            values.id = values.meeting_id

        extra = getattr(values, "model_extra", None) or getattr(
            values, "__pydantic_extra__", None
        )

        participants_attr = extra.get("participants") if extra else None
        if participants_attr:
            values.participant_ids = [
                getattr(participant, "user_id")
                for participant in participants_attr
                if hasattr(participant, "user_id")
            ]

        facilitator_links = extra.get("facilitator_links") if extra else None
        existing_facilitators = list(values.facilitators or [])
        if facilitator_links:
            summaries: List[MeetingFacilitatorSummary] = []
            facilitator_ids: List[str] = []
            facilitator_user_ids: List[str] = []
            facilitator_names: List[str] = []
            for link in facilitator_links:
                if isinstance(link, dict):
                    roster_id = link.get("facilitator_id") or link.get("id")
                    user_id = link.get("user_id")
                    name = link.get("name") or "Unknown"
                    summary = MeetingFacilitatorSummary(
                        id=roster_id,
                        user_id=user_id,
                        name=name,
                        is_owner=bool(link.get("is_owner", False)),
                    )
                else:
                    roster_id = getattr(link, "facilitator_id", None)
                    user_id = getattr(link, "user_id", None)
                    user_obj = getattr(link, "user", None)
                    name = _format_user_display(user_obj) if user_obj else "Unknown"
                    summary = MeetingFacilitatorSummary(
                        id=roster_id,
                        user_id=user_id,
                        name=name,
                        is_owner=bool(getattr(link, "is_owner", False)),
                    )
                summaries.append(summary)
                if roster_id:
                    facilitator_ids.append(roster_id)
                if user_id:
                    facilitator_user_ids.append(user_id)
                facilitator_names.append(name)
            values.facilitators = summaries
            values.facilitator_ids = list(dict.fromkeys(facilitator_ids))
            values.facilitator_user_ids = list(dict.fromkeys(facilitator_user_ids))
            values.facilitator_names = list(dict.fromkeys(facilitator_names))

            if values.owner_id:
                for summary in summaries:
                    if summary.user_id == values.owner_id:
                        summary.is_owner = True

        elif existing_facilitators:
            converted: List[MeetingFacilitatorSummary] = []
            seen_roster_ids: List[str] = []
            seen_user_ids: List[str] = []
            seen_names: List[str] = []

            for raw in existing_facilitators:
                summary = (
                    MeetingFacilitatorSummary(**raw) if isinstance(raw, dict) else raw
                )
                summary.is_owner = summary.user_id == values.owner_id
                converted.append(summary)

                if summary.id and summary.id not in seen_roster_ids:
                    seen_roster_ids.append(summary.id)
                if summary.user_id and summary.user_id not in seen_user_ids:
                    seen_user_ids.append(summary.user_id)
                if summary.name and summary.name not in seen_names:
                    seen_names.append(summary.name)

            values.facilitators = converted
            values.facilitator_ids = seen_roster_ids
            values.facilitator_user_ids = seen_user_ids
            values.facilitator_names = seen_names
        agenda_attr = getattr(values, "agenda_activities", None)
        if not agenda_attr and extra:
            agenda_attr = extra.get("agenda_activities")
        if agenda_attr:
            values.agenda = [
                AgendaActivityResponse.model_validate(item)  # type: ignore[arg-type]
                for item in agenda_attr
            ]
        return values


class ActivityCatalogEntry(BaseModel):
    tool_type: str
    label: str
    description: Optional[str] = None
    stem: str
    default_config: Dict[str, Any] = Field(default_factory=dict)
    reliability_policy: Dict[str, Any] = Field(default_factory=dict)


class MeetingStateSnapshot(BaseModel):
    meetingId: str
    status: Optional[str] = None
    currentActivity: Optional[str] = None
    currentTool: Optional[str] = None
    agendaItemId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    participants: List[str] = Field(default_factory=list)
    activeActivities: List[Dict[str, Any]] = Field(default_factory=list)
    updatedAt: Optional[str] = None


class MeetingControlRequest(BaseModel):
    action: MeetingControlAction
    tool: Optional[str] = None
    activityId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = None

    @model_validator(mode="after")
    def validate_action_payload(
        cls, values: "MeetingControlRequest"
    ) -> "MeetingControlRequest":
        if values.action == MeetingControlAction.START_TOOL and not values.tool:
            raise ValueError("tool must be provided when action is 'start_tool'")
        return values


class MeetingControlResponse(BaseModel):
    meetingId: str
    action: MeetingControlAction
    state: MeetingStateSnapshot


class MeetingQuickActions(BaseModel):
    enter: str
    details: str
    view_results: Optional[str] = None


class MeetingNotificationCounts(BaseModel):
    invitations: int = 0
    reminders: int = 0
    updates: int = 0
    announcements: int = 0
    total_unread: int = 0


class MeetingListItem(BaseModel):
    id: str
    meeting_id: str
    owner_id: str
    title: str
    status: DashboardMeetingStatus
    raw_status: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: Optional[datetime] = None
    description_snippet: str
    facilitator: MeetingFacilitatorSummary
    facilitators: List[MeetingFacilitatorSummary] = Field(default_factory=list)
    facilitator_names: List[str] = Field(default_factory=list)
    is_facilitator: bool
    is_participant: bool
    is_public: bool
    participant_count: int = 0
    quick_actions: MeetingQuickActions
    notifications: MeetingNotificationCounts


class MeetingListFilters(BaseModel):
    role_scope: Literal["participant", "facilitator", "all"] = "participant"
    status: Optional[DashboardMeetingStatus] = None
    sort: Literal["start_time", "status", "created"] = "start_time"


class MeetingDashboardSummary(BaseModel):
    total: int
    never_started: int
    not_running: int
    running: int
    stopped: int
    notifications: MeetingNotificationCounts


class MeetingDashboardResponse(BaseModel):
    items: List[MeetingListItem]
    summary: MeetingDashboardSummary
    filters: MeetingListFilters


class JoinMeetingRequest(BaseModel):
    meeting_code: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    as_guest: bool = False


class JoinMeetingResponse(BaseModel):
    status: Literal["joined", "already_member"]
    meeting_id: str
    redirect: str
