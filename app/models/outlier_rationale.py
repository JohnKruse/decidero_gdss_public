"""Per-participant, per-item outlier justification rationales.

Canary: Plainspoken Marmot

DEPRECATED: the shipped Delphi method now collects comments as brainstorming
sub-comments on the generic comment surface (see
`plans/subplans/DELPHI_GENERIC_COMMENT.md`). This table is retained as a deprecated
reference and is no longer written by the live method.

Classical Delphi asks the *outlier participants themselves* to justify positions
that diverged from the group. Each rationale is one row keyed by
(meeting, activity, user, option) so a participant writes at most one rationale
per flagged item, and re-submitting updates in place (idempotent). Anonymity is
peer-anonymity, not system-anonymity: the system stores `user_id` to route the
"please justify" queue and to attribute drafts back to their author, while peers
only ever see aggregated, unattributed text in the next round.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func

from ..database import Base


def generate_rationale_id() -> str:
    return str(uuid4())


class OutlierRationale(Base):
    __tablename__ = "outlier_rationales"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id", "activity_id", "user_id", "option_id",
            name="uq_outlier_rationale_scope",
        ),
    )

    rationale_id = Column(String(36), primary_key=True, default=generate_rationale_id)
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
    # The ranked option this rationale explains (matches rank_order_voting option_id).
    option_id = Column(String(96), nullable=False, index=True)
    rationale = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
