from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TransferBundleItem(BaseModel):
    id: Optional[int] = None
    content: Optional[str] = None
    meeting_id: Optional[str] = None
    activity_id: Optional[str] = None
    user_id: Optional[str] = None
    user_color: Optional[str] = None
    submitted_name: Optional[str] = None
    parent_id: Optional[int] = None
    timestamp: Optional[str] = None
    updated_at: Optional[str] = None
    created_at: Optional[str] = None  # Legacy alias for timestamp
    metadata: Optional[Dict[str, Any]] = None
    source: Optional[Dict[str, Any]] = None


class TransferDraftUpdate(BaseModel):
    include_comments: bool = True
    items: List[TransferBundleItem] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None


class TransferTargetActivity(BaseModel):
    tool_type: str
    title: Optional[str] = None
    instructions: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class TransferCommit(BaseModel):
    donor_activity_id: str
    include_comments: bool = True
    items: List[TransferBundleItem] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    target_activity: TransferTargetActivity
