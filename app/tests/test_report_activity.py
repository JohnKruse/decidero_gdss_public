"""Report plugin end-to-end: iterate concludes -> report materializes + builds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_manager import MeetingManager
from app.models.user import User, UserRole
from app.plugins.builtin.report_plugin import ReportPlugin
from app.plugins.context import ActivityContext
from app.schemas.meeting import MeetingCreate, PublicityType
from app.services.agenda_strategy import OrchestrationEngineStrategy
from app.services.orchestration_loader import load_orchestration_data


_META = {
    "thinklets": ["Ranked Evaluation"],
    "collaboration_patterns": ["Evaluate"],
    "deliverables": ["Converged ranked list"],
    "group_size_range": {"min": 1, "max": 6},
    "typical_duration_minutes": {"min": 5, "max": 30},
    "notes": "report activity fixture",
}


def _meeting(db_session):
    admin = db_session.query(User).filter(User.role == UserRole.ADMIN.value).first()
    mm = MeetingManager(db_session)
    start = datetime.now(UTC) + timedelta(minutes=5)
    return mm.create_meeting(
        meeting_data=MeetingCreate(
            title="Report Run", description="terminal report fixture",
            start_time=start, end_time=start + timedelta(minutes=30),
            duration_minutes=30, publicity=PublicityType.PRIVATE,
            owner_id=admin.user_id, participant_ids=[], additional_facilitator_ids=[],
        ),
        facilitator_id=admin.user_id, agenda_items=[],
    )


def _round_output(activity_id, round_label, votes_by_user):
    labels = sorted({l for v in votes_by_user.values() for l in v})
    items = [
        {"content": f"Idea {l}", "id": f"{round_label}:{l}",
         "metadata": {"rank_order_voting": {"option_id": f"{round_label}:{l}"}}}
        for l in labels
    ]
    votes = [
        {"option_id": f"{round_label}:{l}", "user_id": u, "rank_position": pos}
        for u, ranks in votes_by_user.items() for l, pos in ranks.items()
    ]
    return items, {"votes": votes}


def test_report_activity_materializes_and_builds(db_session, user_manager_with_admin, mocker):
    meeting = _meeting(db_session)
    doc = load_orchestration_data({
        "name": "Classical Delphi", "version": "1.0", "author": "t", "citation": "c",
        "metadata": _META,
        "steps": [{"type": "sequence", "steps": [
            {"type": "iterate", "max_rounds": 3,
             "convergence_predicate": {"name": "fixed_n", "config": {"max_rounds": 2}},
             "bundle_transform": {"name": "identity", "config": {}},
             "steps": [{"type": "activity", "tool_type": "rank_order_voting",
                        "title": "Rank", "transform_input": "previous_round_feedback",
                        "config": {"ideas": []}}]},
            {"type": "activity", "tool_type": "report", "title": "Final Report",
             "config": {}},
        ]}],
    })
    strategy = OrchestrationEngineStrategy(doc)
    bm = ActivityBundleManager(db_session)

    round_votes = [
        {"u1": {"A": 1, "B": 2, "C": 3}, "u2": {"A": 1, "B": 3, "C": 2},
         "u3": {"A": 2, "B": 1, "C": 3}},
        {"u1": {"A": 1, "B": 2, "C": 3}, "u2": {"A": 1, "B": 2, "C": 3},
         "u3": {"A": 1, "B": 2, "C": 3}},
    ]
    for r in range(2):
        activity = strategy.create_activity(meeting, None, None)
        lsid, ridx = strategy.iteration_metadata_for(activity.activity_id)
        items, meta = _round_output(activity.activity_id, f"r{r}", round_votes[r])
        bm.finalize_output_bundle(meeting.meeting_id, activity.activity_id, items,
                                  metadata=meta, logical_step_id=lsid, round_index=ridx)

    # Iterate has converged (fixed_n=2) -> next materialization is the report step.
    report_activity = strategy.create_activity(meeting, None, None)
    assert report_activity.tool_type == "report"

    # The plugin resolves the strategy from the meeting; point it at ours.
    mocker.patch(
        "app.services.agenda_strategy.get_agenda_strategy", return_value=strategy
    )
    ctx = ActivityContext(db=db_session, meeting=meeting, activity=report_activity)
    ReportPlugin().open_activity(ctx)

    out = bm.get_latest_bundle(meeting.meeting_id, report_activity.activity_id, "output")
    assert out is not None
    report = out.bundle_metadata["report_payload"]
    assert report["meeting"]["round_count"] == 2
    assert report["meeting"]["method"]["name"] == "Classical Delphi"
    types = {s["type"] for s in report["sections"]}
    assert {"narrative", "ranked_list", "table", "chart", "rounds"} <= types
    ranked = next(s for s in report["sections"] if s["type"] == "ranked_list")
    assert ranked["body"]["items"][0]["label"] == "Idea A"  # consensus winner
    # bundle items mirror the headline ranking for export
    assert out.items[0]["content"] == "Idea A"
