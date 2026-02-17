from __future__ import annotations

from datetime import datetime, timedelta, UTC
from hashlib import sha256
import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.idempotency import BrainstormingIdempotencyKey


class BrainstormingIdempotencyManager:
    """Persistence helpers for brainstorming idempotency replays."""

    def _ttl_cutoff(self, ttl_hours: int = 48) -> datetime:
        return datetime.now(UTC) + timedelta(hours=max(1, ttl_hours))

    def build_request_hash(
        self,
        *,
        content: str,
        parent_id: Optional[int],
        metadata: Optional[Dict[str, Any]],
        submitted_name: Optional[str],
    ) -> str:
        normalized = {
            "content": (content or "").strip(),
            "parent_id": int(parent_id) if parent_id is not None else None,
            "metadata": metadata or {},
            "submitted_name": (submitted_name or "").strip() or None,
        }
        # Deterministic payload digest for mismatch detection.
        raw = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return sha256(raw).hexdigest()

    def get_existing(
        self,
        db: Session,
        *,
        meeting_id: str,
        activity_id: str,
        user_id: str,
        idempotency_key: str,
    ) -> Optional[BrainstormingIdempotencyKey]:
        now = datetime.now(UTC)
        return (
            db.query(BrainstormingIdempotencyKey)
            .filter(
                BrainstormingIdempotencyKey.meeting_id == meeting_id,
                BrainstormingIdempotencyKey.activity_id == activity_id,
                BrainstormingIdempotencyKey.user_id == user_id,
                BrainstormingIdempotencyKey.idempotency_key == idempotency_key,
                BrainstormingIdempotencyKey.expires_at > now,
            )
            .first()
        )

    def claim(
        self,
        db: Session,
        *,
        meeting_id: str,
        activity_id: str,
        user_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> BrainstormingIdempotencyKey:
        row = BrainstormingIdempotencyKey(
            meeting_id=meeting_id,
            activity_id=activity_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            expires_at=self._ttl_cutoff(),
        )
        db.add(row)
        db.flush()
        return row

    def store_success(
        self,
        db: Session,
        *,
        entry: BrainstormingIdempotencyKey,
        status_code: int,
        response_payload: Dict[str, Any],
        idea_id: Optional[int],
    ) -> None:
        entry.status_code = int(status_code)
        entry.response_payload = response_payload
        entry.idea_id = idea_id
        entry.expires_at = self._ttl_cutoff()
        db.add(entry)

    def prune_expired(self, db: Session) -> int:
        now = datetime.now(UTC)
        deleted = (
            db.query(BrainstormingIdempotencyKey)
            .filter(BrainstormingIdempotencyKey.expires_at <= now)
            .delete(synchronize_session=False)
        )
        return int(deleted or 0)
