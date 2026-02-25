from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.idea import Idea
from app.models.meeting import AgendaActivity, Meeting
from app.plugins.context import ActivityContext
from app.plugins.registry import get_activity_registry
from app.utils.user_colors import get_user_color

logger = logging.getLogger(__name__)


def build_transfer_items(
    db: Session,
    meeting: Meeting,
    activity: AgendaActivity,
    *,
    include_comments: bool,
) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    tool_type = (getattr(activity, "tool_type", "") or "").lower()
    plugin = get_activity_registry().get_plugin(tool_type)
    if plugin:
        context = ActivityContext(db=db, meeting=meeting, activity=activity)
        try:
            result = plugin.get_transfer_source(
                context, include_comments=include_comments
            )
        except HTTPException as exc:
            logger.warning(
                "transfer source plugin failed tool=%s activity=%s meeting=%s status=%s detail=%s",
                tool_type,
                getattr(activity, "activity_id", None),
                getattr(meeting, "meeting_id", None),
                getattr(exc, "status_code", None),
                getattr(exc, "detail", None),
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.exception(
                "transfer source plugin error tool=%s activity=%s meeting=%s error=%s",
                tool_type,
                getattr(activity, "activity_id", None),
                getattr(meeting, "meeting_id", None),
                exc,
            )
        else:
            if result is not None:
                items = _filter_transfer_items(
                    list(result.items or []), include_comments=include_comments
                )
                return items, result.source or "plugin", dict(result.metadata or {})

    items, source = _default_transfer_items(db, meeting, activity)
    items = _filter_transfer_items(items, include_comments=include_comments)
    return items, source, {}


def get_transfer_count(
    db: Session,
    meeting: Meeting,
    activity: AgendaActivity,
    *,
    idea_counts: Optional[Dict[str, int]] = None,
    bundle_counts: Optional[Dict[str, int]] = None,
) -> Tuple[int, str]:
    tool_type = (getattr(activity, "tool_type", "") or "").lower()
    plugin = get_activity_registry().get_plugin(tool_type)
    if plugin:
        context = ActivityContext(db=db, meeting=meeting, activity=activity)
        try:
            count = plugin.get_transfer_count(context)
            if count is not None:
                return max(int(count or 0), 0), "plugin"
            result = plugin.get_transfer_source(context, include_comments=False)
            if result is not None:
                items = _filter_transfer_items(
                    list(result.items or []), include_comments=False
                )
                return len(items), result.source or "plugin"
        except HTTPException as exc:
            logger.warning(
                "transfer count plugin failed tool=%s activity=%s meeting=%s status=%s detail=%s",
                tool_type,
                getattr(activity, "activity_id", None),
                getattr(meeting, "meeting_id", None),
                getattr(exc, "status_code", None),
                getattr(exc, "detail", None),
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.exception(
                "transfer count plugin error tool=%s activity=%s meeting=%s error=%s",
                tool_type,
                getattr(activity, "activity_id", None),
                getattr(meeting, "meeting_id", None),
                exc,
            )

    activity_id = activity.activity_id
    if tool_type == "brainstorming":
        if idea_counts is not None:
            count = int(idea_counts.get(activity_id, 0) or 0)
        else:
            count = _count_brainstorming_ideas(db, meeting, activity)
        return count, "ideas" if count > 0 else "none"

    if bundle_counts is not None:
        count = int(bundle_counts.get(activity_id, 0) or 0)
    else:
        count = _count_output_bundle_items(db, meeting, activity)
    return count, "bundle" if count > 0 else "none"


def _default_transfer_items(
    db: Session,
    meeting: Meeting,
    activity: AgendaActivity,
) -> Tuple[List[Dict[str, Any]], str]:
    tool_type = (getattr(activity, "tool_type", "") or "").lower()
    if tool_type == "brainstorming":
        ideas = (
            db.query(Idea)
            .filter(
                Idea.meeting_id == meeting.meeting_id,
                Idea.activity_id == activity.activity_id,
            )
            .order_by(Idea.timestamp)
            .all()
        )
        return [_serialize_export_idea(idea) for idea in ideas], "ideas"

    bundle_manager = ActivityBundleManager(db)
    output_bundle = bundle_manager.get_latest_bundle(
        meeting.meeting_id, activity.activity_id, "output"
    )
    raw_items = list(getattr(output_bundle, "items", []) or [])
    items = [
        _normalize_bundle_item(
            item, meeting_id=meeting.meeting_id, activity_id=activity.activity_id
        )
        for item in raw_items
        if isinstance(item, dict)
    ]
    return items, "bundle"


def _filter_transfer_items(
    items: List[Dict[str, Any]],
    *,
    include_comments: bool,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        normalized = dict(entry)
        content = str(
            normalized.get("content")
            or normalized.get("label")
            or ""
        ).strip()
        if not content:
            continue
        normalized["content"] = content
        if not include_comments and normalized.get("parent_id") is not None:
            continue
        filtered.append(normalized)
    return filtered


def _serialize_export_idea(idea: Idea) -> Dict[str, Any]:
    return {
        "id": idea.id,
        "content": idea.content,
        "parent_id": idea.parent_id,
        "timestamp": idea.timestamp.isoformat() if idea.timestamp else None,
        "updated_at": idea.updated_at.isoformat() if idea.updated_at else None,
        "meeting_id": idea.meeting_id,
        "activity_id": idea.activity_id,
        "user_id": idea.user_id,
        "user_color": get_user_color(user=idea.author),
        "user_avatar_key": getattr(getattr(idea, "author", None), "avatar_key", None),
        "user_avatar_icon_path": getattr(
            getattr(idea, "author", None), "avatar_icon_path", None
        ),
        "submitted_name": idea.submitted_name,
        "metadata": idea.idea_metadata or {},
        "source": {
            "meeting_id": idea.meeting_id,
            "activity_id": idea.activity_id,
        },
    }


def _normalize_bundle_item(
    item: Dict[str, Any],
    *,
    meeting_id: str,
    activity_id: str,
) -> Dict[str, Any]:
    content = str(item.get("content") or item.get("label") or "").strip()
    return {
        "id": item.get("id"),
        "content": content,
        "parent_id": item.get("parent_id"),
        "timestamp": item.get("timestamp") or item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "meeting_id": item.get("meeting_id") or meeting_id,
        "activity_id": item.get("activity_id") or activity_id,
        "user_id": item.get("user_id"),
        "user_color": item.get("user_color"),
        "user_avatar_key": item.get("user_avatar_key"),
        "user_avatar_icon_path": item.get("user_avatar_icon_path"),
        "submitted_name": item.get("submitted_name"),
        "metadata": item.get("metadata") or {},
        "source": item.get("source") or {},
    }


def _count_brainstorming_ideas(
    db: Session,
    meeting: Meeting,
    activity: AgendaActivity,
) -> int:
    return (
        db.query(Idea)
        .filter(
            Idea.meeting_id == meeting.meeting_id,
            Idea.activity_id == activity.activity_id,
            Idea.parent_id.is_(None),
        )
        .count()
    )


def _count_output_bundle_items(
    db: Session,
    meeting: Meeting,
    activity: AgendaActivity,
) -> int:
    bundle_manager = ActivityBundleManager(db)
    output_bundle = bundle_manager.get_latest_bundle(
        meeting.meeting_id, activity.activity_id, "output"
    )
    items = list(getattr(output_bundle, "items", []) or [])
    return len(items)
