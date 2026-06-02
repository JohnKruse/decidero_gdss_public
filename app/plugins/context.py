from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User


@dataclass
class ActivityContext:
    db: Session
    meeting: Meeting
    activity: AgendaActivity
    user: Optional[User] = None
    logger: Optional[Any] = None

    def _bundle_manager(self) -> ActivityBundleManager:
        return ActivityBundleManager(self.db)

    def load_input_bundle(self) -> Optional[ActivityBundle]:
        return self._bundle_manager().get_latest_bundle(
            self.meeting.meeting_id, self.activity.activity_id, "input"
        )

    def load_draft_bundle(self) -> Optional[ActivityBundle]:
        return self._bundle_manager().get_latest_bundle(
            self.meeting.meeting_id, self.activity.activity_id, "draft"
        )

    def save_draft_bundle(
        self,
        items: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActivityBundle:
        return self._bundle_manager().upsert_draft_bundle(
            self.meeting.meeting_id,
            self.activity.activity_id,
            items,
            metadata,
        )

    def finalize_output_bundle(
        self,
        items: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActivityBundle:
        orchestration = dict((self.activity.config or {}).get("_orchestration") or {})
        return self._bundle_manager().finalize_output_bundle(
            self.meeting.meeting_id,
            self.activity.activity_id,
            items,
            metadata,
            logical_step_id=orchestration.get("logical_step_id"),
            round_index=orchestration.get("round_index"),
        )
