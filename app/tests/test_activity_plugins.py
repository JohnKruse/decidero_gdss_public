from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.activity_bundle import ActivityBundle
from app.models.categorization import (
    CategorizationAssignment,
    CategorizationBucket,
    CategorizationItem,
)
from app.models.idea import Idea
from app.models.meeting import AgendaActivity, Meeting
from app.models.rank_order_voting import RankOrderVote
from app.models.user import User, UserRole
from app.models.voting import VotingVote
from app.plugins.builtin.categorization_plugin import CategorizationPlugin
from app.plugins.builtin.rank_order_voting_plugin import RankOrderVotingPlugin
from app.plugins.builtin.voting_plugin import VotingPlugin
from app.plugins.builtin.brainstorming_plugin import BrainstormingPlugin
from app.plugins.base import ActivityPlugin, ActivityPluginManifest
from app.plugins.context import ActivityContext
from app.plugins.loader import load_builtin_plugins
from app.plugins.registry import ActivityRegistry
import app.services.activity_pipeline as activity_pipeline_module
from app.services.activity_pipeline import ActivityPipeline
from app.services.activity_catalog import get_activity_catalog, normalise_reliability_policy
from app.services.agenda_strategy import PriorActivityReference
from app.services.categorization_manager import CategorizationManager
from app.services.contract_schemas import (
    ContractSchemaError,
    validate_activity_manifest,
    validate_bundle_payload,
)
from app.services.voting_manager import VotingManager


THINKLET_AUDIT_PATH = Path(__file__).resolve().parents[2] / "docs" / "THINKLET_AUDIT.md"


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


def _seed_meeting_with_rank_order_voting(db_session):
    user = User(
        user_id="u-rank-seed",
        login="urankseed",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(
        meeting_id="M-RANK-SEED",
        owner_id=user.user_id,
        title="Rank-order seed meeting",
    )
    brainstorming_activity = AgendaActivity(
        activity_id="M-RANK-SEED-BRAIN-0001",
        meeting_id=meeting.meeting_id,
        tool_type="brainstorming",
        title="Brainstorm",
        order_index=1,
        tool_config_id="tc-rank-1",
        config={},
    )
    rank_activity = AgendaActivity(
        activity_id="M-RANK-SEED-RANK-0002",
        meeting_id=meeting.meeting_id,
        tool_type="rank_order_voting",
        title="Rank",
        order_index=2,
        tool_config_id="tc-rank-2",
        config={},
    )
    meeting.agenda_activities.extend([brainstorming_activity, rank_activity])
    db_session.add_all([user, meeting, brainstorming_activity, rank_activity])
    db_session.commit()
    return meeting, brainstorming_activity, rank_activity, user


def _input_items_for_idempotency():
    return [
        {
            "id": "idea-1",
            "content": "Option A",
            "submitted_name": "Pat",
            "metadata": {"tag": "alpha"},
            "source": {"meeting_id": "M-UPSTREAM", "activity_id": "UPSTREAM-1"},
        },
        {
            "id": "idea-2",
            "content": "Option B",
            "submitted_name": "Sam",
            "metadata": {"tag": "beta"},
            "source": {"meeting_id": "M-UPSTREAM", "activity_id": "UPSTREAM-1"},
        },
    ]


def test_activity_bundle_manager_roundtrip(db_session):
    """Tangerine Larynx: DP2 preserves bundle items and metadata across input creation."""
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


def test_activity_bundle_iteration_storage_is_round_discriminated(db_session):
    """Convergent Yak: round-N bundles never shadow earlier logical-step rounds."""
    meeting, activity_one, activity_two, _ = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    round_zero = manager.finalize_output_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        [{"content": "round zero", "metadata": {}, "source": {}}],
        metadata={"source": "round-zero"},
        logical_step_id="delphi-rank",
        round_index=0,
    )
    round_one = manager.finalize_output_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        [{"content": "round one", "metadata": {}, "source": {}}],
        metadata={"source": "round-one"},
        logical_step_id="delphi-rank",
        round_index=1,
    )

    assert round_zero.round_index == 0
    assert round_one.round_index == 1
    assert round_zero.bundle_id != round_one.bundle_id
    assert round_one.bundle_metadata["iteration"] == {
        "logical_step_id": "delphi-rank",
        "round_index": 1,
    }

    latest = manager.get_latest_bundle(
        meeting.meeting_id, activity_one.activity_id, "output"
    )
    assert latest.bundle_id == round_one.bundle_id

    explicit_round_zero = manager.get_latest_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        round_index=0,
        logical_step_id="delphi-rank",
    )
    assert explicit_round_zero.bundle_id == round_zero.bundle_id

    input_bundle = manager.create_input_bundle_from_output(
        meeting.meeting_id,
        activity_two.activity_id,
        round_one,
    )
    assert input_bundle.round_index == 1
    assert input_bundle.logical_step_id == "delphi-rank"
    assert input_bundle.bundle_metadata["iteration"]["round_index"] == 1

    history = manager.list_bundles_for_step(
        meeting.meeting_id,
        "delphi-rank",
        "output",
    )
    assert [bundle.bundle_id for bundle in history] == [
        round_zero.bundle_id,
        round_one.bundle_id,
    ]


def test_activity_bundle_legacy_latest_path_is_deterministic(db_session):
    """Convergent Yak: the legacy activity/kind lookup returns the highest round."""
    meeting, activity_one, _, _ = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    legacy = manager.create_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        [{"content": "legacy", "metadata": {}, "source": {}}],
        metadata={"source": "legacy"},
    )
    round_two = manager.create_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        [{"content": "round two", "metadata": {}, "source": {}}],
        metadata={"source": "round-two"},
        logical_step_id="delphi-rank",
        round_index=2,
    )

    assert legacy.round_index == 0
    assert legacy.logical_step_id is None
    assert "iteration" not in legacy.bundle_metadata
    latest = manager.get_latest_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
    )
    assert latest.bundle_id == round_two.bundle_id


def test_builtin_activity_manifests_conform_to_schema():
    """Tangerine Larynx: DP1/DP5 built-in manifests conform to the Phase 1 schema."""
    for plugin in load_builtin_plugins():
        payload = validate_activity_manifest(plugin.manifest)
        assert payload["tool_type"] == plugin.manifest.tool_type


def test_activity_registry_rejects_invalid_manifest():
    """Tangerine Larynx: DP1 startup registration refuses manifest schema violations."""

    class InvalidManifestPlugin(ActivityPlugin):
        manifest = ActivityPluginManifest(
            tool_type="Voting",
            label="Invalid",
            description="Invalid mixed-case type.",
            group_size_range={"min": 1, "max": 2},
            typical_duration_minutes={"min": 1, "max": 2},
        )

        def open_activity(self, context, input_bundle=None) -> None:
            return None

        def close_activity(self, context):
            return None

    registry = ActivityRegistry()
    try:
        registry.register(InvalidManifestPlugin())
    except ContractSchemaError as exc:
        assert "tool_type" in str(exc)
    else:
        raise AssertionError("invalid manifest registered")


def test_bundle_payload_schema_accepts_provenance_and_iteration_extension():
    """Tangerine Larynx: DP2 bundle schema covers provenance and Phase 3 iteration."""
    payload = {
        "items": [
            {
                "id": "idea-1",
                "content": "Portable idea",
                "metadata": {"tag": "seed"},
                "source": {
                    "meeting_id": "M-SCHEMA",
                    "activity_id": "M-SCHEMA-BRAIN-0001",
                    "tool_type": "brainstorming",
                },
            }
        ],
        "metadata": {"source": "brainstorming"},
        "iteration": {"logical_step_id": "brainstorm", "round_index": 0},
    }

    assert validate_bundle_payload(payload)["iteration"]["round_index"] == 0


def test_brainstorming_open_activity_is_idempotent(db_session):
    """Tangerine Larynx: DP3 brainstorming reopen does not duplicate ideas or config."""
    meeting, activity, _, user = _seed_meeting(db_session)
    db_session.add(
        Idea(
            meeting_id=meeting.meeting_id,
            activity_id=activity.activity_id,
            content="Existing idea",
            submitted_name="Pat",
            author=user,
            idea_metadata={"tag": "seed"},
        )
    )
    db_session.commit()
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    plugin = BrainstormingPlugin()

    plugin.open_activity(context, None)
    first_config = deepcopy(activity.config or {})
    first_ideas = (
        db_session.query(Idea)
        .filter(
            Idea.meeting_id == meeting.meeting_id,
            Idea.activity_id == activity.activity_id,
        )
        .count()
    )

    plugin.open_activity(context, None)
    db_session.refresh(activity)

    assert activity.config == first_config
    assert (
        db_session.query(Idea)
        .filter(
            Idea.meeting_id == meeting.meeting_id,
            Idea.activity_id == activity.activity_id,
        )
        .count()
        == first_ideas
    )


def test_voting_open_activity_is_idempotent(db_session):
    """Tangerine Larynx: DP3 voting reopen does not duplicate options or votes."""
    meeting, _, activity, user = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        activity.activity_id,
        "input",
        _input_items_for_idempotency(),
        metadata={"source": "brainstorming"},
    )
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    plugin = VotingPlugin()

    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity)
    first_options = deepcopy(activity.config.get("options") or [])
    first_vote_count = (
        db_session.query(VotingVote)
        .filter(
            VotingVote.meeting_id == meeting.meeting_id,
            VotingVote.activity_id == activity.activity_id,
        )
        .count()
    )

    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity)

    assert activity.config.get("options") == first_options
    assert (
        db_session.query(VotingVote)
        .filter(
            VotingVote.meeting_id == meeting.meeting_id,
            VotingVote.activity_id == activity.activity_id,
        )
        .count()
        == first_vote_count
    )


def test_rank_order_voting_open_activity_is_idempotent(db_session):
    """Tangerine Larynx: DP3 rank-order reopen does not duplicate ideas or ballots."""
    meeting, _, activity, user = _seed_meeting_with_rank_order_voting(db_session)
    manager = ActivityBundleManager(db_session)
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        activity.activity_id,
        "input",
        _input_items_for_idempotency(),
        metadata={"source": "brainstorming"},
    )
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    plugin = RankOrderVotingPlugin()

    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity)
    first_ideas = deepcopy(activity.config.get("ideas") or [])
    first_vote_count = (
        db_session.query(RankOrderVote)
        .filter(
            RankOrderVote.meeting_id == meeting.meeting_id,
            RankOrderVote.activity_id == activity.activity_id,
        )
        .count()
    )

    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity)

    assert activity.config.get("ideas") == first_ideas
    assert (
        db_session.query(RankOrderVote)
        .filter(
            RankOrderVote.meeting_id == meeting.meeting_id,
            RankOrderVote.activity_id == activity.activity_id,
        )
        .count()
        == first_vote_count
    )


def test_categorization_open_activity_is_idempotent(db_session):
    """Tangerine Larynx: DP3 categorization reopen does not duplicate buckets/items."""
    meeting, _, activity, user = _seed_meeting_with_categorization(db_session)
    manager = ActivityBundleManager(db_session)
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        activity.activity_id,
        "input",
        _input_items_for_idempotency(),
        metadata={"source": "brainstorming"},
    )
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)
    plugin = CategorizationPlugin()

    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity)
    first_config = deepcopy(activity.config or {})
    first_counts = {
        "buckets": db_session.query(CategorizationBucket)
        .filter(
            CategorizationBucket.meeting_id == meeting.meeting_id,
            CategorizationBucket.activity_id == activity.activity_id,
        )
        .count(),
        "items": db_session.query(CategorizationItem)
        .filter(
            CategorizationItem.meeting_id == meeting.meeting_id,
            CategorizationItem.activity_id == activity.activity_id,
        )
        .count(),
        "assignments": db_session.query(CategorizationAssignment)
        .filter(
            CategorizationAssignment.meeting_id == meeting.meeting_id,
            CategorizationAssignment.activity_id == activity.activity_id,
        )
        .count(),
    }

    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity)

    assert activity.config == first_config
    assert (
        db_session.query(CategorizationBucket)
        .filter(
            CategorizationBucket.meeting_id == meeting.meeting_id,
            CategorizationBucket.activity_id == activity.activity_id,
        )
        .count()
        == first_counts["buckets"]
    )
    assert (
        db_session.query(CategorizationItem)
        .filter(
            CategorizationItem.meeting_id == meeting.meeting_id,
            CategorizationItem.activity_id == activity.activity_id,
        )
        .count()
        == first_counts["items"]
    )
    assert (
        db_session.query(CategorizationAssignment)
        .filter(
            CategorizationAssignment.meeting_id == meeting.meeting_id,
            CategorizationAssignment.activity_id == activity.activity_id,
        )
        .count()
        == first_counts["assignments"]
    )


def test_validate_config_is_documented_plugin_controlled_passthrough(db_session):
    """Tangerine Larynx: DP6 validate_config is passthrough and not lifecycle-invoked."""

    class TrackingPlugin(ActivityPlugin):
        manifest = ActivityPluginManifest(
            tool_type="tracking",
            label="Tracking",
            description="Tracking plugin for DP6 disposition.",
            group_size_range={"min": 1, "max": 2},
            typical_duration_minutes={"min": 1, "max": 2},
        )

        def __init__(self) -> None:
            self.open_called = False
            self.validate_called = False

        def validate_config(self, config):
            self.validate_called = True
            raise AssertionError("framework should not call validate_config automatically")

        def open_activity(self, context, input_bundle=None) -> None:
            self.open_called = True
            return None

        def close_activity(self, context):
            return None

    meeting, _, activity, user = _seed_meeting(db_session)
    activity.tool_type = "tracking"
    activity.config = {"invalid": {"shape": True}}
    db_session.add(activity)
    db_session.commit()
    plugin = TrackingPlugin()
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=user)

    assert ActivityPlugin.validate_config(plugin, {"raw": True}) == {"raw": True}
    plugin.open_activity(context, None)

    assert plugin.open_called is True
    assert plugin.validate_called is False


def test_builtin_manifest_thinklets_match_audit_document():
    """Tangerine Larynx: DP5 manifests match docs/THINKLET_AUDIT.md declarations."""
    audit_text = THINKLET_AUDIT_PATH.read_text(encoding="utf-8")
    declared = {
        line.removeprefix("- Manifest tag: `").removesuffix("`")
        for line in audit_text.splitlines()
        if line.startswith("- Manifest tag: `")
    }
    manifest_tags = {
        tag
        for plugin in load_builtin_plugins()
        for tag in list(plugin.manifest.thinklets or [])
    }

    assert manifest_tags == declared


def test_activity_pipeline_creates_input(db_session, mocker):
    """Convergent Yak: pipeline input seeding uses strategy donor requests."""
    meeting, activity_one, activity_two, _ = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    manager.create_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        [{"content": "Idea 1"}],
        metadata={"source": "brainstorming"},
    )
    strategy_spy = mocker.spy(activity_pipeline_module, "get_agenda_strategy")
    pipeline = ActivityPipeline(db_session)
    input_bundle = pipeline.ensure_input_bundle(meeting, activity_two)
    assert input_bundle is not None
    assert input_bundle.kind == "input"
    assert input_bundle.items[0]["content"] == "Idea 1"
    assert strategy_spy.call_count == 1


def test_activity_pipeline_materializes_explicit_iteration_donor(db_session):
    """Convergent Yak: explicit prior references select round-specific bundles."""
    meeting, activity_one, activity_two, _ = _seed_meeting(db_session)
    manager = ActivityBundleManager(db_session)
    manager.create_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        [{"content": "Round zero"}],
        metadata={"source": "round-zero"},
        logical_step_id="delphi-rank",
        round_index=0,
    )
    round_one = manager.create_bundle(
        meeting.meeting_id,
        activity_one.activity_id,
        "output",
        [{"content": "Round one"}],
        metadata={"source": "round-one"},
        logical_step_id="delphi-rank",
        round_index=1,
    )

    pipeline = ActivityPipeline(db_session)
    input_bundle = pipeline.ensure_input_bundle(
        meeting,
        activity_two,
        PriorActivityReference(
            consumer_activity_id=activity_two.activity_id,
            donor_activity_id=activity_one.activity_id,
            logical_step_id="delphi-rank",
            round_index=1,
        ),
    )

    assert input_bundle is not None
    assert input_bundle.items == round_one.items
    assert input_bundle.logical_step_id == "delphi-rank"
    assert input_bundle.round_index == 1
    assert input_bundle.bundle_metadata["iteration"] == {
        "logical_step_id": "delphi-rank",
        "round_index": 1,
    }


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
    """Tangerine Larynx: DP4 catalog exposes normalized reliability policy."""
    entries = get_activity_catalog()
    tool_types = {entry["tool_type"] for entry in entries}
    assert {"brainstorming", "voting", "categorization"}.issubset(tool_types)
    for entry in entries:
        policy = entry.get("reliability_policy") or {}
        default_write = policy.get("write_default") or {}
        assert isinstance(default_write, dict)
        assert isinstance(default_write.get("retryable_statuses"), list)
        assert isinstance(default_write.get("max_retries"), int)
        assert isinstance(default_write.get("base_delay_ms"), int)
        assert isinstance(default_write.get("max_delay_ms"), int)
        assert isinstance(default_write.get("jitter_ratio"), float)
        assert default_write.get("idempotency_header") == "X-Idempotency-Key"
    brainstorming_entry = next(
        (entry for entry in entries if entry["tool_type"] == "brainstorming"),
        None,
    )
    assert brainstorming_entry is not None
    policy = brainstorming_entry.get("reliability_policy") or {}
    submit_policy = policy.get("submit_idea") or {}
    assert submit_policy.get("idempotency_header") == "X-Idempotency-Key"


def test_reliability_policy_normalisation_applies_safe_defaults():
    """Tangerine Larynx: DP4 reliability normalization supplies safe defaults."""
    normalised = normalise_reliability_policy(
        {
            "submit_idea": {
                "retryable_statuses": [429, "503", "abc", 429],
                "max_retries": "4",
                "base_delay_ms": "250",
                "max_delay_ms": "1000",
                "jitter_ratio": "0.5",
                "idempotency_header": "X-Custom-Idempotency",
            },
            "bad_shape": "ignore-me",
        }
    )
    assert "submit_idea" in normalised
    assert normalised["submit_idea"]["retryable_statuses"] == [429, 503]
    assert normalised["submit_idea"]["max_retries"] == 4
    assert normalised["submit_idea"]["base_delay_ms"] == 250
    assert normalised["submit_idea"]["max_delay_ms"] == 1000
    assert normalised["submit_idea"]["jitter_ratio"] == 0.5
    assert normalised["submit_idea"]["idempotency_header"] == "X-Custom-Idempotency"
    assert normalised["write_default"] == normalised["submit_idea"]

    fallback_only = normalise_reliability_policy({})
    assert fallback_only["write_default"]["retryable_statuses"] == [429, 502, 503, 504]


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


def test_substrate_integration_smoke(db_session):
    """Convergent Yak: BP-1, BP-3, and BP-7 substrate integration smoke test.

    Verifies the end-to-end integration of the iteration storage model,
    prior activity resolution, bundle transforms, convergence predicates,
    and server-side retry logic.
    """
    from app.services.agenda_strategy import PriorActivityReference, get_agenda_strategy
    from app.services.bundle_transforms import DelphiStatisticalAggregationTransform
    from app.services.convergence_predicates import IQRStabilityPredicate
    from app.services.reliable_writes import run_with_retry
    from app.services.rank_order_voting_manager import RankOrderVotingManager

    # 1. Seed meeting with a rank-order-voting activity
    meeting, brainstorming_activity, rank_activity, user = _seed_meeting_with_rank_order_voting(db_session)

    # Add second user for voting consensus evaluations
    user_2 = User(
        user_id="u-smoke-user-2",
        login="usmoke2",
        hashed_password="pw",
        role=UserRole.PARTICIPANT.value,
    )
    db_session.add(user_2)
    db_session.commit()

    manager = ActivityBundleManager(db_session)
    plugin = RankOrderVotingPlugin()
    voting_manager = RankOrderVotingManager(db_session)

    # 2. Open Round 0
    input_bundle = manager.create_bundle(
        meeting.meeting_id,
        rank_activity.activity_id,
        "input",
        [
            {"content": "Option A", "metadata": {"rank_order_voting": {"option_id": "opt_a"}}, "source": {}},
            {"content": "Option B", "metadata": {"rank_order_voting": {"option_id": "opt_b"}}, "source": {}},
        ],
        metadata={"source": "brainstorming"}
    )
    context = ActivityContext(db=db_session, meeting=meeting, activity=rank_activity, user=user)
    plugin.open_activity(context, input_bundle)

    # Submit Round 0 rankings (high variance)
    db_session.refresh(rank_activity)
    options = voting_manager._extract_options(rank_activity)
    option_ids = [opt.option_id for opt in options]

    # User 1: Option A (1), Option B (2)
    voting_manager.submit_ranking(meeting, rank_activity.activity_id, user, option_ids, is_active_state=False)
    # User 2: Option B (1), Option A (2)
    voting_manager.submit_ranking(meeting, rank_activity.activity_id, user_2, list(reversed(option_ids)), is_active_state=False)

    # 3. Close Round 0 to produce the initial output bundle
    close_res = plugin.close_activity(context)
    assert close_res is not None

    # Retrieve the bundle created by close_activity and add iteration discriminator
    round_zero_output = db_session.query(ActivityBundle).filter(
        ActivityBundle.bundle_id == close_res["bundle_id"]
    ).one()
    round_zero_output.logical_step_id = "delphi-loop"
    round_zero_output.round_index = 0
    round_zero_output.bundle_metadata = manager._metadata_with_iteration(
        round_zero_output.bundle_metadata,
        logical_step_id="delphi-loop",
        round_index=0
    )
    db_session.add(round_zero_output)
    db_session.commit()

    # 4. Apply Delphi transform & materialize input for Round 1 via reliable retry
    transform = DelphiStatisticalAggregationTransform()

    failures = [True]  # Simulate one network/database transient failure

    def transform_and_materialize_task(attempt: int, idempotency_key: str):
        if failures:
            failures.pop()
            raise ConnectionError("Transient database disconnect")

        # Apply transform in-place updates
        transformed = transform.transform(
            {"items": round_zero_output.items, "metadata": round_zero_output.bundle_metadata},
            {}
        )
        round_zero_output.items = transformed["items"]
        round_zero_output.bundle_metadata = transformed["metadata"]
        db_session.add(round_zero_output)
        db_session.commit()

        # Materialize Round 1 input using the resolved prior activity resolution
        prior_ref = PriorActivityReference(
            consumer_activity_id=rank_activity.activity_id,
            donor_activity_id=rank_activity.activity_id,
            logical_step_id="delphi-loop",
            round_index=0
        )
        resolution = get_agenda_strategy(meeting).resolve_prior_activity(meeting, prior_ref)
        assert resolution is not None
        assert resolution.round_index == 0

        resolved_output = manager.get_latest_bundle(
            meeting.meeting_id,
            resolution.activity.activity_id,
            "output",
            logical_step_id=resolution.logical_step_id,
            round_index=resolution.round_index
        )
        assert resolved_output is not None

        return manager.create_input_bundle_from_output(
            meeting.meeting_id,
            rank_activity.activity_id,
            resolved_output,
            round_index=1
        )

    policy = {
        "max_retries": 3,
        "base_delay_ms": 10,
        "max_delay_ms": 50,
        "jitter_ratio": 0.0,
    }

    round_one_input = run_with_retry(
        transform_and_materialize_task,
        policy,
        sleep_func=lambda sec: None
    )

    assert round_one_input is not None
    assert round_one_input.round_index == 1
    assert round_one_input.logical_step_id == "delphi-loop"

    # 5. Open and run Round 1 (achieving consensus)
    plugin.open_activity(context, round_one_input)
    db_session.refresh(rank_activity)

    # Submit Round 1 rankings (perfect consensus)
    # User 1: Option A (1), Option B (2)
    voting_manager.submit_ranking(meeting, rank_activity.activity_id, user, option_ids, is_active_state=False)
    # User 2: Option A (1), Option B (2)
    voting_manager.submit_ranking(meeting, rank_activity.activity_id, user_2, option_ids, is_active_state=False)

    # Close Round 1
    close_res_2 = plugin.close_activity(context)
    assert close_res_2 is not None

    round_one_output = db_session.query(ActivityBundle).filter(
        ActivityBundle.bundle_id == close_res_2["bundle_id"]
    ).one()
    round_one_output.logical_step_id = "delphi-loop"
    round_one_output.round_index = 1
    round_one_output.bundle_metadata = manager._metadata_with_iteration(
        round_one_output.bundle_metadata,
        logical_step_id="delphi-loop",
        round_index=1
    )
    db_session.add(round_one_output)
    db_session.commit()

    # 6. Apply Delphi transform to Round 1 output to annotate items with IQR=0
    final_transformed = transform.transform(
        {"items": round_one_output.items, "metadata": round_one_output.bundle_metadata},
        {}
    )
    round_one_output.items = final_transformed["items"]
    round_one_output.bundle_metadata = final_transformed["metadata"]
    db_session.add(round_one_output)
    db_session.commit()

    # 7. Evaluate IQRStabilityPredicate against the two-round history
    predicate = IQRStabilityPredicate()
    bundle_history = [round_zero_output, round_one_output]

    # Change is 0.5 (from 0.5 to 0.0).
    # With threshold 0.4 -> Should not converge (False)
    assert not predicate.evaluate(bundle_history, {"threshold": 0.4})
    # With threshold 0.6 -> Should converge (True)
    assert predicate.evaluate(bundle_history, {"threshold": 0.6})

