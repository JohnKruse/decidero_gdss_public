from datetime import datetime, timezone

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.activity_bundle import ActivityBundle
from app.models.categorization import CategorizationItem
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.models.voting import VotingVote
from app.plugins.builtin.categorization_plugin import CategorizationPlugin
from app.plugins.builtin.voting_plugin import VotingPlugin
from app.plugins.builtin.brainstorming_plugin import BrainstormingPlugin
from app.plugins.context import ActivityContext
from app.services.activity_pipeline import ActivityPipeline
from app.services.activity_catalog import get_activity_catalog
from app.services.categorization_manager import CategorizationManager
from app.services.voting_manager import VotingManager


def _seed_meeting(db_session):
    user = User(
        user_id="u-seed",
        login="useed",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(
        meeting_id="M-SEED",
        owner_id=user.user_id,
        title="Seed meeting",
    )
    activity_one = AgendaActivity(
        activity_id="M-SEED-BRAIN-0001",
        meeting_id=meeting.meeting_id,
        tool_type="brainstorming",
        title="Brainstorm",
        order_index=1,
        tool_config_id="tc-1",
        config={},
    )
    activity_two = AgendaActivity(
        activity_id="M-SEED-VOTE-0002",
        meeting_id=meeting.meeting_id,
        tool_type="voting",
        title="Voting",
        order_index=2,
        tool_config_id="tc-2",
        config={},
    )
    meeting.agenda_activities.extend([activity_one, activity_two])
    db_session.add_all([user, meeting, activity_one, activity_two])
    db_session.commit()
    return meeting, activity_one, activity_two, user


def _seed_meeting_with_categorization(db_session):
    user = User(
        user_id="u-cat-seed",
        login="ucatseed",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(
        meeting_id="M-CAT-SEED",
        owner_id=user.user_id,
        title="Categorization Seed meeting",
    )
    brainstorming_activity = AgendaActivity(
        activity_id="M-CAT-SEED-BRAIN-0001",
        meeting_id=meeting.meeting_id,
        tool_type="brainstorming",
        title="Brainstorm",
        order_index=1,
        tool_config_id="tc-cat-1",
        config={},
    )
    categorization_activity = AgendaActivity(
        activity_id="M-CAT-SEED-CATGRY-0002",
        meeting_id=meeting.meeting_id,
        tool_type="categorization",
        title="Categorization",
        order_index=2,
        tool_config_id="tc-cat-2",
        config={"mode": "FACILITATOR_LIVE", "items": [], "buckets": ["Theme A"]},
    )
    meeting.agenda_activities.extend([brainstorming_activity, categorization_activity])
    db_session.add_all([user, meeting, brainstorming_activity, categorization_activity])
    db_session.commit()
    return meeting, brainstorming_activity, categorization_activity, user


def test_activity_bundle_manager_roundtrip(db_session):
    meeting, activity_one, activity_two, _ = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    output = manager.create_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        [{"content": "Idea 1", "metadata": {"votes": 0}}],
        metadata={"source": "brainstorming"},
    )
    input_bundle = manager.create_input_bundle_from_output(
        meeting.meeting_id, activity_two.activity_id, output
    )
    assert input_bundle.kind == "input"
    assert input_bundle.items == output.items
    assert input_bundle.bundle_metadata == output.bundle_metadata


def test_activity_pipeline_creates_input(db_session):
    meeting, activity_one, activity_two, _ = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    manager.create_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        [{"content": "Idea 1"}],
        metadata={"source": "brainstorming"},
    )
    pipeline = ActivityPipeline(db_session)
    input_bundle = pipeline.ensure_input_bundle(meeting, activity_two)
    assert input_bundle is not None
    assert input_bundle.kind == "input"
    assert input_bundle.items[0]["content"] == "Idea 1"


def test_voting_plugin_seeds_options_from_input(db_session):
    meeting, _, activity_two, user = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        activity_two.activity_id,
        "input",
        [{"content": "Option A"}, {"content": "Option B"}],
        metadata={"source": "brainstorming"},
    )
    context = ActivityContext(
        db=db_session, meeting=meeting, activity=activity_two, user=user
    )
    plugin = VotingPlugin()
    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity_two)
    options = activity_two.config.get("options")
    assert isinstance(options, list)
    assert [entry.get("content") for entry in options] == ["Option A", "Option B"]


def test_voting_plugin_preserves_input_items_in_output_bundle(db_session):
    meeting, _, activity_two, user = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    input_items = [
        {
            "id": 123,
            "content": "Keep provenance",
            "submitted_name": "Pat",
            "parent_id": None,
            "created_at": "2026-01-01T00:00:00Z",
            "metadata": {"tag": "seed"},
            "source": {"meeting_id": meeting.meeting_id, "activity_id": "UPSTREAM-0001"},
        }
    ]
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        activity_two.activity_id,
        "input",
        input_items,
        metadata={"source": "brainstorming"},
    )
    context = ActivityContext(
        db=db_session, meeting=meeting, activity=activity_two, user=user
    )
    plugin = VotingPlugin()
    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity_two)

    option_id = f"{activity_two.activity_id}:idea-123"
    db_session.add(
        VotingVote(
            meeting_id=meeting.meeting_id,
            activity_id=activity_two.activity_id,
            user_id=user.user_id,
            option_id=option_id,
            option_label="Keep provenance",
            weight=1,
        )
    )
    db_session.commit()

    result = plugin.close_activity(context)
    assert result is not None
    assert isinstance(result.get("items"), list)
    output_item = result["items"][0]
    assert output_item.get("id") == 123
    assert output_item.get("submitted_name") == "Pat"
    assert output_item.get("metadata", {}).get("tag") == "seed"
    assert output_item.get("metadata", {}).get("voting", {}).get("option_id") == option_id
    assert output_item.get("metadata", {}).get("voting", {}).get("votes") == 1


def test_voting_plugin_clears_stale_votes_and_bundles(db_session):
    meeting, _, activity_two, user = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        activity_two.activity_id,
        "input",
        [
            {
                "content": "Sanitized option",
                "metadata": {
                    "votes": 5,
                    "option_id": "OLD:1",
                    "tag": "seed",
                    "voting": {"option_id": "OLD:1", "votes": 5, "extra": "keep"},
                },
            }
        ],
        metadata={"source": "legacy"},
    )
    db_session.add(
        VotingVote(
            meeting_id=meeting.meeting_id,
            activity_id=activity_two.activity_id,
            user_id=user.user_id,
            option_id=f"{activity_two.activity_id}:idea-1",
            option_label="Existing",
            weight=1,
        )
    )
    db_session.commit()

    context = ActivityContext(db=db_session, meeting=meeting, activity=activity_two, user=user)
    plugin = VotingPlugin()
    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity_two)

    assert (
        db_session.query(VotingVote)
        .filter(
            VotingVote.meeting_id == meeting.meeting_id,
            VotingVote.activity_id == activity_two.activity_id,
        )
        .count()
        == 0
    )
    assert (
        db_session.query(ActivityBundle)
        .filter(
            ActivityBundle.meeting_id == meeting.meeting_id,
            ActivityBundle.activity_id == activity_two.activity_id,
        )
        .count()
        == 0
    )

    options = activity_two.config.get("options") or []
    assert options
    metadata = options[0].get("metadata", {})
    assert metadata.get("tag") == "seed"
    assert metadata.get("votes") is None
    assert metadata.get("option_id") is None
    voting_metadata = metadata.get("voting")
    if voting_metadata is not None:
        assert "option_id" not in voting_metadata
        assert "votes" not in voting_metadata


def test_voting_manager_scopes_option_ids(db_session):
    meeting, _, activity_two, user = _seed_meeting(db_session)
    activity_two.config = {
        "options": [
            {
                "content": "Scoped option",
                "metadata": {"voting": {"option_id": "LEGACY:opt-legacy"}},
            }
        ],
        "max_votes": 2,
    }
    db_session.add(activity_two)
    db_session.commit()

    summary = VotingManager(db_session).build_summary(meeting, activity_two.activity_id, user)
    assert all(
        option["option_id"].startswith(f"{activity_two.activity_id}:")
        for option in summary["options"]
    )


def test_activity_pipeline_replaces_stale_input_bundle(db_session):
    meeting, activity_one, activity_two, _ = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    output = manager.create_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        [{"content": "Idea from previous"}],
        metadata={"source": "brainstorming"},
    )
    stale_input = manager.create_bundle(
        meeting.meeting_id,
        activity_two.activity_id,
        "input",
        [{"content": "Stale option"}],
        metadata={"source": "legacy"},
    )
    stale_input.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    activity_two.created_at = datetime.now(timezone.utc)
    db_session.add(stale_input)
    db_session.add(activity_two)
    db_session.commit()

    pipeline = ActivityPipeline(db_session)
    replaced = pipeline.ensure_input_bundle(meeting, activity_two)
    assert replaced is not None
    assert replaced.kind == "input"
    assert replaced.bundle_id != stale_input.bundle_id
    assert replaced.items == output.items

    active_inputs = (
        db_session.query(ActivityBundle)
        .filter(
            ActivityBundle.meeting_id == meeting.meeting_id,
            ActivityBundle.activity_id == activity_two.activity_id,
            ActivityBundle.kind == "input",
        )
        .all()
    )
    assert len(active_inputs) == 1


def test_autosave_seconds_clamped():
    plugin = BrainstormingPlugin()
    assert plugin.get_autosave_seconds({"autosave_seconds": 1}) == 5
    assert plugin.get_autosave_seconds({"autosave_seconds": 500}) == 300


def test_activity_catalog_includes_core_tools():
    entries = get_activity_catalog()
    tool_types = {entry["tool_type"] for entry in entries}
    assert {"brainstorming", "voting", "categorization"}.issubset(tool_types)
    brainstorming_entry = next(
        (entry for entry in entries if entry["tool_type"] == "brainstorming"),
        None,
    )
    assert brainstorming_entry is not None
    policy = brainstorming_entry.get("reliability_policy") or {}
    submit_policy = policy.get("submit_idea") or {}
    assert submit_policy.get("idempotency_header") == "X-Idempotency-Key"


def test_categorization_plugin_seeds_items_with_comment_folding_and_provenance(db_session):
    meeting, _, activity, user = _seed_meeting_with_categorization(db_session)
    manager = ActivityBundleManager(db_session)
    input_items = [
        {
            "id": 1,
            "content": "Top idea",
            "parent_id": None,
            "metadata": {"tag": "seed"},
            "source": {"meeting_id": meeting.meeting_id, "activity_id": "UPSTREAM-0001"},
        },
        {
            "id": 2,
            "content": "Comment A",
            "parent_id": 1,
            "metadata": {"kind": "comment"},
            "source": {"meeting_id": meeting.meeting_id, "activity_id": "UPSTREAM-0001"},
        },
    ]
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        activity.activity_id,
        "input",
        input_items,
        metadata={
            "source": "brainstorming",
            "include_comments": True,
            "comments_by_parent": {"1": [{"content": "Comment A"}]},
        },
    )

    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    plugin = CategorizationPlugin()
    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity)

    seeded_items = activity.config.get("items") or []
    assert len(seeded_items) == 1
    assert seeded_items[0]["content"] == "Top idea (Comments: Comment A)"
    assert seeded_items[0]["metadata"]["tag"] == "seed"
    assert seeded_items[0]["source"]["activity_id"] == "UPSTREAM-0001"

    persisted_items = (
        db_session.query(CategorizationItem)
        .filter(
            CategorizationItem.meeting_id == meeting.meeting_id,
            CategorizationItem.activity_id == activity.activity_id,
        )
        .all()
    )
    assert len(persisted_items) == 1
    assert persisted_items[0].content == "Top idea (Comments: Comment A)"


def test_categorization_plugin_does_not_overwrite_existing_items(db_session):
    meeting, _, activity, user = _seed_meeting_with_categorization(db_session)
    activity.config = {"mode": "FACILITATOR_LIVE", "items": [{"id": "manual-1", "content": "Manual"}]}
    db_session.add(activity)
    db_session.commit()

    input_bundle = ActivityBundleManager(db_session).create_bundle(
        meeting.meeting_id,
        activity.activity_id,
        "input",
        [{"id": 1, "content": "Incoming"}],
        metadata={"source": "brainstorming"},
    )

    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    CategorizationPlugin().open_activity(context, input_bundle)
    db_session.refresh(activity)

    seeded_items = activity.config.get("items") or []
    assert len(seeded_items) == 1
    assert seeded_items[0]["content"] == "Manual"


def test_categorization_plugin_close_emits_finalized_output_metadata(db_session):
    meeting, _, activity, user = _seed_meeting_with_categorization(db_session)
    activity.config = {
        "mode": "PARALLEL_BALLOT",
        "items": [{"id": "cat-1", "content": "Idea One"}],
        "buckets": ["Theme A", "Theme B"],
        "agreement_threshold": 0.6,
        "minimum_ballots": 1,
        "finalization_metadata": {"mode": "PARALLEL_BALLOT", "ballot_count": 1},
    }
    db_session.add(activity)
    db_session.commit()

    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    plugin = CategorizationPlugin()
    plugin.open_activity(context, None)

    manager = CategorizationManager(db_session)
    buckets = manager.list_buckets(meeting.meeting_id, activity.activity_id)
    target_bucket = next(
        bucket.category_id for bucket in buckets if bucket.category_id != "UNSORTED"
    )
    manager.upsert_ballot(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        user_id=user.user_id,
        item_key="cat-1",
        category_id=target_bucket,
        submitted=True,
    )
    manager.set_final_assignment(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        item_key="cat-1",
        category_id=target_bucket,
        resolver_user_id=user.user_id,
    )

    result = plugin.close_activity(context)
    assert result is not None

    output_bundle = (
        db_session.query(ActivityBundle)
        .filter(
            ActivityBundle.meeting_id == meeting.meeting_id,
            ActivityBundle.activity_id == activity.activity_id,
            ActivityBundle.kind == "output",
        )
        .order_by(ActivityBundle.created_at.desc())
        .first()
    )
    assert output_bundle is not None
    metadata = output_bundle.bundle_metadata or {}
    assert "categories" in metadata
    assert metadata["finalization_metadata"]["mode"] == "FACILITATOR_LIVE"
    assert metadata["final_assignments"]["cat-1"] == target_bucket
    assert metadata["agreement_metrics"] == {}
    assert output_bundle.items[0]["metadata"]["categorization"]["bucket_id"] == target_bucket
