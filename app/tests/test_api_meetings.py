import asyncio
import base64
import io
import json
import os
import zipfile
from pathlib import Path
from datetime import datetime, timedelta, UTC

import pytest
from fastapi.testclient import TestClient

import app.routers.meetings as meetings_router
from app.config.loader import get_guest_join_enabled
from app.data.user_manager import UserManager
from app.data.meeting_manager import MeetingManager
from app.services import meeting_state_manager
from app.schemas.meeting import AgendaActivityCreate
from app.schemas.meeting import MeetingCreate, PublicityType
from app.models.categorization import CategorizationBallot
from app.models.idea import Idea
from app.models.meeting import AgendaActivity
from app.data.activity_bundle_manager import ActivityBundleManager
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

APP_ROOT = Path(__file__).resolve().parents[1]


def _decode_export_zip() -> bytes:
    return base64.b64decode(EXPORT_ZIP_BASE64)


def test_phase6_step3_removed_model_residue_absent_from_active_app_code():
    """Lobster Teacup: Phase 6 Step 3 proves removed facilitator-model tokens are absent from non-test app code."""
    forbidden_markers = [
        "MeetingFacilitator",
        "meeting_facilitators",
        "facilitator_links",
        "_ensure_facilitator_assignment",
        "_collect_facilitator_assignments",
        "_should_auto_facilitate",
    ]
    active_files = [
        path
        for path in APP_ROOT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and "tests" not in path.parts
        and path.suffix in {".py", ".js", ".html", ".yaml", ".yml", ".json", ".css"}
    ]

    residue = {
        str(path.relative_to(APP_ROOT.parent)): [
            marker for marker in forbidden_markers if marker in path.read_text(encoding="utf-8")
        ]
        for path in active_files
    }
    residue = {path: markers for path, markers in residue.items() if markers}

    assert residue == {}


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
    """Muffin Tractor: dashboard inventory exposes meeting capability metadata for the Phase 1 contract."""

    response = authenticated_client.get("/api/meetings/")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"items", "summary", "filters"}
    assert isinstance(payload["items"], list)
    assert payload["summary"]["total"] == len(payload["items"])
    assert payload["filters"]["role_scope"] == "participant"
    assert any(item["id"] == test_meeting_data for item in payload["items"])
    meeting_item = next(item for item in payload["items"] if item["id"] == test_meeting_data)
    assert {"enter", "details", "roster"}.issubset(meeting_item["quick_actions"].keys())
    assert meeting_item["quick_actions"]["roster"].endswith("?roster=1")
    assert "notifications" in meeting_item
    assert "owner" in meeting_item
    assert meeting_item["owner"]["name"]
    assert "authority_names" in meeting_item
    assert isinstance(meeting_item["authority_names"], list)
    assert meeting_item["authority_names"]
    assert "facilitator_names" not in meeting_item
    assert "facilitators" not in meeting_item
    assert "is_facilitator" in meeting_item
    assert meeting_item["is_facilitator"] is True
    assert meeting_item["viewer_capabilities"]["can_view"] is True
    assert meeting_item["viewer_capabilities"]["can_manage"] is True
    assert meeting_item["viewer_capabilities"]["can_delete"] is True
    assert meeting_item["viewer_capabilities"]["is_facilitator"] is True
    assert meeting_item["viewer_capabilities"]["is_participant"] is False


def test_list_meetings_supports_status_filter(
    authenticated_client: TestClient, test_meeting_data: str
):
    """Status filter should narrow results to the requested bucket."""

    response = authenticated_client.get("/api/meetings/?status=never_started")

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["status"] == "never_started"
    assert payload["summary"]["never_started"] == len(payload["items"])


def test_archive_and_restore_meeting_dashboard_visibility(
    authenticated_client: TestClient,
    test_meeting_data: str,
):
    """Archived meetings should move off the default dashboard and support restore."""
    archive_response = authenticated_client.post(
        f"/api/meetings/{test_meeting_data}/archive"
    )
    assert archive_response.status_code == 200, archive_response.json()
    archived_payload = archive_response.json()
    assert archived_payload["status"] == "archived"
    snapshot = asyncio.run(meeting_state_manager.snapshot(test_meeting_data))
    assert snapshot["status"] == "archived"
    assert snapshot["metadata"]["archived"] is True

    active_dashboard = authenticated_client.get("/api/meetings/")
    assert active_dashboard.status_code == 200
    active_items = active_dashboard.json()["items"]
    assert all(item["id"] != test_meeting_data for item in active_items)

    archived_dashboard = authenticated_client.get("/api/meetings/archived")
    assert archived_dashboard.status_code == 200
    archived_items = archived_dashboard.json()["items"]
    archived_item = next(
        (item for item in archived_items if item["id"] == test_meeting_data),
        None,
    )
    assert archived_item is not None
    assert archived_item["raw_status"] == "archived"
    assert archived_item.get("archive_file")
    archive_file = Path(archived_item["archive_file"])
    assert archive_file.is_file()

    restore_response = authenticated_client.post(
        f"/api/meetings/{test_meeting_data}/restore"
    )
    assert restore_response.status_code == 200, restore_response.json()
    restored_payload = restore_response.json()
    assert restored_payload["status"] == "completed"
    assert asyncio.run(meeting_state_manager.snapshot(test_meeting_data)) is None

    refreshed_active = authenticated_client.get("/api/meetings/")
    assert refreshed_active.status_code == 200
    assert any(
        item["id"] == test_meeting_data for item in refreshed_active.json()["items"]
    )

    refreshed_archived = authenticated_client.get("/api/meetings/archived")
    assert refreshed_archived.status_code == 200
    assert all(
        item["id"] != test_meeting_data for item in refreshed_archived.json()["items"]
    )


def test_archive_meeting_does_not_force_connected_clients_to_redirect(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    monkeypatch,
):
    """Archiving should not force-navigate meeting pages; clients show a notice."""
    participant_password = "ParticipantArchived@123!"
    participant = user_manager_with_admin.add_user(
        first_name="Archive",
        last_name="Target",
        email="archive.target@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="archive_target",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(participant)

    create_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Archive Target Meeting",
            "description": "Archive should not force websocket redirects.",
            "agenda_items": ["Discuss"],
            "participant_ids": [participant.user_id],
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    meeting_id = created["id"]
    personal_messages = []

    async def capture_personal(meeting_id_arg, connection_id, message):
        personal_messages.append((meeting_id_arg, connection_id, message))

    monkeypatch.setattr(
        meetings_router.websocket_manager,
        "send_personal_message",
        capture_personal,
    )

    archive_response = authenticated_client.post(f"/api/meetings/{meeting_id}/archive")
    assert archive_response.status_code == 200, archive_response.json()
    assert personal_messages == []


def test_archive_meeting_broadcasts_meeting_archived_notice(
    authenticated_client: TestClient,
    mocker,
):
    """Archiving broadcasts a `meeting_archived` envelope so connected clients
    surface the archived popup (return-to-dashboard) instead of sitting in a
    dead meeting."""
    create_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Archive Notice Meeting",
            "description": "Archiving should notify connected clients.",
            "agenda_items": ["Discuss"],
            "participant_ids": [],
        },
    )
    assert create_response.status_code == 200, create_response.text
    meeting_id = create_response.json()["id"]

    broadcast_mock = mocker.patch(
        "app.routers.meetings.websocket_manager.broadcast"
    )

    archive_response = authenticated_client.post(f"/api/meetings/{meeting_id}/archive")
    assert archive_response.status_code == 200, archive_response.json()

    archived_messages = [
        call.args[1]
        for call in broadcast_mock.await_args_list
        if call.args[1].get("type") == "meeting_archived"
    ]
    assert len(archived_messages) == 1, broadcast_mock.await_args_list
    assert archived_messages[0]["payload"]["meetingId"] == meeting_id


def test_save_meeting_as_template_endpoint_strips_runtime_data(
    authenticated_client: TestClient,
):
    meeting_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Reusable Working Session",
            "description": "A structure worth repeating.",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect options",
                    "order_index": 1,
                    "config": {
                        "prompt": "Suggest options",
                        "duration_minutes": 12,
                        "output_bundle": {"items": ["runtime idea"]},
                        "votes": [{"option": "runtime"}],
                        "elapsedTime": 99,
                    },
                }
            ],
        },
    )
    assert meeting_response.status_code == 200, meeting_response.text
    meeting_id = meeting_response.json()["id"]

    template_response = authenticated_client.post(
        f"/api/meetings/{meeting_id}/templates",
        json={
            "name": "Repeatable Working Session",
            "purpose": "Use this structure again.",
            "tags": ["Reusable", "Reusable", "Workshop"],
        },
    )

    assert template_response.status_code == 200, template_response.text
    payload = template_response.json()
    assert payload["source"] == "custom"
    assert payload["name"] == "Repeatable Working Session"
    assert payload["purpose"] == "Use this structure again."
    assert payload["tags"] == ["Reusable", "Workshop"]
    assert payload["permissions"]["can_edit"] is True
    assert payload["template_payload"]["defaults"]["title"] == "Reusable Working Session"
    saved_config = payload["template_payload"]["agenda"][0]["config"]
    assert saved_config["prompt"] == "Suggest options"
    assert "output_bundle" not in saved_config
    assert "votes" not in saved_config
    assert "elapsedTime" not in saved_config
    assert "participant_ids" not in json.dumps(payload["template_payload"])


def test_custom_template_metadata_archive_and_delete_lifecycle(
    authenticated_client: TestClient,
):
    meeting_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Lifecycle Source Meeting",
            "description": "Template lifecycle source.",
            "agenda_items": ["Review"],
        },
    )
    assert meeting_response.status_code == 200, meeting_response.text
    meeting_id = meeting_response.json()["id"]

    template_response = authenticated_client.post(
        f"/api/meetings/{meeting_id}/templates",
        json={"name": "Lifecycle Template"},
    )
    assert template_response.status_code == 200, template_response.text
    template_id = template_response.json()["template_id"]

    update_response = authenticated_client.put(
        f"/api/meetings/templates/{template_id}",
        json={
            "name": "Renamed Lifecycle Template",
            "purpose": "Reusable lifecycle path.",
            "tags": ["Lifecycle", "Lifecycle", "Custom"],
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["name"] == "Renamed Lifecycle Template"
    assert updated["purpose"] == "Reusable lifecycle path."
    assert updated["tags"] == ["Lifecycle", "Custom"]
    assert updated["permissions"]["can_archive"] is True
    assert updated["permissions"]["can_delete"] is True

    archive_response = authenticated_client.post(
        f"/api/meetings/templates/{template_id}/archive",
        json={},
    )
    assert archive_response.status_code == 200, archive_response.text
    assert archive_response.json()["status"] == "archived"

    delete_response = authenticated_client.delete(f"/api/meetings/templates/{template_id}")
    assert delete_response.status_code == 204

    second_delete = authenticated_client.delete(f"/api/meetings/templates/{template_id}")
    assert second_delete.status_code == 404


def test_builtin_template_management_routes_are_read_only(
    authenticated_client: TestClient,
    db_session,
):
    from app.data.meeting_template_manager import seed_builtin_meeting_templates

    [template] = seed_builtin_meeting_templates(db_session)

    update_response = authenticated_client.put(
        f"/api/meetings/templates/{template.template_id}",
        json={"name": "Not Editable"},
    )
    assert update_response.status_code == 403

    archive_response = authenticated_client.post(
        f"/api/meetings/templates/{template.template_id}/archive",
        json={},
    )
    assert archive_response.status_code == 403

    delete_response = authenticated_client.delete(
        f"/api/meetings/templates/{template.template_id}"
    )
    assert delete_response.status_code == 403


def test_participant_cannot_save_meeting_as_template(
    client: TestClient,
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    participant_password = "TemplateSave1!"
    participant = user_manager_with_admin.add_user(
        first_name="Template",
        last_name="Participant",
        email="template.participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="template_participant",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(participant)

    meeting_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Participant Template Block",
            "description": "Participants can attend but not save templates.",
            "agenda_items": ["Review"],
            "participant_ids": [participant.user_id],
        },
    )
    assert meeting_response.status_code == 200, meeting_response.text
    meeting_id = meeting_response.json()["id"]

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.text

    template_response = client.post(
        f"/api/meetings/{meeting_id}/templates",
        json={"name": "Should Not Save"},
    )
    assert template_response.status_code == 403


def test_participant_cannot_archive_meeting(
    client: TestClient,
    user_manager_with_admin: UserManager,
    test_meeting_data: str,
):
    """Muffin Tractor: roster participants can view meetings but cannot archive or otherwise manage them."""
    participant_password = "ParticipantArchive@123!"
    participant = user_manager_with_admin.add_user(
        first_name="Part",
        last_name="Archiver",
        email="participant.archive@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="participant_archive",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(participant)

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.text

    archive_response = client.post(f"/api/meetings/{test_meeting_data}/archive")
    assert archive_response.status_code == 403


def test_dashboard_marks_rostered_participant_as_non_facilitator(
    authenticated_client: TestClient,
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    """Muffin Tractor: roster-only participants appear on the dashboard without facilitator authority."""
    participant_password = "ParticipantDashboard@123!"
    participant = user_manager_with_admin.add_user(
        first_name="Dash",
        last_name="Participant",
        email="participant.dashboard@example.com",
        hashed_password=get_password_hash(participant_password),
        role=UserRole.PARTICIPANT.value,
        login="participant_dashboard",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(participant)

    create_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Participant Dashboard Scope",
            "description": "Verifies participant-facing meeting capability output",
            "scheduled_datetime": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "agenda_items": ["Review"],
            "participant_ids": [participant.user_id],
        },
    )
    assert create_response.status_code == 200, create_response.json()
    meeting_id = create_response.json()["id"]

    login_response = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login_response.status_code == 200, login_response.text

    dashboard_response = client.get("/api/meetings/")
    assert dashboard_response.status_code == 200, dashboard_response.json()
    meeting_item = next(
        item for item in dashboard_response.json()["items"] if item["id"] == meeting_id
    )
    assert meeting_item["is_participant"] is True
    assert meeting_item["is_facilitator"] is False
    assert meeting_item["viewer_capabilities"]["can_view"] is True
    assert meeting_item["viewer_capabilities"]["can_manage"] is False
    assert meeting_item["viewer_capabilities"]["can_delete"] is False
    assert meeting_item["viewer_capabilities"]["is_facilitator"] is False
    assert meeting_item["viewer_capabilities"]["is_participant"] is True


def test_meeting_payload_exposes_rostered_facilitator_viewer_capabilities(
    authenticated_client: TestClient,
    client: TestClient,
    user_manager_with_admin: UserManager,
):
    """Toaster Sombrero: meeting payload exposes backend-derived viewer capability state for the current rostered facilitator."""
    facilitator_password = "ViewerCaps1!"
    facilitator = user_manager_with_admin.add_user(
        first_name="Viewer",
        last_name="Caps",
        email="viewer.caps@example.com",
        hashed_password=get_password_hash(facilitator_password),
        role=UserRole.FACILITATOR.value,
        login="viewer_caps_facilitator",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(facilitator)

    create_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Viewer Capability Meeting",
            "description": "Expose meeting capability state to rostered facilitator clients",
            "scheduled_datetime": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "agenda_items": ["Review"],
            "participant_ids": [facilitator.user_id],
            "co_facilitator_ids": [facilitator.user_id],
        },
    )
    assert create_response.status_code == 200, create_response.json()
    meeting_id = create_response.json()["id"]

    login_response = client.post(
        "/api/auth/token",
        json={"username": facilitator.login, "password": facilitator_password},
    )
    assert login_response.status_code == 200, login_response.text

    meeting_response = client.get(f"/api/meetings/{meeting_id}")
    assert meeting_response.status_code == 200, meeting_response.json()
    viewer_capabilities = meeting_response.json()["viewer_capabilities"]
    assert viewer_capabilities["can_view"] is True
    assert viewer_capabilities["can_manage"] is True
    assert viewer_capabilities["can_delete"] is False
    assert viewer_capabilities["is_facilitator"] is True
    assert viewer_capabilities["is_participant"] is True


def test_export_meeting_returns_zip_bundle(
    authenticated_client: TestClient, test_meeting_data: str
):
    """Pickle Trombone: new meeting exports write owner metadata without legacy facilitator structures."""
    response = authenticated_client.get(f"/api/meetings/{test_meeting_data}/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "meeting.json" in archive.namelist()

    meeting_payload = json.loads(archive.read("meeting.json").decode("utf-8"))
    assert meeting_payload["meeting"]["meeting_id"] == test_meeting_data
    assert meeting_payload["meeting"]["title"] == "Test Meeting for Get"
    assert "owner" in meeting_payload
    assert meeting_payload["owner"]["user_id"]
    assert "facilitators" not in meeting_payload


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


def test_import_ignores_legacy_facilitators_as_authority(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    """Pickle Trombone: legacy import compatibility reads old facilitator-bearing bundles one way without granting active authority."""
    legacy_password = "LegacyImportFac1!"
    legacy_facilitator = user_manager_with_admin.add_user(
        first_name="Legacy",
        last_name="ImportFac",
        email="legacy.import.facilitator@example.com",
        hashed_password=get_password_hash(legacy_password),
        role=UserRole.FACILITATOR.value,
        login="legacy_import_facilitator",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(legacy_facilitator)

    export_payload = {
        "version": 1,
        "meeting": {
            "title": "Legacy Facilitator Import",
            "description": "Old bundle with facilitator-only user",
            "is_public": True,
        },
        "facilitators": [
            {
                "user_id": legacy_facilitator.user_id,
                "login": legacy_facilitator.login,
                "email": legacy_facilitator.email,
                "first_name": legacy_facilitator.first_name,
                "last_name": legacy_facilitator.last_name,
                "is_owner": False,
            }
        ],
        "participants": [],
        "agenda": [],
        "ideas": [],
        "votes": [],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("meeting.json", json.dumps(export_payload))

    response = authenticated_client.post(
        "/api/meetings/import",
        content=buffer.getvalue(),
        headers={"Content-Type": "application/zip"},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert legacy_facilitator.user_id not in payload["participant_ids"]
    assert legacy_facilitator.user_id not in payload["authority_user_ids"]
    assert all(
        authority["user_id"] != legacy_facilitator.user_id
        for authority in payload["meeting_authorities"]
    )


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
    }

    # Act
    response = authenticated_client.post("/api/meetings/", json=meeting_data)

    # Assert
    assert response.status_code == 200, f"Response: {response.json()}"
    result = response.json()
    assert result["title"] == meeting_data["title"]
    assert result["description"] == meeting_data["description"]
    assert "id" in result
    assert result.get("authority_user_ids")
    assert result.get("meeting_authorities")
    assert "facilitator_user_ids" not in result
    assert "facilitators" not in result
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
    assert result["viewer_capabilities"]["can_view"] is True
    assert result["viewer_capabilities"]["can_manage"] is True
    assert result["viewer_capabilities"]["can_delete"] is True
    assert result["viewer_capabilities"]["is_facilitator"] is True
    assert result["viewer_capabilities"]["is_participant"] is False
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None
    assert admin_user.user_id in result.get("authority_user_ids", [])
    assert "facilitator_user_ids" not in result
    assert "agenda" in result
    assert len(result["agenda"]) >= 1


def test_meeting_outputs_ignore_off_roster_facilitator_role(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    """Pickle Trombone: active meeting and dashboard outputs expose authority metadata, not facilitator assignment fields."""
    off_roster_password = "LegacyFac1!"
    off_roster_user = user_manager_with_admin.add_user(
        first_name="Legacy",
        last_name="Facilitator",
        email="legacy.facilitator@example.com",
        hashed_password=get_password_hash(off_roster_password),
        role=UserRole.FACILITATOR.value,
        login="legacy_off_roster_facilitator",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(off_roster_user)

    create_response = authenticated_client.post(
        "/api/meetings/",
        json={
            "title": "Canonical Output Meeting",
            "description": "Step 4 capability output regression",
            "scheduled_datetime": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "agenda_items": ["Review"],
        },
    )
    assert create_response.status_code == 200, create_response.json()
    meeting_id = create_response.json()["id"]

    update_response = authenticated_client.put(
        f"/api/meetings/{meeting_id}",
        json={"facilitator_ids": [off_roster_user.user_id]},
    )
    assert update_response.status_code == 200, update_response.json()

    meeting_response = authenticated_client.get(f"/api/meetings/{meeting_id}")
    assert meeting_response.status_code == 200, meeting_response.json()
    meeting_payload = meeting_response.json()
    assert off_roster_user.user_id not in meeting_payload["authority_user_ids"]
    assert "Legacy Facilitator" not in meeting_payload["authority_names"]
    assert all(
        authority["user_id"] != off_roster_user.user_id
        for authority in meeting_payload["meeting_authorities"]
    )
    for removed_key in ("facilitator_user_ids", "facilitator_names", "facilitators"):
        assert removed_key not in meeting_payload

    dashboard_response = authenticated_client.get("/api/meetings/")
    assert dashboard_response.status_code == 200, dashboard_response.json()
    meeting_item = next(
        item for item in dashboard_response.json()["items"] if item["id"] == meeting_id
    )
    assert off_roster_user.user_id not in [
        authority["user_id"] for authority in meeting_item["meeting_authorities"]
    ]
    assert "Legacy Facilitator" not in meeting_item["authority_names"]
    for removed_key in ("facilitator", "facilitator_names", "facilitators"):
        assert removed_key not in meeting_item


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
    voting = next((entry for entry in catalog if entry.get("tool_type") == "voting"), None)
    assert brainstorming is not None
    assert voting is not None
    assert "reliability_policy" in brainstorming
    assert "write_default" in (brainstorming.get("reliability_policy") or {})
    assert "write_default" in (voting.get("reliability_policy") or {})


def test_add_agenda_item_to_meeting(
    authenticated_client: TestClient, test_meeting_data: str, mocker
):
    """Smug Otter: agenda API reads preserve behavior through AgendaStrategy."""

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

    strategy_spy = mocker.spy(meetings_router, "get_agenda_strategy")
    list_response = authenticated_client.get(
        f"/api/meetings/{test_meeting_data}/agenda"
    )
    assert list_response.status_code == 200
    items = list_response.json()
    assert any(item["activity_id"] == created["activity_id"] for item in items)
    assert strategy_spy.call_count == 1


def test_running_meeting_agenda_post_resequences_and_broadcasts(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
    mocker,
):
    """Smug Otter: router mid-meeting insertion resequences and broadcasts agenda_update."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    assert admin_user is not None

    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Running Agenda Insert API",
            description="Router path should safely insert while active.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=45),
            duration_minutes=45,
            publicity=PublicityType.PRIVATE,
            owner_id=admin_user.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=admin_user.user_id,
        agenda_items=[
            AgendaActivityCreate(tool_type="brainstorming", title="Opening"),
            AgendaActivityCreate(tool_type="categorization", title="Grouping"),
        ],
    )
    running_activity_id = meeting.agenda_activities[0].activity_id

    try:
        asyncio.run(
            meeting_state_manager.apply_patch(
                meeting.meeting_id,
                {
                    "currentActivity": running_activity_id,
                    "agendaItemId": running_activity_id,
                    "currentTool": "brainstorming",
                    "status": "in_progress",
                },
            )
        )
        broadcast_mock = mocker.patch(
            "app.routers.meetings.websocket_manager.broadcast"
        )

        create_response = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/agenda",
            json={
                "tool_type": "voting",
                "title": "Inserted API Vote",
                "order_index": 2,
                "config": {"max_votes": 1},
            },
        )
        assert create_response.status_code == 201, create_response.json()
        created = create_response.json()
        assert created["activity_id"].startswith(f"{meeting.meeting_id}-RANKVT-")
        assert created["order_index"] == 2

        refreshed_agenda = meeting_manager.list_agenda(meeting.meeting_id)
        assert [activity.order_index for activity in refreshed_agenda] == [1, 2, 3]
        assert [activity.title for activity in refreshed_agenda] == [
            "Opening",
            "Inserted API Vote",
            "Grouping",
        ]

        assert broadcast_mock.await_count == 1
        broadcast_meeting_id, message = broadcast_mock.await_args.args
        assert broadcast_meeting_id == meeting.meeting_id
        assert message["type"] == "agenda_update"
        assert message["meta"]["initiatorId"] == admin_user.user_id
        assert [item["order_index"] for item in message["payload"]] == [1, 2, 3]
        assert any(
            item["activity_id"] == created["activity_id"]
            for item in message["payload"]
        )
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


def test_facilitator_decision_state_surfaces_prior_ai_review(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    """Loquacious Pelican: facilitator decision UI can load prompt/options and AI proposal."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Decision State API",
            description="Review endpoint test.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=admin_user.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=admin_user.user_id,
        agenda_items=[],
    )
    ai_activity = AgendaActivity(
        activity_id=f"{meeting.meeting_id}-AI-0001",
        meeting_id=meeting.meeting_id,
        tool_type="ai_decision",
        title="AI Summary",
        order_index=1,
        tool_config_id=f"{meeting.meeting_id}-CFG-AI-0001",
        config={},
    )
    decision_activity = AgendaActivity(
        activity_id=f"{meeting.meeting_id}-FD-0001",
        meeting_id=meeting.meeting_id,
        tool_type="facilitator_decision",
        title="Approve summary?",
        order_index=2,
        tool_config_id=f"{meeting.meeting_id}-CFG-FD-0001",
        config={
            "prompt": "Approve summary?",
            "options": ["approve", "reject"],
            "context_bundle_keys": [],
        },
    )
    db_session.add_all([ai_activity, decision_activity])
    db_session.commit()
    ActivityBundleManager(db_session).finalize_output_bundle(
        meeting.meeting_id,
        ai_activity.activity_id,
        items=[{
            "content": '{"summary": "Promote option A"}',
            "metadata": {
                "ai_decision": {
                    "validated_output": {"summary": "Promote option A"},
                    "review_required": True,
                }
            },
            "source": {
                "meeting_id": meeting.meeting_id,
                "activity_id": ai_activity.activity_id,
                "tool_type": "ai_decision",
            },
        }],
        metadata={"source": "ai_decision"},
    )

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/orchestration/facilitator-decisions/{decision_activity.activity_id}"
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["prompt"] == "Approve summary?"
    assert payload["options"] == ["approve", "reject"]
    assert payload["ai_decision"]["validated_output"] == {"summary": "Promote option A"}


def test_facilitator_decision_response_writes_bundle_and_broadcasts(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
    mocker,
):
    """Loquacious Pelican: decision response uses existing agenda/state envelopes."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    meeting_manager = MeetingManager(db_session)
    start_time = datetime.now(UTC) + timedelta(minutes=5)
    meeting = meeting_manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Decision Response API",
            description="Resume endpoint test.",
            start_time=start_time,
            end_time=start_time + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=admin_user.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=admin_user.user_id,
        agenda_items=[],
    )
    decision_activity = AgendaActivity(
        activity_id=f"{meeting.meeting_id}-FD-0002",
        meeting_id=meeting.meeting_id,
        tool_type="facilitator_decision",
        title="Continue?",
        order_index=1,
        tool_config_id=f"{meeting.meeting_id}-CFG-FD-0002",
        config={
            "prompt": "Continue?",
            "options": ["continue", "stop"],
            "context_bundle_keys": [],
        },
    )
    db_session.add(decision_activity)
    db_session.commit()
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting.meeting_id,
            {
                "currentActivity": decision_activity.activity_id,
                "agendaItemId": decision_activity.activity_id,
                "currentTool": "facilitator_decision",
                "status": "in_progress",
                "activeActivities": {
                    decision_activity.activity_id: {
                        "activityId": decision_activity.activity_id,
                        "tool": "facilitator_decision",
                        "status": "in_progress",
                    }
                },
            },
        )
    )
    broadcast_mock = mocker.patch(
        "app.services.orchestration_realtime.websocket_manager.broadcast"
    )

    try:
        response = authenticated_client.post(
            f"/api/meetings/{meeting.meeting_id}/orchestration/facilitator-decisions/{decision_activity.activity_id}/responses",
            json={"chosen_option": "continue"},
        )
        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["chosen_option"] == "continue"
        assert payload["state"]["currentActivity"] is None
        bundle = ActivityBundleManager(db_session).get_latest_bundle(
            meeting.meeting_id,
            decision_activity.activity_id,
            "output",
        )
        assert bundle.items[0]["metadata"]["facilitator_decision"]["chosen"] == "continue"
        assert broadcast_mock.await_count == 2
        assert broadcast_mock.await_args_list[0].args[1]["type"] == "agenda_update"
        assert broadcast_mock.await_args_list[1].args[1]["type"] == "meeting_state"
    finally:
        asyncio.run(meeting_state_manager.reset(meeting.meeting_id))


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


def test_rostered_facilitator_update_permissions(
    client: TestClient,
    db_session,
    user_manager_with_admin: UserManager,
):
    """Gravy Parachute: a rostered facilitator inherits core manage gates but not delete-authority gates such as delete, archive, or restore."""
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
        participant_ids=[cofac_user_id],
        additional_facilitator_ids=[],
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

    configuration_response = client.put(
        f"/api/meetings/{meeting.meeting_id}/configuration",
        json={
            "title": "Configured by Co-Facilitator",
            "description": "Updated through the configuration endpoint",
            "scheduled_datetime": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            "agenda_items": ["Review"],
            "participant_ids": [cofac_user_id],
        },
    )
    assert configuration_response.status_code == 200, configuration_response.json()

    archive_response = client.post(f"/api/meetings/{meeting.meeting_id}/archive")
    assert archive_response.status_code == 403, archive_response.json()

    restore_response = client.post(f"/api/meetings/{meeting.meeting_id}/restore")
    assert restore_response.status_code == 403, restore_response.json()

    delete_response = client.delete(f"/api/meetings/{meeting.meeting_id}")
    assert delete_response.status_code == 403, delete_response.json()


def test_facilitator_controls_start_stop_tool(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
):
    """Muffin Tractor: meeting-scoped management authority includes activity-control operations."""
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
        "description": "Testing meeting control authority",
        "scheduled_datetime": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "agenda_items": ["Kickoff"],
        "participant_ids": [cofac_user.user_id],
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


def test_removed_facilitator_loses_control_until_readded(
    client: TestClient,
    db_session,
    user_manager_with_admin: UserManager,
):
    """Lobster Teacup: remove-and-readd stale-authority prevention keeps UI/backend capabilities tied to current roster membership."""
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None

    facilitator_password = "RosterFac1!"
    facilitator_user = user_manager_with_admin.add_user(
        first_name="Roster",
        last_name="Facilitator",
        email="roster.facilitator@example.com",
        hashed_password=get_password_hash(facilitator_password),
        role=UserRole.FACILITATOR.value,
        login="roster_facilitator",
    )
    db_session.commit()
    db_session.refresh(facilitator_user)

    meeting_manager = MeetingManager(db_session)
    meeting_payload = MeetingCreate(
        title="Roster Access Boundary",
        description="Exercise remove and re-add meeting authority behavior",
        start_time=datetime.now(UTC) + timedelta(hours=2),
        duration_minutes=45,
        publicity=PublicityType.PUBLIC,
        owner_id=admin_user.user_id,
        participant_ids=[facilitator_user.user_id],
        additional_facilitator_ids=[facilitator_user.user_id],
    )
    meeting = meeting_manager.create_meeting(
        meeting_payload,
        admin_user.user_id,
        agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Kickoff")],
    )
    assert meeting is not None
    activity_id = meeting.agenda_activities[0].activity_id if meeting.agenda_activities else None
    assert activity_id is not None

    login_response = client.post(
        "/api/auth/token",
        json={"username": facilitator_user.login, "password": facilitator_password},
    )
    assert login_response.status_code == 200, login_response.text

    control_payload = {
        "action": "start_tool",
        "tool": "brainstorming",
        "activityId": activity_id,
    }
    initial_control = client.post(
        f"/api/meetings/{meeting.meeting_id}/control",
        json=control_payload,
    )
    assert initial_control.status_code == 200, initial_control.json()
    initial_page = client.get(f"/meeting/{meeting.meeting_id}")
    assert initial_page.status_code == 200, initial_page.text
    assert "Meeting Roster" in initial_page.text
    assert "Meeting Settings" in initial_page.text
    assert 'data-view-mode="facilitator"' in initial_page.text

    initial_dashboard = client.get("/api/meetings/")
    assert initial_dashboard.status_code == 200, initial_dashboard.json()
    initial_item = next(
        item
        for item in initial_dashboard.json()["items"]
        if item["id"] == meeting.meeting_id
    )
    assert initial_item["viewer_capabilities"]["can_manage"] is True

    meeting_manager.remove_participant(meeting.meeting_id, facilitator_user.user_id)
    after_removal = client.post(
        f"/api/meetings/{meeting.meeting_id}/control",
        json=control_payload,
    )
    assert after_removal.status_code == 403, after_removal.json()
    removed_page = client.get(f"/meeting/{meeting.meeting_id}")
    assert removed_page.status_code == 403, removed_page.text

    removed_dashboard = client.get("/api/meetings/")
    assert removed_dashboard.status_code == 200, removed_dashboard.json()
    assert all(
        item["id"] != meeting.meeting_id for item in removed_dashboard.json()["items"]
    )

    meeting_manager.add_participant(meeting.meeting_id, facilitator_user)
    after_readd = client.post(
        f"/api/meetings/{meeting.meeting_id}/control",
        json=control_payload,
    )
    assert after_readd.status_code == 200, after_readd.json()
    readded_page = client.get(f"/meeting/{meeting.meeting_id}")
    assert readded_page.status_code == 200, readded_page.text
    assert "Meeting Roster" in readded_page.text
    assert "Meeting Settings" in readded_page.text
    assert 'data-view-mode="facilitator"' in readded_page.text

    readded_dashboard = client.get("/api/meetings/")
    assert readded_dashboard.status_code == 200, readded_dashboard.json()
    readded_item = next(
        item
        for item in readded_dashboard.json()["items"]
        if item["id"] == meeting.meeting_id
    )
    assert readded_item["viewer_capabilities"]["can_manage"] is True


def test_demoted_facilitator_loses_control_across_meetings_and_page_controls(
    client: TestClient,
    db_session,
    user_manager_with_admin: UserManager,
):
    """Lobster Teacup: demotion authority revocation removes visible controls and backend meeting powers across meetings."""
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    assert admin_user is not None

    facilitator_password = "DemoteFac1!"
    facilitator_user = user_manager_with_admin.add_user(
        first_name="Demoted",
        last_name="Facilitator",
        email="demoted.facilitator@example.com",
        hashed_password=get_password_hash(facilitator_password),
        role=UserRole.FACILITATOR.value,
        login="demoted_facilitator",
    )
    db_session.commit()
    db_session.refresh(facilitator_user)

    meeting_manager = MeetingManager(db_session)
    meeting_ids = []
    for index in range(2):
        meeting_payload = MeetingCreate(
            title=f"Demotion Meeting {index + 1}",
            description="Verify role change propagation",
            start_time=datetime.now(UTC) + timedelta(hours=2 + index),
            duration_minutes=30,
            publicity=PublicityType.PUBLIC,
            owner_id=admin_user.user_id,
            participant_ids=[facilitator_user.user_id],
            additional_facilitator_ids=[facilitator_user.user_id],
        )
        meeting = meeting_manager.create_meeting(
            meeting_payload,
            admin_user.user_id,
            agenda_items=[AgendaActivityCreate(tool_type="brainstorming", title="Kickoff")],
        )
        assert meeting is not None
        meeting_ids.append((meeting.meeting_id, meeting.agenda_activities[0].activity_id))

    login_response = client.post(
        "/api/auth/token",
        json={"username": facilitator_user.login, "password": facilitator_password},
    )
    assert login_response.status_code == 200, login_response.text

    pre_demote_control = client.post(
        f"/api/meetings/{meeting_ids[0][0]}/control",
        json={"action": "start_tool", "tool": "brainstorming", "activityId": meeting_ids[0][1]},
    )
    assert pre_demote_control.status_code == 200, pre_demote_control.json()

    updated_user = user_manager_with_admin.update_user_role(
        facilitator_user.login,
        UserRole.PARTICIPANT.value,
    )
    assert updated_user is not None
    assert updated_user.role == UserRole.PARTICIPANT.value

    meeting_page = client.get(f"/meeting/{meeting_ids[0][0]}")
    assert meeting_page.status_code == 200, meeting_page.text
    assert "Meeting Roster" not in meeting_page.text
    assert "Meeting Settings" not in meeting_page.text
    assert 'data-view-mode="participant"' in meeting_page.text

    dashboard_response = client.get("/api/meetings/")
    assert dashboard_response.status_code == 200, dashboard_response.json()
    for meeting_id, _activity_id in meeting_ids:
        item = next(
            item
            for item in dashboard_response.json()["items"]
            if item["id"] == meeting_id
        )
        assert item["viewer_capabilities"]["can_manage"] is False
        assert item["viewer_capabilities"]["can_delete"] is False
        assert item["viewer_capabilities"]["is_facilitator"] is False
        assert item["viewer_capabilities"]["is_participant"] is True

    for meeting_id, activity_id in meeting_ids:
        control_attempt = client.post(
            f"/api/meetings/{meeting_id}/control",
            json={"action": "start_tool", "tool": "brainstorming", "activityId": activity_id},
        )
        assert control_attempt.status_code == 403, control_attempt.json()


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
