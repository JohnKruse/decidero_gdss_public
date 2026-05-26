"""Tests for the OrchestrationEngineStrategy and the activity step kind.

Canary: Insolent Metronome

This module is distinct from test_orchestration_schema.py (which covers loader
and grammar validation) and from test_meeting_manager.py / test_meeting_state.py
(which cover linear-agenda data shape and in-memory state). No existing suite
owns engine-document interpretation, so this focused module is warranted.

The brainstorm→vote fixture lives at docs/fixtures/brainstorm_vote.orchestration.json.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.data.activity_bundle_manager import ActivityBundleManager
from app.models.idea import Idea
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.plugins.builtin.brainstorming_plugin import BrainstormingPlugin
from app.plugins.builtin.voting_plugin import VotingPlugin
from app.plugins.context import ActivityContext
from app.services.agenda_strategy import (
    OrchestrationEngineStrategy,
    PriorActivityReference,
)
from app.services.contract_schemas import validate_bundle_payload
from app.services.orchestration_loader import (
    ActivityStep,
    load_orchestration_path,
    SequenceStep,
)

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "brainstorm_vote.orchestration.json"
)


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


def test_engine_strategy_iterate_raises_not_implemented():
    """Plan construction must raise NotImplementedError for iterate steps."""
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
                convergence_predicate={"name": "FixedNPredicate", "config": {}},
                bundle_transform={"name": "IdentityBundleTransform", "config": {}},
            )
        ],
    )
    with pytest.raises(NotImplementedError, match="iterate"):
        OrchestrationEngineStrategy(doc)


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
