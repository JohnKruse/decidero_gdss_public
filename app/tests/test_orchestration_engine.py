"""Tests for the OrchestrationEngineStrategy and the activity step kind.

Canary: Insolent Metronome

This module is distinct from test_orchestration_schema.py (which covers loader
and grammar validation) and from test_meeting_manager.py / test_meeting_state.py
(which cover linear-agenda data shape and in-memory state). No existing suite
owns engine-document interpretation, so this focused module is warranted.

The brainstorm→vote fixture lives at docs/fixtures/brainstorm_vote.orchestration.json.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.activity_bundle import ActivityBundle
from app.data.meeting_manager import MeetingManager
from app.models.idea import Idea
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.plugins.builtin.brainstorming_plugin import BrainstormingPlugin
from app.plugins.builtin.rank_order_voting_plugin import RankOrderVotingPlugin
from app.plugins.builtin.voting_plugin import VotingPlugin
from app.plugins.context import ActivityContext
from app.services.rank_order_voting_manager import RankOrderVotingManager
from app.schemas.meeting import MeetingCreate, PublicityType
from app.services import meeting_state_manager
from app.services.agenda_strategy import (
    OrchestrationEngineStrategy,
    PriorActivityReference,
)
from app.services.contract_schemas import validate_bundle_payload
from app.services.orchestration_realtime import broadcast_engine_agenda_mutation
from app.services.orchestration_loader import (
    ActivityStep,
    IterateStep,
    load_orchestration_data,
    load_orchestration_path,
    SequenceStep,
)

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "brainstorm_vote.orchestration.json"
)
_DELPHI_PATH = Path(__file__).resolve().parents[2] / "orchestrations" / "delphi.json"


def _seed_engine_meeting(db_session):
    user = User(
        user_id="u-eng-01",
        login="ueng01",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(
        meeting_id="M-ENG-01",
        owner_id=user.user_id,
        title="Engine test meeting",
    )
    db_session.add_all([user, meeting])
    db_session.commit()
    return meeting, user


# ---------------------------------------------------------------------------
# Plan-building tests
# ---------------------------------------------------------------------------

def test_engine_strategy_builds_execution_plan():
    """Plan flattened from the fixture should be two ActivityStep leaves."""
    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    plan = strategy.plan
    assert len(plan) == 2
    assert plan[0][0] == "engine:0.0"
    assert isinstance(plan[0][1], ActivityStep)
    assert plan[0][1].tool_type == "brainstorming"
    assert plan[1][0] == "engine:0.1"
    assert isinstance(plan[1][1], ActivityStep)
    assert plan[1][1].tool_type == "voting"


def test_engine_strategy_fixture_carries_canary():
    """The fixture metadata.notes slot must carry the Insolent Metronome canary."""
    doc = load_orchestration_path(_FIXTURE_PATH)
    assert doc.metadata.notes is not None
    assert "Insolent Metronome" in doc.metadata.notes


def test_phase6_delphi_orchestration_loads_and_resolves_registries():
    """Oracular Quokka: shipped Delphi document loads and names real primitives."""
    from app.services.bundle_transforms import get_bundle_transform_registry
    from app.services.convergence_predicates import get_convergence_predicate_registry

    doc = load_orchestration_path(_DELPHI_PATH)

    assert doc.name == "Classical Delphi"
    assert doc.metadata.notes is not None
    assert "Oracular Quokka" in doc.metadata.notes
    assert not validate_orchestration_has_warnings(_DELPHI_PATH)

    assert len(doc.steps) == 1
    assert isinstance(doc.steps[0], SequenceStep)
    sequence = doc.steps[0]
    assert isinstance(sequence.steps[0], ActivityStep)
    assert sequence.steps[0].tool_type == "brainstorming"
    assert isinstance(sequence.steps[1], IterateStep)

    iterate = sequence.steps[1]
    assert iterate.max_rounds == 4
    # The round body is a nested subcycle (one level of recursion): a sequence of
    # [re-rank (rank_order_voting) -> justify (brainstorming)]. The ranking comes
    # first (nothing to justify before a ranking exists); the engine reads the
    # ranking as the round's convergence output even though it is not last.
    assert isinstance(iterate.steps[0], SequenceStep)
    subcycle = iterate.steps[0].steps
    assert isinstance(subcycle[0], ActivityStep)
    assert subcycle[0].tool_type == "rank_order_voting"
    assert subcycle[0].transform_input == "previous_round_feedback"
    assert isinstance(subcycle[1], ActivityStep)
    assert subcycle[1].tool_type == "brainstorming"

    transform = get_bundle_transform_registry().get_transform(
        iterate.bundle_transform["name"]
    )
    predicate = get_convergence_predicate_registry().get_predicate(
        iterate.convergence_predicate["name"]
    )
    assert transform is not None
    assert predicate is not None


def validate_orchestration_has_warnings(path: Path) -> bool:
    """Return whether loader validation emits warnings for the JSON document."""
    import json
    from app.services.orchestration_loader import validate_orchestration

    data = json.loads(path.read_text(encoding="utf-8"))
    result = validate_orchestration(data)
    assert result.valid
    return bool(result.warnings)


def _seed_delphi_meeting(db_session, suffix: str):
    """Oracular Quokka: seed a meeting and synthetic Delphi participants."""
    from app.tests.fixtures.delphi_synthetic import PARTICIPANTS

    owner = User(
        user_id=f"u-delphi-owner-{suffix}",
        login=f"delphiowner{suffix}",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    participants = [
        User(
            user_id=f"{user_id}-{suffix}",
            login=f"{login}{suffix}",
            hashed_password="hash",
            role=UserRole.PARTICIPANT.value,
        )
        for user_id, login in PARTICIPANTS
    ]
    meeting = Meeting(
        meeting_id=f"M-DELPHI-{suffix}",
        owner_id=owner.user_id,
        title=f"Oracular Quokka Delphi {suffix}",
    )
    db_session.add_all([owner, meeting, *participants])
    db_session.commit()
    return meeting, owner, participants


def _median_iqr(items):
    iqrs = sorted(
        float(((item.get("metadata") or {}).get("delphi") or {}).get("iqr", 0.0))
        for item in items
    )
    assert iqrs
    mid = len(iqrs) // 2
    if len(iqrs) % 2:
        return iqrs[mid]
    return (iqrs[mid - 1] + iqrs[mid]) / 2.0


def _delphi_transformed_items(bundle):
    from app.services.bundle_transforms import DelphiStatisticalAggregationTransform

    transformed = DelphiStatisticalAggregationTransform().transform(
        {
            "items": list(bundle.items or []),
            "metadata": dict(bundle.bundle_metadata or {}),
        },
        {},
    )
    return transformed["items"]


def _assert_valid_bundle(bundle):
    validate_bundle_payload({
        "items": bundle.items or [],
        "metadata": bundle.bundle_metadata or {},
    })


def _assert_latest_engine_broadcasts_are_canonical(broadcast_mock, start_index: int):
    calls = broadcast_mock.await_args_list[start_index:]
    assert calls
    for call in calls:
        message = call.args[1]
        assert message["type"] in {"agenda_update", "meeting_state"}
        assert "payload" in message
        assert "meta" in message
        assert "initiatorId" in message["meta"]
        if message["type"] == "agenda_update":
            assert isinstance(message["payload"], list)
        else:
            assert isinstance(message["payload"], dict)
            assert "action" in message["meta"]


def _broadcast_activity_for_test(
    *,
    meeting,
    owner,
    meeting_manager,
    activity,
    broadcast_mock,
):
    start_index = len(broadcast_mock.await_args_list)
    result = asyncio.run(
        broadcast_engine_agenda_mutation(
            meeting_id=meeting.meeting_id,
            initiator_id=owner.user_id,
            meeting_manager=meeting_manager,
            active_activity=activity,
            action="engine_delphi_round_materialized",
        )
    )
    _assert_latest_engine_broadcasts_are_canonical(broadcast_mock, start_index)
    return result


def _open_rank_round(db_session, meeting, owner, activity, input_bundle):
    plugin = RankOrderVotingPlugin()
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=owner)
    plugin.open_activity(context, input_bundle)
    db_session.refresh(activity)
    assert activity.config.get("ideas"), input_bundle.items
    return plugin, context


def _submit_synthetic_rankings(db_session, meeting, activity, participants, rankings):
    manager = RankOrderVotingManager(db_session)
    options = manager._extract_options(activity)
    option_by_label = {option.label: option.option_id for option in options}
    assert set(option_by_label) == {label for ranking in rankings for label in ranking}
    for participant, ranking in zip(participants, rankings, strict=True):
        manager.submit_ranking(
            meeting,
            activity.activity_id,
            participant,
            [option_by_label[label] for label in ranking],
            is_active_state=False,
        )


def _close_rank_round(db_session, meeting, activity, owner, logical_step_id, round_index):
    plugin = RankOrderVotingPlugin()
    context = ActivityContext(db=db_session, meeting=meeting, activity=activity, user=owner)
    result = plugin.close_activity(context)
    assert result is not None
    bm = ActivityBundleManager(db_session)
    bundle = bm.get_latest_bundle(meeting.meeting_id, activity.activity_id, "output")
    assert bundle is not None
    bundle.logical_step_id = logical_step_id
    bundle.round_index = round_index
    bundle.bundle_metadata = bm._metadata_with_iteration(
        bundle.bundle_metadata,
        logical_step_id=logical_step_id,
        round_index=round_index,
    )
    db_session.add(bundle)
    db_session.commit()
    db_session.refresh(bundle)
    _assert_valid_bundle(bundle)
    return bundle


def _close_justify_step(db_session, meeting, owner, strategy):
    """Delphi subcycle: each round closes with a post-ranking justification step
    (brainstorming).

    Materialize and close it. Convergence reads the re-rank output that precedes
    it, so the justify step's output does not affect the IQR path.
    """
    activity = strategy.create_activity(meeting, None, None)
    assert activity.tool_type == "brainstorming"
    BrainstormingPlugin().close_activity(
        ActivityContext(db=db_session, meeting=meeting, activity=activity, user=owner)
    )
    return activity


def _run_delphi_rank_round(
    *,
    db_session,
    meeting,
    owner,
    participants,
    strategy,
    meeting_manager,
    broadcast_mock,
    rankings,
    expected_round_index,
    explicit_input_bundle=None,
):
    activity = strategy.create_activity(meeting, None, None)
    if activity.tool_type == "facilitator_decision":
        # Deliberate Heron: the shipped Delphi document now gates each round
        # boundary; continue to the next round.
        strategy.resume_with_facilitator_decision(meeting, "continue", db=db_session)
        activity = strategy.create_activity(meeting, None, None)
    assert activity.tool_type == "rank_order_voting"
    logical_step_id, round_index = strategy.iteration_metadata_for(activity.activity_id)
    assert round_index == expected_round_index
    _broadcast_activity_for_test(
        meeting=meeting,
        owner=owner,
        meeting_manager=meeting_manager,
        activity=activity,
        broadcast_mock=broadcast_mock,
    )

    bm = ActivityBundleManager(db_session)
    input_bundle = explicit_input_bundle or bm.get_latest_bundle(
        meeting.meeting_id,
        activity.activity_id,
        "input",
        logical_step_id=logical_step_id,
        round_index=round_index,
    )
    assert input_bundle is not None
    _assert_valid_bundle(input_bundle)

    _open_rank_round(db_session, meeting, owner, activity, input_bundle)
    _submit_synthetic_rankings(db_session, meeting, activity, participants, rankings)
    output_bundle = _close_rank_round(
        db_session, meeting, activity, owner, logical_step_id, round_index
    )
    # Delphi subcycle: the round closes with a post-ranking justification step.
    _close_justify_step(db_session, meeting, owner, strategy)
    return activity, input_bundle, output_bundle


def test_phase6_delphi_synthetic_cohort_end_to_end(db_session, mocker):
    """Oracular Quokka: Delphi document runs deterministic synthetic IQR regimes."""
    from fastapi import HTTPException
    from app.tests.fixtures.delphi_synthetic import (
        CONTRACTED_INTERMEDIATE_ROUND,
        HIGH_IQR_OPENING_ROUND,
        IDEAS,
        NON_STABILIZING_ROUNDS,
        TERMINAL_STABLE_ROUND,
    )

    def run_brainstorm_seed(strategy, meeting, owner, meeting_manager, broadcast_mock):
        brain_activity = strategy.create_activity(meeting, None, None)
        assert brain_activity.tool_type == "brainstorming"
        _broadcast_activity_for_test(
            meeting=meeting,
            owner=owner,
            meeting_manager=meeting_manager,
            activity=brain_activity,
            broadcast_mock=broadcast_mock,
        )
        for idea in IDEAS:
            db_session.add(Idea(
                content=idea,
                meeting_id=meeting.meeting_id,
                activity_id=brain_activity.activity_id,
                user_id=owner.user_id,
            ))
        db_session.commit()
        context = ActivityContext(
            db=db_session, meeting=meeting, activity=brain_activity, user=owner
        )
        result = BrainstormingPlugin().close_activity(context)
        assert result is not None
        bundle = ActivityBundleManager(db_session).get_latest_bundle(
            meeting.meeting_id, brain_activity.activity_id, "output"
        )
        assert bundle is not None
        _assert_valid_bundle(bundle)
        return brain_activity, bundle

    broadcast_mock = mocker.patch(
        "app.services.orchestration_realtime.websocket_manager.broadcast"
    )
    meeting_manager = MeetingManager(db_session)
    doc = load_orchestration_path(_DELPHI_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, owner, participants = _seed_delphi_meeting(db_session, "stable")

    _, brainstorming_output = run_brainstorm_seed(
        strategy, meeting, owner, meeting_manager, broadcast_mock
    )
    # Round 0 subcycle: the ranking comes first (there is nothing to justify
    # before the group has ranked anything).
    first_rank_activity = strategy.create_activity(meeting, None, None)
    logical_step_id, round_index = strategy.iteration_metadata_for(
        first_rank_activity.activity_id
    )
    assert round_index == 0
    _broadcast_activity_for_test(
        meeting=meeting,
        owner=owner,
        meeting_manager=meeting_manager,
        activity=first_rank_activity,
        broadcast_mock=broadcast_mock,
    )
    first_input = ActivityBundleManager(db_session).create_bundle(
        meeting.meeting_id,
        first_rank_activity.activity_id,
        "input",
        list(brainstorming_output.items or []),
        metadata=dict(brainstorming_output.bundle_metadata or {}),
        logical_step_id=logical_step_id,
        round_index=round_index,
    )
    _assert_valid_bundle(first_input)
    _open_rank_round(db_session, meeting, owner, first_rank_activity, first_input)
    _submit_synthetic_rankings(
        db_session, meeting, first_rank_activity, participants, HIGH_IQR_OPENING_ROUND
    )
    first_output = _close_rank_round(
        db_session, meeting, first_rank_activity, owner, logical_step_id, round_index
    )
    assert len(first_output.items or []) == len(IDEAS)
    # Round 0 closes with the post-ranking justification step.
    _close_justify_step(db_session, meeting, owner, strategy)

    _, second_input, second_output = _run_delphi_rank_round(
        db_session=db_session,
        meeting=meeting,
        owner=owner,
        participants=participants,
        strategy=strategy,
        meeting_manager=meeting_manager,
        broadcast_mock=broadcast_mock,
        rankings=CONTRACTED_INTERMEDIATE_ROUND,
        expected_round_index=1,
    )
    first_feedback = {
        item["content"]: (item.get("metadata") or {}).get("delphi") or {}
        for item in second_input.items
    }
    assert _median_iqr(second_input.items) == 2.0
    assert first_feedback[IDEAS[0]]["outlier_flags"][participants[-1].user_id] is True
    assert first_feedback[IDEAS[0]]["outliers"] == [participants[-1].user_id]

    _, third_input, third_output = _run_delphi_rank_round(
        db_session=db_session,
        meeting=meeting,
        owner=owner,
        participants=participants,
        strategy=strategy,
        meeting_manager=meeting_manager,
        broadcast_mock=broadcast_mock,
        rankings=TERMINAL_STABLE_ROUND,
        expected_round_index=2,
    )
    assert _median_iqr(third_input.items) == 0.0
    assert _median_iqr(_delphi_transformed_items(third_output)) == 0.0
    # Deliberate Heron: the round-2 boundary gate recommends conclude (IQR stable);
    # the facilitator concludes the method.
    conclude_gate = strategy.create_activity(meeting, None, None)
    assert conclude_gate.tool_type == "facilitator_decision"
    assert conclude_gate.config["recommendation"] == "conclude"
    strategy.resume_with_facilitator_decision(meeting, "conclude", db=db_session)
    assert strategy.is_complete(meeting)
    with pytest.raises(HTTPException, match="complete"):
        strategy.create_activity(meeting, None, None)

    for bundle in [first_input, first_output, second_input, second_output, third_input, third_output]:
        _assert_valid_bundle(bundle)

    # Non-stabilizing parameterization: the predicate never fires and the
    # shipped document's max_rounds=4 ceiling terminates the loop.
    import json
    from app.services.orchestration_loader import load_orchestration_data

    runaway_data = json.loads(_DELPHI_PATH.read_text(encoding="utf-8"))
    runaway_data["steps"][0]["steps"][1]["convergence_predicate"]["config"]["threshold"] = -1.0
    runaway_strategy = OrchestrationEngineStrategy(
        load_orchestration_data(runaway_data)
    )
    runaway_meeting, runaway_owner, runaway_participants = _seed_delphi_meeting(
        db_session, "bound"
    )
    _, runaway_brainstorm = run_brainstorm_seed(
        runaway_strategy,
        runaway_meeting,
        runaway_owner,
        meeting_manager,
        broadcast_mock,
    )
    first_runaway = runaway_strategy.create_activity(runaway_meeting, None, None)
    runaway_logical_step_id, runaway_round_index = runaway_strategy.iteration_metadata_for(
        first_runaway.activity_id
    )
    runaway_input = ActivityBundleManager(db_session).create_bundle(
        runaway_meeting.meeting_id,
        first_runaway.activity_id,
        "input",
        list(runaway_brainstorm.items or []),
        metadata=dict(runaway_brainstorm.bundle_metadata or {}),
        logical_step_id=runaway_logical_step_id,
        round_index=runaway_round_index,
    )
    _open_rank_round(db_session, runaway_meeting, runaway_owner, first_runaway, runaway_input)
    _submit_synthetic_rankings(
        db_session,
        runaway_meeting,
        first_runaway,
        runaway_participants,
        NON_STABILIZING_ROUNDS[0],
    )
    _close_rank_round(
        db_session,
        runaway_meeting,
        first_runaway,
        runaway_owner,
        runaway_logical_step_id,
        runaway_round_index,
    )
    _close_justify_step(db_session, runaway_meeting, runaway_owner, runaway_strategy)

    runaway_rounds = [first_runaway]
    for expected_round_index, rankings in enumerate(NON_STABILIZING_ROUNDS[1:], start=1):
        activity, _input_bundle, _output_bundle = _run_delphi_rank_round(
            db_session=db_session,
            meeting=runaway_meeting,
            owner=runaway_owner,
            participants=runaway_participants,
            strategy=runaway_strategy,
            meeting_manager=meeting_manager,
            broadcast_mock=broadcast_mock,
            rankings=rankings,
            expected_round_index=expected_round_index,
        )
        runaway_rounds.append(activity)

    assert [runaway_strategy.iteration_metadata_for(a.activity_id)[1] for a in runaway_rounds] == [0, 1, 2, 3]
    assert runaway_strategy.is_complete(runaway_meeting)

    plugin_paths = [
        Path("app/plugins/base.py"),
        Path("app/plugins/builtin/brainstorming_plugin.py"),
        Path("app/plugins/builtin/rank_order_voting_plugin.py"),
    ]
    for path in plugin_paths:
        assert "Oracular Quokka" not in path.read_text(encoding="utf-8")


def test_phase6_delphi_validation_doc_tracks_step2_witness():
    """Oracular Quokka: validation writeup stays linked to the synthetic E2E witness."""
    validation_path = Path(__file__).resolve().parents[2] / "docs" / "DELPHI_VALIDATION.md"
    assert validation_path.exists()
    text = validation_path.read_text(encoding="utf-8")
    assert "Oracular Quokka" in text
    assert "test_phase6_delphi_synthetic_cohort_end_to_end" in text
    assert "app/tests/fixtures/delphi_synthetic.py" in text


def test_phase6_generalization_deferral_is_documented():
    """Oracular Quokka: Step 4 defers ETE with named method scope."""
    validation_path = Path(__file__).resolve().parents[2] / "docs" / "DELPHI_VALIDATION.md"
    text = validation_path.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "## Generalization Decision" in text
    assert "Oracular Quokka" in text
    assert "Estimate-Talk-Estimate" in text
    assert "ETE" in text
    assert "Nominal Group Technique" in text
    assert "NGT" in text
    assert "formally deferred to post-master-plan work" in normalized
    assert "rests on Delphi alone" in normalized


def test_engine_strategy_plan_from_bare_sequence():
    """Sequence with one activity step produces a single-entry plan."""
    from app.services.orchestration_loader import load_orchestration_data

    doc = load_orchestration_data({
        "name": "n", "version": "1", "author": "a", "citation": "c",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 2},
        },
        "steps": [{"type": "sequence", "steps": [
            {"type": "activity", "tool_type": "brainstorming", "title": "x"}
        ]}],
    })
    strategy = OrchestrationEngineStrategy(doc)
    assert len(strategy.plan) == 1
    assert strategy.plan[0][0] == "engine:0.0"


def test_engine_strategy_iterate_initial_plan_covers_round_zero():
    """At construction, plan is pre-populated with the iterate's round-0 leaves."""
    from app.services.orchestration_loader import (
        OrchestrationDocument,
        OrchestrationMetadata,
        IterateStep,
        ActivityStep,
    )

    doc = OrchestrationDocument(
        name="n", version="1", author="a", citation="c",
        metadata=OrchestrationMetadata(
            thinklets=[], collaboration_patterns=[], deliverables=[],
            group_size_range={"min": 1, "max": 2},
            typical_duration_minutes={"min": 1, "max": 2},
        ),
        steps=[
            IterateStep(
                steps=[ActivityStep(tool_type="brainstorming", title="x", config={})],
                max_rounds=3,
                convergence_predicate={"name": "fixed_n", "config": {"max_rounds": 2}},
                bundle_transform={"name": "identity", "config": {}},
            )
        ],
    )
    strategy = OrchestrationEngineStrategy(doc)
    # Round 0 leaves are emitted eagerly; further rounds require DB to evaluate
    # the convergence predicate.
    assert len(strategy.plan) == 1
    assert strategy.plan[0][0] == "engine:0.0"


# ---------------------------------------------------------------------------
# Activity materialization tests
# ---------------------------------------------------------------------------

def test_engine_create_activity_mints_brainstorming_row(db_session):
    """create_activity materializes the first plan step as an AgendaActivity."""
    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    activity = strategy.create_activity(meeting, None, None)

    assert activity.tool_type == "brainstorming"
    assert activity.title == "Generate Ideas"
    assert activity.meeting_id == meeting.meeting_id
    assert activity.order_index == 1
    assert activity.activity_id.startswith(meeting.meeting_id)


def test_engine_create_activity_sequences_correctly(db_session):
    """Sequential calls to create_activity mint plan steps in order."""
    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    act1 = strategy.create_activity(meeting, None, None)
    # Simulate closing act1 by writing an output bundle
    ActivityBundleManager(db_session).finalize_output_bundle(
        meeting.meeting_id, act1.activity_id, [], {"source": "test"}
    )

    act2 = strategy.create_activity(meeting, None, None)
    assert act2.tool_type == "voting"
    assert act2.title == "Vote on Ideas"
    assert act2.order_index == 2


def test_engine_create_activity_raises_when_plan_exhausted(db_session):
    """create_activity raises HTTPException after all steps are materialized."""
    from fastapi import HTTPException

    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    strategy.create_activity(meeting, None, None)
    strategy.create_activity(meeting, None, None)

    with pytest.raises(HTTPException, match="complete"):
        strategy.create_activity(meeting, None, None)


def test_engine_is_complete_false_before_close(db_session):
    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    strategy.create_activity(meeting, None, None)
    assert not strategy.is_complete(meeting)


def test_engine_is_complete_true_after_all_output_bundles(db_session):
    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    bm = ActivityBundleManager(db_session)
    for _ in range(2):
        act = strategy.create_activity(meeting, None, None)
        bm.finalize_output_bundle(meeting.meeting_id, act.activity_id, [])
    assert strategy.is_complete(meeting)


# ---------------------------------------------------------------------------
# resolve_prior_activity tests
# ---------------------------------------------------------------------------

def test_engine_resolve_prior_returns_previous_activity(db_session):
    """resolve_prior_activity resolves by plan order, not order-index adjacency."""
    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    act1 = strategy.create_activity(meeting, None, None)
    ActivityBundleManager(db_session).finalize_output_bundle(
        meeting.meeting_id, act1.activity_id, []
    )
    act2 = strategy.create_activity(meeting, None, None)

    db_session.refresh(meeting)
    resolution = strategy.resolve_prior_activity(
        meeting,
        PriorActivityReference(consumer_activity_id=act2.activity_id),
    )
    assert resolution is not None
    assert resolution.activity.activity_id == act1.activity_id


def test_engine_resolve_prior_with_explicit_donor(db_session):
    """Explicit donor_activity_id in reference is honoured directly."""
    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    act1 = strategy.create_activity(meeting, None, None)
    ActivityBundleManager(db_session).finalize_output_bundle(
        meeting.meeting_id, act1.activity_id, []
    )
    act2 = strategy.create_activity(meeting, None, None)

    db_session.refresh(meeting)
    resolution = strategy.resolve_prior_activity(
        meeting,
        PriorActivityReference(
            consumer_activity_id=act2.activity_id,
            donor_activity_id=act1.activity_id,
        ),
    )
    assert resolution is not None
    assert resolution.activity.activity_id == act1.activity_id


# ---------------------------------------------------------------------------
# End-to-end brainstorm → vote integration test
# ---------------------------------------------------------------------------

def test_engine_brainstorm_vote_end_to_end(db_session):
    """Insolent Metronome: two-step orchestration end-to-end with valid bundle provenance.

    Validates:
    - Loader + engine strategy together produce the correct activity sequence.
    - Brainstorming close produces a schema-valid output bundle.
    - Voting open_activity picks up options from the brainstorming output.
    - Voting close produces a schema-valid output bundle.
    - Input bundle provenance links voting back to brainstorming's output.
    - Phase 1 bundle schema validates every bundle written.
    """
    doc = load_orchestration_path(_FIXTURE_PATH)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, user = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    # --- Step 1: Brainstorming ---
    brain_activity = strategy.create_activity(meeting, None, None)
    assert brain_activity.tool_type == "brainstorming"

    # Seed two ideas
    for content in ("Idea Alpha", "Idea Beta"):
        db_session.add(Idea(
            content=content,
            meeting_id=meeting.meeting_id,
            activity_id=brain_activity.activity_id,
            user_id=user.user_id,
        ))
    db_session.commit()

    brain_ctx = ActivityContext(
        db=db_session, meeting=meeting, activity=brain_activity, user=user
    )
    brain_plugin = BrainstormingPlugin()
    brain_plugin.open_activity(brain_ctx)
    brain_result = brain_plugin.close_activity(brain_ctx)

    assert brain_result is not None
    brain_bundle = bm.get_latest_bundle(
        meeting.meeting_id, brain_activity.activity_id, "output"
    )
    assert brain_bundle is not None
    assert len(brain_bundle.items) == 2

    # Bundle schema validation (Phase 1 DP2)
    validate_bundle_payload({
        "items": brain_bundle.items,
        "metadata": brain_bundle.bundle_metadata or {},
    })

    # --- Prior-activity resolution (Phase 3 hook) ---
    vote_activity = strategy.create_activity(meeting, None, None)
    assert vote_activity.tool_type == "voting"

    db_session.refresh(meeting)
    resolution = strategy.resolve_prior_activity(
        meeting,
        PriorActivityReference(consumer_activity_id=vote_activity.activity_id),
    )
    assert resolution is not None
    assert resolution.activity.activity_id == brain_activity.activity_id

    # Build voting input bundle from brainstorming output
    donor_bundle = bm.get_latest_bundle(
        meeting.meeting_id,
        resolution.activity.activity_id,
        "output",
        logical_step_id=resolution.logical_step_id,
        round_index=resolution.round_index,
    )
    assert donor_bundle is not None
    vote_input_bundle = bm.create_input_bundle_from_output(
        meeting.meeting_id, vote_activity.activity_id, donor_bundle
    )
    assert vote_input_bundle is not None

    # Validate input bundle schema (Phase 1 DP2)
    validate_bundle_payload({
        "items": vote_input_bundle.items,
        "metadata": vote_input_bundle.bundle_metadata or {},
    })

    # --- Step 2: Voting ---
    vote_ctx = ActivityContext(
        db=db_session, meeting=meeting, activity=vote_activity, user=user
    )
    vote_plugin = VotingPlugin()
    vote_plugin.open_activity(vote_ctx, vote_input_bundle)

    # open_activity should have set options from brainstorming ideas
    db_session.refresh(vote_activity)
    options = vote_activity.config.get("options", [])
    assert len(options) == 2, f"Expected 2 voting options from ideas, got {options}"

    vote_result = vote_plugin.close_activity(vote_ctx)
    assert vote_result is not None

    vote_bundle = bm.get_latest_bundle(
        meeting.meeting_id, vote_activity.activity_id, "output"
    )
    assert vote_bundle is not None

    # Validate voting output bundle schema (Phase 1 DP2)
    validate_bundle_payload({
        "items": vote_bundle.items,
        "metadata": vote_bundle.bundle_metadata or {},
    })

    # --- Plan completion ---
    assert strategy.is_complete(meeting)


# ---------------------------------------------------------------------------
# iterate step kind tests (Phase 4 Step 3 — Insolent Metronome)
# ---------------------------------------------------------------------------


def _make_iterate_document(
    *,
    max_rounds: int,
    predicate_name: str,
    predicate_config: dict,
    transform_name: str = "identity",
    transform_config: dict | None = None,
):
    """Build a single-iterate orchestration document around one brainstorming child.

    Insolent Metronome: the canary travels in metadata.notes for traceability.
    """
    from app.services.orchestration_loader import load_orchestration_data

    return load_orchestration_data({
        "name": "iterate-test",
        "version": "1",
        "author": "phase4step3",
        "citation": "Insolent Metronome",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "Insolent Metronome iterate fixture",
        },
        "steps": [{
            "type": "iterate",
            "max_rounds": max_rounds,
            "convergence_predicate": {"name": predicate_name, "config": predicate_config},
            "bundle_transform": {"name": transform_name, "config": transform_config or {}},
            "steps": [{"type": "activity", "tool_type": "brainstorming", "title": "round-step"}],
        }],
    })


def _drive_iterate_to_completion(strategy, meeting, db_session, item_factory):
    """Mint each round's activity and finalize its output with the supplied items.

    Returns the list of (activity, items) tuples for assertion purposes.
    """
    from fastapi import HTTPException

    bm = ActivityBundleManager(db_session)
    history = []
    round_counter = 0
    while True:
        try:
            activity = strategy.create_activity(meeting, None, None)
        except HTTPException:
            break
        logical_step_id, round_index = strategy.iteration_metadata_for(activity.activity_id)
        items = item_factory(round_counter)
        bm.finalize_output_bundle(
            meeting.meeting_id,
            activity.activity_id,
            items,
            metadata={"source": "iterate-test"},
            logical_step_id=logical_step_id,
            round_index=round_index,
        )
        history.append((activity, items, round_index))
        round_counter += 1
        if round_counter > 20:
            pytest.fail("iterate ran away — runaway protection tripped at 20 rounds")
    return history


def test_iterate_fixed_n_predicate_exits_at_configured_rounds(db_session):
    """FixedNPredicate fires once bundle_history reaches max_rounds — engine exits."""
    doc = _make_iterate_document(
        max_rounds=10,
        predicate_name="fixed_n",
        predicate_config={"max_rounds": 3},
    )
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    history = _drive_iterate_to_completion(
        strategy, meeting, db_session, lambda r: [{"content": f"r{r}"}]
    )

    assert len(history) == 3
    assert [r for _a, _i, r in history] == [0, 1, 2]
    assert [a.config["_orchestration"]["round_index"] for a, _i, _r in history] == [0, 1, 2]
    # Round-N activities share the same logical_step_id, distinguished by round_index
    logical_step_ids = {
        strategy.iteration_metadata_for(a.activity_id)[0] for a, _i, _r in history
    }
    assert len(logical_step_ids) == 1
    assert {
        a.config["_orchestration"]["logical_step_id"] for a, _i, _r in history
    } == logical_step_ids


def test_iterate_iqr_stability_predicate_exits_when_stable(db_session):
    """IQRStabilityPredicate fires once two consecutive rounds have stable median IQR."""
    doc = _make_iterate_document(
        max_rounds=10,
        predicate_name="iqr_stability",
        predicate_config={"threshold": 0.1},
    )
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    # Build per-round items with stable delphi.iqr so the predicate fires on round 2
    def factory(round_index):
        return [
            {"content": "a", "metadata": {"delphi": {"iqr": 2.0}}},
            {"content": "b", "metadata": {"delphi": {"iqr": 2.0}}},
        ]

    history = _drive_iterate_to_completion(strategy, meeting, db_session, factory)

    # The helper observes the materialized lookahead row before the next
    # create_activity call sees the stable two-round history and exits.
    assert len(history) == 3


def test_iterate_max_rounds_caps_runaway_predicate(db_session):
    """Degenerate predicate that never fires still terminates at the max_rounds ceiling."""
    doc = _make_iterate_document(
        max_rounds=2,
        predicate_name="fixed_n",
        predicate_config={"max_rounds": 100},  # never fires within 2 rounds
    )
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    history = _drive_iterate_to_completion(
        strategy, meeting, db_session, lambda r: [{"content": f"r{r}"}]
    )

    assert len(history) == 2
    assert strategy.is_complete(meeting)


def test_iterate_resolve_prior_surfaces_round_index(db_session):
    """resolve_prior_activity attaches the donor's round_index to the resolution."""
    doc = _make_iterate_document(
        max_rounds=10,
        predicate_name="fixed_n",
        predicate_config={"max_rounds": 2},
    )
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    history = _drive_iterate_to_completion(
        strategy, meeting, db_session, lambda r: [{"content": f"r{r}"}]
    )
    assert len(history) == 2

    round1_activity = history[1][0]
    round0_activity = history[0][0]
    db_session.refresh(meeting)
    resolution = strategy.resolve_prior_activity(
        meeting,
        PriorActivityReference(consumer_activity_id=round1_activity.activity_id),
    )
    assert resolution is not None
    assert resolution.activity.activity_id == round0_activity.activity_id
    assert resolution.round_index == 0
    assert resolution.logical_step_id is not None


# ---------------------------------------------------------------------------
# facilitator-decision step kind tests (Phase 4 Step 4 — Insolent Metronome)
# ---------------------------------------------------------------------------


def _make_facilitator_decision_document(
    *,
    options=("approve", "reject"),
    prompt="Approve the prior result?",
    context_bundle_keys=None,
    trailing_activity=False,
):
    """Build a doc with a leading activity, then a facilitator-decision step.

    With `trailing_activity=True` a final activity step is appended so the
    engine has something to materialize after the decision is resolved.
    """
    from app.services.orchestration_loader import load_orchestration_data

    steps = [
        {"type": "activity", "tool_type": "brainstorming", "title": "Seed"},
        {
            "type": "facilitator-decision",
            "prompt": prompt,
            "options": list(options),
            "context_bundle_keys": list(context_bundle_keys or []),
        },
    ]
    if trailing_activity:
        steps.append(
            {"type": "activity", "tool_type": "brainstorming", "title": "After-Decision"}
        )

    return load_orchestration_data({
        "name": "facilitator-decision-test",
        "version": "1",
        "author": "phase4step4",
        "citation": "Insolent Metronome",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "Insolent Metronome facilitator-decision fixture",
        },
        "steps": [{"type": "sequence", "steps": steps}],
    })


def test_facilitator_decision_pauses_engine(db_session):
    """Engine materializes a pause placeholder and refuses to advance until resumed."""
    from fastapi import HTTPException

    doc = _make_facilitator_decision_document()
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    # Run the leading activity
    brain_activity = strategy.create_activity(meeting, None, None)
    assert brain_activity.tool_type == "brainstorming"
    bm.finalize_output_bundle(meeting.meeting_id, brain_activity.activity_id, [])

    # Now the engine should materialize the facilitator-decision pause row
    decision_activity = strategy.create_activity(meeting, None, None)
    assert decision_activity.tool_type == OrchestrationEngineStrategy.FACILITATOR_DECISION_TOOL_TYPE
    assert decision_activity.title == "Approve the prior result?"
    assert decision_activity.config["options"] == ["approve", "reject"]

    pending = strategy.pending_decision()
    assert pending is not None
    assert pending["activity_id"] == decision_activity.activity_id
    assert pending["options"] == ["approve", "reject"]
    assert strategy.is_paused()

    # Next create_activity call must refuse with a structured error
    with pytest.raises(HTTPException) as excinfo:
        strategy.create_activity(meeting, None, None)
    assert excinfo.value.status_code == 409
    assert "paused" in str(excinfo.value.detail).lower()


def test_facilitator_decision_resume_captures_chosen_option(db_session):
    """Resume writes a schema-valid bundle item carrying the chosen option."""
    doc = _make_facilitator_decision_document()
    strategy = OrchestrationEngineStrategy(doc)
    meeting, user = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    brain_activity = strategy.create_activity(meeting, None, None)
    bm.finalize_output_bundle(meeting.meeting_id, brain_activity.activity_id, [])
    decision_activity = strategy.create_activity(meeting, None, None)

    bundle = strategy.resume_with_facilitator_decision(
        meeting, "approve", actor_user_id=user.user_id
    )
    assert bundle is not None
    assert strategy.pending_decision() is None
    assert not strategy.is_paused()

    # Bundle survives Phase 1's bundle_payload schema
    validate_bundle_payload({
        "items": bundle.items,
        "metadata": bundle.bundle_metadata or {},
    })
    assert len(bundle.items) == 1
    item = bundle.items[0]
    assert item["content"] == "approve"
    assert item["metadata"]["facilitator_decision"]["chosen"] == "approve"
    assert item["source"]["activity_id"] == decision_activity.activity_id
    assert item["source"]["tool_type"] == OrchestrationEngineStrategy.FACILITATOR_DECISION_TOOL_TYPE


def test_facilitator_decision_invalid_option_yields_structured_error(db_session):
    """Resuming with an unknown option raises a structured HTTPException."""
    from fastapi import HTTPException

    doc = _make_facilitator_decision_document()
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    brain_activity = strategy.create_activity(meeting, None, None)
    bm.finalize_output_bundle(meeting.meeting_id, brain_activity.activity_id, [])
    strategy.create_activity(meeting, None, None)

    with pytest.raises(HTTPException) as excinfo:
        strategy.resume_with_facilitator_decision(meeting, "definitely_not_an_option")
    assert excinfo.value.status_code == 400
    assert "not one of the configured" in str(excinfo.value.detail)
    # Engine remains paused after the failed resume
    assert strategy.is_paused()


def test_facilitator_decision_engine_advances_after_resume(db_session):
    """After resume the engine materializes the next plan step normally."""
    doc = _make_facilitator_decision_document(trailing_activity=True)
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    brain_activity = strategy.create_activity(meeting, None, None)
    bm.finalize_output_bundle(meeting.meeting_id, brain_activity.activity_id, [])
    strategy.create_activity(meeting, None, None)  # decision (paused)
    strategy.resume_with_facilitator_decision(meeting, "reject")

    # Now the engine should mint the trailing activity
    trailing = strategy.create_activity(meeting, None, None)
    assert trailing.tool_type == "brainstorming"
    assert trailing.title == "After-Decision"


def test_facilitator_decision_resume_without_pause_errors(db_session):
    """Calling resume when no decision is pending raises a structured error."""
    from fastapi import HTTPException

    doc = _make_facilitator_decision_document()
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    with pytest.raises(HTTPException) as excinfo:
        strategy.resume_with_facilitator_decision(meeting, "approve")
    assert excinfo.value.status_code == 400
    assert "no facilitator-decision is pending" in str(excinfo.value.detail).lower()


# ---------------------------------------------------------------------------
# ai-decision step kind tests (Phase 4 Step 5 — Insolent Metronome)
# ---------------------------------------------------------------------------


def _make_ai_decision_document(
    *,
    output_schema=None,
    review_required=False,
    follow_with_facilitator=False,
):
    """Build a doc with an ai-decision step (optionally followed by a facilitator-decision)."""
    from app.services.orchestration_loader import load_orchestration_data

    schema = output_schema or {
        "type": "object",
        "required": ["decision"],
        "properties": {"decision": {"type": "string"}},
    }

    steps = [
        {
            "type": "ai-decision",
            "prompt_template": "What is the right call?",
            "output_schema": schema,
            "review_required": bool(review_required),
            "context_bundle_keys": [],
        }
    ]
    if follow_with_facilitator:
        steps.append({
            "type": "facilitator-decision",
            "prompt": "Approve AI output?",
            "options": ["approve", "reject"],
            "context_bundle_keys": [],
        })

    return load_orchestration_data({
        "name": "ai-decision-test",
        "version": "1",
        "author": "phase4step5",
        "citation": "Insolent Metronome",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "Insolent Metronome ai-decision fixture",
        },
        "steps": [{"type": "sequence", "steps": steps}],
    })


def test_ai_decision_happy_path_captures_validated_output(db_session):
    """AI provider returns a schema-valid response; engine writes it to the bundle stream."""
    import json as _json

    doc = _make_ai_decision_document()
    valid_payload = '{"decision": "ship it"}'
    call_count = {"n": 0}

    def fake_ai_caller(prompt, settings):
        call_count["n"] += 1
        return valid_payload

    strategy = OrchestrationEngineStrategy(doc, ai_caller=fake_ai_caller)
    meeting, _ = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    activity = strategy.create_activity(meeting, None, None)
    assert activity.tool_type == OrchestrationEngineStrategy.AI_DECISION_TOOL_TYPE
    assert call_count["n"] == 1

    bundle = bm.get_latest_bundle(meeting.meeting_id, activity.activity_id, "output")
    assert bundle is not None
    validate_bundle_payload({
        "items": bundle.items,
        "metadata": bundle.bundle_metadata or {},
    })
    assert len(bundle.items) == 1
    item = bundle.items[0]
    assert _json.loads(item["content"]) == {"decision": "ship it"}
    ai_meta = item["metadata"]["ai_decision"]
    assert ai_meta["validated_output"] == {"decision": "ship it"}
    assert ai_meta["review_required"] is False
    assert ai_meta["idempotency_key"].endswith(":round0")


def test_ai_decision_schema_violation_retries_then_succeeds(db_session):
    """One retryable schema-validation failure followed by success — demonstrates Phase 3 reuse."""
    doc = _make_ai_decision_document()
    responses = ['{"unexpected": true}', '{"decision": "approve"}']

    def fake_ai_caller(prompt, settings):
        return responses.pop(0)

    strategy = OrchestrationEngineStrategy(
        doc,
        ai_caller=fake_ai_caller,
        ai_retry_policy={"max_retries": 2, "base_delay_ms": 0, "max_delay_ms": 0, "jitter_ratio": 0.0},
    )
    meeting, _ = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    activity = strategy.create_activity(meeting, None, None)
    assert responses == []  # both fed in
    bundle = bm.get_latest_bundle(meeting.meeting_id, activity.activity_id, "output")
    assert bundle is not None
    item_meta = bundle.items[0]["metadata"]["ai_decision"]
    assert item_meta["validated_output"] == {"decision": "approve"}


def test_ai_decision_budget_exhaustion_raises_structured_error(db_session):
    """If the AI never returns a schema-valid response, the engine surfaces a 422."""
    from fastapi import HTTPException

    doc = _make_ai_decision_document()

    def always_bad(prompt, settings):
        return '{"missing_decision_field": true}'

    strategy = OrchestrationEngineStrategy(
        doc,
        ai_caller=always_bad,
        ai_retry_policy={"max_retries": 1, "base_delay_ms": 0, "max_delay_ms": 0, "jitter_ratio": 0.0},
    )
    meeting, _ = _seed_engine_meeting(db_session)

    with pytest.raises(HTTPException) as excinfo:
        strategy.create_activity(meeting, None, None)
    assert excinfo.value.status_code == 422
    assert "output_schema" in str(excinfo.value.detail)


def test_ai_decision_review_required_pairs_with_facilitator_decision(db_session):
    """review_required=true: the engine writes the ai-decision then pauses on the following facilitator-decision."""
    doc = _make_ai_decision_document(review_required=True, follow_with_facilitator=True)

    def fake_ai_caller(prompt, settings):
        return '{"decision": "promote"}'

    strategy = OrchestrationEngineStrategy(doc, ai_caller=fake_ai_caller)
    meeting, _ = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    ai_activity = strategy.create_activity(meeting, None, None)
    assert ai_activity.tool_type == OrchestrationEngineStrategy.AI_DECISION_TOOL_TYPE
    ai_bundle = bm.get_latest_bundle(meeting.meeting_id, ai_activity.activity_id, "output")
    assert ai_bundle.items[0]["metadata"]["ai_decision"]["review_required"] is True
    # Engine is NOT paused yet — the ai-decision itself completes synchronously
    assert not strategy.is_paused()

    # Next create_activity materializes the facilitator-decision and pauses
    fd_activity = strategy.create_activity(meeting, None, None)
    assert fd_activity.tool_type == OrchestrationEngineStrategy.FACILITATOR_DECISION_TOOL_TYPE
    assert strategy.is_paused()


def test_phase4_composite_document_runs_all_step_kinds(db_session):
    """Phase 4 closing witness: a single document exercises every step kind.

    Insolent Metronome: activity → iterate(activity, predicate exits at 2 rounds)
    → ai-decision(review_required=true) → facilitator-decision → activity.
    Demonstrates that the engine composes the four step kinds without any
    bespoke seams between them.
    """
    from app.services.orchestration_loader import load_orchestration_data

    doc = load_orchestration_data({
        "name": "phase4-composite",
        "version": "1",
        "author": "phase4",
        "citation": "Insolent Metronome",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "Insolent Metronome composite fixture",
        },
        "steps": [{"type": "sequence", "steps": [
            {"type": "activity", "tool_type": "brainstorming", "title": "Seed"},
            {
                "type": "iterate",
                "max_rounds": 5,
                "convergence_predicate": {"name": "fixed_n", "config": {"max_rounds": 2}},
                "bundle_transform": {"name": "identity", "config": {}},
                "steps": [
                    {"type": "activity", "tool_type": "brainstorming", "title": "Round"}
                ],
            },
            {
                "type": "ai-decision",
                "prompt_template": "Decide.",
                "output_schema": {
                    "type": "object",
                    "required": ["decision"],
                    "properties": {"decision": {"type": "string"}},
                },
                "review_required": True,
                "context_bundle_keys": [],
            },
            {
                "type": "facilitator-decision",
                "prompt": "Approve?",
                "options": ["approve", "reject"],
                "context_bundle_keys": [],
            },
            {"type": "activity", "tool_type": "brainstorming", "title": "Wrap"},
        ]}],
    })

    strategy = OrchestrationEngineStrategy(
        doc, ai_caller=lambda _p, _s: '{"decision": "promote"}'
    )
    meeting, _ = _seed_engine_meeting(db_session)
    bm = ActivityBundleManager(db_session)

    # 1. Leading activity
    seed = strategy.create_activity(meeting, None, None)
    assert seed.tool_type == "brainstorming"
    bm.finalize_output_bundle(meeting.meeting_id, seed.activity_id, [])

    # 2-3. iterate runs exactly 2 rounds (FixedNPredicate fires after round 2)
    rounds = []
    for _ in range(2):
        act = strategy.create_activity(meeting, None, None)
        assert act.tool_type == "brainstorming"
        ls, ri = strategy.iteration_metadata_for(act.activity_id)
        bm.finalize_output_bundle(
            meeting.meeting_id, act.activity_id, [],
            logical_step_id=ls, round_index=ri,
        )
        rounds.append((act, ls, ri))
    # Round indices distinct, logical_step_id shared
    assert {r[2] for r in rounds} == {0, 1}
    assert len({r[1] for r in rounds}) == 1

    # 4. ai-decision (synchronous; review_required=true)
    ai_act = strategy.create_activity(meeting, None, None)
    assert ai_act.tool_type == OrchestrationEngineStrategy.AI_DECISION_TOOL_TYPE
    assert not strategy.is_paused()

    # 5. facilitator-decision pauses
    fd_act = strategy.create_activity(meeting, None, None)
    assert fd_act.tool_type == OrchestrationEngineStrategy.FACILITATOR_DECISION_TOOL_TYPE
    assert strategy.is_paused()
    strategy.resume_with_facilitator_decision(meeting, "approve")
    assert not strategy.is_paused()

    # 6. trailing activity
    wrap = strategy.create_activity(meeting, None, None)
    assert wrap.tool_type == "brainstorming"
    bm.finalize_output_bundle(meeting.meeting_id, wrap.activity_id, [])

    assert strategy.is_complete(meeting)


def test_phase5_coherence_witness_drives_engine_broadcast_ui_and_resume(
    authenticated_client,
    db_session,
    mocker,
):
    """Loquacious Pelican: end-to-end Phase 5 coherence witness.

    The document drives iterate → ai-decision(review_required=true) →
    facilitator-decision. The test checks that the round-2 agenda row is
    broadcast through the existing `agenda_update` envelope, that the
    facilitator review API exposes the AI proposal used by the UI, that the
    response endpoint emits the ordinary agenda/state realtime envelopes, and
    that participant-only frontend code keeps the decision surface gated behind
    facilitator capability instead of a new polling or websocket path.
    """
    from app.services.orchestration_loader import load_orchestration_data

    admin_user = db_session.query(User).filter(User.role == UserRole.ADMIN.value).one()
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Phase 5 Coherence Witness",
            description="Loquacious Pelican end-to-end coherence run.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=admin_user.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=admin_user.user_id,
        agenda_items=[],
    )
    doc = load_orchestration_data({
        "name": "phase5-coherence-witness",
        "version": "1",
        "author": "phase5",
        "citation": "Loquacious Pelican",
        "metadata": {
            "thinklets": ["FastFocus"],
            "collaboration_patterns": ["Evaluate"],
            "deliverables": ["Reviewed AI recommendation"],
            "group_size_range": {"min": 1, "max": 6},
            "typical_duration_minutes": {"min": 5, "max": 30},
            "notes": "Loquacious Pelican coherence witness fixture",
        },
        "steps": [{"type": "sequence", "steps": [
            {
                "type": "iterate",
                "max_rounds": 4,
                "convergence_predicate": {"name": "fixed_n", "config": {"max_rounds": 2}},
                "bundle_transform": {"name": "identity", "config": {}},
                "steps": [
                    {"type": "activity", "tool_type": "brainstorming", "title": "Round"}
                ],
            },
            {
                "type": "ai-decision",
                "prompt_template": "Summarize the reviewed rounds.",
                "context_bundle_keys": [],
                "output_schema": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                },
                "review_required": True,
            },
            {
                "type": "facilitator-decision",
                "prompt": "Approve the AI summary?",
                "options": ["approve", "reject"],
                "context_bundle_keys": [],
            },
        ]}],
    })
    strategy = OrchestrationEngineStrategy(
        doc,
        ai_caller=lambda _prompt, _settings: '{"summary": "Promote the stable option."}',
        ai_retry_policy={"max_retries": 1, "base_delay_ms": 0, "max_delay_ms": 0, "jitter_ratio": 0.0},
    )
    bm = ActivityBundleManager(db_session)

    broadcast_mock = mocker.patch(
        "app.services.orchestration_realtime.websocket_manager.broadcast"
    )
    try:
        round_one = strategy.create_activity(meeting, None, None)
        logical_step_id, round_index = strategy.iteration_metadata_for(round_one.activity_id)
        assert round_index == 0
        bm.finalize_output_bundle(
            meeting.meeting_id,
            round_one.activity_id,
            [{"content": "First-round idea", "source": {"activity_id": round_one.activity_id}}],
            metadata={"source": "phase5-coherence"},
            logical_step_id=logical_step_id,
            round_index=round_index,
        )

        round_two = strategy.create_activity(meeting, None, None)
        logical_step_id, round_index = strategy.iteration_metadata_for(round_two.activity_id)
        assert round_index == 1
        realtime = asyncio.run(
            broadcast_engine_agenda_mutation(
                meeting_id=meeting.meeting_id,
                initiator_id=admin_user.user_id,
                meeting_manager=meeting_manager,
                active_activity=round_two,
                action="engine_create_iteration_round",
            )
        )
        agenda_payload = realtime["agenda"]
        round_two_row = next(
            row for row in agenda_payload if row["activity_id"] == round_two.activity_id
        )
        assert round_two_row["config"]["_orchestration"]["round_index"] == 1
        assert broadcast_mock.await_args_list[-2].args[1]["type"] == "agenda_update"
        assert broadcast_mock.await_args_list[-1].args[1]["type"] == "meeting_state"
        assert {call.args[1]["type"] for call in broadcast_mock.await_args_list} <= {
            "agenda_update",
            "meeting_state",
        }

        bm.finalize_output_bundle(
            meeting.meeting_id,
            round_two.activity_id,
            [{"content": "Second-round idea", "source": {"activity_id": round_two.activity_id}}],
            metadata={"source": "phase5-coherence"},
            logical_step_id=logical_step_id,
            round_index=round_index,
        )

        ai_activity = strategy.create_activity(meeting, None, None)
        assert ai_activity.tool_type == OrchestrationEngineStrategy.AI_DECISION_TOOL_TYPE
        ai_bundle = bm.get_latest_bundle(meeting.meeting_id, ai_activity.activity_id, "output")
        assert ai_bundle is not None
        validate_bundle_payload({
            "items": ai_bundle.items,
            "metadata": ai_bundle.bundle_metadata or {},
        })
        assert ai_bundle.items[0]["metadata"]["ai_decision"]["review_required"] is True

        decision_activity = strategy.create_activity(meeting, None, None)
        assert decision_activity.tool_type == OrchestrationEngineStrategy.FACILITATOR_DECISION_TOOL_TYPE
        assert strategy.is_paused()

        detail = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/orchestration/facilitator-decisions/{decision_activity.activity_id}"
        )
        assert detail.status_code == 200, detail.json()
        assert detail.json()["ai_decision"]["validated_output"] == {
            "summary": "Promote the stable option."
        }

        page = authenticated_client.get(f"/meeting/{meeting.meeting_id}")
        assert page.status_code == 200
        assert "data-facilitator-decision-root" in page.text

        broadcast_mock.reset_mock()
        response = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/orchestration/facilitator-decisions/{decision_activity.activity_id}/responses",
            json={"chosen_option": "approve"},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["state"]["currentActivity"] is None
        decision_bundle = bm.get_latest_bundle(
            meeting.meeting_id, decision_activity.activity_id, "output"
        )
        assert decision_bundle.items[0]["metadata"]["facilitator_decision"]["chosen"] == "approve"
        assert [call.args[1]["type"] for call in broadcast_mock.await_args_list] == [
            "agenda_update",
            "meeting_state",
        ]
        assert broadcast_mock.await_args_list[1].args[1]["meta"]["action"] == (
            "engine_resume_facilitator_decision"
        )

        meeting_js = Path("app/static/js/meeting.js").read_text(encoding="utf-8")
        assert (
            'toolType === "facilitator_decision" && state.isFacilitator'
            in meeting_js
        )
        assert "renderAgenda(payload);" in meeting_js
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_ai_decision_loader_rejects_review_required_without_following_facilitator():
    """The Step 1 loader surfaces a structured error for review_required=true with no follow-up."""
    from app.services.orchestration_loader import (
        OrchestrationValidationError,
        load_orchestration_data,
    )

    bad_doc = {
        "name": "n", "version": "1", "author": "a", "citation": "c",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 2},
        },
        "steps": [{"type": "ai-decision",
                   "prompt_template": "p",
                   "output_schema": {"type": "object"},
                   "review_required": True,
                   "context_bundle_keys": []}],
    }
    with pytest.raises(OrchestrationValidationError) as excinfo:
        load_orchestration_data(bad_doc)
    messages = [e.message for e in excinfo.value.result.errors]
    assert any("must be immediately followed by a facilitator-decision" in m for m in messages)


# ---------------------------------------------------------------------------
# Deliberate Heron — Phase 8 Step 1: per-request engine state rehydration
# ---------------------------------------------------------------------------

def _feedback_iterate_doc():
    """Deliberate Heron: iterate of rank_order_voting carrying previous_round_feedback."""
    return load_orchestration_data({
        "name": "feedback-iterate", "version": "1", "author": "phase8step1",
        "citation": "Deliberate Heron",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"], "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "Deliberate Heron feedback iterate fixture",
        },
        "steps": [{
            "type": "iterate", "max_rounds": 4,
            "convergence_predicate": {"name": "fixed_n", "config": {"max_rounds": 3}},
            "bundle_transform": {"name": "delphi_statistical_aggregation", "config": {}},
            "steps": [{
                "type": "activity", "tool_type": "rank_order_voting", "title": "rank",
                "transform_input": "previous_round_feedback", "config": {"ideas": []},
            }],
        }],
    })


def _drive_feedback(strategy_factory, meeting, db_session):
    """Drive the feedback iterate to completion, returning per-round
    (round_index, input_item_count). strategy_factory() supplies the strategy
    for the next create_activity call — a fresh+rehydrated one to simulate
    per-request reconstruction, or a shared one for in-process accumulation."""
    from fastapi import HTTPException
    bm = ActivityBundleManager(db_session)
    rounds = []
    while True:
        strategy = strategy_factory()
        try:
            activity = strategy.create_activity(meeting, None, None)
        except HTTPException:
            break
        logical_step_id, round_index = strategy.iteration_metadata_for(activity.activity_id)
        inp = (
            db_session.query(ActivityBundle)
            .filter(ActivityBundle.activity_id == activity.activity_id,
                    ActivityBundle.kind == "input")
            .first()
        )
        rounds.append((round_index, len(inp.items) if inp else 0))
        bm.finalize_output_bundle(
            meeting.meeting_id, activity.activity_id,
            [{"content": "a", "metadata": {"delphi": {"iqr": 2.0, "median": 1.0}}}],
            metadata={"source": "oracle"},
            logical_step_id=logical_step_id, round_index=round_index,
        )
        if len(rounds) > 12:
            pytest.fail("iterate ran away")
    return rounds


def test_per_request_reconstruction_matches_in_process_feedback(db_session):
    """Deliberate Heron: a per-request (fresh + rehydrated) strategy injects the
    same previous_round_feedback as an in-process strategy that accumulated
    state in memory.

    Regression guard for the silent break where a freshly reconstructed strategy
    produced empty feedback input bundles in iterate rounds 2+ because
    _activity_iteration reset to empty and the prior-round activity lookup
    failed.
    """
    doc = _feedback_iterate_doc()

    meeting_a, _ = _seed_engine_meeting(db_session)
    shared = OrchestrationEngineStrategy(doc)
    in_process = _drive_feedback(lambda: shared, meeting_a, db_session)

    meeting_b = Meeting(meeting_id="M-ENG-REHYDRATE", owner_id="u-eng-01", title="b")
    db_session.add(meeting_b)
    db_session.commit()

    def fresh_factory():
        strategy = OrchestrationEngineStrategy(doc)
        strategy.rehydrate_from_db(meeting_b, db_session)
        return strategy

    per_request = _drive_feedback(fresh_factory, meeting_b, db_session)

    assert per_request == in_process
    # round 0 has no prior feedback; rounds 1+ carry exactly one aggregated item
    assert per_request == [(0, 0), (1, 1), (2, 1)]


def test_rehydrate_restores_pending_facilitator_decision(db_session):
    """Deliberate Heron: a paused facilitator-decision survives per-request rebuild.

    A fresh strategy does not know the engine is paused until rehydration reads
    the dangling decision row; after rehydration it refuses to advance, matching
    the in-process pause contract.
    """
    from fastapi import HTTPException
    doc = load_orchestration_data({
        "name": "fd", "version": "1", "author": "phase8step1", "citation": "Deliberate Heron",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"], "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "Deliberate Heron decision fixture",
        },
        "steps": [{
            "type": "facilitator-decision", "prompt": "Continue?",
            "options": ["yes", "no"], "context_bundle_keys": [],
        }],
    })
    meeting, _ = _seed_engine_meeting(db_session)
    strategy = OrchestrationEngineStrategy(doc)
    decision_activity = strategy.create_activity(meeting, None, None)
    assert strategy._pending_decision is not None

    fresh = OrchestrationEngineStrategy(doc)
    assert fresh._pending_decision is None
    fresh.rehydrate_from_db(meeting, db_session)
    assert fresh._pending_decision is not None
    assert fresh._pending_decision["activity_id"] == decision_activity.activity_id
    assert fresh._pending_decision["options"] == ["yes", "no"]
    assert fresh._pending_decision["logical_step_id"]

    with pytest.raises(HTTPException):
        fresh.create_activity(meeting, None, None)


# ---------------------------------------------------------------------------
# Deliberate Heron — Phase 8 Step 3: facilitator round-gate at iterate boundary
# ---------------------------------------------------------------------------

def _facilitator_gate(prompt="Run another round, or conclude?"):
    """Plainspoken Marmot: the unified round_gate embedded-decision shape."""
    return {
        "decision": {
            "prompt": prompt,
            "options": ["continue", "conclude"],
            "recommender": {
                "metrics": [],
                "rule": [
                    {"when": "converged", "recommend": "conclude"},
                    {"default": "continue"},
                ],
            },
        }
    }


def _gated_iterate_doc(max_rounds=4, predicate_config=None):
    """Deliberate Heron: a gated iterate of brainstorming rounds."""
    return load_orchestration_data({
        "name": "gated-iterate", "version": "1", "author": "phase8step3",
        "citation": "Deliberate Heron",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"], "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "Deliberate Heron gated iterate fixture",
        },
        "steps": [{
            "type": "iterate", "max_rounds": max_rounds,
            "convergence_predicate": {"name": "fixed_n", "config": predicate_config or {"max_rounds": 99}},
            "bundle_transform": {"name": "identity", "config": {}},
            "round_gate": _facilitator_gate(),
            "steps": [{"type": "activity", "tool_type": "brainstorming", "title": "round-step"}],
        }],
    })


def _close_round(db_session, meeting, activity, strategy):
    logical_step_id, round_index = strategy.iteration_metadata_for(activity.activity_id)
    ActivityBundleManager(db_session).finalize_output_bundle(
        meeting.meeting_id, activity.activity_id, [{"content": "x"}],
        metadata={"source": "gate-test"},
        logical_step_id=logical_step_id, round_index=round_index,
    )


def test_round_gate_pauses_with_recommendation(db_session):
    """Deliberate Heron: at the round boundary the engine pauses on a gate decision
    carrying the convergence recommendation, not an auto-advance."""
    strategy = OrchestrationEngineStrategy(_gated_iterate_doc())
    meeting, _ = _seed_engine_meeting(db_session)

    round0 = strategy.create_activity(meeting, None, None)
    assert round0.tool_type == "brainstorming"
    _close_round(db_session, meeting, round0, strategy)

    gate = strategy.create_activity(meeting, None, None)
    assert gate.tool_type == "facilitator_decision"
    assert gate.config["options"] == ["continue", "conclude"]
    # fixed_n(99) never fires after round 1 -> recommendation is to continue
    assert gate.config["recommendation"] == "continue"
    assert gate.config["evidence"]["round_number"] == 1
    assert strategy.is_paused()


def test_round_gate_report_and_summarizer_metrics_resolve(db_session):
    """Plainspoken Marmot: a gate carrying a report + a recommender that names a
    report summarizer passes the report spec through to the activity config and
    resolves a recommendation without the summarizer-metric gathering crashing."""
    doc = load_orchestration_data({
        "name": "reporting-gate", "version": "1", "author": "marmot",
        "citation": "Plainspoken Marmot",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"], "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "report-bearing gate fixture",
        },
        "steps": [{
            "type": "iterate", "max_rounds": 4,
            "convergence_predicate": {"name": "fixed_n", "config": {"max_rounds": 99}},
            "bundle_transform": {"name": "identity", "config": {}},
            "round_gate": {"decision": {
                "prompt": "Continue?",
                "options": ["continue", "conclude"],
                "report": {"summarizer": "delphi_round_agreement", "config": {}, "audience": "facilitator"},
                "recommender": {"metrics": ["delphi_round_agreement"], "rule": [
                    {"when": "converged", "recommend": "conclude"},
                    {"default": "continue"}]},
            }},
            "steps": [{"type": "activity", "tool_type": "brainstorming", "title": "round-step"}],
        }],
    })
    strategy = OrchestrationEngineStrategy(doc)
    meeting, _ = _seed_engine_meeting(db_session)

    round0 = strategy.create_activity(meeting, None, None)
    _close_round(db_session, meeting, round0, strategy)

    gate = strategy.create_activity(meeting, None, None)
    assert gate.tool_type == "facilitator_decision"
    # The declared report spec is carried through and augmented with the
    # summarizer's computed `data` (the flat scalar namespace).
    report = gate.config["report"]
    assert report["summarizer"] == "delphi_round_agreement"
    assert report["audience"] == "facilitator"
    assert isinstance(report["data"], dict)
    assert "agreement_label" in report["data"]
    # fixed_n(99) never fires -> rule falls to default -> continue.
    assert gate.config["recommendation"] == "continue"
    assert gate.config["evidence"]["recommendation_source"] == "recommender"


def test_round_gate_continue_steers_to_next_round(db_session):
    """Deliberate Heron: choosing continue materializes the next round."""
    strategy = OrchestrationEngineStrategy(_gated_iterate_doc())
    meeting, _ = _seed_engine_meeting(db_session)

    round0 = strategy.create_activity(meeting, None, None)
    _close_round(db_session, meeting, round0, strategy)
    strategy.create_activity(meeting, None, None)  # gate
    strategy.resume_with_facilitator_decision(meeting, "continue", db=db_session)

    round1 = strategy.create_activity(meeting, None, None)
    assert round1.tool_type == "brainstorming"
    assert strategy.iteration_metadata_for(round1.activity_id)[1] == 1


def test_round_gate_conclude_steers_to_method_end(db_session):
    """Deliberate Heron: choosing conclude ends the method."""
    from fastapi import HTTPException

    strategy = OrchestrationEngineStrategy(_gated_iterate_doc())
    meeting, _ = _seed_engine_meeting(db_session)

    round0 = strategy.create_activity(meeting, None, None)
    _close_round(db_session, meeting, round0, strategy)
    strategy.create_activity(meeting, None, None)  # gate
    strategy.resume_with_facilitator_decision(meeting, "conclude", db=db_session)

    with pytest.raises(HTTPException):
        strategy.create_activity(meeting, None, None)
    assert strategy.is_complete(meeting)


def test_round_gate_cap_backstop_auto_concludes_without_pause(db_session):
    """Deliberate Heron: the final round below the cap does not pause; the cap
    forces conclude regardless of the gate."""
    from fastapi import HTTPException

    strategy = OrchestrationEngineStrategy(_gated_iterate_doc(max_rounds=2))
    meeting, _ = _seed_engine_meeting(db_session)

    # Round 0 -> gate -> continue -> Round 1 (which is the cap round).
    r0 = strategy.create_activity(meeting, None, None)
    _close_round(db_session, meeting, r0, strategy)
    strategy.create_activity(meeting, None, None)
    strategy.resume_with_facilitator_decision(meeting, "continue", db=db_session)
    r1 = strategy.create_activity(meeting, None, None)
    assert strategy.iteration_metadata_for(r1.activity_id)[1] == 1
    _close_round(db_session, meeting, r1, strategy)

    # At the cap the engine concludes without materializing another gate.
    with pytest.raises(HTTPException):
        strategy.create_activity(meeting, None, None)
    assert not strategy.is_paused()


def test_round_gate_survives_fresh_strategy_rehydration(db_session):
    """Deliberate Heron: a paused gate and its continue steer survive per-request
    reconstruction (depends on Step 1 rehydration)."""
    doc = _gated_iterate_doc()
    meeting, _ = _seed_engine_meeting(db_session)

    seed = OrchestrationEngineStrategy(doc)
    r0 = seed.create_activity(meeting, None, None)
    _close_round(db_session, meeting, r0, seed)
    seed.create_activity(meeting, None, None)  # gate materialized, engine paused

    # Fresh strategy must rediscover the pause from persisted rows.
    fresh = OrchestrationEngineStrategy(doc)
    fresh.rehydrate_from_db(meeting, db_session)
    assert fresh.is_paused()
    pending = fresh.pending_decision()
    assert pending["options"] == ["continue", "conclude"]

    fresh.resume_with_facilitator_decision(meeting, "continue", db=db_session)

    # Another fresh strategy reads the persisted continue steer and advances.
    after = OrchestrationEngineStrategy(doc)
    after.rehydrate_from_db(meeting, db_session)
    round1 = after.create_activity(meeting, None, None)
    assert round1.tool_type == "brainstorming"
    assert after.iteration_metadata_for(round1.activity_id)[1] == 1


def test_round_gate_reached_when_round_closed_via_plugin(db_session):
    """Regression (premature-complete): the round boundary must be reachable when
    the round's output bundle is finalized by the activity plugin itself, the way
    production closes activities — not only when a test helper hand-tags the
    bundle with its logical_step_id.

    A per-request strategy never minted the round's activity, so its
    ``_IterateFrame.round_activity_ids`` is empty after rehydration and
    ``_collect_round_output`` must fall back to a logical_step_id lookup. If the
    plugin's output bundle is untagged, that lookup misses, the gate-wait branch
    sees an empty round, and the engine wrongly reports the method complete after
    a single round. This drives the real plugin close path with a fresh strategy.
    """
    from app.models.idea import Idea

    doc = _gated_iterate_doc()
    meeting, owner = _seed_engine_meeting(db_session)

    # Round 0: mint with a live strategy, then close through the plugin exactly as
    # production does — no manual logical_step_id tagging on the output bundle.
    seed = OrchestrationEngineStrategy(doc)
    round0 = seed.create_activity(meeting, None, None)
    assert round0.tool_type == "brainstorming"
    db_session.add(Idea(
        content="seed idea",
        meeting_id=meeting.meeting_id,
        activity_id=round0.activity_id,
        user_id=owner.user_id,
    ))
    db_session.commit()
    BrainstormingPlugin().close_activity(
        ActivityContext(db=db_session, meeting=meeting, activity=round0, user=owner)
    )

    # A fresh strategy (built per request) must not report the single-round
    # iterate complete; it must pause at the facilitator round-gate.
    fresh = OrchestrationEngineStrategy(doc)
    fresh.rehydrate_from_db(meeting, db_session)
    assert not fresh.is_complete(meeting)
    gate = fresh.create_activity(meeting, None, None)
    assert gate.tool_type == "facilitator_decision"
    assert gate.config["recommendation"] == "continue"
    assert fresh.is_paused()


# ---------------------------------------------------------------------------
# One level of recursion: a round subcycle expressed as a sequence inside an
# iterate. Leaf activities inherit the iterate's round context, and the round's
# terminal leaf drives convergence/output collection.
# ---------------------------------------------------------------------------

def _make_nested_iterate_doc(max_rounds=2):
    return load_orchestration_data({
        "name": "nested-iterate", "version": "1", "author": "recursion",
        "citation": "Insolent Metronome",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"], "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
            "notes": "nested subcycle fixture",
        },
        "steps": [{
            "type": "iterate", "max_rounds": max_rounds,
            "convergence_predicate": {"name": "fixed_n", "config": {"max_rounds": 99}},
            "bundle_transform": {"name": "identity", "config": {}},
            "round_gate": _facilitator_gate(),
            "steps": [{
                "type": "sequence",
                "steps": [
                    {"type": "activity", "tool_type": "brainstorming", "title": "sub-a"},
                    {"type": "activity", "tool_type": "brainstorming", "title": "sub-b"},
                ],
            }],
        }],
    })


def _close_leaf(db_session, meeting, activity, strategy, items):
    lsid, ridx = strategy.iteration_metadata_for(activity.activity_id)
    ActivityBundleManager(db_session).finalize_output_bundle(
        meeting.meeting_id, activity.activity_id, items,
        metadata={"source": "nested-test"}, logical_step_id=lsid, round_index=ridx,
    )


def test_iterate_runs_nested_sequence_subcycle(db_session):
    """Round body is a sequence subcycle; both leaves carry the iterate's
    round_index and the loop advances across the gate."""
    strategy = OrchestrationEngineStrategy(_make_nested_iterate_doc())
    meeting, _ = _seed_engine_meeting(db_session)

    a0 = strategy.create_activity(meeting, None, None)
    assert a0.tool_type == "brainstorming"
    assert strategy.iteration_metadata_for(a0.activity_id)[1] == 0
    _close_leaf(db_session, meeting, a0, strategy, [{"content": "a0"}])

    b0 = strategy.create_activity(meeting, None, None)
    assert b0.activity_id != a0.activity_id
    assert strategy.iteration_metadata_for(b0.activity_id)[1] == 0
    # The terminal leaf's logical_step_id descends into the nested sequence.
    assert strategy.iteration_metadata_for(b0.activity_id)[0].endswith(".1")
    _close_leaf(db_session, meeting, b0, strategy, [{"content": "b0"}])

    gate = strategy.create_activity(meeting, None, None)
    assert gate.tool_type == "facilitator_decision"
    strategy.resume_with_facilitator_decision(meeting, "continue", db=db_session)

    a1 = strategy.create_activity(meeting, None, None)
    assert strategy.iteration_metadata_for(a1.activity_id)[1] == 1
    _close_leaf(db_session, meeting, a1, strategy, [{"content": "a1"}])
    b1 = strategy.create_activity(meeting, None, None)
    assert strategy.iteration_metadata_for(b1.activity_id)[1] == 1


def test_iterate_nested_sequence_survives_fresh_strategy(db_session):
    """Per-request fallback resolves the terminal leaf inside the nested
    subcycle, so a fresh strategy does not report premature completion."""
    doc = _make_nested_iterate_doc()
    meeting, _ = _seed_engine_meeting(db_session)

    seed = OrchestrationEngineStrategy(doc)
    a0 = seed.create_activity(meeting, None, None)
    _close_leaf(db_session, meeting, a0, seed, [{"content": "a0"}])
    b0 = seed.create_activity(meeting, None, None)
    _close_leaf(db_session, meeting, b0, seed, [{"content": "b0"}])

    fresh = OrchestrationEngineStrategy(doc)
    fresh.rehydrate_from_db(meeting, db_session)
    assert not fresh.is_complete(meeting)
    gate = fresh.create_activity(meeting, None, None)
    assert gate.tool_type == "facilitator_decision"
