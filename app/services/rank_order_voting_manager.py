from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting
from app.models.rank_order_voting import RankOrderVote
from app.models.user import User, UserRole


@dataclass(frozen=True)
class RankOrderOption:
    option_id: str
    label: str
    raw_item: Optional[Dict[str, Any]] = None


class RankOrderVotingManager:
    def __init__(self, db: Session, logger=None) -> None:
        self.db = db
        self.logger = logger or (lambda _msg: None)

    @staticmethod
    def _normalize_label(raw: Any) -> str:
        if raw is None:
            return ""
        return str(raw).strip()

    @staticmethod
    def _normalize_option_id(activity_id: str, label: str, index: int) -> str:
        slug = (
            label.lower().strip().replace(" ", "-").replace("/", "-").replace("\\", "-")
        )
        slug = "".join(ch for ch in slug if ch.isalnum() or ch in {"-", "_"})
        slug = slug or f"idea-{index + 1}"
        return f"{activity_id}:{slug}"

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
            ro_meta = metadata.get("rank_order_voting")
            if isinstance(ro_meta, dict):
                option_id = ro_meta.get("option_id")
                if option_id:
                    candidate = str(option_id).strip()
                    if candidate.startswith(f"{activity_id}:"):
                        return candidate

        item_id = item.get("id")
        if item_id is not None and str(item_id).strip():
            return f"{activity_id}:idea-{str(item_id).strip()}"

        return self._normalize_option_id(activity_id, label, index)

    def _extract_options(self, activity: AgendaActivity) -> List[RankOrderOption]:
        config = activity.config or {}
        raw_ideas = config.get("ideas", [])
        options: List[RankOrderOption] = []

        if isinstance(raw_ideas, str):
            for index, line in enumerate(raw_ideas.splitlines()):
                label = self._normalize_label(line)
                if not label:
                    continue
                options.append(
                    RankOrderOption(
                        option_id=self._normalize_option_id(activity.activity_id, label, index),
                        label=label,
                        raw_item=None,
                    )
                )
        elif isinstance(raw_ideas, Sequence):
            for index, value in enumerate(raw_ideas):
                if isinstance(value, str):
                    label = self._normalize_label(value)
                    if not label:
                        continue
                    options.append(
                        RankOrderOption(
                            option_id=self._normalize_option_id(activity.activity_id, label, index),
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
                        RankOrderOption(
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

        deduped: List[RankOrderOption] = []
        seen_ids: Set[str] = set()
        for option in options:
            if option.option_id in seen_ids:
                continue
            seen_ids.add(option.option_id)
            deduped.append(option)
        return deduped

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

    def _resolve_activity(self, meeting: Meeting, activity_id: str) -> AgendaActivity:
        if not meeting.agenda_activities:
            raise HTTPException(status_code=404, detail="No agenda activities found for this meeting.")
        for activity in meeting.agenda_activities:
            if activity.activity_id == activity_id:
                if str(activity.tool_type or "").lower() != "rank_order_voting":
                    raise HTTPException(
                        status_code=400,
                        detail="Requested activity is not rank-order voting.",
                    )
                return activity
        raise HTTPException(status_code=404, detail="Agenda activity not found.")

    def _aggregate_user_ranking(
        self,
        meeting_id: str,
        activity_id: str,
        user_id: str,
    ) -> Dict[str, int]:
        rows = (
            self.db.query(RankOrderVote.option_id, RankOrderVote.rank_position)
            .filter(
                RankOrderVote.meeting_id == meeting_id,
                RankOrderVote.activity_id == activity_id,
                RankOrderVote.user_id == user_id,
            )
            .all()
        )
        return {str(option_id): int(rank_position) for option_id, rank_position in rows}

    def _aggregate_submission_count(self, meeting_id: str, activity_id: str) -> int:
        value = (
            self.db.query(func.count(func.distinct(RankOrderVote.user_id)))
            .filter(
                RankOrderVote.meeting_id == meeting_id,
                RankOrderVote.activity_id == activity_id,
            )
            .scalar()
        )
        return int(value or 0)

    def _aggregate_borda(
        self,
        meeting_id: str,
        activity_id: str,
        option_ids: Set[str],
        option_count: int,
    ) -> Dict[str, Dict[str, float]]:
        rows = (
            self.db.query(
                RankOrderVote.user_id,
                RankOrderVote.option_id,
                RankOrderVote.rank_position,
            )
            .filter(
                RankOrderVote.meeting_id == meeting_id,
                RankOrderVote.activity_id == activity_id,
            )
            .all()
        )

        by_user: Dict[str, Dict[str, int]] = {}
        for user_id, option_id, rank_position in rows:
            normalized_option_id = str(option_id)
            if normalized_option_id not in option_ids:
                continue
            by_user.setdefault(str(user_id), {})[normalized_option_id] = int(rank_position)

        complete_rankings = [ranking for ranking in by_user.values() if len(ranking) == option_count]
        submission_count = len(complete_rankings)

        metrics: Dict[str, Dict[str, float]] = {
            option_id: {
                "borda_score": 0.0,
                "rank_sum": 0.0,
                "rank_sq_sum": 0.0,
                "top_choice_count": 0.0,
                "submission_count": float(submission_count),
            }
            for option_id in option_ids
        }

        for ranking in complete_rankings:
            for option_id, rank in ranking.items():
                data = metrics[option_id]
                data["borda_score"] += float(max(option_count - int(rank), 0))
                data["rank_sum"] += float(rank)
                data["rank_sq_sum"] += float(rank * rank)
                if int(rank) == 1:
                    data["top_choice_count"] += 1.0

        for option_id, data in metrics.items():
            if submission_count <= 0:
                data["avg_rank"] = 0.0
                data["rank_variance"] = 0.0
                data["top_choice_share"] = 0.0
                continue
            avg_rank = data["rank_sum"] / submission_count
            mean_sq = data["rank_sq_sum"] / submission_count
            variance = max(mean_sq - (avg_rank * avg_rank), 0.0)
            data["avg_rank"] = avg_rank
            data["rank_variance"] = variance
            data["top_choice_share"] = data["top_choice_count"] / submission_count

        return metrics

    def build_summary(
        self,
        meeting: Meeting,
        activity_id: str,
        user: User,
        *,
        force_results: bool = False,
        is_active_state: bool = False,
        active_participant_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        activity = self._resolve_activity(meeting, activity_id)
        options = self._extract_options(activity)

        config = dict(activity.config or {})
        show_results = bool(config.get("show_results_immediately", False))
        allow_reset = bool(config.get("allow_reset", True))
        randomize_order = bool(config.get("randomize_order", False))

        is_facilitator = self._is_facilitator(meeting, user)
        can_view_results = bool(show_results or force_results or is_facilitator)

        user_ranking = self._aggregate_user_ranking(
            meeting.meeting_id,
            activity.activity_id,
            user.user_id,
        )
        if not options:
            return {
                "activity_id": activity.activity_id,
                "tool_type": activity.tool_type,
                "show_results": show_results,
                "can_view_results": can_view_results,
                "allow_reset": allow_reset,
                "randomize_order": randomize_order,
                "submitted": False,
                "is_active": bool(is_active_state),
                "submission_count": 0,
                "active_participant_count": int(active_participant_count or 0),
                "options": [],
                "results": [],
            }

        submitted = len(user_ranking) == len(options)

        option_ids = {option.option_id for option in options}
        borda = self._aggregate_borda(
            meeting.meeting_id,
            activity.activity_id,
            option_ids,
            len(options),
        )

        def option_payload(option: RankOrderOption) -> Dict[str, Any]:
            metric = borda.get(option.option_id, {})
            return {
                "option_id": option.option_id,
                "label": option.label,
                "user_rank": user_ranking.get(option.option_id),
                "borda_score": metric.get("borda_score") if can_view_results else None,
                "avg_rank": metric.get("avg_rank") if can_view_results else None,
                "rank_variance": metric.get("rank_variance") if can_view_results else None,
                "top_choice_share": metric.get("top_choice_share") if can_view_results else None,
            }

        serialized_options = [option_payload(option) for option in options]

        if submitted:
            serialized_options.sort(
                key=lambda row: (
                    int(row.get("user_rank") or 999999),
                    str(row.get("label") or "").casefold(),
                )
            )
        elif randomize_order and not is_facilitator:
            serialized_options.sort(
                key=lambda row: self._participant_order_key(
                    meeting.meeting_id,
                    activity.activity_id,
                    user.user_id,
                    row["option_id"],
                )
            )

        if can_view_results:
            results = sorted(
                serialized_options,
                key=lambda row: (
                    -(float(row.get("borda_score") or 0.0)),
                    float(row.get("avg_rank") or 999999.0),
                    str(row.get("label") or "").casefold(),
                ),
            )
        else:
            results = []

        submission_count = self._aggregate_submission_count(
            meeting.meeting_id,
            activity.activity_id,
        )

        return {
            "activity_id": activity.activity_id,
            "tool_type": activity.tool_type,
            "show_results": show_results,
            "can_view_results": can_view_results,
            "allow_reset": allow_reset,
            "randomize_order": randomize_order,
            "submitted": submitted,
            "is_active": bool(is_active_state),
            "submission_count": submission_count,
            "active_participant_count": int(active_participant_count or 0),
            "options": serialized_options,
            "results": results,
        }

    def submit_ranking(
        self,
        meeting: Meeting,
        activity_id: str,
        user: User,
        ordered_option_ids: List[str],
        *,
        is_active_state: bool,
        active_participant_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        activity = self._resolve_activity(meeting, activity_id)
        options = self._extract_options(activity)
        expected_ids = [option.option_id for option in options]
        if not expected_ids:
            raise HTTPException(status_code=400, detail="Rank-order voting has no configured ideas.")

        normalized_ids = [str(option_id).strip() for option_id in ordered_option_ids if str(option_id).strip()]
        if len(normalized_ids) != len(expected_ids):
            raise HTTPException(status_code=400, detail="Ranking must include every idea exactly once.")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise HTTPException(status_code=400, detail="Ranking includes duplicate ideas.")

        expected_set = set(expected_ids)
        provided_set = set(normalized_ids)
        if provided_set != expected_set:
            raise HTTPException(status_code=400, detail="Ranking contains invalid ideas for this activity.")

        option_lookup = {option.option_id: option for option in options}

        self.db.query(RankOrderVote).filter(
            RankOrderVote.meeting_id == meeting.meeting_id,
            RankOrderVote.activity_id == activity.activity_id,
            RankOrderVote.user_id == user.user_id,
        ).delete(synchronize_session=False)

        for index, option_id in enumerate(normalized_ids, start=1):
            option = option_lookup[option_id]
            self.db.add(
                RankOrderVote(
                    meeting_id=meeting.meeting_id,
                    activity_id=activity.activity_id,
                    user_id=user.user_id,
                    option_id=option.option_id,
                    option_label=option.label,
                    rank_position=index,
                )
            )
        self.db.commit()

        return self.build_summary(
            meeting,
            activity.activity_id,
            user,
            force_results=self._is_facilitator(meeting, user),
            is_active_state=is_active_state,
            active_participant_count=active_participant_count,
        )

    def reset_ranking(
        self,
        meeting: Meeting,
        activity_id: str,
        user: User,
        *,
        is_active_state: bool,
        active_participant_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        activity = self._resolve_activity(meeting, activity_id)
        config = dict(activity.config or {})
        allow_reset = bool(config.get("allow_reset", True))
        if not allow_reset:
            raise HTTPException(status_code=400, detail="Ranking reset is disabled for this activity.")

        self.db.query(RankOrderVote).filter(
            RankOrderVote.meeting_id == meeting.meeting_id,
            RankOrderVote.activity_id == activity.activity_id,
            RankOrderVote.user_id == user.user_id,
        ).delete(synchronize_session=False)
        self.db.commit()

        return self.build_summary(
            meeting,
            activity.activity_id,
            user,
            force_results=self._is_facilitator(meeting, user),
            is_active_state=is_active_state,
            active_participant_count=active_participant_count,
        )

    def reset_activity_state(
        self,
        meeting_id: str,
        activity_id: str,
        *,
        clear_bundles: bool = True,
    ) -> None:
        self.db.query(RankOrderVote).filter(
            RankOrderVote.meeting_id == meeting_id,
            RankOrderVote.activity_id == activity_id,
        ).delete(synchronize_session=False)
        if clear_bundles:
            self.db.query(ActivityBundle).filter(
                ActivityBundle.meeting_id == meeting_id,
                ActivityBundle.activity_id == activity_id,
            ).delete(synchronize_session=False)
        self.db.commit()
