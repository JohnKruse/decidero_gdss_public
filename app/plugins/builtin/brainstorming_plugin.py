from __future__ import annotations

from typing import Any, Dict, Optional

from app.config.loader import get_brainstorming_defaults
from app.data.activity_bundle_manager import ActivityBundleManager, serialize_idea
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
    )

    def open_activity(self, context, input_bundle=None) -> None:
        # Brainstorming does not require setup; input bundles are optional.
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
        bundle = ActivityBundleManager(context.db).finalize_output_bundle(
            context.meeting.meeting_id,
            context.activity.activity_id,
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
