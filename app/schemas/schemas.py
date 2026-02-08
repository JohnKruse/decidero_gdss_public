from enum import Enum  # Re-add the standard Enum import
from pydantic import BaseModel, Field, field_validator, ValidationInfo
from typing import Optional, List
from datetime import datetime
from app.utils.password_validation import validate_password
from app.models.user import UserRole  # Import UserRole from the model definition

LOGIN_PATTERN = r"^[A-Za-z0-9._@+-]+$"


# Removed local UserRole definition, using the one from models now
class Permission(str, Enum):
    CREATE_MEETING = "create_meeting"
    UPDATE_MEETING = "update_meeting"
    DELETE_MEETING = "delete_meeting"
    VIEW_MEETING = "view_meeting"
    MANAGE_USERS = "manage_users"
    MANAGE_ROLES = "manage_roles"


class Token(BaseModel):
    access_token: str
    token_type: str
    needs_password_change: bool = False


class LoginResponse(BaseModel):
    login_successful: bool
    needs_password_change: bool
    role: UserRole  # Uses the imported UserRole from models


class UserBase(BaseModel):
    login: Optional[str] = Field(
        None, min_length=3, max_length=50, pattern=LOGIN_PATTERN
    )
    email: Optional[str] = None
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, value):
        if value is None:
            return value
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("login", mode="before")
    @classmethod
    def normalize_login(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class UserCreate(UserBase):
    login: str = Field(..., min_length=3, max_length=50, pattern=LOGIN_PATTERN)
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.PARTICIPANT

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v):
        is_valid, error_message = validate_password(v)
        if not is_valid:
            raise ValueError(error_message)
        return v


class UserUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, min_length=1, max_length=50)
    login: Optional[str] = Field(
        None, min_length=3, max_length=50, pattern=LOGIN_PATTERN
    )
    password: Optional[str] = None
    role: Optional[UserRole] = None

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v):
        if v is not None:
            is_valid, error_message = validate_password(v)
            if not is_valid:
                raise ValueError(error_message)
        return v


class User(UserBase):
    user_id: str = Field(..., json_schema_extra={"example": "USR-ADKINSJ-001"})
    legacy_user_id: Optional[int] = None
    login: str
    role: UserRole = UserRole.PARTICIPANT
    avatar_color: Optional[str] = None
    avatar_key: Optional[str] = None
    avatar_seed: int = 0
    avatar_icon_path: Optional[str] = None

    model_config = {"from_attributes": True}


class MeetingBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=100)
    description: str
    is_public: bool = False


class Idea(BaseModel):
    """Schema for brainstorming ideas within a meeting."""

    idea_id: str
    author_id: str
    idea_text: str
    timestamp: datetime


class AgendaBase(BaseModel):
    title: str
    description: str


class AgendaCreate(AgendaBase):
    pass


class AgendaUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class AgendaResponse(AgendaBase):
    agenda_id: str

    model_config = {"from_attributes": True}


class ToolConfigBase(BaseModel):
    name: str
    config: dict


class ToolConfigCreate(ToolConfigBase):
    pass


class ToolConfigUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None


class ToolConfigResponse(ToolConfigBase):
    tool_config_id: str

    model_config = {"from_attributes": True}


class MeetingCreate(MeetingBase):
    start_time: datetime
    end_time: datetime
    owner_id: str
    participant_ids: List[str] = []

    @field_validator("end_time")
    @classmethod
    def end_time_must_be_after_start_time(
        cls, v: datetime, info: ValidationInfo
    ) -> datetime:
        if "start_time" in info.data and v <= info.data["start_time"]:
            raise ValueError("end_time must be after start_time")
        return v


class MeetingResponse(MeetingBase):
    meeting_id: str
    start_time: datetime
    end_time: datetime
    owner: "User"  # Assuming a User schema exists
    participants: List["User"] = []  # Assuming a User schema exists
    agenda_items: List[AgendaResponse] = []
    tool_configs: List[ToolConfigResponse] = []

    model_config = {"from_attributes": True}


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_public: Optional[bool] = None
    owner_id: Optional[str] = None
    participant_ids: Optional[List[str]] = None
