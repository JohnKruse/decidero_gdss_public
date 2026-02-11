import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.data.meeting_manager import MeetingManager
from app.models.categorization import CategorizationBallot
from app.models.user import UserRole
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services import meeting_state_manager
from app.services.categorization_manager import CategorizationManager
from app.utils.security import get_password_hash


def _create_categorization_meeting(db_session, owner_id: str):
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Categorization API Test",
            description="Categorization API coverage",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=owner_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=owner_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Categorize",
                config={
                    "mode": "FACILITATOR_LIVE",
                    "items": [{"id": "i-1", "content": "Item 1"}],
                    "buckets": ["Bucket A"],
                },
            )
        ],
    )
    return meeting


def _create_parallel_categorization_meeting(db_session, owner_id: str):
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Categorization Parallel API Test",
            description="Categorization parallel API coverage",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=owner_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=owner_id,
        agenda_items=[
            AgendaActivityCreate(
                tool_type="categorization",
                title="Categorize Parallel",
                config={
                    "mode": "PARALLEL_BALLOT",
                    "private_until_reveal": True,
                    "allow_unsorted_submission": True,
                    "items": [
                        {"id": "pi-1", "content": "Parallel 1"},
                        {"id": "pi-2", "content": "Parallel 2"},
                    ],
                    "buckets": ["Theme A", "Theme B"],
                },
            )
        ],
    )
    return meeting


def test_categorization_state_and_bucket_mutations(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "categorization",
                "status": "in_progress",
                "activeActivities": [
                    {
                        "activityId": activity_id,
                        "tool": "categorization",
                        "status": "in_progress",
                        "metadata": {"participantScope": "all"},
                    }
                ],
            },
        )
    )

    try:
        state_resp = authenticated_client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/state",
            params={"activity_id": activity_id},
        )
        assert state_resp.status_code == 200, state_resp.json()
        state_payload = state_resp.json()
        assert state_payload["unsorted_category_id"] == "UNSORTED"
        assert len(state_payload["items"]) == 1

        create_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/buckets",
            json={"activity_id": activity_id, "title": "Bucket B"},
        )
        assert create_resp.status_code == 200, create_resp.json()
        created_bucket_id = create_resp.json()["category_id"]

        assign_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/assignments",
            json={"activity_id": activity_id, "item_key": "i-1", "category_id": created_bucket_id},
        )
        assert assign_resp.status_code == 200, assign_resp.json()
        assert assign_resp.json()["category_id"] == created_bucket_id
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_categorization_bucket_create_forbidden_for_participant(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    participant = user_manager_with_admin.add_user(
        first_name="Part",
        last_name="User",
        email="participant@decidero.local",
        hashed_password=get_password_hash("Participant@123"),
        role=UserRole.PARTICIPANT.value,
        login="participant",
    )
    meeting.participants.append(participant)
    db_session.add(meeting)
    db_session.commit()

    login_resp = client.post(
        "/api/auth/token",
        json={"username": "participant", "password": "Participant@123"},
    )
    assert login_resp.status_code == 200, login_resp.json()

    create_resp = client.post(
        f"/api/meetings/{meeting.meeting_id}/categorization/buckets",
        json={"activity_id": activity_id, "title": "Not Allowed"},
    )
    assert create_resp.status_code == 403, create_resp.json()


def test_categorization_item_mutations_are_facilitator_only(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    participant = user_manager_with_admin.add_user(
        first_name="Item",
        last_name="Participant",
        email="item.participant@decidero.local",
        hashed_password=get_password_hash("ItemParticipant@123"),
        role=UserRole.PARTICIPANT.value,
        login="item_participant",
    )
    meeting.participants.append(participant)
    db_session.add(meeting)
    db_session.commit()

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "categorization",
                "status": "in_progress",
            },
        )
    )

    try:
        facilitator_login = client.post(
            "/api/auth/token",
            json={"username": "admin", "password": "Admin@123!"},
        )
        assert facilitator_login.status_code == 200, facilitator_login.json()

        create_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/items",
            json={"activity_id": activity_id, "content": "Idea 2"},
        )
        assert create_resp.status_code == 200, create_resp.json()
        item_key = create_resp.json()["item_key"]

        update_resp = client.patch(
            f"/api/meetings/{meeting.meeting_id}/categorization/items/{item_key}",
            json={"activity_id": activity_id, "content": "Idea 2 updated"},
        )
        assert update_resp.status_code == 200, update_resp.json()
        assert update_resp.json()["content"] == "Idea 2 updated"

        participant_login = client.post(
            "/api/auth/token",
            json={"username": "item_participant", "password": "ItemParticipant@123"},
        )
        assert participant_login.status_code == 200, participant_login.json()
        participant_create_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/items",
            json={"activity_id": activity_id, "content": "Not allowed"},
        )
        assert participant_create_resp.status_code == 403, participant_create_resp.json()

        facilitator_login_again = client.post(
            "/api/auth/token",
            json={"username": "admin", "password": "Admin@123!"},
        )
        assert facilitator_login_again.status_code == 200, facilitator_login_again.json()
        delete_resp = client.request(
            "DELETE",
            f"/api/meetings/{meeting.meeting_id}/categorization/items/{item_key}",
            json={"activity_id": activity_id},
        )
        assert delete_resp.status_code == 204
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_categorization_scope_enforced_for_custom_participant_list(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    participant_allowed = user_manager_with_admin.add_user(
        first_name="Allowed",
        last_name="User",
        email="allowed@decidero.local",
        hashed_password=get_password_hash("Allowed@123"),
        role=UserRole.PARTICIPANT.value,
        login="allowed_user",
    )
    participant_blocked = user_manager_with_admin.add_user(
        first_name="Blocked",
        last_name="User",
        email="blocked@decidero.local",
        hashed_password=get_password_hash("Blocked@123"),
        role=UserRole.PARTICIPANT.value,
        login="blocked_user",
    )
    meeting.participants.extend([participant_allowed, participant_blocked])
    db_session.add(meeting)
    db_session.commit()

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "categorization",
                "status": "in_progress",
                "activeActivities": [
                    {
                        "activityId": activity_id,
                        "tool": "categorization",
                        "status": "in_progress",
                        "metadata": {
                            "participantScope": "custom",
                            "participantIds": [participant_allowed.user_id],
                        },
                    }
                ],
            },
        )
    )

    try:
        login_allowed = client.post(
            "/api/auth/token",
            json={"username": "allowed_user", "password": "Allowed@123"},
        )
        assert login_allowed.status_code == 200, login_allowed.json()
        state_allowed = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/state",
            params={"activity_id": activity_id},
        )
        assert state_allowed.status_code == 200, state_allowed.json()

        login_blocked = client.post(
            "/api/auth/token",
            json={"username": "blocked_user", "password": "Blocked@123"},
        )
        assert login_blocked.status_code == 200, login_blocked.json()
        state_blocked = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/state",
            params={"activity_id": activity_id},
        )
        assert state_blocked.status_code == 403, state_blocked.json()
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_categorization_bucket_mutation_requires_active_activity(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )

    create_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/categorization/buckets",
        json={"activity_id": activity_id, "title": "Bucket C"},
    )
    assert create_resp.status_code == 403, create_resp.json()
    assert create_resp.json()["detail"] == "This activity is not open for categorization."


def test_categorization_mutations_broadcast_updates(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "categorization",
                "status": "in_progress",
            },
        )
    )

    try:
        with patch(
            "app.routers.categorization.websocket_manager.broadcast",
            new=AsyncMock(),
        ) as mocked_broadcast:
            create_resp = authenticated_client.post(
                f"/api/meetings/{meeting.meeting_id}/categorization/buckets",
                json={"activity_id": activity_id, "title": "Bucket D"},
            )
            assert create_resp.status_code == 200, create_resp.json()
            created_bucket_id = create_resp.json()["category_id"]

            assign_resp = authenticated_client.post(
                f"/api/meetings/{meeting.meeting_id}/categorization/assignments",
                json={"activity_id": activity_id, "item_key": "i-1", "category_id": created_bucket_id},
            )
            assert assign_resp.status_code == 200, assign_resp.json()
            assert mocked_broadcast.await_count == 2
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_parallel_ballot_lifecycle_and_privacy_controls(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_parallel_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    participant_one = user_manager_with_admin.add_user(
        first_name="Parallel",
        last_name="One",
        email="parallel.one@decidero.local",
        hashed_password=get_password_hash("ParallelOne@123"),
        role=UserRole.PARTICIPANT.value,
        login="parallel_one",
    )
    participant_two = user_manager_with_admin.add_user(
        first_name="Parallel",
        last_name="Two",
        email="parallel.two@decidero.local",
        hashed_password=get_password_hash("ParallelTwo@123"),
        role=UserRole.PARTICIPANT.value,
        login="parallel_two",
    )
    meeting.participants.extend([participant_one, participant_two])
    db_session.add(meeting)
    db_session.commit()

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "categorization",
                "status": "in_progress",
                "activeActivities": [
                    {
                        "activityId": activity_id,
                        "tool": "categorization",
                        "status": "in_progress",
                        "metadata": {"participantScope": "all"},
                    }
                ],
            },
        )
    )

    try:
        facilitator_login = client.post(
            "/api/auth/token",
            json={"username": "admin", "password": "Admin@123!"},
        )
        assert facilitator_login.status_code == 200, facilitator_login.json()

        participant_one_login = client.post(
            "/api/auth/token",
            json={"username": "parallel_one", "password": "ParallelOne@123"},
        )
        assert participant_one_login.status_code == 200, participant_one_login.json()

        hidden_state = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/state",
            params={"activity_id": activity_id},
        )
        assert hidden_state.status_code == 200, hidden_state.json()
        assert hidden_state.json()["assignments"] == {}
        assert hidden_state.json()["agreement_metrics"] == {}

        ballot_state = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/ballot",
            params={"activity_id": activity_id},
        )
        assert ballot_state.status_code == 200, ballot_state.json()
        assert ballot_state.json()["submitted"] is False
        assert len(ballot_state.json()["items"]) == 2

        first_bucket = next(
            bucket["category_id"]
            for bucket in ballot_state.json()["buckets"]
            if bucket["category_id"] != "UNSORTED"
        )
        assign_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/ballot/assignments",
            json={"activity_id": activity_id, "item_key": "pi-1", "category_id": first_bucket},
        )
        assert assign_resp.status_code == 200, assign_resp.json()

        submit_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/ballot/submit",
            json={"activity_id": activity_id},
        )
        assert submit_resp.status_code == 200, submit_resp.json()
        assert submit_resp.json()["submitted"] is True

        facilitator_login_after_submit = client.post(
            "/api/auth/token",
            json={"username": "admin", "password": "Admin@123!"},
        )
        assert facilitator_login_after_submit.status_code == 200, facilitator_login_after_submit.json()
        facilitator_state = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/state",
            params={"activity_id": activity_id},
        )
        assert facilitator_state.status_code == 200, facilitator_state.json()
        assert "pi-1" in facilitator_state.json()["agreement_metrics"]

        participant_two_login = client.post(
            "/api/auth/token",
            json={"username": "parallel_two", "password": "ParallelTwo@123"},
        )
        assert participant_two_login.status_code == 200, participant_two_login.json()
        second_ballot = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/ballot",
            params={"activity_id": activity_id},
        )
        assert second_ballot.status_code == 200, second_ballot.json()
        assert second_ballot.json()["assignments"] == {}

        facilitator_login_again = client.post(
            "/api/auth/token",
            json={"username": "admin", "password": "Admin@123!"},
        )
        assert facilitator_login_again.status_code == 200, facilitator_login_again.json()
        reveal_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/reveal",
            json={"activity_id": activity_id, "revealed": True},
        )
        assert reveal_resp.status_code == 200, reveal_resp.json()
        assert reveal_resp.json()["results_revealed"] is True

        participant_two_login_again = client.post(
            "/api/auth/token",
            json={"username": "parallel_two", "password": "ParallelTwo@123"},
        )
        assert participant_two_login_again.status_code == 200, participant_two_login_again.json()
        revealed_state = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/state",
            params={"activity_id": activity_id},
        )
        assert revealed_state.status_code == 200, revealed_state.json()
        assert isinstance(revealed_state.json()["assignments"], dict)

        facilitator_login_for_resolution = client.post(
            "/api/auth/token",
            json={"username": "admin", "password": "Admin@123!"},
        )
        assert (
            facilitator_login_for_resolution.status_code == 200
        ), facilitator_login_for_resolution.json()
        disputed_resp = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/disputed",
            params={"activity_id": activity_id},
        )
        assert disputed_resp.status_code == 200, disputed_resp.json()
        assert isinstance(disputed_resp.json()["disputed_items"], list)
        finalize_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/final-assignments",
            json={"activity_id": activity_id, "item_key": "pi-1", "category_id": "UNSORTED"},
        )
        assert finalize_resp.status_code == 200, finalize_resp.json()

        participant_two_login_post_finalize = client.post(
            "/api/auth/token",
            json={"username": "parallel_two", "password": "ParallelTwo@123"},
        )
        assert (
            participant_two_login_post_finalize.status_code == 200
        ), participant_two_login_post_finalize.json()
        post_finalize_state = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/state",
            params={"activity_id": activity_id},
        )
        assert post_finalize_state.status_code == 200, post_finalize_state.json()
        assert post_finalize_state.json()["final_assignments"]["pi-1"] == "UNSORTED"

        preserved_ballot = (
            db_session.query(CategorizationBallot)
            .filter(
                CategorizationBallot.meeting_id == meeting.meeting_id,
                CategorizationBallot.activity_id == activity_id,
                CategorizationBallot.user_id == participant_one.user_id,
                CategorizationBallot.item_key == "pi-1",
            )
            .first()
        )
        assert preserved_ballot is not None
        assert preserved_ballot.category_id == first_bucket

        participant_one_login_again = client.post(
            "/api/auth/token",
            json={"username": "parallel_one", "password": "ParallelOne@123"},
        )
        assert participant_one_login_again.status_code == 200, participant_one_login_again.json()
        unsubmit_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/ballot/unsubmit",
            json={"activity_id": activity_id},
        )
        assert unsubmit_resp.status_code == 200, unsubmit_resp.json()
        assert unsubmit_resp.json()["submitted"] is False
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_parallel_reveal_forbidden_for_participant(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_parallel_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    participant = user_manager_with_admin.add_user(
        first_name="Parallel",
        last_name="Viewer",
        email="parallel.viewer@decidero.local",
        hashed_password=get_password_hash("ParallelViewer@123"),
        role=UserRole.PARTICIPANT.value,
        login="parallel_viewer",
    )
    meeting.participants.append(participant)
    db_session.add(meeting)
    db_session.commit()

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "categorization",
                "status": "in_progress",
            },
        )
    )

    try:
        participant_login = client.post(
            "/api/auth/token",
            json={"username": "parallel_viewer", "password": "ParallelViewer@123"},
        )
        assert participant_login.status_code == 200, participant_login.json()
        reveal_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/reveal",
            json={"activity_id": activity_id, "revealed": True},
        )
        assert reveal_resp.status_code == 403, reveal_resp.json()
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_categorization_lock_keeps_facilitator_mutations_available(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id
    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "categorization",
                "status": "in_progress",
            },
        )
    )

    try:
        lock_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/lock",
            json={"activity_id": activity_id, "locked": True},
        )
        assert lock_resp.status_code == 200, lock_resp.json()
        assert lock_resp.json()["locked"] is True

        create_resp = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/buckets",
            json={"activity_id": activity_id, "title": "Blocked"},
        )
        assert create_resp.status_code == 200, create_resp.json()
        assert create_resp.json()["title"] == "Blocked"
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_parallel_lock_blocks_participant_ballot_mutation_but_allows_facilitator_controls(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None
    meeting = _create_parallel_categorization_meeting(db_session, owner_id=facilitator.user_id)
    activity_id = meeting.agenda_activities[0].activity_id

    participant = user_manager_with_admin.add_user(
        first_name="Locked",
        last_name="Participant",
        email="parallel.locked@decidero.local",
        hashed_password=get_password_hash("ParallelLocked@123"),
        role=UserRole.PARTICIPANT.value,
        login="parallel_locked",
    )
    meeting.participants.append(participant)
    db_session.add(meeting)
    db_session.commit()

    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=meeting.agenda_activities[0],
        actor_user_id=facilitator.user_id,
    )
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "categorization",
                "status": "in_progress",
                "activeActivities": [
                    {
                        "activityId": activity_id,
                        "tool": "categorization",
                        "status": "in_progress",
                        "metadata": {"participantScope": "all"},
                    }
                ],
            },
        )
    )

    try:
        facilitator_login = client.post(
            "/api/auth/token",
            json={"username": "admin", "password": "Admin@123!"},
        )
        assert facilitator_login.status_code == 200, facilitator_login.json()
        lock_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/lock",
            json={"activity_id": activity_id, "locked": True},
        )
        assert lock_resp.status_code == 200, lock_resp.json()

        reveal_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/reveal",
            json={"activity_id": activity_id, "revealed": True},
        )
        assert reveal_resp.status_code == 200, reveal_resp.json()
        assert reveal_resp.json()["results_revealed"] is True

        participant_login = client.post(
            "/api/auth/token",
            json={"username": "parallel_locked", "password": "ParallelLocked@123"},
        )
        assert participant_login.status_code == 200, participant_login.json()

        ballot_state = client.get(
            f"/api/meetings/{meeting.meeting_id}/categorization/ballot",
            params={"activity_id": activity_id},
        )
        assert ballot_state.status_code == 200, ballot_state.json()
        first_bucket = next(
            bucket["category_id"]
            for bucket in ballot_state.json()["buckets"]
            if bucket["category_id"] != "UNSORTED"
        )
        assign_resp = client.post(
            f"/api/meetings/{meeting.meeting_id}/categorization/ballot/assignments",
            json={"activity_id": activity_id, "item_key": "pi-1", "category_id": first_bucket},
        )
        assert assign_resp.status_code == 409, assign_resp.json()
        assert assign_resp.json()["detail"] == "This activity is locked."
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))
