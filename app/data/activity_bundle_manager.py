from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.activity_bundle import ActivityBundle
from app.models.idea import Idea
from app.utils.user_colors import get_user_color


class ActivityBundleManager:
    """Convergent Yak bundle persistence helper with round-aware accessors."""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _normalize_round_index(round_index: Optional[int]) -> int:
        if round_index is None:
            return 0
        return max(0, int(round_index))

    @staticmethod
    def _metadata_with_iteration(
        metadata: Optional[Dict[str, Any]],
        *,
        logical_step_id: Optional[str],
        round_index: int,
    ) -> Dict[str, Any]:
        enriched = dict(metadata or {})
        if logical_step_id is None and round_index == 0:
            return enriched
        iteration = dict(enriched.get("iteration") or {})
        if logical_step_id is not None:
            iteration["logical_step_id"] = logical_step_id
        iteration["round_index"] = round_index
        enriched["iteration"] = iteration
        return enriched

    def create_bundle(
        self,
        meeting_id: str,
        activity_id: str,
        kind: str,
        items: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        *,
        logical_step_id: Optional[str] = None,
        round_index: Optional[int] = None,
    ) -> ActivityBundle:
        normalized_round = self._normalize_round_index(round_index)
        bundle = ActivityBundle(
            bundle_id=str(uuid4()),
            meeting_id=meeting_id,
            activity_id=activity_id,
            kind=kind,
            logical_step_id=logical_step_id,
            round_index=normalized_round,
            items=items,
            bundle_metadata=self._metadata_with_iteration(
                metadata,
                logical_step_id=logical_step_id,
                round_index=normalized_round,
            ),
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
        *,
        round_index: Optional[int] = None,
        logical_step_id: Optional[str] = None,
    ) -> Optional[ActivityBundle]:
        query = self.db.query(ActivityBundle).filter(
            ActivityBundle.meeting_id == meeting_id,
            ActivityBundle.activity_id == activity_id,
            ActivityBundle.kind == kind,
        )
        if round_index is not None:
            query = query.filter(
                ActivityBundle.round_index == self._normalize_round_index(round_index)
            )
        if logical_step_id is not None:
            query = query.filter(ActivityBundle.logical_step_id == logical_step_id)
        return query.order_by(
            ActivityBundle.round_index.desc(),
            ActivityBundle.created_at.desc(),
            ActivityBundle.id.desc(),
        ).first()

    def upsert_draft_bundle(
        self,
        meeting_id: str,
        activity_id: str,
        items: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        *,
        logical_step_id: Optional[str] = None,
        round_index: Optional[int] = None,
    ) -> ActivityBundle:
        normalized_round = self._normalize_round_index(round_index)
        existing = self.get_latest_bundle(
            meeting_id,
            activity_id,
            "draft",
            round_index=normalized_round,
            logical_step_id=logical_step_id,
        )
        if existing:
            existing.items = items
            existing.bundle_metadata = self._metadata_with_iteration(
                metadata,
                logical_step_id=logical_step_id,
                round_index=normalized_round,
            )
            existing.updated_at = datetime.now(timezone.utc)
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        return self.create_bundle(
            meeting_id,
            activity_id,
            "draft",
            items,
            metadata,
            logical_step_id=logical_step_id,
            round_index=normalized_round,
        )

    def finalize_output_bundle(
        self,
        meeting_id: str,
        activity_id: str,
        items: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        *,
        logical_step_id: Optional[str] = None,
        round_index: Optional[int] = None,
    ) -> ActivityBundle:
        return self.create_bundle(
            meeting_id,
            activity_id,
            "output",
            items,
            metadata,
            logical_step_id=logical_step_id,
            round_index=round_index,
        )

    def create_input_bundle_from_output(
        self,
        meeting_id: str,
        activity_id: str,
        source_bundle: ActivityBundle,
        *,
        round_index: Optional[int] = None,
    ) -> ActivityBundle:
        target_round = (
            self._normalize_round_index(round_index)
            if round_index is not None
            else self._normalize_round_index(getattr(source_bundle, "round_index", 0))
        )
        return self.create_bundle(
            meeting_id,
            activity_id,
            "input",
            items=list(source_bundle.items or []),
            metadata=dict(source_bundle.bundle_metadata or {}),
            logical_step_id=getattr(source_bundle, "logical_step_id", None),
            round_index=target_round,
        )

    def list_bundles_for_step(
        self,
        meeting_id: str,
        logical_step_id: str,
        kind: str,
    ) -> List[ActivityBundle]:
        """Convergent Yak: return all bundles for one logical step by round."""
        return (
            self.db.query(ActivityBundle)
            .filter(
                ActivityBundle.meeting_id == meeting_id,
                ActivityBundle.logical_step_id == logical_step_id,
                ActivityBundle.kind == kind,
            )
            .order_by(ActivityBundle.round_index.asc(), ActivityBundle.id.asc())
            .all()
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
