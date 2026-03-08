"""
API endpoints for the AI Meeting Designer.

Routes:
  GET  /api/meeting-designer/status           — Is the AI model configured?
  POST /api/meeting-designer/chat             — Streaming chat (SSE)
  POST /api/meeting-designer/generate-agenda  — Generate structured JSON agenda
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc

from app.auth.auth import get_current_user
from app.config.loader import get_meeting_designer_settings
from app.database import SessionLocal, engine
from app.models.meeting_designer_log import MeetingDesignerLog
from app.models.user import UserRole
from app.data.user_manager import UserManager, get_user_manager
from app.services.ai_provider import (
    AIProviderError,
    AIProviderNotConfiguredError,
    chat_complete,
    chat_stream,
)
from app.services.agenda_validator import (
    AgendaFieldError,
    AgendaValidationResult,
    validate_agenda,
    validate_outline,
)
from app.services.meeting_designer_prompt import (
    build_system_prompt,
    build_generation_system_prompt,
    build_generation_messages,
    build_outline_messages,
    parse_agenda_json,
    parse_outline_json,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meeting-designer", tags=["meeting-designer"])
_MEETING_DESIGNER_LOG_TABLE_READY = False
# Configurable: increase if the model frequently needs more correction rounds
_OUTLINE_MAX_ATTEMPTS = 3
_AGENDA_MAX_ATTEMPTS = 2


class GenerationPipelineError(Exception):
    """Raised when a pipeline stage produces output that fails validation.

    Carries stage name, formatted error detail, individual error messages, and
    truncated raw output for logging. Also carries attempts_made and error_trail
    metadata for retry-aware diagnostics.
    """

    def __init__(
        self,
        *,
        stage: str,
        detail: str,
        validation_errors: Optional[List[str]] = None,
        raw_output: str = "",
        attempts_made: int = 1,
        error_trail: Optional[List[List[str]]] = None,
    ) -> None:
        super().__init__(detail)
        self.stage = stage
        self.detail = detail
        self.validation_errors = validation_errors or []
        self.raw_output = (raw_output or "")[:500]
        self.attempts_made = attempts_made
        self.error_trail = error_trail


def _format_validation_errors(
    result: AgendaValidationResult,
    stage: str,
    attempts_made: int = 1,
    error_trail: Optional[List[List[str]]] = None,
) -> GenerationPipelineError:
    """Converts an AgendaValidationResult into a GenerationPipelineError.

    Builds human-readable error messages from validator errors.

    Optional retry metadata is attached for callers that attempt a stage
    multiple times before giving up.
    """

    formatted_errors = [
        f"Activity {issue.activity_index}: {issue.field} - {issue.message}"
        for issue in result.errors
    ]
    count = len(formatted_errors)
    joined_errors = "; ".join(formatted_errors)
    detail = (
        f"Stage '{stage}' failed validation after {attempts_made} attempt(s) "
        f"with {count} error(s): {joined_errors}"
    )
    return GenerationPipelineError(
        stage=stage,
        detail=detail,
        validation_errors=formatted_errors,
        raw_output="",
        attempts_made=attempts_made,
        error_trail=error_trail,
    )


def _build_correction_prompt(
    stage: str,
    parse_failed: bool,
    parse_snippet: str,
    validation_errors: Optional[List[AgendaFieldError]],
) -> str:
    """Builds a user-message correction prompt for a failed pipeline stage.

    Includes the specific error details and a schema reminder so the AI can
    self-correct. Used by the retry loop to append error feedback before
    re-attempting generation.
    """

    schema_reminder = (
        "The JSON must have a top-level \"outline\" array. Each item needs: "
        "tool_type, title, duration_minutes, collaboration_pattern, rationale. "
        "Do NOT include instructions or config_overrides."
        if stage == "outline"
        else "The JSON must have top-level keys: meeting_summary, session_name, "
        "evaluation_criteria, design_rationale, complexity, phases, agenda. Each agenda item "
        "needs: tool_type, title, instructions, duration_minutes, collaboration_pattern, "
        "rationale, config_overrides, phase_id, track_id."
    )

    if parse_failed:
        snippet = (parse_snippet or "")[:300]
        lines = [
            "Your previous response was not valid JSON.",
            "Here is the beginning of what you returned:",
            snippet,
            "Please output ONLY a valid JSON object with no preamble, no markdown fences, and no explanation outside the JSON.",
            schema_reminder,
        ]
        return "\n".join(lines)

    errors = validation_errors or []
    lines = [f"Your previous response had {len(errors)} validation error(s):"]
    for idx, issue in enumerate(errors, start=1):
        lines.append(
            f"  {idx}. Activity {issue.activity_index}: {issue.field} - {issue.message}"
        )
    lines.extend(
        [
            "Please fix these issues and regenerate. Output ONLY the corrected JSON object.",
            schema_reminder,
        ]
    )
    return "\n".join(lines)


async def _run_stage_with_retry(
    stage: str,
    messages: List[Dict[str, str]],
    parser_fn: Callable[[str], Dict[str, Any]],
    validator_fn: Callable[[Dict[str, Any]], AgendaValidationResult],
    max_attempts: int,
    settings: Dict[str, Any],
    system_prompt: str,
) -> Tuple[Dict[str, Any], int]:
    """Executes a pipeline stage (parse -> validate) with automatic retry.

    When parsing or validation fails, the AI's bad output and a correction
    prompt are appended to the message list, and the stage is re-attempted.
    Non-recoverable errors (AIProviderError) propagate immediately. Returns a
    tuple: (parsed and validated data dict, attempts_used), or raises
    GenerationPipelineError after all attempts are exhausted.
    """

    accumulated_errors: List[List[str]] = []

    for attempt_idx in range(max_attempts):
        # Logging: INFO for attempt lifecycle, DEBUG for warnings and correction prompts
        logger.info("Stage '%s' attempt %d/%d", stage, attempt_idx + 1, max_attempts)
        raw_output = await chat_complete(settings, messages, system_prompt)

        try:
            parsed_data = parser_fn(raw_output)
        except ValueError as exc:
            parse_errors = [f"Parse error: {exc}"]
            accumulated_errors.append(parse_errors)
            if attempt_idx < max_attempts - 1:
                logger.info(
                    "Stage '%s' attempt %d/%d: parse error - retrying",
                    stage,
                    attempt_idx + 1,
                    max_attempts,
                )
                correction_prompt = _build_correction_prompt(
                    stage=stage,
                    parse_failed=True,
                    parse_snippet=raw_output[:300],
                    validation_errors=None,
                )
                messages.append({"role": "assistant", "content": raw_output})
                messages.append({"role": "user", "content": correction_prompt})
                continue

            raise GenerationPipelineError(
                stage=stage,
                detail=(
                    f"Stage '{stage}' produced invalid JSON after "
                    f"{attempt_idx + 1} attempt(s): {exc}"
                ),
                validation_errors=parse_errors,
                raw_output=raw_output[:500],
                attempts_made=attempt_idx + 1,
                error_trail=accumulated_errors,
            ) from exc

        validation_result = validator_fn(parsed_data)
        if validation_result.valid:
            if attempt_idx > 0:
                logger.info(
                    "Stage '%s' recovered on attempt %d/%d",
                    stage,
                    attempt_idx + 1,
                    max_attempts,
                )
            else:
                logger.info("Stage '%s' passed on first attempt", stage)
            if validation_result.warnings:
                logger.debug(
                    "Stage '%s' warnings: %s",
                    stage,
                    [warning.message for warning in validation_result.warnings],
                )
            return parsed_data, attempt_idx + 1

        formatted_errors = [
            f"Activity {issue.activity_index}: {issue.field} - {issue.message}"
            for issue in validation_result.errors
        ]
        accumulated_errors.append(formatted_errors)

        if attempt_idx < max_attempts - 1:
            logger.info(
                "Stage '%s' attempt %d/%d: %d validation error(s) - retrying",
                stage,
                attempt_idx + 1,
                max_attempts,
                len(validation_result.errors),
            )
            correction_prompt = _build_correction_prompt(
                stage=stage,
                parse_failed=False,
                parse_snippet="",
                validation_errors=validation_result.errors,
            )
            messages.append({"role": "assistant", "content": raw_output})
            messages.append({"role": "user", "content": correction_prompt})
            continue

        pipeline_error = _format_validation_errors(
            validation_result,
            stage,
            attempts_made=attempt_idx + 1,
            error_trail=accumulated_errors,
        )
        pipeline_error.raw_output = raw_output[:500]
        raise pipeline_error

    raise GenerationPipelineError(
        stage=stage,
        detail=f"Stage '{stage}' failed before executing attempts.",
    )


def _estimate_stage2_max_tokens(activity_count: int, base_max_tokens: int) -> int:
    """Estimate Stage 2 max_tokens from validated outline size.

    Estimates the minimum max_tokens needed for Stage 2 full JSON generation
    based on the validated outline's activity count. Returns the larger of the
    base max_tokens and the estimate, capped at 16384.
    Formula: (activity_count x 300 + 400) x 1.5.
    """
    estimated = int((activity_count * 300 + 400) * 1.5)
    return min(16384, max(base_max_tokens, estimated))


async def _run_generation_pipeline(
    settings: Dict[str, Any],
    history: List[Dict[str, str]],
    system_prompt: str,
) -> Dict[str, Any]:
    """Orchestrates the two-stage agenda generation pipeline.

    Stage 1 generates and validates an activity outline (with retry). Stage 2
    generates and validates full agenda JSON using the validated outline
    injected into the generation prompt (with retry). Raises
    GenerationPipelineError on parse/validation failures after retries are
    exhausted. AIProviderError propagates uncaught.

    Returns:
        Dict[str, Any]: Agenda payload with original contract fields and an
        additive `_pipeline_meta` object containing retry/timing diagnostics.
    """

    start_time = time.monotonic()
    outline_messages = build_outline_messages(history)
    outline_data, outline_attempts = await _run_stage_with_retry(
        stage="outline",
        messages=outline_messages,
        parser_fn=parse_outline_json,
        validator_fn=validate_outline,
        max_attempts=_OUTLINE_MAX_ATTEMPTS,
        settings=settings,
        system_prompt=system_prompt,
    )
    validated_outline = outline_data.get("outline", [])
    outline_elapsed = time.monotonic() - start_time
    logger.info(
        "Outline stage completed in %.1fs (%d activities)",
        outline_elapsed,
        len(validated_outline),
    )
    logger.info(
        "Outline stage passed (%d activities). Proceeding to full generation.",
        len(validated_outline),
    )

    base_max_tokens = int(settings.get("max_tokens", 2048) or 2048)
    # Scaling addresses discovery risk C2 - token exhaustion on large agendas.
    scaled_max_tokens = _estimate_stage2_max_tokens(
        len(validated_outline),
        base_max_tokens,
    )
    stage2_settings = {**settings, "max_tokens": scaled_max_tokens}
    logger.info(
        "Stage 2 max_tokens: %d (base: %d, activities: %d)",
        scaled_max_tokens,
        base_max_tokens,
        len(validated_outline),
    )

    generation_messages = build_generation_messages(history, outline=outline_data)
    agenda_data, agenda_attempts = await _run_stage_with_retry(
        stage="full_json",
        messages=generation_messages,
        parser_fn=parse_agenda_json,
        validator_fn=validate_agenda,
        max_attempts=_AGENDA_MAX_ATTEMPTS,
        settings=stage2_settings,
        system_prompt=system_prompt,
    )
    final_agenda = agenda_data.get("agenda", [])
    total_elapsed = time.monotonic() - start_time
    logger.info(
        "Full generation completed in %.1fs total (%d activities)",
        total_elapsed,
        len(final_agenda),
    )
    logger.info(
        "Full generation stage passed. Returning %d validated activities.",
        len(final_agenda),
    )

    # Informational metadata for frontend display; not part of the agenda contract.
    pipeline_meta = {
        "outline_attempts": outline_attempts,
        "agenda_attempts": agenda_attempts,
        "outline_activity_count": len(validated_outline),
        "total_seconds": round(total_elapsed, 1),
    }

    return {
        "success": True,
        "meeting_summary": agenda_data.get("meeting_summary", ""),
        "session_name": agenda_data.get("session_name", ""),
        "evaluation_criteria": agenda_data.get("evaluation_criteria", []),
        "design_rationale": agenda_data.get("design_rationale", ""),
        "complexity": agenda_data.get("complexity", "simple"),
        "phases": agenda_data.get("phases", []),
        "agenda": final_agenda,
        "_pipeline_meta": pipeline_meta,
    }


# ---------------------------------------------------------------------------
# Permission guard — facilitator/admin only
# ---------------------------------------------------------------------------

def _require_facilitator(user_manager: UserManager, user_id: str):
    user = user_manager.get_user_by_login(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    if user.role not in (UserRole.FACILITATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only facilitators and administrators can use the AI Meeting Designer",
        )
    return user


def _persist_meeting_designer_log(
    *,
    event_type: str,
    user_id: Optional[str],
    user_login: str,
    settings: Dict[str, Any],
    request_messages: List[Dict[str, str]],
    new_message: Optional[str] = None,
    assistant_response: Optional[str] = None,
    raw_output: Optional[str] = None,
    parsed_output: Optional[Dict[str, Any]] = None,
    error_detail: Optional[str] = None,
    status_code: Optional[int] = None,
) -> None:
    """Persist a Meeting Designer audit record.

    This is best-effort: logging failures should never break user flows.
    """
    global _MEETING_DESIGNER_LOG_TABLE_READY
    db = SessionLocal()
    try:
        if not _MEETING_DESIGNER_LOG_TABLE_READY:
            MeetingDesignerLog.__table__.create(bind=engine, checkfirst=True)
            _MEETING_DESIGNER_LOG_TABLE_READY = True
        row = MeetingDesignerLog(
            event_type=event_type,
            user_id=user_id,
            user_login=user_login,
            provider=str(settings.get("provider") or ""),
            model=str(settings.get("model") or ""),
            request_messages=list(request_messages),
            new_message=new_message,
            assistant_response=assistant_response,
            raw_output=raw_output,
            parsed_output=parsed_output,
            error_detail=error_detail,
            status_code=status_code,
        )
        db.add(row)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Failed to persist meeting designer audit log")
    finally:
        db.close()


def _serialize_meeting_designer_log(
    row: MeetingDesignerLog, *, include_payloads: bool = False
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "log_id": row.log_id,
        "event_type": row.event_type,
        "user_id": row.user_id,
        "user_login": row.user_login,
        "provider": row.provider,
        "model": row.model,
        "status_code": row.status_code,
        "error_detail": row.error_detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "message_count": len(row.request_messages or []),
        "has_assistant_response": bool(row.assistant_response),
        "has_raw_output": bool(row.raw_output),
        "has_parsed_output": isinstance(row.parsed_output, dict),
    }
    if include_payloads:
        data.update(
            {
                "request_messages": row.request_messages or [],
                "new_message": row.new_message,
                "assistant_response": row.assistant_response,
                "raw_output": row.raw_output,
                "parsed_output": row.parsed_output,
            }
        )
    return data


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)
    new_message: str = Field(..., min_length=1, max_length=4000)


class GenerateRequest(BaseModel):
    messages: List[ChatMessage] = Field(
        ..., description="Full conversation history including the most recent assistant turn"
    )


class StatusResponse(BaseModel):
    configured: bool
    provider: Optional[str] = None
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=StatusResponse)
async def get_status(
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> StatusResponse:
    """Return whether the AI Meeting Designer is configured."""
    _require_facilitator(user_manager, current_user)
    settings = get_meeting_designer_settings()
    if settings["enabled"]:
        return StatusResponse(
            configured=True,
            provider=settings["provider"],
            model=settings["model"],
        )
    return StatusResponse(configured=False)


@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Stream an AI response as Server-Sent Events.

    The client sends the full conversation history plus the new user message.
    The server appends the new message to the history and streams the response.

    SSE format:
      data: {"chunk": "...", "done": false}\\n\\n
      data: {"chunk": "", "done": true}\\n\\n
      data: {"error": "..."}\\n\\n  (on error)
    """
    user = _require_facilitator(user_manager, current_user)
    settings = get_meeting_designer_settings()

    # Build the full message list for the AI
    history: List[Dict[str, str]] = [
        {"role": m.role, "content": m.content} for m in request.messages
    ]
    history.append({"role": "user", "content": request.new_message})

    async def event_generator():
        assembled_response = ""
        try:
            async for chunk in chat_stream(settings, history, build_system_prompt()):
                assembled_response += chunk
                payload = json.dumps({"chunk": chunk, "done": False})
                yield f"data: {payload}\n\n"
            # Signal completion
            _persist_meeting_designer_log(
                event_type="chat_turn",
                user_id=getattr(user, "user_id", None),
                user_login=getattr(user, "login", current_user),
                settings=settings,
                request_messages=history,
                new_message=request.new_message,
                assistant_response=assembled_response,
                status_code=200,
            )
            yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
        except AIProviderNotConfiguredError as exc:
            logger.warning("Meeting Designer not configured: %s", exc)
            _persist_meeting_designer_log(
                event_type="chat_turn",
                user_id=getattr(user, "user_id", None),
                user_login=getattr(user, "login", current_user),
                settings=settings,
                request_messages=history,
                new_message=request.new_message,
                assistant_response=assembled_response,
                error_detail=str(exc),
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            payload = json.dumps({"error": "not_configured", "message": str(exc)})
            yield f"data: {payload}\n\n"
        except AIProviderError as exc:
            logger.error("AI provider error in chat: %s", exc)
            _persist_meeting_designer_log(
                event_type="chat_turn",
                user_id=getattr(user, "user_id", None),
                user_login=getattr(user, "login", current_user),
                settings=settings,
                request_messages=history,
                new_message=request.new_message,
                assistant_response=assembled_response,
                error_detail=str(exc),
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
            payload = json.dumps({"error": "provider_error", "message": str(exc)})
            yield f"data: {payload}\n\n"
        except Exception as exc:
            logger.exception("Unexpected error in Meeting Designer chat")
            _persist_meeting_designer_log(
                event_type="chat_turn",
                user_id=getattr(user, "user_id", None),
                user_login=getattr(user, "login", current_user),
                settings=settings,
                request_messages=history,
                new_message=request.new_message,
                assistant_response=assembled_response,
                error_detail=str(exc),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            payload = json.dumps({"error": "internal_error", "message": "An unexpected error occurred"})
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/generate-agenda")
async def generate_agenda(
    request: GenerateRequest,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Dict[str, Any]:
    """Generate a structured meeting agenda using a two-stage pipeline.

    Stage 1 produces and validates an activity outline. Stage 2 generates the
    full agenda JSON constrained by the validated outline.

    Returns:
        {
          "success": true,
          "meeting_summary": "...",
          "design_rationale": "...",
          "agenda": [
            {
              "tool_type": "brainstorming",
              "title": "...",
              "instructions": "...",
              "duration_minutes": 15,
              "collaboration_pattern": "Generate",
              "rationale": "...",
              "config_overrides": {...}
            },
            ...
          ]
        }
    """
    user = _require_facilitator(user_manager, current_user)
    settings = get_meeting_designer_settings()

    history = [{"role": m.role, "content": m.content} for m in request.messages]
    system_prompt = build_generation_system_prompt()

    try:
        result = await _run_generation_pipeline(
            settings=settings,
            history=history,
            system_prompt=system_prompt,
        )
    except AIProviderNotConfiguredError as exc:
        _persist_meeting_designer_log(
            event_type="generate_agenda",
            user_id=getattr(user, "user_id", None),
            user_login=getattr(user, "login", current_user),
            settings=settings,
            request_messages=history,
            error_detail=str(exc),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Meeting Designer is not configured. Contact your administrator.",
        ) from exc
    except AIProviderError as exc:
        logger.error("AI provider error during agenda generation: %s", exc)
        _persist_meeting_designer_log(
            event_type="generate_agenda",
            user_id=getattr(user, "user_id", None),
            user_login=getattr(user, "login", current_user),
            settings=settings,
            request_messages=history,
            error_detail=str(exc),
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI provider error: {exc}",
        ) from exc
    except GenerationPipelineError as exc:
        logger.error(
            "Pipeline stage '%s' failed after %d attempt(s): %s | Raw: %s",
            exc.stage,
            exc.attempts_made,
            exc.detail,
            exc.raw_output,
        )
        _persist_meeting_designer_log(
            event_type="generate_agenda",
            user_id=getattr(user, "user_id", None),
            user_login=getattr(user, "login", current_user),
            settings=settings,
            request_messages=history,
            raw_output=exc.raw_output,
            error_detail=exc.detail,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.detail,
        ) from exc

    _persist_meeting_designer_log(
        event_type="generate_agenda",
        user_id=getattr(user, "user_id", None),
        user_login=getattr(user, "login", current_user),
        settings=settings,
        request_messages=history,
        parsed_output={k: v for k, v in result.items() if k != "_pipeline_meta"},
        status_code=status.HTTP_200_OK,
    )

    return result


@router.get("/logs")
async def list_logs(
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(None),
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Dict[str, Any]:
    """List recent Meeting Designer audit records for facilitators/admins."""
    _require_facilitator(user_manager, current_user)
    db = SessionLocal()
    try:
        query = db.query(MeetingDesignerLog)
        if event_type:
            query = query.filter(MeetingDesignerLog.event_type == event_type)
        rows = (
            query.order_by(desc(MeetingDesignerLog.created_at), desc(MeetingDesignerLog.log_id))
            .limit(limit)
            .all()
        )
        return {
            "items": [
                _serialize_meeting_designer_log(row, include_payloads=False)
                for row in rows
            ],
            "count": len(rows),
        }
    finally:
        db.close()


@router.get("/logs/{log_id}")
async def get_log(
    log_id: str,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
) -> Dict[str, Any]:
    """Get one Meeting Designer audit record (full payload)."""
    _require_facilitator(user_manager, current_user)
    db = SessionLocal()
    try:
        row = db.query(MeetingDesignerLog).filter(MeetingDesignerLog.log_id == log_id).first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log entry not found")
        return _serialize_meeting_designer_log(row, include_payloads=True)
    finally:
        db.close()
