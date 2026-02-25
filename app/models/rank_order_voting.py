from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from ..database import Base


def generate_rank_vote_id() -> str:
    return str(uuid4())


class RankOrderVote(Base):
    __tablename__ = "rank_order_votes"

    rank_vote_id = Column(String(36), primary_key=True, default=generate_rank_vote_id)
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
    option_id = Column(String(96), nullable=False, index=True)
    option_label = Column(String(255), nullable=False)
    rank_position = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
