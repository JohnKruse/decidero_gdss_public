"""Per-viewer Delphi justification: queue + comment-only rationale store.

Canary: Plainspoken Marmot

The justification activity is **one activity with per-viewer content** (the same
shape as rank_order_voting's per-user ballot), not N activities and not a shared
list participants sift. By default each participant's queue is the set of items
where they were flagged as an outlier this round. In adaptive Delphi feedback
rounds, the facilitator may instead open a selected set of low-consensus items
for comments from all participants. Submission remains comment-only: a rationale
may be written only for an item in the writer's queue; there is no path to
create items here.
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

    @staticmethod
    def _selected_items(activity: AgendaActivity) -> List[Dict[str, Any]]:
        """Facilitator-selected comment targets for adaptive Delphi feedback."""
        return list((activity.config or {}).get("selected_comment_items") or [])

    @staticmethod
    def _comment_scope(activity: AgendaActivity) -> str:
        return str((activity.config or {}).get("comment_scope") or "outliers_only")

    def uses_selected_items(self, activity: AgendaActivity) -> bool:
        return self._comment_scope(activity) == "selected_items"

    def comment_items(self, activity: AgendaActivity) -> List[Dict[str, Any]]:
        if self.uses_selected_items(activity):
            return self._selected_items(activity)
        return self._seed(activity)

    def queue_for(self, activity: AgendaActivity, user_id: str) -> List[Dict[str, Any]]:
        """The items `user_id` may comment on, with their own rank + group spread.

        Only the requesting user's rank is exposed; other participants' ranks
        stay in the server-side seed and are never returned.
        """
        queue: List[Dict[str, Any]] = []
        selected_mode = self.uses_selected_items(activity)
        for entry in self.comment_items(activity):
            if not selected_mode:
                flags = entry.get("outlier_flags") or {}
                if not flags.get(user_id):
                    continue
            option_id = entry.get("option_id")
            if not option_id:
                continue
            ranks = entry.get("ranks_by_user") or {}
            queue.append(
                {
                    "option_id": option_id,
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
        saved = {
            r.option_id: r.rationale
            for r in self._rationales(meeting, activity, user.user_id)
        }
        items = [
            {**entry, "rationale": saved.get(entry["option_id"], "")} for entry in queue
        ]
        return {
            "activity_id": activity.activity_id,
            "items": items,
            "nothing_to_justify": len(items) == 0,
            "submitted": bool(items)
            and all((i["rationale"] or "").strip() for i in items),
        }

    def facilitator_progress(
        self, meeting: Meeting, activity: AgendaActivity
    ) -> Dict[str, int]:
        """Return facilitator-facing completion counts without exposing identities.

        In selected-item mode, `outlier_count` is kept as the assignee count for
        API compatibility and `selected_item_count` names the opened item count.
        In outlier mode, `outlier_count` remains the number of distinct
        participants with at least one queued outlier. `submitted_count` counts
        assignees with non-empty rationales for every item in their own queue.
        """
        selected_mode = self.uses_selected_items(activity)
        if selected_mode:
            assignee_user_ids = {
                str(user.user_id)
                for user in getattr(meeting, "participants", [])
                if str(getattr(user, "user_id", "")).strip()
            }
        else:
            assignee_user_ids = {
                str(user_id)
                for entry in self._seed(activity)
                for user_id, flagged in (entry.get("outlier_flags") or {}).items()
                if flagged and str(user_id).strip()
            }
        saved = {
            (row.user_id, row.option_id): (row.rationale or "").strip()
            for row in self._rationales(meeting, activity)
        }
        submitted_count = 0
        for user_id in assignee_user_ids:
            queue = self.queue_for(activity, user_id)
            if queue and all(
                saved.get((user_id, entry["option_id"])) for entry in queue
            ):
                submitted_count += 1
        progress = {
            "outlier_count": len(assignee_user_ids),
            "submitted_count": submitted_count,
        }
        if selected_mode:
            progress["selected_item_count"] = len(self._selected_items(activity))
        return progress

    def submit_rationale(
        self,
        meeting: Meeting,
        activity: AgendaActivity,
        user: User,
        option_id: str,
        rationale: str,
    ) -> OutlierRationale:
        """Upsert a rationale for one queued comment item (idempotent).

        Comment-only: the option must be in the user's queue, and there is no way
        to introduce a new item.
        """
        allowed = {
            entry["option_id"] for entry in self.queue_for(activity, user.user_id)
        }
        if option_id not in allowed:
            if self.uses_selected_items(activity):
                raise JustificationError(
                    "This item is not open for comments in this feedback round."
                )
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
