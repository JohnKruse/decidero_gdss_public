from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship
from app.database import Base
from enum import Enum

from app.models.meeting import MeetingFacilitator

meeting_facilitators_table = MeetingFacilitator.__table__


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    FACILITATOR = "facilitator"
    PARTICIPANT = "participant"


class User(Base):
    __tablename__ = "users"

    user_id = Column(String(20), primary_key=True, index=True)
    legacy_user_id = Column(Integer, unique=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    login = Column(
        String, unique=True, index=True, nullable=False
    )  # Login is required and unique
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    role = Column(String, default=UserRole.PARTICIPANT.value, nullable=False)
    password_changed = Column(Boolean, default=False)
    avatar_color = Column(String(7), nullable=True, index=True)
    avatar_key = Column(String(128), nullable=True, index=True)
    avatar_seed = Column(Integer, nullable=False, default=0)
    profile_svg = Column(String, nullable=True)
    about_me = Column(String, nullable=True)
    organization = Column(String, nullable=True)
    # Email verification is currently disabled; default all users to verified.
    is_verified = Column(Boolean, default=True)
    verification_token = Column(String, nullable=True, index=True)

    # Meetings this user owns (primary facilitator/creator)
    owned_meetings = relationship(
        "Meeting",
        back_populates="owner",
        foreign_keys="Meeting.owner_id",
    )

    facilitator_links = relationship(
        "MeetingFacilitator",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # Meetings where this user is assigned as a facilitator (owner or co-facilitator)
    facilitated_meetings = relationship(
        "Meeting",
        secondary=meeting_facilitators_table,
        viewonly=True,
        overlaps="facilitator_links,facilitators,owned_meetings",
    )

    # Relationship to Meetings this user participates in (defined in Meeting model via participants_table)
    meetings = relationship(
        "Meeting",
        secondary="participants",
        back_populates="participants",
        primaryjoin="User.user_id==participants.c.user_id",
    )

    @property
    def avatar_icon_path(self) -> str | None:
        from app.services.avatar_catalog import get_avatar_path

        return get_avatar_path(getattr(self, "avatar_key", None))
