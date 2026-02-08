from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting


class ActivityPipeline:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.bundle_manager = ActivityBundleManager(db)

    def ensure_input_bundle(
        self, meeting: Meeting, activity: AgendaActivity
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

        previous = self._find_previous_activity(meeting, activity)
        if not previous:
            return None

        output = self.bundle_manager.get_latest_bundle(
            meeting.meeting_id, previous.activity_id, "output"
        )
        if not output:
            return None

        return self.bundle_manager.create_input_bundle_from_output(
            meeting.meeting_id, activity.activity_id, output
        )

    @staticmethod
    def _find_previous_activity(
        meeting: Meeting, activity: AgendaActivity
    ) -> Optional[AgendaActivity]:
        agenda = sorted(
            getattr(meeting, "agenda_activities", []) or [],
            key=lambda item: item.order_index,
        )
        previous = None
        for item in agenda:
            if item.activity_id == activity.activity_id:
                return previous
            previous = item
        return None
