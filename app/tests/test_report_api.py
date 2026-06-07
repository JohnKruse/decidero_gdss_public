"""Report download API coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_manager import MeetingManager
from app.data.user_manager import UserManager
from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity
from app.models.user import User, UserRole
from app.schemas.meeting import MeetingCreate, PublicityType
from app.utils.security import get_password_hash


def _report_payload():
    return {
        "report_version": "1.0",
        "title": "Plainspoken Marmot Report",
        "meeting": {
            "meeting_id": "fixture",
            "title": "Report API",
            "method": {"name": "Classical Delphi", "version": "1.0"},
            "round_count": 1,
        },
        "generated_at": "2026-06-07T12:00:00+00:00",
        "sections": [
            {
                "id": "overview",
                "type": "narrative",
                "title": "Overview",
                "body": {
                    "markdown": "The group converged on Idea A.",
                    "ai_drafted": False,
                },
            },
            {
                "id": "trajectory",
                "type": "table",
                "title": "Trajectory",
                "body": {
                    "columns": [
                        {"key": "rank", "label": "Final rank"},
                        {"key": "item", "label": "Item"},
                    ],
                    "rows": [
                        {"rank": 1, "item": "Idea A"},
                        {"rank": 2, "item": "Idea B"},
                    ],
                },
            },
        ],
    }


def _meeting_with_report(db_session):
    admin = db_session.query(User).filter(User.role == UserRole.ADMIN.value).first()
    manager = MeetingManager(db_session)
    start = datetime.now(UTC) + timedelta(minutes=5)
    meeting = manager.create_meeting(
        meeting_data=MeetingCreate(
            title="Report API",
            description="download endpoint fixture",
            start_time=start,
            end_time=start + timedelta(minutes=30),
            duration_minutes=30,
            publicity=PublicityType.PRIVATE,
            owner_id=admin.user_id,
            participant_ids=[],
            additional_facilitator_ids=[],
        ),
        facilitator_id=admin.user_id,
        agenda_items=[],
    )
    activity = AgendaActivity(
        activity_id=f"{meeting.meeting_id}-REPORT-0001",
        meeting_id=meeting.meeting_id,
        tool_type="report",
        title="Final Report",
        order_index=1,
        tool_config_id=f"{meeting.meeting_id}-CFG-REPORT-0001",
        config={},
    )
    db_session.add(activity)
    db_session.commit()
    ActivityBundleManager(db_session).finalize_output_bundle(
        meeting.meeting_id,
        activity.activity_id,
        items=[{"content": "Idea A", "metadata": {"rank": 1}}],
        metadata={"report": True, "report_payload": _report_payload()},
    )
    return meeting, activity


def test_report_downloads_render_each_supported_format(
    authenticated_client: TestClient,
    db_session,
):
    meeting, activity = _meeting_with_report(db_session)

    json_response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/activities/{activity.activity_id}/report.json"
    )
    assert json_response.status_code == 200, json_response.text
    assert json_response.headers["content-type"].startswith("application/json")
    assert json_response.json()["title"] == "Plainspoken Marmot Report"
    assert "Content-Disposition" in json_response.headers

    md_response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/activities/{activity.activity_id}/report.md"
    )
    assert md_response.status_code == 200, md_response.text
    assert md_response.headers["content-type"].startswith("text/markdown")
    assert "# Plainspoken Marmot Report" in md_response.text

    csv_response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/activities/{activity.activity_id}/report.csv"
    )
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "Final rank,Item" in csv_response.text
    assert "1,Idea A" in csv_response.text
    assert "2,Idea B" in csv_response.text

    docx_response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/activities/{activity.activity_id}/report.docx"
    )
    assert docx_response.status_code == 200, docx_response.text
    assert docx_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx_response.content.startswith(b"PK")


def test_report_preview_returns_html_from_stored_payload(
    authenticated_client: TestClient,
    db_session,
):
    meeting, activity = _meeting_with_report(db_session)

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/activities/{activity.activity_id}/report/preview"
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "Plainspoken Marmot Report" in response.text
    assert "Idea A" in response.text


def test_report_download_requires_report_output(
    authenticated_client: TestClient,
    db_session,
):
    meeting, activity = _meeting_with_report(db_session)
    db_session.query(ActivityBundle).filter(
        ActivityBundle.meeting_id == meeting.meeting_id,
        ActivityBundle.activity_id == activity.activity_id,
        ActivityBundle.kind == "output",
    ).delete()
    db_session.commit()

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/activities/{activity.activity_id}/report.json"
    )
    assert response.status_code == 404
    assert "not available" in response.json()["detail"]


def test_report_download_rejects_unsupported_format(
    authenticated_client: TestClient,
    db_session,
):
    meeting, activity = _meeting_with_report(db_session)

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/activities/{activity.activity_id}/report.pdf"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Unsupported report format."


def test_report_download_is_facilitator_only_for_now(
    client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    meeting, activity = _meeting_with_report(db_session)
    participant_password = "ReportUser1!"
    participant = user_manager_with_admin.add_user(
        first_name="Report",
        last_name="Participant",
        email="report.participant@example.com",
        hashed_password=get_password_hash(participant_password),
        role="participant",
        login="report_participant",
    )
    meeting.participants.append(participant)
    db_session.add(meeting)
    db_session.commit()

    login = client.post(
        "/api/auth/token",
        json={"username": participant.login, "password": participant_password},
    )
    assert login.status_code == 200

    response = client.get(
        f"/api/meetings/{meeting.meeting_id}/activities/{activity.activity_id}/report.json"
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Only facilitators can download meeting reports."
