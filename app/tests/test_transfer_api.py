import asyncio
from datetime import datetime, timedelta, UTC

from fastapi.testclient import TestClient

from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_manager import MeetingManager
from app.models.activity_bundle import ActivityBundle
from app.models.categorization import CategorizationItem
from app.models.idea import Idea
from app.models.voting import VotingVote
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services.categorization_manager import CategorizationManager
from app.services.voting_manager import VotingManager
from app.services import meeting_state_manager


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
        new_activity = commit_resp.json()["new_activity"]
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
