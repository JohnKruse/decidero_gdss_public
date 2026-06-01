import json
from datetime import UTC, datetime

from app.data.meeting_manager import MeetingManager
from app.data.meeting_template_manager import MeetingTemplateManager
from app.models.activity_bundle import ActivityBundle
from app.models.idea import Idea
from app.models.meeting_template import MeetingTemplate
from app.models.user import User
from app.models.voting import VotingVote
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.schemas.meeting_template import (
    MeetingTemplateFlowType,
    MeetingTemplatePayload,
    MeetingTemplateSource,
)


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
