"""Smug Otter agenda-strategy seam and deterministic default binding.

The seam keeps agenda interpretation behind a strategy object. Phase 2 defines
`LinearAgendaStrategy` as the canonical reference implementation for today's
order-index agenda behavior and admits mid-meeting creation through
`MeetingManager.add_agenda_activity`; later phases can bind an engine-backed
strategy without changing callers of this interface.

Convergent Yak: prior-bundle resolution now flows through explicit donor
requests rather than making the activity pipeline infer meaning from order
adjacency. LinearAgendaStrategy still answers those requests with order-index
adjacency when no donor activity is supplied.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional

from sqlalchemy.orm import object_session

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
    """Smug Otter deterministic binding for a meeting's agenda strategy."""
    return LinearAgendaStrategy()
