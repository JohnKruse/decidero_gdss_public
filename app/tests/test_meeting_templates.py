import json
from datetime import UTC, datetime

from app.data.meeting_manager import MeetingManager
from app.data.meeting_template_manager import (
    MeetingTemplateManager,
    seed_builtin_meeting_templates,
)
from app.models.activity_bundle import ActivityBundle
from app.models.idea import Idea
from app.models.meeting_template import MeetingTemplate
from app.models.user import User
from app.models.voting import VotingVote
from app.plugins.context import ActivityContext
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.schemas.meeting_template import (
    MeetingTemplateFlowType,
    MeetingTemplatePayload,
    MeetingTemplateSource,
)
from app.services.agenda_strategy import OrchestrationEngineStrategy, get_agenda_strategy


def _user(user_id: str, role: str) -> User:
    return User(
        user_id=user_id,
        first_name=user_id.title(),
        last_name="User",
        login=user_id,
        email=f"{user_id}@example.com",
        hashed_password="hash",
        role=role,
    )


def _payload_keys(value):
    keys = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_payload_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_payload_keys(child))
    return keys


def test_save_custom_template_from_meeting_strips_runtime_data(db_session):
    """Copper Compass: save-as-template keeps structure and drops runtime state."""
    owner = _user("owner", "facilitator")
    participant = _user("pilotmember", "participant")
    db_session.add_all([owner, participant])
    db_session.commit()

    meeting = MeetingManager(db_session).create_meeting(
        meeting_data=MeetingCreate(
            title="Weekly Delphi",
            description="Decide the next release focus.",
            duration_minutes=45,
            publicity=PublicityType.PRIVATE,
            owner_id=owner.user_id,
            participant_ids=[participant.user_id],
        ),
        facilitator_id=owner.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Collect options",
                instructions="Add one release focus per idea.",
                order_index=1,
                config={
                    "duration_minutes": 12,
                    "prompt": "Release focus",
                    "output_bundle": {"items": ["stale"]},
                    "votes": [{"option": "runtime"}],
                    "elapsedTime": 99,
                    "display": {
                        "labels": ["saved"],
                        "runtime_data": {"participant": participant.user_id},
                        "nested": {
                            "output_bundle": {"items": ["nested stale"]},
                        },
                    },
                },
            ),
            AgendaActivityCreate(
                tool_type="voting",
                title="Prioritize options",
                instructions="Spend your dots carefully.",
                order_index=2,
                config={
                    "duration_minutes": 8,
                    "max_votes_per_user": 3,
                    "options": [{"id": "a", "label": "Option A"}],
                },
            ),
        ],
    )

    first_activity = meeting.agenda_activities[0]
    first_activity.started_at = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    first_activity.stopped_at = datetime(2026, 6, 1, 10, 5, tzinfo=UTC)
    first_activity.elapsed_duration = 300
    db_session.add(
        Idea(
            content="Runtime idea",
            meeting_id=meeting.meeting_id,
            activity_id=first_activity.activity_id,
            user_id=participant.user_id,
            idea_metadata={"runtime": True},
        )
    )
    db_session.add(
        VotingVote(
            meeting_id=meeting.meeting_id,
            activity_id=meeting.agenda_activities[1].activity_id,
            user_id=participant.user_id,
            option_id="a",
            option_label="Option A",
            weight=1,
        )
    )
    db_session.add(
        ActivityBundle(
            bundle_id="bundle-runtime-1",
            meeting_id=meeting.meeting_id,
            activity_id=first_activity.activity_id,
            kind="output",
            items=[{"content": "Runtime bundle item", "metadata": {"votes": 1}}],
            bundle_metadata={"runtime": True},
        )
    )
    db_session.commit()

    template = MeetingTemplateManager(db_session).save_custom_template_from_meeting(
        meeting_id=meeting.meeting_id,
        creator_user_id=owner.user_id,
        name="Reusable Weekly Delphi",
        purpose="Repeatable prioritization",
        tags=["Delphi", "Copper Compass", "Delphi"],
    )

    assert template.source == MeetingTemplateSource.CUSTOM.value
    assert template.created_by_user_id == owner.user_id
    assert template.tags == ["Delphi", "Copper Compass"]
    payload = template.template_payload
    assert payload["metadata"]["phase_canary"] == "Copper Compass"
    assert payload["defaults"] == {
        "title": "Weekly Delphi",
        "description": "Decide the next release focus.",
    }
    assert [item["title"] for item in payload["agenda"]] == [
        "Collect options",
        "Prioritize options",
    ]
    assert payload["agenda"][0]["duration_minutes"] == 12
    assert payload["agenda"][0]["config"]["prompt"] == "Release focus"
    assert payload["agenda"][0]["config"]["display"]["labels"] == ["saved"]
    assert payload["agenda"][1]["config"]["options"][0]["label"] == "Option A"

    payload_json = json.dumps(payload)
    assert participant.user_id not in payload_json
    assert first_activity.activity_id not in payload_json
    runtime_keys = _payload_keys(payload)
    assert "output_bundle" not in runtime_keys
    assert "votes" not in runtime_keys
    assert "elapsedTime" not in runtime_keys
    assert "started_at" not in runtime_keys
    assert "stopped_at" not in runtime_keys
    assert "participant_ids" not in runtime_keys
    assert "runtime_data" not in runtime_keys


def test_create_meeting_from_custom_template_uses_clean_agenda_payload(db_session):
    """Copper Compass: ordinary templates create a fresh linear meeting from structure only."""
    owner = _user("customowner", "facilitator")
    db_session.add(owner)
    db_session.commit()

    source_meeting = MeetingManager(db_session).create_meeting(
        meeting_data=MeetingCreate(
            title="Reusable Linear Workshop",
            description="A clean agenda should survive; runtime data should not.",
            duration_minutes=60,
            publicity=PublicityType.PRIVATE,
            owner_id=owner.user_id,
        ),
        facilitator_id=owner.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Collect options",
                instructions="Capture candidate actions.",
                order_index=1,
                config={
                    "prompt": "Suggest actions",
                    "duration_minutes": 15,
                    "nested": {
                        "kept": "facilitator default",
                        "votes": [{"user_id": owner.user_id, "option": "runtime"}],
                    },
                },
            ),
            AgendaActivityCreate(
                tool_type="voting",
                title="Prioritize options",
                instructions="Vote on the candidate actions.",
                order_index=2,
                config={"max_votes_per_user": 3},
            ),
        ],
    )

    manager = MeetingTemplateManager(db_session)
    template = manager.save_custom_template_from_meeting(
        meeting_id=source_meeting.meeting_id,
        creator_user_id=owner.user_id,
        name="Linear Workshop Template",
    )

    meeting = manager.create_meeting_from_template(
        template_id=template.template_id,
        facilitator_id=owner.user_id,
        meeting_data=MeetingCreate(
            title="Fresh Linear Workshop",
            description="Started from a custom template.",
            duration_minutes=60,
            publicity=PublicityType.PRIVATE,
            owner_id=owner.user_id,
        ),
    )

    assert meeting.agenda_strategy == "linear"
    assert meeting.orchestration_path is None
    assert meeting.source_template_id == template.template_id
    assert [activity.title for activity in meeting.agenda_activities] == [
        "Collect options",
        "Prioritize options",
    ]
    first_config = meeting.agenda_activities[0].config
    assert first_config["prompt"] == "Suggest actions"
    assert first_config["duration_minutes"] == 15
    assert first_config["nested"] == {"kept": "facilitator default"}
    assert owner.user_id not in json.dumps(
        [activity.config for activity in meeting.agenda_activities]
    )


def test_template_permission_model_builtin_and_custom(db_session):
    """Copper Compass: built-ins are read-only; custom templates are owner/admin-managed."""
    admin = _user("admin", "admin")
    facilitator = _user("facilitator", "facilitator")
    other_facilitator = _user("other", "facilitator")
    participant = _user("viewer", "participant")
    db_session.add_all([admin, facilitator, other_facilitator, participant])
    db_session.commit()

    manager = MeetingTemplateManager(db_session)
    builtin = manager.upsert_builtin_template(
        built_in_key="classical-delphi",
        name="Classical Delphi",
        purpose="Iterative anonymous expert convergence.",
        description="A stock collaboration process for Delphi-style decisions.",
        estimated_duration_minutes=60,
        min_participants=3,
        max_participants=25,
        tags=["Delphi", "Expert judgment", "Copper Compass"],
        flow_type=MeetingTemplateFlowType.MULTI_ROUND,
        template_payload=MeetingTemplatePayload(
            defaults={"title": "Classical Delphi"},
            agenda=[
                {
                    "tool_type": "brainstorming",
                    "title": "Round 1 responses",
                    "order_index": 1,
                    "config": {"max_rounds": 3},
                }
            ],
            metadata={"phase_canary": "Copper Compass"},
        ),
    )
    custom = MeetingTemplate(
        template_id="custom-template-1",
        source=MeetingTemplateSource.CUSTOM.value,
        status="active",
        name="Team Retrospective",
        created_by_user_id=facilitator.user_id,
        flow_type=MeetingTemplateFlowType.LINEAR.value,
        contract_version=1,
        template_payload={
            "schema_version": 1,
            "defaults": {"title": "Team Retrospective"},
            "agenda": [],
            "parameters": {},
            "metadata": {"phase_canary": "Copper Compass"},
        },
        tags=[],
        template_version=1,
    )
    db_session.add(custom)
    db_session.commit()

    assert manager.permission_summary(builtin, admin).can_start is True
    assert manager.permission_summary(builtin, admin).can_edit is False
    assert manager.permission_summary(builtin, facilitator).is_read_only is True
    assert manager.permission_summary(custom, facilitator).can_edit is True
    assert manager.permission_summary(custom, other_facilitator).can_edit is False
    assert manager.permission_summary(custom, admin).can_delete is True
    assert manager.permission_summary(custom, participant).can_start is False


def test_seed_builtin_delphi_template_references_packaged_orchestration(db_session):
    """Copper Compass: Classical Delphi is an orchestration-backed method template."""
    [template] = seed_builtin_meeting_templates(db_session)

    payload = template.template_payload
    feedback_policy = {
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
        "agreement_bands": {
            "score_source": "iqr",
            "green_max": 1.0,
            "yellow_max": 2.0,
        },
        "participant_prompt": (
            "These items had the widest spread in the last ranking. Add brief "
            "reasons or considerations before the group ranks again."
        ),
        "facilitator_prompt": (
            "Choose how many of the least-agreed items to open for comments before "
            "reranking."
        ),
    }
    assert payload["agenda"] == []
    assert payload["parameters"]["comment_selection_strategy"] == {
        "default": "adaptive_least_converged",
        "source": (
            "orchestration.outlier_justification.feedback_policy.comment_selection.strategy"
        ),
    }
    assert payload["parameters"]["comment_default_fraction"] == {
        "default": 0.25,
        "source": (
            "orchestration.outlier_justification.feedback_policy.comment_selection.default_fraction"
        ),
    }
    assert payload["parameters"]["comment_max_fraction"] == {
        "default": 0.5,
        "source": (
            "orchestration.outlier_justification.feedback_policy.comment_selection.max_fraction"
        ),
    }
    assert payload["orchestration"] == {
        "kind": "orchestration_document",
        "document_path": "orchestrations/delphi.json",
        "document_name": "Classical Delphi",
        "document_version": "1.0",
        "citation": (
            "Linstone, H. A., and Turoff, M., editors. The Delphi Method: "
            "Techniques and Applications. Addison-Wesley, 1975."
        ),
        "instantiation_status": "ready",
        "method_outline": [
            "Generate candidate Delphi items.",
            "Iterate a round subcycle: review feedback and justify, then re-rank.",
            "Transform each round's rankings into statistical feedback (median, IQR).",
            "Evaluate IQR stability and max-round bounds at the round gate.",
        ],
        "runtime_gates": [
            "Additional ranking rounds are materialized only if convergence has not been reached.",
            "The process stops when IQR stability fires or the maximum-round bound is reached.",
            "Future facilitator or AI review steps can add explicit continue/stop decisions.",
        ],
        "feedback_policy": feedback_policy,
    }
    assert "Strong agreement" not in json.dumps(payload)
    assert "Divergent view" not in json.dumps(payload)
    assert MeetingTemplateManager(db_session).template_start_block_reason(template) is None


def test_persisted_orchestration_meeting_rebinds_to_engine_strategy(db_session):
    """Copper Compass: template-created meetings can persist orchestration binding."""
    owner = _user("engineowner", "facilitator")
    db_session.add(owner)
    db_session.commit()

    meeting = MeetingManager(db_session).create_meeting(
        meeting_data=MeetingCreate(
            title="Packaged Delphi",
            description="Exercise persisted orchestration binding.",
            duration_minutes=60,
            publicity=PublicityType.PRIVATE,
            owner_id=owner.user_id,
            agenda_strategy="orchestration",
            orchestration_path="orchestrations/delphi.json",
            source_template_id="builtin-classical-delphi",
        ),
        facilitator_id=owner.user_id,
    )

    strategy = get_agenda_strategy(meeting)
    assert isinstance(strategy, OrchestrationEngineStrategy)
    assert meeting.agenda_strategy == "orchestration"
    assert meeting.orchestration_path == "orchestrations/delphi.json"
    assert meeting.source_template_id == "builtin-classical-delphi"


def test_create_meeting_from_orchestration_template_materializes_first_step_only(db_session):
    """Copper Compass: orchestration templates create a bound meeting, not a fixed agenda."""
    owner = _user("templateowner", "facilitator")
    db_session.add(owner)
    db_session.commit()
    [template] = seed_builtin_meeting_templates(db_session)

    meeting = MeetingTemplateManager(db_session).create_meeting_from_template(
        template_id=template.template_id,
        facilitator_id=owner.user_id,
        meeting_data=MeetingCreate(
            title="Template Delphi Run",
            description="Use the packaged method outline.",
            duration_minutes=90,
            publicity=PublicityType.PRIVATE,
            owner_id=owner.user_id,
        ),
    )

    assert meeting.agenda_strategy == "orchestration"
    assert meeting.orchestration_path == "orchestrations/delphi.json"
    assert meeting.source_template_id == template.template_id
    assert len(meeting.agenda_activities) == 1
    first_activity = meeting.agenda_activities[0]
    assert first_activity.tool_type == "brainstorming"
    assert first_activity.title == "Round 1: Generate Delphi Items"
    assert "rank_order_voting" not in [item.tool_type for item in meeting.agenda_activities]


def test_activity_context_persists_orchestration_iteration_metadata(db_session):
    """Copper Compass: activity close can survive request-bound orchestration state."""
    owner = _user("bundleowner", "facilitator")
    db_session.add(owner)
    db_session.commit()

    meeting = MeetingManager(db_session).create_meeting(
        meeting_data=MeetingCreate(
            title="Round Metadata",
            description="Persist bundle iteration identity from activity config.",
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=owner.user_id,
        ),
        facilitator_id=owner.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Round activity",
                order_index=1,
                config={
                    "_orchestration": {
                        "logical_step_id": "engine:1.0",
                        "round_index": 2,
                    }
                },
            )
        ],
    )
    activity = meeting.agenda_activities[0]

    bundle = ActivityContext(
        db=db_session,
        meeting=meeting,
        activity=activity,
        user=owner,
    ).finalize_output_bundle(
        [{"content": "Round output"}],
        metadata={"source": "test"},
    )

    assert bundle.logical_step_id == "engine:1.0"
    assert bundle.round_index == 2
    assert bundle.bundle_metadata["iteration"] == {
        "logical_step_id": "engine:1.0",
        "round_index": 2,
    }


# ---------------------------------------------------------------------------
# Plainspoken Marmot — Phase 9 Step 1: fork-and-tune
# ---------------------------------------------------------------------------

def test_fork_orchestration_template_persists_inline_tuned_document(db_session):
    """Plainspoken Marmot: forking compiles plain tuning into a custom template
    that stores the tuned orchestration document inline."""
    owner = _user("forkowner", "facilitator")
    db_session.add(owner)
    db_session.commit()
    [delphi] = seed_builtin_meeting_templates(db_session)

    manager = MeetingTemplateManager(db_session)
    forked, summary = manager.fork_orchestration_template(
        base_template_id=delphi.template_id,
        name="Faster Delphi",
        created_by_user_id=owner.user_id,
        max_rounds=2,
        who_decides="automatic",
    )

    assert forked.source == "custom"
    payload = forked.template_payload
    orchestration = payload["orchestration"]
    assert orchestration["kind"] == "orchestration_document"
    assert orchestration["forked_from"] == delphi.template_id
    # The tuned document is stored inline, not as a file path.
    document = orchestration["document"]
    iterate = document["steps"][0]["steps"][1]
    assert iterate["max_rounds"] == 2
    assert "round_gate" not in iterate
    assert isinstance(summary, list) and summary


def test_fork_orchestration_template_tunes_comment_workload(db_session):
    """Plainspoken Marmot: the adaptive comment workload chosen at fork time
    compiles into the inline document's feedback policy and the summary."""
    from app.services.orchestration_authoring import _feedback_policy_steps

    owner = _user("forkcomments", "facilitator")
    db_session.add(owner)
    db_session.commit()
    [delphi] = seed_builtin_meeting_templates(db_session)

    manager = MeetingTemplateManager(db_session)
    forked, summary = manager.fork_orchestration_template(
        base_template_id=delphi.template_id,
        name="Lighter-comment Delphi",
        created_by_user_id=owner.user_id,
        comment_default_fraction=0.2,
        comment_max_fraction=0.4,
    )

    document = forked.template_payload["orchestration"]["document"]
    selection = _feedback_policy_steps(document)[0]["config"]["feedback_policy"][
        "comment_selection"
    ]
    assert selection["default_fraction"] == 0.2
    assert selection["max_fraction"] == 0.4
    text = " ".join(summary).lower()
    assert "most-disputed ideas are opened for comment" in text


def test_meeting_created_from_forked_template_resolves_inline_document(db_session):
    """Plainspoken Marmot: a meeting from a forked template binds to the inline
    document via a template:// path and the engine materializes its first step."""
    owner = _user("forkrunner", "facilitator")
    db_session.add(owner)
    db_session.commit()
    [delphi] = seed_builtin_meeting_templates(db_session)

    manager = MeetingTemplateManager(db_session)
    forked, _summary = manager.fork_orchestration_template(
        base_template_id=delphi.template_id,
        name="Tuned Delphi",
        created_by_user_id=owner.user_id,
        max_rounds=3,
        convergence_threshold=0.2,
    )

    meeting = manager.create_meeting_from_template(
        template_id=forked.template_id,
        facilitator_id=owner.user_id,
        meeting_data=MeetingCreate(
            title="Forked Delphi Run",
            description="Run a tuned Delphi fork.",
            duration_minutes=60,
            publicity=PublicityType.PRIVATE,
            owner_id=owner.user_id,
        ),
    )

    assert meeting.agenda_strategy == "orchestration"
    assert meeting.orchestration_path == f"template://{forked.template_id}"
    assert meeting.source_template_id == forked.template_id
    # The engine resolves the inline document and materialized exactly the first step.
    assert len(meeting.agenda_activities) == 1
    assert meeting.agenda_activities[0].tool_type == "brainstorming"

    # get_agenda_strategy resolves template:// to a real orchestration engine.
    strategy = get_agenda_strategy(meeting)
    assert isinstance(strategy, OrchestrationEngineStrategy)
