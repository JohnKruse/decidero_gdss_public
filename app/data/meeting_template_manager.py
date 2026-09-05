from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models.meeting import Meeting
from ..models.meeting_template import MeetingTemplate
from ..models.user import User
from ..schemas.meeting import MeetingCreate
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
DELPHI_ORCHESTRATION_PATH = Path(__file__).resolve().parents[2] / "orchestrations" / "delphi.json"


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

    def update_custom_template_metadata(
        self,
        *,
        template: MeetingTemplate,
        name: Optional[str] = None,
        purpose: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> MeetingTemplate:
        if template.source == MeetingTemplateSource.BUILT_IN.value:
            raise HTTPException(status_code=403, detail="Built-in templates are read-only")
        if name is not None:
            cleaned_name = name.strip()
            if not cleaned_name:
                raise HTTPException(status_code=400, detail="Template name is required")
            template.name = cleaned_name
        if purpose is not None:
            template.purpose = purpose.strip() or None
        if tags is not None:
            template.tags = self._normalize_tags(tags)
        self.db.commit()
        self.db.refresh(template)
        return template

    def archive_custom_template(self, template: MeetingTemplate) -> MeetingTemplate:
        if template.source == MeetingTemplateSource.BUILT_IN.value:
            raise HTTPException(status_code=403, detail="Built-in templates are read-only")
        template.status = MeetingTemplateStatus.ARCHIVED.value
        self.db.commit()
        self.db.refresh(template)
        return template

    def delete_custom_template(self, template: MeetingTemplate) -> None:
        if template.source == MeetingTemplateSource.BUILT_IN.value:
            raise HTTPException(status_code=403, detail="Built-in templates are read-only")
        self.db.delete(template)
        self.db.commit()

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

    def _orchestration_document_dict(self, orchestration: Dict[str, Any]) -> Dict[str, Any]:
        """Return the orchestration document as a dict, inline or read from file."""
        inline = orchestration.get("document")
        if isinstance(inline, dict):
            return deepcopy(inline)
        document_path = str(orchestration.get("document_path") or "").strip()
        if document_path:
            path = Path(document_path)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[2] / document_path
            return json.loads(path.read_text(encoding="utf-8"))
        raise HTTPException(
            status_code=400, detail="Template has no orchestration document to fork."
        )

    def orchestration_document_dict(
        self, template: MeetingTemplate
    ) -> Optional[Dict[str, Any]]:
        """Return the resolved orchestration document for an orchestration-backed
        template (inline or read from file), or ``None`` if the template carries no
        orchestration. Read-only; used by the show-it-back flow view (Phase 9 Step 3).
        """
        payload = template.template_payload if isinstance(template.template_payload, dict) else {}
        orchestration = payload.get("orchestration") if isinstance(payload, dict) else None
        if not isinstance(orchestration, dict) or orchestration.get("kind") != "orchestration_document":
            return None
        return self._orchestration_document_dict(orchestration)

    @staticmethod
    def _replace_first_iterate_step(
        document: Dict[str, Any], iterate_step: Dict[str, Any]
    ) -> bool:
        """Replace the first iterate block in document order."""
        steps = document.get("steps")
        if not isinstance(steps, list):
            return False
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            if step.get("type") == "iterate":
                steps[index] = deepcopy(iterate_step)
                return True
            if MeetingTemplateManager._replace_first_iterate_step(step, iterate_step):
                return True
        return False

    def fork_orchestration_template(
        self,
        *,
        base_template_id: str,
        name: str,
        created_by_user_id: str,
        max_rounds: Optional[int] = None,
        convergence_threshold: Optional[float] = None,
        who_decides: Optional[str] = None,
        comment_default_fraction: Optional[float] = None,
        comment_max_fraction: Optional[float] = None,
        control_point: Optional[Dict[str, Any]] = None,
        purpose: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> tuple[MeetingTemplate, list[str]]:
        """Plainspoken Marmot: fork an orchestration template with plain tuning.

        Compiles the facilitator's plain choices (round limit, stop threshold, who
        decides each round) into a new orchestration document stored inline on a
        custom template, and returns the template plus its plain-language summary.
        """
        from ..services.orchestration_authoring import (
            apply_tuning,
            compile_control_point_card,
            summarize_orchestration,
        )
        from ..services.orchestration_loader import OrchestrationValidationError

        base = self.get_template(base_template_id)
        if base is None:
            raise HTTPException(status_code=404, detail="Base template not found")
        payload = base.template_payload if isinstance(base.template_payload, dict) else {}
        orchestration = payload.get("orchestration") if isinstance(payload, dict) else None
        if not (isinstance(orchestration, dict) and orchestration.get("kind") == "orchestration_document"):
            raise HTTPException(
                status_code=400,
                detail="Only orchestration-backed templates can be forked and tuned.",
            )

        creator = self.db.query(User).filter(User.user_id == created_by_user_id).one_or_none()
        if creator is None:
            raise HTTPException(status_code=404, detail="Template creator not found")

        base_doc = self._orchestration_document_dict(orchestration)
        try:
            tuned = apply_tuning(
                base_doc,
                max_rounds=max_rounds,
                convergence_threshold=convergence_threshold,
                who_decides=who_decides,
                comment_default_fraction=comment_default_fraction,
                comment_max_fraction=comment_max_fraction,
            )
            if control_point is not None:
                compiled_iterate = compile_control_point_card(dict(control_point))
                if not self._replace_first_iterate_step(tuned, compiled_iterate):
                    raise ValueError("This method has no control point to tune.")
                from ..services.orchestration_loader import load_orchestration_data

                load_orchestration_data(tuned)
        except (ValueError, OrchestrationValidationError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Could not build the tuned method: {exc}"
            ) from exc

        summary = summarize_orchestration(tuned)
        try:
            flow_type = MeetingTemplateFlowType(base.flow_type)
        except (ValueError, TypeError):
            flow_type = MeetingTemplateFlowType.MULTI_ROUND

        new_payload = MeetingTemplatePayload(
            context=payload.get("context") or {},
            agenda=[],
            parameters=payload.get("parameters") or {},
            orchestration={
                "kind": "orchestration_document",
                "document": tuned,
                "document_name": tuned.get("name") or orchestration.get("document_name"),
                "document_version": tuned.get("version") or orchestration.get("document_version"),
                "citation": tuned.get("citation") or orchestration.get("citation"),
                "instantiation_status": "ready",
                "method_outline": summary,
                "runtime_gates": orchestration.get("runtime_gates") or [],
                "forked_from": base.template_id,
            },
            metadata={
                **(payload.get("metadata") or {}),
                "phase_canary": "Plainspoken Marmot",
                "forked_from": base.template_id,
            },
        )
        data = MeetingTemplateCreate(
            source=MeetingTemplateSource.CUSTOM,
            name=name,
            purpose=purpose,
            description=base.description,
            estimated_duration_minutes=base.estimated_duration_minutes,
            min_participants=base.min_participants,
            max_participants=base.max_participants,
            tags=list(tags or []),
            flow_type=flow_type,
            created_by_user_id=creator.user_id,
            template_payload=new_payload,
        )
        db_template = MeetingTemplate(template_id=self._new_template_id("custom"))
        self._apply_create_data(db_template, data)
        try:
            self.db.add(db_template)
            self.db.commit()
            self.db.refresh(db_template)
        except SQLAlchemyError as exc:
            self.db.rollback()
            self.logger(f"fork_orchestration_template failed: {exc}")
            raise HTTPException(
                status_code=500,
                detail="Could not save the forked template due to a database error.",
            ) from exc
        return db_template, summary

    def create_meeting_from_template(
        self,
        *,
        template_id: str,
        meeting_data: MeetingCreate,
        facilitator_id: str,
    ) -> Meeting:
        """Create a fresh meeting from a template without copying runtime data."""
        template = self.get_template(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Meeting template not found")

        payload = template.template_payload if isinstance(template.template_payload, dict) else {}
        orchestration = payload.get("orchestration") if isinstance(payload, dict) else None
        if isinstance(orchestration, dict) and orchestration.get("kind") == "orchestration_document":
            return self._create_orchestration_meeting(
                template=template,
                orchestration=orchestration,
                meeting_data=meeting_data,
                facilitator_id=facilitator_id,
            )

        agenda_items = []
        for item in payload.get("agenda") or []:
            if not isinstance(item, dict):
                continue
            agenda_items.append(
                {
                    "tool_type": item.get("tool_type"),
                    "title": item.get("title"),
                    "instructions": item.get("instructions"),
                    "order_index": item.get("order_index"),
                    "config": item.get("config") or {},
                }
            )

        from ..schemas.meeting import AgendaActivityCreate
        from .meeting_manager import MeetingManager

        meeting_data.source_template_id = template.template_id
        return MeetingManager(self.db).create_meeting(
            meeting_data=meeting_data,
            facilitator_id=facilitator_id,
            agenda_items=[AgendaActivityCreate.model_validate(item) for item in agenda_items],
        )

    def _create_orchestration_meeting(
        self,
        *,
        template: MeetingTemplate,
        orchestration: Dict[str, Any],
        meeting_data: MeetingCreate,
        facilitator_id: str,
    ) -> Meeting:
        from .meeting_manager import MeetingManager
        from ..services.agenda_strategy import get_agenda_strategy

        inline_document = orchestration.get("document")
        document_path = str(orchestration.get("document_path") or "").strip()
        meeting_data.agenda_strategy = "orchestration"
        if isinstance(inline_document, dict):
            # Plainspoken Marmot: forked templates store the document inline; the
            # meeting references it via a template:// path resolved at load time.
            meeting_data.orchestration_path = f"template://{template.template_id}"
        elif document_path:
            meeting_data.orchestration_path = document_path
        else:
            raise HTTPException(
                status_code=400,
                detail="Orchestration-backed template is missing a document.",
            )
        meeting_data.source_template_id = template.template_id
        manager = MeetingManager(self.db)
        meeting = manager.create_meeting(
            meeting_data=meeting_data,
            facilitator_id=facilitator_id,
            agenda_items=[],
        )
        strategy = get_agenda_strategy(meeting)
        strategy.create_activity(meeting, payload=None, manager=manager)
        self.db.refresh(meeting)
        question = (meeting.description or "").strip()
        if question:
            activities = sorted(meeting.agenda_activities or [], key=lambda a: a.order_index or 0)
            first_brainstorm = next((a for a in activities if a.tool_type == "brainstorming"), None)
            if first_brainstorm is not None and not (first_brainstorm.instructions or "").strip():
                first_brainstorm.instructions = question
                self.db.add(first_brainstorm)
                self.db.commit()
                self.db.refresh(meeting)
        return meeting

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

        raw_role = getattr(user, "role", "") or ""
        role = str(getattr(raw_role, "value", raw_role)).lower()
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

    def template_start_block_reason(self, template: MeetingTemplate) -> Optional[str]:
        """Return why a template cannot yet be started, or None when startable."""
        payload = template.template_payload if isinstance(template.template_payload, dict) else {}
        orchestration = payload.get("orchestration") if isinstance(payload, dict) else None
        if not isinstance(orchestration, dict):
            return None
        if orchestration.get("kind") != "orchestration_document":
            return None
        status = str(orchestration.get("instantiation_status") or "").strip().lower()
        if status and status != "ready":
            return (
                "Orchestration template UI pending. This packaged method is documented "
                "and validated, but the user-facing creation flow is not wired yet."
            )
        return None

    def orchestration_summary(self, template: MeetingTemplate) -> Optional[Dict[str, Any]]:
        """Return display metadata for orchestration-backed templates."""
        payload = template.template_payload if isinstance(template.template_payload, dict) else {}
        orchestration = payload.get("orchestration") if isinstance(payload, dict) else None
        if not isinstance(orchestration, dict):
            return None
        if orchestration.get("kind") != "orchestration_document":
            return None
        return {
            "label": "Packaged method",
            "document_name": orchestration.get("document_name"),
            "document_path": orchestration.get("document_path"),
            "document_version": orchestration.get("document_version"),
            "citation": orchestration.get("citation"),
            "method_outline": orchestration.get("method_outline") or [],
            "runtime_gates": orchestration.get("runtime_gates") or [],
        }

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

    def _normalize_tags(self, tags: Iterable[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            tag = str(raw or "").strip()
            if not tag:
                continue
            key = tag.lower()
            if key in seen:
                continue
            cleaned.append(tag)
            seen.add(key)
        return cleaned

    def _coerce_payload(
        self, payload: MeetingTemplatePayload | Dict[str, Any]
    ) -> MeetingTemplatePayload:
        if isinstance(payload, MeetingTemplatePayload):
            return payload
        return MeetingTemplatePayload.model_validate(payload)

    def _strip_runtime_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return self._strip_runtime_value(config)

    def _strip_runtime_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            clean: Dict[str, Any] = {}
            for key, child in value.items():
                if key in TEMPLATE_RUNTIME_CONFIG_KEYS:
                    continue
                clean[key] = self._strip_runtime_value(child)
            return clean
        if isinstance(value, list):
            return [self._strip_runtime_value(item) for item in value]
        return deepcopy(value)

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


def _load_delphi_orchestration_metadata() -> Dict[str, Any]:
    try:
        raw = json.loads(DELPHI_ORCHESTRATION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    feedback_policy: Dict[str, Any] = {}
    for step in raw.get("steps") or []:
        for inner in step.get("steps", []) if isinstance(step, dict) else []:
            for sequence in inner.get("steps", []) if isinstance(inner, dict) else []:
                for activity in sequence.get("steps", []) if isinstance(sequence, dict) else []:
                    # Find the comment step by the presence of a feedback_policy, not
                    # by tool_type — the comment step is now the generic brainstorming
                    # activity configured as a comment surface.
                    if isinstance(activity, dict):
                        config = activity.get("config") if isinstance(activity.get("config"), dict) else {}
                        candidate = config.get("feedback_policy")
                        if isinstance(candidate, dict):
                            feedback_policy = deepcopy(candidate)
                            break
                if feedback_policy:
                    break
            if feedback_policy:
                break
        if feedback_policy:
            break
    return {
        "name": raw.get("name") or "Classical Delphi",
        "version": raw.get("version") or "1.0",
        "citation": raw.get("citation"),
        "group_size_range": metadata.get("group_size_range") or {"min": 3, "max": 25},
        "typical_duration_minutes": metadata.get("typical_duration_minutes") or {"min": 45, "max": 120},
        "thinklets": metadata.get("thinklets") or [],
        "collaboration_patterns": metadata.get("collaboration_patterns") or [],
        "deliverables": metadata.get("deliverables") or [],
        "feedback_policy": feedback_policy,
    }


def seed_builtin_meeting_templates(db: Session) -> list[MeetingTemplate]:
    """Create or refresh built-in templates shipped with the application."""
    manager = MeetingTemplateManager(db=db)
    delphi = _load_delphi_orchestration_metadata()
    group_size = delphi["group_size_range"]
    duration = delphi["typical_duration_minutes"]
    feedback_policy = delphi.get("feedback_policy") or {}
    comment_selection = (
        feedback_policy.get("comment_selection")
        if isinstance(feedback_policy.get("comment_selection"), dict)
        else {}
    )
    classical_delphi = manager.upsert_builtin_template(
        built_in_key="classical-delphi",
        name=str(delphi["name"]),
        purpose="Iterative expert judgment with structured statistical feedback.",
        description=(
            "A packaged Delphi reference method backed by the validated orchestration "
            "document. The method starts with item generation, then iterates rank-order "
            "voting with statistical feedback and IQR-based convergence."
        ),
        estimated_duration_minutes=int(duration.get("max") or 120),
        min_participants=int(group_size.get("min") or 3),
        max_participants=int(group_size.get("max") or 25),
        tags=["Delphi", "Expert judgment", "Multi-round", "Copper Compass"],
        flow_type=MeetingTemplateFlowType.MULTI_ROUND,
        template_payload=MeetingTemplatePayload(
            defaults={
                "title": "Classical Delphi",
                "description": (
                    "Use iterative expert input, structured statistical feedback, "
                    "and convergence checks to move a group toward clearer judgment."
                ),
            },
            agenda=[],
            parameters={
                "problem_statement": {"required": True, "label": "Problem statement"},
                "max_rounds": {"default": 4, "source": "orchestration.iterate.max_rounds"},
                "convergence_threshold": {
                    "default": 0.15,
                    "source": "orchestration.iqr_stability.threshold",
                },
                "comment_selection_strategy": {
                    "default": comment_selection.get("strategy", "adaptive_least_converged"),
                    "source": "orchestration.comment_step.feedback_policy.comment_selection.strategy",
                },
                "comment_default_fraction": {
                    "default": float(comment_selection.get("default_fraction", 0.25)),
                    "source": "orchestration.comment_step.feedback_policy.comment_selection.default_fraction",
                },
                "comment_max_fraction": {
                    "default": float(comment_selection.get("max_fraction", 0.5)),
                    "source": "orchestration.comment_step.feedback_policy.comment_selection.max_fraction",
                },
            },
            orchestration={
                "kind": "orchestration_document",
                "document_path": "orchestrations/delphi.json",
                "document_name": delphi["name"],
                "document_version": delphi["version"],
                "citation": delphi["citation"],
                "instantiation_status": "ready",
                "method_outline": [
                    "Generate candidate Delphi items.",
                    "Iterate a round subcycle: review feedback and justify, then re-rank.",
                    "Transform each round's rankings into statistical feedback (median, IQR).",
                    "Evaluate IQR stability and max-round bounds at the round gate.",
                ],
                "runtime_gates": [
                    "Additional ranking rounds are materialized only if convergence has not been reached.",
                    "The process stops when IQR stability fires or the maximum-round bound is reached.",
                    "Future facilitator or AI review steps can add explicit continue/stop decisions.",
                ],
                "feedback_policy": feedback_policy,
            },
            metadata={
                "phase_canary": "Copper Compass",
                "runtime_stripping": "orchestration_reference_only",
                "thinklets": delphi["thinklets"],
                "collaboration_patterns": delphi["collaboration_patterns"],
                "deliverables": delphi["deliverables"],
            },
        ),
    )
    return [classical_delphi]
