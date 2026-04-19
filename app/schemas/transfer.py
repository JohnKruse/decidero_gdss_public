from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class TransferBundleItem(BaseModel):
    id: Optional[int | str] = None
    content: Optional[str] = None
    meeting_id: Optional[str] = None
    activity_id: Optional[str] = None
    user_id: Optional[str] = None
    user_color: Optional[str] = None
    submitted_name: Optional[str] = None
    parent_id: Optional[int | str] = None
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
    """
    Schema for the target of a transfer.
    Supports two modes:
    1. New activity creation: `tool_type` must be provided.
    2. Transfer to existing activity: `activity_id` must be provided (the target tool type is derived from the existing activity).
    """
    activity_id: Optional[str] = None
    tool_type: Optional[str] = None
    title: Optional[str] = None
    instructions: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_target_identity(self) -> 'TransferTargetActivity':
        if not self.activity_id and not self.tool_type:
            raise ValueError("Either tool_type or activity_id must be provided")
        return self


class TransferCommit(BaseModel):
    donor_activity_id: str
    include_comments: bool = True
    items: List[TransferBundleItem] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    target_activity: TransferTargetActivity


class TransferCommitResponse(BaseModel):
    """
    Response payload for transfer commit operations.

    `target_activity` is the canonical key for the transfer destination.
    `new_activity` is retained as a backward-compatible alias for clients that
    still read the legacy field when a new activity is created.
    """

    target_activity: Dict[str, Any]
    new_activity: Optional[Dict[str, Any]] = None
    agenda: List[Dict[str, Any]]
    input_bundle_id: str
