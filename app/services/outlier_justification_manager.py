"""Per-viewer outlier justification: queue + comment-only rationale store.

Canary: Plainspoken Marmot

The justification activity is **one activity with per-viewer content** (the same
shape as rank_order_voting's per-user ballot), not N activities and not a shared
list participants sift. Each participant's queue is the set of items where they
were flagged as an outlier this round — already computed by the Delphi
aggregation (`metadata.delphi.outlier_flags[user]`) and seeded onto the activity
config at open time. The server projects that seed per requesting user, so a
participant only ever receives their own flagged items (peer-anonymity is
preserved: no one sees who else was an outlier). Submission is comment-only — a
rationale may be written only for an item in the writer's own queue; there is no
path to create items here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.meeting import AgendaActivity, Meeting
from app.models.outlier_rationale import OutlierRationale
from app.models.user import User


class JustificationError(ValueError):
    """Raised on an invalid justification submission (e.g. a non-queued item)."""


class OutlierJustificationManager:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _seed(activity: AgendaActivity) -> List[Dict[str, Any]]:
        """The per-item seed stored at open time: option_id, content, delphi
        stats, outlier_flags, and ranks_by_user (server-side only)."""
        return list((activity.config or {}).get("justification_seed") or [])

    def queue_for(self, activity: AgendaActivity, user_id: str) -> List[Dict[str, Any]]:
        """The items `user_id` must justify, each with their own rank + group spread.

        Only the requesting user's rank is exposed; other participants' ranks
        stay in the server-side seed and are never returned.
        """
        queue: List[Dict[str, Any]] = []
        for entry in self._seed(activity):
            flags = entry.get("outlier_flags") or {}
            if not flags.get(user_id):
                continue
            ranks = entry.get("ranks_by_user") or {}
            queue.append(
                {
                    "option_id": entry.get("option_id"),
                    "content": entry.get("content"),
                    "your_rank": ranks.get(user_id),
                    "group_median": entry.get("median"),
                    "group_iqr": entry.get("iqr"),
                }
            )
        return queue

    def _rationales(
        self, meeting: Meeting, activity: AgendaActivity, user_id: Optional[str] = None
    ) -> List[OutlierRationale]:
        query = self.db.query(OutlierRationale).filter(
            OutlierRationale.meeting_id == meeting.meeting_id,
            OutlierRationale.activity_id == activity.activity_id,
        )
        if user_id is not None:
            query = query.filter(OutlierRationale.user_id == user_id)
        return query.all()

    def build_state(
        self, meeting: Meeting, activity: AgendaActivity, user: User
    ) -> Dict[str, Any]:
        """The per-viewer payload: the user's queue with any saved rationales,
        whether they have nothing to do, and whether every item is answered."""
        queue = self.queue_for(activity, user.user_id)
        saved = {r.option_id: r.rationale for r in self._rationales(meeting, activity, user.user_id)}
        items = [{**entry, "rationale": saved.get(entry["option_id"], "")} for entry in queue]
        return {
            "activity_id": activity.activity_id,
            "items": items,
            "nothing_to_justify": len(items) == 0,
            "submitted": bool(items) and all((i["rationale"] or "").strip() for i in items),
        }

    def submit_rationale(
        self,
        meeting: Meeting,
        activity: AgendaActivity,
        user: User,
        option_id: str,
        rationale: str,
    ) -> OutlierRationale:
        """Upsert a rationale for one of the user's own flagged items (idempotent).

        Comment-only: the option must be in the user's queue — there is no way to
        justify an item not flagged for them, and no way to introduce a new item.
        """
        allowed = {entry["option_id"] for entry in self.queue_for(activity, user.user_id)}
        if option_id not in allowed:
            raise JustificationError(
                "This item is not in your justification queue; you can only explain "
                "your own outlier rankings."
            )
        row = (
            self.db.query(OutlierRationale)
            .filter(
                OutlierRationale.meeting_id == meeting.meeting_id,
                OutlierRationale.activity_id == activity.activity_id,
                OutlierRationale.user_id == user.user_id,
                OutlierRationale.option_id == option_id,
            )
            .one_or_none()
        )
        if row is None:
            row = OutlierRationale(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id=user.user_id,
                option_id=option_id,
                rationale=rationale,
            )
            self.db.add(row)
        else:
            row.rationale = rationale
        self.db.commit()
        self.db.refresh(row)
        return row

    def collected_by_option(
        self, meeting: Meeting, activity: AgendaActivity
    ) -> Dict[str, List[str]]:
        """Non-empty rationales grouped by option, unattributed — the input to the
        next round's anonymized cross-round display (a later increment)."""
        grouped: Dict[str, List[str]] = {}
        for row in self._rationales(meeting, activity):
            text = (row.rationale or "").strip()
            if text:
                grouped.setdefault(row.option_id, []).append(text)
        return grouped
