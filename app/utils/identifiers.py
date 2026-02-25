import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.meeting import Meeting, MeetingFacilitator, AgendaActivity

USER_ID_PREFIX = "USR"
USER_ID_SEQUENCE_WIDTH = 3
USER_ID_STEM_LENGTH = 6

MEETING_ID_PREFIX = "MTG"
MEETING_ID_SUFFIX_WIDTH = 4

FACILITATOR_ID_PREFIX = "FAC"
FACILITATOR_ID_SEQUENCE_WIDTH = 3
FACILITATOR_ID_STEM_LENGTH = 6

ACTIVITY_SEQUENCE_WIDTH = 4
TOOL_CONFIG_SEQUENCE_WIDTH = 2

DEFAULT_ACTIVITY_PREFIX = "ACTVT"
ACTIVITY_TYPE_PREFIXES = {
    "brainstorming": "BRAINS",
    "voting": "RANKVT",
    "rank_order_voting": "RANKOR",
    "categorization": "CATGRY",
    "prioritization": "PRIORI",
    "discussion": "DISCUS",
}


def _clean_stem(value: Optional[str]) -> str:
    """
    Normalise the last name into a six-character uppercase stem.
    Non-alphanumeric characters are stripped and the result padded with X.
    """
    if not value:
        cleaned = ""
    else:
        cleaned = re.sub(r"[^A-Z0-9]", "", value.upper())
    if not cleaned:
        cleaned = "X" * USER_ID_STEM_LENGTH
    return (cleaned[:USER_ID_STEM_LENGTH]).ljust(USER_ID_STEM_LENGTH, "X")


def _clean_initial(value: Optional[str]) -> str:
    """Return the uppercase first initial or 'X' when unavailable."""
    if not value:
        return "X"
    cleaned = re.sub(r"[^A-Z0-9]", "", value.upper())
    return cleaned[0] if cleaned else "X"


def build_user_id_prefix(first_name: Optional[str], last_name: Optional[str]) -> str:
    stem = _clean_stem(last_name)
    initial = _clean_initial(first_name)
    return f"{USER_ID_PREFIX}-{stem}{initial}"


def _next_sequence_for_prefix(db: Session, prefix: str) -> int:
    """
    Determine the next numeric sequence for the given prefix.
    The prefix is expected without the trailing dash (e.g., 'USR-ADKINSJ').
    """
    like_pattern = f"{prefix}-%"
    existing = (
        db.query(User.user_id)
        .filter(User.user_id.like(like_pattern))
        .order_by(User.user_id.desc())
        .limit(1)
        .scalar()
    )
    if not existing:
        return 1
    try:
        return int(existing.split("-")[-1]) + 1
    except (ValueError, IndexError):
        # Fallback to avoid blocking user creation even if legacy data is malformed.
        return 1


def generate_user_id(
    db: Session, first_name: Optional[str], last_name: Optional[str]
) -> str:
    """
    Construct a unique `user_id` following the USR-LLLLLLF-NNN pattern.
    The sequence component increments per prefix to avoid collisions.
    """
    prefix = build_user_id_prefix(first_name, last_name)
    sequence = _next_sequence_for_prefix(db, prefix)
    return f"{prefix}-{sequence:0{USER_ID_SEQUENCE_WIDTH}d}"


def _format_base36(number: int) -> str:
    if number < 0:
        raise ValueError("number must be non-negative")
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if number == 0:
        return "0"
    result = []
    while number:
        number, remainder = divmod(number, 36)
        result.append(digits[remainder])
    return "".join(reversed(result))


def _next_meeting_sequence(db: Session, date_prefix: str) -> int:
    like_pattern = f"{date_prefix}-%"
    latest: Optional[str] = (
        db.query(Meeting.meeting_id)
        .filter(Meeting.meeting_id.like(like_pattern))
        .order_by(Meeting.meeting_id.desc())
        .limit(1)
        .scalar()
    )
    if not latest:
        return 1
    try:
        suffix = latest.split("-")[-1]
        return int(suffix, 36) + 1
    except (ValueError, IndexError):
        return 1


def generate_meeting_id(db: Session, created_at: Optional[datetime] = None) -> str:
    """
    Construct a unique meeting identifier with the format MTGYYYYMMDD-XXXX
    where the suffix is a zero-padded base36 sequence scoped to the given day.
    """
    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    date_prefix = f"{MEETING_ID_PREFIX}{timestamp:%Y%m%d}"
    sequence = _next_meeting_sequence(db, date_prefix)
    suffix = _format_base36(sequence).upper().rjust(MEETING_ID_SUFFIX_WIDTH, "0")
    return f"{date_prefix}-{suffix}"


def _next_facilitator_sequence(db: Session, prefix: str) -> int:
    like_pattern = f"{prefix}-%"
    latest: Optional[str] = (
        db.query(MeetingFacilitator.facilitator_id)
        .filter(MeetingFacilitator.facilitator_id.like(like_pattern))
        .order_by(MeetingFacilitator.facilitator_id.desc())
        .limit(1)
        .scalar()
    )
    if not latest:
        return 1
    try:
        return int(latest.split("-")[-1]) + 1
    except (ValueError, IndexError):
        return 1


def generate_facilitator_id(
    db: Session,
    first_name: Optional[str],
    last_name: Optional[str],
) -> str:
    """
    Construct a facilitator roster identifier following FAC-LLLLLLF-NNN.
    The sequence is global per stem/initial combination to maintain readability.
    """
    stem = _clean_stem(last_name)[:FACILITATOR_ID_STEM_LENGTH]
    initial = _clean_initial(first_name)
    prefix = f"{FACILITATOR_ID_PREFIX}-{stem}{initial}"
    sequence = _next_facilitator_sequence(db, prefix)
    return f"{prefix}-{sequence:0{FACILITATOR_ID_SEQUENCE_WIDTH}d}"


def derive_activity_prefix(tool_type: str) -> str:
    normalised = (tool_type or "").strip().lower()
    if not normalised:
        return DEFAULT_ACTIVITY_PREFIX
    prefix = ACTIVITY_TYPE_PREFIXES.get(normalised)
    if prefix:
        return prefix
    cleaned = re.sub(r"[^A-Z0-9]", "", normalised.upper())
    if not cleaned:
        return DEFAULT_ACTIVITY_PREFIX
    if len(cleaned) >= 6:
        return cleaned[:6]
    return cleaned.ljust(6, "X")


def _next_activity_sequence(db: Session, meeting_id: str, prefix: str) -> int:
    like_pattern = f"{meeting_id}-{prefix}-%"
    latest: Optional[str] = (
        db.query(AgendaActivity.activity_id)
        .filter(
            AgendaActivity.meeting_id == meeting_id,
            AgendaActivity.activity_id.like(like_pattern),
        )
        .order_by(AgendaActivity.activity_id.desc())
        .limit(1)
        .scalar()
    )
    if not latest:
        return 1
    try:
        return int(latest.split("-")[-1]) + 1
    except (ValueError, IndexError):
        return 1


def generate_activity_id(db: Session, meeting_id: str, tool_type: str) -> str:
    """
    Generate an agenda activity identifier following the pattern STEM-NNNN where
    the stem is derived from the tool type and the sequence is local to the meeting.
    """
    prefix = derive_activity_prefix(tool_type)
    safe_meeting = (meeting_id or "").strip() or MEETING_ID_PREFIX
    sequence = _next_activity_sequence(db, safe_meeting, prefix)
    return f"{safe_meeting}-{prefix}-{sequence:0{ACTIVITY_SEQUENCE_WIDTH}d}"


def generate_tool_config_id(
    activity_id: str,
    meeting_id: Optional[str] = None,
    sequence: int = 1,
) -> str:
    """
    Generate a tool configuration identifier linked to the given meeting and activity.

    The activity_id is used to keep configurations grouped with their agenda item.
    """
    safe_activity = (activity_id or DEFAULT_ACTIVITY_PREFIX).strip()
    if not safe_activity:
        safe_activity = DEFAULT_ACTIVITY_PREFIX
    if meeting_id:
        safe_meeting = str(meeting_id).strip()
        if safe_meeting and not safe_activity.startswith(f"{safe_meeting}-"):
            return (
                f"TL-{safe_meeting}-{safe_activity}-"
                f"{sequence:0{TOOL_CONFIG_SEQUENCE_WIDTH}d}"
            )
    return f"TL-{safe_activity}-{sequence:0{TOOL_CONFIG_SEQUENCE_WIDTH}d}"
