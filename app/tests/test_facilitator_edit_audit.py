from datetime import UTC, datetime, timedelta
from fastapi.testclient import TestClient

from app.data.meeting_manager import MeetingManager
from app.models.facilitator_edit import FacilitatorEditEvent
from app.schemas.meeting import AgendaActivityCreate, MeetingCreate, PublicityType
from app.services.facilitator_edit_log import diff_packages, record_edit


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
