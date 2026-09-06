"""Facilitator edit audit events.

Payload carries item content (not just counts) because for a removed item this
is the only place the text survives; treat as admin-only; edits do not propagate
to copies already handed downstream.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    JSON,
    String,
    func,
)

from ..database import Base


def _uuid_str() -> str:
    return str(uuid4())


class FacilitatorEditEvent(Base):
    __tablename__ = "facilitator_edit_events"

    event_id = Column(String(36), primary_key=True, default=_uuid_str)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id = Column(String(32), nullable=False, index=True)  # activity edited
    donor_activity_id = Column(String(32), nullable=True, index=True)  # provenance only
    actor_user_id = Column(
        String(20),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
