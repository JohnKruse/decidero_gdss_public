from sqlalchemy import Column, DateTime, Integer, JSON, String, func

from ..database import Base


class ActivityBundle(Base):
    __tablename__ = "activity_bundles"

    id = Column(Integer, primary_key=True, index=True)
    bundle_id = Column(String(36), unique=True, nullable=False, index=True)
    meeting_id = Column(String(20), nullable=False, index=True)
    activity_id = Column(String(32), nullable=False, index=True)
    kind = Column(String(16), nullable=False, index=True)  # input, draft, output
    items = Column(JSON, nullable=False, default=list)
    bundle_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
