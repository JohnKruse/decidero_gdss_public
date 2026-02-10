from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Dict, List, Optional

from app.data.activity_bundle_manager import ActivityBundleManager
from app.plugins.base import ActivityPlugin, ActivityPluginManifest, TransferSourceResult
from app.services.categorization_manager import CategorizationManager


class CategorizationPlugin(ActivityPlugin):
    manifest = ActivityPluginManifest(
        tool_type="categorization",
        label="Bucketing / Categorization",
        description="Group ideas into facilitator-defined buckets and keep a portable categorized output.",
        default_config={
            "mode": "FACILITATOR_LIVE",
            "items": [],
            "buckets": [],
            "single_assignment_only": True,
            "agreement_threshold": 0.60,
            "margin_threshold": 0.15,
            "minimum_ballots": 1,
            "tie_policy": "TIE_UNRESOLVED",
            "missing_vote_handling": "ignore",
            "private_until_reveal": True,
            "allow_unsorted_submission": True,
        },
    )

    def open_activity(self, context, input_bundle=None) -> None:
        config = dict(context.activity.config or {})
        seeded_from_bundle = False

        existing_items = config.get("items")
        if input_bundle and not (isinstance(existing_items, list) and existing_items):
            seeded_items = self._seed_items_from_bundle(input_bundle)
            if seeded_items:
                config["items"] = seeded_items
                seeded_from_bundle = True

        if seeded_from_bundle:
            CategorizationManager(context.db).reset_activity_state(
                context.meeting.meeting_id,
                context.activity.activity_id,
                clear_bundles=True,
            )

        context.activity.config = config
        context.db.add(context.activity)
        context.db.commit()
        context.db.refresh(context.activity)

        CategorizationManager(context.db).seed_activity(
            meeting_id=context.meeting.meeting_id,
            activity=context.activity,
            actor_user_id=getattr(getattr(context, "user", None), "user_id", None),
        )
        return None

    def close_activity(self, context) -> Optional[Dict[str, Any]]:
        manager = CategorizationManager(context.db)
        state = manager.build_state(context.meeting.meeting_id, context.activity.activity_id)
        config = dict(context.activity.config or {})
        mode = str(config.get("mode") or "FACILITATOR_LIVE").upper()
        threshold = self._as_float(
            config.get("agreement_threshold", config.get("agree_threshold", 0.60)),
            fallback=0.60,
        )
        minimum_ballots = self._as_int(
            config.get("minimum_ballots", config.get("min_ballots", 1)),
            fallback=1,
        )
        metrics = (
            manager.compute_agreement_metrics(
                meeting_id=context.meeting.meeting_id,
                activity_id=context.activity.activity_id,
                agreement_threshold=threshold,
                minimum_ballots=minimum_ballots,
            )
            if mode == "PARALLEL_BALLOT"
            else {}
        )
        final_assignments = manager.list_final_assignments(
            context.meeting.meeting_id, context.activity.activity_id
        )
        items = self._build_items(context)
        bucket_titles = {
            str(bucket.get("category_id")): str(bucket.get("title") or "")
            for bucket in state.get("buckets", [])
        }
        grouped_item_ids: Dict[str, List[str]] = defaultdict(list)
        for item in items:
            item_id = str(item.get("id") or "")
            category_id = (
                final_assignments.get(item_id)
                or state.get("assignments", {}).get(item_id)
                or "UNSORTED"
            )
            grouped_item_ids[category_id].append(item_id)
            metadata = dict(item.get("metadata") or {})
            categorization_meta = dict(metadata.get("categorization") or {})
            categorization_meta.update(
                {
                    "bucket_id": category_id,
                    "bucket_title": bucket_titles.get(category_id, category_id),
                }
            )
            if item_id in metrics:
                categorization_meta["agreement"] = metrics[item_id]
            metadata["categorization"] = categorization_meta
            item["metadata"] = metadata

        categories_output = []
        ordered_buckets = sorted(
            state.get("buckets", []),
            key=lambda bucket: int(bucket.get("order_index", 0)),
        )
        for bucket in ordered_buckets:
            category_id = str(bucket.get("category_id") or "")
            categories_output.append(
                {
                    "category_id": category_id,
                    "title": bucket.get("title"),
                    "description": bucket.get("description"),
                    "item_ids": grouped_item_ids.get(category_id, []),
                }
            )

        finalization_metadata = dict(config.get("finalization_metadata") or {})
        if not finalization_metadata:
            finalization_metadata = {
                "mode": mode,
                "agreement_threshold": threshold,
                "minimum_ballots": minimum_ballots,
            }
        bundle = ActivityBundleManager(context.db).finalize_output_bundle(
            context.meeting.meeting_id,
            context.activity.activity_id,
            items,
            metadata={
                "source": "categorization",
                "categories": categories_output,
                "finalization_metadata": finalization_metadata,
                "agreement_metrics": metrics,
                "final_assignments": final_assignments,
            },
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
    def _as_float(raw: Any, fallback: float) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(fallback)

    @staticmethod
    def _as_int(raw: Any, fallback: int) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return int(fallback)

    @staticmethod
    def _seed_items_from_bundle(input_bundle) -> List[Dict[str, Any]]:
        items = list(getattr(input_bundle, "items", []) or [])
        metadata = dict(getattr(input_bundle, "bundle_metadata", {}) or {})
        include_comments = bool(metadata.get("include_comments", False))
        comments_by_parent = metadata.get("comments_by_parent", {}) or {}
        if not isinstance(comments_by_parent, dict):
            comments_by_parent = {}

        # Fallback: derive parent->comments map from item rows when metadata is missing.
        if include_comments and not comments_by_parent:
            derived: Dict[str, List[Dict[str, Any]]] = {}
            for row in items:
                if not isinstance(row, dict):
                    continue
                parent_id = row.get("parent_id")
                if parent_id is None:
                    continue
                parent_key = str(parent_id)
                derived.setdefault(parent_key, []).append(row)
            comments_by_parent = derived

        seeded: List[Dict[str, Any]] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            # Categorization consumes idea rows only; comments are folded into parent content.
            if entry.get("parent_id") is not None:
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
        manager = CategorizationManager(context.db)
        state = manager.build_state(context.meeting.meeting_id, context.activity.activity_id)
        items = state.get("items", [])
        buckets = {
            str(bucket.get("category_id")): str(bucket.get("title") or "")
            for bucket in state.get("buckets", [])
        }
        assignments = dict(state.get("assignments") or {})
        final_assignments = manager.list_final_assignments(
            context.meeting.meeting_id, context.activity.activity_id
        )

        if items:
            built: List[Dict[str, Any]] = []
            for item in items:
                item_key = str(item.get("item_key") or "")
                if not item_key:
                    continue
                category_id = (
                    final_assignments.get(item_key)
                    or assignments.get(item_key)
                    or "UNSORTED"
                )
                metadata = deepcopy(item.get("metadata") or {})
                categorization = dict(metadata.get("categorization") or {})
                categorization.setdefault("bucket_id", category_id)
                categorization.setdefault("bucket_title", buckets.get(category_id, category_id))
                metadata["categorization"] = categorization
                source = deepcopy(item.get("source") or {})
                source.setdefault("meeting_id", context.meeting.meeting_id)
                source.setdefault("activity_id", context.activity.activity_id)
                built.append(
                    {
                        "id": item_key,
                        "content": item.get("content"),
                        "submitted_name": item.get("submitted_name"),
                        "metadata": metadata,
                        "source": source,
                    }
                )
            return built

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
