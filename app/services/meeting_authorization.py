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
        payload = asdict(self)
        payload["is_participant"] = self.is_participant
        return payload


@dataclass(frozen=True)
class MeetingFacilitatorOutput:
    """Canonical facilitator-facing meeting metadata derived from capabilities."""

    id: Optional[str]
    user_id: Optional[str]
    name: str
    is_owner: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MeetingFacilitatorOutputs:
    facilitators: list[MeetingFacilitatorOutput]
    facilitator_ids: list[str]
    facilitator_user_ids: list[str]
    facilitator_names: list[str]

    def owner_summary(self) -> dict[str, Any]:
        owner = next((item for item in self.facilitators if item.is_owner), None)
        if owner is None:
            return {"id": None, "user_id": None, "name": "Unknown"}
        return {
            "id": owner.id,
            "user_id": owner.user_id,
            "name": owner.name,
        }


def _normalize_role_value(user: Optional[User]) -> Optional[str]:
    role_value = getattr(user, "role", None)
    if isinstance(role_value, UserRole):
        return role_value.value
    return role_value


def _format_user_display(user: Any) -> str:
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    name = " ".join(part for part in (first, last) if part)
    if name:
        return name
    login = getattr(user, "login", None)
    if login:
        return login
    email = getattr(user, "email", None)
    if email:
        return email
    return "Unknown"


def _resolve_meeting_capabilities(
    meeting: Meeting,
    *,
    user_id: Optional[str],
    role_value: Optional[str],
) -> MeetingCapabilities:
    normalized_role = role_value.value if isinstance(role_value, UserRole) else role_value
    is_admin = normalized_role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}
    is_owner = getattr(meeting, "owner_id", None) == user_id
    participant_ids = {
        getattr(participant, "user_id", None)
        for participant in (getattr(meeting, "participants", []) or [])
        if getattr(participant, "user_id", None)
    }
    is_roster_participant = user_id in participant_ids
    has_facilitator_role = normalized_role == UserRole.FACILITATOR.value
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


def resolve_meeting_capabilities_for_identity(
    meeting: Meeting,
    *,
    user_id: Optional[str],
    role_value: Optional[str],
) -> MeetingCapabilities:
    """Resolve capabilities for a meeting-scoped identity without a loaded User model."""
    if not user_id:
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
    return _resolve_meeting_capabilities(
        meeting,
        user_id=user_id,
        role_value=role_value,
    )


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

    return _resolve_meeting_capabilities(
        meeting,
        user_id=getattr(user, "user_id", None),
        role_value=_normalize_role_value(user),
    )


def derive_meeting_facilitator_outputs(meeting: Any) -> MeetingFacilitatorOutputs:
    """
    Gravy Parachute: derive surviving facilitator-facing meeting metadata from the
    canonical capability model, not from facilitator rows.
    """

    identities: list[tuple[Optional[str], Optional[str], str, bool]] = []
    seen_user_ids: set[str] = set()

    def add_identity(
        user_id: Optional[str],
        *,
        role_value: Optional[str],
        name: str,
        is_owner: bool = False,
    ) -> None:
        if not user_id or user_id in seen_user_ids:
            return
        seen_user_ids.add(user_id)
        identities.append((user_id, role_value, name, is_owner))

    owner = getattr(meeting, "owner", None)
    owner_id = getattr(meeting, "owner_id", None)
    add_identity(
        owner_id,
        role_value=(
            _normalize_role_value(owner) if owner is not None else UserRole.FACILITATOR.value
        ),
        name=_format_user_display(
            owner or type("MeetingOwnerIdentity", (), {"login": owner_id})()
        ),
        is_owner=True,
    )

    for participant in list(getattr(meeting, "participants", []) or []):
        add_identity(
            getattr(participant, "user_id", None),
            role_value=_normalize_role_value(participant),
            name=_format_user_display(participant),
        )

    facilitators: list[MeetingFacilitatorOutput] = []
    facilitator_ids: list[str] = []
    facilitator_user_ids: list[str] = []
    facilitator_names: list[str] = []

    for user_id, role_value, name, is_owner in identities:
        capabilities = resolve_meeting_capabilities_for_identity(
            meeting,
            user_id=user_id,
            role_value=role_value,
        )
        if not capabilities.is_facilitator:
            continue

        summary = MeetingFacilitatorOutput(
            id=None,
            user_id=user_id,
            name=name,
            is_owner=is_owner,
        )
        facilitators.append(summary)
        facilitator_user_ids.append(user_id)
        if name and name not in facilitator_names:
            facilitator_names.append(name)

    return MeetingFacilitatorOutputs(
        facilitators=facilitators,
        facilitator_ids=facilitator_ids,
        facilitator_user_ids=facilitator_user_ids,
        facilitator_names=facilitator_names,
    )
