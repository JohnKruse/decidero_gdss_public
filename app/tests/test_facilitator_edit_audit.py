from datetime import UTC, datetime, timedelta
from fastapi.testclient import TestClient

from app.data.meeting_manager import MeetingManager
from app.models.facilitator_edit import FacilitatorEditEvent
from app.models.idea import Idea
from app.models.user import UserRole
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services.facilitator_edit_log import diff_packages, record_edit
from app.utils.security import get_password_hash


def test_diff_packages_rename_and_removal():
    before = [
        {"content": "Item A", "metadata": {"stable_key": "key-a"}},
        {"content": "Item B", "metadata": {"stable_key": "key-b"}},
    ]
    after = [
        {"content": "Item A Renamed", "metadata": {"stable_key": "key-a"}},
    ]
    diff = diff_packages(before, after)
    assert len(diff["changed"]) == 1
    assert diff["changed"][0]["before"]["content"] == "Item A"
    assert diff["changed"][0]["after"]["content"] == "Item A Renamed"
    assert len(diff["removed"]) == 1
    assert diff["removed"][0]["content"] == "Item B"
    assert len(diff["added"]) == 0


def test_diff_packages_noop():
    items = [
        {"content": "Item A", "metadata": {"stable_key": "key-a"}},
        {"content": "Item B", "metadata": {"stable_key": "key-b"}},
    ]
    diff = diff_packages(items, items)
    assert len(diff["changed"]) == 0
    assert len(diff["removed"]) == 0
    assert len(diff["added"]) == 0


def test_record_edit_noop_returns_none(db_session):
    diff = {"added": [], "removed": [], "changed": []}
    result = record_edit(
        db_session,
        meeting_id="mtg-test",
        activity_id="act-test",
        event_type="package_edited",
        diff=diff,
    )
    assert result is None
    events = db_session.query(FacilitatorEditEvent).all()
    assert len(events) == 0


def test_facilitator_edit_audit_rename_produces_single_event(
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
            title="Facilitator Audit Rename Test",
            description="Renaming one item produces one event with actor set and changed text.",
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
            ),
            AgendaActivityCreate(
                tool_type="rank_order_voting",
                title="Target",
                config={
                    "ideas": [
                        {
                            "id": "item-1",
                            "content": "Original Content Text",
                            "metadata": {"stable_key": "key-1"},
                        }
                    ]
                },
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    commit_payload = {
        "donor_activity_id": donor_id,
        "include_comments": False,
        "items": [
            {
                "id": "item-1",
                "content": "Renamed Content Text",
                "metadata": {"stable_key": "key-1"},
            }
        ],
        "metadata": {},
        "target_activity": {"activity_id": target_id},
    }
    commit_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json=commit_payload,
    )
    assert commit_resp.status_code == 200, commit_resp.json()

    events = (
        db_session.query(FacilitatorEditEvent)
        .filter(
            FacilitatorEditEvent.meeting_id == meeting.meeting_id,
            FacilitatorEditEvent.activity_id == target_id,
        )
        .all()
    )
    assert len(events) == 1
    event = events[0]
    assert event.actor_user_id == facilitator.user_id
    assert event.event_type == "package_edited"
    assert event.donor_activity_id == donor_id
    assert len(event.payload["changed"]) == 1
    changed_entry = event.payload["changed"][0]
    assert changed_entry["before"]["content"] == "Original Content Text"
    assert changed_entry["after"]["content"] == "Renamed Content Text"
    assert len(event.payload["added"]) == 0
    assert len(event.payload["removed"]) == 0


def test_facilitator_edit_audit_removal_retains_removed_content_in_payload(
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
            title="Facilitator Audit Removal Test",
            description="Removing an item retains the removed content in the audit payload.",
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
            ),
            AgendaActivityCreate(
                tool_type="rank_order_voting",
                title="Target",
                config={
                    "ideas": [
                        {
                            "id": "item-1",
                            "content": "Keep Me",
                            "metadata": {"stable_key": "key-1"},
                        },
                        {
                            "id": "item-2",
                            "content": "Delete Me Later",
                            "metadata": {"stable_key": "key-2"},
                        },
                    ]
                },
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    commit_payload = {
        "donor_activity_id": donor_id,
        "include_comments": False,
        "items": [
            {
                "id": "item-1",
                "content": "Keep Me",
                "metadata": {"stable_key": "key-1"},
            }
        ],
        "metadata": {},
        "target_activity": {"activity_id": target_id},
    }
    commit_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json=commit_payload,
    )
    assert commit_resp.status_code == 200, commit_resp.json()

    events = (
        db_session.query(FacilitatorEditEvent)
        .filter(
            FacilitatorEditEvent.meeting_id == meeting.meeting_id,
            FacilitatorEditEvent.activity_id == target_id,
        )
        .all()
    )
    assert len(events) == 1
    event = events[0]
    assert event.actor_user_id == facilitator.user_id
    assert event.event_type == "package_edited"
    assert len(event.payload["removed"]) == 1
    removed_entry = event.payload["removed"][0]
    assert removed_entry["content"] == "Delete Me Later"
    assert removed_entry["stable_key"] == "key-2"


def test_facilitator_edit_audit_noop_commit_writes_no_event(
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
            title="Facilitator Audit Noop Test",
            description="No-op commit writes no event.",
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
            ),
            AgendaActivityCreate(
                tool_type="rank_order_voting",
                title="Target",
                config={
                    "ideas": [
                        {
                            "id": "item-1",
                            "content": "Unchanged Item",
                            "metadata": {"stable_key": "key-1"},
                        }
                    ]
                },
            ),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    commit_payload = {
        "donor_activity_id": donor_id,
        "include_comments": False,
        "items": [
            {
                "id": "item-1",
                "content": "Unchanged Item",
                "metadata": {"stable_key": "key-1"},
            }
        ],
        "metadata": {},
        "target_activity": {"activity_id": target_id},
    }
    commit_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json=commit_payload,
    )
    assert commit_resp.status_code == 200, commit_resp.json()

    events = (
        db_session.query(FacilitatorEditEvent)
        .filter(
            FacilitatorEditEvent.meeting_id == meeting.meeting_id,
            FacilitatorEditEvent.activity_id == target_id,
        )
        .all()
    )
    assert len(events) == 0


def test_participant_reply_on_unchanged_idea_survives(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    participant = user_manager_with_admin.add_user(
        first_name="Participant",
        last_name="One",
        email="part1@example.com",
        hashed_password=get_password_hash("Password123!"),
        role=UserRole.PARTICIPANT.value,
        login="part1",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Unchanged Idea Comment Survival Test",
            description="Participant reply on unchanged idea survives with original id and user_id.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[participant.user_id],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(tool_type="brainstorming", title="Target Brainstorming"),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    top_idea = Idea(
        meeting_id=meeting.meeting_id,
        activity_id=target_id,
        content="Stable Parent Idea",
        user_id=facilitator.user_id,
        idea_metadata={"stable_key": "stable-parent-key"},
    )
    db_session.add(top_idea)
    db_session.commit()
    db_session.refresh(top_idea)

    reply = Idea(
        meeting_id=meeting.meeting_id,
        activity_id=target_id,
        content="Participant Reply On Stable Idea",
        parent_id=top_idea.id,
        user_id=participant.user_id,
        idea_metadata={"stable_key": "participant-reply-key"},
    )
    db_session.add(reply)
    db_session.commit()
    db_session.refresh(reply)

    original_reply_id = reply.id
    original_reply_user_id = reply.user_id
    original_reply_timestamp = reply.timestamp

    commit_payload = {
        "donor_activity_id": donor_id,
        "include_comments": False,
        "items": [
            {
                "id": top_idea.id,
                "content": "Stable Parent Idea",
                "metadata": {"stable_key": "stable-parent-key"},
            }
        ],
        "metadata": {},
        "target_activity": {"activity_id": target_id},
    }
    commit_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json=commit_payload,
    )
    assert commit_resp.status_code == 200, commit_resp.json()

    db_session.expire_all()
    comments = (
        db_session.query(Idea)
        .filter(
            Idea.meeting_id == meeting.meeting_id,
            Idea.activity_id == target_id,
            Idea.parent_id.isnot(None),
        )
        .all()
    )
    assert len(comments) == 1
    assert comments[0].id == original_reply_id
    assert comments[0].user_id == original_reply_user_id
    assert comments[0].parent_id == top_idea.id
    assert comments[0].timestamp == original_reply_timestamp
    assert comments[0].content == "Participant Reply On Stable Idea"


def test_participant_reply_on_renamed_idea_survives_and_stays_attached(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    participant = user_manager_with_admin.add_user(
        first_name="Participant",
        last_name="Two",
        email="part2@example.com",
        hashed_password=get_password_hash("Password123!"),
        role=UserRole.PARTICIPANT.value,
        login="part2",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Renamed Idea Comment Survival Test",
            description="Participant reply on renamed idea survives and stays attached to same row.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[participant.user_id],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(tool_type="brainstorming", title="Target Brainstorming"),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    top_idea = Idea(
        meeting_id=meeting.meeting_id,
        activity_id=target_id,
        content="Idea Before Rename",
        user_id=facilitator.user_id,
        idea_metadata={"stable_key": "rename-parent-key"},
    )
    db_session.add(top_idea)
    db_session.commit()
    db_session.refresh(top_idea)

    reply = Idea(
        meeting_id=meeting.meeting_id,
        activity_id=target_id,
        content="Participant Reply On Renamed Idea",
        parent_id=top_idea.id,
        user_id=participant.user_id,
        idea_metadata={"stable_key": "reply-key-2"},
    )
    db_session.add(reply)
    db_session.commit()
    db_session.refresh(reply)

    original_top_id = top_idea.id
    original_reply_id = reply.id
    original_reply_user_id = reply.user_id
    original_reply_timestamp = reply.timestamp

    commit_payload = {
        "donor_activity_id": donor_id,
        "include_comments": False,
        "items": [
            {
                "id": top_idea.id,
                "content": "Idea After Rename",
                "metadata": {"stable_key": "rename-parent-key"},
            }
        ],
        "metadata": {},
        "target_activity": {"activity_id": target_id},
    }
    commit_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json=commit_payload,
    )
    assert commit_resp.status_code == 200, commit_resp.json()

    db_session.expire_all()
    updated_top = db_session.query(Idea).filter(Idea.id == original_top_id).first()
    assert updated_top is not None
    assert updated_top.content == "Idea After Rename"

    comments = (
        db_session.query(Idea)
        .filter(
            Idea.meeting_id == meeting.meeting_id,
            Idea.activity_id == target_id,
            Idea.parent_id.isnot(None),
        )
        .all()
    )
    assert len(comments) == 1
    assert comments[0].id == original_reply_id
    assert comments[0].parent_id == original_top_id
    assert comments[0].user_id == original_reply_user_id
    assert comments[0].timestamp == original_reply_timestamp
    assert comments[0].content == "Participant Reply On Renamed Idea"


def test_removing_idea_with_reply_deletes_reply_and_records_audit_payload(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    participant = user_manager_with_admin.add_user(
        first_name="Participant",
        last_name="Three",
        email="part3@example.com",
        hashed_password=get_password_hash("Password123!"),
        role=UserRole.PARTICIPANT.value,
        login="part3",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Removed Idea Comment Audit Test",
            description="Removing an idea with a reply deletes reply and records removed_comments.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[participant.user_id],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(tool_type="brainstorming", title="Target Brainstorming"),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    idea_surviving = Idea(
        meeting_id=meeting.meeting_id,
        activity_id=target_id,
        content="Surviving Idea",
        user_id=facilitator.user_id,
        idea_metadata={"stable_key": "surviving-idea-key"},
    )
    idea_to_remove = Idea(
        meeting_id=meeting.meeting_id,
        activity_id=target_id,
        content="Idea To Remove",
        user_id=facilitator.user_id,
        idea_metadata={"stable_key": "remove-idea-key"},
    )
    db_session.add_all([idea_surviving, idea_to_remove])
    db_session.commit()
    db_session.refresh(idea_surviving)
    db_session.refresh(idea_to_remove)

    reply_to_remove = Idea(
        meeting_id=meeting.meeting_id,
        activity_id=target_id,
        content="Participant Reply On Doomed Idea",
        parent_id=idea_to_remove.id,
        user_id=participant.user_id,
        idea_metadata={"stable_key": "reply-doomed-key"},
    )
    db_session.add(reply_to_remove)
    db_session.commit()
    db_session.refresh(reply_to_remove)

    doomed_idea_id = idea_to_remove.id
    doomed_reply_id = reply_to_remove.id
    participant_user_id = participant.user_id

    commit_payload = {
        "donor_activity_id": donor_id,
        "include_comments": False,
        "items": [
            {
                "id": idea_surviving.id,
                "content": "Surviving Idea",
                "metadata": {"stable_key": "surviving-idea-key"},
            }
        ],
        "metadata": {},
        "target_activity": {"activity_id": target_id},
    }
    commit_resp = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json=commit_payload,
    )
    assert commit_resp.status_code == 200, commit_resp.json()

    db_session.expire_all()
    assert db_session.query(Idea).filter(Idea.id == doomed_idea_id).first() is None
    assert db_session.query(Idea).filter(Idea.id == doomed_reply_id).first() is None

    events = (
        db_session.query(FacilitatorEditEvent)
        .filter(
            FacilitatorEditEvent.meeting_id == meeting.meeting_id,
            FacilitatorEditEvent.activity_id == target_id,
        )
        .all()
    )
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "package_edited"
    assert len(event.payload["removed"]) == 1
    assert event.payload["removed"][0]["stable_key"] == "remove-idea-key"
    assert "removed_comments" in event.payload
    assert len(event.payload["removed_comments"]) == 1
    rc = event.payload["removed_comments"][0]
    assert rc["stable_key"] == "reply-doomed-key"
    assert rc["content"] == "Participant Reply On Doomed Idea"
    assert rc["user_id"] == participant_user_id
    assert rc["parent_stable_key"] == "remove-idea-key"


def test_committing_same_package_twice_does_not_duplicate_comments_and_no_second_event(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    assert facilitator is not None

    participant = user_manager_with_admin.add_user(
        first_name="Participant",
        last_name="Four",
        email="part4@example.com",
        hashed_password=get_password_hash("Password123!"),
        role=UserRole.PARTICIPANT.value,
        login="part4",
    )
    db_session.commit()
    db_session.refresh(participant)

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Idempotent Package Commit Test",
            description="Committing same package twice does not duplicate comments and produces no second audit event.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[participant.user_id],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Donor"),
            AgendaActivityCreate(tool_type="brainstorming", title="Target Brainstorming"),
        ],
    )
    donor_id = meeting.agenda_activities[0].activity_id
    target_id = meeting.agenda_activities[1].activity_id

    commit_payload = {
        "donor_activity_id": donor_id,
        "include_comments": True,
        "items": [
            {
                "id": "donor-item-10",
                "content": "Top-level Idea Ten",
                "metadata": {"stable_key": "top-key-10"},
            },
            {
                "id": "donor-comment-10",
                "parent_id": "donor-item-10",
                "content": "Discussion Reply Ten",
                "user_id": participant.user_id,
                "metadata": {"stable_key": "reply-key-10"},
            },
        ],
        "metadata": {},
        "target_activity": {"activity_id": target_id},
    }
    resp1 = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json=commit_payload,
    )
    assert resp1.status_code == 200, resp1.json()

    db_session.expire_all()
    comments_pass1 = (
        db_session.query(Idea)
        .filter(
            Idea.meeting_id == meeting.meeting_id,
            Idea.activity_id == target_id,
            Idea.parent_id.isnot(None),
        )
        .all()
    )
    assert len(comments_pass1) == 1
    c1_id = comments_pass1[0].id
    events_count_pass1 = (
        db_session.query(FacilitatorEditEvent)
        .filter(
            FacilitatorEditEvent.meeting_id == meeting.meeting_id,
            FacilitatorEditEvent.activity_id == target_id,
        )
        .count()
    )

    resp2 = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/transfer/commit",
        json=commit_payload,
    )
    assert resp2.status_code == 200, resp2.json()

    db_session.expire_all()
    comments_pass2 = (
        db_session.query(Idea)
        .filter(
            Idea.meeting_id == meeting.meeting_id,
            Idea.activity_id == target_id,
            Idea.parent_id.isnot(None),
        )
        .all()
    )
    assert len(comments_pass2) == 1
    assert comments_pass2[0].id == c1_id

    events_count_pass2 = (
        db_session.query(FacilitatorEditEvent)
        .filter(
            FacilitatorEditEvent.meeting_id == meeting.meeting_id,
            FacilitatorEditEvent.activity_id == target_id,
        )
        .count()
    )
    assert events_count_pass2 == events_count_pass1


def test_record_edit_removed_comments_only_writes_event(
    user_manager_with_admin,
    db_session,
):
    facilitator = user_manager_with_admin.get_user_by_email("admin@decidero.local")
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Record Edit Removed Comments Test",
            description="Test record_edit with only removed_comments.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=facilitator.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=facilitator.user_id,
        agenda_items=[],
    )
    diff = {
        "added": [],
        "removed": [],
        "changed": [],
        "removed_comments": [
            {
                "stable_key": "c1",
                "content": "Comment 1",
                "user_id": "u1",
                "parent_stable_key": "p1",
            }
        ],
    }
    result = record_edit(
        db_session,
        meeting_id=meeting.meeting_id,
        activity_id="act-test-comments",
        event_type="package_edited",
        diff=diff,
    )
    assert result is not None
    events = (
        db_session.query(FacilitatorEditEvent)
        .filter(FacilitatorEditEvent.meeting_id == meeting.meeting_id)
        .all()
    )
    assert len(events) == 1
    assert len(events[0].payload["removed_comments"]) == 1
    assert events[0].payload["removed_comments"][0]["content"] == "Comment 1"

