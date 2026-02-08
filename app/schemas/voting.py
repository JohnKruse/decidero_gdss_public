from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class VoteOptionSummary(BaseModel):
    option_id: str
    label: str
    votes: Optional[int] = None
    user_votes: int = 0


class VotingOptionsResponse(BaseModel):
    activity_id: str
    tool_type: str
    max_votes: int
    max_votes_per_option: Optional[int] = None
    allow_retract: bool = False
    vote_label_singular: Optional[str] = None
    vote_label_plural: Optional[str] = None
    votes_cast: int
    remaining_votes: int
    show_results: bool = True
    can_view_results: bool = False
    is_active: bool = False
    options: List[VoteOptionSummary] = Field(default_factory=list)


class VoteCastRequest(BaseModel):
    activity_id: str
    option_id: str
    action: Literal["add", "retract"] = "add"


class VoteCastResponse(BaseModel):
    activity_id: str
    votes_cast: int
    remaining_votes: int
    max_votes: int
    max_votes_per_option: Optional[int] = None
    allow_retract: bool = False
    vote_label_singular: Optional[str] = None
    vote_label_plural: Optional[str] = None
    show_results: bool
    can_view_results: bool = False
    is_active: bool = False
    options: List[VoteOptionSummary] = Field(default_factory=list)
