"""Plainspoken Marmot: Phase 9 Step 2 — Control-Point Card schemas.

Request/response models for the stateless compile and decompile endpoints
that translate a plain-language control-point card to/from the Layer-2
iterate step structure.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ControlPointCardRequest(BaseModel):
    """The facilitator's plain-language control-point card form payload."""

    activity_tool_type: str = Field(
        ...,
        min_length=1,
        description="The activity tool type for the repeated round (e.g. rank_order_voting).",
    )
    activity_title: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional display title for the activity step. Defaults from the catalog if omitted.",
    )
    who_decides: Literal["facilitator", "assisted", "auto"] = Field(
        ...,
        description=(
            "'facilitator' = I'll decide; "
            "'assisted' = I'll decide but show me a suggestion; "
            "'auto' = decide automatically."
        ),
    )
    stop_condition: Literal[
        "responses_stabilize", "agreement", "fixed_rounds", "custom"
    ] = Field(
        ...,
        description="The named stop condition for the iterate loop.",
    )
    stop_condition_text: Optional[str] = Field(
        None,
        max_length=2000,
        description="Free-text description when stop_condition == 'custom'.",
    )
    max_rounds: int = Field(
        ...,
        ge=1,
        le=50,
        description="Hard round cap — the loop stops after this many rounds regardless.",
    )
    threshold: Optional[float] = Field(
        None,
        ge=0.0,
        description="Optional threshold for computational predicates (e.g. IQR stability threshold).",
    )

    @field_validator("stop_condition_text")
    @classmethod
    def _require_text_for_custom(cls, v: Optional[str], info) -> Optional[str]:
        data = info.data
        if data.get("stop_condition") == "custom" and not (v or "").strip():
            raise ValueError(
                "A description is required when the stop condition is 'Describe it in your own words'."
            )
        return v


class ControlPointCardResponse(BaseModel):
    """Compiled iterate step plus plain-language confirmation summary."""

    iterate_step: Dict[str, Any] = Field(
        ...,
        description="The compiled iterate step dict, ready to embed in an orchestration document.",
    )
    summary: List[str] = Field(
        ...,
        description="Plain-language summary lines describing what the control point will do.",
    )


class ControlPointCardDecompileResponse(BaseModel):
    """Card form state reverse-engineered from an existing iterate step."""

    activity_tool_type: Optional[str] = None
    activity_title: Optional[str] = None
    who_decides: Literal["facilitator", "assisted", "auto"] = "facilitator"
    stop_condition: Literal[
        "responses_stabilize", "agreement", "fixed_rounds", "custom"
    ] = "responses_stabilize"
    stop_condition_text: Optional[str] = None
    max_rounds: int = 4
    threshold: Optional[float] = None
