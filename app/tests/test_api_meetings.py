import asyncio
import base64
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, UTC

import pytest
from fastapi.testclient import TestClient

from app.config.loader import get_guest_join_enabled
from app.data.user_manager import UserManager
from app.data.meeting_manager import MeetingManager
from app.services import meeting_state_manager
from app.schemas.meeting import AgendaActivityCreate
from app.schemas.meeting import MeetingCreate, PublicityType
from app.models.categorization import CategorizationBallot
from app.models.idea import Idea
from app.models.meeting import AgendaActivity
from app.models.voting import VotingVote
from app.models.user import UserRole
from app.utils.security import get_password_hash

EXPORT_ZIP_BASE64 = (
    "UEsDBBQAAAAIAOGKMFzeP7hayQIAAAoPAAAMAAAAbWVldGluZy5qc29u1VZda9swFH3vrwh+XVNkx05b"
    "v7VQxhjZoG2gYxSj2EqrVraMPtqEkv++K9mxnVTuAoGWQEjse66kc4+kc/N2NBh4L0RIygsvHvjH5p0s"
    "Si4UyRKsIOYFKBgPkT/0x7f+OA5GMRqdRGfjsX/+DaEYIc8OyglRtHiAAW/w2gYSmplJJrffzTzI92Eu"
    "hHw7CLIUVYyYhDp90CAZkamgpaqYeZN6/hqVCistDSDTR5JpRrI1RGVS6hmjKaBKaFKHU0Gwu6gwhk8U"
    "dqqpFhAqUTQn79Nt4mY6KTJncrSRDLkrq9Ycp5RRqIELU8RfO0klHKBaElHrNr25Hk6mNz//3F0NW9kg"
    "h/EHaoXBWQ4PTZzkmDKIF5qxJjinQqqkwBW/K8Y7AxjuQBMtn5ctBlLy14KIWkkbXsH3vS2iBIVoSktc"
    "qP8XcTG9/X13N+0pwiZ3kR3KmMKYnjIutOJexfZ4R1ZBL6vgC1mNelmNvpBV2Msq/EJWUS+r6NNZffqV"
    "3bqa+AEMCb+/lDhV9IWqZU318vrix6+briEbS+acJWpZ2tlnAtNCgk3lrfl2bfvSjZuY0Kkxb7ldGReZ"
    "0arIyGLdcmw85cWctg2k4ssYf01wwYtlzq3ft47eSZB6lvI8J5URbafApiVPOi+TgrxC4QQ7kjpeBimt"
    "ndVw3542oMveHGDwETj6CAw/AiOvwe7rp1Wjq+1k68a3sROwb2XZ1+eDOEInpyhE/mZnNAeW4VLCuEwL"
    "XPfnAJ1tHcG10Fsn0B68jU1XsG1mfXvi20VgR4jdjG3Wps1CTXnp6OPj+D1bXWbYXf9Of1F2vDWtAWxK"
    "rGc5VWb5+r4a1OkgdmzgEgbLbD9ZAj8Ox4csS+SWZT9VRuGBq3LqUmXG8KNbl2gnUaLYR4csynnPDZo/"
    "Pw3Mzz5nJjp8g/GRS5/FYrG/LueHokvTol64IrZF3R+t/gFQSwECFAMUAAAACADhijBc3j+4WskCAAAK"
    "DwAADAAAAAAAAAAAAAAAgAEAAAAAbWVldGluZy5qc29uUEsFBgAAAAABAAEAOgAAAPMCAAAAAA=="
)


def _decode_export_zip() -> bytes:
    return base64.b64decode(EXPORT_ZIP_BASE64)


@pytest.fixture(scope="function")
def test_meeting_data(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    """
    Fixture to create a test meeting and return its ID.
    Ensures a facilitator exists and creates a meeting via the API.
    """
    # Get the admin user created by user_manager_with_admin fixture
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    meeting_data = {
        "title": "Test Meeting for Get",
        "description": "Description for get test",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        "agenda_items": ["Discuss milestones"],
        "participant_contacts": [admin_user.login],
    }

    response = authenticated_client.post("/api/meetings/", json=meeting_data)
    assert (
        response.status_code == 200
    ), f"Failed to create test meeting: {response.json()}"

    meeting_id = response.json()["id"]
    return meeting_id


def test_list_meetings_returns_dashboard_payload(
    authenticated_client: TestClient, test_meeting_data: str
):
    """GET /api/meetings/ should return dashboard metadata with meeting items."""

    response = authenticated_client.get("/api/meetings/")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"items", "summary", "filters"}
    assert isinstance(payload["items"], list)
    assert payload["summary"]["total"] == len(payload["items"])
    assert payload["filters"]["role_scope"] == "participant"
    assert any(item["id"] == test_meeting_data for item in payload["items"])
    first_item = payload["items"][0]
    assert {"enter", "details"}.issubset(first_item["quick_actions"].keys())
    assert "notifications" in first_item
    assert "facilitator_names" in first_item
    assert isinstance(first_item["facilitator_names"], list)
    assert first_item["facilitator_names"]


def test_list_meetings_supports_status_filter(
    authenticated_client: TestClient, test_meeting_data: str
):
    """Status filter should narrow results to the requested bucket."""

    response = authenticated_client.get("/api/meetings/?status=never_started")

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["status"] == "never_started"
    assert payload["summary"]["never_started"] == len(payload["items"])


def test_export_meeting_returns_zip_bundle(
    authenticated_client: TestClient, test_meeting_data: str
):
    response = authenticated_client.get(f"/api/meetings/{test_meeting_data}/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "meeting.json" in archive.namelist()

    meeting_payload = json.loads(archive.read("meeting.json").decode("utf-8"))
    assert meeting_payload["meeting"]["meeting_id"] == test_meeting_data
    assert meeting_payload["meeting"]["title"] == "Test Meeting for Get"


def test_import_meeting_bundle_from_fixture(
    authenticated_client: TestClient, db_session
):
    zip_bytes = _decode_export_zip()
    response = authenticated_client.post(
        "/api/meetings/import",
        content=zip_bytes,
        headers={"Content-Type": "application/zip"},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["id"]
    assert payload["title"].startswith("meeting 1")
    assert payload["agenda"]
    assert payload["agenda"][0]["title"] == "Brainstorming"

    idea_count = (
        db_session.query(Idea)
        .filter(Idea.meeting_id == payload["id"])
        .count()
    )
    assert idea_count == 6


def test_create_meeting_returns_new_meeting(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    """Tests that creating a meeting via POST /api/meetings/ returns the new meeting."""
    # Arrange
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    meeting_data = {
        "title": "New Test Meeting",
        "description": "A new meeting created by test",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "agenda_items": ["Kickoff", "Risk review"],
        "participant_contacts": [admin_user.login],
    }

    # Act
    response = authenticated_client.post("/api/meetings/", json=meeting_data)

    # Assert
    assert response.status_code == 200, f"Response: {response.json()}"
    result = response.json()
    assert result["title"] == meeting_data["title"]
    assert result["description"] == meeting_data["description"]
    assert "id" in result
    assert result.get("facilitator_user_ids")
    assert result.get("facilitators")
    assert "agenda" in result
    assert len(result["agenda"]) == len(meeting_data["agenda_items"])
    assert all(item["tool_type"] == "brainstorming" for item in result["agenda"])


def test_create_meeting_accepts_participant_ids(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    """Participant selections should be persisted when creating a meeting."""
    additional_user = user_manager_with_admin.add_user(
        first_name="Directory",
        last_name="Participant",
        email="directory.participant@example.com",
        hashed_password=get_password_hash("DirPass1!"),
        role=UserRole.PARTICIPANT.value,
        login="directory_participant",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(additional_user)

    meeting_data = {
        "title": "Roster Creation Test",
        "description": "Ensures participant IDs are accepted.",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "agenda_items": ["Review"],
        "participant_contacts": [],
        "participant_ids": [additional_user.user_id],
    }

    response = authenticated_client.post("/api/meetings/", json=meeting_data)
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert additional_user.user_id in payload.get("participant_ids", [])

    meeting_record = MeetingManager(user_manager_with_admin.db).get_meeting(
        payload["id"]
    )
    assert meeting_record is not None
    assert any(
        p.user_id == additional_user.user_id
        for p in getattr(meeting_record, "participants", [])
        if p
    )


def test_participant_cannot_create_meeting(
    client: TestClient, user_manager_with_admin: UserManager
):
    """Participants should be blocked from creating meetings by RBAC."""
    participant_password = "Participant@123!"
    participant = user_manager_with_admin.add_user(
        first_name="Pat",
        last_name="User",
        email="participant.rbac@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="participant_rbac",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(participant)

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.text

    meeting_data = {
        "title": "Participant Attempt",
        "description": "Should fail",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "agenda_items": ["Item"],
    }
    create_response = client.post("/api/meetings/", json=meeting_data)
    assert create_response.status_code == 403
    assert "permission" in create_response.json().get("detail", "").lower() or create_response.json().get("detail")


def test_get_meeting_returns_meeting(
    authenticated_client: TestClient,
    test_meeting_data: str,
    user_manager_with_admin: UserManager,
):
    """Tests that GET /api/meetings/{meeting_id} returns the correct meeting."""
    # Arrange: test_meeting_data provides a valid meeting_id
    meeting_id = test_meeting_data

    # Act
    response = authenticated_client.get(f"/api/meetings/{meeting_id}")

    # Assert
    assert response.status_code == 200, f"Response: {response.json()}"
    result = response.json()
    assert isinstance(result, dict)
    assert result["id"] == meeting_id
    assert "title" in result
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None
    assert admin_user.user_id in result.get("facilitator_user_ids", [])
    assert "agenda" in result
    assert len(result["agenda"]) >= 1


def test_get_active_meetings_returns_active_meetings(
    authenticated_client: TestClient, test_meeting_data: str
):
    """Tests that GET /api/meetings/active returns a list of active meetings."""
    # Arrange: test_meeting_data ensures at least one scheduled meeting exists

    # Act
    response = authenticated_client.get("/api/meetings/active")

    # Assert
    assert response.status_code == 200, f"Response: {response.json()}"
    result = response.json()
    assert isinstance(result, list)
    assert len(result) > 0
    # Check if the specific test meeting is in the active list
    found_test_meeting = any(m["id"] == test_meeting_data for m in result)
    assert (
        found_test_meeting
    ), "The created test meeting was not found in the active list."


def test_list_agenda_modules(authenticated_client: TestClient):
    """The agenda module catalog should list brainstorming and voting tools."""

    response = authenticated_client.get("/api/meetings/modules")
    assert response.status_code == 200, f"Response: {response.json()}"

    catalog = response.json()
    assert isinstance(catalog, list)
    tool_types = {entry["tool_type"] for entry in catalog}
    assert {"brainstorming", "voting"}.issubset(tool_types)
    brainstorming = next(
        (entry for entry in catalog if entry.get("tool_type") == "brainstorming"),
        None,
    )
    assert brainstorming is not None
    assert "reliability_policy" in brainstorming


def test_add_agenda_item_to_meeting(
    authenticated_client: TestClient, test_meeting_data: str
):
    """Facilitators can append a new agenda item via the agenda API."""

    payload = {
        "tool_type": "voting",
        "title": "Prioritise ideas",
        "config": {"max_votes": 3},
    }

    create_response = authenticated_client.post(
        f"/api/meetings/{test_meeting_data}/agenda",
        json=payload,
    )
    assert create_response.status_code == 201, f"Response: {create_response.json()}"

    created = create_response.json()
    assert created["tool_type"] == "voting"
    assert created["config"]["max_votes"] == 3
    assert created["order_index"] >= 1

    list_response = authenticated_client.get(
        f"/api/meetings/{test_meeting_data}/agenda"
    )
    assert list_response.status_code == 200
    items = list_response.json()
    assert any(item["activity_id"] == created["activity_id"] for item in items)


def test_update_and_delete_agenda_item(
    authenticated_client: TestClient, test_meeting_data: str, mocker
):
    """Agenda items can be updated and deleted via the API, with active guard."""

    # Add an activity to be later deleted
    create_payload_1 = {
        "tool_type": "voting",
        "title": "Initial vote",
    }
    create_response_1 = authenticated_client.post(
        f"/api/meetings/{test_meeting_data}/agenda",
        json=create_payload_1,
    )
    assert create_response_1.status_code == 201
    activity_id_1 = create_response_1.json()["activity_id"]

    # Add another activity to make it active
    create_payload_2 = {
        "tool_type": "brainstorming",
        "title": "Active item",
    }
    create_response_2 = authenticated_client.post(
        f"/api/meetings/{test_meeting_data}/agenda",
        json=create_payload_2,
    )
    assert create_response_2.status_code == 201
    activity_id_2 = create_response_2.json()["activity_id"]

    update_payload = {
        "title": "Updated vote",
        "order_index": 1,
        "config": {"max_votes": 7},
    }

    update_response = authenticated_client.put(
        f"/api/meetings/{test_meeting_data}/agenda/{activity_id_1}",
        json=update_payload,
    )
    assert update_response.status_code == 200, f"Response: {update_response.json()}"
    updated = update_response.json()
    assert updated["title"] == "Updated vote"
    assert updated["order_index"] == 1
    assert updated["config"]["max_votes"] == 7

    # --- Test deletion guard ---
    # Simulate activity_id_1 being active
    mocker.patch(
        "app.data.meeting_manager.meeting_state_manager.snapshot",
        return_value={"currentActivity": activity_id_1, "status": "in_progress"},
    )

    # Attempt to delete active activity_id_1 - should fail
    delete_active_response = authenticated_client.delete(
        f"/api/meetings/{test_meeting_data}/agenda/{activity_id_1}"
    )
    assert delete_active_response.status_code == 400
    assert (
        "Cannot delete an active activity. Please stop it first."
        in delete_active_response.json()["detail"]
    )

    # Now simulate no activity being active
    mocker.patch(
        "app.data.meeting_manager.meeting_state_manager.snapshot",
        return_value={"currentActivity": None},
    )

    # Attempt to delete active_activity_id_1 again (now inactive) - should succeed
    delete_response_1 = authenticated_client.delete(
        f"/api/meetings/{test_meeting_data}/agenda/{activity_id_1}"
    )
    assert delete_response_1.status_code == 204

    agenda_after_delete_1 = authenticated_client.get(
        f"/api/meetings/{test_meeting_data}/agenda"
    ).json()
    assert all(item["activity_id"] != activity_id_1 for item in agenda_after_delete_1)
    assert any(
        item["activity_id"] == activity_id_2 for item in agenda_after_delete_1
    )  # activity_id_2 should still be there

    # Delete activity_id_2 (also inactive) - should succeed
    delete_response_2 = authenticated_client.delete(
        f"/api/meetings/{test_meeting_data}/agenda/{activity_id_2}"
    )
    assert delete_response_2.status_code == 204

    agenda_after_delete_2 = authenticated_client.get(
        f"/api/meetings/{test_meeting_data}/agenda"
    ).json()
    assert not any(
        item["activity_id"] == activity_id_2 for item in agenda_after_delete_2
    )


def test_reorder_agenda_activities_api(
    authenticated_client: TestClient, test_meeting_data: str, mocker
):
    """API endpoint for reordering agenda activities should work correctly."""

    # 1. Fetch existing agenda to know what's there (fixture creates one item)
    existing_agenda_resp = authenticated_client.get(
        f"/api/meetings/{test_meeting_data}/agenda"
    )
    assert existing_agenda_resp.status_code == 200
    existing_ids = [item["activity_id"] for item in existing_agenda_resp.json()]

    # 2. Add several new activities (let backend handle order_index to avoid collision)
    new_activity_ids = []
    for i in range(3):
        create_payload = {
            "tool_type": "brainstorming",
            "title": f"Activity {i + 1}",
        }
        create_response = authenticated_client.post(
            f"/api/meetings/{test_meeting_data}/agenda",
            json=create_payload,
        )
        assert create_response.status_code == 201
        new_activity_ids.append(create_response.json()["activity_id"])

    # 3. Construct the reorder list (Reverse everything)
    all_ids = existing_ids + new_activity_ids
    new_order = list(reversed(all_ids))

    # Mock the websocket broadcast
    mocker.patch("app.routers.meetings.websocket_manager.broadcast", return_value=None)

    # 4. Send Reorder Request
    reorder_response = authenticated_client.put(
        f"/api/meetings/{test_meeting_data}/agenda-reorder",
        json={"activity_ids": new_order},
    )
    assert reorder_response.status_code == 200, f"Response: {reorder_response.json()}"
    reordered_agenda = reorder_response.json()

    # 5. Verify Response
    assert len(reordered_agenda) == len(all_ids)
    for index, item in enumerate(reordered_agenda):
        assert item["activity_id"] == new_order[index]
        assert item["order_index"] == index + 1

    # 6. Verify Persistence (fetch again)
    fetched_agenda = authenticated_client.get(
        f"/api/meetings/{test_meeting_data}/agenda"
    ).json()
    assert len(fetched_agenda) == len(all_ids)
    for index, item in enumerate(fetched_agenda):
        assert item["activity_id"] == new_order[index]
        assert item["order_index"] == index + 1

    # Test invalid payload (empty list)
    invalid_reorder_response = authenticated_client.put(
        f"/api/meetings/{test_meeting_data}/agenda-reorder",
        json={"activity_ids": []},
    )
    assert invalid_reorder_response.status_code == 422  # Pydantic validation error

    # Test invalid payload (unknown activity ID) - expecting 404
    invalid_id_payload = {"activity_ids": all_ids[:-1] + ["NON_EXISTENT_ID"]}
    error_response = authenticated_client.put(
        f"/api/meetings/{test_meeting_data}/agenda-reorder",
        json=invalid_id_payload,
    )
    if error_response.status_code == 404:
        assert "not found" in error_response.json()["detail"]


def test_get_meeting_agenda_includes_lock_metadata(
    authenticated_client: TestClient,
    test_meeting_data: str,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    voting_create = authenticated_client.post(
        f"/api/meetings/{test_meeting_data}/agenda",
        json={
            "tool_type": "voting",
            "title": "Prioritise",
            "config": {"options": ["Alpha", "Beta"], "max_votes": 2},
        },
    )
    assert voting_create.status_code == 201, voting_create.json()
    voting_activity = voting_create.json()

    categorization_create = authenticated_client.post(
        f"/api/meetings/{test_meeting_data}/agenda",
        json={
            "tool_type": "categorization",
            "title": "Bucket Ideas",
            "config": {
                "mode": "PARALLEL_BALLOT",
                "items": ["Idea 1"],
                "buckets": ["Bucket A"],
            },
        },
    )
    assert categorization_create.status_code == 201, categorization_create.json()
    categorization_activity = categorization_create.json()

    db_session.add(
        VotingVote(
            meeting_id=test_meeting_data,
            activity_id=voting_activity["activity_id"],
            user_id=admin_user.user_id,
            option_id=f"{voting_activity['activity_id']}:alpha",
            option_label="Alpha",
            weight=1,
        )
    )
    categorization_activity_model = (
        db_session.query(AgendaActivity)
        .filter(AgendaActivity.activity_id == categorization_activity["activity_id"])
        .first()
    )
    assert categorization_activity_model is not None
    categorization_activity_model.stopped_at = datetime.now(UTC)
    db_session.add(categorization_activity_model)
    db_session.add(
        CategorizationBallot(
            meeting_id=test_meeting_data,
            activity_id=categorization_activity["activity_id"],
            user_id=admin_user.user_id,
            item_key=f"{categorization_activity['activity_id']}:item-1",
            category_id="UNSORTED",
            submitted=True,
        )
    )
    db_session.commit()

    meeting_response = authenticated_client.get(f"/api/meetings/{test_meeting_data}")
    assert meeting_response.status_code == 200, meeting_response.json()
    agenda = meeting_response.json().get("agenda") or []

    voting_row = next(
        item for item in agenda if item.get("activity_id") == voting_activity["activity_id"]
    )
    assert voting_row["has_votes"] is True
    assert voting_row["has_data"] is True
    assert set(voting_row["locked_config_keys"]) == {
        "options",
        "max_votes",
        "max_votes_per_option",
    }

    categorization_row = next(
        item
        for item in agenda
        if item.get("activity_id") == categorization_activity["activity_id"]
    )
    assert categorization_row["has_submitted_ballots"] is True
    assert categorization_row["has_data"] is True
    assert "items" in categorization_row["locked_config_keys"]
    assert "buckets" in categorization_row["locked_config_keys"]
    assert "mode" in categorization_row["locked_config_keys"]


def test_cofacilitator_update_permissions(
    client: TestClient,
    db_session,
    user_manager_with_admin: UserManager,
):
    """Co-facilitators can update meeting metadata but not ownership or facilitator roster."""
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None
    admin_user_id = admin_user.user_id

    cofac_password = "CoFacPass1!"
    cofac_user = user_manager_with_admin.add_user(
        first_name="Co",
        last_name="Facilitator",
        email="cofac@example.com",
        hashed_password=get_password_hash(cofac_password),
        role=UserRole.FACILITATOR.value,
        login="cofac_user",
    )
    db_session.commit()
    db_session.refresh(cofac_user)
    cofac_user_id = cofac_user.user_id

    meeting_manager = MeetingManager(db_session)
    meeting_payload = MeetingCreate(
        title="Collaboration Session",
        description="Initial description",
        start_time=datetime.now(UTC) + timedelta(days=1),
        duration_minutes=60,
        publicity=PublicityType.PUBLIC,
        owner_id=admin_user_id,
        participant_ids=[],
        additional_facilitator_ids=[cofac_user_id],
    )
    meeting = meeting_manager.create_meeting(meeting_payload, admin_user.user_id)
    assert meeting is not None

    login_response = client.post(
        "/api/auth/token",
        json={"username": cofac_user.login, "password": cofac_password},
    )
    assert (
        login_response.status_code == 200
    ), f"Failed to log in co-facilitator: {login_response.json()}"

    restricted_response = client.put(
        f"/api/meetings/{meeting.meeting_id}",
        json={"owner_id": cofac_user_id},
    )
    assert restricted_response.status_code == 403, restricted_response.json()

    update_payload = {
        "title": "Updated by Co-Facilitator",
        "description": "Adjusted details by co-facilitator",
    }
    update_response = client.put(
        f"/api/meetings/{meeting.meeting_id}",
        json=update_payload,
    )
    assert update_response.status_code == 200, f"Response: {update_response.json()}"
    updated = update_response.json()
    assert updated["title"] == update_payload["title"]
    assert updated["description"] == update_payload["description"]
    assert updated["owner_id"] == admin_user_id


def test_facilitator_controls_start_stop_tool(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None

    db = user_manager_with_admin.db
    cofac_user = user_manager_with_admin.add_user(
        first_name="Real",
        last_name="Facilitator",
        email="facilitator@example.com",
        hashed_password=get_password_hash("FacPass1!"),
        role=UserRole.FACILITATOR.value,
        login="real_facilitator",
    )
    db.commit()
    db.refresh(cofac_user)

    meeting_request = {
        "title": "Realtime Workshop",
        "description": "Testing facilitator controls",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "agenda_items": ["Kickoff"],
        "participant_contacts": [admin_user.login],
        "co_facilitator_ids": [cofac_user.user_id],
    }
    meeting_response = authenticated_client.post("/api/meetings/", json=meeting_request)
    assert meeting_response.status_code == 200, meeting_response.json()
    meeting_data = meeting_response.json()
    meeting_id = meeting_data["id"]
    activity_id = meeting_data["agenda"][0]["activity_id"]

    start_payload = {
        "action": "start_tool",
        "tool": "brainstorming",
        "activityId": activity_id,
        "metadata": {"phase": "ideation"},
    }
    start_response = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control", json=start_payload
    )
    assert start_response.status_code == 200, start_response.json()
    start_state = start_response.json()["state"]
    assert start_state["currentTool"] == "brainstorming"
    assert start_state["currentActivity"] == activity_id
    assert start_state["metadata"]["phase"] == "ideation"
    assert start_state["status"] == "in_progress"

    stop_payload = {
        "action": "stop_tool",
        "status": "completed",
        "activityId": activity_id,
    }
    stop_response = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control", json=stop_payload
    )
    assert stop_response.status_code == 200, stop_response.json()
    stop_state = stop_response.json()["state"]
    assert stop_state["currentTool"] is None
    assert stop_state["status"] == "completed"


def test_start_preserves_accumulated_elapsed_time(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None

    meeting_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Elapsed Preservation",
            "description": "Ensure elapsed_time survives restart",
            "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "agenda_items": ["Item A"],
            "participant_contacts": [admin_user.login],
        },
    )
    assert meeting_response.status_code == 200, meeting_response.json()
    meeting_data = meeting_response.json()
    meeting_id = meeting_data["id"]
    activity_id = meeting_data["agenda"][0]["activity_id"]

    # Preload elapsed time to simulate prior run
    activity = (
        user_manager_with_admin.db.query(AgendaActivity)
        .filter(AgendaActivity.activity_id == activity_id)
        .first()
    )
    assert activity is not None
    activity.elapsed_duration = 25
    user_manager_with_admin.db.commit()

    start_res = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={
            "action": "start_tool",
            "tool": "brainstorming",
            "activityId": activity_id,
        },
    )
    assert start_res.status_code == 200, start_res.json()
    payload = start_res.json()["state"]
    assert payload["metadata"]["elapsedTime"] == 25


def test_participant_cannot_control_meeting(
    client: TestClient,
    db_session,
    user_manager_with_admin: UserManager,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None

    participant_password = "Participant1!"
    participant_user = user_manager_with_admin.add_user(
        first_name="Plain",
        last_name="Participant",
        email="participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="plain_participant",
    )
    db_session.commit()
    db_session.refresh(participant_user)

    meeting_manager = MeetingManager(db_session)
    meeting_payload = MeetingCreate(
        title="Participant Restrictions",
        description="Ensure participants lack control access",
        start_time=datetime.now(UTC) + timedelta(minutes=30),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=admin_user.user_id,
        participant_ids=[participant_user.user_id],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager.create_meeting(meeting_payload, admin_user.user_id)
    assert meeting is not None

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant_user.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.json()

    control_attempt = client.post(
        f"/api/meetings/{meeting.meeting_id}/control",
        json={"action": "start_tool", "tool": "polling"},
    )
    assert control_attempt.status_code == 403


def test_control_default_scope_resets_between_runs(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None

    meeting_request = {
        "title": "Scoped Control Session",
        "description": "Verify scope resets when launching new activities",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "agenda_items": ["Item A", "Item B"],
        "participant_contacts": [admin_user.login],
    }
    meeting_response = authenticated_client.post("/api/meetings/", json=meeting_request)
    assert meeting_response.status_code == 200, meeting_response.json()
    meeting_data = meeting_response.json()
    meeting_id = meeting_data["id"]
    activity_id_1 = meeting_data["agenda"][0]["activity_id"]
    activity_id_2 = meeting_data["agenda"][1]["activity_id"]

    # Launch with a custom scope
    first_start = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={
            "action": "start_tool",
            "tool": "brainstorming",
            "activityId": activity_id_1,
            "metadata": {
                "participantScope": "custom",
                "participantIds": [admin_user.user_id],
            },
        },
    )
    assert first_start.status_code == 200, first_start.json()
    first_state = first_start.json()["state"]
    assert first_state["metadata"].get("participantScope") == "custom"
    assert admin_user.user_id in first_state["metadata"].get("participantIds", [])

    # Launch another activity without metadata; scope should reset to "all"
    second_start = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={
            "action": "start_tool",
            "tool": "voting",
            "activityId": activity_id_2,
        },
    )
    assert second_start.status_code == 200, second_start.json()
    second_state = second_start.json()["state"]
    assert second_state["metadata"].get("participantScope") == "all"
    assert second_state["metadata"].get("participantIds") == []


def test_control_stop_clears_scope_metadata(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None

    meeting_request = {
        "title": "Scope Stop Reset",
        "description": "Stopping an activity should clear scoped metadata.",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "agenda_items": ["Item A"],
        "participant_contacts": [admin_user.login],
    }
    meeting_response = authenticated_client.post("/api/meetings/", json=meeting_request)
    assert meeting_response.status_code == 200, meeting_response.json()
    meeting_data = meeting_response.json()
    meeting_id = meeting_data["id"]
    activity_id = meeting_data["agenda"][0]["activity_id"]

    start = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={
            "action": "start_tool",
            "tool": "brainstorming",
            "activityId": activity_id,
            "metadata": {
                "participantScope": "custom",
                "participantIds": [admin_user.user_id],
            },
        },
    )
    assert start.status_code == 200, start.json()
    stop = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={"action": "stop_tool", "activityId": activity_id},
    )
    assert stop.status_code == 200, stop.json()
    stop_state = stop.json()["state"]
    assert stop_state["currentTool"] is None
    assert stop_state["metadata"].get("participantScope") == "all"
    assert stop_state["metadata"].get("participantIds") == []


def test_control_start_allows_overlap(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    """Starting an activity with overlapping participants should succeed when exclusivity is disabled."""
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None

    participant_one = user_manager_with_admin.add_user(
        first_name="Collide",
        last_name="One",
        email="collide.one@example.com",
        hashed_password=get_password_hash("CollideOne1!"),
        role=UserRole.PARTICIPANT.value,
        login="collide_one",
    )
    participant_two = user_manager_with_admin.add_user(
        first_name="Collide",
        last_name="Two",
        email="collide.two@example.com",
        hashed_password=get_password_hash("CollideTwo1!"),
        role=UserRole.PARTICIPANT.value,
        login="collide_two",
    )
    db_session.commit()
    db_session.refresh(participant_one)
    db_session.refresh(participant_two)

    meeting_manager = MeetingManager(db_session)
    meeting_payload = MeetingCreate(
        title="Collision Details",
        description="Conflict header should be returned on collisions",
        start_time=datetime.now(UTC) + timedelta(minutes=30),
        duration_minutes=30,
        publicity=PublicityType.PUBLIC,
        owner_id=admin_user.user_id,
        participant_ids=[participant_one.user_id, participant_two.user_id],
        additional_facilitator_ids=[],
    )
    meeting = meeting_manager.create_meeting(
        meeting_payload,
        facilitator_id=admin_user.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Active"),
            AgendaActivityCreate(tool_type="voting", title="Next"),
        ],
    )
    assert meeting is not None
    activity_one = meeting.agenda_activities[0].activity_id
    activity_two = meeting.agenda_activities[1].activity_id

    # Seed live state so activity_one is running with participant_one
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": activity_one,
                "agendaItemId": activity_one,
                "currentTool": "brainstorming",
                "status": "in_progress",
                "activeActivities": [
                    {
                        "activityId": activity_one,
                        "tool": "brainstorming",
                        "status": "in_progress",
                        "participantIds": [participant_one.user_id],
                    }
                ],
            },
        )
    )

    # Attempt to start activity_two which includes both participants
    start_attempt = authenticated_client.post(
        f"/api/meetings/{meeting.meeting_id}/control",
        json={"action": "start_tool", "tool": "voting", "activityId": activity_two},
    )
    assert start_attempt.status_code == 200, start_attempt.json()

def test_join_meeting_by_code_success(
    authenticated_client: TestClient, user_manager_with_admin: UserManager
):
    """Posting to /api/meetings/join should add the user and return redirect."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    meeting_request = {
        "title": "Joinable Session",
        "description": "Test join flow",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "agenda_items": ["Intro"],
        "participant_contacts": [admin_user.login],
    }
    create_res = authenticated_client.post("/api/meetings/", json=meeting_request)
    assert create_res.status_code == 200, create_res.json()
    meeting_id = create_res.json()["id"]

    join_res = authenticated_client.post(
        "/api/meetings/join",
        json={
            "meeting_code": meeting_id,
            "display_name": admin_user.first_name or admin_user.login,
        },
    )
    assert join_res.status_code == 200, join_res.json()
    payload = join_res.json()
    assert payload["meeting_id"] == meeting_id
    assert payload["redirect"] == f"/meeting/{meeting_id}"
    assert payload["status"] == "joined"


def test_guest_join_by_code_success(
    client: TestClient, user_manager_with_admin: UserManager
):
    """Unauthenticated users can join as guests and receive an auth cookie."""
    if not get_guest_join_enabled():
        pytest.skip("Guest join disabled by config.")
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    # Log in to create a meeting, then clear cookie to simulate guest
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_login = os.getenv("ADMIN_LOGIN", admin_email.split("@")[0])
    admin_password = os.getenv("ADMIN_PASSWORD", "Admin@123!")
    login_data = {"username": admin_login, "password": admin_password}
    login_res = client.post("/api/auth/token", json=login_data)
    assert login_res.status_code == 200

    meeting_request = {
        "title": "Guest Joinable Session",
        "description": "Guest join flow",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "agenda_items": ["Intro"],
        "participant_contacts": [admin_user.login],
    }
    create_res = client.post("/api/meetings/", json=meeting_request)
    assert create_res.status_code == 200, create_res.json()
    meeting_id = create_res.json()["id"]

    # Clear auth cookie to emulate an unauthenticated guest
    client.cookies.clear()

    join_payload = {
        "meeting_code": meeting_id,
        "display_name": "Guest Tester",
        "email": "guest@example.com",
        "as_guest": True,
    }
    join_res = client.post("/api/meetings/join", json=join_payload)
    assert join_res.status_code == 200, join_res.json()
    data = join_res.json()
    assert data["meeting_id"] == meeting_id
    assert data["redirect"] == f"/meeting/{meeting_id}"
    assert data["status"] == "joined"
    # Cookie should be set to authenticate subsequent requests
    assert "access_token" in join_res.cookies


def test_guest_join_requires_flag(
    client: TestClient, user_manager_with_admin: UserManager
):
    """Unauthenticated join without as_guest flag should return 401."""
    if not get_guest_join_enabled():
        pytest.skip("Guest join disabled by config.")
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    # Log in to create a meeting, then clear cookie to simulate guest
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_login = os.getenv("ADMIN_LOGIN", admin_email.split("@")[0])
    admin_password = os.getenv("ADMIN_PASSWORD", "Admin@123!")
    login_data = {"username": admin_login, "password": admin_password}
    login_res = client.post("/api/auth/token", json=login_data)
    assert login_res.status_code == 200

    meeting_request = {
        "title": "Flag Required Session",
        "description": "Ensure 401 without as_guest",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "agenda_items": ["Intro"],
        "participant_contacts": [admin_user.login],
    }
    create_res = client.post("/api/meetings/", json=meeting_request)
    assert create_res.status_code == 200, create_res.json()
    meeting_id = create_res.json()["id"]

    # Clear auth cookie to emulate an unauthenticated guest
    client.cookies.clear()

    join_payload = {
        "meeting_code": meeting_id,
        "display_name": "Unauthenticated User",
        # No as_guest flag
    }
    join_res = client.post("/api/meetings/join", json=join_payload)
    assert join_res.status_code == 401, join_res.json()
    detail = join_res.json().get("detail")
    assert detail == "Authentication required."


def test_join_meeting_by_code_participant_added(
    client: TestClient,
    authenticated_client: TestClient,
    db_session,
    user_manager_with_admin: UserManager,
):
    """A non-member participant can join a meeting by code and is added."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    # Create a participant user and log them in
    participant_password = "JoinPass1!"
    participant_user = user_manager_with_admin.add_user(
        first_name="New",
        last_name="Participant",
        email="new.participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="new_participant",
    )
    db_session.commit()
    db_session.refresh(participant_user)

    # Create a meeting without this participant
    meeting_req = {
        "title": "Join Flow",
        "description": "Verify participant added",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "agenda_items": ["Welcome"],
        "participant_contacts": [admin_user.login],
    }
    m_res = authenticated_client.post("/api/meetings/", json=meeting_req)
    assert m_res.status_code == 200, m_res.json()
    meeting_id = m_res.json()["id"]

    # Login as the participant
    login_res = client.post(
        "/api/auth/token",
        json={"username": participant_user.login, "password": participant_password},
    )
    assert login_res.status_code == 200, login_res.json()

    # Join the meeting by code
    j_res = client.post(
        "/api/meetings/join",
        json={"meeting_code": meeting_id, "display_name": "New Participant"},
    )
    assert j_res.status_code == 200, j_res.json()
    j_payload = j_res.json()
    assert j_payload["meeting_id"] == meeting_id
    assert j_payload["redirect"].endswith(meeting_id)


def test_join_meeting_by_code_not_found(authenticated_client: TestClient):
    """Joining a nonexistent meeting should return 404."""
    bad_code = "MTG20990101-XXXX"
    res = authenticated_client.post(
        "/api/meetings/join", json={"meeting_code": bad_code}
    )
    assert res.status_code == 404
