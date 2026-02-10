from __future__ import annotations

from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)

from ..database import Base


def _uuid_str() -> str:
    return str(uuid4())


class CategorizationItem(Base):
    __tablename__ = "categorization_items"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "activity_id",
            "item_key",
            name="uq_categorization_item_key",
        ),
    )

    item_row_id = Column(String(36), primary_key=True, default=_uuid_str)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id = Column(String(32), nullable=False, index=True)
    item_key = Column(String(128), nullable=False)
    content = Column(Text, nullable=False)
    submitted_name = Column(String(200), nullable=True)
    parent_item_key = Column(String(128), nullable=True, index=True)
    item_metadata = Column(JSON, default=dict, nullable=False)
    source = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CategorizationBucket(Base):
    __tablename__ = "categorization_buckets"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "activity_id",
            "category_id",
            name="uq_categorization_bucket_id",
        ),
    )

    bucket_row_id = Column(String(36), primary_key=True, default=_uuid_str)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id = Column(String(32), nullable=False, index=True)
    category_id = Column(String(64), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="active")
    created_by = Column(
        String(20),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CategorizationAssignment(Base):
    __tablename__ = "categorization_assignments"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "activity_id",
            "item_key",
            name="uq_categorization_assignment_item",
        ),
    )

    assignment_id = Column(String(36), primary_key=True, default=_uuid_str)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id = Column(String(32), nullable=False, index=True)
    item_key = Column(String(128), nullable=False, index=True)
    category_id = Column(String(64), nullable=False, index=True, default="UNSORTED")
    is_unsorted = Column(Boolean, nullable=False, default=True)
    assigned_by = Column(
        String(20),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CategorizationBallot(Base):
    __tablename__ = "categorization_ballots"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "activity_id",
            "user_id",
            "item_key",
            name="uq_categorization_ballot_item",
        ),
    )

    ballot_id = Column(String(36), primary_key=True, default=_uuid_str)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id = Column(String(32), nullable=False, index=True)
    user_id = Column(
        String(20),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_key = Column(String(128), nullable=False, index=True)
    category_id = Column(String(64), nullable=True, index=True)
    submitted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CategorizationFinalAssignment(Base):
    __tablename__ = "categorization_final_assignments"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "activity_id",
            "item_key",
            name="uq_categorization_final_item",
        ),
    )

    final_assignment_id = Column(String(36), primary_key=True, default=_uuid_str)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id = Column(String(32), nullable=False, index=True)
    item_key = Column(String(128), nullable=False, index=True)
    category_id = Column(String(64), nullable=False, index=True)
    resolved_by = Column(
        String(20),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_at = Column(DateTime(timezone=True), server_default=func.now())


class CategorizationAuditEvent(Base):
    __tablename__ = "categorization_audit_events"

    event_id = Column(String(36), primary_key=True, default=_uuid_str)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id = Column(String(32), nullable=False, index=True)
    actor_user_id = Column(
        String(20),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
