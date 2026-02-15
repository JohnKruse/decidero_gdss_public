from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


CATEGORIZATION_SCHEMA_VERSION = 1


class CategorizationSeedItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[Union[str, int]] = None
    content: str = Field(..., min_length=1)
    submitted_name: Optional[str] = None
    parent_id: Optional[Union[str, int]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source: Dict[str, Any] = Field(default_factory=dict)


class CategorizationBucket(BaseModel):
    model_config = ConfigDict(extra="allow")

    category_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    order_index: int = Field(default=0, ge=0)
    status: Literal["active", "archived", "deleted"] = "active"


class CategorizationConfigV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[CATEGORIZATION_SCHEMA_VERSION] = CATEGORIZATION_SCHEMA_VERSION
    mode: Literal["FACILITATOR_LIVE", "PARALLEL_BALLOT"] = "FACILITATOR_LIVE"
    items: List[Union[CategorizationSeedItem, str]] = Field(default_factory=list)
    buckets: List[Union[CategorizationBucket, str]] = Field(default_factory=list)
    single_assignment_only: bool = True
    allow_unsorted_submission: bool = True
    agreement_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    minimum_ballots: int = Field(default=1, ge=0)
    tie_policy: Literal[
        "TIE_UNRESOLVED",
        "TIE_BREAK_FACILITATOR",
        "TIE_BREAK_BY_RULE",
    ] = "TIE_UNRESOLVED"
    missing_vote_handling: Literal["ignore", "unsorted"] = "ignore"
    private_until_reveal: bool = True


class CategorizationAgreementMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")

    top_category_id: Optional[str] = None
    top_count: int = Field(default=0, ge=0)
    top_share: float = Field(default=0.0, ge=0.0, le=1.0)
    second_share: float = Field(default=0.0, ge=0.0, le=1.0)
    margin: float = Field(default=0.0, ge=-1.0, le=1.0)
    status_label: Literal["AGREED", "DISPUTED"] = "DISPUTED"


class CategorizationStateV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[CATEGORIZATION_SCHEMA_VERSION] = CATEGORIZATION_SCHEMA_VERSION
    meeting_id: str = Field(..., min_length=1)
    activity_id: str = Field(..., min_length=1)
    mode: Literal["FACILITATOR_LIVE", "PARALLEL_BALLOT"]
    locked: bool = False
    buckets: List[CategorizationBucket] = Field(default_factory=list)
    assignments: Dict[str, Optional[str]] = Field(default_factory=dict)
    ballots: Dict[str, Dict[str, Optional[str]]] = Field(default_factory=dict)
    agreement_metrics: Dict[str, CategorizationAgreementMetrics] = Field(default_factory=dict)


class CategorizationOutputCategory(BaseModel):
    model_config = ConfigDict(extra="allow")

    category_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    item_ids: List[str] = Field(default_factory=list)


class CategorizationFinalizationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: Literal["FACILITATOR_LIVE", "PARALLEL_BALLOT"]
    finalized_at: str = Field(..., min_length=1)
    facilitator_id: Optional[str] = None
    agreement_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    minimum_ballots: int = Field(default=1, ge=0)
    ballot_count: int = Field(default=0, ge=0)


class CategorizationOutputV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[CATEGORIZATION_SCHEMA_VERSION] = CATEGORIZATION_SCHEMA_VERSION
    meeting_id: str = Field(..., min_length=1)
    activity_id: str = Field(..., min_length=1)
    categories: List[CategorizationOutputCategory] = Field(default_factory=list)
    finalization_metadata: CategorizationFinalizationMetadata
    tallies: Optional[Dict[str, Any]] = None
    ballots: Optional[Dict[str, Any]] = None


def validate_categorization_config(payload: Dict[str, Any]) -> CategorizationConfigV1:
    return CategorizationConfigV1.model_validate(payload)


def validate_categorization_state(payload: Dict[str, Any]) -> CategorizationStateV1:
    return CategorizationStateV1.model_validate(payload)


def validate_categorization_output(payload: Dict[str, Any]) -> CategorizationOutputV1:
    return CategorizationOutputV1.model_validate(payload)
