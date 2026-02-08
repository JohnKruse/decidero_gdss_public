from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func  # For default timestamps

from ..database import Base

# Association table linking users to meetings as participants (attendees)
participants_table = Table(
    "participants",
    Base.metadata,
    Column("user_id", String(20), ForeignKey("users.user_id"), primary_key=True),
    Column(
        "meeting_id",
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("joined_at", DateTime(timezone=True), server_default=func.now()),
)


class Meeting(Base):
    __tablename__ = "meetings"

    meeting_id = Column(String(20), primary_key=True, index=True)
    legacy_meeting_id = Column(Integer, unique=True, nullable=True)
    title = Column(String, index=True)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    status = Column(String, default="active")  # e.g., 'active', 'archived', 'completed'
    is_public = Column(Boolean, default=False)

    # Primary owner of the meeting (creator/facilitator with elevated permissions)
    owner_id = Column(String(20), ForeignKey("users.user_id"), nullable=False)

    owner = relationship(
        "User",
        back_populates="owned_meetings",
        foreign_keys=[owner_id],
    )

    facilitator_links = relationship(
        "MeetingFacilitator",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )

    facilitators = relationship(
        "User",
        secondary="meeting_facilitators",
        viewonly=True,
        back_populates="facilitated_meetings",
        overlaps="facilitator_links,facilitated_meetings,owned_meetings,owner",
    )

    participants = relationship(
        "User",
        secondary=participants_table,
        back_populates="meetings",
        primaryjoin="Meeting.meeting_id==participants.c.meeting_id",
        secondaryjoin="User.user_id==participants.c.user_id",
    )

    ideas = relationship(
        "Idea",
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    agendas = relationship("Agenda", back_populates="meeting")
    tool_configs = relationship("ToolConfig", back_populates="meeting")
    agenda_activities = relationship(
        "AgendaActivity",
        order_by="AgendaActivity.order_index",
        cascade="all, delete-orphan",
        back_populates="meeting",
    )

    @property
    def agenda(self):
        return list(self.agenda_activities or [])


class MeetingFacilitator(Base):
    __tablename__ = "meeting_facilitators"
    __table_args__ = (
        UniqueConstraint(
            "facilitator_id", name="uq_meeting_facilitators_facilitator_id"
        ),
        UniqueConstraint("meeting_id", "user_id", name="uq_meeting_facilitators_user"),
    )

    facilitator_id = Column(String(20), primary_key=True, index=True)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        String(20), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    is_owner = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    meeting = relationship(
        "Meeting",
        back_populates="facilitator_links",
        foreign_keys=[meeting_id],
    )
    user = relationship(
        "User", back_populates="facilitator_links", foreign_keys=[user_id]
    )


meeting_facilitators_table = MeetingFacilitator.__table__


class ToolConfig(Base):
    __tablename__ = "tool_configs"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_type = Column(String)  # e.g., "whiteboard", "voting", "timer"
    config = Column(String)  # JSON string containing tool-specific configuration

    meeting = relationship("Meeting", back_populates="tool_configs")


class Agenda(Base):
    __tablename__ = "agendas"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic = Column(String, index=True)
    description = Column(String)
    duration = Column(Integer)  # Duration in minutes
    order = Column(Integer)  # Order of the agenda item

    meeting = relationship("Meeting", back_populates="agendas")

    def __repr__(self):
        return f"Agenda(id={self.id}, topic='{self.topic}', duration={self.duration}, order={self.order})"


class AgendaActivity(Base):
    __tablename__ = "agenda_activities"
    __table_args__ = (
        UniqueConstraint("meeting_id", "order_index", name="uq_agenda_activity_order"),
        UniqueConstraint("meeting_id", "activity_id", name="uq_agenda_activity_id"),
    )

    activity_id = Column(String(32), primary_key=True, index=True)
    meeting_id = Column(
        String(20),
        ForeignKey("meetings.meeting_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    instructions = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False)
    tool_config_id = Column(String(48), unique=True, nullable=False)
    config = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    elapsed_duration = Column(
        Integer, default=0, nullable=False
    )  # New column for accumulated seconds

    meeting = relationship("Meeting", back_populates="agenda_activities")

    def __repr__(self) -> str:
        return (
            f"AgendaActivity(activity_id={self.activity_id!r}, "
            f"tool_type={self.tool_type!r}, order_index={self.order_index})"
        )
