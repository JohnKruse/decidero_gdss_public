from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Optional, List, Literal
from app.models.user import UserRole  # Import UserRole for type hinting

LOGIN_PATTERN = r"^[A-Za-z0-9._@+-]+$"


class UserBase(BaseModel):
    login: Optional[str] = Field(
        None,
        min_length=3,
        max_length=50,
        pattern=LOGIN_PATTERN,
        json_schema_extra={"example": "admin@example.com"},
    )
    email: Optional[str] = Field(
        None, json_schema_extra={"example": "user@example.com"}
    )
    first_name: Optional[str] = Field(None, json_schema_extra={"example": "John"})
    last_name: Optional[str] = Field(None, json_schema_extra={"example": "Doe"})
    organization: Optional[str] = Field(
        None, json_schema_extra={"example": "Acme Corp"}
    )

    model_config = ConfigDict(from_attributes=True)

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, value: Optional[str]):
        if value is None:
            return value
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("login", mode="before")
    @classmethod
    def normalize_login(cls, value: Optional[str]):
        if value is None:
            return value
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class UserCreate(UserBase):
    login: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=LOGIN_PATTERN,
        json_schema_extra={"example": "admin@example.com"},
    )
    password: str = Field(
        ..., min_length=8, json_schema_extra={"example": "SecurePassword123!"}
    )
    # Role will be determined by the registration logic (first user is admin, others participant)
    # So, not strictly needed in UserCreate from client, but can be set by admin.
    # For UserCreate schema used in /api/auth/register, first_name, last_name, email, password are primary.
    # login is derived if not provided.


class UserUpdate(UserBase):  # This might be for admin updates
    password: Optional[str] = Field(None, min_length=8)
    is_active: Optional[bool] = None
    role: Optional[UserRole] = None
    first_name: Optional[str] = Field(None, json_schema_extra={"example": "John"})
    last_name: Optional[str] = Field(None, json_schema_extra={"example": "Doe"})
    login: Optional[str] = Field(
        None,
        min_length=3,
        max_length=50,
        pattern=LOGIN_PATTERN,
        json_schema_extra={"example": "team.lead@example.com"},
    )
    organization: Optional[str] = Field(
        None, json_schema_extra={"example": "Acme Corp"}
    )


class User(
    UserBase
):  # This is the basic User model for general use, often for responses
    user_id: str = Field(..., json_schema_extra={"example": "USR-ADKINSJ-001"})
    legacy_user_id: Optional[int] = None
    login: str
    is_active: bool = True
    role: UserRole = Field(default=UserRole.PARTICIPANT)
    avatar_color: Optional[str] = None
    avatar_key: Optional[str] = None
    avatar_seed: int = 0
    avatar_icon_path: Optional[str] = None
    profile_svg: Optional[str] = None
    about_me: Optional[str] = None
    # password_changed: bool # Typically not exposed in general User schema

    model_config = ConfigDict(from_attributes=True)


# Specific schema for user responses, ensuring no sensitive data like password hashes
class UserResponse(UserBase):
    user_id: str = Field(..., json_schema_extra={"example": "USR-ADKINSJ-001"})
    legacy_user_id: Optional[int] = None
    login: str
    is_active: bool
    role: UserRole
    avatar_color: Optional[str] = None
    avatar_key: Optional[str] = None
    avatar_seed: int = 0
    avatar_icon_path: Optional[str] = None
    profile_svg: Optional[str] = None
    about_me: Optional[str] = None
    # Explicitly list all fields to be returned, excluding hashed_password

    model_config = ConfigDict(from_attributes=True)


# Specific schema for updating user's own profile (e.g., only about_me)
class UserProfileUpdate(BaseModel):
    about_me: Optional[str] = Field(
        None, json_schema_extra={"example": "I am a software developer."}
    )
    organization: Optional[str] = Field(
        None, json_schema_extra={"example": "Acme Corp"}
    )
    first_name: Optional[str] = Field(
        None, json_schema_extra={"example": "Preferred display name"}
    )
    avatar_key: Optional[str] = Field(
        None,
        json_schema_extra={"example": "fluent-1f984"},
    )

    model_config = ConfigDict(from_attributes=True)


# Batch creation schemas
class BatchCreateByPattern(BaseModel):
    prefix: str = Field(..., json_schema_extra={"example": "user_"})
    start: int = Field(..., ge=0, json_schema_extra={"example": 0})
    end: int = Field(..., gt=0, json_schema_extra={"example": 99})
    email_domain: Optional[str] = Field(
        None, json_schema_extra={"example": "example.com"}
    )
    default_password: str = Field(
        ..., min_length=8, json_schema_extra={"example": "SecurePassword123!"}
    )
    role: UserRole = Field(default=UserRole.PARTICIPANT)
    first_name: Optional[str] = Field(default=None)
    last_name: Optional[str] = Field(default=None)

    @field_validator("default_password")
    @classmethod
    def validate_default_password(cls, v):
        from app.utils.password_validation import validate_password

        is_valid, error_message = validate_password(v)
        if not is_valid:
            raise ValueError(error_message)
        return v

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v):
        if not v or not v.strip():
            raise ValueError("prefix is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_range(self):
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class BatchCreateByEmails(BaseModel):
    emails: List[str] = Field(..., min_length=1)
    default_password: str = Field(..., min_length=8)
    role: UserRole = Field(default=UserRole.PARTICIPANT)
    first_name: Optional[str] = Field(default=None)
    last_name: Optional[str] = Field(default=None)

    @field_validator("default_password")
    @classmethod
    def validate_default_password(cls, v):
        from app.utils.password_validation import validate_password

        is_valid, error_message = validate_password(v)
        if not is_valid:
            raise ValueError(error_message)
        return v

    @field_validator("emails")
    @classmethod
    def normalize_emails(cls, emails):
        normalized = []
        for e in emails:
            if not isinstance(e, str) or not e.strip():
                raise ValueError("email entries must be non-empty strings")
            normalized.append(e.strip().lower())
        return normalized


class BatchCreateResult(BaseModel):
    created_count: int
    created_logins: List[str] = Field(default_factory=list)
    updated_count: int = 0
    updated_logins: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)


class UserDirectorySort(str, Enum):
    NAME = "name"
    LOGIN = "login"
    ROLE = "role"


class UserDirectoryEntry(BaseModel):
    user_id: str
    login: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    avatar_color: Optional[str] = None
    avatar_key: Optional[str] = None
    avatar_icon_path: Optional[str] = None
    role: UserRole = Field(default=UserRole.PARTICIPANT)
    is_active: bool = True
    is_meeting_participant: bool = False
    is_activity_participant: bool = False
    is_facilitator: bool = False
    disabled_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserDirectoryPagination(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class UserDirectoryContext(BaseModel):
    meeting_id: Optional[str] = None
    activity_id: Optional[str] = None
    meeting_participant_count: int = 0
    activity_participant_count: int = 0
    activity_mode: Literal["all", "custom"] = "all"


class UserDirectoryResponse(BaseModel):
    items: List[UserDirectoryEntry] = Field(default_factory=list)
    pagination: UserDirectoryPagination
    context: UserDirectoryContext = Field(default_factory=UserDirectoryContext)
