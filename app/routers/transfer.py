from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_active_user
from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.database import get_db
from app.models.idea import Idea
from app.models.meeting import AgendaActivity, Meeting, MeetingFacilitator
from app.models.user import User, UserRole
from app.schemas.meeting import AgendaActivityCreate, AgendaActivityResponse
from app.schemas.transfer import TransferCommit, TransferDraftUpdate, TransferBundleItem
from app.services import meeting_state_manager
from app.services.activity_catalog import get_activity_definition
from app.services.transfer_source import build_transfer_items
from app.services.voting_manager import VotingManager
from app.services.categorization_manager import CategorizationManager
from app.utils.transfer_metadata import append_transfer_history, ensure_transfer_metadata
from app.utils.websocket_manager import websocket_manager


transfer_router = APIRouter(prefix="/api/meetings/{meeting_id}/transfer")
logger = logging.getLogger(__name__)


def _assert_facilitator_access(meeting: Meeting, user: User) -> None:
    facilitator_links = getattr(meeting, "facilitator_links", []) or []
    is_admin = user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
    is_owner = meeting.owner_id == user.user_id
    is_facilitator = any(link.user_id == user.user_id for link in facilitator_links)
    if not (is_admin or is_owner or is_facilitator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only facilitators can transfer ideas.",
        )


def _resolve_activity(meeting: Meeting, activity_id: str):
    activity = next(
        (
            item
            for item in getattr(meeting, "agenda_activities", [])
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
                "metadata": entry.metadata or {},
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
    active_entries = snapshot.get("activeActivities") or []
    for entry in active_entries:
        entry_id = entry.get("activityId") or entry.get("activity_id")
        status_value = (entry.get("status") or "").lower()
        if entry_id == activity_id and status_value == "in_progress":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Activity is currently running. Stop it before transferring ideas.",
            )


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


@transfer_router.get("/bundles")
async def get_transfer_bundles(
    meeting_id: str,
    activity_id: str = Query(..., description="Donor activity identifier"),
    include_comments: bool = Query(True, description="Include comments in response"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
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

    items, source = build_transfer_items(
        db,
        meeting,
        activity,
        include_comments=include_comments,
    )
    logger.info(
        "transfer bundles meeting=%s activity=%s ideas=%d include_comments=%s source=%s",
        meeting_id,
        activity_id,
        len(items),
        include_comments,
        source,
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
        "metadata": {"include_comments": include_comments},
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
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
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


@transfer_router.post("/commit")
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
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
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
    if not config and (donor.tool_type or "").lower() == target.tool_type.lower():
        config = dict(getattr(donor, "config", {}) or {})

    if target_tool == "voting":
        config.setdefault("allow_retract", True)
        if not config.get("options"):
            options = []
            for entry in ideas:
                if not isinstance(entry, dict):
                    continue
                content = str(entry.get("content", "")).strip()
                if not content:
                    continue
                
                # Append comments to content if include_comments is True
                if payload.include_comments and comments_by_parent:
                    modified_content = _append_comments_to_content(entry, comments_by_parent)
                    if modified_content != content:
                        logger.info(
                            "transfer commit appending comments: original='%s' modified='%s' idea_id=%s",
                            content[:50],
                            modified_content[:100],
                            entry.get("id")
                        )
                    content = modified_content
                
                options.append(content)
            
            if options:
                config["options"] = options
                logger.info(
                    "transfer commit created voting options: count=%d include_comments=%s has_comments=%s",
                    len(options),
                    payload.include_comments,
                    bool(comments_by_parent)
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
                if payload.include_comments and comments_by_parent:
                    content = _append_comments_to_content(entry, comments_by_parent)
                mapped_items.append(content)
            if mapped_items:
                config["items"] = mapped_items
                logger.info(
                    "transfer commit created categorization items: count=%d include_comments=%s has_comments=%s",
                    len(mapped_items),
                    payload.include_comments,
                    bool(comments_by_parent),
                )
        config.setdefault("mode", "FACILITATOR_LIVE")
    agenda_payload = AgendaActivityCreate(
        tool_type=target_tool or target.tool_type,
        title=title,
        instructions=target.instructions,
        config=config,
        order_index=(donor.order_index or 0) + 1,
    )

    created = meeting_manager.add_agenda_activity(meeting_id, agenda_payload)

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
    if target_tool == "brainstorming":
        db.query(Idea).filter(
            Idea.meeting_id == meeting_id,
            Idea.activity_id == created.activity_id,
        ).delete(synchronize_session=False)
        db.flush()
        if not ideas:
            logger.warning(
                "transfer commit has no ideas to seed meeting=%s activity=%s payload_items=%d",
                meeting_id,
                created.activity_id,
                len(normalized),
            )
        else:
            idea_map: Dict[str, int] = {}
            for idea_entry in ideas:
                idea = Idea(
                    meeting_id=meeting_id,
                    activity_id=created.activity_id,
                    content=idea_entry.get("content"),
                    submitted_name=idea_entry.get("submitted_name"),
                    parent_id=None,
                    idea_metadata=idea_entry.get("metadata") or {},
                )
                timestamp = _parse_iso_timestamp(
                    idea_entry.get("timestamp") or idea_entry.get("created_at")
                )
                if timestamp:
                    idea.timestamp = timestamp
                db.add(idea)
                db.flush()
                if idea_entry.get("id") is not None:
                    idea_map[str(idea_entry.get("id"))] = idea.id

            for parent_key, comment_entries in comments_by_parent.items():
                parent_id = idea_map.get(str(parent_key))
                if not parent_id:
                    continue
                for comment_entry in comment_entries:
                    comment = Idea(
                        meeting_id=meeting_id,
                        activity_id=created.activity_id,
                        content=comment_entry.get("content"),
                        submitted_name=comment_entry.get("submitted_name"),
                        parent_id=parent_id,
                        idea_metadata=comment_entry.get("metadata") or {},
                    )
                    timestamp = _parse_iso_timestamp(
                        comment_entry.get("timestamp") or comment_entry.get("created_at")
                    )
                    if timestamp:
                        comment.timestamp = timestamp
                    db.add(comment)
            db.commit()
            seeded_count = (
                db.query(Idea)
                .filter(
                    Idea.meeting_id == meeting_id,
                    Idea.activity_id == created.activity_id,
                )
                .count()
            )
            logger.info(
                "transfer commit seeded brainstorming ideas meeting=%s activity=%s ideas=%d comments=%d total=%d",
                meeting_id,
                created.activity_id,
                len(ideas),
                sum(len(entries) for entries in comments_by_parent.values()),
                seeded_count,
            )

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
    return {
        "new_activity": AgendaActivityResponse.model_validate(created).model_dump(),
        "agenda": [
            AgendaActivityResponse.model_validate(item).model_dump()
            for item in agenda_items
        ],
        "input_bundle_id": input_bundle.bundle_id,
    }
