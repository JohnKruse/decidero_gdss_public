from datetime import datetime, timedelta, UTC

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import relationship

from ..database import Base


class BrainstormingIdempotencyKey(Base):
    __tablename__ = "brainstorming_idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "activity_id",
            "user_id",
            "idempotency_key",
            name="uq_brainstorming_idempotency_scope",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(String(20), nullable=False, index=True)
    activity_id = Column(String(32), nullable=False, index=True)
    user_id = Column(String(20), ForeignKey("users.user_id"), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False, index=True)
    request_hash = Column(String(64), nullable=False, index=True)
    status_code = Column(Integer, nullable=True)
    response_payload = Column(JSON, nullable=True)
    idea_id = Column(Integer, ForeignKey("ideas.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    expires_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC) + timedelta(days=2),
        nullable=False,
        index=True,
    )

    idea = relationship("Idea")
