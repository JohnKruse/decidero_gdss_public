from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User
from app.plugins.base import ActivityPlugin
from app.plugins.context import ActivityContext


_autosave_tasks: Dict[str, asyncio.Task] = {}


async def _run_autosave(
    plugin: ActivityPlugin,
    meeting_id: str,
    activity_id: str,
    user_id: Optional[str],
    interval_seconds: int,
) -> None:
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            db: Session = SessionLocal()
            try:
                meeting = (
                    db.query(Meeting)
                    .filter(Meeting.meeting_id == meeting_id)
                    .first()
                )
                activity = (
                    db.query(AgendaActivity)
                    .filter(AgendaActivity.activity_id == activity_id)
                    .first()
                )
                if not meeting or not activity:
                    return
                user = None
                if user_id:
                    user = db.query(User).filter(User.user_id == user_id).first()
                context = ActivityContext(
                    db=db, meeting=meeting, activity=activity, user=user
                )
                snapshot = plugin.snapshot_activity(context)
                if not snapshot:
                    continue
                items = snapshot.get("items") if isinstance(snapshot, dict) else None
                if not isinstance(items, list):
                    continue
                metadata = snapshot.get("metadata") if isinstance(snapshot, dict) else None
                context.save_draft_bundle(items, metadata)
            finally:
                db.close()
    except asyncio.CancelledError:
        return


def start_autosave(
    plugin: ActivityPlugin,
    meeting_id: str,
    activity_id: str,
    user_id: Optional[str],
    interval_seconds: int,
) -> None:
    stop_autosave(activity_id)
    task = asyncio.create_task(
        _run_autosave(plugin, meeting_id, activity_id, user_id, interval_seconds)
    )
    _autosave_tasks[activity_id] = task


def stop_autosave(activity_id: str) -> None:
    task = _autosave_tasks.pop(activity_id, None)
    if task:
        task.cancel()
