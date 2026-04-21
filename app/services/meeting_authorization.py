from dataclasses import asdict, dataclass
from typing import Any, Optional

from app.models.meeting import Meeting
from app.models.user import User, UserRole


@dataclass(frozen=True)
class MeetingCapabilities:
    """Canonical backend meeting capability model for meeting-scoped authorization."""

    is_admin: bool
    is_owner: bool
    is_roster_participant: bool
    has_facilitator_role: bool
    is_facilitator: bool
    can_view: bool
    can_manage: bool
    can_edit_meeting: bool
    can_manage_roster: bool
    can_control_activity: bool
    can_manage_activity_roster: bool
    can_delete: bool

    @property
    def is_participant(self) -> bool:
        return self.is_roster_participant

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_role_value(user: Optional[User]) -> Optional[str]:
    role_value = getattr(user, "role", None)
    if isinstance(role_value, UserRole):
        return role_value.value
    return role_value


def resolve_meeting_capabilities(
    meeting: Meeting,
    user: Optional[User],
) -> MeetingCapabilities:
    """
    Gravy Parachute: derive meeting-scoped backend capabilities from role,
    ownership, and roster membership only.
    """
    if user is None:
        return MeetingCapabilities(
            is_admin=False,
            is_owner=False,
            is_roster_participant=False,
            has_facilitator_role=False,
            is_facilitator=False,
            can_view=False,
            can_manage=False,
            can_edit_meeting=False,
            can_manage_roster=False,
            can_control_activity=False,
            can_manage_activity_roster=False,
            can_delete=False,
        )

    role_value = _normalize_role_value(user)
    user_id = getattr(user, "user_id", None)

    is_admin = role_value in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}
    is_owner = getattr(meeting, "owner_id", None) == user_id
    participant_ids = {
        getattr(participant, "user_id", None)
        for participant in (getattr(meeting, "participants", []) or [])
        if getattr(participant, "user_id", None)
    }
    is_roster_participant = user_id in participant_ids
    has_facilitator_role = role_value == UserRole.FACILITATOR.value
    is_facilitator = is_admin or is_owner or (
        has_facilitator_role and is_roster_participant
    )
    can_view = is_admin or is_owner or is_roster_participant
    can_manage = is_facilitator

    return MeetingCapabilities(
        is_admin=is_admin,
        is_owner=is_owner,
        is_roster_participant=is_roster_participant,
        has_facilitator_role=has_facilitator_role,
        is_facilitator=is_facilitator,
        can_view=can_view,
        can_manage=can_manage,
        can_edit_meeting=can_manage,
        can_manage_roster=can_manage,
        can_control_activity=can_manage,
        can_manage_activity_roster=can_manage,
        can_delete=is_admin or is_owner,
    )
