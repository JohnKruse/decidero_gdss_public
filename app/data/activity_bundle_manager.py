from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.activity_bundle import ActivityBundle
from app.models.idea import Idea
from app.utils.user_colors import get_user_color


class ActivityBundleManager:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_bundle(
        self,
        meeting_id: str,
        activity_id: str,
        kind: str,
        items: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActivityBundle:
        bundle = ActivityBundle(
            bundle_id=str(uuid4()),
            meeting_id=meeting_id,
            activity_id=activity_id,
            kind=kind,
            items=items,
            bundle_metadata=metadata or {},
        )
        self.db.add(bundle)
        self.db.commit()
        self.db.refresh(bundle)
        return bundle

    def get_latest_bundle(
        self,
        meeting_id: str,
        activity_id: str,
        kind: str,
    ) -> Optional[ActivityBundle]:
        return (
            self.db.query(ActivityBundle)
            .filter(
                ActivityBundle.meeting_id == meeting_id,
                ActivityBundle.activity_id == activity_id,
                ActivityBundle.kind == kind,
            )
            .order_by(ActivityBundle.created_at.desc(), ActivityBundle.id.desc())
            .first()
        )

    def upsert_draft_bundle(
        self,
        meeting_id: str,
        activity_id: str,
        items: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActivityBundle:
        existing = self.get_latest_bundle(meeting_id, activity_id, "draft")
        if existing:
            existing.items = items
            existing.bundle_metadata = metadata or {}
            existing.updated_at = datetime.now(timezone.utc)
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        return self.create_bundle(meeting_id, activity_id, "draft", items, metadata)

    def finalize_output_bundle(
        self,
        meeting_id: str,
        activity_id: str,
        items: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActivityBundle:
        return self.create_bundle(meeting_id, activity_id, "output", items, metadata)

    def create_input_bundle_from_output(
        self,
        meeting_id: str,
        activity_id: str,
        source_bundle: ActivityBundle,
    ) -> ActivityBundle:
        return self.create_bundle(
            meeting_id,
            activity_id,
            "input",
            items=list(source_bundle.items or []),
            metadata=dict(source_bundle.bundle_metadata or {}),
        )


def serialize_idea(idea: Idea) -> Dict[str, Any]:
    return {
        "id": idea.id,
        "content": idea.content,
        "submitted_name": idea.submitted_name,
        "created_at": idea.timestamp.isoformat() if idea.timestamp else None,
        "parent_id": idea.parent_id,
        "activity_id": idea.activity_id,
        "user_id": idea.user_id,
        "user_color": get_user_color(user=idea.author),
        "metadata": idea.idea_metadata or {},
        "source": {
            "meeting_id": idea.meeting_id,
            "activity_id": idea.activity_id,
        },
    }
