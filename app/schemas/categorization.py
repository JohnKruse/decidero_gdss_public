from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CategorizationBucketCreateRequest(BaseModel):
    activity_id: str
    title: str
    category_id: Optional[str] = None
    description: Optional[str] = None


class CategorizationBucketUpdateRequest(BaseModel):
    activity_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class CategorizationBucketDeleteRequest(BaseModel):
    activity_id: str


class CategorizationBucketReorderRequest(BaseModel):
    activity_id: str
    category_ids: List[str] = Field(default_factory=list)


class CategorizationAssignmentRequest(BaseModel):
    activity_id: str
    item_key: str
    category_id: str


class CategorizationBallotStateResponse(BaseModel):
    meeting_id: str
    activity_id: str
    submitted: bool
    assignments: Dict[str, Optional[str]]
    buckets: List[Dict[str, Any]]
    items: List[Dict[str, Any]]


class CategorizationBallotAssignmentRequest(BaseModel):
    activity_id: str
    item_key: str
    category_id: Optional[str] = None


class CategorizationBallotSubmitRequest(BaseModel):
    activity_id: str


class CategorizationRevealRequest(BaseModel):
    activity_id: str
    revealed: bool


class CategorizationLockRequest(BaseModel):
    activity_id: str
    locked: bool = True


class CategorizationFinalAssignmentRequest(BaseModel):
    activity_id: str
    item_key: str
    category_id: str


class CategorizationDisputedItemsResponse(BaseModel):
    meeting_id: str
    activity_id: str
    disputed_items: List[Dict[str, Any]]


class CategorizationStateResponse(BaseModel):
    meeting_id: str
    activity_id: str
    unsorted_category_id: str
    buckets: List[Dict[str, Any]]
    items: List[Dict[str, Any]]
    assignments: Dict[str, str]
    agreement_metrics: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    final_assignments: Dict[str, str] = Field(default_factory=dict)
