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
from app.services.meeting_authorization import resolve_meeting_capabilities


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
        return bool(resolve_meeting_capabilities(meeting, user)["can_manage"])

    @staticmethod
    def _stable_option_key(option_id: str) -> str:
        """The activity-independent part of an option id.

        Option ids are prefixed `{activity_id}:...`, and each Delphi round is a new
        activity, so the raw option id changes every round. Stripping the prefix
        yields a key tied to the item's identity (idea id / content slug) that is
        stable across rounds — so a participant's randomized order stays consistent
        round to round instead of reshuffling.
        """
        text = str(option_id)
        return text.split(":", 1)[1] if ":" in text else text

    def _own_prior_ranks(
        self, meeting: Meeting, round_index: int, user_id: str
    ) -> Dict[str, int]:
        """The viewer's own rank for each item in the prior round, keyed by stable
        option key, so re-ranking can show "you ranked it N last round".

        Reads the previous round's rank_order_voting activity and this user's votes
        on it; the stable key bridges the per-round option-id prefix change.
        """
        prior_rank_activity = None
        for activity in getattr(meeting, "agenda_activities", []) or []:
            if activity.tool_type != "rank_order_voting":
                continue
            orchestration = (activity.config or {}).get("_orchestration") or {}
            try:
                if int(orchestration.get("round_index", -1)) == round_index - 1:
                    prior_rank_activity = activity
            except (TypeError, ValueError):
                continue
        if prior_rank_activity is None:
            return {}
        ranks = self._aggregate_user_ranking(
            meeting.meeting_id, prior_rank_activity.activity_id, user_id
        )
        return {
            self._stable_option_key(option_id): rank
            for option_id, rank in ranks.items()
        }

    def _own_rationale_texts(
        self, meeting: Meeting, justification_activity_id: str, user_id: str
    ) -> Dict[str, str]:
        """The requesting user's own prior-round rationales, keyed by option id.

        Read from this user's private `OutlierRationale` rows so the cross-round
        comment display can privately flag a comment as the viewer's own without
        the unattributed bundle ever carrying peer identities.
        """
        from app.models.outlier_rationale import OutlierRationale

        rows = (
            self.db.query(OutlierRationale)
            .filter(
                OutlierRationale.meeting_id == meeting.meeting_id,
                OutlierRationale.activity_id == justification_activity_id,
                OutlierRationale.user_id == user_id,
            )
            .all()
        )
        return {
            row.option_id: (row.rationale or "").strip()
            for row in rows
            if (row.rationale or "").strip()
        }

    @classmethod
    def _participant_order_key(
        cls,
        meeting_id: str,
        user_id: str,
        option_id: str,
    ) -> Tuple[int, str]:
        stable_key = cls._stable_option_key(option_id)
        seed = f"{meeting_id}:{user_id}:{stable_key}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return int(digest, 16), stable_key

    @staticmethod
    def _prior_group_order_key(row: Dict[str, Any]) -> Tuple[float, float, str]:
        """Sort Round 2+ Delphi items by the prior group result.

        Median rank is the primary controlled-feedback signal; IQR is the
        tie-breaker so equally ranked but more settled items appear first.
        """
        feedback = row.get("prior_round_feedback") or {}
        try:
            median = float(feedback.get("median"))
        except (TypeError, ValueError):
            median = 999999.0
        try:
            iqr = float(feedback.get("iqr"))
        except (TypeError, ValueError):
            iqr = 999999.0
        return median, iqr, str(row.get("label") or "").casefold()

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

        # Delphi: load prior round outlier justification rationales if we are in an iterate loop.
        # Comments stay peer-anonymous in the bundle (unattributed text only); the
        # `mine` flag below is computed per-viewer from this user's own private
        # rationale rows and is never persisted, so no peer identity is exposed.
        rationales_by_stable_key: Dict[str, List[Dict[str, Any]]] = {}
        delphi_round: Optional[Dict[str, int]] = None
        from app.services.agenda_strategy import get_agenda_strategy, OrchestrationEngineStrategy
        strategy = get_agenda_strategy(meeting)
        if isinstance(strategy, OrchestrationEngineStrategy):
            # Round progression is shown even before ideas load, so compute it
            # ahead of the no-options early return below.
            delphi_round = strategy.round_progress_for(activity.activity_id)

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
                "delphi_round": delphi_round,
            }

        submitted = len(user_ranking) == len(options)

        option_ids = {option.option_id for option in options}
        borda = self._aggregate_borda(
            meeting.meeting_id,
            activity.activity_id,
            option_ids,
            len(options),
        )

        # Delphi: load prior round outlier justification rationales if we are in an
        # iterate loop (strategy + delphi_round were resolved above).
        own_prior_ranks: Dict[str, int] = {}
        if isinstance(strategy, OrchestrationEngineStrategy):
            _, round_index = strategy.iteration_metadata_for(activity.activity_id)
            if round_index > 0:
                own_prior_ranks = self._own_prior_ranks(
                    meeting, round_index, user.user_id
                )
                prior_bundles = (
                    self.db.query(ActivityBundle)
                    .filter(
                        ActivityBundle.meeting_id == meeting.meeting_id,
                        ActivityBundle.round_index == round_index - 1,
                        ActivityBundle.kind == "output",
                    )
                    .all()
                )
                just_bundle = None
                for bundle in prior_bundles:
                    if dict(bundle.bundle_metadata or {}).get("source") == "outlier_justification":
                        just_bundle = bundle
                        break

                if just_bundle and just_bundle.items:
                    own_texts = self._own_rationale_texts(
                        meeting, just_bundle.activity_id, user.user_id
                    )
                    for item in just_bundle.items:
                        item_meta = item.get("metadata") or {}
                        just_meta = item_meta.get("outlier_justification") or {}
                        prior_opt_id = just_meta.get("option_id")
                        prior_rationales = just_meta.get("rationales")
                        if prior_opt_id and prior_rationales:
                            stable_key = self._stable_option_key(prior_opt_id)
                            mine_text = own_texts.get(prior_opt_id)
                            marked_mine = False
                            entries: List[Dict[str, Any]] = []
                            for text in prior_rationales:
                                is_mine = (
                                    not marked_mine
                                    and mine_text is not None
                                    and (text or "").strip() == mine_text
                                )
                                if is_mine:
                                    marked_mine = True
                                entries.append({"text": text, "mine": is_mine})
                            rationales_by_stable_key[stable_key] = entries

        def prior_round_feedback(option: RankOrderOption) -> Optional[Dict[str, Any]]:
            # Delphi controlled feedback: the prior round's median/IQR ride along
            # on the input-bundle item metadata (see DelphiStatisticalAggregation).
            # Always surfaced (it is last round's data, not this round's live tally).
            raw = option.raw_item if isinstance(option.raw_item, dict) else {}
            meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            delphi = meta.get("delphi") if isinstance(meta.get("delphi"), dict) else {}
            if not delphi:
                return None
            return {
                "median": delphi.get("median"),
                "iqr": delphi.get("iqr"),
                "dispersion": delphi.get("dispersion"),
                "your_prior_rank": own_prior_ranks.get(
                    self._stable_option_key(option.option_id)
                ),
            }

        def option_payload(option: RankOrderOption) -> Dict[str, Any]:
            metric = borda.get(option.option_id, {})
            stable_key = self._stable_option_key(option.option_id)
            return {
                "option_id": option.option_id,
                "label": option.label,
                "user_rank": user_ranking.get(option.option_id),
                "borda_score": metric.get("borda_score") if can_view_results else None,
                "avg_rank": metric.get("avg_rank") if can_view_results else None,
                "rank_variance": metric.get("rank_variance") if can_view_results else None,
                "top_choice_share": metric.get("top_choice_share") if can_view_results else None,
                "prior_round_feedback": prior_round_feedback(option),
                "prior_round_rationales": rationales_by_stable_key.get(stable_key),
            }

        serialized_options = [option_payload(option) for option in options]

        has_prior_group_feedback = any(row.get("prior_round_feedback") for row in serialized_options)

        if submitted:
            serialized_options.sort(
                key=lambda row: (
                    int(row.get("user_rank") or 999999),
                    str(row.get("label") or "").casefold(),
                )
            )
        elif has_prior_group_feedback:
            serialized_options.sort(key=self._prior_group_order_key)
        elif randomize_order and not is_facilitator:
            serialized_options.sort(
                key=lambda row: self._participant_order_key(
                    meeting.meeting_id,
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
            "delphi_round": delphi_round,
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
        # synchronize_session='fetch' so SQLAlchemy expires the deleted rows
        # from the identity map. Without it, a deleted ActivityBundle whose
        # row is later autoincrement-reassigned (common on SQLite) collides
        # with the ghost entry and triggers an "Identity map already had an
        # identity" warning on the next flush.
        self.db.query(RankOrderVote).filter(
            RankOrderVote.meeting_id == meeting_id,
            RankOrderVote.activity_id == activity_id,
        ).delete(synchronize_session="fetch")
        if clear_bundles:
            self.db.query(ActivityBundle).filter(
                ActivityBundle.meeting_id == meeting_id,
                ActivityBundle.activity_id == activity_id,
            ).delete(synchronize_session="fetch")
        self.db.commit()
