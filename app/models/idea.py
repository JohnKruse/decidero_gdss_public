from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func  # For default timestamps
from ..database import Base


class Idea(Base):
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    parent_id = Column(
        Integer,
        ForeignKey("ideas.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id = Column(String(32), nullable=True, index=True)
    user_id = Column(String(20), ForeignKey("users.user_id"), nullable=True, index=True)
    submitted_name = Column(String(200), nullable=True)
    idea_metadata = Column(JSON, default=dict, nullable=False)

    meeting = relationship("Meeting", back_populates="ideas")
    author = relationship("User")
    parent = relationship("Idea", remote_side=[id], backref="subcomments")
