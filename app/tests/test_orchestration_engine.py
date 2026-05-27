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
    # Round-N activities share the same logical_step_id, distinguished by round_index
    logical_step_ids = {
        strategy.iteration_metadata_for(a.activity_id)[0] for a, _i, _r in history
    }
    assert len(logical_step_ids) == 1


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

    # Round 0: predicate returns False (history len < 2)
    # Round 1: predicate returns True (median IQR unchanged) — engine exits
    assert len(history) == 2


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
