"""Tests for the facilitator round-statistics report-out aggregation."""

from __future__ import annotations

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.services.round_statistics import compute_round_statistics


def _seed(db_session):
    user = User(
        user_id="u-rs-1", login="rs1", hashed_password="h", role=UserRole.ADMIN.value
    )
    meeting = Meeting(meeting_id="M-RS-1", owner_id=user.user_id, title="RS")
    db_session.add_all([user, meeting])
    db_session.commit()
    return meeting, user


def _activity(meeting, activity_id, tool_type, round_index, order_index):
    return AgendaActivity(
        activity_id=activity_id,
        meeting_id=meeting.meeting_id,
        tool_type=tool_type,
        title=activity_id,
        order_index=order_index,
        tool_config_id=f"tc-{activity_id}",
        config={"_orchestration": {"logical_step_id": f"engine:0.1.0.{order_index}", "round_index": round_index}},
    )


def test_round_statistics_aggregates_from_ranking_output(db_session):
    meeting, _ = _seed(db_session)
    rank = _activity(meeting, "A-RANK", "rank_order_voting", 0, 0)
    justify = _activity(meeting, "A-JUST", "brainstorming", 0, 1)
    db_session.add_all([rank, justify])
    db_session.commit()

    items = [
        {"content": "A", "metadata": {"rank_order_voting": {"option_id": "o1"}}},
        {"content": "B", "metadata": {"rank_order_voting": {"option_id": "o2"}}},
    ]
    votes = [
        {"user_id": "u1", "option_id": "o1", "rank_position": 1},
        {"user_id": "u2", "option_id": "o1", "rank_position": 1},
        {"user_id": "u3", "option_id": "o1", "rank_position": 2},
        {"user_id": "u1", "option_id": "o2", "rank_position": 2},
        {"user_id": "u2", "option_id": "o2", "rank_position": 2},
        {"user_id": "u3", "option_id": "o2", "rank_position": 1},
    ]
    ActivityBundleManager(db_session).finalize_output_bundle(
        meeting.meeting_id, "A-RANK", items,
        metadata={"source": "rank_order_voting", "votes": votes},
        logical_step_id="engine:0.1.0.0", round_index=0,
    )

    summary = compute_round_statistics(db_session, meeting, justify)
    assert summary["available"] is True
    assert summary["round_number"] == 1
    assert summary["item_count"] == 2
    assert summary["participant_count"] == 3
    assert summary["strong_agreement_items"] + summary["contested_items"] <= 2
    assert "agreement_label" in summary
    assert isinstance(summary["median_iqr"], float)


def test_round_statistics_unavailable_without_ranking(db_session):
    meeting, _ = _seed(db_session)
    justify = _activity(meeting, "A-JUST", "brainstorming", 0, 1)
    db_session.add(justify)
    db_session.commit()

    summary = compute_round_statistics(db_session, meeting, justify)
    assert summary["available"] is False
    assert summary["round_number"] == 1
