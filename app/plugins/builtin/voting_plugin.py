from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, Optional

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.meeting import AgendaActivity, Meeting
from app.plugins.base import ActivityPlugin, ActivityPluginManifest, TransferSourceResult
from app.services.voting_manager import VotingManager


class VotingPlugin(ActivityPlugin):
    manifest = ActivityPluginManifest(
        tool_type="voting",
        label="Dot Voting",
        description="Let participants distribute multiple picks across ideas to prioritise options.",
        default_config={
            "vote_type": "dot",
            "options": ["Edit vote option here"],
            "max_votes": 5,
            "max_votes_per_option": 5,
            "allow_retract": True,
            "show_results_immediately": False,
            "randomize_participant_order": False,
        },
        collaboration_patterns=["Evaluate", "Build Consensus"],
        use_cases=[
            "Prioritizing ideas or options after a brainstorming or categorization phase",
            "Quick temperature checks to gauge group sentiment on proposals",
            "Building consensus by revealing collective preferences transparently",
            "Narrowing a large set of options to a manageable shortlist for deeper evaluation",
            "Final confirmation polls to validate group commitment to a decision",
        ],
        when_to_use=(
            "Use when the group needs to evaluate or prioritize a set of options "
            "without requiring a complete ordering. Best suited after Generate or "
            "Organize phases to converge on top priorities. Dot voting is fast and "
            "intuitive, making it ideal for time-constrained sessions or groups "
            "unfamiliar with formal ranking methods. Enable randomized option order "
            "when primacy/recency bias is a concern."
        ),
        when_not_to_use=(
            "Not ideal when complete preference orderings are needed or when the "
            "group must weigh trade-offs across multiple criteria. Avoid for small "
            "option sets (fewer than 3) where rank-order voting provides richer "
            "information. Not suitable when the group is still in a divergent "
            "ideation phase."
        ),
        group_size_range={"min": 2, "max": 100},
        typical_duration_minutes={"min": 3, "max": 15},
        bias_mitigation=[
            "Randomized option order prevents primacy and recency bias, ensuring "
            "options listed first or last do not receive disproportionate votes",
            "Hidden results mode prevents bandwagon effects and social conformity "
            "by concealing vote totals until the facilitator reveals them",
            "Multi-vote allocation (dot voting) reduces the impact of single-issue "
            "voters by distributing influence across preferences",
        ],
        thinklets=[
            "StrawPoll (temperature check — quick single-round vote to gauge sentiment)",
            "FastFocus (multi-vote prioritisation — distribute vote budget across options)",
        ],
        input_requirements=(
            "Requires a set of options to vote on. Options can be manually entered "
            "or automatically populated from a prior activity (brainstorming or "
            "categorization output) via the activity transfer pipeline."
        ),
        output_characteristics=(
            "Ranked list of options with vote counts and per-option metadata. "
            "Output feeds into rank-order voting for deeper evaluation or into "
            "categorization for thematic grouping of top-voted items."
        ),
    )

    def open_activity(self, context, input_bundle=None) -> None:
        if not input_bundle:
            return None
        config = dict(context.activity.config or {})
        if config.get("options"):
            return None
        items = input_bundle.items or []
        options = [
            entry
            for entry in items
            if isinstance(entry, dict) and str(entry.get("content", "")).strip()
        ]
        if not options:
            return None

        sanitized_options = []
        for entry in options:
            sanitized = self._sanitize_option_entry(entry)
            if sanitized:
                sanitized_options.append(sanitized)
        if not sanitized_options:
            return None

        VotingManager(context.db).reset_activity_state(
            context.meeting.meeting_id, context.activity.activity_id, clear_bundles=True
        )
        config["options"] = sanitized_options
        context.activity.config = config
        context.db.add(context.activity)
        context.db.commit()
        return None

    @staticmethod
    def _sanitize_option_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(entry, dict):
            return None
        sanitized: Dict[str, Any] = {}
        for key in ("id", "content", "submitted_name", "parent_id", "created_at"):
            if key in entry:
                sanitized[key] = entry.get(key)
        metadata = dict(entry.get("metadata") or {})
        metadata.pop("votes", None)
        metadata.pop("option_id", None)
        voting_meta = metadata.get("voting")
        if isinstance(voting_meta, dict):
            voting_meta.pop("votes", None)
            voting_meta.pop("option_id", None)
            if voting_meta:
                metadata["voting"] = voting_meta
            else:
                metadata.pop("voting", None)
        sanitized["metadata"] = metadata
        sanitized["source"] = dict(entry.get("source") or {})
        return sanitized

    def close_activity(self, context) -> Optional[Dict[str, Any]]:
        meeting: Meeting = context.meeting
        activity: AgendaActivity = context.activity
        items = self._build_items(context, meeting, activity)
        bundle = ActivityBundleManager(context.db).finalize_output_bundle(
            meeting.meeting_id,
            activity.activity_id,
            items,
            metadata={"source": "voting"},
        )
        return {"bundle_id": bundle.bundle_id, "items": bundle.items}

    def snapshot_activity(self, context) -> Optional[Dict[str, Any]]:
        meeting: Meeting = context.meeting
        activity: AgendaActivity = context.activity
        items = self._build_items(context, meeting, activity)
        return {"items": items, "metadata": {"source": "voting", "draft": True}}

    def get_transfer_source(
        self,
        context,
        include_comments: bool = True,
    ) -> Optional[TransferSourceResult]:
        meeting: Meeting = context.meeting
        activity: AgendaActivity = context.activity
        items = self._build_items(context, meeting, activity)
        for item in items:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            metadata = item.get("metadata")
            voting_meta = metadata.get("voting") if isinstance(metadata, dict) else {}
            votes = 0
            if isinstance(voting_meta, dict):
                try:
                    votes = int(voting_meta.get("votes") or 0)
                except (TypeError, ValueError):
                    votes = 0
            item["content"] = self._append_votes_to_content(content, votes)
        return TransferSourceResult(items=items, source="voting")

    def get_transfer_count(self, context) -> Optional[int]:
        meeting: Meeting = context.meeting
        activity: AgendaActivity = context.activity
        items = self._build_items(context, meeting, activity)
        return len(items)

    @staticmethod
    def _build_items(
        context, meeting: Meeting, activity: AgendaActivity
    ) -> list[dict[str, Any]]:
        voting_manager = VotingManager(context.db)
        options = voting_manager._extract_options(activity)
        totals = voting_manager.aggregate_totals(meeting.meeting_id, activity.activity_id)

        items_with_keys: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for option in options:
            base: dict[str, Any]
            if option.raw_item:
                base = deepcopy(option.raw_item)
            else:
                base = {"content": option.label}

            if not base.get("content"):
                base["content"] = option.label

            if not isinstance(base.get("metadata"), dict):
                base["metadata"] = {}
            if not isinstance(base.get("source"), dict):
                base["source"] = {}
            base["source"].setdefault("meeting_id", meeting.meeting_id)
            base["source"].setdefault("activity_id", activity.activity_id)

            votes = totals.get(option.option_id, 0)
            base["metadata"]["votes"] = votes
            base["metadata"]["voting"] = {
                "option_id": option.option_id,
                "votes": votes,
            }
            sort_label = option.label or str(base.get("content") or "")
            sort_key = (-votes, sort_label.casefold(), sort_label, option.option_id)
            items_with_keys.append((sort_key, base))

        items_with_keys.sort(key=lambda entry: entry[0])
        items: list[dict[str, Any]] = []
        for index, (_, base) in enumerate(items_with_keys, start=1):
            voting_meta = base.get("metadata", {}).get("voting")
            if isinstance(voting_meta, dict):
                voting_meta["rank"] = index
            items.append(base)

        return items

    @staticmethod
    def _append_votes_to_content(content: str, votes: int) -> str:
        base = re.sub(r"\s+\(Votes:\s*\d+\)\s*$", "", str(content or "").strip())
        return f"{base} (Votes: {max(int(votes or 0), 0)})"


PLUGIN = VotingPlugin()
