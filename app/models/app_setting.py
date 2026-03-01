"""
SQLAlchemy model for the app_settings table.

Stores runtime-configurable settings as JSON-encoded key-value pairs.
Keys use dot-notation namespacing (e.g. "ai.api_key", "brainstorming.idea_character_limit").
Sensitive values (API keys, passwords) are stored with an "enc:" prefix by the settings_store
layer — raw values here are always treated as opaque text.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text

from app.database import Base


class AppSetting(Base):
    """Persistent runtime-configurable key/value settings store."""

    __tablename__ = "app_settings"

    key = Column(String(128), primary_key=True, nullable=False)
    # JSON-encoded value; sensitive keys are prefixed with "enc:" and Fernet-encrypted.
    value = Column(Text, nullable=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # user_id of the admin/facilitator who last wrote this setting
    updated_by = Column(String(20), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AppSetting key={self.key!r} updated_by={self.updated_by!r}>"
