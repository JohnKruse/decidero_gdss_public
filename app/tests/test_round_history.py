"""Convergent Yak: multi-bundle round-history input for consuming activities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_manager import MeetingManager
from app.models.activity_bundle import ActivityBundle
from app.models.user import User, UserRole
from app.schemas.meeting import MeetingCreate, PublicityType
from app.services.agenda_strategy import (
    OrchestrationEngineStrategy,
    fetch_round_history,
)
from app.services.orchestration_loader import load_orchestration_data


_META = {
    "thinklets": ["Ranked Evaluation"],
    "collaboration_patterns": ["Evaluate"],
    "deliverables": ["Converged ranked list"],
    "group_size_range": {"min": 1, "max": 6},
    "typical_duration_minutes": {"min": 5, "max": 30},
    "notes": "round-history fixture",
}


def _make_meeting(db_session):
    admin = db_session.query(User).filter(User.role == UserRole.ADMIN.value).first()
    mm = MeetingManager(db_session)
    start = datetime.now(UTC) + timedelta(minutes=5)
    return mm.create_meeting(
        meeting_data=MeetingCreate(
            title="Round History",
            description="Convergent Yak fixture.",
            start_time=start,
            end_time=start + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=admin.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=admin.user_id,
        agenda_items=[],
    )


def test_fetch_round_history_orders_and_dedups_by_round(db_session, user_manager_with_admin):
    meeting = _make_meeting(db_session)
    lsid = "engine:test.0"
    # Insert out of order, with a duplicate round 1 (later id should win).
    for round_index, marker, item in [
        (2, "r2", "C"),
        (0, "r0", "A"),
        (1, "r1-old", "B-old"),
        (1, "r1-new", "B-new"),
    ]:
        db_session.add(
            ActivityBundle(
                bundle_id=f"BND-{marker}",
                meeting_id=meeting.meeting_id,
                activity_id=f"act-{marker}",
                kind="output",
                items=[{"content": item}],
                bundle_metadata={"marker": marker},
                logical_step_id=lsid,
                round_index=round_index,
            )
        )
    # A bundle under a different logical_step_id must not leak in.
    db_session.add(
        ActivityBundle(
            bundle_id="BND-other",
            meeting_id=meeting.meeting_id,
            activity_id="other",
            kind="output",
            items=[{"content": "X"}],
            bundle_metadata={},
            logical_step_id="engine:other.0",
            round_index=0,
        )
    )
    db_session.commit()

    history = fetch_round_history(db_session, meeting.meeting_id, lsid)
    assert [h["round_index"] for h in history] == [0, 1, 2]
    assert [h["items"][0]["content"] for h in history] == ["A", "B-new", "C"]
    assert history[1]["metadata"]["marker"] == "r1-new"  # dedup keeps latest id


def test_round_history_returns_iterate_series_across_rounds(db_session, user_manager_with_admin):
    meeting = _make_meeting(db_session)
    doc = load_orchestration_data({
        "name": "round-history-witness",
        "version": "1",
        "author": "t",
        "citation": "c",
        "metadata": _META,
        "steps": [{
            "type": "iterate",
            "max_rounds": 3,
            "convergence_predicate": {"name": "fixed_n", "config": {"max_rounds": 2}},
            "bundle_transform": {"name": "identity", "config": {}},
            "steps": [{
                "type": "activity",
                "tool_type": "rank_order_voting",
                "title": "Rank",
                "transform_input": "previous_round_feedback",
                "config": {"ideas": []},
            }],
        }],
    })
    strategy = OrchestrationEngineStrategy(doc)
    bm = ActivityBundleManager(db_session)

    # Before any round runs, there is no history yet.
    assert strategy.round_history(meeting, db_session) == []

    for r in range(2):
        activity = strategy.create_activity(meeting, None, None)
        lsid, round_index = strategy.iteration_metadata_for(activity.activity_id)
        assert lsid == "engine:0.0"  # round-output series id
        assert round_index == r
        bm.finalize_output_bundle(
            meeting.meeting_id,
            activity.activity_id,
            [{"content": f"Idea-{r}", "source": {"activity_id": activity.activity_id}}],
            metadata={"round": r},
            logical_step_id=lsid,
            round_index=round_index,
        )

    history = strategy.round_history(meeting, db_session)
    assert [h["round_index"] for h in history] == [0, 1]
    assert [h["items"][0]["content"] for h in history] == ["Idea-0", "Idea-1"]
