"""Transfer API routes.

Smug Otter: agenda activity resolution consults `AgendaStrategy` so transfer
eligibility and commits use the bound strategy's canonical agenda view.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_active_user
from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.database import get_db
from app.models.idea import Idea
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.schemas.meeting import AgendaActivityCreate, AgendaActivityResponse
from app.schemas.transfer import (
    TransferCommit,
    TransferCommitResponse,
    TransferDraftUpdate,
    TransferBundleItem,
)
from app.services import meeting_state_manager
from app.services.activity_catalog import get_activity_definition
from app.services.agenda_strategy import get_agenda_strategy
from app.services.transfer_source import build_transfer_items
from app.services.transfer_transforms import apply_transfer_transform
from app.services.voting_manager import VotingManager
from app.services.categorization_manager import CategorizationManager
from app.services.rank_order_voting_manager import RankOrderVotingManager
from app.services.meeting_authorization import resolve_meeting_capabilities
from app.services.facilitator_edit_log import diff_packages, record_edit
from app.utils.transfer_metadata import append_transfer_history, ensure_transfer_metadata
from app.utils.websocket_manager import websocket_manager


transfer_router = APIRouter(prefix="/api/meetings/{meeting_id}/transfer")
logger = logging.getLogger(__name__)


def _assert_facilitator_access(meeting: Meeting, user: User) -> None:
    capabilities = resolve_meeting_capabilities(meeting, user)
    if not capabilities["can_manage"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only facilitators can transfer ideas.",
        )


def _resolve_activity(meeting: Meeting, activity_id: str):
    # Smug Otter: resolve against the strategy's canonical agenda view.
    activity = next(
        (
            item
            for item in get_agenda_strategy(meeting).list_agenda(meeting)
            if item.activity_id == activity_id
        ),
        None,
    )
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agenda activity not found"
        )
    return activity


def _serialize_bundle(bundle):
    if not bundle:
        return None
    return {
        "bundle_id": bundle.bundle_id,
        "meeting_id": bundle.meeting_id,
        "activity_id": bundle.activity_id,
        "kind": bundle.kind,
        "items": list(bundle.items or []),
        "metadata": dict(bundle.bundle_metadata or {}),
        "created_at": bundle.created_at,
        "updated_at": bundle.updated_at,
    }


def _normalize_items(items: List[TransferBundleItem]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for entry in items:
        if not entry:
            continue
        content = (entry.content or "").strip()
        if not content:
            continue
        entry_id = entry.id
        if entry_id is None and entry.source:
            entry_id = entry.source.get("original_id") or entry.source.get("id")
        normalized.append(
            {
                "id": entry_id,
                "content": content,
                "submitted_name": entry.submitted_name,
                "parent_id": entry.parent_id,
                "timestamp": entry.timestamp or entry.created_at,
                "updated_at": entry.updated_at,
                "meeting_id": entry.meeting_id,
                "activity_id": entry.activity_id,
                "user_id": entry.user_id,
                "user_color": entry.user_color,
                "metadata": dict(entry.metadata or {}),
                "source": entry.source or {},
            }
        )
    return normalized


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[tuple] = set()
    deduped: List[Dict[str, Any]] = []
    for entry in items:
        source = entry.get("source") or {}
        key = (
            entry.get("id")
            or source.get("original_id")
            or source.get("id")
            or entry.get("content"),
            entry.get("parent_id"),
            entry.get("submitted_name"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _generate_stable_key(content: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (content or "").strip().lower()).strip("-")
    return slug or f"item-{uuid.uuid4().hex[:8]}"


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _resolve_round_index(
    *,
    metadata: Optional[Dict[str, Any]],
    donor: AgendaActivity,
) -> int:
    existing = metadata.get("round_index") if isinstance(metadata, dict) else None
    if existing is not None:
        try:
            parsed = int(existing)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed >= 0 else 0
    donor_index = getattr(donor, "order_index", None)
    if isinstance(donor_index, int) and donor_index > 0:
        return max(donor_index - 1, 0)
    return 0


def _split_ideas_and_comments(
    items: List[Dict[str, Any]]
) -> tuple[list[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    ideas: List[Dict[str, Any]] = []
    comments_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    idea_ids = set()
    for entry in items:
        if entry.get("parent_id") is None:
            ideas.append(entry)
            if entry.get("id") is not None:
                idea_ids.add(entry.get("id"))
    for entry in items:
        parent_id = entry.get("parent_id")
        if parent_id is None:
            continue
        if parent_id not in idea_ids:
            continue
        comments_by_parent.setdefault(str(parent_id), []).append(entry)
    return ideas, comments_by_parent


def _append_comments_to_content(
    idea_entry: Dict[str, Any],
    comments_by_parent: Dict[str, List[Dict[str, Any]]],
) -> str:
    """
    Append comments to idea content in the format: (Comments: comment1; comment2; comment3)
    
    Args:
        idea_entry: The idea dictionary containing 'id' and 'content'
        comments_by_parent: Dictionary mapping parent idea IDs to their comment lists
    
    Returns:
        The idea content with appended comments if any exist, otherwise original content
    """
    content = str(idea_entry.get("content", "")).strip()
    idea_id = idea_entry.get("id")
    
    if not idea_id or str(idea_id) not in comments_by_parent:
        return content
    
    comments = comments_by_parent.get(str(idea_id), [])
    if not comments:
        return content
    
    # Extract comment text and filter out empty ones
    comment_texts = [
        str(comment.get("content", "")).strip()
        for comment in comments
        if comment.get("content")
    ]
    
    if not comment_texts:
        return content
    
    # Join comments with semicolon delimiter
    comments_str = "; ".join(comment_texts)
    
    # Append to content in parentheses
    return f"{content} (Comments: {comments_str})"


def _upsert_transfer_bundle(
    bundle_manager: ActivityBundleManager,
    meeting_id: str,
    activity_id: str,
    items: List[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]],
):
    existing = bundle_manager.get_latest_bundle(meeting_id, activity_id, "transfer")
    if existing:
        existing.items = items
        existing.bundle_metadata = metadata or {}
        bundle_manager.db.add(existing)
        bundle_manager.db.commit()
        bundle_manager.db.refresh(existing)
        return existing
    return bundle_manager.create_bundle(
        meeting_id, activity_id, "transfer", items, metadata
    )


async def _ensure_not_running(meeting_id: str, activity_id: str) -> None:
    snapshot = await meeting_state_manager.snapshot(meeting_id)
    if not snapshot:
        return
    current_activity = snapshot.get("currentActivity") or snapshot.get("agendaItemId")
    current_status = (snapshot.get("status") or "").lower()
    active_entries = snapshot.get("activeActivities") or []
    for entry in active_entries:
        entry_id = entry.get("activityId") or entry.get("activity_id")
        status_value = (entry.get("status") or "").lower()
        if entry_id == current_activity == activity_id and current_status != "in_progress":
            continue
        if entry_id == activity_id and status_value == "in_progress":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Activity is currently running. Stop it before transferring ideas.",
            )


async def _assert_transfer_eligible(
    target: AgendaActivity,
    donor_activity_id: str,
    meeting_id: str,
    meeting_manager: MeetingManager,
) -> None:
    """
    Validate whether a target activity can receive a transfer under the facilitator edit policy.

    The facilitator is trusted to edit any activity that is not currently running.
    Rejects:
    - 422 if target is the donor activity itself
    - 409 if target is currently running (delegated to `_ensure_not_running`)
    """
    if target.activity_id == donor_activity_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot transfer into the donor activity itself.",
        )
    await _ensure_not_running(meeting_id, target.activity_id)


async def _broadcast_agenda_update(
    meeting_id: str,
    initiator_id: str,
    meeting_manager: MeetingManager,
) -> None:
    updated_agenda_items = meeting_manager.list_agenda(meeting_id)
    payload = [
        AgendaActivityResponse.model_validate(item).model_dump()
        for item in updated_agenda_items
    ]
    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "agenda_update",
            "payload": payload,
            "meta": {"initiatorId": initiator_id},
        },
    )


def _map_transfer_config(
    target_tool: str,
    config: dict,
    ideas: list,
    comments_by_parent: dict,
    include_comments: bool,
    inherited_config_from_donor: bool,
) -> dict:
    """Apply tool-type-specific mapping of transferred ideas into the target config dict. Mutates and returns config."""
    if target_tool == "voting":
        config.setdefault("allow_retract", True)
        use_transferred_options = inherited_config_from_donor or not config.get("options")
        if use_transferred_options:
            options = []
            for entry in ideas:
                if not isinstance(entry, dict):
                    continue
                content = str(entry.get("content", "")).strip()
                if not content:
                    continue
                if include_comments and comments_by_parent:
                    modified_content = _append_comments_to_content(entry, comments_by_parent)
                    if modified_content != content:
                        logger.info(
                            "transfer commit appending comments: original='%s' modified='%s' idea_id=%s",
                            content[:50],
                            modified_content[:100],
                            entry.get("id"),
                        )
                    content = modified_content
                options.append(content)
            if options:
                config["options"] = options
                logger.info(
                    "transfer commit created voting options: count=%d include_comments=%s has_comments=%s",
                    len(options),
                    include_comments,
                    bool(comments_by_parent),
                )
    if target_tool == "categorization":
        incoming_items = config.get("items")
        items_missing = not isinstance(incoming_items, list) or not incoming_items
        if not items_missing:
            normalized_existing = [
                str(value).strip().lower()
                for value in incoming_items
                if str(value).strip()
            ]
            if normalized_existing in (
                ["edit item here"],
                ["one idea per line."],
            ):
                items_missing = True
        if items_missing:
            mapped_items = []
            for entry in ideas:
                if not isinstance(entry, dict):
                    continue
                content = str(entry.get("content", "")).strip()
                if not content:
                    continue
                if include_comments and comments_by_parent:
                    content = _append_comments_to_content(entry, comments_by_parent)
                mapped_items.append(content)
            if mapped_items:
                config["items"] = mapped_items
                logger.info(
                    "transfer commit created categorization items: count=%d include_comments=%s has_comments=%s",
                    len(mapped_items),
                    include_comments,
                    bool(comments_by_parent),
                )
        config.setdefault("mode", "FACILITATOR_LIVE")
    if target_tool == "rank_order_voting":
        incoming_ideas = config.get("ideas")
        ideas_missing = (
            inherited_config_from_donor
            or not isinstance(incoming_ideas, list)
            or not incoming_ideas
        )
        if ideas_missing:
            mapped_ideas: List[Dict[str, Any]] = []
            for entry in ideas:
                if not isinstance(entry, dict):
                    continue
                content = str(entry.get("content", "")).strip()
                if not content:
                    continue
                if include_comments and comments_by_parent:
                    content = _append_comments_to_content(entry, comments_by_parent)
                entry_metadata = dict(entry.get("metadata") or {})
                if not entry_metadata.get("stable_key"):
                    entry_metadata["stable_key"] = _generate_stable_key(content)
                mapped_entry = {
                    "id": entry.get("id"),
                    "content": content,
                    "submitted_name": entry.get("submitted_name"),
                    "parent_id": None,
                    "created_at": entry.get("timestamp") or entry.get("created_at"),
                    "metadata": entry_metadata,
                    "source": dict(entry.get("source") or {}),
                }
                mapped_ideas.append(mapped_entry)
            if mapped_ideas:
                config["ideas"] = mapped_ideas
                logger.info(
                    "transfer commit created rank-order ideas: count=%d include_comments=%s has_comments=%s",
                    len(mapped_ideas),
                    include_comments,
                    bool(comments_by_parent),
                )
        config.setdefault("show_results_immediately", False)
        config.setdefault("allow_reset", True)
        config.setdefault("randomize_order", True)
    return config


def _seed_brainstorming_ideas(
    db: Session,
    meeting_id: str,
    activity_id: str,
    ideas: list,
    comments_by_parent: dict,
) -> Dict[str, Any]:
    """Reconcile transferred ideas and comments as Idea rows, keyed on stable_key."""
    # 1. Ensure every incoming item has metadata["stable_key"]
    synthesized_keys: set[str] = set()
    for idea_entry in ideas:
        entry_meta = dict(idea_entry.get("metadata") or {})
        if not entry_meta.get("stable_key"):
            key = _generate_stable_key(str(idea_entry.get("content") or ""))
            entry_meta["stable_key"] = key
            synthesized_keys.add(key)
            idea_entry["metadata"] = entry_meta

    # 2. Index existing top-level rows (parent_id is None) for the activity by idea_metadata.get("stable_key")
    existing_rows = (
        db.query(Idea)
        .filter(
            Idea.meeting_id == meeting_id,
            Idea.activity_id == activity_id,
            Idea.parent_id.is_(None),
        )
        .all()
    )
    existing_by_key: Dict[str, Idea] = {}
    for row in existing_rows:
        row_meta = row.idea_metadata if isinstance(row.idea_metadata, dict) else {}
        key = row_meta.get("stable_key")
        if not key:
            key = _generate_stable_key(row.content or "")
        if key not in existing_by_key:
            existing_by_key[key] = row

    existing_comment_rows = (
        db.query(Idea)
        .filter(
            Idea.meeting_id == meeting_id,
            Idea.activity_id == activity_id,
            Idea.parent_id.isnot(None),
        )
        .all()
    )

    matched_keys: set[str] = set()
    added: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    changed: List[Dict[str, Any]] = []
    removed_comments: List[Dict[str, Any]] = []
    idea_map: Dict[str, int] = {}

    # 3. Matched -> update in place: set content, submitted_name, merge idea_metadata.
    #    Preserve id, user_id, and timestamp.
    # 4. Unmatched incoming -> insert, carrying user_id from the item (entry.get("user_id"))
    #    alongside the existing fields.
    for idea_entry in ideas:
        entry_meta = dict(idea_entry.get("metadata") or {})
        key = entry_meta["stable_key"]
        content = str(idea_entry.get("content") or "").strip()
        submitted_name = idea_entry.get("submitted_name")
        incoming_user_id = idea_entry.get("user_id")

        existing_idea = existing_by_key.pop(key, None)
        if existing_idea is not None:
            matched_keys.add(key)
            if existing_idea.content != content:
                changed.append({
                    "before": {
                        "stable_key": key,
                        "content": existing_idea.content,
                        "user_id": existing_idea.user_id,
                    },
                    "after": {
                        "stable_key": key,
                        "content": content,
                        "user_id": existing_idea.user_id,
                    },
                })
            existing_idea.content = content
            if submitted_name is not None:
                existing_idea.submitted_name = submitted_name
            merged_meta = dict(existing_idea.idea_metadata or {})
            incoming_meta = dict(entry_meta)
            if key in synthesized_keys and "stable_key" not in (existing_idea.idea_metadata or {}):
                incoming_meta.pop("stable_key", None)
            merged_meta.update(incoming_meta)
            existing_idea.idea_metadata = merged_meta
            db.add(existing_idea)
            db.flush()
            target_id = existing_idea.id
        else:
            new_meta = dict(entry_meta)
            if key in synthesized_keys:
                new_meta.pop("stable_key", None)
            new_idea = Idea(
                meeting_id=meeting_id,
                activity_id=activity_id,
                content=content,
                submitted_name=submitted_name,
                parent_id=None,
                idea_metadata=new_meta,
                user_id=incoming_user_id,
            )
            timestamp = _parse_iso_timestamp(
                idea_entry.get("timestamp") or idea_entry.get("created_at")
            )
            if timestamp:
                new_idea.timestamp = timestamp
            db.add(new_idea)
            db.flush()
            target_id = new_idea.id
            added.append({
                "stable_key": key,
                "content": content,
                "user_id": incoming_user_id,
            })

        if idea_entry.get("id") is not None:
            idea_map[str(idea_entry.get("id"))] = target_id
        idea_map[key] = target_id
        idea_map[str(target_id)] = target_id

    # 5. Existing rows with no incoming match -> delete, but only after their
    #    {stable_key, content, user_id, submitted_name} has been collected for the caller,
    #    and their child comment rows have been collected and explicitly deleted.
    deleted_parent_ids: set[int] = set()
    for key, remaining_row in existing_by_key.items():
        removed.append({
            "stable_key": key,
            "content": remaining_row.content,
            "user_id": remaining_row.user_id,
            "submitted_name": remaining_row.submitted_name,
        })
        deleted_parent_ids.add(remaining_row.id)
        child_comments = [c for c in existing_comment_rows if c.parent_id == remaining_row.id]
        for child in child_comments:
            c_meta = child.idea_metadata if isinstance(child.idea_metadata, dict) else {}
            c_key = c_meta.get("stable_key")
            if not c_key:
                c_key = _generate_stable_key(child.content or "")
            removed_comments.append({
                "stable_key": c_key,
                "content": child.content,
                "user_id": child.user_id,
                "parent_stable_key": key,
            })
            db.delete(child)
        db.delete(remaining_row)
    db.flush()

    # 6. Reconcile comments for surviving ideas.
    #    Surviving comments are indexed by (parent_id, stable_key).
    surviving_comment_rows = [
        c for c in existing_comment_rows if c.parent_id not in deleted_parent_ids
    ]
    existing_comments_by_key: Dict[Tuple[int, str], List[Idea]] = {}
    for crow in surviving_comment_rows:
        cmeta = crow.idea_metadata if isinstance(crow.idea_metadata, dict) else {}
        ckey = cmeta.get("stable_key")
        if not ckey:
            ckey = _generate_stable_key(crow.content or "")
        k = (int(crow.parent_id), ckey)
        existing_comments_by_key.setdefault(k, []).append(crow)

    for parent_key, comment_entries in (comments_by_parent or {}).items():
        parent_id = idea_map.get(str(parent_key)) or idea_map.get(parent_key)
        if not parent_id:
            continue
        for comment_entry in comment_entries:
            c_meta = dict(comment_entry.get("metadata") or {})
            c_key = c_meta.get("stable_key")
            if not c_key:
                c_key = _generate_stable_key(str(comment_entry.get("content") or ""))
            k = (int(parent_id), c_key)
            matches = existing_comments_by_key.get(k)
            if matches:
                existing_comment = matches.pop(0)
                incoming_content = comment_entry.get("content")
                if incoming_content is not None:
                    existing_comment.content = incoming_content
                if comment_entry.get("submitted_name") is not None:
                    existing_comment.submitted_name = comment_entry.get("submitted_name")
                merged_meta = dict(existing_comment.idea_metadata or {})
                merged_meta.update(c_meta)
                existing_comment.idea_metadata = merged_meta
                db.add(existing_comment)
            else:
                comment = Idea(
                    meeting_id=meeting_id,
                    activity_id=activity_id,
                    content=comment_entry.get("content"),
                    submitted_name=comment_entry.get("submitted_name"),
                    parent_id=int(parent_id),
                    idea_metadata=c_meta,
                    user_id=comment_entry.get("user_id"),
                )
                timestamp = _parse_iso_timestamp(
                    comment_entry.get("timestamp") or comment_entry.get("created_at")
                )
                if timestamp:
                    comment.timestamp = timestamp
                db.add(comment)
    db.flush()

    seeded_count = (
        db.query(Idea)
        .filter(
            Idea.meeting_id == meeting_id,
            Idea.activity_id == activity_id,
        )
        .count()
    )
    logger.info(
        "transfer commit seeded brainstorming ideas meeting=%s activity=%s ideas=%d comments=%d total=%d",
        meeting_id,
        activity_id,
        len(ideas),
        sum(len(entries) for entries in (comments_by_parent or {}).values()),
        seeded_count,
    )
    # 7. Return a diff dict: {"added": [...], "removed": [...], "changed": [{"before","after"}], "removed_comments": [...]},
    #    each entry {stable_key, content, user_id}.
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "removed_comments": removed_comments,
    }


@transfer_router.get("/bundles")
async def get_transfer_bundles(
    meeting_id: str,
    activity_id: str = Query(..., description="Donor activity identifier"),
    include_comments: bool = Query(True, description="Include comments in response"),
    transfer_profile: Optional[str] = Query(
        None, description="Transfer transform profile applied before editing"
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.agenda_activities),
        )
        .filter(Meeting.meeting_id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )
    _assert_facilitator_access(meeting, current_user)
    activity = _resolve_activity(meeting, activity_id)
    await _ensure_not_running(meeting_id, activity_id)

    items, source, source_metadata = build_transfer_items(
        db,
        meeting,
        activity,
        include_comments=include_comments,
    )
    transformed = apply_transfer_transform(
        items=items,
        donor_tool_type=activity.tool_type,
        requested_profile=transfer_profile,
        source_metadata=source_metadata,
    )
    items = transformed.items
    logger.info(
        "transfer bundles meeting=%s activity=%s ideas=%d include_comments=%s source=%s profile=%s",
        meeting_id,
        activity_id,
        len(items),
        include_comments,
        source,
        transformed.profile,
    )
    items = [
        {
            "id": item.get("id"),
            "content": item.get("content"),
            "submitted_name": item.get("submitted_name"),
            "parent_id": item.get("parent_id"),
            "timestamp": item.get("timestamp"),
            "updated_at": item.get("updated_at"),
            "meeting_id": item.get("meeting_id") or meeting_id,
            "activity_id": item.get("activity_id") or activity_id,
            "user_id": item.get("user_id"),
            "user_color": item.get("user_color"),
            "metadata": item.get("metadata") or {},
            "source": {
                **(item.get("source") or {}),
                "original_id": item.get("id"),
            },
        }
        for item in items
    ]
    input_bundle = {
        "bundle_id": None,
        "meeting_id": meeting_id,
        "activity_id": activity_id,
        "kind": "input",
        "items": items,
        "metadata": {
            "include_comments": include_comments,
            "transfer_profile": transformed.profile,
            "source_tool_type": str(activity.tool_type or "").lower(),
            "source_metadata": source_metadata,
        },
        "created_at": None,
        "updated_at": None,
    }

    bundle_manager = ActivityBundleManager(db)
    draft = _serialize_bundle(
        bundle_manager.get_latest_bundle(meeting_id, activity_id, "transfer")
    )
    return {"input": input_bundle, "draft": draft}


@transfer_router.put("/draft")
async def update_transfer_draft(
    meeting_id: str,
    payload: TransferDraftUpdate,
    activity_id: str = Query(..., description="Donor activity identifier"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.agenda_activities),
        )
        .filter(Meeting.meeting_id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )
    _assert_facilitator_access(meeting, current_user)
    donor = _resolve_activity(meeting, activity_id)
    await _ensure_not_running(meeting_id, activity_id)

    normalized = _dedupe_items(_normalize_items(payload.items))
    metadata = dict(payload.metadata or {})
    metadata["include_comments"] = payload.include_comments
    round_index = _resolve_round_index(metadata=metadata, donor=donor)
    metadata = ensure_transfer_metadata(
        base=metadata,
        meeting_id=meeting_id,
        source_activity_id=activity_id,
        source_tool_type=donor.tool_type,
        round_index=round_index,
        tool_type="transfer",
        tool_details={
            "include_comments": payload.include_comments,
            "item_count": len(normalized),
        },
    )
    append_transfer_history(
        metadata=metadata,
        tool_type="transfer_draft",
        activity_id=activity_id,
        details={
            "include_comments": payload.include_comments,
            "item_count": len(normalized),
        },
        created_at=metadata.get("created_at"),
    )
    bundle_manager = ActivityBundleManager(db)
    draft = _upsert_transfer_bundle(
        bundle_manager, meeting_id, activity_id, normalized, metadata
    )
    return _serialize_bundle(draft)


@transfer_router.post("/commit", response_model=TransferCommitResponse)
async def commit_transfer(
    meeting_id: str,
    payload: TransferCommit,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.agenda_activities),
        )
        .filter(Meeting.meeting_id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        )
    _assert_facilitator_access(meeting, current_user)
    donor = _resolve_activity(meeting, payload.donor_activity_id)
    await _ensure_not_running(meeting_id, payload.donor_activity_id)

    normalized = _normalize_items(payload.items)
    ideas, comments_by_parent = _split_ideas_and_comments(normalized)
    if not payload.include_comments:
        comments_by_parent = {}

    target = payload.target_activity
    existing_target_mode = bool(target.activity_id)
    prior_content: list = []
    if target.activity_id:
        existing_target = _resolve_activity(meeting, target.activity_id)
        await _assert_transfer_eligible(
            existing_target, payload.donor_activity_id, meeting_id, meeting_manager
        )
        target_tool = (existing_target.tool_type or "").strip().lower()
        # Crimson Narwhal: existing-activity commit path — replaces content config, preserves settings.
        config = dict(existing_target.config or {})
        for content_key in ("options", "items", "ideas"):
            if content_key in config and isinstance(config[content_key], list):
                prior_content = list(config[content_key])
                break
        for content_key in ("options", "items", "ideas"):
            config.pop(content_key, None)
        config = _map_transfer_config(
            target_tool=target_tool,
            config=config,
            ideas=ideas,
            comments_by_parent=comments_by_parent,
            include_comments=payload.include_comments,
            inherited_config_from_donor=False,
        )
        existing_target.config = config
        db.add(existing_target)
        db.flush()
        created = existing_target
    else:
        target_tool = (target.tool_type or "").strip().lower()
        definition = get_activity_definition(target.tool_type)
        if not definition:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown tool type '{target.tool_type}'",
            )
        title = (target.title or "").strip()
        if not title:
            donor_title = (donor.title or "").strip()
            if donor_title:
                title = f"{donor_title} - Transfer"
            else:
                title = definition.get("label") or target.tool_type.replace("_", " ").title()
        config = dict(target.config or {})
        inherited_config_from_donor = False
        if not config and (donor.tool_type or "").lower() == target.tool_type.lower():
            config = dict(getattr(donor, "config", {}) or {})
            inherited_config_from_donor = True
        config = _map_transfer_config(
            target_tool=target_tool,
            config=config,
            ideas=ideas,
            comments_by_parent=comments_by_parent,
            include_comments=payload.include_comments,
            inherited_config_from_donor=inherited_config_from_donor,
        )
        agenda_payload = AgendaActivityCreate(
            tool_type=target_tool or target.tool_type,
            title=title,
            instructions=target.instructions,
            config=config,
            order_index=(donor.order_index or 0) + 1,
        )
        created = meeting_manager.add_agenda_activity(meeting_id, agenda_payload)

    # State init for existing target mirrors create path and is safe due to eligibility checks.
    if target_tool == "voting":
        VotingManager(meeting_manager.db).reset_activity_state(
            meeting_id, created.activity_id, clear_bundles=True
        )
    if target_tool == "categorization":
        cat_manager = CategorizationManager(meeting_manager.db)
        cat_manager.reset_activity_state(
            meeting_id, created.activity_id, clear_bundles=True
        )
        cat_manager.seed_activity(
            meeting_id=meeting_id,
            activity=created,
            actor_user_id=current_user.user_id,
        )
    if target_tool == "rank_order_voting":
        RankOrderVotingManager(meeting_manager.db).reset_activity_state(
            meeting_id, created.activity_id, clear_bundles=True
        )

    bundle_metadata = dict(payload.metadata or {})
    round_index = _resolve_round_index(metadata=bundle_metadata, donor=donor)
    bundle_metadata = ensure_transfer_metadata(
        base=bundle_metadata,
        meeting_id=meeting_id,
        source_activity_id=payload.donor_activity_id,
        source_tool_type=donor.tool_type,
        round_index=round_index,
        tool_type="transfer",
        tool_details={
            "include_comments": payload.include_comments,
            "idea_count": len(ideas),
            "comment_count": sum(len(entries) for entries in comments_by_parent.values()),
        },
    )
    append_transfer_history(
        metadata=bundle_metadata,
        tool_type="transfer_commit",
        activity_id=payload.donor_activity_id,
        details={
            "target_tool_type": target_tool,
            "target_activity_id": created.activity_id,
            "target_mode": "existing" if existing_target_mode else "new",
            "include_comments": payload.include_comments,
            "idea_count": len(ideas),
            "comment_count": sum(len(entries) for entries in comments_by_parent.values()),
        },
        created_at=bundle_metadata.get("created_at"),
    )
    bundle_metadata.update(
        {
            "source_activity_id": payload.donor_activity_id,
            "include_comments": payload.include_comments,
            "comments_by_parent": comments_by_parent,
        }
    )
    bundle_metadata = ensure_transfer_metadata(
        base=bundle_metadata,
        meeting_id=meeting_id,
        source_activity_id=payload.donor_activity_id,
        source_tool_type=donor.tool_type,
        round_index=round_index,
        tool_type=target_tool,
        tool_details={
            "activity_id": created.activity_id,
            "title": created.title,
        },
    )
    bundle_manager = ActivityBundleManager(db)
    input_bundle = bundle_manager.create_bundle(
        meeting_id, created.activity_id, "input", ideas, bundle_metadata
    )
    diff = None
    if target_tool == "brainstorming":
        diff = _seed_brainstorming_ideas(
            db=db,
            meeting_id=meeting_id,
            activity_id=created.activity_id,
            ideas=ideas,
            comments_by_parent=comments_by_parent,
        )
    else:
        diff = diff_packages(before=prior_content, after=ideas)

    event_type = "package_edited" if existing_target_mode else "package_transferred"
    record_edit(
        db=db,
        meeting_id=meeting_id,
        activity_id=created.activity_id,
        donor_activity_id=payload.donor_activity_id,
        actor_user_id=current_user.user_id,
        event_type=event_type,
        diff=diff,
    )
    db.commit()

    await _broadcast_agenda_update(meeting_id, current_user.user_id, meeting_manager)
    await meeting_state_manager.apply_patch(
        meeting_id,
        {
            "currentActivity": created.activity_id,
            "agendaItemId": created.activity_id,
            "currentTool": created.tool_type,
            "status": "stopped",
        },
    )

    agenda_items = meeting_manager.list_agenda(meeting_id)
    target_activity_payload = AgendaActivityResponse.model_validate(created).model_dump()
    # target_activity is the canonical key; new_activity is None for existing-target transfers.
    return {
        "target_activity": target_activity_payload,
        "new_activity": None if existing_target_mode else target_activity_payload,
        "agenda": [
            AgendaActivityResponse.model_validate(item).model_dump()
            for item in agenda_items
        ],
        "input_bundle_id": input_bundle.bundle_id,
    }
