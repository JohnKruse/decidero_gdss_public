"""Per-viewer outlier justification activity (Delphi).

Canary: Plainspoken Marmot

The purpose-built replacement for the brainstorming placeholder at the Delphi
round's justification step. At open time it runs the Delphi aggregation over the
round's ranking output to derive, per item, the group median/IQR and the
per-participant outlier flags, and seeds that onto the activity config. The
manager (`OutlierJustificationManager`) then serves each participant only the
items they were flagged on, and accepts a comment-only rationale per flagged
item. At close time the collected rationales are finalized as the activity's
output bundle (the seed for the next round's anonymized cross-round display).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.meeting import AgendaActivity, Meeting
from app.plugins.base import ActivityPlugin, ActivityPluginManifest
from app.services.outlier_justification_manager import OutlierJustificationManager


class OutlierJustificationPlugin(ActivityPlugin):
    manifest = ActivityPluginManifest(
        tool_type="outlier_justification",
        label="Outlier Justification",
        description=(
            "Ask each participant flagged as a ranking outlier to explain their "
            "divergent positions, Delphi-style (comment-only, per-viewer queue)."
        ),
        default_config={"justification_seed": []},
        collaboration_patterns=["Build Consensus"],
        use_cases=[
            "Delphi feedback rounds where outlier participants justify divergent rankings",
            "Surfacing the reasoning behind disagreement before a re-vote",
        ],
        when_to_use=(
            "Use immediately after a ranking round in an iterative Delphi process, "
            "to collect rationales from the participants whose rankings fell outside "
            "the group's interquartile range. Each participant sees only the items "
            "they were flagged on."
        ),
        when_not_to_use=(
            "Not for open idea generation (use brainstorming) and not for collecting "
            "comments from everyone — only flagged outliers are queued. Not meaningful "
            "without a preceding ranking activity that produces per-participant votes."
        ),
        group_size_range={"min": 4, "max": 25},
        typical_duration_minutes={"min": 3, "max": 15},
        bias_mitigation=[
            "Peer-anonymous: the system routes each queue by identity but peers see "
            "only aggregated, unattributed rationales in the next round",
            "Comment-only on flagged items prevents agenda-stuffing or re-litigating "
            "the item set during justification",
        ],
        thinklets=[],
        input_requirements=(
            "Requires the prior ranking activity's output (items + per-participant "
            "votes), from which group statistics and outlier flags are derived."
        ),
        output_characteristics=(
            "Per-item collected rationales (unattributed), suitable for feeding the "
            "next round's cross-round justification display."
        ),
    )

    def open_activity(self, context, input_bundle=None) -> None:
        """Seed the per-item justification queue from the ranking output.

        Idempotent: a non-empty seed (set on a prior open) is left untouched.
        """
        config = dict(context.activity.config or {})
        if config.get("justification_seed"):
            return None
        if input_bundle is None:
            return None

        from app.services.bundle_transforms import get_bundle_transform_registry

        items = list(getattr(input_bundle, "items", None) or [])
        metadata = dict(getattr(input_bundle, "bundle_metadata", None) or {})

        # ranks_by_user per option, grouped exactly as the aggregation does.
        ranks_by_option: Dict[str, Dict[str, Any]] = {}
        for vote in metadata.get("votes") or []:
            opt_id = vote.get("option_id")
            u_id = vote.get("user_id")
            pos = vote.get("rank_position")
            if opt_id and u_id and pos is not None:
                ranks_by_option.setdefault(str(opt_id), {})[u_id] = int(pos)

        transform = get_bundle_transform_registry().get_transform(
            "delphi_statistical_aggregation"
        )
        aggregated = transform.transform({"items": items, "metadata": metadata}, {})

        seed: List[Dict[str, Any]] = []
        for item in aggregated.get("items") or []:
            item_meta = item.get("metadata") or {}
            option_id = str((item_meta.get("rank_order_voting") or {}).get("option_id") or "")
            if not option_id:
                continue
            delphi = item_meta.get("delphi") or {}
            seed.append(
                {
                    "option_id": option_id,
                    "content": item.get("content"),
                    "median": delphi.get("median"),
                    "iqr": delphi.get("iqr"),
                    "outlier_flags": delphi.get("outlier_flags") or {},
                    "ranks_by_user": ranks_by_option.get(option_id, {}),
                }
            )

        config["justification_seed"] = seed
        context.activity.config = config
        context.db.add(context.activity)
        context.db.commit()
        return None

    def close_activity(self, context) -> Optional[Dict[str, Any]]:
        """Finalize collected rationales as the output bundle, one item per
        ranked option that drew at least one rationale (unattributed)."""
        meeting: Meeting = context.meeting
        activity: AgendaActivity = context.activity
        manager = OutlierJustificationManager(context.db)
        grouped = manager.collected_by_option(meeting, activity)

        seed_by_option = {
            entry.get("option_id"): entry for entry in manager.comment_items(activity)
        }
        items: List[Dict[str, Any]] = []
        for option_id, rationales in grouped.items():
            entry = seed_by_option.get(option_id) or {}
            items.append(
                {
                    "content": entry.get("content") or option_id,
                    "metadata": {
                        "outlier_justification": {
                            "option_id": option_id,
                            "rationales": list(rationales),
                            "rationale_count": len(rationales),
                        }
                    },
                    "source": {
                        "meeting_id": meeting.meeting_id,
                        "activity_id": activity.activity_id,
                        "tool_type": self.manifest.tool_type,
                    },
                }
            )

        bundle = context.finalize_output_bundle(
            items,
            metadata={"source": "outlier_justification"},
        )
        return {"bundle_id": bundle.bundle_id, "items": bundle.items}

    def snapshot_activity(self, context) -> Optional[Dict[str, Any]]:
        manager = OutlierJustificationManager(context.db)
        grouped = manager.collected_by_option(context.meeting, context.activity)
        return {
            "items": [
                {
                    "content": option_id,
                    "metadata": {"outlier_justification": {"rationale_count": len(rationales)}},
                }
                for option_id, rationales in grouped.items()
            ],
            "metadata": {"source": "outlier_justification", "draft": True},
        }


PLUGIN = OutlierJustificationPlugin()
