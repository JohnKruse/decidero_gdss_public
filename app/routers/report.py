"""Report download endpoints.

Plainspoken Marmot: downloads are pure renderings of the stored canonical report
payload. The endpoint never rebuilds report data from meeting state.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.auth import get_current_user
from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.data.user_manager import UserManager, get_user_manager
from app.database import get_db
from app.models.meeting import AgendaActivity
from app.services.meeting_authorization import resolve_meeting_capabilities
from app.services.report_renderers import (
    render_csv,
    render_docx,
    render_html,
    render_json,
    render_markdown,
)

router = APIRouter(prefix="/api/meetings", tags=["reports"])


Renderer = Callable[[Dict[str, Any]], str | bytes]

_FORMAT_RENDERERS: Dict[str, Tuple[str, str, Renderer]] = {
    "json": ("application/json", "json", render_json),
    "md": ("text/markdown; charset=utf-8", "md", render_markdown),
    "csv": ("text/csv; charset=utf-8", "csv", render_csv),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
        render_docx,
    ),
}


def _assert_report_download_access(meeting, user) -> None:
    capabilities = resolve_meeting_capabilities(meeting, user)
    if not capabilities["can_manage"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only facilitators can download meeting reports.",
        )


def _report_payload_from_bundle(
    bundle_manager: ActivityBundleManager,
    *,
    meeting_id: str,
    activity_id: str,
) -> Dict[str, Any]:
    bundle = bundle_manager.get_latest_bundle(meeting_id, activity_id, "output")
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report output is not available yet.",
        )
    payload = (bundle.bundle_metadata or {}).get("report_payload")
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report output is missing its canonical payload.",
        )
    return payload


@router.get("/{meeting_id}/activities/{activity_id}/report.{format}")
async def download_report(
    meeting_id: str,
    activity_id: str,
    format: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
    db: Session = Depends(get_db),
):
    format_key = format.lower()
    renderer_info = _FORMAT_RENDERERS.get(format_key)
    if renderer_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unsupported report format.",
        )

    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    _assert_report_download_access(meeting, user)

    activity = (
        db.query(AgendaActivity)
        .filter(
            AgendaActivity.meeting_id == meeting_id,
            AgendaActivity.activity_id == activity_id,
        )
        .first()
    )
    if activity is None or activity.tool_type != "report":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report activity not found.",
        )

    report = _report_payload_from_bundle(
        ActivityBundleManager(db),
        meeting_id=meeting_id,
        activity_id=activity_id,
    )
    media_type, extension, renderer = renderer_info
    rendered = renderer(report)
    body = rendered if isinstance(rendered, bytes) else rendered.encode("utf-8")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"meeting_{meeting_id}_{activity_id}_report_{timestamp}.{extension}"
    return StreamingResponse(
        io.BytesIO(body),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{meeting_id}/activities/{activity_id}/report/preview")
async def preview_report(
    meeting_id: str,
    activity_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
    db: Session = Depends(get_db),
):
    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    _assert_report_download_access(meeting, user)

    activity = (
        db.query(AgendaActivity)
        .filter(
            AgendaActivity.meeting_id == meeting_id,
            AgendaActivity.activity_id == activity_id,
        )
        .first()
    )
    if activity is None or activity.tool_type != "report":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report activity not found.",
        )

    report = _report_payload_from_bundle(
        ActivityBundleManager(db),
        meeting_id=meeting_id,
        activity_id=activity_id,
    )
    return StreamingResponse(
        io.BytesIO(render_html(report).encode("utf-8")),
        media_type="text/html; charset=utf-8",
    )
