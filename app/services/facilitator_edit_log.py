"""Facilitator edit audit logging service.

Provides package diffing and audit recording for facilitator edits and transfers.
Payloads retain item content so deleted items remain auditable.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.facilitator_edit import FacilitatorEditEvent


def _slug_or_hash(content: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (content or "").strip().lower()).strip("-")
    return slug or f"item-{uuid.uuid4().hex[:8]}"


def _extract_item_info(item: Any) -> Dict[str, Any]:
    if isinstance(item, str):
        content = item.strip()
        stable_key = _slug_or_hash(content)
        return {
            "stable_key": stable_key,
            "content": content,
            "user_id": None,
        }
    if isinstance(item, dict):
        content = str(
            item.get("content") or item.get("label") or item.get("text") or ""
        ).strip()
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        stable_key = meta.get("stable_key")
        if not stable_key:
            stable_key = _slug_or_hash(content)
        user_id = item.get("user_id")
        return {
            "stable_key": str(stable_key),
            "content": content,
            "user_id": user_id,
        }
    content = str(item).strip()
    return {
        "stable_key": _slug_or_hash(content),
        "content": content,
        "user_id": None,
    }


def diff_packages(before: Optional[List[Any]], after: Optional[List[Any]]) -> Dict[str, Any]:
    """Compare before and after item packages by stable_key, falling back to normalized content.

    Returns {"added": [...], "removed": [...], "changed": [{"before": ..., "after": ...}]}.
    """
    before_items = [_extract_item_info(x) for x in (before or [])]
    after_items = [_extract_item_info(x) for x in (after or [])]

    matched_before_indices: set[int] = set()
    matched_after_indices: set[int] = set()
    changed: List[Dict[str, Any]] = []
    added: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []

    # Pass 1: match by stable_key
    for j, after_item in enumerate(after_items):
        after_key = after_item["stable_key"]
        for i, before_item in enumerate(before_items):
            if i in matched_before_indices:
                continue
            if before_item["stable_key"] == after_key:
                matched_before_indices.add(i)
                matched_after_indices.add(j)
                if before_item["content"] != after_item["content"]:
                    changed.append({"before": before_item, "after": after_item})
                break

    # Pass 2: fallback to normalized content match for unmatched items
    for j, after_item in enumerate(after_items):
        if j in matched_after_indices:
            continue
        after_norm = after_item["content"].strip().lower()
        for i, before_item in enumerate(before_items):
            if i in matched_before_indices:
                continue
            if before_item["content"].strip().lower() == after_norm:
                matched_before_indices.add(i)
                matched_after_indices.add(j)
                if before_item["content"] != after_item["content"]:
                    changed.append({"before": before_item, "after": after_item})
                break

    # Pass 3: remaining in after are added
    for j, after_item in enumerate(after_items):
        if j not in matched_after_indices:
            added.append(after_item)

    # Pass 4: remaining in before are removed
    for i, before_item in enumerate(before_items):
        if i not in matched_before_indices:
            removed.append(before_item)

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def record_edit(
    db: Session,
    *,
    meeting_id: str,
    activity_id: str,
    donor_activity_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    event_type: str,
    diff: Optional[Dict[str, Any]],
) -> Optional[FacilitatorEditEvent]:
    """Write one FacilitatorEditEvent row if the diff contains changes; no-op otherwise."""
    if not diff:
        return None
    has_changes = bool(
        diff.get("added") or diff.get("removed") or diff.get("changed")
    )
    if not has_changes:
        return None

    event = FacilitatorEditEvent(
        meeting_id=meeting_id,
        activity_id=activity_id,
        donor_activity_id=donor_activity_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        payload=diff,
    )
    db.add(event)
    db.flush()
    return event
