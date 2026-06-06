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
    u = User(
        user_id=uid, login=uid, hashed_password="h", role=UserRole.PARTICIPANT.value
    )
    db.add(u)
    db.commit()
    return u


def _meeting(db, owner_id="owner"):
    owner = User(
        user_id=owner_id, login=owner_id, hashed_password="h", role=UserRole.ADMIN.value
    )
    meeting = Meeting(meeting_id="M-OJ-1", owner_id=owner_id, title="OJ")
    db.add_all([owner, meeting])
    db.commit()
    return meeting


def _activity(
    db,
    meeting,
    seed,
    activity_id="A-JUST",
    round_index=0,
    config_extra=None,
):
    config = {
        "justification_seed": seed,
        "_orchestration": {
            "logical_step_id": f"engine:{activity_id}",
            "round_index": round_index,
        },
    }
    if config_extra:
        config.update(config_extra)
    activity = AgendaActivity(
        activity_id=activity_id,
        meeting_id=meeting.meeting_id,
        tool_type="outlier_justification",
        title="Justify",
        order_index=1,
        tool_config_id=f"tc-{activity_id}",
        config=config,
    )
    db.add(activity)
    db.commit()
    return activity


# A seed: option o1 has u3 flagged as an outlier; o2 has nobody flagged.
_SEED = [
    {
        "option_id": "o1",
        "content": "Idea A",
        "median": 1.0,
        "iqr": 0.0,
        "outlier_flags": {"u1": False, "u2": False, "u3": True},
        "ranks_by_user": {"u1": 1, "u2": 1, "u3": 9},
    },
    {
        "option_id": "o2",
        "content": "Idea B",
        "median": 2.0,
        "iqr": 1.0,
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
    assert set(flagged[0]) == {
        "option_id",
        "content",
        "your_rank",
        "group_median",
        "group_iqr",
    }

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


def test_selected_items_mode_opens_same_comment_queue_to_all_participants(db_session):
    meeting = _meeting(db_session)
    selected_items = [
        {
            "option_id": "o2",
            "content": "Idea B",
            "median": 2.0,
            "iqr": 1.0,
            "ranks_by_user": {"u1": 2, "u2": 1},
        },
        {
            "option_id": "o3",
            "content": "Idea C",
            "median": 3.0,
            "iqr": 2.0,
            "ranks_by_user": {"u1": 1, "u2": 3},
        },
    ]
    activity = _activity(
        db_session,
        meeting,
        _SEED,
        config_extra={
            "comment_scope": "selected_items",
            "selected_comment_items": selected_items,
        },
    )
    u1, u2 = _user(db_session, "u1"), _user(db_session, "u2")
    mgr = OutlierJustificationManager(db_session)

    assert [q["option_id"] for q in mgr.queue_for(activity, "u1")] == ["o2", "o3"]
    assert [q["option_id"] for q in mgr.queue_for(activity, "u2")] == ["o2", "o3"]
    assert mgr.queue_for(activity, "u1")[0]["your_rank"] == 2

    mgr.submit_rationale(meeting, activity, u1, "o2", "Please clarify constraints.")
    with pytest.raises(JustificationError, match="not open for comments"):
        mgr.submit_rationale(meeting, activity, u1, "o1", "Not selected.")


def test_collected_by_option_is_unattributed(db_session):
    meeting = _meeting(db_session)
    # Both u3 and u4 flagged on o1.
    seed = [
        {
            "option_id": "o1",
            "content": "Idea A",
            "median": 1.0,
            "iqr": 0.0,
            "outlier_flags": {"u3": True, "u4": True},
            "ranks_by_user": {"u3": 9, "u4": 8},
        }
    ]
    activity = _activity(db_session, meeting, seed)
    u3, u4 = _user(db_session, "u3"), _user(db_session, "u4")
    mgr = OutlierJustificationManager(db_session)
    mgr.submit_rationale(meeting, activity, u3, "o1", "cost")
    mgr.submit_rationale(meeting, activity, u4, "o1", "risk")

    grouped = mgr.collected_by_option(meeting, activity)
    assert set(grouped["o1"]) == {"cost", "risk"}  # text only, no user_ids


def test_facilitator_progress_counts_complete_outlier_queues(db_session):
    meeting = _meeting(db_session)
    seed = [
        {
            "option_id": "o1",
            "content": "Idea A",
            "median": 1.0,
            "iqr": 0.0,
            "outlier_flags": {"u3": True, "u4": True},
            "ranks_by_user": {"u3": 9, "u4": 8},
        },
        {
            "option_id": "o2",
            "content": "Idea B",
            "median": 2.0,
            "iqr": 1.0,
            "outlier_flags": {"u3": True, "u4": False},
            "ranks_by_user": {"u3": 7, "u4": 2},
        },
    ]
    activity = _activity(db_session, meeting, seed)
    u3, u4 = _user(db_session, "u3"), _user(db_session, "u4")
    mgr = OutlierJustificationManager(db_session)

    assert mgr.facilitator_progress(meeting, activity) == {
        "outlier_count": 2,
        "submitted_count": 0,
    }

    mgr.submit_rationale(meeting, activity, u4, "o1", "risk")
    assert mgr.facilitator_progress(meeting, activity) == {
        "outlier_count": 2,
        "submitted_count": 1,
    }

    mgr.submit_rationale(meeting, activity, u3, "o1", "cost")
    assert mgr.facilitator_progress(meeting, activity)["submitted_count"] == 1
    mgr.submit_rationale(meeting, activity, u3, "o2", "capacity")
    assert mgr.facilitator_progress(meeting, activity) == {
        "outlier_count": 2,
        "submitted_count": 2,
    }


def test_facilitator_progress_counts_selected_item_comment_assignees(db_session):
    meeting = _meeting(db_session)
    u1, u2 = _user(db_session, "u1"), _user(db_session, "u2")
    meeting.participants.extend([u1, u2])
    db_session.commit()
    activity = _activity(
        db_session,
        meeting,
        _SEED,
        config_extra={
            "comment_scope": "selected_items",
            "selected_comment_items": [
                {"option_id": "o1", "content": "Idea A"},
                {"option_id": "o2", "content": "Idea B"},
            ],
        },
    )
    mgr = OutlierJustificationManager(db_session)

    assert mgr.facilitator_progress(meeting, activity) == {
        "outlier_count": 2,
        "submitted_count": 0,
        "selected_item_count": 2,
    }

    mgr.submit_rationale(meeting, activity, u1, "o1", "cost")
    assert mgr.facilitator_progress(meeting, activity)["submitted_count"] == 0
    mgr.submit_rationale(meeting, activity, u1, "o2", "risk")
    assert mgr.facilitator_progress(meeting, activity) == {
        "outlier_count": 2,
        "submitted_count": 1,
        "selected_item_count": 2,
    }


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
    OutlierJustificationPlugin().open_activity(
        ctx, input_bundle=_ranking_bundle_with_outlier()
    )

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
    OutlierJustificationPlugin().open_activity(
        ctx, input_bundle=_ranking_bundle_with_outlier()
    )
    # Existing seed untouched (still the two-option fixture, not recomputed).
    assert len((activity.config or {}).get("justification_seed")) == 2


_FEEDBACK_POLICY = {
    "comment_selection": {
        "strategy": "adaptive_least_converged",
        "default_fraction": 0.25,
        "max_fraction": 0.5,
        "low_disagreement_fraction": 0.0,
        "moderate_disagreement_fraction": 0.15,
        "high_disagreement_fraction": 0.25,
        "min_items_when_disputed": 1,
        "allow_skip": True,
    },
    "agreement_bands": {"score_source": "iqr", "green_max": 1.0, "yellow_max": 2.0},
}


def _disputed_ranking_bundle():
    """Three ideas with descending disagreement: o1 widest, o3 tightest."""
    items = [
        {"content": "Idea A", "metadata": {"rank_order_voting": {"option_id": "o1"}}},
        {"content": "Idea B", "metadata": {"rank_order_voting": {"option_id": "o2"}}},
        {"content": "Idea C", "metadata": {"rank_order_voting": {"option_id": "o3"}}},
    ]
    votes = []
    o1_ranks = [1, 1, 9, 9]   # wide spread
    o2_ranks = [2, 2, 5, 6]   # moderate spread
    o3_ranks = [3, 3, 3, 3]   # converged
    for uid, r1, r2, r3 in zip(["u1", "u2", "u3", "u4"], o1_ranks, o2_ranks, o3_ranks):
        votes.append({"user_id": uid, "option_id": "o1", "rank_position": r1})
        votes.append({"user_id": uid, "option_id": "o2", "rank_position": r2})
        votes.append({"user_id": uid, "option_id": "o3", "rank_position": r3})
    return _StubBundle(items, {"source": "rank_order_voting", "votes": votes})


def _record_gate_decision(db, meeting, round_index, selected_comment_count):
    from app.models.activity_bundle import ActivityBundle

    db.add(
        ActivityBundle(
            bundle_id=f"gate-{round_index}",
            meeting_id=meeting.meeting_id,
            activity_id="GATE",
            kind="output",
            round_index=round_index,
            items=[],
            bundle_metadata={
                "source": "facilitator_decision",
                "chosen": "continue",
                "selected_comment_count": selected_comment_count,
            },
        )
    )
    db.commit()


def test_plugin_open_applies_facilitator_selected_count(db_session):
    """A prior-round gate count of N opens the N most-disputed ideas to everyone."""
    meeting = _meeting(db_session)
    _record_gate_decision(db_session, meeting, round_index=0, selected_comment_count=2)
    activity = _activity(
        db_session,
        meeting,
        seed=[],
        round_index=1,
        config_extra={"feedback_policy": _FEEDBACK_POLICY},
    )

    ctx = ActivityContext(db=db_session, meeting=meeting, activity=activity)
    OutlierJustificationPlugin().open_activity(ctx, input_bundle=_disputed_ranking_bundle())

    config = activity.config or {}
    assert config["comment_scope"] == "selected_items"
    selected = [e["option_id"] for e in config["selected_comment_items"]]
    # The two widest-spread ideas, most-disputed first; the converged o3 stays out.
    assert selected == ["o1", "o2"]

    # Every participant — outlier or not — now sees the same selected queue.
    mgr = OutlierJustificationManager(db_session)
    assert [q["option_id"] for q in mgr.queue_for(activity, "u1")] == ["o1", "o2"]
    assert [q["option_id"] for q in mgr.queue_for(activity, "u4")] == ["o1", "o2"]


def test_plugin_open_count_zero_skips_comments(db_session):
    """A gate count of 0 opens an empty selected queue (a soft skip to reranking)."""
    meeting = _meeting(db_session)
    _record_gate_decision(db_session, meeting, round_index=0, selected_comment_count=0)
    activity = _activity(
        db_session,
        meeting,
        seed=[],
        round_index=1,
        config_extra={"feedback_policy": _FEEDBACK_POLICY},
    )

    ctx = ActivityContext(db=db_session, meeting=meeting, activity=activity)
    OutlierJustificationPlugin().open_activity(ctx, input_bundle=_disputed_ranking_bundle())

    config = activity.config or {}
    assert config["comment_scope"] == "selected_items"
    assert config["selected_comment_items"] == []
    mgr = OutlierJustificationManager(db_session)
    assert mgr.build_state(meeting, activity, _user(db_session, "u1"))["nothing_to_justify"] is True


def test_plugin_open_without_gate_decision_stays_outlier_mode(db_session):
    """With no recorded gate count, the activity keeps its default outlier mode."""
    meeting = _meeting(db_session)
    activity = _activity(
        db_session,
        meeting,
        seed=[],
        round_index=1,
        config_extra={"feedback_policy": _FEEDBACK_POLICY},
    )

    ctx = ActivityContext(db=db_session, meeting=meeting, activity=activity)
    OutlierJustificationPlugin().open_activity(ctx, input_bundle=_disputed_ranking_bundle())

    config = activity.config or {}
    assert "selected_comment_items" not in config
    assert config.get("comment_scope") in (None, "outliers_only")


def test_plugin_close_finalizes_unattributed_rationale_bundle(db_session):
    meeting = _meeting(db_session)
    activity = _activity(db_session, meeting, _SEED)
    u3 = _user(db_session, "u3")
    mgr = OutlierJustificationManager(db_session)
    mgr.submit_rationale(meeting, activity, u3, "o1", "long-term cost")

    ctx = ActivityContext(db=db_session, meeting=meeting, activity=activity)
    result = OutlierJustificationPlugin().close_activity(ctx)
    items = result["items"]
    o1 = next(
        i for i in items if i["metadata"]["outlier_justification"]["option_id"] == "o1"
    )
    assert o1["metadata"]["outlier_justification"]["rationales"] == ["long-term cost"]
    assert o1["metadata"]["outlier_justification"]["rationale_count"] == 1


# --- registration -----------------------------------------------------------


def test_tool_type_registered_in_catalog_and_loader():
    from app.services.activity_catalog import get_enriched_activity_catalog

    tool_types = {e["tool_type"] for e in get_enriched_activity_catalog()}
    assert "outlier_justification" in tool_types
