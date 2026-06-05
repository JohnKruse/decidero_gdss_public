from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class JustificationItem(BaseModel):
    option_id: str
    content: Optional[str] = None
    your_rank: Optional[int] = None
    group_median: Optional[float] = None
    group_iqr: Optional[float] = None
    rationale: str = ""


class JustificationProgress(BaseModel):
    outlier_count: int = 0
    submitted_count: int = 0


class JustificationStateResponse(BaseModel):
    activity_id: str
    items: List[JustificationItem] = Field(default_factory=list)
    nothing_to_justify: bool
    submitted: bool
    progress: Optional[JustificationProgress] = None


class JustificationSubmitRequest(BaseModel):
    activity_id: str
    option_id: str
    rationale: str = ""
