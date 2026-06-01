from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models.meeting import Meeting
from ..models.meeting_template import MeetingTemplate
from ..models.user import User
from ..schemas.meeting_template import (
    MEETING_TEMPLATE_CONTRACT_VERSION,
    MeetingTemplateCreate,
    MeetingTemplateFlowType,
    MeetingTemplatePayload,
    MeetingTemplatePermissionSummary,
    MeetingTemplateSource,
    MeetingTemplateStatus,
)

TEMPLATE_RUNTIME_CONFIG_KEYS = {
    "activity_state",
    "draft_bundle",
    "elapsed_duration",
    "elapsedTime",
    "input_bundle",
    "output_bundle",
    "participant_responses",
    "rankings",
    "responses",
    "runtime_data",
    "started_at",
    "state_snapshot",
    "stopped_at",
    "submitted_ballots",
    "timer",
    "votes",
}

START_TEMPLATE_ROLES = {"facilitator", "admin", "super_admin"}
MANAGE_ALL_TEMPLATE_ROLES = {"admin", "super_admin"}


class MeetingTemplateManager:
    """Persists reusable meeting designs without meeting runtime data."""

    def __init__(self, db: Session, logger=None):
        self.db = db
        self.logger = logger or print

    def list_templates(
        self,
        *,
        include_archived: bool = False,
        created_by_user_id: Optional[str] = None,
    ) -> list[MeetingTemplate]:
        query = self.db.query(MeetingTemplate).order_by(
            MeetingTemplate.source.asc(),
            MeetingTemplate.name.asc(),
        )
        if not include_archived:
            query = query.filter(
                MeetingTemplate.status == MeetingTemplateStatus.ACTIVE.value
            )
        if created_by_user_id:
            query = query.filter(
                MeetingTemplate.created_by_user_id == created_by_user_id
            )
        return list(query.all())

    def get_template(self, template_id: str) -> Optional[MeetingTemplate]:
        return (
            self.db.query(MeetingTemplate)
            .filter(MeetingTemplate.template_id == template_id)
            .one_or_none()
        )

    def upsert_builtin_template(
        self,
        *,
        built_in_key: str,
        name: str,
        purpose: Optional[str],
        description: Optional[str],
        estimated_duration_minutes: Optional[int],
        min_participants: Optional[int],
        max_participants: Optional[int],
        tags: Optional[Iterable[str]],
        flow_type: MeetingTemplateFlowType,
        template_payload: MeetingTemplatePayload | Dict[str, Any],
        template_version: int = 1,
    ) -> MeetingTemplate:
        payload = self._coerce_payload(template_payload)
        data = MeetingTemplateCreate(
            source=MeetingTemplateSource.BUILT_IN,
            name=name,
            purpose=purpose,
            description=description,
            estimated_duration_minutes=estimated_duration_minutes,
            min_participants=min_participants,
            max_participants=max_participants,
            tags=list(tags or []),
            flow_type=flow_type,
            template_version=template_version,
            built_in_key=built_in_key,
            template_payload=payload,
        )

        existing = (
            self.db.query(MeetingTemplate)
            .filter(MeetingTemplate.built_in_key == built_in_key)
            .one_or_none()
        )
        if existing is None:
            existing = MeetingTemplate(template_id=self._new_template_id("builtin"))
            self.db.add(existing)

        self._apply_create_data(existing, data)
        self.db.commit()
        self.db.refresh(existing)
        return existing

    def save_custom_template_from_meeting(
        self,
        *,
        meeting_id: str,
        creator_user_id: str,
        name: Optional[str] = None,
        purpose: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        flow_type: Optional[MeetingTemplateFlowType] = None,
    ) -> MeetingTemplate:
        meeting = (
            self.db.query(Meeting)
            .options(joinedload(Meeting.agenda_activities))
            .filter(Meeting.meeting_id == meeting_id)
            .one_or_none()
        )
        if meeting is None:
            raise HTTPException(status_code=404, detail="Meeting not found")

        creator = (
            self.db.query(User)
            .filter(User.user_id == creator_user_id)
            .one_or_none()
        )
        if creator is None:
            raise HTTPException(status_code=404, detail="Template creator not found")

        payload = self.extract_payload_from_meeting(meeting)
        data = MeetingTemplateCreate(
            source=MeetingTemplateSource.CUSTOM,
            name=name or meeting.title,
            purpose=purpose,
            description=meeting.description,
            estimated_duration_minutes=self._estimate_duration_minutes(payload),
            min_participants=None,
            max_participants=None,
            tags=list(tags or []),
            flow_type=flow_type or self._infer_flow_type(payload),
            created_by_user_id=creator.user_id,
            template_payload=payload,
        )

        db_template = MeetingTemplate(template_id=self._new_template_id("custom"))
        self._apply_create_data(db_template, data)
        try:
            self.db.add(db_template)
            self.db.commit()
            self.db.refresh(db_template)
            return db_template
        except SQLAlchemyError as exc:
            self.db.rollback()
            self.logger(f"save_custom_template_from_meeting failed: {exc}")
            raise HTTPException(
                status_code=500,
                detail="Could not save meeting template due to a database error.",
            ) from exc

    def extract_payload_from_meeting(self, meeting: Meeting) -> MeetingTemplatePayload:
        agenda = []
        activities = sorted(
            list(getattr(meeting, "agenda_activities", None) or []),
            key=lambda activity: activity.order_index or 0,
        )
        for index, activity in enumerate(activities, start=1):
            config = self._strip_runtime_config(activity.config or {})
            agenda.append(
                {
                    "tool_type": activity.tool_type,
                    "title": activity.title,
                    "instructions": activity.instructions,
                    "order_index": index,
                    "duration_minutes": self._extract_duration_minutes(config),
                    "config": config,
                }
            )

        return MeetingTemplatePayload(
            schema_version=MEETING_TEMPLATE_CONTRACT_VERSION,
            defaults={
                "title": getattr(meeting, "title", None),
                "description": getattr(meeting, "description", None),
            },
            agenda=agenda,
            parameters={},
            orchestration=self._extract_orchestration_metadata(agenda),
            metadata={
                "phase_canary": "Copper Compass",
                "runtime_stripping": "agenda_structure_only",
            },
        )

    def permission_summary(
        self,
        template: MeetingTemplate,
        user: Optional[User],
    ) -> MeetingTemplatePermissionSummary:
        if user is None:
            return MeetingTemplatePermissionSummary()

        role = str(getattr(user, "role", "") or "").lower()
        is_active = template.status == MeetingTemplateStatus.ACTIVE.value
        is_builtin = template.source == MeetingTemplateSource.BUILT_IN.value
        owns_template = template.created_by_user_id == user.user_id
        manages_all = role in MANAGE_ALL_TEMPLATE_ROLES

        can_start = is_active and role in START_TEMPLATE_ROLES
        can_edit = (not is_builtin) and (owns_template or manages_all)
        return MeetingTemplatePermissionSummary(
            can_start=can_start,
            can_edit=can_edit,
            can_archive=can_edit and is_active,
            can_delete=can_edit,
            is_read_only=not can_edit,
        )

    def _apply_create_data(
        self, template: MeetingTemplate, data: MeetingTemplateCreate
    ) -> None:
        template.source = data.source.value
        template.status = MeetingTemplateStatus.ACTIVE.value
        template.name = data.name
        template.purpose = data.purpose
        template.description = data.description
        template.estimated_duration_minutes = data.estimated_duration_minutes
        template.min_participants = data.min_participants
        template.max_participants = data.max_participants
        template.tags = list(data.tags)
        template.flow_type = data.flow_type.value
        template.template_version = data.template_version
        template.built_in_key = data.built_in_key
        template.created_by_user_id = data.created_by_user_id
        template.contract_version = MEETING_TEMPLATE_CONTRACT_VERSION
        template.template_payload = data.template_payload.model_dump(mode="json")

    def _new_template_id(self, prefix: str) -> str:
        while True:
            candidate = f"{prefix}-{uuid4().hex[:20]}"
            exists = (
                self.db.query(MeetingTemplate.template_id)
                .filter(MeetingTemplate.template_id == candidate)
                .first()
            )
            if not exists:
                return candidate

    def _coerce_payload(
        self, payload: MeetingTemplatePayload | Dict[str, Any]
    ) -> MeetingTemplatePayload:
        if isinstance(payload, MeetingTemplatePayload):
            return payload
        return MeetingTemplatePayload.model_validate(payload)

    def _strip_runtime_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        clean = deepcopy(config)
        for key in list(clean.keys()):
            if key in TEMPLATE_RUNTIME_CONFIG_KEYS:
                clean.pop(key, None)
        return clean

    def _extract_duration_minutes(self, config: Dict[str, Any]) -> Optional[int]:
        for key in ("duration_minutes", "duration", "time_limit_minutes"):
            value = config.get(key)
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return None

    def _estimate_duration_minutes(
        self, payload: MeetingTemplatePayload
    ) -> Optional[int]:
        total = 0
        for activity in payload.agenda:
            if activity.duration_minutes:
                total += activity.duration_minutes
        return total or None

    def _infer_flow_type(self, payload: MeetingTemplatePayload) -> MeetingTemplateFlowType:
        if any(
            isinstance(activity.config, dict)
            and (
                activity.config.get("max_rounds")
                or activity.config.get("convergence_threshold")
                or activity.config.get("orchestration")
            )
            for activity in payload.agenda
        ):
            return MeetingTemplateFlowType.MULTI_ROUND
        return MeetingTemplateFlowType.LINEAR

    def _extract_orchestration_metadata(
        self, agenda: list[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        for activity in agenda:
            config = activity.get("config") or {}
            orchestration = config.get("orchestration")
            if isinstance(orchestration, dict):
                return deepcopy(orchestration)
        return None


def get_meeting_template_manager(
    db: Session = Depends(get_db),
) -> MeetingTemplateManager:
    return MeetingTemplateManager(db=db)
