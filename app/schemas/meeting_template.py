from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


MEETING_TEMPLATE_CONTRACT_VERSION = 1


class MeetingTemplateSource(str, Enum):
    BUILT_IN = "built_in"
    CUSTOM = "custom"


class MeetingTemplateStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MeetingTemplateFlowType(str, Enum):
    LINEAR = "linear"
    MULTI_ROUND = "multi_round"
    MULTI_TRACK = "multi_track"


class MeetingTemplateActivity(BaseModel):
    tool_type: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=200)
    instructions: Optional[str] = Field(None, max_length=2000)
    order_index: int = Field(..., ge=1)
    duration_minutes: Optional[int] = Field(None, gt=0)
    config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_type")
    @classmethod
    def normalize_tool_type(cls, value: str) -> str:
        trimmed = (value or "").strip().lower()
        if not trimmed:
            raise ValueError("tool_type is required")
        return trimmed

    @field_validator("instructions")
    @classmethod
    def trim_instructions(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("config", mode="before")
    @classmethod
    def ensure_config_dict(cls, value: Optional[Any]) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise TypeError("config must be an object")


class MeetingTemplatePayload(BaseModel):
    schema_version: int = Field(default=MEETING_TEMPLATE_CONTRACT_VERSION)
    defaults: Dict[str, Any] = Field(default_factory=dict)
    agenda: List[MeetingTemplateActivity] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    orchestration: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract_version(self) -> "MeetingTemplatePayload":
        if self.schema_version != MEETING_TEMPLATE_CONTRACT_VERSION:
            raise ValueError(
                f"meeting template schema_version must be {MEETING_TEMPLATE_CONTRACT_VERSION}"
            )
        return self


class MeetingTemplateCreate(BaseModel):
    source: MeetingTemplateSource
    name: str = Field(..., min_length=1, max_length=200)
    purpose: Optional[str] = Field(None, max_length=1000)
    description: Optional[str] = Field(None, max_length=2000)
    estimated_duration_minutes: Optional[int] = Field(None, gt=0)
    min_participants: Optional[int] = Field(None, ge=1)
    max_participants: Optional[int] = Field(None, ge=1)
    tags: List[str] = Field(default_factory=list)
    flow_type: MeetingTemplateFlowType = MeetingTemplateFlowType.LINEAR
    template_version: int = Field(default=1, ge=1)
    built_in_key: Optional[str] = Field(None, min_length=1, max_length=80)
    created_by_user_id: Optional[str] = Field(None, min_length=1, max_length=20)
    template_payload: MeetingTemplatePayload

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Optional[Any]) -> List[str]:
        if not value:
            return []
        if not isinstance(value, list):
            raise TypeError("tags must be a list")
        cleaned: List[str] = []
        seen: set[str] = set()
        for item in value:
            tag = str(item).strip()
            if not tag:
                continue
            key = tag.lower()
            if key in seen:
                continue
            cleaned.append(tag)
            seen.add(key)
        return cleaned

    @model_validator(mode="after")
    def validate_source_fields(self) -> "MeetingTemplateCreate":
        if self.source == MeetingTemplateSource.BUILT_IN:
            if not self.built_in_key:
                raise ValueError("built-in templates require built_in_key")
            if self.created_by_user_id:
                raise ValueError("built-in templates cannot have created_by_user_id")
        if self.source == MeetingTemplateSource.CUSTOM and not self.created_by_user_id:
            raise ValueError("custom templates require created_by_user_id")
        if (
            self.min_participants is not None
            and self.max_participants is not None
            and self.min_participants > self.max_participants
        ):
            raise ValueError("min_participants cannot exceed max_participants")
        return self


class MeetingTemplatePermissionSummary(BaseModel):
    can_start: bool = False
    can_edit: bool = False
    can_archive: bool = False
    can_delete: bool = False
    is_read_only: bool = True


class MeetingTemplateResponse(BaseModel):
    template_id: str
    source: MeetingTemplateSource
    status: MeetingTemplateStatus
    name: str
    purpose: Optional[str] = None
    description: Optional[str] = None
    estimated_duration_minutes: Optional[int] = None
    min_participants: Optional[int] = None
    max_participants: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    flow_type: MeetingTemplateFlowType
    template_version: int
    built_in_key: Optional[str] = None
    created_by_user_id: Optional[str] = None
    contract_version: int
    template_payload: MeetingTemplatePayload
    permissions: MeetingTemplatePermissionSummary = Field(
        default_factory=MeetingTemplatePermissionSummary
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
