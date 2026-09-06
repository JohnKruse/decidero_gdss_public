import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, UTC

from fastapi.testclient import TestClient

import app.routers.transfer as transfer_router_module
from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_manager import MeetingManager
from app.models.activity_bundle import ActivityBundle
from app.models.categorization import CategorizationItem
from app.models.facilitator_edit import FacilitatorEditEvent
from app.models.idea import Idea
from app.models.meeting import AgendaActivity
from app.models.user import UserRole
from app.models.voting import VotingVote
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services.categorization_manager import CategorizationManager
from app.services.voting_manager import VotingManager
from app.services import meeting_state_manager
from app.schemas.transfer import TransferTargetActivity
from app.utils.security import get_password_hash
from pydantic import ValidationError


def test_transfer_target_schema_accepts_tool_type_only():
    obj = TransferTargetActivity(tool_type="voting")
    assert obj.tool_type == "voting"
    assert obj.activity_id is None


def test_transfer_target_schema_accepts_activity_id_only():
    obj = TransferTargetActivity(activity_id="VO-0003")
    assert obj.activity_id == "VO-0003"
    assert obj.tool_type is None


def test_transfer_target_schema_accepts_both():
    obj = TransferTargetActivity(tool_type="voting", activity_id="VO-0003")
    assert obj.tool_type == "voting"
    assert obj.activity_id == "VO-0003"


def test_transfer_target_schema_rejects_neither():
    try:
        TransferTargetActivity()
        assert False, "Should have raised ValidationError"
    except ValidationError:
        pass


def test_transfer_commit_response_contains_target_activity(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Response Contract Test",
            description="Commit response should expose target_activity and new_activity.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Donor")],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Seed idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"tool_type": "voting"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        payload = commit_resp.json()
        assert "target_activity" in payload
        assert "new_activity" in payload
        assert payload["target_activity"] == payload["new_activity"]
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_off_roster_facilitator_cannot_access_transfer_routes(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    off_roster_password = "TransferOffRoster1!"
    off_roster_facilitator = user_manager_with_admin.add_user(
        first_name="Transfer",
        last_name="OffRoster",
        email="transfer.off.roster@example.com",
        hashed_password=get_password_hash(off_roster_password),
        role=UserRole.FACILITATOR.value,
        login="transfer_off_roster",
    )
    db_session.commit()
    db_session.refresh(off_roster_facilitator)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Off Roster Access",
            description="Off-roster facilitators must not get transfer access.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=60),
            duration_minutes=60,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Donor")],
    )
    assert meeting is not None
    activity_id = meeting.agenda_activities[0].activity_id

    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "brainstorming",
                "status": "in_progress",
            },
        )
    )
    db_session.add(
        Idea(
            meeting_id=meeting.meeting_id,
            activity_id=activity_id,
            content="Seed transfer idea",
            user_id=facilitator.user_id,
        )
    )
    db_session.commit()

    login_res = client.post(
        "/api/auth/token",
        json={
            "username": off_roster_facilitator.login,
            "password": off_roster_password,
        },
    )
    assert login_res.status_code == 200, login_res.json()

    bundle_res = client.get(
        f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
        params={"activity_id": activity_id},
    )
    assert bundle_res.status_code == 403


def test_transfer_eligible_rejects_self_transfer(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Self Eligibility Test",
            description="Target must not be the donor.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Donor")],
    )
    donor_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Donor idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": donor_id},
            },
        )
        assert commit_resp.status_code == 422, commit_resp.json()
        assert "donor activity itself" in commit_resp.json().get("detail", "")
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_allows_started_activity_and_records_edit(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
    mocker,
):
    """Facilitator edit policy: started target is allowed and audit event is recorded."""
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Started Eligibility Test",
            description="Started target is allowed and records audit.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(tool_type="voting", title="Target"),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Donor idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        target_row = meeting.agenda_activities[1]
        target_row.started_at = datetime.now(UTC)
        db_session.commit()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        strategy_spy = mocker.spy(transfer_router_module, "get_agenda_strategy")
        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        assert strategy_spy.call_count >= 1

        event = (
            db_session.query(FacilitatorEditEvent)
            .filter(
                FacilitatorEditEvent.meeting_id == meeting.meeting_id,
                FacilitatorEditEvent.activity_id == target_id,
            )
            .first()
        )
        assert event is not None
        assert event.actor_user_id == facilitator.user_id
        assert event.event_type == "package_edited"
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_allows_activity_with_data_and_records_edit(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Target Data Eligibility Test",
            description="Target with participant data is allowed and records audit.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(
                tool_type="voting",
                title="Target",
                config={"options": ["Alpha", "Beta"], "max_votes": 1},
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Donor idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        db_session.add(
            VotingVote(
                meeting_id=meeting.meeting_id,
                activity_id=target_id,
                user_id=facilitator.user_id,
                option_id=f"{target_id}:alpha",
                option_label="Alpha",
                weight=1,
            )
        )
        db_session.commit()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()

        event = (
            db_session.query(FacilitatorEditEvent)
            .filter(
                FacilitatorEditEvent.meeting_id == meeting.meeting_id,
                FacilitatorEditEvent.activity_id == target_id,
            )
            .first()
        )
        assert event is not None
        assert event.actor_user_id == facilitator.user_id
        assert event.event_type == "package_edited"
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_into_existing_voting_replaces_options(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Existing Voting Replace Test",
            description="Existing-target commit replaces voting options and preserves settings.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(
                tool_type="voting",
                title="Eligible Target",
                config={"options": ["Placeholder A"], "max_votes": 5},
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Donor idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()

        refreshed = (
            db_session.query(type(meeting.agenda_activities[1]))
            .filter(type(meeting.agenda_activities[1]).activity_id == target_id)
            .first()
        )
        assert refreshed is not None
        config = dict(refreshed.config or {})
        assert config.get("options") == ["Donor idea"]
        assert config.get("max_votes") == 5
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_into_existing_categorization_seeds_state(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Existing Categorization State Test",
            description="Existing-target categorization transfer should seed state.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(
                tool_type="categorization",
                title="Categorization Target",
                config={
                    "items": ["Old card"],
                    "buckets": [{"title": "Bucket 1"}],
                    "mode": "FACILITATOR_LIVE",
                },
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Donor card 1"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()

        refreshed = meeting_manager.get_meeting(meeting.meeting_id)
        target = next(
            item for item in refreshed.agenda_activities if item.activity_id == target_id
        )
        config = dict(target.config or {})
        assert config.get("items") == ["Donor card 1"]
        assert config.get("buckets") == [{"title": "Bucket 1"}]

        seeded_rows = (
            db_session.query(CategorizationItem)
            .filter(
                CategorizationItem.meeting_id == meeting.meeting_id,
                CategorizationItem.activity_id == target_id,
            )
            .all()
        )
        assert seeded_rows
        assert any((row.content or "") == "Donor card 1" for row in seeded_rows)
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_into_existing_brainstorming_seeds_ideas(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Existing Brainstorming Seed Test",
            description="Existing-target brainstorming transfer should seed ideas and comments.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Donor",
                config={"allow_subcomments": True},
            ),
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Target",
                config={"allow_subcomments": True},
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Parent idea"},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent = parent_resp.json()

        child_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Child comment", "parent_id": parent["id"]},
        )
        assert child_resp.status_code == 201, child_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "true"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": True,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()

        seeded_rows = (
            db_session.query(Idea)
            .filter(Idea.meeting_id == meeting.meeting_id, Idea.activity_id == target_id)
            .all()
        )
        assert len(seeded_rows) >= 2

        parent_rows = [row for row in seeded_rows if row.parent_id is None]
        comment_rows = [row for row in seeded_rows if row.parent_id is not None]
        assert any((row.content or "") == "Parent idea" for row in parent_rows)
        assert any((row.content or "") == "Child comment" for row in comment_rows)
        assert any(
            comment.parent_id in {idea.id for idea in parent_rows}
            for comment in comment_rows
        )
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_into_existing_response_shape(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Existing Response Shape Test",
            description="Existing-target response should set target_activity and new_activity=None.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(tool_type="voting", title="Target", config={"max_votes": 3}),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        initial_agenda_len = len(meeting.agenda_activities)
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )
        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Shape seed"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()
        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        payload = commit_resp.json()
        assert payload["target_activity"]["activity_id"] == target_id
        assert payload["new_activity"] is None
        assert isinstance(payload.get("agenda"), list)
        assert isinstance(payload.get("input_bundle_id"), str)
        assert len(payload["agenda"]) == initial_agenda_len
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_into_existing_creates_input_bundle(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Existing Input Bundle Test",
            description="Existing-target transfer should create input bundle with target metadata.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(tool_type="voting", title="Target", config={"max_votes": 2}),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )
        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Bundle seed"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()
        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()

        bundles = (
            db_session.query(ActivityBundle)
            .filter(
                ActivityBundle.meeting_id == meeting.meeting_id,
                ActivityBundle.activity_id == target_id,
                ActivityBundle.kind == "input",
            )
            .all()
        )
        assert len(bundles) == 1
        bundle = bundles[0]
        assert [entry.get("content") for entry in (bundle.items or [])] == ["Bundle seed"]
        metadata = dict(bundle.bundle_metadata or {})
        history = metadata.get("history") or []
        assert history
        last = history[-1]
        details = dict(last.get("details") or {})
        assert details.get("target_mode") == "existing"
        assert details.get("target_activity_id") == target_id
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_into_existing_rank_order_voting_populates_ideas(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Existing ROV Seed Test",
            description="Existing-target rank-order voting should remap ideas and preserve settings.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(
                tool_type="rank_order_voting",
                title="ROV Target",
                config={
                    "ideas": [{"id": 1, "content": "Placeholder"}],
                    "randomize_order": True,
                    "allow_reset": False,
                },
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )
        for text in ("Gamma", "Delta"):
            idea_resp = authenticated_client.post(
                f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
                json={"content": text},
            )
            assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        payload = commit_resp.json()
        assert payload["new_activity"] is None

        refreshed = meeting_manager.get_meeting(meeting.meeting_id)
        target = next(
            item for item in refreshed.agenda_activities if item.activity_id == target_id
        )
        config = dict(target.config or {})
        ideas = config.get("ideas") or []
        contents = [
            str(entry.get("content") or "")
            for entry in ideas
            if isinstance(entry, dict)
        ]
        assert contents == ["Gamma", "Delta"]
        assert config.get("randomize_order") is True
        assert config.get("allow_reset") is False
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_into_existing_twice_replaces_first(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Existing Retransfer Test",
            description="Second transfer into same target should replace first payload.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor 1"),
            AgendaActivityCreate(
                tool_type="voting",
                title="Voting Target",
                config={"options": ["Placeholder A"], "max_votes": 1},
            ),
        ],
    )
    donor_1_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_1_id,
                    "agendaItemId": donor_1_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )
        for text in ("Alpha", "Beta"):
            idea_resp = authenticated_client.post(
                f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
                json={"content": text},
            )
            assert idea_resp.status_code == 201, idea_resp.json()

        bundles_1 = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_1_id, "include_comments": "false"},
        )
        assert bundles_1.status_code == 200, bundles_1.json()
        items_1 = bundles_1.json()["input"]["items"]

        commit_1 = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_1_id,
                "include_comments": False,
                "items": items_1,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_1.status_code == 200, commit_1.json()

        donor_2 = meeting_manager.add_agenda_activity(
            meeting.meeting_id,
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Donor 2",
                order_index=(meeting.agenda_activities[-1].order_index or 0) + 1,
            ),
        )
        donor_2_id = donor_2.activity_id
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_2_id,
                    "agendaItemId": donor_2_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )
        for text in ("Gamma", "Delta"):
            idea_resp = authenticated_client.post(
                f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
                json={"content": text},
            )
            assert idea_resp.status_code == 201, idea_resp.json()

        bundles_2 = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_2_id, "include_comments": "false"},
        )
        assert bundles_2.status_code == 200, bundles_2.json()
        items_2 = bundles_2.json()["input"]["items"]

        commit_2 = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_2_id,
                "include_comments": False,
                "items": items_2,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_2.status_code == 200, commit_2.json()

        refreshed = meeting_manager.get_meeting(meeting.meeting_id)
        target = next(
            item for item in refreshed.agenda_activities if item.activity_id == target_id
        )
        config = dict(target.config or {})
        assert config.get("options") == ["Gamma", "Delta"]

        input_bundles = (
            db_session.query(ActivityBundle)
            .filter(
                ActivityBundle.meeting_id == meeting.meeting_id,
                ActivityBundle.activity_id == target_id,
                ActivityBundle.kind == "input",
            )
            .all()
        )
        assert len(input_bundles) == 1
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_into_existing_replaces_ai_prepopulated_config(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Existing AI Config Replace Test",
            description="Transfer should replace AI-prepopulated options and preserve settings.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(
                tool_type="voting",
                title="Voting Target",
                config={
                    "options": ["AI Option 1", "AI Option 2", "AI Option 3"],
                    "max_votes": 2,
                },
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )
        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Human Idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"activity_id": target_id},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()

        refreshed = meeting_manager.get_meeting(meeting.meeting_id)
        target = next(
            item for item in refreshed.agenda_activities if item.activity_id == target_id
        )
        config = dict(target.config or {})
        assert config.get("options") == ["Human Idea"]
        assert config.get("max_votes") == 2
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_bundles_seed_from_brainstorming(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Seed Test",
            description="Seed transfer bundles from brainstorming ideas.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Round 1",
                config={"allow_subcomments": True},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )

        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Parent idea"},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent = parent_resp.json()

        subcomment_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Child comment", "parent_id": parent["id"]},
        )
        assert subcomment_resp.status_code == 201, subcomment_resp.json()

        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        response = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "true"},
        )
        assert response.status_code == 200, response.json()
        payload = response.json()
        items = payload["input"]["items"]
        assert len(items) == 2

        response_no_comments = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "false"},
        )
        assert response_no_comments.status_code == 200, response_no_comments.json()
        items_no_comments = response_no_comments.json()["input"]["items"]
        assert len(items_no_comments) == 1
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_bundles_use_voting_plugin_source(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Voting Transfer Source Test",
            description="Transfer bundles should use voting plugin source.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="voting",
                title="Vote Round",
                config={"options": ["Option A", "Option B"]},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
        params={"activity_id": activity_id, "include_comments": "true"},
    )
    assert response.status_code == 200, response.json()
    items = response.json()["input"]["items"]
    assert len(items) == 2


def test_transfer_bundles_sort_voting_results_with_metadata(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Voting Transfer Sorting Test",
            description="Transfer bundles should sort by votes and include ranks.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="voting",
                title="Vote Round",
                config={"options": ["Alpha", "beta", "Gamma"]},
            )
        ],
    )
    activity = meeting.agenda_activities[0]
    voting_manager = VotingManager(db_session)
    options = voting_manager._extract_options(activity)
    option_ids = {option.label: option.option_id for option in options}

    db_session.add_all(
        [
            VotingVote(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id=facilitator.user_id,
                option_id=option_ids["Alpha"],
                option_label="Alpha",
                weight=2,
            ),
            VotingVote(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id=facilitator.user_id,
                option_id=option_ids["beta"],
                option_label="beta",
                weight=2,
            ),
            VotingVote(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id=facilitator.user_id,
                option_id=option_ids["Gamma"],
                option_label="Gamma",
                weight=1,
            ),
        ]
    )
    db_session.commit()

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
        params={"activity_id": activity.activity_id, "include_comments": "true"},
    )
    assert response.status_code == 200, response.json()
    items = response.json()["input"]["items"]
    assert [item.get("content") for item in items] == [
        "Alpha (Votes: 2)",
        "beta (Votes: 2)",
        "Gamma (Votes: 1)",
    ]
    assert items[0]["metadata"]["votes"] == 2
    assert items[0]["metadata"]["voting"]["votes"] == 2
    assert items[0]["metadata"]["voting"]["rank"] == 1
    assert items[1]["metadata"]["votes"] == 2
    assert items[1]["metadata"]["voting"]["votes"] == 2
    assert items[1]["metadata"]["voting"]["rank"] == 2
    assert items[2]["metadata"]["votes"] == 1
    assert items[2]["metadata"]["voting"]["votes"] == 1
    assert items[2]["metadata"]["voting"]["rank"] == 3


def test_transfer_commit_from_voting_carries_vote_suffix_into_next_activity(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Voting Transfer Vote Suffix Test",
            description="Transferred voting ideas should carry vote totals in content.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="voting",
                title="Vote Round",
                config={"options": ["Alpha", "Gamma"]},
            )
        ],
    )
    activity = meeting.agenda_activities[0]
    voting_manager = VotingManager(db_session)
    options = voting_manager._extract_options(activity)
    option_ids = {option.label: option.option_id for option in options}

    db_session.add_all(
        [
            VotingVote(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id=facilitator.user_id,
                option_id=option_ids["Alpha"],
                option_label="Alpha",
                weight=3,
            ),
            VotingVote(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id=facilitator.user_id,
                option_id=option_ids["Gamma"],
                option_label="Gamma",
                weight=1,
            ),
        ]
    )
    db_session.commit()

    bundles_resp = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
        params={"activity_id": activity.activity_id, "include_comments": "true"},
    )
    assert bundles_resp.status_code == 200, bundles_resp.json()
    items = bundles_resp.json()["input"]["items"]
    assert [item.get("content") for item in items] == [
        "Alpha (Votes: 3)",
        "Gamma (Votes: 1)",
    ]

    commit_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json={
            "donor_activity_id": activity.activity_id,
            "include_comments": True,
            "items": items,
            "metadata": {},
            "target_activity": {"tool_type": "voting"},
        },
    )
    assert commit_resp.status_code == 200, commit_resp.json()
    new_activity_id = commit_resp.json()["new_activity"]["activity_id"]

    options_resp = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": new_activity_id},
    )
    assert options_resp.status_code == 200, options_resp.json()
    labels = [opt["label"] for opt in options_resp.json().get("options", [])]
    assert labels == ["Alpha (Votes: 3)", "Gamma (Votes: 1)"]


def test_transfer_counts_use_plugin_source(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Voting Transfer Count Test",
            description="Transfer counts should use plugin source.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="voting",
                title="Vote Round",
                config={"options": ["Option A", "Option B"]},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/agenda"
    )
    assert response.status_code == 200, response.json()
    agenda = response.json()
    entry = next(item for item in agenda if item["activity_id"] == activity_id)
    assert entry["transfer_count"] == 2


def test_agenda_includes_transfer_target_eligible_flag(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Agenda Transfer Eligibility Flag Test",
            description="Agenda should expose transfer_target_eligible per activity.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(
                tool_type="voting",
                title="Eligible Voting Target",
                config={"options": ["Alpha", "Beta"], "max_votes": 1},
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_id,
                    "agendaItemId": donor_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Donor idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        agenda_resp = authenticated_client.get(f"/api/meetings/{meeting.meeting_id}/agenda")
        assert agenda_resp.status_code == 200, agenda_resp.json()
        agenda = agenda_resp.json()

        donor_entry = next(item for item in agenda if item["activity_id"] == donor_id)
        target_entry = next(item for item in agenda if item["activity_id"] == target_id)

        assert donor_entry["transfer_target_eligible"] is False
        assert target_entry["transfer_target_eligible"] is True
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_bundles_always_retain_metadata(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Metadata Policy Test",
            description="Metadata should always be retained in transfer payloads.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Metadata Donor",
                config={"allow_subcomments": True},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        metadata_payload = {"tag": "keep", "origin": "unit-test"}
        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Metadata idea", "metadata": metadata_payload},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent = parent_resp.json()

        comment_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={
                "content": "Metadata comment",
                "parent_id": parent["id"],
                "metadata": {"note": "child"},
            },
        )
        assert comment_resp.status_code == 201, comment_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]
        assert len(items) == 1
        assert items[0]["metadata"] == metadata_payload

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"tool_type": "brainstorming"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        commit_payload = commit_resp.json()
        assert commit_payload.get("target_activity") == commit_payload.get("new_activity")
        new_activity_id = commit_payload["new_activity"]["activity_id"]

        transferred = (
            db_session.query(Idea)
            .filter(
                Idea.meeting_id == meeting.meeting_id,
                Idea.activity_id == new_activity_id,
            )
            .order_by(Idea.id)
            .all()
        )
        assert len(transferred) == 1
        assert transferred[0].idea_metadata == metadata_payload
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_draft_and_commit_preserve_item_metadata(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Metadata Round Trip Test",
            description="Draft/commit should preserve voting and history metadata.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Metadata Donor",
                config={"allow_subcomments": False},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Metadata idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]
        assert len(items) == 1

        custom_metadata = {
            "voting": {"votes": 3, "rank": 1},
            "history": [
                {
                    "tool_type": "voting",
                    "activity_id": activity_id,
                    "created_at": datetime.now(UTC).isoformat(),
                    "round_index": 0,
                }
            ],
            "tag": "custom",
        }
        items[0]["metadata"] = custom_metadata

        draft_resp = authenticated_client.put(
            f"/api/meetings/{meeting.meeting_id}/transfer/draft",
            params={"activity_id": activity_id},
            json={
                "include_comments": False,
                "items": items,
                "metadata": {},
            },
        )
        assert draft_resp.status_code == 200, draft_resp.json()
        draft_payload = draft_resp.json()
        draft_items = draft_payload.get("items") or []
        assert len(draft_items) == 1
        assert draft_items[0]["metadata"] == custom_metadata

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": False,
                "items": draft_items,
                "metadata": draft_payload.get("metadata") or {},
                "target_activity": {"tool_type": "brainstorming"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        new_activity_id = commit_resp.json()["new_activity"]["activity_id"]

        transferred = (
            db_session.query(Idea)
            .filter(
                Idea.meeting_id == meeting.meeting_id,
                Idea.activity_id == new_activity_id,
            )
            .order_by(Idea.id)
            .all()
        )
        assert len(transferred) == 1
        assert transferred[0].idea_metadata == custom_metadata
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_copies_config_and_ideas(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Commit Test",
            description="Commit transfer to new brainstorming activity.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Donor Activity",
                config={
                    "allow_anonymous": True,
                    "allow_subcomments": True,
                    "auto_jump_new_ideas": False,
                },
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Seed idea"},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent = parent_resp.json()

        comment_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Seed comment", "parent_id": parent["id"]},
        )
        assert comment_resp.status_code == 201, comment_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "true"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": True,
                "items": items,
                "metadata": {},
                "target_activity": {"tool_type": "brainstorming"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        commit_payload = commit_resp.json()
        assert commit_payload.get("target_activity") == commit_payload.get("new_activity")
        new_activity = commit_payload["new_activity"]
        new_activity_id = new_activity["activity_id"]

        refreshed = meeting_manager.get_meeting(meeting.meeting_id)
        created = next(
            item
            for item in refreshed.agenda_activities
            if item.activity_id == new_activity_id
        )
        assert created.config.get("allow_anonymous") is True
        assert created.config.get("allow_subcomments") is True
        assert created.config.get("auto_jump_new_ideas") is False

        transferred = (
            db_session.query(Idea)
            .filter(
                Idea.meeting_id == meeting.meeting_id,
                Idea.activity_id == new_activity_id,
            )
            .order_by(Idea.id)
            .all()
        )
        assert len(transferred) == 2
        parent_idea = next(item for item in transferred if item.parent_id is None)
        comment_idea = next(item for item in transferred if item.parent_id is not None)
        assert parent_idea.content == "Seed idea"
        assert comment_idea.content == "Seed comment"
        assert comment_idea.parent_id == parent_idea.id
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_metadata_history_on_draft_and_commit(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Metadata History Test",
            description="Ensure transfer metadata history entries are recorded.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Round 1",
                config={"allow_subcomments": True},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Metadata trail idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        draft_resp = authenticated_client.put(
            f"/api/meetings/{meeting.meeting_id}/transfer/draft",
            params={"activity_id": activity_id},
            json={
                "include_comments": False,
                "items": items,
                "metadata": {},
            },
        )
        assert draft_resp.status_code == 200, draft_resp.json()
        draft_payload = draft_resp.json()
        metadata = draft_payload.get("metadata") or {}
        assert metadata.get("schema_version") == 1
        assert metadata.get("meeting_id") == meeting.meeting_id
        assert metadata.get("created_at")
        assert metadata.get("round_index") == 0
        assert metadata.get("source", {}).get("activity_id") == activity_id
        history = metadata.get("history") or []
        assert history
        assert history[-1].get("tool_type") == "transfer_draft"
        assert history[-1].get("created_at")
        assert history[-1].get("created_at") == metadata.get("created_at")

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": False,
                "items": items,
                "metadata": metadata,
                "target_activity": {"tool_type": "brainstorming"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        new_activity_id = commit_resp.json()["new_activity"]["activity_id"]

        bundle_manager = ActivityBundleManager(db_session)
        input_bundle = bundle_manager.get_latest_bundle(
            meeting.meeting_id, new_activity_id, "input"
        )
        assert input_bundle is not None
        commit_metadata = input_bundle.bundle_metadata or {}
        assert commit_metadata.get("schema_version") == 1
        assert commit_metadata.get("meeting_id") == meeting.meeting_id
        assert commit_metadata.get("created_at")
        assert commit_metadata.get("round_index") == 0
        history = commit_metadata.get("history") or []
        assert history
        assert history[-1].get("tool_type") == "transfer_commit"
        assert history[-1].get("created_at")
        assert history[-1].get("created_at") == commit_metadata.get("created_at")
        tools = commit_metadata.get("tools") or {}
        assert tools.get("brainstorming", {}).get("activity_id") == new_activity_id
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_does_not_mutate_donor(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Donor Isolation Test",
            description="Ensure donor ideas remain unchanged.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Donor",
                config={"allow_subcomments": True},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Original idea"},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent = parent_resp.json()

        comment_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Original comment", "parent_id": parent["id"]},
        )
        assert comment_resp.status_code == 201, comment_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "true"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]
        edited_items = [item for item in items if item.get("parent_id") is None]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": False,
                "items": edited_items,
                "metadata": {},
                "target_activity": {"tool_type": "brainstorming"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        new_activity_id = commit_resp.json()["new_activity"]["activity_id"]

        donor_ideas = (
            db_session.query(Idea)
            .filter(Idea.meeting_id == meeting.meeting_id, Idea.activity_id == activity_id)
            .order_by(Idea.id)
            .all()
        )
        assert len(donor_ideas) == 2
        assert donor_ideas[0].content == "Original idea"
        assert donor_ideas[1].content == "Original comment"

        new_ideas = (
            db_session.query(Idea)
            .filter(Idea.meeting_id == meeting.meeting_id, Idea.activity_id == new_activity_id)
            .all()
        )
        assert len(new_ideas) == 1
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_to_voting_preserves_option_labels(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = "admin@decidero.local"
    facilitator = user_manager_with_admin.get_user_by_email(admin_email)
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Voting Label Test",
            description="Ensure voting options preserve idea content.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Ideas",
                config={},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_texts = ["First idea", "Second idea"]
        for text in idea_texts:
            resp = authenticated_client.post(
                f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
                json={"content": text},
            )
            assert resp.status_code == 201, resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"tool_type": "voting"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        new_activity = commit_resp.json()["new_activity"]
        new_activity_id = new_activity["activity_id"]

        options_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/voting/options",
            params={"activity_id": new_activity_id},
        )
        assert options_resp.status_code == 200, options_resp.json()
        labels = [opt["label"] for opt in options_resp.json().get("options", [])]
        assert set(labels) == set(idea_texts)
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_to_categorization_populates_items(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Categorization Seed Test",
            description="Ensure categorization items are seeded from transfer ideas.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Ideas",
                config={"allow_subcomments": True},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Campus parking is limited"},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent = parent_resp.json()
        comment_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Especially during peak classes", "parent_id": parent["id"]},
        )
        assert comment_resp.status_code == 201, comment_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "true"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": True,
                "items": items,
                "metadata": {},
                "target_activity": {"tool_type": "categorization"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        new_activity = commit_resp.json()["new_activity"]
        new_activity_id = new_activity["activity_id"]

        refreshed = meeting_manager.get_meeting(meeting.meeting_id)
        created = next(
            item
            for item in refreshed.agenda_activities
            if item.activity_id == new_activity_id
        )
        seeded_items = created.config.get("items") or []
        assert seeded_items
        assert any("Campus parking is limited" in str(value) for value in seeded_items)
        assert any("Comments:" in str(value) for value in seeded_items)
        assert created.config.get("mode") == "FACILITATOR_LIVE"
        seeded_rows = (
            db_session.query(CategorizationItem)
            .filter(
                CategorizationItem.meeting_id == meeting.meeting_id,
                CategorizationItem.activity_id == new_activity_id,
            )
            .all()
        )
        assert seeded_rows
        assert any("Campus parking is limited" in (row.content or "") for row in seeded_rows)
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_commit_to_rank_order_voting_populates_ideas_and_meeting_stays_readable(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Rank Order Seed Test",
            description="Ensure rank-order ideas are seeded from transfer items.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Ideas",
                config={"allow_subcomments": True},
            )
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": activity_id,
                    "agendaItemId": activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        parent_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Adopt async API gateway"},
        )
        assert parent_resp.status_code == 201, parent_resp.json()
        parent = parent_resp.json()
        comment_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Needs retry semantics", "parent_id": parent["id"]},
        )
        assert comment_resp.status_code == 201, comment_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": activity_id, "include_comments": "true"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": activity_id,
                "include_comments": True,
                "items": items,
                "metadata": {},
                "target_activity": {"tool_type": "rank_order_voting"},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        new_activity = commit_resp.json()["new_activity"]
        new_activity_id = new_activity["activity_id"]

        refreshed = meeting_manager.get_meeting(meeting.meeting_id)
        created = next(
            item
            for item in refreshed.agenda_activities
            if item.activity_id == new_activity_id
        )
        seeded_ideas = created.config.get("ideas") or []
        assert seeded_ideas
        assert any(
            "Adopt async API gateway" in str(idea.get("content") or "")
            for idea in seeded_ideas
            if isinstance(idea, dict)
        )
        assert any(
            "Comments:" in str(idea.get("content") or "")
            for idea in seeded_ideas
            if isinstance(idea, dict)
        )

        summary_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/rank-order-voting/summary",
            params={"activity_id": new_activity_id},
        )
        assert summary_resp.status_code == 200, summary_resp.json()
        assert len(summary_resp.json().get("options", [])) >= 1

        meeting_resp = authenticated_client.get(f"/api/meetings/{meeting.meeting_id}")
        assert meeting_resp.status_code == 200, meeting_resp.json()
        agenda = meeting_resp.json().get("agenda", [])
        assert len(agenda) >= 2
        assert any(
            item.get("activity_id") == activity_id and item.get("transfer_count", 0) >= 1
            for item in agenda
        )
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_transfer_bundles_from_categorization_support_profiles(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Categorization Transfer Profiles",
            description="Ensure categorization transfer supports rollup and suffix profiles.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Buckets",
                config={
                    "mode": "FACILITATOR_LIVE",
                    "items": ["Apply policy", "Train staff", "Reserve room"],
                    "buckets": ["Rules & Regulations", "Logistics", "Unused Bucket"],
                },
            )
        ],
    )
    activity = meeting.agenda_activities[0]
    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=activity,
        actor_user_id=facilitator.user_id,
    )

    buckets = manager.list_buckets(meeting.meeting_id, activity.activity_id)
    rules_bucket = next(bucket for bucket in buckets if bucket.title == "Rules & Regulations")
    logistics_bucket = next(bucket for bucket in buckets if bucket.title == "Logistics")

    items = manager.list_items(meeting.meeting_id, activity.activity_id)
    item_map = {item.content: item.item_key for item in items}
    manager.upsert_assignment(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        item_key=item_map["Apply policy"],
        category_id=rules_bucket.category_id,
        actor_user_id=facilitator.user_id,
    )
    manager.upsert_assignment(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        item_key=item_map["Train staff"],
        category_id=rules_bucket.category_id,
        actor_user_id=facilitator.user_id,
    )
    manager.upsert_assignment(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        item_key=item_map["Reserve room"],
        category_id=logistics_bucket.category_id,
        actor_user_id=facilitator.user_id,
    )

    rollup_resp = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
        params={
            "activity_id": activity.activity_id,
            "include_comments": "false",
            "transfer_profile": "bucket_rollup",
        },
    )
    assert rollup_resp.status_code == 200, rollup_resp.json()
    rollup_items = rollup_resp.json()["input"]["items"]
    assert [item["content"] for item in rollup_items] == [
        "Category: Rules & Regulations (Ideas: Apply policy; Train staff)",
        "Category: Logistics (Ideas: Reserve room)",
        "Category: Unused Bucket (Ideas: )",
    ]

    suffix_resp = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
        params={
            "activity_id": activity.activity_id,
            "include_comments": "false",
            "transfer_profile": "bucket_suffix",
        },
    )
    assert suffix_resp.status_code == 200, suffix_resp.json()
    suffix_items = suffix_resp.json()["input"]["items"]
    assert [item["content"] for item in suffix_items] == [
        "Apply policy (Category: Rules & Regulations)",
        "Train staff (Category: Rules & Regulations)",
        "Reserve room (Category: Logistics)",
    ]


def test_transfer_commit_bucket_rollup_to_voting_accepts_string_ids(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Categorization Rollup To Voting",
            description="Ensure rollup transfer items with string ids can commit to voting.",
            start_time=datetime.now(UTC) + timedelta(minutes=5),
            end_time=datetime.now(UTC) + timedelta(minutes=35),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Buckets",
                config={
                    "mode": "FACILITATOR_LIVE",
                    "items": ["Alpha", "Beta"],
                    "buckets": ["Rules"],
                },
            )
        ],
    )
    activity = meeting.agenda_activities[0]
    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=activity,
        actor_user_id=facilitator.user_id,
    )
    rules_bucket = next(
        bucket
        for bucket in manager.list_buckets(meeting.meeting_id, activity.activity_id)
        if bucket.title == "Rules"
    )
    for row in manager.list_items(meeting.meeting_id, activity.activity_id):
        manager.upsert_assignment(
            meeting_id=meeting.meeting_id,
            activity_id=activity.activity_id,
            item_key=row.item_key,
            category_id=rules_bucket.category_id,
            actor_user_id=facilitator.user_id,
        )

    bundles_resp = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
        params={
            "activity_id": activity.activity_id,
            "include_comments": "false",
            "transfer_profile": "bucket_rollup",
        },
    )
    assert bundles_resp.status_code == 200, bundles_resp.json()
    items = bundles_resp.json()["input"]["items"]
    assert items
    assert isinstance(items[0].get("id"), str)

    commit_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json={
            "donor_activity_id": activity.activity_id,
            "include_comments": False,
            "items": items,
            "metadata": {},
            "target_activity": {"tool_type": "voting"},
        },
    )
    assert commit_resp.status_code == 200, commit_resp.json()
    new_activity_id = commit_resp.json()["new_activity"]["activity_id"]

    options_resp = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/voting/options",
        params={"activity_id": new_activity_id},
    )
    assert options_resp.status_code == 200, options_resp.json()
    labels = [opt["label"] for opt in options_resp.json().get("options", [])]
    assert any(label.startswith("Category: Rules") for label in labels)


def test_transfer_commit_to_voting_resets_stale_state(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Transfer Voting Reset",
            description="Ensure transfer to voting clears old votes/bundles.",
            start_time=datetime.now(UTC) + timedelta(minutes=5),
            end_time=datetime.now(UTC) + timedelta(minutes=35),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(
                tool_type="voting",
                title="Stale Voting",
                config={"options": ["Alpha", "Beta"], "max_votes": 3},
            ),
        ],
    )
    donor_activity = meeting.agenda_activities[0]
    stale_activity = meeting.agenda_activities[1]

    bundle_manager = ActivityBundleManager(db_session)
    bundle_manager.create_bundle(
        meeting.meeting_id,
        stale_activity.activity_id,
        "input",
        [{"content": "Old option"}],
        metadata={"source": "legacy"},
    )
    bundle_manager.create_bundle(
        meeting.meeting_id,
        stale_activity.activity_id,
        "output",
        [{"content": "Old option"}],
        metadata={"source": "legacy"},
    )
    db_session.add(
        VotingVote(
            meeting_id=meeting.meeting_id,
            activity_id=stale_activity.activity_id,
            user_id=facilitator.user_id,
            option_id=f"{stale_activity.activity_id}:alpha",
            option_label="Alpha",
            weight=2,
        )
    )
    db_session.commit()

    db_session.delete(stale_activity)
    db_session.commit()

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": donor_activity.activity_id,
                    "agendaItemId": donor_activity.activity_id,
                    "currentTool": "brainstorming",
                    "status": "paused",
                },
            )
        )

        idea_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/brainstorming/ideas",
            json={"content": "Transfer idea"},
        )
        assert idea_resp.status_code == 201, idea_resp.json()

        bundles_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/transfer/bundles",
            params={"activity_id": donor_activity.activity_id, "include_comments": "false"},
        )
        assert bundles_resp.status_code == 200, bundles_resp.json()
        items = bundles_resp.json()["input"]["items"]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_activity.activity_id,
                "include_comments": False,
                "items": items,
                "metadata": {},
                "target_activity": {"tool_type": "voting", "config": {"max_votes": 3}},
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()
        new_activity = commit_resp.json()["new_activity"]
        assert new_activity["activity_id"] == stale_activity.activity_id

        assert (
            db_session.query(VotingVote)
            .filter(
                VotingVote.meeting_id == meeting.meeting_id,
                VotingVote.activity_id == new_activity["activity_id"],
            )
            .count()
            == 0
        )
        assert (
            db_session.query(ActivityBundle)
            .filter(
                ActivityBundle.meeting_id == meeting.meeting_id,
                ActivityBundle.activity_id == new_activity["activity_id"],
            )
            .count()
            == 1
        )

        # Activate the voting activity in the meeting state before querying options
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": new_activity["activity_id"],
                    "agendaItemId": new_activity["activity_id"],
                    "currentTool": "voting",
                    "status": "in_progress",
                },
            )
        )

        options_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/voting/options",
            params={"activity_id": new_activity["activity_id"]},
        )
        assert options_resp.status_code == 200, options_resp.json()
        payload = options_resp.json()
        assert payload["activity_id"] == new_activity["activity_id"]
        assert payload["votes_cast"] == 0
        assert payload["remaining_votes"] == payload["max_votes"]
        assert all(
            option["option_id"].startswith(f"{payload['activity_id']}:")
            for option in payload["options"]
        )
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_commit_curated_package_to_orchestrated_activity_preserves_stable_key_and_donor(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Curated Package Preservation Test",
            description="Commit curated package to orchestrated activity preserves stable_key and donor bundle.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="brainstorming",
                title="Donor Brainstorming",
            ),
            AgendaActivityCreate(
                tool_type="rank_order_voting",
                title="Orchestrated Ranking Target",
                config={
                    "_orchestration": {"round_index": 1},
                    "ideas": [
                        {
                            "id": "old-idea-id",
                            "content": "Old idea",
                            "metadata": {"stable_key": "old-key"},
                        }
                    ],
                },
            ),
        ],
    )
    donor_activity = meeting.agenda_activities[0]
    target_activity = meeting.agenda_activities[1]

    # Seed donor output bundle
    bundle_manager = ActivityBundleManager(db_session)
    donor_items = [
        {
            "id": "donor-item-1",
            "content": "Original text 1",
            "submitted_name": "Alice",
            "parent_id": None,
            "metadata": {"stable_key": "donor-key-1", "origin": "brainstorming"},
            "source": {"original_id": "donor-item-1"},
        },
        {
            "id": "donor-item-2",
            "content": "Original text 2",
            "submitted_name": "Bob",
            "parent_id": None,
            "metadata": {"stable_key": "donor-key-2", "origin": "brainstorming"},
            "source": {"original_id": "donor-item-2"},
        },
    ]
    donor_bundle = bundle_manager.create_bundle(
        meeting.meeting_id,
        donor_activity.activity_id,
        "output",
        donor_items,
        metadata={"source": "brainstorming_output", "total_items": 2},
    )
    db_session.commit()

    # Capture donor bundle before state
    donor_items_before = deepcopy(donor_bundle.items)
    donor_metadata_before = deepcopy(donor_bundle.bundle_metadata)
    donor_updated_at_before = donor_bundle.updated_at

    try:
        # Curate items: rename donor-key-1, omit donor-key-2, add a brand-new item
        curated_items = [
            {
                "id": "donor-item-1",
                "content": "Renamed text 1",
                "submitted_name": "Alice",
                "parent_id": None,
                "metadata": {"stable_key": "donor-key-1", "origin": "brainstorming"},
                "source": {"original_id": "donor-item-1"},
            },
            {
                "id": None,
                "content": "Brand new item added by facilitator",
                "submitted_name": "Facilitator",
                "parent_id": None,
                "metadata": {},
                "source": {},
            },
        ]

        commit_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/transfer/commit",
            json={
                "donor_activity_id": donor_activity.activity_id,
                "include_comments": False,
                "items": curated_items,
                "metadata": {},
                "target_activity": {
                    "activity_id": target_activity.activity_id,
                    "tool_type": "rank_order_voting",
                },
            },
        )
        assert commit_resp.status_code == 200, commit_resp.json()

        # Refresh objects from DB
        db_session.expire_all()
        reloaded_target = (
            db_session.query(AgendaActivity)
            .filter(AgendaActivity.activity_id == target_activity.activity_id)
            .one()
        )
        reloaded_donor_bundle = (
            db_session.query(ActivityBundle)
            .filter(ActivityBundle.bundle_id == donor_bundle.bundle_id)
            .one()
        )

        # (a) Target activity's config items are replaced
        target_ideas = reloaded_target.config.get("ideas", [])
        assert len(target_ideas) == 2
        contents = [idea["content"] for idea in target_ideas]
        assert "Old idea" not in contents
        assert "Renamed text 1" in contents
        assert "Brand new item added by facilitator" in contents
        # Preserves orchestration settings on target
        assert reloaded_target.config.get("_orchestration") == {"round_index": 1}

        # (b) Donor activity's output bundle is byte-identical
        assert reloaded_donor_bundle.items == donor_items_before
        assert reloaded_donor_bundle.bundle_metadata == donor_metadata_before
        assert reloaded_donor_bundle.updated_at == donor_updated_at_before

        # (c) stable_key is preserved on edited item and generated for new item
        edited_idea = next(i for i in target_ideas if i["content"] == "Renamed text 1")
        assert edited_idea["metadata"].get("stable_key") == "donor-key-1"
        assert edited_idea["metadata"].get("origin") == "brainstorming"

        new_idea = next(
            i for i in target_ideas if i["content"] == "Brand new item added by facilitator"
        )
        new_key = new_idea["metadata"].get("stable_key")
        assert new_key is not None
        assert len(new_key) > 0
        assert new_key != "donor-key-1"
        assert new_key != "old-key"
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_seed_brainstorming_ideas_preserves_id_and_user_id_for_unchanged_item(
    user_manager_with_admin,
    db_session,
):
    admin = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert admin is not None

    author = user_manager_with_admin.add_user(
        first_name="Original",
        last_name="Author",
        email="original.author@example.com",
        hashed_password=get_password_hash("AuthorPass123!"),
        role=UserRole.PARTICIPANT.value,
        login="orig_author",
    )
    db_session.commit()
    db_session.refresh(author)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Reconcile Test Meeting",
            description="Test brainstorming seeder reconcile.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=admin.user_id,
            participant_ids=[author.user_id],
            additional_facilitator_ids=[],
        ),
        facilitator_id=admin.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Brainstorm Target"),
        ],
    )
    activity_id = meeting.agenda_activities[0].activity_id

    initial_idea = Idea(
        meeting_id=meeting.meeting_id,
        activity_id=activity_id,
        content="Preserved idea content",
        user_id=author.user_id,
        submitted_name="Alice",
        idea_metadata={"stable_key": "preserved-idea-content"},
    )
    db_session.add(initial_idea)
    db_session.commit()
    db_session.refresh(initial_idea)
    original_id = initial_idea.id
    original_timestamp = initial_idea.timestamp

    incoming_ideas = [
        {
            "id": original_id,
            "content": "Preserved idea content",
            "submitted_name": "Alice Updated",
            "user_id": admin.user_id,
            "metadata": {"stable_key": "preserved-idea-content"},
        },
        {
            "content": "Newly added idea",
            "user_id": admin.user_id,
            "metadata": {"stable_key": "newly-added-idea"},
        },
    ]

    diff = transfer_router_module._seed_brainstorming_ideas(
        db=db_session,
        meeting_id=meeting.meeting_id,
        activity_id=activity_id,
        ideas=incoming_ideas,
        comments_by_parent={},
    )

    rows = (
        db_session.query(Idea)
        .filter(Idea.meeting_id == meeting.meeting_id, Idea.activity_id == activity_id)
        .all()
    )
    assert len(rows) == 2
    unchanged_row = next(r for r in rows if r.content == "Preserved idea content")
    assert unchanged_row.id == original_id
    assert unchanged_row.user_id == author.user_id
    assert unchanged_row.timestamp == original_timestamp

    new_row = next(r for r in rows if r.content == "Newly added idea")
    assert new_row.user_id == admin.user_id

    assert len(diff["added"]) == 1
    assert diff["added"][0]["stable_key"] == "newly-added-idea"
    assert diff["added"][0]["user_id"] == admin.user_id
    assert len(diff["removed"]) == 0
    assert len(diff["changed"]) == 0

