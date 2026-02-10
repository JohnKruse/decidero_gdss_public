from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.activity_bundle import ActivityBundle
from app.models.categorization import (
    CategorizationAssignment,
    CategorizationAuditEvent,
    CategorizationBallot,
    CategorizationBucket,
    CategorizationFinalAssignment,
    CategorizationItem,
)
from app.models.meeting import AgendaActivity


UNSORTED_CATEGORY_ID = "UNSORTED"
UNSORTED_TITLE = "Unsorted"


class CategorizationManager:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def normalize_item_key(activity_id: str, raw_key: Any, index: int) -> str:
        candidate = str(raw_key).strip() if raw_key is not None else ""
        if candidate:
            return candidate
        return f"{activity_id}:item-{index + 1}"

    def reset_activity_state(
        self,
        meeting_id: str,
        activity_id: str,
        *,
        clear_bundles: bool = True,
    ) -> None:
        self.db.query(CategorizationAuditEvent).filter(
            CategorizationAuditEvent.meeting_id == meeting_id,
            CategorizationAuditEvent.activity_id == activity_id,
        ).delete(synchronize_session=False)
        self.db.query(CategorizationFinalAssignment).filter(
            CategorizationFinalAssignment.meeting_id == meeting_id,
            CategorizationFinalAssignment.activity_id == activity_id,
        ).delete(synchronize_session=False)
        self.db.query(CategorizationBallot).filter(
            CategorizationBallot.meeting_id == meeting_id,
            CategorizationBallot.activity_id == activity_id,
        ).delete(synchronize_session=False)
        self.db.query(CategorizationAssignment).filter(
            CategorizationAssignment.meeting_id == meeting_id,
            CategorizationAssignment.activity_id == activity_id,
        ).delete(synchronize_session=False)
        self.db.query(CategorizationBucket).filter(
            CategorizationBucket.meeting_id == meeting_id,
            CategorizationBucket.activity_id == activity_id,
        ).delete(synchronize_session=False)
        self.db.query(CategorizationItem).filter(
            CategorizationItem.meeting_id == meeting_id,
            CategorizationItem.activity_id == activity_id,
        ).delete(synchronize_session=False)

        if clear_bundles:
            self.db.query(ActivityBundle).filter(
                ActivityBundle.meeting_id == meeting_id,
                ActivityBundle.activity_id == activity_id,
            ).delete(synchronize_session=False)
        self.db.commit()

    def ensure_unsorted_bucket(
        self,
        meeting_id: str,
        activity_id: str,
        *,
        actor_user_id: Optional[str] = None,
    ) -> CategorizationBucket:
        bucket = (
            self.db.query(CategorizationBucket)
            .filter(
                CategorizationBucket.meeting_id == meeting_id,
                CategorizationBucket.activity_id == activity_id,
                CategorizationBucket.category_id == UNSORTED_CATEGORY_ID,
            )
            .first()
        )
        if bucket:
            return bucket

        bucket = CategorizationBucket(
            meeting_id=meeting_id,
            activity_id=activity_id,
            category_id=UNSORTED_CATEGORY_ID,
            title=UNSORTED_TITLE,
            order_index=0,
            status="active",
            created_by=actor_user_id,
        )
        self.db.add(bucket)
        self.db.commit()
        self.db.refresh(bucket)
        self.log_event(
            meeting_id=meeting_id,
            activity_id=activity_id,
            actor_user_id=actor_user_id,
            event_type="bucket_created",
            payload={"category_id": UNSORTED_CATEGORY_ID, "title": UNSORTED_TITLE},
            commit=True,
        )
        return bucket

    def seed_activity(
        self,
        *,
        meeting_id: str,
        activity: AgendaActivity,
        actor_user_id: Optional[str] = None,
    ) -> Dict[str, int]:
        self.ensure_unsorted_bucket(
            meeting_id,
            activity.activity_id,
            actor_user_id=actor_user_id,
        )
        config = dict(activity.config or {})
        buckets = config.get("buckets", [])
        items = config.get("items", [])

        bucket_count = self._seed_buckets(
            meeting_id=meeting_id,
            activity_id=activity.activity_id,
            buckets=buckets,
            actor_user_id=actor_user_id,
        )
        item_count = self._seed_items(
            meeting_id=meeting_id,
            activity_id=activity.activity_id,
            items=items,
            actor_user_id=actor_user_id,
        )
        return {"buckets": bucket_count, "items": item_count}

    def _seed_buckets(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        buckets: Iterable[Any],
        actor_user_id: Optional[str],
    ) -> int:
        inserted = 0
        order_index = 1
        for raw in buckets or []:
            title = ""
            category_id = ""
            description = None
            if isinstance(raw, str):
                title = raw.strip()
            elif isinstance(raw, dict):
                title = str(raw.get("title", "")).strip()
                category_id = str(raw.get("category_id", "")).strip()
                description = raw.get("description")
            if not title:
                continue
            if not category_id:
                category_id = f"{activity_id}:bucket-{order_index}"
            exists = (
                self.db.query(CategorizationBucket)
                .filter(
                    CategorizationBucket.meeting_id == meeting_id,
                    CategorizationBucket.activity_id == activity_id,
                    CategorizationBucket.category_id == category_id,
                )
                .first()
            )
            if exists:
                continue
            self.db.add(
                CategorizationBucket(
                    meeting_id=meeting_id,
                    activity_id=activity_id,
                    category_id=category_id,
                    title=title,
                    description=description,
                    order_index=order_index,
                    status="active",
                    created_by=actor_user_id,
                )
            )
            inserted += 1
            order_index += 1
        self.db.commit()
        return inserted

    def _seed_items(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        items: Iterable[Any],
        actor_user_id: Optional[str],
    ) -> int:
        inserted = 0
        for index, raw in enumerate(items or []):
            content = ""
            item_key = ""
            metadata: Dict[str, Any] = {}
            source: Dict[str, Any] = {}
            submitted_name = None
            parent_item_key = None
            if isinstance(raw, str):
                content = raw.strip()
            elif isinstance(raw, dict):
                content = str(raw.get("content", "")).strip()
                item_key = str(raw.get("id", "")).strip()
                metadata = dict(raw.get("metadata") or {})
                source = dict(raw.get("source") or {})
                submitted_name = raw.get("submitted_name")
                parent_item_key = (
                    str(raw.get("parent_id")).strip()
                    if raw.get("parent_id") is not None
                    else None
                )
            if not content:
                continue
            item_key = self.normalize_item_key(activity_id, item_key, index)
            exists = (
                self.db.query(CategorizationItem)
                .filter(
                    CategorizationItem.meeting_id == meeting_id,
                    CategorizationItem.activity_id == activity_id,
                    CategorizationItem.item_key == item_key,
                )
                .first()
            )
            if exists:
                continue
            self.db.add(
                CategorizationItem(
                    meeting_id=meeting_id,
                    activity_id=activity_id,
                    item_key=item_key,
                    content=content,
                    submitted_name=submitted_name,
                    parent_item_key=parent_item_key,
                    item_metadata=metadata,
                    source=source,
                )
            )
            self.db.add(
                CategorizationAssignment(
                    meeting_id=meeting_id,
                    activity_id=activity_id,
                    item_key=item_key,
                    category_id=UNSORTED_CATEGORY_ID,
                    is_unsorted=True,
                    assigned_by=actor_user_id,
                )
            )
            inserted += 1
        self.db.commit()
        return inserted

    def list_buckets(self, meeting_id: str, activity_id: str) -> List[CategorizationBucket]:
        return (
            self.db.query(CategorizationBucket)
            .filter(
                CategorizationBucket.meeting_id == meeting_id,
                CategorizationBucket.activity_id == activity_id,
            )
            .order_by(CategorizationBucket.order_index.asc())
            .all()
        )

    def list_items(self, meeting_id: str, activity_id: str) -> List[CategorizationItem]:
        return (
            self.db.query(CategorizationItem)
            .filter(
                CategorizationItem.meeting_id == meeting_id,
                CategorizationItem.activity_id == activity_id,
            )
            .order_by(CategorizationItem.created_at.asc(), CategorizationItem.item_key.asc())
            .all()
        )

    def upsert_assignment(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        item_key: str,
        category_id: str,
        actor_user_id: Optional[str] = None,
    ) -> CategorizationAssignment:
        assignment = (
            self.db.query(CategorizationAssignment)
            .filter(
                CategorizationAssignment.meeting_id == meeting_id,
                CategorizationAssignment.activity_id == activity_id,
                CategorizationAssignment.item_key == item_key,
            )
            .first()
        )
        if assignment:
            assignment.category_id = category_id
            assignment.is_unsorted = category_id == UNSORTED_CATEGORY_ID
            assignment.assigned_by = actor_user_id
        else:
            assignment = CategorizationAssignment(
                meeting_id=meeting_id,
                activity_id=activity_id,
                item_key=item_key,
                category_id=category_id,
                is_unsorted=category_id == UNSORTED_CATEGORY_ID,
                assigned_by=actor_user_id,
            )
            self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def create_bucket(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        title: str,
        actor_user_id: Optional[str],
        category_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> CategorizationBucket:
        title = str(title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Bucket title is required.")

        max_order = (
            self.db.query(CategorizationBucket.order_index)
            .filter(
                CategorizationBucket.meeting_id == meeting_id,
                CategorizationBucket.activity_id == activity_id,
            )
            .order_by(CategorizationBucket.order_index.desc())
            .first()
        )
        next_order = int(max_order[0]) + 1 if max_order else 1
        category_id = str(category_id or "").strip() or f"{activity_id}:bucket-{next_order}"

        existing = (
            self.db.query(CategorizationBucket)
            .filter(
                CategorizationBucket.meeting_id == meeting_id,
                CategorizationBucket.activity_id == activity_id,
                CategorizationBucket.category_id == category_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Bucket category_id already exists.")

        bucket = CategorizationBucket(
            meeting_id=meeting_id,
            activity_id=activity_id,
            category_id=category_id,
            title=title,
            description=description,
            order_index=next_order,
            status="active",
            created_by=actor_user_id,
        )
        self.db.add(bucket)
        self.db.commit()
        self.db.refresh(bucket)
        self.log_event(
            meeting_id=meeting_id,
            activity_id=activity_id,
            actor_user_id=actor_user_id,
            event_type="bucket_created",
            payload={"category_id": category_id, "title": title},
            commit=True,
        )
        return bucket

    def update_bucket(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        category_id: str,
        actor_user_id: Optional[str],
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
    ) -> CategorizationBucket:
        bucket = (
            self.db.query(CategorizationBucket)
            .filter(
                CategorizationBucket.meeting_id == meeting_id,
                CategorizationBucket.activity_id == activity_id,
                CategorizationBucket.category_id == category_id,
            )
            .first()
        )
        if not bucket:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        if bucket.category_id == UNSORTED_CATEGORY_ID:
            raise HTTPException(status_code=400, detail="UNSORTED bucket cannot be edited.")

        if title is not None:
            title_value = str(title).strip()
            if not title_value:
                raise HTTPException(status_code=400, detail="Bucket title cannot be empty.")
            bucket.title = title_value
        if description is not None:
            bucket.description = description
        if status is not None:
            bucket.status = status
        self.db.add(bucket)
        self.db.commit()
        self.db.refresh(bucket)
        self.log_event(
            meeting_id=meeting_id,
            activity_id=activity_id,
            actor_user_id=actor_user_id,
            event_type="bucket_updated",
            payload={"category_id": category_id},
            commit=True,
        )
        return bucket

    def delete_bucket(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        category_id: str,
        actor_user_id: Optional[str],
    ) -> None:
        if category_id == UNSORTED_CATEGORY_ID:
            raise HTTPException(status_code=400, detail="UNSORTED bucket cannot be deleted.")
        bucket = (
            self.db.query(CategorizationBucket)
            .filter(
                CategorizationBucket.meeting_id == meeting_id,
                CategorizationBucket.activity_id == activity_id,
                CategorizationBucket.category_id == category_id,
            )
            .first()
        )
        if not bucket:
            raise HTTPException(status_code=404, detail="Bucket not found.")

        self.ensure_unsorted_bucket(meeting_id, activity_id, actor_user_id=actor_user_id)
        self.db.query(CategorizationAssignment).filter(
            CategorizationAssignment.meeting_id == meeting_id,
            CategorizationAssignment.activity_id == activity_id,
            CategorizationAssignment.category_id == category_id,
        ).update(
            {
                CategorizationAssignment.category_id: UNSORTED_CATEGORY_ID,
                CategorizationAssignment.is_unsorted: True,
                CategorizationAssignment.assigned_by: actor_user_id,
            },
            synchronize_session=False,
        )
        self.db.query(CategorizationBallot).filter(
            CategorizationBallot.meeting_id == meeting_id,
            CategorizationBallot.activity_id == activity_id,
            CategorizationBallot.category_id == category_id,
        ).update(
            {CategorizationBallot.category_id: UNSORTED_CATEGORY_ID},
            synchronize_session=False,
        )
        self.db.delete(bucket)
        self.db.commit()
        self.log_event(
            meeting_id=meeting_id,
            activity_id=activity_id,
            actor_user_id=actor_user_id,
            event_type="bucket_deleted",
            payload={"category_id": category_id, "remapped_to": UNSORTED_CATEGORY_ID},
            commit=True,
        )

    def reorder_buckets(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        ordered_category_ids: List[str],
        actor_user_id: Optional[str],
    ) -> List[CategorizationBucket]:
        buckets = self.list_buckets(meeting_id, activity_id)
        bucket_by_id = {bucket.category_id: bucket for bucket in buckets}

        normalized = [str(value).strip() for value in ordered_category_ids if str(value).strip()]
        if UNSORTED_CATEGORY_ID in bucket_by_id and UNSORTED_CATEGORY_ID not in normalized:
            normalized = [UNSORTED_CATEGORY_ID, *normalized]
        for category_id in bucket_by_id:
            if category_id not in normalized:
                normalized.append(category_id)

        for index, category_id in enumerate(normalized):
            bucket = bucket_by_id.get(category_id)
            if not bucket:
                continue
            bucket.order_index = index
            self.db.add(bucket)
        self.db.commit()
        self.log_event(
            meeting_id=meeting_id,
            activity_id=activity_id,
            actor_user_id=actor_user_id,
            event_type="bucket_reordered",
            payload={"order": normalized},
            commit=True,
        )
        return self.list_buckets(meeting_id, activity_id)

    def build_state(self, meeting_id: str, activity_id: str) -> Dict[str, Any]:
        self.ensure_unsorted_bucket(meeting_id, activity_id, actor_user_id=None)
        buckets = self.list_buckets(meeting_id, activity_id)
        items = self.list_items(meeting_id, activity_id)
        assignments = (
            self.db.query(CategorizationAssignment)
            .filter(
                CategorizationAssignment.meeting_id == meeting_id,
                CategorizationAssignment.activity_id == activity_id,
            )
            .all()
        )
        assignment_map = {entry.item_key: entry.category_id for entry in assignments}
        return {
            "meeting_id": meeting_id,
            "activity_id": activity_id,
            "unsorted_category_id": UNSORTED_CATEGORY_ID,
            "buckets": [
                {
                    "category_id": bucket.category_id,
                    "title": bucket.title,
                    "description": bucket.description,
                    "order_index": bucket.order_index,
                    "status": bucket.status,
                }
                for bucket in buckets
            ],
            "items": [
                {
                    "item_key": item.item_key,
                    "content": item.content,
                    "submitted_name": item.submitted_name,
                    "metadata": item.item_metadata or {},
                    "source": item.source or {},
                }
                for item in items
            ],
            "assignments": assignment_map,
        }

    def upsert_ballot(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        user_id: str,
        item_key: str,
        category_id: Optional[str],
        submitted: bool,
    ) -> CategorizationBallot:
        ballot = (
            self.db.query(CategorizationBallot)
            .filter(
                CategorizationBallot.meeting_id == meeting_id,
                CategorizationBallot.activity_id == activity_id,
                CategorizationBallot.user_id == user_id,
                CategorizationBallot.item_key == item_key,
            )
            .first()
        )
        if ballot:
            ballot.category_id = category_id
            ballot.submitted = submitted
        else:
            ballot = CategorizationBallot(
                meeting_id=meeting_id,
                activity_id=activity_id,
                user_id=user_id,
                item_key=item_key,
                category_id=category_id,
                submitted=submitted,
            )
            self.db.add(ballot)
        self.db.commit()
        self.db.refresh(ballot)
        return ballot

    def set_final_assignment(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        item_key: str,
        category_id: str,
        resolver_user_id: Optional[str],
    ) -> CategorizationFinalAssignment:
        final_assignment = (
            self.db.query(CategorizationFinalAssignment)
            .filter(
                CategorizationFinalAssignment.meeting_id == meeting_id,
                CategorizationFinalAssignment.activity_id == activity_id,
                CategorizationFinalAssignment.item_key == item_key,
            )
            .first()
        )
        if final_assignment:
            final_assignment.category_id = category_id
            final_assignment.resolved_by = resolver_user_id
        else:
            final_assignment = CategorizationFinalAssignment(
                meeting_id=meeting_id,
                activity_id=activity_id,
                item_key=item_key,
                category_id=category_id,
                resolved_by=resolver_user_id,
            )
            self.db.add(final_assignment)
        self.db.commit()
        self.db.refresh(final_assignment)
        return final_assignment

    def log_event(
        self,
        *,
        meeting_id: str,
        activity_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        actor_user_id: Optional[str] = None,
        commit: bool = True,
    ) -> CategorizationAuditEvent:
        event = CategorizationAuditEvent(
            meeting_id=meeting_id,
            activity_id=activity_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            payload=payload or {},
        )
        self.db.add(event)
        if commit:
            self.db.commit()
            self.db.refresh(event)
        return event
