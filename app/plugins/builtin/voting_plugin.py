from __future__ import annotations

from copy import deepcopy
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


PLUGIN = VotingPlugin()
