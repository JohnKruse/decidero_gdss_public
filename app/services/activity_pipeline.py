"""Activity bundle input pipeline.

Smug Otter: agenda consultation flows through app/services/agenda_strategy.py.
`LinearAgendaStrategy` is the Phase 2 reference implementation for today's
order-index semantics, including safe mid-meeting agenda insertion through the
strategy seam.

Convergent Yak: input materialization asks the agenda strategy to resolve a
donor reference for the consumer instead of inferring a previous bundle locally.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting
from app.services.agenda_strategy import PriorActivityReference, get_agenda_strategy


class ActivityPipeline:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.bundle_manager = ActivityBundleManager(db)

    def ensure_input_bundle(
        self,
        meeting: Meeting,
        activity: AgendaActivity,
        prior_reference: Optional[PriorActivityReference] = None,
    ) -> Optional[ActivityBundle]:
        existing = self.bundle_manager.get_latest_bundle(
            meeting.meeting_id, activity.activity_id, "input"
        )
        if existing:
            activity_created = getattr(activity, "created_at", None)
            existing_created = getattr(existing, "created_at", None)
            if (
                activity_created
                and existing_created
                and existing_created < activity_created
            ):
                self.db.query(ActivityBundle).filter(
                    ActivityBundle.meeting_id == meeting.meeting_id,
                    ActivityBundle.activity_id == activity.activity_id,
                    ActivityBundle.kind == "input",
                ).delete(synchronize_session=False)
                self.db.flush()
                existing = None
            else:
                return existing

        # Convergent Yak: prior-bundle interpretation belongs to AgendaStrategy.
        resolution = get_agenda_strategy(meeting).resolve_prior_activity(
            meeting, prior_reference or PriorActivityReference.for_consumer(activity)
        )
        if not resolution:
            return None

        output = self.bundle_manager.get_latest_bundle(
            meeting.meeting_id,
            resolution.activity.activity_id,
            "output",
            logical_step_id=resolution.logical_step_id,
            round_index=resolution.round_index,
        )
        if not output:
            return None

        return self.bundle_manager.create_input_bundle_from_output(
            meeting.meeting_id, activity.activity_id, output
        )
