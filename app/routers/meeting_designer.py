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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.auth import get_current_user
from app.config.loader import get_meeting_designer_settings
from app.models.user import UserRole
from app.data.user_manager import UserManager, get_user_manager
from app.services.ai_provider import (
    AIProviderError,
    AIProviderNotConfiguredError,
    chat_complete,
    chat_stream,
)
from app.services.meeting_designer_prompt import (
    MEETING_DESIGNER_SYSTEM_PROMPT,
    build_generation_messages,
    parse_agenda_json,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meeting-designer", tags=["meeting-designer"])

# ---------------------------------------------------------------------------
# Permission guard — facilitator/admin only
# ---------------------------------------------------------------------------

def _require_facilitator(user_manager: UserManager, user_id: str):
    user = user_manager.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    if user.role not in (UserRole.FACILITATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only facilitators and administrators can use the AI Meeting Designer",
        )
    return user


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
    _require_facilitator(user_manager, current_user)
    settings = get_meeting_designer_settings()

    # Build the full message list for the AI
    history: List[Dict[str, str]] = [
        {"role": m.role, "content": m.content} for m in request.messages
    ]
    history.append({"role": "user", "content": request.new_message})

    async def event_generator():
        try:
            async for chunk in chat_stream(settings, history, MEETING_DESIGNER_SYSTEM_PROMPT):
                payload = json.dumps({"chunk": chunk, "done": False})
                yield f"data: {payload}\n\n"
            # Signal completion
            yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
        except AIProviderNotConfiguredError as exc:
            logger.warning("Meeting Designer not configured: %s", exc)
            payload = json.dumps({"error": "not_configured", "message": str(exc)})
            yield f"data: {payload}\n\n"
        except AIProviderError as exc:
            logger.error("AI provider error in chat: %s", exc)
            payload = json.dumps({"error": "provider_error", "message": str(exc)})
            yield f"data: {payload}\n\n"
        except Exception as exc:
            logger.exception("Unexpected error in Meeting Designer chat")
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
    """Generate a structured meeting agenda from the conversation history.

    Sends the conversation + a generation prompt to the AI and parses
    the returned JSON into a validated agenda structure.

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
    _require_facilitator(user_manager, current_user)
    settings = get_meeting_designer_settings()

    history = [{"role": m.role, "content": m.content} for m in request.messages]
    generation_messages = build_generation_messages(history)

    try:
        raw = await chat_complete(
            settings,
            generation_messages,
            MEETING_DESIGNER_SYSTEM_PROMPT,
        )
    except AIProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Meeting Designer is not configured. Contact your administrator.",
        ) from exc
    except AIProviderError as exc:
        logger.error("AI provider error during agenda generation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI provider error: {exc}",
        ) from exc

    try:
        agenda_data = parse_agenda_json(raw)
    except ValueError as exc:
        logger.error("Failed to parse agenda JSON: %s | Raw: %s", exc, raw[:500])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI returned an invalid agenda format. Please try again.",
        ) from exc

    # Validate minimum required structure
    if "agenda" not in agenda_data or not isinstance(agenda_data["agenda"], list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI returned an agenda with missing or invalid structure. Please try again.",
        )

    return {
        "success": True,
        "meeting_summary": agenda_data.get("meeting_summary", ""),
        "design_rationale": agenda_data.get("design_rationale", ""),
        "agenda": agenda_data.get("agenda", []),
    }
