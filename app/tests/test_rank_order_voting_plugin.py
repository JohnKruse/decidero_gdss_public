from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.plugins.builtin.rank_order_voting_plugin import RankOrderVotingPlugin
from app.plugins.context import ActivityContext


def _seed_meeting(db_session):
    user = User(
        user_id="u-rank-seed",
        login="urankseed",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(
        meeting_id="M-RANK-SEED",
        owner_id=user.user_id,
        title="Rank seed meeting",
    )
    activity = AgendaActivity(
        activity_id="M-RANK-SEED-RANKOR-0001",
        meeting_id=meeting.meeting_id,
        tool_type="rank_order_voting",
        title="Rank ideas",
        order_index=1,
        tool_config_id="tc-rank-1",
        config={"ideas": []},
    )
    meeting.agenda_activities.append(activity)
    db_session.add_all([user, meeting, activity])
    db_session.commit()
    return meeting, activity, user


def test_rank_order_plugin_seeds_ideas_from_input_bundle(db_session):
    meeting, activity, user = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        activity.activity_id,
        "input",
        [
            {"content": "Idea A", "metadata": {"tag": "alpha"}},
            {"content": "Idea B", "metadata": {"tag": "beta"}},
        ],
        metadata={"source": "brainstorming"},
    )

    plugin = RankOrderVotingPlugin()
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    plugin.open_activity(context, input_bundle)

    db_session.refresh(activity)
    ideas = activity.config.get("ideas")
    assert isinstance(ideas, list)
    assert [entry.get("content") for entry in ideas] == ["Idea A", "Idea B"]
    assert ideas[0].get("metadata", {}).get("tag") == "alpha"


def test_rank_order_plugin_close_emits_rank_metadata(db_session):
    meeting, activity, user = _seed_meeting(db_session)
    activity.config = {
        "ideas": ["Idea A", "Idea B", "Idea C"],
        "show_results_immediately": True,
    }
    db_session.add(activity)
    db_session.commit()

    plugin = RankOrderVotingPlugin()
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    result = plugin.close_activity(context)

    assert result is not None
    items = result.get("items")
    assert isinstance(items, list)
    assert len(items) == 3
    for item in items:
        metadata = item.get("metadata", {})
        assert "rank_order_voting" in metadata
        assert metadata["rank_order_voting"].get("option_id")
