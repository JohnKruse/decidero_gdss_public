from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from ..database import Base


def generate_vote_id() -> str:
    return str(uuid4())


class VotingVote(Base):
    __tablename__ = "voting_votes"

    vote_id = Column(String(36), primary_key=True, default=generate_vote_id)
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
    option_id = Column(String(64), nullable=False)
    option_label = Column(String(255), nullable=False)
    weight = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
