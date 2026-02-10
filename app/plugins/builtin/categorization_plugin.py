from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from app.data.activity_bundle_manager import ActivityBundleManager
from app.plugins.base import ActivityPlugin, ActivityPluginManifest, TransferSourceResult


class CategorizationPlugin(ActivityPlugin):
    manifest = ActivityPluginManifest(
        tool_type="categorization",
        label="Bucketing / Categorization",
        description="Group ideas into facilitator-defined buckets and keep a portable categorized output.",
        default_config={
            "mode": "FACILITATOR_LIVE",
            "items": [],
            "buckets": [],
            "agreement_threshold": 0.60,
            "minimum_ballots": 1,
            "private_until_reveal": True,
            "allow_unsorted_submission": True,
        },
    )

    def open_activity(self, context, input_bundle=None) -> None:
        if not input_bundle:
            return None

        config = dict(context.activity.config or {})
        existing_items = config.get("items")
        if isinstance(existing_items, list) and existing_items:
            return None

        seeded_items = self._seed_items_from_bundle(input_bundle)
        if not seeded_items:
            return None

        config["items"] = seeded_items
        context.activity.config = config
        context.db.add(context.activity)
        context.db.commit()
        return None

    def close_activity(self, context) -> Optional[Dict[str, Any]]:
        items = self._build_items(context)
        bundle = ActivityBundleManager(context.db).finalize_output_bundle(
            context.meeting.meeting_id,
            context.activity.activity_id,
            items,
            metadata={"source": "categorization"},
        )
        return {"bundle_id": bundle.bundle_id, "items": bundle.items}

    def snapshot_activity(self, context) -> Optional[Dict[str, Any]]:
        items = self._build_items(context)
        return {"items": items, "metadata": {"source": "categorization", "draft": True}}

    def get_transfer_source(
        self,
        context,
        include_comments: bool = True,
    ) -> Optional[TransferSourceResult]:
        return TransferSourceResult(items=self._build_items(context), source="categorization")

    def get_transfer_count(self, context) -> Optional[int]:
        return len(self._build_items(context))

    @staticmethod
    def _seed_items_from_bundle(input_bundle) -> List[Dict[str, Any]]:
        items = list(getattr(input_bundle, "items", []) or [])
        metadata = dict(getattr(input_bundle, "bundle_metadata", {}) or {})
        include_comments = bool(metadata.get("include_comments", False))
        comments_by_parent = metadata.get("comments_by_parent", {}) or {}

        seeded: List[Dict[str, Any]] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            content = str(entry.get("content", "")).strip()
            if not content:
                continue
            if include_comments and comments_by_parent and entry.get("id") is not None:
                content = CategorizationPlugin._append_comments_to_content(
                    entry.get("id"),
                    content,
                    comments_by_parent,
                )

            seeded.append(
                {
                    "id": entry.get("id"),
                    "content": content,
                    "submitted_name": entry.get("submitted_name"),
                    "parent_id": entry.get("parent_id"),
                    "metadata": dict(entry.get("metadata") or {}),
                    "source": dict(entry.get("source") or {}),
                }
            )
        return seeded

    @staticmethod
    def _append_comments_to_content(
        idea_id: Any,
        content: str,
        comments_by_parent: Dict[str, Any],
    ) -> str:
        key = str(idea_id)
        comments = comments_by_parent.get(key) or []
        if not isinstance(comments, list):
            return content

        comment_texts = []
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            text = str(comment.get("content", "")).strip()
            if text:
                comment_texts.append(text)
        if not comment_texts:
            return content
        return f"{content} (Comments: {'; '.join(comment_texts)})"

    @staticmethod
    def _build_items(context) -> List[Dict[str, Any]]:
        config = dict(context.activity.config or {})
        raw_items = config.get("items", [])
        built: List[Dict[str, Any]] = []

        if isinstance(raw_items, str):
            raw_items = [line.strip() for line in raw_items.splitlines() if line.strip()]

        if isinstance(raw_items, list):
            for index, entry in enumerate(raw_items):
                if isinstance(entry, str):
                    content = entry.strip()
                    if not content:
                        continue
                    built.append(
                        {
                            "id": f"{context.activity.activity_id}:item-{index + 1}",
                            "content": content,
                            "metadata": {
                                "categorization": {
                                    "bucket_id": "UNSORTED",
                                    "bucket_title": "Unsorted",
                                }
                            },
                            "source": {
                                "meeting_id": context.meeting.meeting_id,
                                "activity_id": context.activity.activity_id,
                            },
                        }
                    )
                    continue
                if isinstance(entry, dict):
                    base = deepcopy(entry)
                    content = str(base.get("content", "")).strip()
                    if not content:
                        continue
                    if not isinstance(base.get("metadata"), dict):
                        base["metadata"] = {}
                    if not isinstance(base.get("source"), dict):
                        base["source"] = {}
                    base["source"].setdefault("meeting_id", context.meeting.meeting_id)
                    base["source"].setdefault("activity_id", context.activity.activity_id)
                    base["metadata"].setdefault(
                        "categorization",
                        {"bucket_id": "UNSORTED", "bucket_title": "Unsorted"},
                    )
                    built.append(base)
        return built


PLUGIN = CategorizationPlugin()
