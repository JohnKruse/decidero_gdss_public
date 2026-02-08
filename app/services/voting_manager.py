from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.models.voting import VotingVote


@dataclass(frozen=True)
class VotingOption:
    option_id: str
    label: str
    raw_item: Optional[Dict[str, Any]] = None


class VotingManager:
    def __init__(self, db: Session, logger=None) -> None:
        self.db = db
        self.logger = logger or (lambda msg: None)

    @staticmethod
    def _normalize_option_id(activity_id: str, label: str, index: int) -> str:
        slug = (
            label.lower().strip().replace(" ", "-").replace("/", "-").replace("\\", "-")
        )
        slug = "".join(char for char in slug if char.isalnum() or char in {"-", "_"})
        slug = slug or f"opt-{index+1}"
        return f"{activity_id}:{slug}"

    @staticmethod
    def _normalize_label(raw: Any) -> str:
        if raw is None:
            return ""
        return str(raw).strip()

    def _scoped_option_id(
        self, activity_id: str, candidate: str, index: int
    ) -> str:
        suffix = str(candidate).strip().split(":", 1)[-1]
        suffix = self._normalize_label(suffix) or suffix
        return self._normalize_option_id(activity_id, suffix, index)

    def _option_id_for_item(
        self,
        activity_id: str,
        item: Dict[str, Any],
        label: str,
        index: int,
    ) -> str:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if isinstance(metadata, dict):
            direct = metadata.get("option_id")
            if direct:
                candidate = str(direct).strip()
                if candidate.startswith(f"{activity_id}:"):
                    return candidate
                return self._scoped_option_id(activity_id, candidate, index)
            voting_meta = metadata.get("voting")
            if isinstance(voting_meta, dict):
                option_id = voting_meta.get("option_id")
                if option_id:
                    candidate = str(option_id).strip()
                    if candidate.startswith(f"{activity_id}:"):
                        return candidate
                    return self._scoped_option_id(activity_id, candidate, index)

        item_id = item.get("id")
        if item_id is not None and str(item_id).strip():
            return f"{activity_id}:idea-{str(item_id).strip()}"

        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        if isinstance(source, dict):
            upstream_activity = source.get("activity_id")
            if upstream_activity and str(upstream_activity).strip():
                return f"{activity_id}:src-{str(upstream_activity).strip()}:{index+1}"

        return self._normalize_option_id(activity_id, label, index)

    def _extract_options(self, activity: AgendaActivity) -> List[VotingOption]:
        config = activity.config or {}
        raw_options = config.get("options", [])
        options: List[VotingOption] = []
        if isinstance(raw_options, str):
            for index, line in enumerate(raw_options.splitlines()):
                label = self._normalize_label(line)
                if not label:
                    continue
                options.append(
                    VotingOption(
                        option_id=self._normalize_option_id(
                            activity.activity_id, label, index
                        ),
                        label=label,
                        raw_item=None,
                    )
                )
        elif isinstance(raw_options, Sequence):
            for index, value in enumerate(raw_options):
                if isinstance(value, str):
                    label = self._normalize_label(value)
                    if not label:
                        continue
                    options.append(
                        VotingOption(
                            option_id=self._normalize_option_id(
                                activity.activity_id, label, index
                            ),
                            label=label,
                            raw_item=None,
                        )
                    )
                    continue

                if isinstance(value, dict):
                    label = self._normalize_label(value.get("content"))
                    if not label:
                        label = self._normalize_label(value.get("label"))
                    if not label:
                        continue
                    options.append(
                        VotingOption(
                            option_id=self._option_id_for_item(
                                activity.activity_id,
                                value,
                                label,
                                index,
                            ),
                            label=label,
                            raw_item=value,
                        )
                    )

        if not options:
            return []

        for option in options:
            if not option.option_id.startswith(f"{activity.activity_id}:"):
                raise HTTPException(
                    status_code=400,
                    detail="Voting option IDs must be scoped to the activity.",
                )

        return options

    @staticmethod
    def _is_facilitator(meeting: Meeting, user: User) -> bool:
        role_value = getattr(user, "role", UserRole.PARTICIPANT.value)
        if role_value in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}:
            return True
        if getattr(meeting, "owner_id", None) == user.user_id:
            return True
        for link in meeting.facilitator_links or []:
            if getattr(link, "user_id", None) == user.user_id:
                return True
        return False

    @staticmethod
    def _participant_order_key(
        meeting_id: str,
        activity_id: str,
        user_id: str,
        option_id: str,
    ) -> Tuple[int, str]:
        seed = f"{meeting_id}:{activity_id}:{user_id}:{option_id}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return int(digest, 16), option_id

    def _aggregate_totals(self, meeting_id: str, activity_id: str) -> Dict[str, int]:
        rows = (
            self.db.query(VotingVote.option_id, func.sum(VotingVote.weight))
            .filter(
                VotingVote.meeting_id == meeting_id,
                VotingVote.activity_id == activity_id,
            )
            .group_by(VotingVote.option_id)
            .all()
        )
        return {option_id: int(total or 0) for option_id, total in rows}

    def aggregate_totals(self, meeting_id: str, activity_id: str) -> Dict[str, int]:
        return self._aggregate_totals(meeting_id, activity_id)

    def _aggregate_user_totals(
        self,
        meeting_id: str,
        activity_id: str,
        user_id: str,
    ) -> Tuple[int, Dict[str, int]]:
        rows = (
            self.db.query(
                VotingVote.option_id,
                func.sum(VotingVote.weight),
            )
            .filter(
                VotingVote.meeting_id == meeting_id,
                VotingVote.activity_id == activity_id,
                VotingVote.user_id == user_id,
            )
            .group_by(VotingVote.option_id)
            .all()
        )
        per_option = {option_id: int(total or 0) for option_id, total in rows}
        total_cast = sum(per_option.values())
        return total_cast, per_option

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _normalize_max_votes(self, raw_value: Any, option_count: int) -> int:
        max_votes = self._coerce_int(raw_value, 0)
        if option_count == 0:
            return 0
        if option_count > 0:
            if max_votes <= 0:
                max_votes = math.ceil(option_count / 4)
            max_votes = max(1, max_votes)
        else:
            if max_votes <= 0:
                max_votes = 1
        return max_votes

    def reset_activity_state(
        self,
        meeting_id: str,
        activity_id: str,
        *,
        clear_bundles: bool = True,
    ) -> None:
        self.db.query(VotingVote).filter(
            VotingVote.meeting_id == meeting_id,
            VotingVote.activity_id == activity_id,
        ).delete(synchronize_session=False)
        if clear_bundles:
            self.db.query(ActivityBundle).filter(
                ActivityBundle.meeting_id == meeting_id,
                ActivityBundle.activity_id == activity_id,
            ).delete(synchronize_session=False)
        self.db.commit()

    def _resolve_activity(
        self,
        meeting: Meeting,
        activity_id: str,
    ) -> AgendaActivity:
        if not meeting.agenda_activities:
            raise HTTPException(
                status_code=404, detail="No agenda activities found for this meeting."
            )
        for activity in meeting.agenda_activities:
            if activity.activity_id == activity_id:
                return activity
        raise HTTPException(status_code=404, detail="Agenda activity not found.")

    def _resolve_voting_activity(
        self,
        meeting: Meeting,
        activity_id: str,
    ) -> AgendaActivity:
        activity = self._resolve_activity(meeting, activity_id)
        if activity.tool_type.lower() != "voting":
            raise HTTPException(
                status_code=400, detail="Requested activity is not a voting module."
            )
        return activity

    def build_summary(
        self,
        meeting: Meeting,
        activity_id: str,
        user: User,
        force_results: bool = False,
        is_active_state: bool = False,
    ) -> Dict[str, object]:
        activity = self._resolve_voting_activity(meeting, activity_id)
        options = self._extract_options(activity)
        config = activity.config or {}
        max_votes = self._normalize_max_votes(config.get("max_votes"), len(options))
        max_votes_per_option_raw = config.get("max_votes_per_option")
        max_votes_per_option: Optional[int] = None
        if max_votes_per_option_raw is not None:
            max_votes_per_option = max(
                1, self._coerce_int(max_votes_per_option_raw, 1)
            )
            max_votes_per_option = min(9, max_votes_per_option)
            max_votes_per_option = min(max_votes, max_votes_per_option)
        allow_retract = bool(config.get("allow_retract", True))
        vote_label_singular = self._normalize_label(config.get("vote_label_singular"))
        vote_label_plural = self._normalize_label(config.get("vote_label_plural"))
        vote_label_singular = vote_label_singular or None
        vote_label_plural = vote_label_plural or None
        show_results = bool(config.get("show_results_immediately", True))

        totals = self._aggregate_totals(meeting.meeting_id, activity.activity_id)
        user_total, user_option_totals = self._aggregate_user_totals(
            meeting.meeting_id,
            activity.activity_id,
            user.user_id,
        )
        is_facilitator = self._is_facilitator(meeting, user)
        has_locked_submission = user_total > 0 and not allow_retract
        can_view_results = (
            show_results or force_results or is_facilitator or has_locked_submission
        )

        serialized_options = []
        for option in options:
            option_id = option.option_id
            serialized_options.append(
                {
                    "option_id": option_id,
                    "label": option.label,
                    "votes": totals.get(option_id, 0) if can_view_results else None,
                    "user_votes": user_option_totals.get(option_id, 0),
                }
            )

        randomize_participant_order = bool(
            config.get("randomize_participant_order", False)
        )
        if randomize_participant_order and not self._is_facilitator(meeting, user):
            serialized_options.sort(
                key=lambda opt: self._participant_order_key(
                    meeting.meeting_id,
                    activity.activity_id,
                    user.user_id,
                    opt["option_id"],
                )
            )

        return {
            "activity_id": activity.activity_id,
            "tool_type": activity.tool_type,
            "max_votes": max_votes,
            "max_votes_per_option": max_votes_per_option,
            "allow_retract": allow_retract,
            "vote_label_singular": vote_label_singular,
            "vote_label_plural": vote_label_plural,
            "votes_cast": user_total,
            "remaining_votes": max(max_votes - user_total, 0),
            "show_results": show_results,
            "can_view_results": can_view_results,
            "is_active": is_active_state,
            "options": serialized_options,
        }

    def cast_vote(
        self,
        meeting: Meeting,
        activity_id: str,
        user: User,
        option_id: str,
        action: str = "add",
    ) -> Dict[str, object]:
        activity = self._resolve_voting_activity(meeting, activity_id)
        options = self._extract_options(activity)
        option_lookup = {opt.option_id: opt for opt in options}
        selected = option_lookup.get(option_id)
        if not selected:
            raise HTTPException(
                status_code=400,
                detail="Selected option is not valid for this activity.",
            )

        config = activity.config or {}
        max_votes = self._normalize_max_votes(config.get("max_votes"), len(options))
        max_votes_per_option_raw = config.get("max_votes_per_option")
        max_votes_per_option: Optional[int] = None
        if max_votes_per_option_raw is not None:
            max_votes_per_option = max(
                1, self._coerce_int(max_votes_per_option_raw, 1)
            )
            max_votes_per_option = min(9, max_votes_per_option)
            max_votes_per_option = min(max_votes, max_votes_per_option)
        allow_retract = bool(config.get("allow_retract", True))

        current_votes, _ = self._aggregate_user_totals(
            meeting.meeting_id,
            activity.activity_id,
            user.user_id,
        )
        action_value = str(action or "add").strip().lower()
        if action_value not in {"add", "retract"}:
            raise HTTPException(status_code=400, detail="Invalid voting action.")

        if action_value == "retract":
            if not allow_retract:
                raise HTTPException(
                    status_code=400, detail="Vote retraction is not enabled."
                )
            existing_vote = (
                self.db.query(VotingVote)
                .filter(
                    VotingVote.meeting_id == meeting.meeting_id,
                    VotingVote.activity_id == activity.activity_id,
                    VotingVote.user_id == user.user_id,
                    VotingVote.option_id == selected.option_id,
                )
                .order_by(VotingVote.created_at.desc())
                .first()
            )
            if not existing_vote:
                raise HTTPException(status_code=400, detail="No vote to retract.")
            self.db.delete(existing_vote)
            self.db.commit()

            is_facilitator = user.role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value} or any(
                link.user_id == user.user_id
                for link in (meeting.facilitator_links or [])
            )
            meeting_state = self.db.merge(meeting)
            return self.build_summary(
                meeting_state,
                activity.activity_id,
                user,
                force_results=is_facilitator,
                is_active_state=True,
            )

        if current_votes >= max_votes:
            raise HTTPException(
                status_code=400, detail="Vote limit reached for this activity."
            )

        _, current_by_option = self._aggregate_user_totals(
            meeting.meeting_id,
            activity.activity_id,
            user.user_id,
        )
        if (
            max_votes_per_option is not None
            and current_by_option.get(selected.option_id, 0) >= max_votes_per_option
        ):
            raise HTTPException(
                status_code=400,
                detail="Vote limit reached for this option.",
            )

        vote = VotingVote(
            meeting_id=meeting.meeting_id,
            activity_id=activity.activity_id,
            user_id=user.user_id,
            option_id=selected.option_id,
            option_label=selected.label,
            weight=1,
        )
        self.db.add(vote)
        self.db.commit()

        is_facilitator = user.role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value} or any(
            link.user_id == user.user_id for link in (meeting.facilitator_links or [])
        )
        meeting_state = self.db.merge(meeting)
        return self.build_summary(
            meeting_state,
            activity.activity_id,
            user,
            force_results=is_facilitator,
            is_active_state=True,
        )
