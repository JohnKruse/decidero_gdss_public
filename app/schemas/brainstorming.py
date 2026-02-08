from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BrainstormingIdeaCreate(BaseModel):
    content: str = Field(..., min_length=1)
    submitted_name: Optional[str] = Field(default=None, max_length=200)
    parent_id: Optional[int] = Field(default=None)
    metadata: Optional[dict] = Field(default=None)


class BrainstormingIdeaResponse(BaseModel):
    id: int
    meeting_id: str
    activity_id: Optional[str] = None
    user_id: Optional[str] = None
    user_color: Optional[str] = None
    user_avatar_key: Optional[str] = None
    user_avatar_icon_path: Optional[str] = None
    submitted_name: Optional[str] = None
    content: str
    parent_id: Optional[int] = None
    metadata: Optional[dict] = Field(
        default=None,
        validation_alias="idea_metadata",
        serialization_alias="metadata",
    )
    timestamp: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
