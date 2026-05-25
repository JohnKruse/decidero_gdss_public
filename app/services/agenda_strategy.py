"""Smug Otter agenda-strategy seam and deterministic default binding.

The seam keeps agenda interpretation behind a strategy object. Phase 2 defines
`LinearAgendaStrategy` as the canonical reference implementation for today's
order-index agenda behavior and admits mid-meeting creation through
`MeetingManager.add_agenda_activity`; later phases can bind an engine-backed
strategy without changing callers of this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from sqlalchemy.orm import object_session

from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting


class AgendaStrategy(ABC):
    """Smug Otter interface for interpreting a meeting agenda."""

    name = "abstract"

    @abstractmethod
    def resolve_prior_activity(
        self,
        meeting: Meeting,
        activity: AgendaActivity,
    ) -> Optional[AgendaActivity]:
        """Return the activity considered prior to `activity` by this strategy."""

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
    """Smug Otter reference implementation for current order-index agendas."""

    name = "linear"

    def resolve_prior_activity(
        self,
        meeting: Meeting,
        activity: AgendaActivity,
    ) -> Optional[AgendaActivity]:
        agenda = self.list_agenda(meeting)
        previous = None
        for item in agenda:
            if item.activity_id == activity.activity_id:
                return previous
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
