from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RankOrderPriorRoundFeedback(BaseModel):
    """Delphi controlled feedback: the prior round's group statistics for an item,
    surfaced so participants can reconsider before re-ranking."""

    median: Optional[float] = None
    iqr: Optional[float] = None
    dispersion: Optional[float] = None
    # The viewer's own rank for this item last round (None if they didn't rank it).
    your_prior_rank: Optional[int] = None


class RankOrderPriorRoundComment(BaseModel):
    """A prior-round comment, peer-anonymous. `mine` privately flags the comment
    the requesting viewer authored, computed per-viewer and never persisted."""

    text: str
    mine: bool = False


class RankOrderOptionSummary(BaseModel):
    option_id: str
    label: str
    user_rank: Optional[int] = None
    borda_score: Optional[float] = None
    avg_rank: Optional[float] = None
    rank_variance: Optional[float] = None
    top_choice_share: Optional[float] = None
    # Delphi: prior-round median/IQR for this item (None outside a Delphi loop).
    prior_round_feedback: Optional[RankOrderPriorRoundFeedback] = None
    # Delphi: prior-round outlier rationales (None outside a Delphi loop / if empty).
    prior_round_rationales: Optional[List[RankOrderPriorRoundComment]] = None


class RankOrderRoundProgress(BaseModel):
    """Delphi loop progress for the round-progression display."""

    round_number: int
    max_rounds: int


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
    # Delphi: "Round N of M" progression (None outside a Delphi iterate loop).
    delphi_round: Optional[RankOrderRoundProgress] = None


class RankOrderSubmitRequest(BaseModel):
    activity_id: str
    ordered_option_ids: List[str] = Field(default_factory=list)


class RankOrderResetRequest(BaseModel):
    activity_id: str
