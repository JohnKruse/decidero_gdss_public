from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import relationship

from ..database import Base


class MeetingTemplate(Base):
    __tablename__ = "meeting_templates"

    template_id = Column(String(64), primary_key=True, index=True)
    source = Column(String(16), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="active", index=True)
    name = Column(String(200), nullable=False, index=True)
    purpose = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    estimated_duration_minutes = Column(Integer, nullable=True)
    min_participants = Column(Integer, nullable=True)
    max_participants = Column(Integer, nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    flow_type = Column(String(32), nullable=False, default="linear", index=True)
    template_version = Column(Integer, nullable=False, default=1)
    built_in_key = Column(String(80), nullable=True, unique=True, index=True)
    created_by_user_id = Column(
        String(20),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contract_version = Column(Integer, nullable=False, default=1)
    template_payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    creator = relationship("User")
