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


class CategorizationStateResponse(BaseModel):
    meeting_id: str
    activity_id: str
    unsorted_category_id: str
    buckets: List[Dict[str, Any]]
    items: List[Dict[str, Any]]
    assignments: Dict[str, str]
