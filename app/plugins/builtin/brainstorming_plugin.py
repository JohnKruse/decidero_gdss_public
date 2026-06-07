"""Tangerine Larynx: brainstorming lifecycle is DP3 idempotent; see docs/THINKLET_AUDIT.md."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.config.loader import get_brainstorming_defaults
from app.data.activity_bundle_manager import serialize_idea
from app.models.idea import Idea
from app.plugins.base import ActivityPlugin, ActivityPluginManifest, TransferSourceResult
from app.utils.user_colors import get_user_color


_BRAINSTORMING_DEFAULTS = get_brainstorming_defaults()


class BrainstormingPlugin(ActivityPlugin):
    manifest = ActivityPluginManifest(
        tool_type="brainstorming",
        label="Brainstorming",
        description="Capture ideas quickly and surface them to the group in real-time.",
        default_config={
            "allow_anonymous": _BRAINSTORMING_DEFAULTS.get("allow_anonymous", False),
            "allow_subcomments": _BRAINSTORMING_DEFAULTS.get(
                "allow_subcomments", False
            ),
            "auto_jump_new_ideas": _BRAINSTORMING_DEFAULTS.get(
                "auto_jump_new_ideas", True
            ),
        },
        reliability_policy={
            "submit_idea": {
                "retryable_statuses": [429, 502, 503, 504],
                "max_retries": 3,
                "base_delay_ms": 400,
                "max_delay_ms": 2500,
                "jitter_ratio": 0.25,
                "idempotency_header": "X-Idempotency-Key",
            }
        },
        collaboration_patterns=["Generate", "Clarify"],
        use_cases=[
            "Divergent idea generation for new topics or open-ended questions",
            "Gathering diverse perspectives on a problem from all participants",
            "Building on others' contributions with sub-comments (Clarify pattern)",
            "Anonymous ideation to reduce status bias and evaluation apprehension",
            "Extracting unshared knowledge in cross-functional teams (hidden profiles)",
        ],
        when_to_use=(
            "Use when the group needs to generate a large volume of ideas without "
            "premature evaluation. Best suited for the opening phase of a collaborative "
            "session. Enable anonymous mode when power asymmetry exists or when "
            "participants may self-censor due to organizational politics. Enable "
            "sub-comments when the group needs to clarify or annotate ideas inline."
        ),
        when_not_to_use=(
            "Not ideal when ideas have already been collected elsewhere and need "
            "evaluation rather than generation. Avoid when the group needs structured "
            "convergence or prioritization; use categorization or voting instead."
        ),
        group_size_range={"min": 2, "max": 100},
        typical_duration_minutes={"min": 5, "max": 30},
        bias_mitigation=[
            "Anonymous mode prevents anchoring on authority figures and reduces "
            "evaluation apprehension (HiPPO effect mitigation)",
            "Simultaneous electronic submission eliminates production blocking, "
            "allowing all participants to contribute at the speed of thought",
            "Sub-comments allow in-context clarification without interrupting "
            "the generation flow or creating verbal dominance",
        ],
        thinklets=[
            "FreeBrainstorm (anonymous, parallel — maximises idea volume)",
            "LeafHopper (sub-comments for inline Clarify without interruption)",
        ],
        input_requirements=(
            "None required. Can optionally receive a seed prompt or topic framing "
            "to focus ideation."
        ),
        output_characteristics=(
            "Unstructured list of ideas with optional sub-comments and author "
            "metadata. Output feeds directly into categorization, voting, or "
            "rank-order voting activities via the activity transfer pipeline."
        ),
    )

    def open_activity(self, context, input_bundle=None) -> None:
        """Brainstorming needs no setup by default. When configured with
        ``seed_from_input`` it instead seeds its idea list from the input bundle —
        a generic capability any method can use (here: a Delphi comment step that
        shows the ranked ideas and opens a facilitator-chosen subset for comment).

        All behavior is config-driven; there is no method-specific logic here.
        """
        config = dict(context.activity.config or {})
        if not config.get("seed_from_input"):
            return None
        if input_bundle is None:
            return None
        self._seed_from_input(context, config, input_bundle)
        return None

    @staticmethod
    def _seed_from_input(context, config, input_bundle) -> None:
        """Seed idea rows from the input bundle, in group-vote order, annotated for
        display (group median/IQR/agreement band/rank) and flagged ``commentable``.

        The commentable subset is the facilitator's in-round choice (count of
        least-converged items). The Delphi scoring lives in
        ``app/services/delphi_feedback_policy.py`` — a configured selection
        strategy — not in this activity.
        """
        from app.models.idea import Idea
        from app.services.delphi_feedback_policy import (
            DEFAULT_FEEDBACK_POLICY,
            build_delphi_feedback_selection,
            selected_comment_count_for_round,
        )

        db = context.db
        activity = context.activity
        meeting = context.meeting

        # Idempotent: do not re-seed if this activity already has ideas.
        existing = (
            db.query(Idea)
            .filter(Idea.meeting_id == meeting.meeting_id, Idea.activity_id == activity.activity_id)
            .first()
        )
        if existing is not None:
            return None

        items = list(getattr(input_bundle, "items", None) or [])
        if not items:
            return None

        policy = config.get("feedback_policy")
        if not isinstance(policy, dict) or not policy:
            policy = DEFAULT_FEEDBACK_POLICY

        # Disagreement scoring (for agreement bands + the commentable subset).
        selection = build_delphi_feedback_selection({"items": items}, policy)
        rows_by_key = {row["item_key"]: row for row in selection.get("items") or []}
        ordered_by_dispute = [row["item_key"] for row in selection.get("items") or []]

        # The facilitator's in-round count picks how many disputed items to open.
        orchestration = config.get("_orchestration") or {}
        try:
            round_index = int(orchestration.get("round_index", 0) or 0)
        except (TypeError, ValueError):
            round_index = 0
        count = selected_comment_count_for_round(db, meeting.meeting_id, round_index)
        if count is None:
            # No recorded decision: fall back to the policy's suggested count.
            count = int(selection.get("suggested_count") or 0)
        max_selectable = int(selection.get("max_selectable_count") or 0)
        count = max(0, min(count, max_selectable))
        commentable_keys = set(ordered_by_dispute[:count])

        def _option_id(item):
            meta = item.get("metadata") if isinstance(item, dict) else {}
            ro = (meta or {}).get("rank_order_voting") if isinstance(meta, dict) else {}
            return (ro or {}).get("option_id") or item.get("id") or item.get("content")

        def _median(item):
            meta = item.get("metadata") if isinstance(item, dict) else {}
            delphi = (meta or {}).get("delphi") if isinstance(meta, dict) else {}
            try:
                return float((delphi or {}).get("median"))
            except (TypeError, ValueError):
                return float("inf")

        # Display order = group vote order (best group median first).
        display = sorted(
            items,
            key=lambda it: (_median(it), str(it.get("content") or "").casefold()),
        )
        for position, item in enumerate(display, start=1):
            key = _option_id(item)
            row = rows_by_key.get(key, {})
            db.add(
                Idea(
                    content=item.get("content") or str(key),
                    meeting_id=meeting.meeting_id,
                    activity_id=activity.activity_id,
                    user_id=None,
                    idea_metadata={
                        "seeded": True,
                        "stable_key": str(key).split(":", 1)[1] if ":" in str(key) else str(key),
                        "group_rank": position,
                        "group_median": row.get("median"),
                        "group_iqr": row.get("iqr"),
                        "agreement_band": row.get("band"),
                        "commentable": key in commentable_keys,
                    },
                )
            )
        db.commit()
        return None

    def close_activity(self, context) -> Optional[Dict[str, Any]]:
        ideas = (
            context.db.query(Idea)
            .filter(
                Idea.meeting_id == context.meeting.meeting_id,
                Idea.activity_id == context.activity.activity_id,
            )
            .order_by(Idea.timestamp)
            .all()
        )
        items = [serialize_idea(idea) for idea in ideas]
        bundle = context.finalize_output_bundle(
            items,
            metadata={"source": "brainstorming"},
        )
        return {"bundle_id": bundle.bundle_id, "items": bundle.items}

    def snapshot_activity(self, context) -> Optional[Dict[str, Any]]:
        ideas = (
            context.db.query(Idea)
            .filter(
                Idea.meeting_id == context.meeting.meeting_id,
                Idea.activity_id == context.activity.activity_id,
            )
            .order_by(Idea.timestamp)
            .all()
        )
        items = [serialize_idea(idea) for idea in ideas]
        return {"items": items, "metadata": {"source": "brainstorming", "draft": True}}

    def get_transfer_source(
        self,
        context,
        include_comments: bool = True,
    ) -> Optional[TransferSourceResult]:
        ideas = (
            context.db.query(Idea)
            .filter(
                Idea.meeting_id == context.meeting.meeting_id,
                Idea.activity_id == context.activity.activity_id,
            )
            .order_by(Idea.timestamp)
            .all()
        )
        items = [_serialize_transfer_idea(idea) for idea in ideas]
        if not include_comments:
            items = [item for item in items if item.get("parent_id") is None]
        return TransferSourceResult(items=items, source="ideas")


def _serialize_transfer_idea(idea: Idea) -> Dict[str, Any]:
    return {
        "id": idea.id,
        "content": idea.content,
        "parent_id": idea.parent_id,
        "timestamp": idea.timestamp.isoformat() if idea.timestamp else None,
        "updated_at": idea.updated_at.isoformat() if idea.updated_at else None,
        "meeting_id": idea.meeting_id,
        "activity_id": idea.activity_id,
        "user_id": idea.user_id,
        "user_color": get_user_color(user=idea.author),
        "user_avatar_key": getattr(getattr(idea, "author", None), "avatar_key", None),
        "user_avatar_icon_path": getattr(
            getattr(idea, "author", None), "avatar_icon_path", None
        ),
        "submitted_name": idea.submitted_name,
        "metadata": idea.idea_metadata or {},
        "source": {
            "meeting_id": idea.meeting_id,
            "activity_id": idea.activity_id,
        },
    }


PLUGIN = BrainstormingPlugin()
