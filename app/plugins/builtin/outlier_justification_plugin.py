"""Per-viewer outlier justification activity (Delphi).

Canary: Plainspoken Marmot

DEPRECATED (kept for reference, not used by the shipped Delphi method): the Delphi
comment step is now the *generic* brainstorming activity configured as a comment
surface (`seed_from_input` + `comment_scope=selected`), demonstrating that
orchestration obviates custom activities. See
`plans/subplans/DELPHI_GENERIC_COMMENT.md`. This module and its router/manager/model
remain only as a deprecated reference; `orchestrations/delphi.json` no longer
references `outlier_justification`.

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

        # Adaptive controlled feedback: if the facilitator chose how many
        # least-converged ideas to open for comments at the prior round gate, apply
        # that decision here so every participant comments on the same selected set
        # rather than only their own outlier flags.
        self._apply_selected_comment_decision(context, config, seed)

        context.activity.config = config
        context.db.add(context.activity)
        context.db.commit()
        return None

    def _apply_selected_comment_decision(
        self, context, config: Dict[str, Any], seed: List[Dict[str, Any]]
    ) -> None:
        """Project the facilitator's selected-comment-count onto this activity.

        Reads the **same round's** in-round facilitator-decision bundle for
        `selected_comment_count` (the count chosen between ranking and commenting).
        When set, switches the activity into `selected_items` mode and seeds the
        top-N least-converged ideas (count 0 / "skip_comments" → empty queue, a
        soft skip to reranking). When no decision is recorded, the activity stays in
        its default outlier-only mode.
        """
        policy = (config.get("feedback_policy") or {})
        if not isinstance(policy, dict) or not policy:
            return
        orchestration = config.get("_orchestration") or {}
        try:
            round_index = int(orchestration.get("round_index", 0) or 0)
        except (TypeError, ValueError):
            round_index = 0

        count = self._selected_comment_count_for_round(context, round_index)
        if count is None:
            return

        from app.services.delphi_feedback_policy import build_delphi_feedback_selection

        # Score over the seed we just built (the just-ranked round output),
        # ordering ideas by disagreement, then keep the facilitator's count.
        ranked = build_delphi_feedback_selection(
            {
                "items": [
                    {
                        "content": entry.get("content"),
                        "metadata": {
                            "rank_order_voting": {"option_id": entry.get("option_id")},
                            "delphi": {
                                "median": entry.get("median"),
                                "iqr": entry.get("iqr"),
                            },
                        },
                    }
                    for entry in seed
                ]
            },
            policy,
        )
        max_selectable = int(ranked.get("max_selectable_count") or 0)
        count = max(0, min(int(count), max_selectable))
        ordered_keys = [row["item_key"] for row in ranked.get("items") or []]
        chosen_keys = ordered_keys[:count]
        seed_by_option = {entry.get("option_id"): entry for entry in seed}
        selected_items = [
            seed_by_option[key] for key in chosen_keys if key in seed_by_option
        ]

        config["comment_scope"] = "selected_items"
        config["selected_comment_items"] = selected_items

    @staticmethod
    def _selected_comment_count_for_round(context, round_index: int):
        """The comment count from this round's in-round decision, or None.

        Scans the round's facilitator-decision output bundles (newest first) for
        the in-round "how many ideas to open?" choice: a `skip_comments` choice
        means zero; otherwise the recorded `selected_comment_count`. The boundary
        round-gate bundle (continue/conclude, no count) is ignored.
        """
        from app.models.activity_bundle import ActivityBundle

        bundles = (
            context.db.query(ActivityBundle)
            .filter(
                ActivityBundle.meeting_id == context.meeting.meeting_id,
                ActivityBundle.round_index == round_index,
                ActivityBundle.kind == "output",
            )
            .order_by(ActivityBundle.id.desc())
            .all()
        )
        for bundle in bundles:
            metadata = dict(bundle.bundle_metadata or {})
            if metadata.get("source") != "facilitator_decision":
                continue
            if metadata.get("chosen") == "skip_comments":
                return 0
            if "selected_comment_count" in metadata:
                try:
                    return int(metadata["selected_comment_count"])
                except (TypeError, ValueError):
                    return None
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
