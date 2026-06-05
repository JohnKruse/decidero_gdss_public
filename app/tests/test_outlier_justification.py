"""Tests for the per-viewer outlier justification activity (backend foundation)."""

from __future__ import annotations

import pytest

from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.plugins.builtin.outlier_justification_plugin import OutlierJustificationPlugin
from app.plugins.context import ActivityContext
from app.services.outlier_justification_manager import (
    JustificationError,
    OutlierJustificationManager,
)


def _user(db, uid):
    u = User(user_id=uid, login=uid, hashed_password="h", role=UserRole.PARTICIPANT.value)
    db.add(u)
    db.commit()
    return u


def _meeting(db, owner_id="owner"):
    owner = User(user_id=owner_id, login=owner_id, hashed_password="h", role=UserRole.ADMIN.value)
    meeting = Meeting(meeting_id="M-OJ-1", owner_id=owner_id, title="OJ")
    db.add_all([owner, meeting])
    db.commit()
    return meeting


def _activity(db, meeting, seed, activity_id="A-JUST", round_index=0):
    activity = AgendaActivity(
        activity_id=activity_id,
        meeting_id=meeting.meeting_id,
        tool_type="outlier_justification",
        title="Justify",
        order_index=1,
        tool_config_id=f"tc-{activity_id}",
        config={
            "justification_seed": seed,
            "_orchestration": {"logical_step_id": f"engine:{activity_id}", "round_index": round_index},
        },
    )
    db.add(activity)
    db.commit()
    return activity


# A seed: option o1 has u3 flagged as an outlier; o2 has nobody flagged.
_SEED = [
    {
        "option_id": "o1", "content": "Idea A", "median": 1.0, "iqr": 0.0,
        "outlier_flags": {"u1": False, "u2": False, "u3": True},
        "ranks_by_user": {"u1": 1, "u2": 1, "u3": 9},
    },
    {
        "option_id": "o2", "content": "Idea B", "median": 2.0, "iqr": 1.0,
        "outlier_flags": {"u1": False, "u2": False, "u3": False},
        "ranks_by_user": {"u1": 2, "u2": 2, "u3": 3},
    },
]


def test_queue_is_per_viewer_and_only_own_rank(db_session):
    meeting = _meeting(db_session)
    activity = _activity(db_session, meeting, _SEED)
    mgr = OutlierJustificationManager(db_session)

    flagged = mgr.queue_for(activity, "u3")
    assert [q["option_id"] for q in flagged] == ["o1"]
    assert flagged[0]["your_rank"] == 9
    assert flagged[0]["group_median"] == 1.0
    # No other participant's rank leaks into the payload.
    assert set(flagged[0]) == {"option_id", "content", "your_rank", "group_median", "group_iqr"}

    # A non-outlier participant has an empty queue.
    assert mgr.queue_for(activity, "u1") == []


def test_build_state_nothing_to_justify_and_submitted_flag(db_session):
    meeting = _meeting(db_session)
    activity = _activity(db_session, meeting, _SEED)
    u1, u3 = _user(db_session, "u1"), _user(db_session, "u3")
    mgr = OutlierJustificationManager(db_session)

    clear = mgr.build_state(meeting, activity, u1)
    assert clear["nothing_to_justify"] is True
    assert clear["submitted"] is False

    pending = mgr.build_state(meeting, activity, u3)
    assert pending["nothing_to_justify"] is False
    assert pending["submitted"] is False
    assert pending["items"][0]["rationale"] == ""

    mgr.submit_rationale(meeting, activity, u3, "o1", "I weighted long-term cost.")
    answered = mgr.build_state(meeting, activity, u3)
    assert answered["submitted"] is True
    assert answered["items"][0]["rationale"] == "I weighted long-term cost."


def test_submit_is_idempotent_upsert(db_session):
    meeting = _meeting(db_session)
    activity = _activity(db_session, meeting, _SEED)
    u3 = _user(db_session, "u3")
    mgr = OutlierJustificationManager(db_session)

    mgr.submit_rationale(meeting, activity, u3, "o1", "first")
    mgr.submit_rationale(meeting, activity, u3, "o1", "revised")
    rows = mgr._rationales(meeting, activity, "u3")
    assert len(rows) == 1
    assert rows[0].rationale == "revised"


def test_comment_only_rejects_non_queued_option(db_session):
    meeting = _meeting(db_session)
    activity = _activity(db_session, meeting, _SEED)
    u3 = _user(db_session, "u3")
    mgr = OutlierJustificationManager(db_session)

    # o2 is not flagged for u3; brand-new option ids are likewise rejected.
    with pytest.raises(JustificationError):
        mgr.submit_rationale(meeting, activity, u3, "o2", "not my outlier")
    with pytest.raises(JustificationError):
        mgr.submit_rationale(meeting, activity, u3, "o-new", "a new idea")


def test_collected_by_option_is_unattributed(db_session):
    meeting = _meeting(db_session)
    # Both u3 and u4 flagged on o1.
    seed = [{
        "option_id": "o1", "content": "Idea A", "median": 1.0, "iqr": 0.0,
        "outlier_flags": {"u3": True, "u4": True},
        "ranks_by_user": {"u3": 9, "u4": 8},
    }]
    activity = _activity(db_session, meeting, seed)
    u3, u4 = _user(db_session, "u3"), _user(db_session, "u4")
    mgr = OutlierJustificationManager(db_session)
    mgr.submit_rationale(meeting, activity, u3, "o1", "cost")
    mgr.submit_rationale(meeting, activity, u4, "o1", "risk")

    grouped = mgr.collected_by_option(meeting, activity)
    assert set(grouped["o1"]) == {"cost", "risk"}  # text only, no user_ids


# --- plugin lifecycle -------------------------------------------------------

class _StubBundle:
    def __init__(self, items, metadata):
        self.items = items
        self.bundle_metadata = metadata


def _ranking_bundle_with_outlier():
    # Four participants rank o1 at 1, the fifth at 9 — a clear IQR-rule outlier.
    items = [
        {"content": "Idea A", "metadata": {"rank_order_voting": {"option_id": "o1"}}},
        {"content": "Idea B", "metadata": {"rank_order_voting": {"option_id": "o2"}}},
    ]
    votes = []
    for uid, r1 in [("u1", 1), ("u2", 1), ("u3", 1), ("u4", 1), ("u5", 9)]:
        votes.append({"user_id": uid, "option_id": "o1", "rank_position": r1})
        votes.append({"user_id": uid, "option_id": "o2", "rank_position": 2})
    return _StubBundle(items, {"source": "rank_order_voting", "votes": votes})


def test_plugin_open_seeds_queue_from_ranking(db_session):
    meeting = _meeting(db_session)
    activity = _activity(db_session, meeting, seed=[])  # empty -> not yet seeded
    activity.config = {**activity.config, "justification_seed": []}
    db_session.commit()

    ctx = ActivityContext(db=db_session, meeting=meeting, activity=activity)
    OutlierJustificationPlugin().open_activity(ctx, input_bundle=_ranking_bundle_with_outlier())

    seed = (activity.config or {}).get("justification_seed")
    by_option = {e["option_id"]: e for e in seed}
    assert by_option["o1"]["outlier_flags"]["u5"] is True
    assert by_option["o1"]["ranks_by_user"]["u5"] == 9
    # u5 now has o1 queued; the clustered voters stay out.
    mgr = OutlierJustificationManager(db_session)
    assert [q["option_id"] for q in mgr.queue_for(activity, "u5")] == ["o1"]
    assert mgr.queue_for(activity, "u1") == []


def test_plugin_open_is_idempotent(db_session):
    meeting = _meeting(db_session)
    activity = _activity(db_session, meeting, _SEED)  # already seeded
    ctx = ActivityContext(db=db_session, meeting=meeting, activity=activity)
    OutlierJustificationPlugin().open_activity(ctx, input_bundle=_ranking_bundle_with_outlier())
    # Existing seed untouched (still the two-option fixture, not recomputed).
    assert len((activity.config or {}).get("justification_seed")) == 2


def test_plugin_close_finalizes_unattributed_rationale_bundle(db_session):
    meeting = _meeting(db_session)
    activity = _activity(db_session, meeting, _SEED)
    u3 = _user(db_session, "u3")
    mgr = OutlierJustificationManager(db_session)
    mgr.submit_rationale(meeting, activity, u3, "o1", "long-term cost")

    ctx = ActivityContext(db=db_session, meeting=meeting, activity=activity)
    result = OutlierJustificationPlugin().close_activity(ctx)
    items = result["items"]
    o1 = next(i for i in items if i["metadata"]["outlier_justification"]["option_id"] == "o1")
    assert o1["metadata"]["outlier_justification"]["rationales"] == ["long-term cost"]
    assert o1["metadata"]["outlier_justification"]["rationale_count"] == 1


# --- registration -----------------------------------------------------------

def test_tool_type_registered_in_catalog_and_loader():
    from app.services.activity_catalog import get_enriched_activity_catalog

    tool_types = {e["tool_type"] for e in get_enriched_activity_catalog()}
    assert "outlier_justification" in tool_types
