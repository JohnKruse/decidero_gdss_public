from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

JSONCompatibleDict = Dict[str, Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_metadata(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not value:
        return {}
    sanitized: Dict[str, Any] = {}
    for key, entry in value.items():
        if isinstance(entry, (str, int, float, bool)) or entry is None:
            sanitized[key] = entry
        elif isinstance(entry, (list, dict)):
            sanitized[key] = entry
        else:
            sanitized[key] = str(entry)
    return sanitized


@dataclass
class MeetingState:
    meeting_id: str
    current_activity: Optional[str] = None
    current_tool: Optional[str] = None
    agenda_item_id: Optional[str] = None
    status: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    active_participants: Set[str] = field(default_factory=set)
    active_activities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    agenda: List[JSONCompatibleDict] = field(default_factory=list)
    last_updated: datetime = field(default_factory=_now)

    def touch(self) -> None:
        self.last_updated = _now()

    def to_payload(self) -> JSONCompatibleDict:
        """Return a JSON-friendly snapshot of the meeting state."""
        return {
            "meetingId": self.meeting_id,
            "currentActivity": self.current_activity,
            "currentTool": self.current_tool,
            "agendaItemId": self.agenda_item_id,
            "status": self.status,
            "metadata": dict(self.metadata),
            "participants": sorted(self.active_participants),
            "agenda": self.agenda,
            "activeActivities": [
                self.active_activities[key]
                for key in sorted(self.active_activities.keys())
            ],
            "updatedAt": self.last_updated.isoformat(),
        }


class MeetingStateManager:
    """In-memory coordination layer for meeting-level real-time state."""

    def __init__(self) -> None:
        self._states: Dict[str, MeetingState] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, meeting_id: str) -> MeetingState:
        async with self._lock:
            state = self._states.get(meeting_id)
            if state is None:
                state = MeetingState(meeting_id=meeting_id)
                self._states[meeting_id] = state
            return state

    async def snapshot(self, meeting_id: str) -> Optional[JSONCompatibleDict]:
        async with self._lock:
            state = self._states.get(meeting_id)
            return state.to_payload() if state else None

    async def register_participant(
        self,
        meeting_id: str,
        participant_id: str,
    ) -> JSONCompatibleDict:
        async with self._lock:
            state = self._states.get(meeting_id)
            if state is None:
                state = MeetingState(meeting_id=meeting_id)
                self._states[meeting_id] = state
            state.active_participants.add(participant_id)
            state.touch()
            return state.to_payload()

    async def unregister_participant(
        self,
        meeting_id: str,
        participant_id: str,
    ) -> Optional[JSONCompatibleDict]:
        async with self._lock:
            state = self._states.get(meeting_id)
            if not state:
                return None
            state.active_participants.discard(participant_id)
            state.touch()
            if not state.active_participants and not any(
                [
                    state.current_activity,
                    state.current_tool,
                    state.agenda_item_id,
                    state.status,
                    state.active_activities,
                ]
            ):
                self._states.pop(meeting_id, None)
                return None
            return state.to_payload()

    async def rename_participant(
        self,
        meeting_id: str,
        old_id: str,
        new_id: str,
    ) -> JSONCompatibleDict:
        async with self._lock:
            state = self._states.get(meeting_id)
            if state is None:
                state = MeetingState(meeting_id=meeting_id)
                self._states[meeting_id] = state
            if old_id and old_id in state.active_participants:
                state.active_participants.discard(old_id)
            if new_id:
                state.active_participants.add(new_id)
            state.touch()
            return state.to_payload()

    async def apply_patch(
        self,
        meeting_id: str,
        patch: Dict[str, Any],
    ) -> Tuple[MeetingState, JSONCompatibleDict]:
        """Apply a structured patch to the meeting state and return updated snapshot."""
        async with self._lock:
            state = self._states.get(meeting_id)
            if state is None:
                state = MeetingState(meeting_id=meeting_id)
                self._states[meeting_id] = state

            if "activeActivities" in patch:
                raw_activities = patch.get("activeActivities")
                normalized: Dict[str, Any] = {}
                if isinstance(raw_activities, dict):
                    normalized = {
                        str(key).strip(): value
                        for key, value in raw_activities.items()
                        if str(key).strip()
                    }
                elif isinstance(raw_activities, list):
                    for entry in raw_activities:
                        if not isinstance(entry, dict):
                            continue
                        activity_id = (
                            entry.get("activityId")
                            or entry.get("activity_id")
                            or entry.get("id")
                        )
                        key = str(activity_id or "").strip()
                        if not key:
                            continue
                        normalized[key] = entry

                for activity_id, value in normalized.items():
                    if value is None:
                        state.active_activities.pop(activity_id, None)
                        continue
                    if not isinstance(value, dict):
                        state.active_activities[activity_id] = {
                            "activityId": activity_id,
                            "value": str(value),
                        }
                        continue
                    payload = dict(value)
                    payload["activityId"] = (
                        payload.get("activityId")
                        or payload.get("activity_id")
                        or activity_id
                    )
                    if isinstance(payload.get("metadata"), dict):
                        payload["metadata"] = _sanitize_metadata(payload["metadata"])
                    participant_ids = (
                        payload.get("participantIds")
                        or payload.get("participant_ids")
                        or []
                    )
                    if isinstance(participant_ids, list):
                        payload["participantIds"] = [
                            str(pid).strip()
                            for pid in participant_ids
                            if str(pid).strip()
                        ]
                        payload.pop("participant_ids", None)
                    state.active_activities[activity_id] = payload

            if "currentActivity" in patch:
                state.current_activity = patch["currentActivity"]
            if "currentTool" in patch:
                state.current_tool = patch["currentTool"]
            if "agendaItemId" in patch:
                state.agenda_item_id = patch["agendaItemId"]
            if "status" in patch:
                state.status = patch["status"]
            if "metadata" in patch and isinstance(patch["metadata"], dict):
                state.metadata.update(_sanitize_metadata(patch["metadata"]))
            if "participants" in patch:
                participants = {
                    str(pid) for pid in patch["participants"] if str(pid).strip()
                }
                if participants:
                    state.active_participants.update(participants)

            if "agenda" in patch and isinstance(patch["agenda"], list):
                state.agenda = patch["agenda"]
            state.touch()
            snapshot = state.to_payload()
            return state, snapshot

    async def reset(self, meeting_id: str) -> None:
        async with self._lock:
            self._states.pop(meeting_id, None)


meeting_state_manager = MeetingStateManager()
