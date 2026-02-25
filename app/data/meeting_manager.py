from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from typing import Dict, Optional, List, Any, Sequence, Iterable, Set, Tuple
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException, Depends

from ..models.meeting import Meeting, MeetingFacilitator, AgendaActivity
from ..models.idea import Idea
from ..models.voting import VotingVote
from ..models.activity_bundle import ActivityBundle
from ..models.user import User, UserRole
from ..models.categorization import (
    CategorizationAssignment,
    CategorizationAuditEvent,
    CategorizationBallot,
    CategorizationFinalAssignment,
)
from ..schemas.meeting import MeetingCreate, AgendaActivityCreate, AgendaActivityUpdate
from ..database import get_db
from ..utils.identifiers import (
    generate_meeting_id,
    generate_facilitator_id,
    generate_activity_id,
    generate_tool_config_id,
    derive_activity_prefix,
)
from ..services.activity_catalog import get_activity_definition, get_activity_catalog
from ..config.loader import get_activity_participant_exclusivity
from ..services import meeting_state_manager

ACTIVITY_SEQUENCE_WIDTH = 4


class MeetingManager:
    """Manages meeting data using SQLAlchemy."""

    def __init__(self, db: Session, logger=None):
        self.db = db
        self.logger = logger or print

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @classmethod
    def _archive_root(cls) -> Path:
        return cls._project_root() / "data" / "meetings_archive"

    @staticmethod
    def _slugify_for_path(value: Optional[str], fallback: str = "owner") -> str:
        text = (value or "").strip().lower()
        if not text:
            return fallback
        slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return slug or fallback

    def _find_latest_archive_file(self, meeting: Meeting) -> Optional[str]:
        owner_login = getattr(getattr(meeting, "owner", None), "login", None) or meeting.owner_id
        owner_slug = self._slugify_for_path(owner_login, "owner")
        owner_dir = self._archive_root() / owner_slug
        if not owner_dir.exists():
            return None

        pattern = f"*__{meeting.meeting_id}.zip"
        matches = sorted(
            owner_dir.glob(pattern),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not matches:
            return None

        latest = matches[0]
        try:
            return str(latest.relative_to(self._project_root()))
        except ValueError:
            return str(latest)

    # ------------------------------------------------------------------ #
    # Agenda activity helpers
    # ------------------------------------------------------------------ #

    def _next_activity_identifier(
        self,
        meeting_id: str,
        tool_type: str,
        sequence_cache: Dict[str, int],
    ) -> str:
        prefix = derive_activity_prefix(tool_type)
        if prefix not in sequence_cache:
            generated = generate_activity_id(self.db, meeting_id, tool_type)
            try:
                suffix_value = int(generated.split("-")[-1])
            except (ValueError, IndexError):
                suffix_value = 1
                generated = f"{prefix}-{suffix_value:0{ACTIVITY_SEQUENCE_WIDTH}d}"
            sequence_cache[prefix] = suffix_value + 1
            return generated

        current = sequence_cache[prefix]
        sequence_cache[prefix] = current + 1
        return f"{meeting_id}-{prefix}-{current:0{ACTIVITY_SEQUENCE_WIDTH}d}"

    def _append_activity(
        self,
        meeting: Meeting,
        payload: AgendaActivityCreate,
        order_index: int,
        sequence_cache: Dict[str, int],
    ) -> AgendaActivity:
        definition = get_activity_definition(payload.tool_type)
        if not definition:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool type '{payload.tool_type}'",
            )

        activity_id = self._next_activity_identifier(
            meeting.meeting_id,
            payload.tool_type,
            sequence_cache,
        )
        tool_config_id = generate_tool_config_id(activity_id, meeting.meeting_id)
        config = dict(definition.get("default_config", {}))
        config.update(payload.config or {})
        self._validate_activity_config_placeholders(payload.tool_type, config)
        if payload.tool_type == "voting":
            self._enforce_voting_limits(config)

        activity = AgendaActivity(
            activity_id=activity_id,
            meeting_id=meeting.meeting_id,
            tool_type=payload.tool_type,
            title=payload.title,
            instructions=payload.instructions,
            order_index=order_index,
            tool_config_id=tool_config_id,
            config=config,
        )
        meeting.agenda_activities.append(activity)
        self.db.flush()
        return activity

    @staticmethod
    def _coerce_positive_int(value: Any) -> Optional[int]:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _enforce_voting_limits(self, config: Dict[str, Any]) -> None:
        max_votes = self._coerce_positive_int(config.get("max_votes"))
        max_votes_per_option = self._coerce_positive_int(
            config.get("max_votes_per_option")
        )
        if max_votes is None or max_votes_per_option is None:
            return
        if max_votes_per_option > max_votes:
            config["max_votes_per_option"] = max_votes

    @staticmethod
    def _contains_object_placeholder(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() == "[object object]"
        if isinstance(value, list):
            return any(
                isinstance(item, str)
                and item.strip().lower() == "[object object]"
                for item in value
            )
        return False

    def _validate_activity_config_placeholders(
        self,
        tool_type: str,
        config: Dict[str, Any],
    ) -> None:
        normalized_tool = (tool_type or "").lower()
        watched_keys: List[str] = []
        if normalized_tool == "voting":
            watched_keys = ["options"]
        elif normalized_tool == "rank_order_voting":
            watched_keys = ["ideas"]
        elif normalized_tool == "categorization":
            watched_keys = ["items", "buckets"]
        if not watched_keys:
            return

        bad_keys = [
            key
            for key in watched_keys
            if key in config and self._contains_object_placeholder(config.get(key))
        ]
        if bad_keys:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Invalid configuration payload: one or more list values resolved "
                    f"to '[object Object]' for {', '.join(sorted(bad_keys))}. "
                    "Use plain text lines or structured objects with content/label fields."
                ),
            )

    @staticmethod
    def _changed_config_keys(
        existing_config: Dict[str, Any],
        patch: Dict[str, Any],
        watched_keys: Set[str],
    ) -> Set[str]:
        return {
            key
            for key in watched_keys
            if key in patch and patch.get(key) != existing_config.get(key)
        }

    def _activity_has_live_data(self, meeting_id: str, activity_id: str) -> bool:
        return bool(self.get_activity_data_flags(meeting_id).get(activity_id))

    def _voting_has_votes(self, meeting_id: str, activity_id: str) -> bool:
        return (
            self.db.query(VotingVote.vote_id)
            .filter(
                VotingVote.meeting_id == meeting_id,
                VotingVote.activity_id == activity_id,
            )
            .first()
            is not None
        )

    def _categorization_has_submitted_ballots(
        self, meeting_id: str, activity_id: str
    ) -> bool:
        return (
            self.db.query(CategorizationBallot.ballot_id)
            .filter(
                CategorizationBallot.meeting_id == meeting_id,
                CategorizationBallot.activity_id == activity_id,
                CategorizationBallot.submitted.is_(True),
            )
            .first()
            is not None
        )

    @staticmethod
    def is_categorization_seed_config_locked(activity: AgendaActivity) -> bool:
        """Seed config becomes immutable once an activity has started at least once."""
        if (activity.tool_type or "").lower() != "categorization":
            return False
        if getattr(activity, "started_at", None) is not None:
            return True
        if getattr(activity, "stopped_at", None) is not None:
            return True
        elapsed = getattr(activity, "elapsed_duration", 0) or 0
        return int(elapsed) > 0

    def _resequence_agenda(
        self,
        meeting: Meeting,
        ordered: Optional[List[AgendaActivity]] = None,
    ) -> None:
        if ordered is None:
            ordered = sorted(
                meeting.agenda_activities,
                key=lambda item: (item.order_index, item.activity_id),
            )
        else:
            ordered = list(ordered)

        # To satisfy the unique constraint during updates, assign placeholder values first.
        max_existing = max(
            (item.order_index or 0 for item in meeting.agenda_activities),
            default=0,
        )
        placeholder_base = max_existing + 1000
        for idx, activity in enumerate(ordered, start=1):
            activity.order_index = placeholder_base + idx
        meeting.agenda_activities[:] = ordered
        self.db.flush()

        for idx, activity in enumerate(ordered, start=1):
            activity.order_index = idx
        self.db.flush()

    def _apply_agenda_items(
        self,
        meeting: Meeting,
        items: Sequence[AgendaActivityCreate],
    ) -> List[AgendaActivity]:
        meeting.agenda_activities.clear()
        self.db.flush()

        if not items:
            return []

        sequence_cache: Dict[str, int] = {}
        ordered = sorted(
            enumerate(items, start=1),
            key=lambda pair: (pair[1].order_index or pair[0], pair[0]),
        )

        created: List[AgendaActivity] = []
        for position, (_, payload) in enumerate(ordered, start=1):
            created.append(
                self._append_activity(
                    meeting,
                    payload,
                    order_index=position,
                    sequence_cache=sequence_cache,
                )
            )

        # Keep categorization runtime state in sync with agenda config immediately.
        if created:
            from ..services.categorization_manager import CategorizationManager

            manager = CategorizationManager(self.db)
            for activity in created:
                if (activity.tool_type or "").lower() != "categorization":
                    continue
                manager.reset_activity_state(
                    meeting_id=meeting.meeting_id,
                    activity_id=activity.activity_id,
                    clear_bundles=True,
                )
                manager.seed_activity(
                    meeting_id=meeting.meeting_id,
                    activity=activity,
                    actor_user_id=None,
                )

        return created

    # ------------------------------------------------------------------ #
    # Agenda activity public interface
    # ------------------------------------------------------------------ #

    def get_activity_catalog_entries(self) -> List[Dict[str, Any]]:
        return get_activity_catalog()

    def list_agenda(self, meeting_id: str) -> List[AgendaActivity]:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return sorted(meeting.agenda_activities, key=lambda item: item.order_index)

    def get_activity_data_flags(self, meeting_id: str) -> Dict[str, bool]:
        idea_ids = {
            row[0]
            for row in self.db.query(Idea.activity_id)
            .filter(Idea.meeting_id == meeting_id, Idea.activity_id.isnot(None))
            .distinct()
            .all()
        }
        vote_ids = {
            row[0]
            for row in self.db.query(VotingVote.activity_id)
            .filter(VotingVote.meeting_id == meeting_id)
            .distinct()
            .all()
        }
        bundle_ids = {
            row[0]
            for row in self.db.query(ActivityBundle.activity_id)
            .filter(ActivityBundle.meeting_id == meeting_id)
            .distinct()
            .all()
        }
        categorization_ballot_ids = {
            row[0]
            for row in self.db.query(CategorizationBallot.activity_id)
            .filter(
                CategorizationBallot.meeting_id == meeting_id,
                CategorizationBallot.activity_id.isnot(None),
            )
            .distinct()
            .all()
        }
        categorization_final_ids = {
            row[0]
            for row in self.db.query(CategorizationFinalAssignment.activity_id)
            .filter(
                CategorizationFinalAssignment.meeting_id == meeting_id,
                CategorizationFinalAssignment.activity_id.isnot(None),
            )
            .distinct()
            .all()
        }
        categorization_moved_ids = {
            row[0]
            for row in self.db.query(CategorizationAssignment.activity_id)
            .filter(
                CategorizationAssignment.meeting_id == meeting_id,
                CategorizationAssignment.activity_id.isnot(None),
                CategorizationAssignment.is_unsorted.is_(False),
            )
            .distinct()
            .all()
        }
        categorization_audit_ids = {
            row[0]
            for row in self.db.query(CategorizationAuditEvent.activity_id)
            .filter(
                CategorizationAuditEvent.meeting_id == meeting_id,
                CategorizationAuditEvent.activity_id.isnot(None),
                CategorizationAuditEvent.actor_user_id.isnot(None),
                CategorizationAuditEvent.event_type.in_(
                    [
                        "bucket_created",
                        "bucket_updated",
                        "bucket_deleted",
                        "bucket_reordered",
                        "item_moved",
                        "ballot_submitted",
                        "ballot_unsubmitted",
                        "final_assignment_set",
                    ]
                ),
            )
            .distinct()
            .all()
        }
        data_ids = {
            activity_id
            for activity_id in (
                idea_ids
                | vote_ids
                | bundle_ids
                | categorization_ballot_ids
                | categorization_final_ids
                | categorization_moved_ids
                | categorization_audit_ids
            )
            if activity_id
        }
        return {activity_id: True for activity_id in data_ids}

    def get_activity_lock_flags(self, meeting_id: str) -> Dict[str, Dict[str, bool]]:
        has_live_data = self.get_activity_data_flags(meeting_id)
        vote_ids = {
            row[0]
            for row in self.db.query(VotingVote.activity_id)
            .filter(
                VotingVote.meeting_id == meeting_id,
                VotingVote.activity_id.isnot(None),
            )
            .distinct()
            .all()
            if row[0]
        }
        submitted_ballot_ids = {
            row[0]
            for row in self.db.query(CategorizationBallot.activity_id)
            .filter(
                CategorizationBallot.meeting_id == meeting_id,
                CategorizationBallot.activity_id.isnot(None),
                CategorizationBallot.submitted.is_(True),
            )
            .distinct()
            .all()
            if row[0]
        }

        flags: Dict[str, Dict[str, bool]] = {}
        for activity_id in set(has_live_data) | vote_ids | submitted_ballot_ids:
            flags[activity_id] = {
                "has_live_data": bool(has_live_data.get(activity_id)),
                "has_votes": activity_id in vote_ids,
                "has_submitted_ballots": activity_id in submitted_ballot_ids,
            }
        return flags

    def get_activity_transfer_counts(self, meeting_id: str) -> Dict[str, Dict[str, Any]]:
        idea_counts = {
            activity_id: int(count or 0)
            for activity_id, count in self.db.query(Idea.activity_id, func.count(Idea.id))
            .filter(
                Idea.meeting_id == meeting_id,
                Idea.activity_id.isnot(None),
                Idea.parent_id.is_(None),
            )
            .group_by(Idea.activity_id)
            .all()
            if activity_id
        }

        bundle_counts: Dict[str, int] = {}
        bundles = (
            self.db.query(ActivityBundle)
            .filter(
                ActivityBundle.meeting_id == meeting_id,
                ActivityBundle.kind == "output",
            )
            .order_by(ActivityBundle.created_at.desc(), ActivityBundle.id.desc())
            .all()
        )
        for bundle in bundles:
            activity_id = bundle.activity_id
            if not activity_id or activity_id in bundle_counts:
                continue
            items = bundle.items if isinstance(bundle.items, list) else []
            bundle_counts[activity_id] = len(items)

        transfer_counts: Dict[str, Dict[str, Any]] = {}
        for activity_id in set(idea_counts) | set(bundle_counts):
            idea_count = idea_counts.get(activity_id, 0)
            if idea_count > 0:
                transfer_counts[activity_id] = {
                    "count": idea_count,
                    "source": "ideas",
                }
                continue
            bundle_count = bundle_counts.get(activity_id, 0)
            transfer_counts[activity_id] = {
                "count": bundle_count,
                "source": "bundle" if bundle_count > 0 else "none",
            }
        return transfer_counts

    def add_agenda_activity(
        self,
        meeting_id: str,
        payload: AgendaActivityCreate,
    ) -> AgendaActivity:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        sequence_cache: Dict[str, int] = {}
        order_index = payload.order_index or (len(meeting.agenda_activities) + 1)
        if payload.order_index is not None:
            existing_orders = [item.order_index for item in meeting.agenda_activities]
            if existing_orders and order_index in existing_orders:
                order_index = max(existing_orders) + 1000
        activity = self._append_activity(
            meeting,
            payload,
            order_index=order_index,
            sequence_cache=sequence_cache,
        )
        ordered_sequence: Optional[List[AgendaActivity]] = None
        if payload.order_index is not None:
            ordered = sorted(
                meeting.agenda_activities,
                key=lambda item: (item.order_index, item.activity_id),
            )
            ordered = [
                item for item in ordered if item.activity_id != activity.activity_id
            ]
            insert_index = min(payload.order_index, len(ordered) + 1) - 1
            ordered.insert(insert_index, activity)
            ordered_sequence = ordered

        self._resequence_agenda(meeting, ordered_sequence)
        self.db.commit()
        self.db.refresh(activity)
        return activity

    def update_agenda_activity(
        self,
        meeting_id: str,
        activity_id: str,
        payload: AgendaActivityUpdate,
    ) -> AgendaActivity:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        activity = next(
            (
                item
                for item in meeting.agenda_activities
                if item.activity_id == activity_id
            ),
            None,
        )
        if not activity:
            raise HTTPException(status_code=404, detail="Agenda activity not found")

        if payload.tool_type and payload.tool_type != activity.tool_type:
            raise HTTPException(
                status_code=400,
                detail="Changing activity tool type is not supported; create a new activity instead.",
            )

        if payload.title is not None:
            activity.title = payload.title
        if payload.instructions is not None:
            activity.instructions = payload.instructions
        if payload.config is not None:
            tool_type = (activity.tool_type or "").lower()
            existing_config = dict(activity.config or {})
            patch_config = dict(payload.config or {})

            if tool_type == "voting":
                voting_locked_keys = {"options", "max_votes", "max_votes_per_option"}
                changed_locked_keys = self._changed_config_keys(
                    existing_config,
                    patch_config,
                    voting_locked_keys,
                )
                if changed_locked_keys and self._voting_has_votes(
                    meeting_id, activity_id
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Voting settings are locked because votes already exist for "
                            f"this activity: {', '.join(sorted(changed_locked_keys))}."
                        ),
                    )

            if tool_type == "categorization":
                categorization_live_locked_keys = {"items", "buckets"}
                changed_live_locked_keys = self._changed_config_keys(
                    existing_config,
                    patch_config,
                    categorization_live_locked_keys,
                )
                if changed_live_locked_keys and self.is_categorization_seed_config_locked(activity):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Categorization seed settings are locked because this "
                            "activity has already started. Manage ideas and buckets "
                            "inside the live activity interface: "
                            f"{', '.join(sorted(changed_live_locked_keys))}."
                        ),
                    )

                categorization_ballot_locked_keys = {
                    "mode",
                    "single_assignment_only",
                    "agreement_threshold",
                    "margin_threshold",
                    "minimum_ballots",
                    "tie_policy",
                    "missing_vote_handling",
                    "private_until_reveal",
                    "allow_unsorted_submission",
                }
                changed_ballot_locked_keys = self._changed_config_keys(
                    existing_config,
                    patch_config,
                    categorization_ballot_locked_keys,
                )
                if changed_ballot_locked_keys and self._categorization_has_submitted_ballots(
                    meeting_id, activity_id
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Parallel categorization interpretation settings are locked "
                            "because submitted ballots already exist for this activity: "
                            f"{', '.join(sorted(changed_ballot_locked_keys))}."
                        ),
                    )

            updated_config = dict(activity.config or {})
            updated_config.update(payload.config)
            self._validate_activity_config_placeholders(
                activity.tool_type, updated_config
            )
            if activity.tool_type == "voting":
                self._enforce_voting_limits(updated_config)
            activity.config = updated_config
            if activity.tool_type == "categorization":
                refreshed_seed_keys = {"items", "buckets"}
                if refreshed_seed_keys.intersection(set(payload.config.keys())):
                    from ..services.categorization_manager import CategorizationManager

                    manager = CategorizationManager(self.db)
                    manager.reset_activity_state(
                        meeting_id=meeting_id,
                        activity_id=activity_id,
                        clear_bundles=True,
                    )
                    manager.seed_activity(
                        meeting_id=meeting_id,
                        activity=activity,
                        actor_user_id=None,
                    )
        ordered_sequence: Optional[List[AgendaActivity]] = None
        if payload.order_index is not None:
            desired_position = max(1, payload.order_index)
            ordered = sorted(
                meeting.agenda_activities,
                key=lambda item: (item.order_index, item.activity_id),
            )
            ordered = [item for item in ordered if item.activity_id != activity_id]
            insert_index = min(desired_position, len(ordered) + 1) - 1
            ordered.insert(insert_index, activity)
            ordered_sequence = ordered

        self._resequence_agenda(meeting, ordered_sequence)

        self.db.flush()
        self.db.commit()
        self.db.refresh(activity)
        return activity

    async def delete_agenda_activity(self, meeting_id: str, activity_id: str) -> None:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        activity = next(
            (
                item
                for item in meeting.agenda_activities
                if item.activity_id == activity_id
            ),
            None,
        )
        if not activity:
            raise HTTPException(status_code=404, detail="Agenda activity not found")

        # Check if the activity is currently active in the meeting state
        current_meeting_state = await meeting_state_manager.snapshot(meeting_id)
        if current_meeting_state:
            active_entries = current_meeting_state.get("activeActivities") or []
            if isinstance(active_entries, dict):
                active_entries = active_entries.values()
            is_active = any(
                isinstance(entry, dict)
                and (entry.get("activityId") or entry.get("activity_id")) == activity_id
                and str(entry.get("status") or "").lower() in {"in_progress", "paused"}
                for entry in active_entries
            )
            if (
                not is_active
                and current_meeting_state.get("currentActivity") == activity_id
                and str(current_meeting_state.get("status") or "").lower()
                in {"in_progress", "paused"}
            ):
                is_active = True

            if is_active:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot delete an active activity. Please stop it first.",
                )

        meeting.agenda_activities.remove(activity)
        self.db.query(VotingVote).filter(
            VotingVote.meeting_id == meeting_id,
            VotingVote.activity_id == activity_id,
        ).delete(synchronize_session=False)
        self.db.query(ActivityBundle).filter(
            ActivityBundle.meeting_id == meeting_id,
            ActivityBundle.activity_id == activity_id,
        ).delete(synchronize_session=False)
        self.db.query(Idea).filter(
            Idea.meeting_id == meeting_id,
            Idea.activity_id == activity_id,
        ).delete(synchronize_session=False)
        self.db.flush()
        self._resequence_agenda(meeting)
        self.db.commit()

    def reorder_agenda_activities(
        self, meeting_id: str, ordered_activity_ids: List[str]
    ) -> List[AgendaActivity]:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        # Validate that all provided activity_ids exist and belong to this meeting
        existing_activities = {
            activity.activity_id: activity for activity in meeting.agenda_activities
        }
        if len(ordered_activity_ids) != len(existing_activities):
            raise HTTPException(
                status_code=400,
                detail="Provided activity_ids list size does not match existing agenda size.",
            )

        new_ordered_list: List[AgendaActivity] = []
        for activity_id in ordered_activity_ids:
            activity = existing_activities.get(activity_id)
            if not activity:
                raise HTTPException(
                    status_code=404,
                    detail=f"Activity with ID '{activity_id}' not found in meeting agenda.",
                )
            new_ordered_list.append(activity)

        self._resequence_agenda(meeting, new_ordered_list)
        self.db.commit()
        self.db.refresh(meeting)  # Refresh meeting to load resequenced agenda
        return sorted(meeting.agenda_activities, key=lambda item: item.order_index)

    async def check_participant_collisions(
        self,
        meeting_id: str,
        activity_id_to_start: str,
        new_activity_participant_ids: Set[
            str
        ],  # Participants of the activity being started
    ) -> List[str]:  # Returns a list of conflicting user_ids
        """
        Checks if starting the given activity would lead to participant collisions
        with other currently active activities in the same meeting.

        A collision occurs if a participant assigned to activity_id_to_start
        is already active in another running activity.
        """
        if not get_activity_participant_exclusivity():
            return []
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        current_meeting_state = await meeting_state_manager.snapshot(meeting_id)
        active_entries: List[Tuple[str, Set[str]]] = []
        if current_meeting_state:
            raw_active = current_meeting_state.get("activeActivities") or []
            if isinstance(raw_active, dict):
                raw_active = raw_active.values()
            for entry in raw_active:
                if not isinstance(entry, dict):
                    continue
                active_id = entry.get("activityId") or entry.get("activity_id")
                if not active_id or active_id == activity_id_to_start:
                    continue
                status = str(entry.get("status") or "").lower()
                if status in {"completed", "stopped"}:
                    continue
                participant_ids = (
                    entry.get("participantIds")
                    or entry.get("participant_ids")
                    or []
                )
                if isinstance(participant_ids, list):
                    participant_set = {
                        str(pid).strip() for pid in participant_ids if str(pid).strip()
                    }
                else:
                    participant_set = set()
                if not participant_set:
                    meeting_participants = self.list_participants(meeting_id)
                    participant_set = {p.user_id for p in meeting_participants}
                active_entries.append((str(active_id), participant_set))

        # Backward-compatible fallback: use legacy single currentActivity state
        if (
            not active_entries
            and current_meeting_state
            and current_meeting_state.get("currentActivity")
        ):
            current_active_activity_id = current_meeting_state["currentActivity"]
            if current_active_activity_id != activity_id_to_start:
                active_activity = next(
                    (
                        a
                        for a in meeting.agenda_activities
                        if a.activity_id == current_active_activity_id
                    ),
                    None,
                )
                if not active_activity:
                    self.logger(
                        f"Warning: Meeting state shows active activity {current_active_activity_id} but not found in agenda."
                    )
                else:
                    active_activity_config = active_activity.config or {}
                    raw_ids = active_activity_config.get("participant_ids")
                    participant_set: Set[str] = set()
                    if raw_ids:
                        participant_set = {str(pid).strip() for pid in raw_ids if str(pid).strip()}
                    else:
                        meeting_participants = self.list_participants(meeting_id)
                        participant_set = {p.user_id for p in meeting_participants}
                    active_entries.append(
                        (str(current_active_activity_id), participant_set)
                    )

        if not active_entries:
            return []

        conflicting: Set[str] = set()
        for _, active_ids in active_entries:
            conflicting.update(new_activity_participant_ids.intersection(active_ids))
        return sorted(conflicting)

    def replace_agenda(
        self,
        meeting_id: str,
        items: Sequence[AgendaActivityCreate],
    ) -> List[AgendaActivity]:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        created = self._apply_agenda_items(meeting, items)
        self.db.commit()
        self.db.refresh(meeting)
        return sorted(created, key=lambda item: item.order_index)

    # ------------------------------------------------------------------ #

    def create_meeting(
        self,
        meeting_data: MeetingCreate,
        facilitator_id: str,
        agenda_items: Optional[Sequence[AgendaActivityCreate]] = None,
    ) -> Meeting:
        """Create a new meeting in the database.

        Args:
            db: Database session
            meeting_data: Validated meeting data from MeetingCreate schema
            facilitator_id: ID of the user who will facilitate the meeting

        Returns:
            The created Meeting instance

        Raises:
            HTTPException: If database operations fail
        """
        try:
            if facilitator_id and facilitator_id != meeting_data.owner_id:
                self.logger(
                    f"create_meeting: facilitator_id {facilitator_id} differs from owner_id {meeting_data.owner_id}; owner_id will be used"
                )

            owner_user = (
                self.db.query(User)
                .filter(User.user_id == meeting_data.owner_id)
                .one_or_none()
            )
            if owner_user is None:
                raise HTTPException(status_code=404, detail="Owner not found")

            participant_ids = list(meeting_data.participant_ids or [])
            additional_facilitator_ids = {
                str(fid)
                for fid in (meeting_data.additional_facilitator_ids or [])
                if fid is not None
            }
            additional_facilitator_ids.discard(owner_user.user_id)

            if additional_facilitator_ids:
                co_facilitators = (
                    self.db.query(User)
                    .filter(User.user_id.in_(additional_facilitator_ids))
                    .all()
                )
                found_ids = {user.user_id for user in co_facilitators}
                missing_ids = additional_facilitator_ids.difference(found_ids)
                if missing_ids:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Facilitator(s) not found for ID(s): {sorted(missing_ids)}",
                    )
            else:
                co_facilitators = []

            created_reference = meeting_data.start_time or datetime.now(timezone.utc)
            meeting_identifier = generate_meeting_id(self.db, created_reference)

            # Map schema fields to model fields
            publicity_attr = getattr(meeting_data, "publicity", None)
            is_public_value = getattr(meeting_data, "is_public", None)
            if is_public_value is None:
                if publicity_attr is not None:
                    raw_publicity = getattr(publicity_attr, "value", publicity_attr)
                    is_public_value = str(raw_publicity).lower() == "public"
                else:
                    is_public_value = False

            db_meeting = Meeting(
                meeting_id=meeting_identifier,
                title=meeting_data.title,
                description=meeting_data.description,
                started_at=meeting_data.start_time,  # Map start_time to started_at
                end_time=meeting_data.end_time,  # Direct mapping from schema
                owner_id=owner_user.user_id,  # Primary owner identifier
                status="scheduled",  # Consistent status for new meetings
                is_public=is_public_value,  # Derived from schema
            )

            # Ensure the primary facilitator is always included in the facilitator roster
            db_meeting.owner = owner_user
            self.db.add(db_meeting)
            self.db.flush()

            def add_facilitator_assignment(
                user: User, is_owner: bool
            ) -> MeetingFacilitator:
                facilitator_identifier = generate_facilitator_id(
                    self.db, user.first_name, user.last_name
                )
                assignment = MeetingFacilitator(
                    facilitator_id=facilitator_identifier,
                    meeting_id=db_meeting.meeting_id,
                    user_id=user.user_id,
                    is_owner=is_owner,
                )
                assignment.user = user
                db_meeting.facilitator_links.append(assignment)
                self.db.flush()
                return assignment

            add_facilitator_assignment(owner_user, True)
            for co_facilitator in co_facilitators:
                if co_facilitator.user_id == owner_user.user_id:
                    continue
                add_facilitator_assignment(co_facilitator, False)

            # Add participants if provided
            if participant_ids:
                participants = (
                    self.db.query(User).filter(User.user_id.in_(participant_ids)).all()
                )
                db_meeting.participants.extend(participants)

            if agenda_items:
                self._apply_agenda_items(db_meeting, agenda_items)

            self.db.commit()
            refreshed = self.get_meeting(db_meeting.meeting_id) or db_meeting
            self.logger(
                f"Successfully created meeting: {db_meeting.title} (ID: {db_meeting.meeting_id})"
            )
            return refreshed
        except SQLAlchemyError as e:
            self.logger(f"Database error creating meeting: {e}")
            self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Could not create meeting due to a database error.",
            )

    def add_meeting(
        self,
        meeting_data: Dict[str, Any],
        facilitator_id: str,
        participant_ids: List[str] = None,
        co_facilitator_ids: Optional[List[str]] = None,
    ) -> Optional[Meeting]:
        """Add a new meeting to the database."""
        # self.db.begin() # moved to init
        try:
            owner = self.db.query(User).filter(User.user_id == facilitator_id).first()
            if not owner:
                self.logger(f"add_meeting: owner with ID {facilitator_id} not found.")
                return None

            created_reference = meeting_data.get("start_time") or datetime.now(
                timezone.utc
            )
            meeting_identifier = generate_meeting_id(self.db, created_reference)

            db_meeting = Meeting(
                meeting_id=meeting_identifier,
                title=meeting_data.get("title"),
                description=meeting_data.get("description"),
                started_at=meeting_data.get("start_time"),  # Corrected to started_at
                end_time=meeting_data.get("end_time"),
                status=meeting_data.get("status", "active"),
                is_public=meeting_data.get("is_public", False),
                owner_id=owner.user_id,
                # created_at is handled by server_default
            )

            db_meeting.owner = owner
            self.db.add(db_meeting)
            self.db.flush()

            def append_facilitator(user: User, is_owner: bool) -> None:
                facilitator_identifier = generate_facilitator_id(
                    self.db, user.first_name, user.last_name
                )
                assignment = MeetingFacilitator(
                    facilitator_id=facilitator_identifier,
                    meeting_id=db_meeting.meeting_id,
                    user_id=user.user_id,
                    is_owner=is_owner,
                )
                assignment.user = user
                db_meeting.facilitator_links.append(assignment)
                self.db.flush()

            append_facilitator(owner, True)

            co_facilitator_ids = co_facilitator_ids or []
            extra_facilitator_ids = {
                fid
                for fid in co_facilitator_ids
                if fid is not None and fid != facilitator_id
            }
            if extra_facilitator_ids:
                co_facilitators = (
                    self.db.query(User)
                    .filter(User.user_id.in_(extra_facilitator_ids))
                    .all()
                )
                found_ids = {user.user_id for user in co_facilitators}
                missing_ids = extra_facilitator_ids.difference(found_ids)
                if missing_ids:
                    self.logger(
                        f"add_meeting: Some co-facilitator IDs not found: {sorted(missing_ids)}"
                    )
                for co_facilitator in co_facilitators:
                    if co_facilitator.user_id == owner.user_id:
                        continue
                    append_facilitator(co_facilitator, False)

            # Handle participants if IDs are provided
            if participant_ids:
                participants = (
                    self.db.query(User).filter(User.user_id.in_(participant_ids)).all()
                )
                if len(participants) != len(participant_ids):
                    print("Warning: Some participant IDs were not found.")
                db_meeting.participants.extend(participants)

            # Add to session and commit
            self.db.flush()
            self.db.commit()
            self.db.refresh(db_meeting)
            self.logger(
                f"add_meeting: Meeting {db_meeting.meeting_id} committed and refreshed"
            )
            print(
                f"Successfully added meeting: {db_meeting.title} (ID: {db_meeting.meeting_id})"
            )
            return db_meeting
        except Exception as e:
            self.logger(f"add_meeting: Rolling back transaction due to error: {e}")
            self.db.rollback()
            print(f"Error adding meeting: {str(e)}")
            # self.db.close() # moved to finally block
            return None

    def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        """Get a meeting by its primary key ID, optionally loading relationships."""
        try:
            return (
                self.db.query(Meeting)
                .options(
                    joinedload(Meeting.participants),
                    joinedload(Meeting.facilitator_links).joinedload(
                        MeetingFacilitator.user
                    ),
                    joinedload(Meeting.owner),
                    joinedload(Meeting.agenda_activities),
                )
                .filter(Meeting.meeting_id == meeting_id)
                .first()
            )
        except Exception as e:
            print(f"Error getting meeting ID {meeting_id}: {str(e)}")
            return None

    def join_meeting_by_code(self, meeting_code: str, user: User) -> Meeting:
        meeting = (
            self.db.query(Meeting)
            .options(joinedload(Meeting.participants))
            .filter(Meeting.meeting_id == meeting_code)
            .one_or_none()
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        existing_ids = {u.user_id for u in (meeting.participants or [])}
        if user.user_id not in existing_ids:
            meeting.participants.append(user)
            self.db.flush()
            self.db.commit()
            self.db.refresh(meeting)
        return meeting

    # --- Participants administration ----------------------------------------
    def _should_auto_facilitate(self, user: User) -> bool:
        return user.role in {
            UserRole.FACILITATOR,
            UserRole.ADMIN,
            UserRole.SUPER_ADMIN,
        }

    def _ensure_facilitator_assignment(self, meeting: Meeting, user: User) -> None:
        if not self._should_auto_facilitate(user):
            return

        existing_links = {
            link.user_id: link
            for link in (getattr(meeting, "facilitator_links", []) or [])
            if link.user_id
        }
        is_owner = user.user_id == getattr(meeting, "owner_id", None)
        existing = existing_links.get(user.user_id)
        if existing:
            if is_owner and not existing.is_owner:
                existing.is_owner = True
            return

        facilitator_identifier = generate_facilitator_id(
            self.db,
            user.first_name,
            user.last_name,
        )
        assignment = MeetingFacilitator(
            facilitator_id=facilitator_identifier,
            meeting_id=meeting.meeting_id,
            user_id=user.user_id,
            is_owner=is_owner,
        )
        assignment.user = user
        meeting.facilitator_links.append(assignment)
        self.db.flush()

    def list_participants(self, meeting_id: str) -> List[User]:
        meeting = (
            self.db.query(Meeting)
            .options(joinedload(Meeting.participants))
            .filter(Meeting.meeting_id == meeting_id)
            .one_or_none()
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return list(meeting.participants or [])

    def add_participant(self, meeting_id: str, user: User) -> Meeting:
        meeting = (
            self.db.query(Meeting)
            .options(
                joinedload(Meeting.participants),
                joinedload(Meeting.facilitator_links),
            )
            .filter(Meeting.meeting_id == meeting_id)
            .one_or_none()
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        existing_ids = {u.user_id for u in (meeting.participants or [])}
        if user.user_id not in existing_ids:
            meeting.participants.append(user)
            self._ensure_facilitator_assignment(meeting, user)
            self.db.flush()
            self.db.commit()
            self.db.refresh(meeting)
        return meeting

    def remove_participant(self, meeting_id: str, user_id: str) -> Meeting:
        meeting = (
            self.db.query(Meeting)
            .options(
                joinedload(Meeting.participants),
                joinedload(Meeting.agenda_activities),
            )
            .filter(Meeting.meeting_id == meeting_id)
            .one_or_none()
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        participant_ids = {
            u.user_id
            for u in (meeting.participants or [])
            if getattr(u, "user_id", None)
        }
        if user_id in participant_ids:
            meeting.participants = [
                u for u in (meeting.participants or []) if u.user_id != user_id
            ]
            self._cascade_activity_participant_cleanup(meeting, {user_id})
            self.db.flush()
            self.db.commit()
            self.db.refresh(meeting)
        return meeting

    def bulk_update_participants(
        self,
        meeting_id: str,
        add_user_ids: Optional[Iterable[str]] = None,
        remove_user_ids: Optional[Iterable[str]] = None,
    ) -> Tuple[Meeting, Dict[str, Any]]:
        meeting = (
            self.db.query(Meeting)
            .options(
                joinedload(Meeting.participants),
                joinedload(Meeting.facilitator_links),
                joinedload(Meeting.agenda_activities),
            )
            .filter(Meeting.meeting_id == meeting_id)
            .one_or_none()
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        normalized_add = self._normalise_user_ids(add_user_ids)
        normalized_remove = self._normalise_user_ids(remove_user_ids)

        existing_ids = {
            user.user_id
            for user in (meeting.participants or [])
            if getattr(user, "user_id", None)
        }
        added_ids: List[str] = []
        duplicate_ids: List[str] = []
        missing_ids: List[str] = []

        if normalized_add:
            users_to_add = (
                self.db.query(User).filter(User.user_id.in_(normalized_add)).all()
            )
            found_ids = {user.user_id for user in users_to_add}
            missing_ids = [
                user_id for user_id in normalized_add if user_id not in found_ids
            ]

            for user in users_to_add:
                if user.user_id in existing_ids:
                    duplicate_ids.append(user.user_id)
                    continue
                meeting.participants.append(user)
                self._ensure_facilitator_assignment(meeting, user)
                existing_ids.add(user.user_id)
                added_ids.append(user.user_id)

        removal_targets = [uid for uid in normalized_remove if uid in existing_ids]
        not_in_meeting = [
            uid for uid in normalized_remove if uid and uid not in existing_ids
        ]

        if removal_targets:
            removal_set = set(removal_targets)
            meeting.participants = [
                participant
                for participant in (meeting.participants or [])
                if participant.user_id not in removal_set
            ]
            self._cascade_activity_participant_cleanup(meeting, removal_set)
            existing_ids.difference_update(removal_set)

        if added_ids or removal_targets:
            self.db.flush()
            self.db.commit()
            self.db.refresh(meeting)

        summary = {
            "added_user_ids": added_ids,
            "removed_user_ids": removal_targets,
            "already_participants": duplicate_ids,
            "missing_user_ids": missing_ids,
            "not_in_meeting": not_in_meeting,
        }
        return meeting, summary

    def _cascade_activity_participant_cleanup(
        self, meeting: Meeting, removed_ids: Set[str]
    ) -> None:
        if not removed_ids:
            return
        for activity in meeting.agenda_activities or []:
            config = dict(activity.config or {})
            participant_ids = config.get("participant_ids")
            if isinstance(participant_ids, list):
                filtered = [pid for pid in participant_ids if pid not in removed_ids]
                if filtered:
                    config["participant_ids"] = filtered
                else:
                    config.pop("participant_ids", None)
                activity.config = config

    def _normalise_user_ids(self, values: Optional[Iterable[str]]) -> List[str]:
        cleaned: List[str] = []
        if not values:
            return cleaned
        seen: Set[str] = set()
        for raw in values:
            identifier = (raw or "").strip()
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            cleaned.append(identifier)
        return cleaned

    def set_activity_participants(
        self,
        meeting_id: str,
        activity_id: str,
        participant_ids: Optional[Iterable[str]],
    ) -> AgendaActivity:
        meeting = (
            self.db.query(Meeting)
            .options(
                joinedload(Meeting.participants),
                joinedload(Meeting.agenda_activities),
            )
            .filter(Meeting.meeting_id == meeting_id)
            .one_or_none()
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        activity = next(
            (
                item
                for item in meeting.agenda_activities
                if item.activity_id == activity_id
            ),
            None,
        )
        if not activity:
            raise HTTPException(status_code=404, detail="Agenda activity not found")

        meeting_participant_ids: Set[str] = {
            participant.user_id
            for participant in (meeting.participants or [])
            if participant.user_id
        }

        config = dict(activity.config or {})

        if participant_ids is None:
            config.pop("participant_ids", None)
        else:
            cleaned: List[str] = []
            for raw in participant_ids:
                identifier = (raw or "").strip()
                if not identifier:
                    continue
                if identifier not in meeting_participant_ids:
                    raise HTTPException(
                        status_code=400,
                        detail=f"User {identifier} is not part of this meeting and cannot be assigned.",
                    )
                cleaned.append(identifier)
            if cleaned:
                config["participant_ids"] = cleaned
            else:
                config.pop("participant_ids", None)

        activity.config = config
        self.db.flush()
        self.db.commit()
        self.db.refresh(activity)
        return activity

    def get_all_meetings(self, skip: int = 0, limit: int = 100) -> List[Meeting]:
        """Get all meetings (active and archived) with pagination."""
        try:
            return (
                self.db.query(Meeting)
                .order_by(Meeting.created_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )
        except Exception as e:
            print(f"Error getting all meetings: {str(e)}")
            return []

    # --- Dashboard helpers -------------------------------------------------

    def get_dashboard_meetings(
        self,
        user: User,
        role_scope: str = "participant",
        status_filter: Optional[str] = None,
        sort: str = "start_time",
        archive_scope: str = "active",
    ) -> Dict[str, Any]:
        """Return meetings scoped to the current user with dashboard metadata."""

        if user is None:
            raise HTTPException(
                status_code=400, detail="User context is required to load meetings"
            )

        effective_scope = role_scope or "participant"
        include_participant = effective_scope in {"participant", "all"}
        include_facilitator = effective_scope in {"facilitator", "all"}

        if (
            not include_facilitator
            and effective_scope == "participant"
            and user.role in {UserRole.FACILITATOR.value, UserRole.ADMIN.value}
        ):
            include_facilitator = True

        query = self.db.query(Meeting).options(
            joinedload(Meeting.owner),
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
            joinedload(Meeting.participants),
            joinedload(Meeting.agenda_activities),
        )

        if user.role != UserRole.ADMIN.value or effective_scope != "all":
            filters = []
            if include_facilitator:
                filters.append(
                    or_(
                        Meeting.facilitator_links.any(
                            MeetingFacilitator.user_id == user.user_id
                        ),
                        Meeting.owner_id == user.user_id,
                    )
                )
            if include_participant:
                filters.append(Meeting.participants.any(User.user_id == user.user_id))

            if not filters:
                filters.append(Meeting.participants.any(User.user_id == user.user_id))

            query = query.filter(or_(*filters))

        meetings = query.all()
        meeting_ids = [meeting.meeting_id for meeting in meetings]
        idea_counts: Dict[str, int] = {}
        vote_counts: Dict[str, int] = {}

        if meeting_ids:
            idea_counts = dict(
                self.db.query(Idea.meeting_id, func.count(Idea.id))
                .filter(Idea.meeting_id.in_(meeting_ids))
                .group_by(Idea.meeting_id)
                .all()
            )
            vote_counts = dict(
                self.db.query(VotingVote.meeting_id, func.count(VotingVote.vote_id))
                .filter(VotingVote.meeting_id.in_(meeting_ids))
                .group_by(VotingVote.meeting_id)
                .all()
            )

        items: List[Dict[str, Any]] = []
        notification_totals = {
            "invitations": 0,
            "reminders": 0,
            "updates": 0,
            "announcements": 0,
            "total_unread": 0,
        }
        status_counts = {
            "never_started": 0,
            "not_running": 0,
            "running": 0,
            "stopped": 0,
        }
        now = datetime.now(timezone.utc)

        for meeting in meetings:
            start_at = self._ensure_aware(meeting.started_at)
            end_at = self._ensure_aware(meeting.end_time)
            created_at = self._ensure_aware(meeting.created_at)
            normalized_status = (meeting.status or "").lower()

            if archive_scope == "active" and normalized_status == "archived":
                continue
            if archive_scope == "archived" and normalized_status != "archived":
                continue

            computed_status = self._classify_dashboard_status(
                meeting,
                idea_counts.get(meeting.meeting_id, 0),
                vote_counts.get(meeting.meeting_id, 0),
            )

            if status_filter and computed_status != status_filter:
                continue

            notification_counts = self._compute_notification_counts(meeting, user, now)
            for key in notification_totals.keys():
                notification_totals[key] += notification_counts.get(key, 0)

            status_counts[computed_status] += 1

            facilitator_assignments = self._collect_facilitator_assignments(meeting)
            facilitator_names = [
                self._format_user_name(link.user)
                for link in facilitator_assignments
                if link.user
            ]
            facilitator_name = (
                ", ".join(facilitator_names)
                if facilitator_names
                else self._format_facilitator_name(meeting, facilitator_assignments)
            )
            facilitator_payload = [
                {
                    "id": link.facilitator_id,
                    "user_id": link.user_id,
                    "name": (
                        self._format_user_name(link.user) if link.user else "Unknown"
                    ),
                    "is_owner": bool(link.is_owner),
                }
                for link in facilitator_assignments
            ]
            owner_link = next(
                (link for link in facilitator_assignments if link.is_owner), None
            )
            owner_summary = {
                "id": owner_link.facilitator_id if owner_link else None,
                "user_id": (
                    owner_link.user_id
                    if owner_link
                    else getattr(meeting.owner, "user_id", None)
                ),
                "name": (
                    self._format_user_name(owner_link.user)
                    if owner_link and owner_link.user
                    else self._format_facilitator_name(meeting, facilitator_assignments)
                ),
            }

            items.append(
                {
                    "id": meeting.meeting_id,
                    "meeting_id": meeting.meeting_id,
                    "owner_id": meeting.owner_id,
                    "title": meeting.title,
                    "status": computed_status,
                    "raw_status": normalized_status if normalized_status else None,
                    "start_time": start_at,
                    "end_time": end_at,
                    "created_at": created_at,
                    "description_snippet": self._build_description_snippet(
                        meeting.description
                    ),
                    "facilitator": owner_summary,
                    "facilitator_names": facilitator_names,
                    "facilitators": facilitator_payload,
                    "is_facilitator": any(
                        link.user_id == user.user_id for link in facilitator_assignments
                    ),
                    "is_participant": any(
                        p.user_id == user.user_id
                        for p in getattr(meeting, "participants", [])
                    ),
                    "is_public": meeting.is_public,
                    "participant_count": len(getattr(meeting, "participants", [])),
                    "archive_file": (
                        self._find_latest_archive_file(meeting)
                        if normalized_status == "archived"
                        else None
                    ),
                    "quick_actions": self._build_quick_actions(meeting),
                    "notifications": notification_counts,
                }
            )

        items = self._sort_dashboard_items(items, sort)

        response_payload = {
            "items": items,
            "summary": {
                "total": len(items),
                "never_started": status_counts["never_started"],
                "not_running": status_counts["not_running"],
                "running": status_counts["running"],
                "stopped": status_counts["stopped"],
                "notifications": notification_totals,
            },
            "filters": {
                "role_scope": effective_scope,
                "status": status_filter,
                "sort": sort,
            },
        }

        return response_payload

    def _build_description_snippet(
        self, description: Optional[str], max_length: int = 160
    ) -> str:
        if not description:
            return ""
        snippet = description.strip()
        if len(snippet) <= max_length:
            return snippet
        return snippet[: max(0, max_length - 1)].rstrip() + "…"

    def _classify_dashboard_status(
        self,
        meeting: Meeting,
        idea_count: int,
        vote_count: int,
    ) -> str:
        normalized_status = (meeting.status or "").lower()
        if normalized_status in {"completed", "archived"}:
            return "stopped"

        activities = meeting.agenda_activities or []
        has_running_activity = any(activity.started_at for activity in activities)
        if has_running_activity:
            return "running"

        has_activity_history = any(
            activity.started_at
            or activity.stopped_at
            or (activity.elapsed_duration or 0) > 0
            for activity in activities
        )
        has_participant_activity = idea_count > 0 or vote_count > 0

        if not (has_participant_activity or has_activity_history):
            return "never_started"
        if has_activity_history:
            return "stopped"
        return "not_running"

    def _compute_notification_counts(
        self, meeting: Meeting, user: User, now: datetime
    ) -> Dict[str, int]:
        """Heuristic notification counters until dedicated notification entities exist."""
        is_participant = any(
            p.user_id == user.user_id for p in getattr(meeting, "participants", [])
        )
        counts = {"invitations": 0, "reminders": 0, "updates": 0, "announcements": 0}

        created_at = self._ensure_aware(meeting.created_at)
        start_at = self._ensure_aware(meeting.started_at)

        if is_participant and created_at and (now - created_at) <= timedelta(days=2):
            counts["invitations"] = 1

        if start_at and start_at >= now:
            delta = start_at - now
            if delta <= timedelta(days=1):
                counts["reminders"] = 1

        normalized_status = (meeting.status or "").lower()
        if normalized_status in {"in_progress", "paused"}:
            counts["updates"] = 1

        # Announcements placeholder; real implementation will pull from announcements table/event log.
        counts["announcements"] = 0

        counts["total_unread"] = sum(counts.values())
        return counts

    def _format_facilitator_name(
        self,
        meeting: Meeting,
        assignments: Optional[List[MeetingFacilitator]] = None,
    ) -> str:
        assignments = assignments or self._collect_facilitator_assignments(meeting)
        owner_assignment = next((link for link in assignments if link.is_owner), None)
        if owner_assignment and owner_assignment.user:
            return self._format_user_name(owner_assignment.user)

        owner = getattr(meeting, "owner", None)
        if owner is not None:
            return self._format_user_name(owner)

        if assignments:
            first = assignments[0]
            if first.user:
                return self._format_user_name(first.user)

        return "Unknown"

    def _format_user_name(self, user: User) -> str:
        parts = [user.first_name or "", user.last_name or ""]
        name = " ".join(part for part in parts if part).strip()
        if not name:
            return user.login or user.email or "Unknown"
        return name

    def _collect_facilitator_assignments(
        self, meeting: Meeting
    ) -> List[MeetingFacilitator]:
        """Return facilitator assignments ordered with the owner first."""
        links = list(getattr(meeting, "facilitator_links", []) or [])
        links.sort(
            key=lambda link: (
                not getattr(link, "is_owner", False),
                getattr(link, "created_at", datetime.min.replace(tzinfo=timezone.utc))
                or datetime.min.replace(tzinfo=timezone.utc),
            )
        )
        return links

    def _build_quick_actions(self, meeting: Meeting) -> Dict[str, Optional[str]]:
        page_path = f"/meeting/{meeting.meeting_id}"
        actions = {
            "enter": page_path,
            "view_results": f"/api/meetings/{meeting.meeting_id}/export",
            "details": f"{page_path}/settings",
        }
        return actions

    def update_meeting_configuration(
        self,
        meeting_id: str,
        *,
        title: str,
        description: Optional[str],
        start_time: datetime,
        end_time: datetime,
        participant_ids: Optional[Sequence[str]] = None,
        agenda_items: Optional[Sequence[AgendaActivityCreate]] = None,
    ) -> Meeting:
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        meeting.title = title
        meeting.description = description or meeting.description or "Meeting"
        meeting.started_at = start_time
        meeting.end_time = end_time

        if participant_ids is not None:
            participants = (
                self.db.query(User)
                .filter(User.user_id.in_(participant_ids or []))
                .all()
            )
            meeting.participants = participants
            for participant in participants:
                self._ensure_facilitator_assignment(meeting, participant)

        agenda_payload = list(agenda_items or [])
        self._apply_agenda_items(meeting, agenda_payload)

        self.db.commit()
        self.db.refresh(meeting)
        return meeting

    def _sort_dashboard_items(
        self, items: List[Dict[str, Any]], sort: str
    ) -> List[Dict[str, Any]]:
        if sort == "status":
            order = {"in_progress": 0, "upcoming": 1, "completed": 2}
            return sorted(
                items,
                key=lambda item: (
                    order.get(item["status"], 3),
                    self._datetime_sort_key(item.get("start_time")),
                ),
            )

        if sort == "created":
            return sorted(
                items,
                key=lambda item: self._datetime_sort_key(item.get("created_at")),
                reverse=True,
            )

        # Default sort by start time ascending for upcoming meetings
        return sorted(
            items, key=lambda item: self._datetime_sort_key(item.get("start_time"))
        )

    def _ensure_aware(self, dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def _datetime_sort_key(self, dt: Optional[datetime]) -> float:
        normalized = self._ensure_aware(dt) if dt else None
        if not normalized:
            return float("inf")
        return normalized.timestamp()

    def get_active_meetings(self, skip: int = 0, limit: int = 100) -> List[Meeting]:
        """Get only active meetings with pagination."""
        try:
            # Assuming 'active' covers meetings currently running or paused
            active_statuses = [
                "scheduled",
                "active",
                "paused",
            ]  # Include scheduled meetings as active by default
            return (
                self.db.query(Meeting)
                .filter(Meeting.status.in_(active_statuses))
                .order_by(Meeting.created_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )
        except Exception as e:
            print(f"Error getting active meetings: {str(e)}")
            return []

    def get_archived_meetings(self, skip: int = 0, limit: int = 100) -> List[Meeting]:
        """Get only archived meetings with pagination."""
        try:
            return (
                self.db.query(Meeting)
                .filter(Meeting.status == "archived")
                .order_by(Meeting.created_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )
        except Exception as e:
            print(f"Error getting archived meetings: {str(e)}")
            return []

    def get_meeting_count(self) -> int:
        """Get the total count of meetings."""
        try:
            return self.db.query(Meeting).count()
        except Exception as e:
            print(f"Error getting meeting count: {str(e)}")
            return 0  # Return 0 or raise an exception

    def update_meeting(
        self, meeting_id: str, updated_data: Dict[str, Any]
    ) -> Optional[Meeting]:
        """Update meeting data."""
        try:
            db_meeting = self.get_meeting(meeting_id)
            if not db_meeting:
                print(f"Meeting ID {meeting_id} not found for update.")
                return None

            update_occurred = False
            participant_ids_to_set: Optional[List[str]] = None
            facilitator_user_ids_to_set: Optional[List[str]] = None
            new_owner_id: Optional[str] = None

            for key, value in updated_data.items():
                if key == "participant_ids":
                    # Handle participant list update separately after other fields
                    participant_ids_to_set = value
                    update_occurred = (
                        True  # Mark update even if list is the same, simplifies logic
                    )
                elif key == "facilitator_ids":
                    facilitator_user_ids_to_set = value or []
                    update_occurred = True
                elif key == "owner_id" and value:
                    new_owner_id = value
                    update_occurred = True
                elif hasattr(db_meeting, key) and value is not None:
                    setattr(db_meeting, key, value)
                    update_occurred = True

            if new_owner_id:
                owner_user = (
                    self.db.query(User)
                    .filter(User.user_id == new_owner_id)
                    .one_or_none()
                )
                if owner_user is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Owner not found for ID: {new_owner_id}",
                    )
                db_meeting.owner_id = owner_user.user_id
                db_meeting.owner = owner_user

            # Update participants if provided
            if participant_ids_to_set is not None:
                participants = (
                    self.db.query(User)
                    .filter(User.user_id.in_(participant_ids_to_set))
                    .all()
                )
                db_meeting.participants = (
                    participants  # Replace existing list with new list
                )

            if facilitator_user_ids_to_set is not None or new_owner_id:
                if facilitator_user_ids_to_set is not None:
                    desired_user_ids = set(facilitator_user_ids_to_set or [])
                else:
                    desired_user_ids = {
                        link.user_id
                        for link in getattr(db_meeting, "facilitator_links", [])
                        if link.user_id
                    }
                desired_user_ids.add(db_meeting.owner_id)

                facilitators = (
                    self.db.query(User).filter(User.user_id.in_(desired_user_ids)).all()
                )
                found_ids = {user.user_id for user in facilitators}
                missing_ids = desired_user_ids.difference(found_ids)
                if missing_ids:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Facilitator(s) not found for ID(s): {sorted(missing_ids)}",
                    )

                existing_links = {
                    link.user_id: link for link in list(db_meeting.facilitator_links)
                }

                # Remove assignments no longer desired
                for user_id, link in list(existing_links.items()):
                    if user_id not in desired_user_ids:
                        db_meeting.facilitator_links.remove(link)
                        self.db.delete(link)

                # Ensure desired facilitators exist and flags are correct
                for user in facilitators:
                    link = existing_links.get(user.user_id)
                    is_owner = user.user_id == db_meeting.owner_id
                    if link:
                        link.is_owner = is_owner
                    else:
                        facilitator_identifier = generate_facilitator_id(
                            self.db,
                            user.first_name,
                            user.last_name,
                        )
                        assignment = MeetingFacilitator(
                            facilitator_id=facilitator_identifier,
                            meeting_id=db_meeting.meeting_id,
                            user_id=user.user_id,
                            is_owner=is_owner,
                        )
                        assignment.user = user
                        db_meeting.facilitator_links.append(assignment)
                        self.db.flush()

                update_occurred = True

            if update_occurred:
                self.db.add(db_meeting)
                self.logger(
                    f"update_meeting: Committing meeting {db_meeting.meeting_id}"
                )
                self.db.commit()
                self.db.refresh(db_meeting)
                print(f"Successfully updated meeting ID: {db_meeting.meeting_id}")
                self.logger(
                    f"update_meeting: Meeting {db_meeting.meeting_id} committed and refreshed"
                )
            else:
                print(
                    f"No relevant updates provided for meeting ID: {db_meeting.meeting_id}"
                )

            return db_meeting
        except Exception as e:
            self.logger(f"update_meeting: Rolling back transaction due to error: {e}")
            self.db.rollback()
            print(f"Error updating meeting ID {meeting_id}: {str(e)}")
            # self.db.close() # moved to finally block
            return None

    def archive_meeting(self, meeting_id: str) -> Optional[Meeting]:
        """Archive a meeting by changing its status."""
        try:
            db_meeting = self.get_meeting(meeting_id)
            if not db_meeting:
                print(f"Meeting ID {meeting_id} not found for archiving.")
                return None

            if db_meeting.status != "archived":
                db_meeting.status = "archived"
                self.db.add(db_meeting)
                self.logger(
                    f"archive_meeting: Committing meeting {db_meeting.meeting_id}"
                )
                self.db.commit()
                self.db.refresh(db_meeting)
                print(f"Successfully archived meeting ID: {db_meeting.meeting_id}")
                self.logger(
                    f"archive_meeting: Meeting {db_meeting.meeting_id} committed and refreshed"
                )
            else:
                print(f"Meeting ID {db_meeting.meeting_id} is already archived.")

            return db_meeting
        except Exception as e:
            self.logger(f"archive_meeting: Rolling back transaction due to error: {e}")
            self.db.rollback()
            print(f"Error archiving meeting ID {meeting_id}: {str(e)}")
            # self.db.close() # moved to finally block
            return None

    def delete_meeting_permanently(self, meeting_id: str) -> bool:
        """Deletes a meeting permanently from the database."""
        try:
            db_meeting = self.get_meeting(meeting_id)
            if not db_meeting:
                print(f"Meeting ID {meeting_id} not found for deletion.")
                return False

            self.db.delete(db_meeting)
            self.logger(
                f"delete_meeting_permanently: Committing meeting {meeting_id} deletion"
            )
            self.db.commit()
            print(f"Successfully deleted meeting ID: {meeting_id} permanently.")
            self.logger(
                f"delete_meeting_permanently: Meeting {meeting_id} deletion committed"
            )
            return True
        except Exception as e:
            self.logger(
                f"delete_meeting_permanently: Rolling back transaction due to error: {e}"
            )
            self.db.rollback()
            print(f"Error deleting meeting ID {meeting_id}: {str(e)}")
            # self.db.close() # moved to finally block
            return False


# Note: Removed the singleton instance creation


def get_meeting_manager(db: Session = Depends(get_db)) -> MeetingManager:
    """Dependency provider for MeetingManager."""
    try:
        return MeetingManager(db=db)
    finally:
        db.close()
