from __future__ import annotations

from typing import Optional
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_active_user
from app.database import get_db
from app.models.categorization import CategorizationBallot
from app.models.meeting import AgendaActivity, Meeting, MeetingFacilitator
from app.models.user import User, UserRole
from app.schemas.categorization import (
    CategorizationAssignmentRequest,
    CategorizationBallotAssignmentRequest,
    CategorizationBallotStateResponse,
    CategorizationBallotSubmitRequest,
    CategorizationDisputedItemsResponse,
    CategorizationFinalAssignmentRequest,
    CategorizationLockRequest,
    CategorizationBucketCreateRequest,
    CategorizationBucketDeleteRequest,
    CategorizationBucketReorderRequest,
    CategorizationBucketUpdateRequest,
    CategorizationRevealRequest,
    CategorizationStateResponse,
)
from app.services import meeting_state_manager
from app.services.categorization_manager import CategorizationManager, UNSORTED_CATEGORY_ID
from app.utils.websocket_manager import websocket_manager


router = APIRouter(prefix="/api/meetings/{meeting_id}/categorization", tags=["categorization"])


def _load_meeting(db: Session, meeting_id: str) -> Meeting:
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
            joinedload(Meeting.participants),
            joinedload(Meeting.agenda_activities),
        )
        .filter(Meeting.meeting_id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


def _resolve_activity(meeting: Meeting, activity_id: str) -> AgendaActivity:
    for activity in getattr(meeting, "agenda_activities", []) or []:
        if activity.activity_id == activity_id:
            if str(activity.tool_type or "").lower() != "categorization":
                raise HTTPException(status_code=400, detail="Requested activity is not categorization.")
            return activity
    raise HTTPException(status_code=404, detail="Agenda activity not found")


def _access(meeting: Meeting, user: User) -> tuple[bool, bool]:
    facilitator_ids = {
        link.user_id
        for link in getattr(meeting, "facilitator_links", []) or []
        if getattr(link, "user_id", None)
    }
    if getattr(meeting, "owner_id", None):
        facilitator_ids.add(meeting.owner_id)
    participant_ids = {
        person.user_id for person in getattr(meeting, "participants", []) or []
    }

    role = getattr(user, "role", UserRole.PARTICIPANT.value)
    is_admin = role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}
    is_facilitator = is_admin or user.user_id in facilitator_ids
    is_participant = is_facilitator or is_admin or user.user_id in participant_ids
    if not is_participant:
        raise HTTPException(status_code=403, detail="You do not have access to this meeting.")
    return is_participant, is_facilitator


async def _resolve_participant_scope(
    meeting_id: str,
    activity_id: str,
    activity: AgendaActivity,
) -> tuple[Optional[set[str]], bool]:
    allowed: Optional[set[str]] = None
    is_active = False
    snapshot = await meeting_state_manager.snapshot(meeting_id)
    if snapshot:
        active_entries = snapshot.get("activeActivities") or []
        if isinstance(active_entries, dict):
            active_entries = active_entries.values()
        for entry in active_entries:
            if not isinstance(entry, dict):
                continue
            entry_tool = str(entry.get("tool") or "").lower()
            entry_id = entry.get("activityId") or entry.get("activity_id")
            if entry_tool == "categorization" and entry_id == activity_id:
                status_value = str(entry.get("status") or "").lower()
                if status_value in {"in_progress", "paused"}:
                    is_active = True
                metadata = entry.get("metadata") or {}
                scope = str(
                    metadata.get("participantScope")
                    or metadata.get("participant_scope")
                    or ""
                ).lower()
                meta_ids = metadata.get("participantIds") or metadata.get("participant_ids")
                if scope == "custom" and isinstance(meta_ids, list):
                    normalized = {str(pid).strip() for pid in meta_ids if str(pid).strip()}
                    if normalized:
                        allowed = normalized
                break

        if allowed is None:
            current_tool = str(snapshot.get("currentTool") or "").lower()
            current_activity = snapshot.get("currentActivity") or snapshot.get("agendaItemId")
            if current_tool == "categorization" and current_activity == activity_id:
                status_value = str(snapshot.get("status") or "").lower()
                if status_value in {"in_progress", "paused"}:
                    is_active = True
                metadata = snapshot.get("metadata") or {}
                scope = str(
                    metadata.get("participantScope")
                    or metadata.get("participant_scope")
                    or ""
                ).lower()
                meta_ids = metadata.get("participantIds") or metadata.get("participant_ids")
                if scope == "custom" and isinstance(meta_ids, list):
                    normalized = {str(pid).strip() for pid in meta_ids if str(pid).strip()}
                    if normalized:
                        allowed = normalized

    if allowed is None and activity:
        config = dict(getattr(activity, "config", {}) or {})
        raw_ids = config.get("participant_ids")
        if isinstance(raw_ids, list) and raw_ids:
            allowed = {str(pid).strip() for pid in raw_ids if str(pid).strip()}
    return allowed, is_active


async def _broadcast_refresh(meeting_id: str, activity_id: str, initiator_id: str) -> None:
    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "categorization_update",
            "payload": {"activity_id": activity_id},
            "meta": {"initiatorId": initiator_id},
        },
    )


def _activity_mode(activity: AgendaActivity) -> str:
    config = dict(getattr(activity, "config", {}) or {})
    return str(config.get("mode") or "FACILITATOR_LIVE").upper()


def _is_parallel_mode(activity: AgendaActivity) -> bool:
    return _activity_mode(activity) == "PARALLEL_BALLOT"


def _is_results_revealed(activity: AgendaActivity) -> bool:
    config = dict(getattr(activity, "config", {}) or {})
    return bool(config.get("results_revealed", False))


def _is_private_until_reveal(activity: AgendaActivity) -> bool:
    config = dict(getattr(activity, "config", {}) or {})
    return bool(config.get("private_until_reveal", True))


def _set_results_revealed(db: Session, activity: AgendaActivity, revealed: bool) -> None:
    config = dict(getattr(activity, "config", {}) or {})
    config["results_revealed"] = bool(revealed)
    activity.config = config
    db.add(activity)
    db.commit()
    db.refresh(activity)


def _is_locked(activity: AgendaActivity) -> bool:
    config = dict(getattr(activity, "config", {}) or {})
    return bool(config.get("locked", False))


def _set_locked(
    db: Session,
    *,
    activity: AgendaActivity,
    locked: bool,
    finalization_metadata: Optional[dict] = None,
) -> None:
    config = dict(getattr(activity, "config", {}) or {})
    config["locked"] = bool(locked)
    if locked:
        if finalization_metadata:
            config["finalization_metadata"] = finalization_metadata
    else:
        config.pop("finalization_metadata", None)
    activity.config = config
    db.add(activity)
    db.commit()
    db.refresh(activity)


def _config_float(config: dict, *keys: str, fallback: float) -> float:
    for key in keys:
        if key not in config:
            continue
        try:
            return float(config[key])
        except (TypeError, ValueError):
            continue
    return float(fallback)


def _config_int(config: dict, *keys: str, fallback: int) -> int:
    for key in keys:
        if key not in config:
            continue
        try:
            return int(config[key])
        except (TypeError, ValueError):
            continue
    return int(fallback)


@router.get("/state", response_model=CategorizationStateResponse)
async def get_state(
    meeting_id: str,
    activity_id: str = Query(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    activity = _resolve_activity(meeting, activity_id)
    allowed_participant_ids, is_active = await _resolve_participant_scope(
        meeting_id, activity_id, activity
    )
    if (
        allowed_participant_ids
        and not is_facilitator
        and current_user.user_id not in allowed_participant_ids
    ):
        raise HTTPException(status_code=403, detail="You are not assigned to this activity.")
    if not is_facilitator and not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )
    manager = CategorizationManager(db)
    state = manager.build_state(meeting_id, activity_id)
    config = dict(getattr(activity, "config", {}) or {})
    can_view_aggregates = is_facilitator or not (
        _is_parallel_mode(activity)
        and _is_private_until_reveal(activity)
        and not _is_results_revealed(activity)
    )
    final_assignments = manager.list_final_assignments(meeting_id, activity_id)
    state["final_assignments"] = final_assignments
    if final_assignments:
        assignments = dict(state.get("assignments") or {})
        assignments.update(final_assignments)
        state["assignments"] = assignments
    if _is_parallel_mode(activity) and can_view_aggregates:
        threshold = _config_float(config, "agreement_threshold", "agree_threshold", fallback=0.6)
        minimum_ballots = _config_int(config, "minimum_ballots", "min_ballots", fallback=1)
        state["agreement_metrics"] = manager.compute_agreement_metrics(
            meeting_id=meeting_id,
            activity_id=activity_id,
            agreement_threshold=threshold,
            minimum_ballots=minimum_ballots,
        )
    if (
        _is_parallel_mode(activity)
        and not is_facilitator
        and _is_private_until_reveal(activity)
        and not _is_results_revealed(activity)
    ):
        state["assignments"] = {}
        state["agreement_metrics"] = {}
        state["final_assignments"] = {}
    return CategorizationStateResponse(**state)


@router.get("/ballot", response_model=CategorizationBallotStateResponse)
async def get_ballot_state(
    meeting_id: str,
    activity_id: str = Query(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    activity = _resolve_activity(meeting, activity_id)
    if not _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Ballot endpoints are only available in PARALLEL_BALLOT mode.",
        )
    allowed_participant_ids, is_active = await _resolve_participant_scope(
        meeting_id, activity_id, activity
    )
    if (
        allowed_participant_ids
        and not is_facilitator
        and current_user.user_id not in allowed_participant_ids
    ):
        raise HTTPException(status_code=403, detail="You are not assigned to this activity.")
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )

    manager = CategorizationManager(db)
    state = manager.build_state(meeting_id, activity_id)
    ballots = (
        db.query(CategorizationBallot)
        .filter(
            CategorizationBallot.meeting_id == meeting_id,
            CategorizationBallot.activity_id == activity_id,
            CategorizationBallot.user_id == current_user.user_id,
        )
        .all()
    )
    assignments = {
        ballot.item_key: ballot.category_id for ballot in ballots if ballot.category_id is not None
    }
    submitted = any(bool(ballot.submitted) for ballot in ballots)
    return CategorizationBallotStateResponse(
        meeting_id=meeting_id,
        activity_id=activity_id,
        submitted=submitted,
        assignments=assignments,
        buckets=state["buckets"],
        items=state["items"],
    )


@router.post("/ballot/assignments")
async def set_ballot_assignment(
    meeting_id: str,
    payload: CategorizationBallotAssignmentRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    activity = _resolve_activity(meeting, payload.activity_id)
    if not _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Ballot endpoints are only available in PARALLEL_BALLOT mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    allowed_participant_ids, is_active = await _resolve_participant_scope(
        meeting_id, payload.activity_id, activity
    )
    if (
        allowed_participant_ids
        and not is_facilitator
        and current_user.user_id not in allowed_participant_ids
    ):
        raise HTTPException(status_code=403, detail="You are not assigned to this activity.")
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )

    category_id = str(payload.category_id or UNSORTED_CATEGORY_ID).strip() or UNSORTED_CATEGORY_ID
    manager = CategorizationManager(db)
    state = manager.build_state(meeting_id, payload.activity_id)
    valid_item_ids = {str(item.get("item_key")) for item in state["items"]}
    if payload.item_key not in valid_item_ids:
        raise HTTPException(status_code=404, detail="Item not found.")
    valid_bucket_ids = {str(bucket.get("category_id")) for bucket in state["buckets"]}
    if category_id not in valid_bucket_ids:
        raise HTTPException(status_code=404, detail="Bucket not found.")

    ballot = manager.upsert_ballot(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        user_id=current_user.user_id,
        item_key=payload.item_key,
        category_id=category_id,
        submitted=False,
    )
    manager.log_event(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        actor_user_id=current_user.user_id,
        event_type="ballot_assignment_set",
        payload={"item_key": payload.item_key, "category_id": category_id},
        commit=True,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {"item_key": ballot.item_key, "category_id": ballot.category_id, "submitted": ballot.submitted}


@router.post("/ballot/submit")
async def submit_ballot(
    meeting_id: str,
    payload: CategorizationBallotSubmitRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    activity = _resolve_activity(meeting, payload.activity_id)
    if not _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Ballot endpoints are only available in PARALLEL_BALLOT mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    allowed_participant_ids, is_active = await _resolve_participant_scope(
        meeting_id, payload.activity_id, activity
    )
    if (
        allowed_participant_ids
        and not is_facilitator
        and current_user.user_id not in allowed_participant_ids
    ):
        raise HTTPException(status_code=403, detail="You are not assigned to this activity.")
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )

    manager = CategorizationManager(db)
    state = manager.build_state(meeting_id, payload.activity_id)
    config = dict(getattr(activity, "config", {}) or {})
    allow_unsorted_submission = bool(config.get("allow_unsorted_submission", True))

    existing_ballots = (
        db.query(CategorizationBallot)
        .filter(
            CategorizationBallot.meeting_id == meeting_id,
            CategorizationBallot.activity_id == payload.activity_id,
            CategorizationBallot.user_id == current_user.user_id,
        )
        .all()
    )
    ballot_by_item = {ballot.item_key: ballot for ballot in existing_ballots}
    missing_required = []
    for item in state["items"]:
        item_key = str(item.get("item_key") or "")
        if not item_key:
            continue
        existing = ballot_by_item.get(item_key)
        category_id = existing.category_id if existing else UNSORTED_CATEGORY_ID
        if not allow_unsorted_submission and category_id in {None, UNSORTED_CATEGORY_ID}:
            missing_required.append(item_key)
            continue
        manager.upsert_ballot(
            meeting_id=meeting_id,
            activity_id=payload.activity_id,
            user_id=current_user.user_id,
            item_key=item_key,
            category_id=category_id,
            submitted=True,
        )
    if missing_required:
        raise HTTPException(
            status_code=400,
            detail="All items must be assigned before submitting.",
        )

    manager.log_event(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        actor_user_id=current_user.user_id,
        event_type="ballot_submitted",
        payload={"user_id": current_user.user_id},
        commit=True,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {"submitted": True}


@router.post("/ballot/unsubmit")
async def unsubmit_ballot(
    meeting_id: str,
    payload: CategorizationBallotSubmitRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    activity = _resolve_activity(meeting, payload.activity_id)
    if not _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Ballot endpoints are only available in PARALLEL_BALLOT mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    allowed_participant_ids, is_active = await _resolve_participant_scope(
        meeting_id, payload.activity_id, activity
    )
    if (
        allowed_participant_ids
        and not is_facilitator
        and current_user.user_id not in allowed_participant_ids
    ):
        raise HTTPException(status_code=403, detail="You are not assigned to this activity.")
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )

    db.query(CategorizationBallot).filter(
        CategorizationBallot.meeting_id == meeting_id,
        CategorizationBallot.activity_id == payload.activity_id,
        CategorizationBallot.user_id == current_user.user_id,
    ).update(
        {CategorizationBallot.submitted: False},
        synchronize_session=False,
    )
    db.commit()
    CategorizationManager(db).log_event(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        actor_user_id=current_user.user_id,
        event_type="ballot_unsubmitted",
        payload={"user_id": current_user.user_id},
        commit=True,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {"submitted": False}


@router.post("/reveal")
async def set_reveal_state(
    meeting_id: str,
    payload: CategorizationRevealRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage reveal state.")
    activity = _resolve_activity(meeting, payload.activity_id)
    if not _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Reveal controls are only available in PARALLEL_BALLOT mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    _set_results_revealed(db, activity, payload.revealed)
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {"results_revealed": _is_results_revealed(activity)}


@router.post("/lock")
async def set_lock_state(
    meeting_id: str,
    payload: CategorizationLockRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can lock this activity.")
    activity = _resolve_activity(meeting, payload.activity_id)

    manager = CategorizationManager(db)
    config = dict(getattr(activity, "config", {}) or {})
    finalization_metadata = None
    if payload.locked:
        submitted_user_count = (
            db.query(CategorizationBallot.user_id)
            .filter(
                CategorizationBallot.meeting_id == meeting_id,
                CategorizationBallot.activity_id == payload.activity_id,
                CategorizationBallot.submitted.is_(True),
            )
            .distinct()
            .count()
        )
        threshold = _config_float(config, "agreement_threshold", "agree_threshold", fallback=0.6)
        minimum_ballots = _config_int(config, "minimum_ballots", "min_ballots", fallback=1)
        metrics = {}
        if _is_parallel_mode(activity):
            metrics = manager.compute_agreement_metrics(
                meeting_id=meeting_id,
                activity_id=payload.activity_id,
                agreement_threshold=threshold,
                minimum_ballots=minimum_ballots,
            )
        finalization_metadata = {
            "mode": _activity_mode(activity),
            "agreement_threshold": threshold,
            "minimum_ballots": minimum_ballots,
            "timestamp": datetime.now(UTC).isoformat(),
            "facilitator_id": current_user.user_id,
            "ballot_count": submitted_user_count,
            "disputed_count": sum(
                1 for metric in metrics.values() if metric.get("status_label") == "DISPUTED"
            ),
        }

    _set_locked(
        db,
        activity=activity,
        locked=payload.locked,
        finalization_metadata=finalization_metadata,
    )
    manager.log_event(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        actor_user_id=current_user.user_id,
        event_type="activity_lock_toggled",
        payload={"locked": bool(payload.locked)},
        commit=True,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {"locked": _is_locked(activity), "finalization_metadata": finalization_metadata}


@router.get("/disputed", response_model=CategorizationDisputedItemsResponse)
async def list_disputed_items(
    meeting_id: str,
    activity_id: str = Query(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can view disputed items.")
    activity = _resolve_activity(meeting, activity_id)
    if not _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Disputed-item workflow is only available in PARALLEL_BALLOT mode.",
        )

    manager = CategorizationManager(db)
    state = manager.build_state(meeting_id, activity_id)
    config = dict(getattr(activity, "config", {}) or {})
    threshold = _config_float(config, "agreement_threshold", "agree_threshold", fallback=0.6)
    minimum_ballots = _config_int(config, "minimum_ballots", "min_ballots", fallback=1)
    metrics = manager.compute_agreement_metrics(
        meeting_id=meeting_id,
        activity_id=activity_id,
        agreement_threshold=threshold,
        minimum_ballots=minimum_ballots,
    )
    final_assignments = manager.list_final_assignments(meeting_id, activity_id)
    item_by_key = {str(item.get("item_key")): item for item in state.get("items", [])}
    disputed = []
    for item_key, metric in metrics.items():
        if str(metric.get("status_label")) != "DISPUTED":
            continue
        disputed.append(
            {
                "item_key": item_key,
                "item": item_by_key.get(item_key, {}),
                "metric": metric,
                "final_category_id": final_assignments.get(item_key),
            }
        )
    disputed.sort(
        key=lambda row: (
            float((row.get("metric") or {}).get("margin", 0.0)),
            -float((row.get("metric") or {}).get("valid_votes", 0)),
            str(row.get("item_key") or ""),
        )
    )
    return CategorizationDisputedItemsResponse(
        meeting_id=meeting_id,
        activity_id=activity_id,
        disputed_items=disputed,
    )


@router.post("/final-assignments")
async def set_final_assignment(
    meeting_id: str,
    payload: CategorizationFinalAssignmentRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can set final assignments.")
    activity = _resolve_activity(meeting, payload.activity_id)
    if not _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Final assignment workflow is only available in PARALLEL_BALLOT mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")

    manager = CategorizationManager(db)
    state = manager.build_state(meeting_id, payload.activity_id)
    valid_item_ids = {str(item.get("item_key")) for item in state["items"]}
    if payload.item_key not in valid_item_ids:
        raise HTTPException(status_code=404, detail="Item not found.")
    valid_bucket_ids = {str(bucket.get("category_id")) for bucket in state["buckets"]}
    if payload.category_id not in valid_bucket_ids:
        raise HTTPException(status_code=404, detail="Bucket not found.")

    final = manager.set_final_assignment(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        item_key=payload.item_key,
        category_id=payload.category_id,
        resolver_user_id=current_user.user_id,
    )
    manager.upsert_assignment(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        item_key=payload.item_key,
        category_id=payload.category_id,
        actor_user_id=current_user.user_id,
    )
    manager.log_event(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        actor_user_id=current_user.user_id,
        event_type="final_assignment_set",
        payload={"item_key": payload.item_key, "category_id": payload.category_id},
        commit=True,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {"item_key": final.item_key, "category_id": final.category_id}


@router.post("/buckets")
async def create_bucket(
    meeting_id: str,
    payload: CategorizationBucketCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage buckets.")
    activity = _resolve_activity(meeting, payload.activity_id)
    if _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Bucket management via this endpoint is only available in FACILITATOR_LIVE mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    _, is_active = await _resolve_participant_scope(meeting_id, payload.activity_id, activity)
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )
    manager = CategorizationManager(db)
    bucket = manager.create_bucket(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        title=payload.title,
        category_id=payload.category_id,
        description=payload.description,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {
        "category_id": bucket.category_id,
        "title": bucket.title,
        "description": bucket.description,
        "order_index": bucket.order_index,
        "status": bucket.status,
    }


@router.patch("/buckets/{category_id}")
async def update_bucket(
    meeting_id: str,
    category_id: str,
    payload: CategorizationBucketUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage buckets.")
    activity = _resolve_activity(meeting, payload.activity_id)
    if _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Bucket management via this endpoint is only available in FACILITATOR_LIVE mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    _, is_active = await _resolve_participant_scope(meeting_id, payload.activity_id, activity)
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )
    bucket = CategorizationManager(db).update_bucket(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        category_id=category_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {
        "category_id": bucket.category_id,
        "title": bucket.title,
        "description": bucket.description,
        "order_index": bucket.order_index,
        "status": bucket.status,
    }


@router.delete("/buckets/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bucket(
    meeting_id: str,
    category_id: str,
    payload: CategorizationBucketDeleteRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage buckets.")
    activity = _resolve_activity(meeting, payload.activity_id)
    if _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Bucket management via this endpoint is only available in FACILITATOR_LIVE mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    _, is_active = await _resolve_participant_scope(meeting_id, payload.activity_id, activity)
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )
    CategorizationManager(db).delete_bucket(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        category_id=category_id,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return None


@router.post("/buckets/reorder")
async def reorder_buckets(
    meeting_id: str,
    payload: CategorizationBucketReorderRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can manage buckets.")
    activity = _resolve_activity(meeting, payload.activity_id)
    if _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Bucket management via this endpoint is only available in FACILITATOR_LIVE mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    _, is_active = await _resolve_participant_scope(meeting_id, payload.activity_id, activity)
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )
    buckets = CategorizationManager(db).reorder_buckets(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        ordered_category_ids=payload.category_ids,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {
        "buckets": [
            {
                "category_id": bucket.category_id,
                "title": bucket.title,
                "order_index": bucket.order_index,
                "status": bucket.status,
            }
            for bucket in buckets
        ]
    }


@router.post("/assignments")
async def set_assignment(
    meeting_id: str,
    payload: CategorizationAssignmentRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    meeting = _load_meeting(db, meeting_id)
    _, is_facilitator = _access(meeting, current_user)
    if not is_facilitator:
        raise HTTPException(status_code=403, detail="Only facilitators can move items in facilitator-live mode.")
    activity = _resolve_activity(meeting, payload.activity_id)
    if _is_parallel_mode(activity):
        raise HTTPException(
            status_code=409,
            detail="Facilitator assignment moves via this endpoint are only available in FACILITATOR_LIVE mode.",
        )
    if _is_locked(activity):
        raise HTTPException(status_code=409, detail="This activity is locked.")
    _, is_active = await _resolve_participant_scope(meeting_id, payload.activity_id, activity)
    if not is_active:
        raise HTTPException(
            status_code=403, detail="This activity is not open for categorization."
        )
    assignment = CategorizationManager(db).upsert_assignment(
        meeting_id=meeting_id,
        activity_id=payload.activity_id,
        item_key=payload.item_key,
        category_id=payload.category_id,
        actor_user_id=current_user.user_id,
    )
    await _broadcast_refresh(meeting_id, payload.activity_id, current_user.user_id)
    return {
        "item_key": assignment.item_key,
        "category_id": assignment.category_id,
        "is_unsorted": assignment.is_unsorted,
    }
