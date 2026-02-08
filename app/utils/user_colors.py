from __future__ import annotations

from typing import Optional, Any

from sqlalchemy.orm import Session


def get_user_color(
    user_id: Optional[str] = None,
    *,
    user: Optional[Any] = None,
    db: Optional[Session] = None,
) -> Optional[str]:
    """Resolve a persisted avatar color from user object or user_id."""
    direct = getattr(user, "avatar_color", None) if user is not None else None
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    if not user_id or db is None:
        return None

    from app.models.user import User

    row = db.query(User.avatar_color).filter(User.user_id == user_id).first()
    if not row:
        return None
    color = row[0]
    if isinstance(color, str) and color.strip():
        return color.strip()
    return None
