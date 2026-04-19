from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.database import Base


def _uuid_str() -> str:
    return str(uuid4())


class MeetingDesignerLog(Base):
    """Audit trail for AI Meeting Designer interactions and generation attempts."""

    __tablename__ = "meeting_designer_logs"

    log_id = Column(String(36), primary_key=True, default=_uuid_str)
    event_type = Column(String(32), nullable=False, index=True)

    user_id = Column(
        String(20),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_login = Column(String(120), nullable=False, index=True)

    provider = Column(String(64), nullable=True, index=True)
    model = Column(String(160), nullable=True, index=True)

    request_messages = Column(JSON, default=list, nullable=False)
    new_message = Column(Text, nullable=True)
    assistant_response = Column(Text, nullable=True)
    raw_output = Column(Text, nullable=True)
    parsed_output = Column(JSON, default=dict, nullable=True)
    error_detail = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
