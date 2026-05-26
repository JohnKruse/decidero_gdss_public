"""Smug Otter agenda-strategy seam and deterministic default binding.

The seam keeps agenda interpretation behind a strategy object. Two reference
implementations are defined here:

- `LinearAgendaStrategy` (Phase 2): canonical reference for order-index agenda
  behavior; admits mid-meeting creation through `MeetingManager.add_agenda_activity`.
- `OrchestrationEngineStrategy` (Phase 4 — Insolent Metronome): interprets a
  loaded `OrchestrationDocument` via a step-pointer state machine. Each call to
  `create_activity` materializes the next document step as an `AgendaActivity`;
  `resolve_prior_activity` uses the engine's plan order rather than order-index
  adjacency to name the donor bundle.

Convergent Yak: prior-bundle resolution now flows through explicit donor
requests rather than making the activity pipeline infer meaning from order
adjacency. Both strategies respect the `PriorActivityReference`/`PriorActivityResolution`
hook signature introduced in Phase 3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, object_session

from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting


@dataclass(frozen=True)
class PriorActivityReference:
    """Convergent Yak request for the donor bundle feeding a consumer activity."""

    consumer_activity_id: str
    donor_activity_id: Optional[str] = None
    logical_step_id: Optional[str] = None
    round_index: Optional[int] = None
    handle: Optional[str] = None

    @classmethod
    def for_consumer(cls, activity: AgendaActivity) -> "PriorActivityReference":
        return cls(consumer_activity_id=activity.activity_id)


@dataclass(frozen=True)
class PriorActivityResolution:
    """Convergent Yak resolved donor plus optional iteration discriminator."""

    activity: AgendaActivity
    logical_step_id: Optional[str] = None
    round_index: Optional[int] = None
    handle: Optional[str] = None


class AgendaStrategy(ABC):
    """Smug Otter interface for interpreting a meeting agenda."""

    name = "abstract"

    @abstractmethod
    def resolve_prior_activity(
        self,
        meeting: Meeting,
        reference: PriorActivityReference,
    ) -> Optional[PriorActivityResolution]:
        """Resolve the donor activity and iteration for an input-bundle request."""

    @abstractmethod
    def list_agenda(self, meeting: Meeting) -> List[AgendaActivity]:
        """Return agenda activities in this strategy's canonical order."""

    @abstractmethod
    def is_complete(self, meeting: Meeting) -> bool:
        """Return whether the strategy considers the meeting agenda complete."""

    @abstractmethod
    def on_activity_close(self, meeting: Meeting, activity: AgendaActivity) -> None:
        """Record an activity close event for strategies that need it."""

    @abstractmethod
    def create_activity(
        self,
        meeting: Meeting,
        payload: Any,
        manager: Any,
    ) -> AgendaActivity:
        """Admit mid-meeting activity creation through the owning manager."""


class LinearAgendaStrategy(AgendaStrategy):
    """Smug Otter reference implementation for current order-index agendas.

    Convergent Yak: explicit donor references pass through unchanged; otherwise
    this strategy preserves the Phase 2 previous-by-order-index behavior.
    """

    name = "linear"

    def resolve_prior_activity(
        self,
        meeting: Meeting,
        reference: PriorActivityReference,
    ) -> Optional[PriorActivityResolution]:
        agenda = self.list_agenda(meeting)
        if reference.donor_activity_id:
            for item in agenda:
                if item.activity_id == reference.donor_activity_id:
                    return PriorActivityResolution(
                        activity=item,
                        logical_step_id=reference.logical_step_id,
                        round_index=reference.round_index,
                        handle=reference.handle,
                    )
            return None

        previous = None
        for item in agenda:
            if item.activity_id == reference.consumer_activity_id:
                if previous is None:
                    return None
                return PriorActivityResolution(
                    activity=previous,
                    logical_step_id=reference.logical_step_id,
                    round_index=reference.round_index,
                    handle=reference.handle,
                )
            previous = item
        return None

    def list_agenda(self, meeting: Meeting) -> List[AgendaActivity]:
        return sorted(
            list(getattr(meeting, "agenda_activities", []) or []),
            key=lambda item: item.order_index,
        )

    def is_complete(self, meeting: Meeting) -> bool:
        agenda = self.list_agenda(meeting)
        if not agenda:
            return True
        db = object_session(meeting)
        if db is None:
            return False
        latest = (
            db.query(ActivityBundle.id)
            .filter(
                ActivityBundle.meeting_id == meeting.meeting_id,
                ActivityBundle.activity_id == agenda[-1].activity_id,
                ActivityBundle.kind == "output",
            )
            .first()
        )
        return latest is not None

    def on_activity_close(self, meeting: Meeting, activity: AgendaActivity) -> None:
        return None

    def create_activity(
        self,
        meeting: Meeting,
        payload: Any,
        manager: Any,
    ) -> AgendaActivity:
        return manager.add_agenda_activity(meeting.meeting_id, payload)


def get_agenda_strategy(meeting: Meeting) -> AgendaStrategy:
    """Smug Otter deterministic binding for a meeting's agenda strategy.

    Currently always returns `LinearAgendaStrategy`. Callers that drive an
    orchestration document bind `OrchestrationEngineStrategy` directly rather
    than routing through this function.
    """
    return LinearAgendaStrategy()


class OrchestrationEngineStrategy(AgendaStrategy):
    """Insolent Metronome step-pointer state machine for orchestration documents.

    Interprets a loaded `OrchestrationDocument` by maintaining a flattened
    execution plan of leaf steps. `create_activity` materializes the next plan
    entry as an `AgendaActivity` row; `resolve_prior_activity` uses plan order
    rather than order-index adjacency to name the donor bundle, preserving the
    Phase 3 explicit-donor-reference hook signature.

    Phase 4 Step 2 implements the `activity` step kind only. `IterateStep`,
    `FacilitatorDecisionStep`, and `AIDecisionStep` raise `NotImplementedError`
    and are delivered in Phase 4 Steps 3-5.
    """

    name = "orchestration"

    def __init__(self, document: "OrchestrationDocument") -> None:  # noqa: F821
        self._document = document
        self._plan: List[Tuple[str, Any]] = self._flatten_plan(document.steps)

    @staticmethod
    def _flatten_plan(
        steps: List[Any],
        _prefix: str = "",
    ) -> List[Tuple[str, Any]]:
        """Flatten the document AST into ordered (logical_step_id, step) leaf pairs."""
        from app.services.orchestration_loader import (
            ActivityStep,
            FacilitatorDecisionStep,
            AIDecisionStep,
            IterateStep,
            SequenceStep,
        )
        result: List[Tuple[str, Any]] = []
        for i, step in enumerate(steps):
            path = str(i) if not _prefix else f"{_prefix}.{i}"
            if isinstance(step, SequenceStep):
                result.extend(
                    OrchestrationEngineStrategy._flatten_plan(step.steps, path)
                )
            elif isinstance(step, ActivityStep):
                result.append((f"engine:{path}", step))
            elif isinstance(step, IterateStep):
                raise NotImplementedError(
                    "iterate step kind is not yet implemented (Phase 4 Step 3)"
                )
            elif isinstance(step, (FacilitatorDecisionStep, AIDecisionStep)):
                raise NotImplementedError(
                    f"'{step.type}' step kind is not yet implemented"
                )
            # ConditionalStep is reserved/deferred — skip silently
        return result

    def _materialize_count(self, meeting: Meeting, db: Session) -> int:
        """Count AgendaActivity rows already minted for this meeting."""
        count = (
            db.query(func.count(AgendaActivity.activity_id))
            .filter(AgendaActivity.meeting_id == meeting.meeting_id)
            .scalar()
        ) or 0
        return int(count)

    def _completed_count(self, meeting: Meeting, db: Session) -> int:
        """Count plan steps whose activity has an output bundle (closed)."""
        count = (
            db.query(func.count(func.distinct(ActivityBundle.activity_id)))
            .filter(
                ActivityBundle.meeting_id == meeting.meeting_id,
                ActivityBundle.kind == "output",
            )
            .scalar()
        ) or 0
        return int(count)

    def resolve_prior_activity(
        self,
        meeting: Meeting,
        reference: PriorActivityReference,
    ) -> Optional[PriorActivityResolution]:
        agenda = self.list_agenda(meeting)
        if reference.donor_activity_id:
            for item in agenda:
                if item.activity_id == reference.donor_activity_id:
                    return PriorActivityResolution(
                        activity=item,
                        logical_step_id=reference.logical_step_id,
                        round_index=reference.round_index,
                        handle=reference.handle,
                    )
            return None

        # No explicit donor: resolve by plan order (previous activity feeds this one)
        previous: Optional[AgendaActivity] = None
        for item in agenda:
            if item.activity_id == reference.consumer_activity_id:
                if previous is None:
                    return None
                return PriorActivityResolution(
                    activity=previous,
                    logical_step_id=None,
                    round_index=None,
                    handle=reference.handle,
                )
            previous = item
        return None

    def list_agenda(self, meeting: Meeting) -> List[AgendaActivity]:
        return sorted(
            list(getattr(meeting, "agenda_activities", []) or []),
            key=lambda item: item.order_index,
        )

    def is_complete(self, meeting: Meeting) -> bool:
        if not self._plan:
            return True
        db = object_session(meeting)
        if db is None:
            return False
        return self._completed_count(meeting, db) >= len(self._plan)

    def on_activity_close(self, meeting: Meeting, activity: AgendaActivity) -> None:
        return None

    def create_activity(
        self,
        meeting: Meeting,
        payload: Any,
        manager: Any,
    ) -> AgendaActivity:
        """Materialize the next engine step as an AgendaActivity row.

        `payload` and `manager` are unused; configuration comes from the bound
        `OrchestrationDocument`. Calls `plugin.validate_config` per DP6.
        """
        from app.plugins.registry import get_activity_registry
        from app.services.activity_catalog import get_activity_definition
        from app.utils.identifiers import generate_activity_id, generate_tool_config_id
        from app.services.orchestration_loader import ActivityStep

        db = object_session(meeting)
        if db is None:
            raise ValueError("Meeting is not attached to a database session.")

        step_index = self._materialize_count(meeting, db)
        if step_index >= len(self._plan):
            raise HTTPException(
                status_code=400,
                detail="Orchestration plan is complete; no further activities to create.",
            )

        logical_step_id, step = self._plan[step_index]
        if not isinstance(step, ActivityStep):
            raise NotImplementedError(
                f"Step at position {step_index} is not an activity step."
            )

        definition = get_activity_definition(step.tool_type)
        if definition is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool type '{step.tool_type}' in orchestration document.",
            )

        # Merge activity catalog defaults with document step config (DP6)
        config: Dict[str, Any] = dict(definition.get("default_config", {}))
        config.update(dict(step.config or {}))
        plugin = get_activity_registry().get_plugin(step.tool_type)
        validated_config = plugin.validate_config(config) if plugin else config

        activity_id = generate_activity_id(db, meeting.meeting_id, step.tool_type)
        tool_config_id = generate_tool_config_id(activity_id, meeting.meeting_id)

        activity = AgendaActivity(
            activity_id=activity_id,
            meeting_id=meeting.meeting_id,
            tool_type=step.tool_type,
            title=step.title,
            order_index=step_index + 1,
            tool_config_id=tool_config_id,
            config=validated_config,
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)
        return activity

    @property
    def document(self) -> "OrchestrationDocument":  # noqa: F821
        return self._document

    @property
    def plan(self) -> List[Tuple[str, Any]]:
        return list(self._plan)
