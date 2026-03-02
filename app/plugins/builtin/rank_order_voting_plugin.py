from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import UserRole
from app.plugins.base import ActivityPlugin, ActivityPluginManifest, TransferSourceResult
from app.services.rank_order_voting_manager import RankOrderVotingManager


class RankOrderVotingPlugin(ActivityPlugin):
    manifest = ActivityPluginManifest(
        tool_type="rank_order_voting",
        label="Rank Order Voting",
        description="Rank ideas from most to least preferred using Borda-style aggregation.",
        default_config={
            "ideas": [],
            "randomize_order": True,
            "show_results_immediately": False,
            "allow_reset": True,
        },
        reliability_policy={
            "submit_ranking": {
                "retryable_statuses": [429, 502, 503, 504],
                "max_retries": 2,
                "base_delay_ms": 300,
                "max_delay_ms": 1500,
                "jitter_ratio": 0.2,
                "idempotency_header": "X-Idempotency-Key",
            },
            "reset_ranking": {
                "retryable_statuses": [429, 502, 503, 504],
                "max_retries": 2,
                "base_delay_ms": 300,
                "max_delay_ms": 1500,
                "jitter_ratio": 0.2,
                "idempotency_header": "X-Idempotency-Key",
            },
        },
        collaboration_patterns=["Evaluate"],
        use_cases=[
            "Formal prioritization requiring complete orderings from every participant",
            "Multi-criteria evaluation where relative position matters more than binary choice",
            "Borda-count aggregation to produce a fair, balanced group ranking",
            "Detecting disagreement via rank variance metrics to surface hidden conflicts",
            "Final prioritization of a shortlist after initial dot voting or categorization",
        ],
        when_to_use=(
            "Use when the group needs a rigorous, complete ordering of options "
            "rather than a simple vote count. Borda-style aggregation gives balanced "
            "weight to all preferences, making it ideal for high-stakes prioritization "
            "where every participant's full ranking matters. Best suited for moderate "
            "option sets (3-15 items) where participants can meaningfully compare all "
            "options. Enable randomized order to reduce anchoring effects."
        ),
        when_not_to_use=(
            "Not ideal for very large option sets (>15 items) where full ranking "
            "becomes cognitively burdensome. Avoid when a quick temperature check "
            "suffices — dot voting is faster and more intuitive for simple "
            "prioritization. Not suitable when the group is still generating or "
            "organizing ideas."
        ),
        group_size_range={"min": 2, "max": 50},
        typical_duration_minutes={"min": 5, "max": 20},
        bias_mitigation=[
            "Borda-count aggregation gives balanced weight to all rank positions, "
            "preventing tyranny of the majority on a single top pick",
            "Randomized presentation order reduces anchoring bias and prevents the "
            "first-listed option from receiving systematically higher rankings",
            "Rank variance metrics reveal hidden disagreement — low variance indicates "
            "genuine consensus while high variance exposes polarized preferences",
            "Complete orderings prevent strategic single-issue voting by requiring "
            "participants to express preferences across all options",
        ],
        thinklets=[
            "Borda Vote (rigorous rank aggregation — Borda-count scoring across all rankings)",
        ],
        input_requirements=(
            "Requires a set of options (ideas) to rank. Options can be manually "
            "entered or automatically populated from a prior activity (brainstorming, "
            "categorization, or dot voting output) via the activity transfer pipeline."
        ),
        output_characteristics=(
            "Fully ordered list with Borda scores, average ranks, rank variance, "
            "and top-choice share metrics per option. Output provides rich analytical "
            "data for facilitator debrief and can feed into further categorization "
            "or discussion activities."
        ),
    )

    def open_activity(self, context, input_bundle=None) -> None:
        if not input_bundle:
            return None
        config = dict(context.activity.config or {})
        if config.get("ideas"):
            return None

        items = input_bundle.items or []
        ideas: List[Dict[str, Any]] = []
        for entry in items:
            sanitized = self._sanitize_idea_entry(entry)
            if sanitized:
                ideas.append(sanitized)
        if not ideas:
            return None

        RankOrderVotingManager(context.db).reset_activity_state(
            context.meeting.meeting_id,
            context.activity.activity_id,
            clear_bundles=True,
        )
        config["ideas"] = ideas
        context.activity.config = config
        context.db.add(context.activity)
        context.db.commit()
        return None

    @staticmethod
    def _sanitize_idea_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(entry, dict):
            return None
        content = str(entry.get("content") or "").strip()
        if not content:
            return None

        sanitized: Dict[str, Any] = {}
        for key in ("id", "content", "submitted_name", "parent_id", "created_at"):
            if key in entry:
                sanitized[key] = entry.get(key)

        metadata = dict(entry.get("metadata") or {})
        metadata.pop("rank_order_voting", None)
        metadata.pop("borda_score", None)
        metadata.pop("avg_rank", None)
        metadata.pop("rank_variance", None)
        metadata.pop("top_choice_share", None)
        sanitized["metadata"] = metadata
        sanitized["source"] = dict(entry.get("source") or {})
        return sanitized

    def close_activity(self, context) -> Optional[Dict[str, Any]]:
        meeting: Meeting = context.meeting
        activity: AgendaActivity = context.activity
        items = self._build_items(context, include_metrics=True)
        bundle = ActivityBundleManager(context.db).finalize_output_bundle(
            meeting.meeting_id,
            activity.activity_id,
            items,
            metadata={"source": "rank_order_voting"},
        )
        return {"bundle_id": bundle.bundle_id, "items": bundle.items}

    def snapshot_activity(self, context) -> Optional[Dict[str, Any]]:
        items = self._build_items(context, include_metrics=False)
        return {
            "items": items,
            "metadata": {"source": "rank_order_voting", "draft": True},
        }

    def get_transfer_source(
        self,
        context,
        include_comments: bool = True,
    ) -> Optional[TransferSourceResult]:
        items = self._build_items(context, include_metrics=True)
        return TransferSourceResult(items=items, source="rank_order_voting")

    def get_transfer_count(self, context) -> Optional[int]:
        return len(self._build_items(context, include_metrics=False))

    @staticmethod
    def _build_items(context, *, include_metrics: bool) -> List[Dict[str, Any]]:
        meeting: Meeting = context.meeting
        activity: AgendaActivity = context.activity
        manager = RankOrderVotingManager(context.db)
        actor = getattr(context, "user", None) or getattr(meeting, "owner", None)
        if actor is None:
            class _SystemActor:
                user_id = "system"
                role = UserRole.ADMIN.value

            actor = _SystemActor()
        summary = manager.build_summary(
            meeting,
            activity.activity_id,
            user=actor,
            force_results=True,
            is_active_state=False,
            active_participant_count=0,
        )

        source_options = summary.get("results") if include_metrics else summary.get("options")
        options = list(source_options or summary.get("options") or [])
        source_by_option = {
            option.option_id: option.raw_item
            for option in manager._extract_options(activity)
        }

        built: List[Dict[str, Any]] = []
        for index, option in enumerate(options, start=1):
            option_id = str(option.get("option_id") or "")
            option_label = str(option.get("label") or "").strip()
            if not option_id or not option_label:
                continue

            raw_item = source_by_option.get(option_id)
            payload: Dict[str, Any] = deepcopy(raw_item) if raw_item else {"content": option_label}

            if not isinstance(payload.get("metadata"), dict):
                payload["metadata"] = {}
            if not isinstance(payload.get("source"), dict):
                payload["source"] = {}
            payload["source"].setdefault("meeting_id", meeting.meeting_id)
            payload["source"].setdefault("activity_id", activity.activity_id)

            ro_meta = dict(payload["metadata"].get("rank_order_voting") or {})
            ro_meta.update(
                {
                    "option_id": option_id,
                    "rank": index,
                }
            )
            if include_metrics:
                ro_meta.update(
                    {
                        "borda_score": option.get("borda_score"),
                        "avg_rank": option.get("avg_rank"),
                        "rank_variance": option.get("rank_variance"),
                        "top_choice_share": option.get("top_choice_share"),
                    }
                )
            payload["metadata"]["rank_order_voting"] = ro_meta
            built.append(payload)

        return built


PLUGIN = RankOrderVotingPlugin()
