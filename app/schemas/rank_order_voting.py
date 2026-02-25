from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RankOrderOptionSummary(BaseModel):
    option_id: str
    label: str
    user_rank: Optional[int] = None
    borda_score: Optional[float] = None
    avg_rank: Optional[float] = None
    rank_variance: Optional[float] = None
    top_choice_share: Optional[float] = None


class RankOrderVotingSummaryResponse(BaseModel):
    activity_id: str
    tool_type: str
    show_results: bool
    can_view_results: bool
    allow_reset: bool
    randomize_order: bool
    submitted: bool
    is_active: bool = False
    submission_count: int = 0
    active_participant_count: int = 0
    options: List[RankOrderOptionSummary] = Field(default_factory=list)
    results: List[RankOrderOptionSummary] = Field(default_factory=list)


class RankOrderSubmitRequest(BaseModel):
    activity_id: str
    ordered_option_ids: List[str] = Field(default_factory=list)


class RankOrderResetRequest(BaseModel):
    activity_id: str
