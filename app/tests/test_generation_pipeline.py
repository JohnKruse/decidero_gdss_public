"""Tests for BRASS-PELICAN-7 / IRON-OSPREY-4 generation pipeline behavior."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.meeting_designer import (
    GenerationPipelineError,
    _format_validation_errors,
    _run_generation_pipeline,
)
from app.services.ai_provider import AIProviderError, AIProviderNotConfiguredError
from app.services.agenda_validator import AgendaFieldError, AgendaValidationResult


VALID_OUTLINE_JSON = """
{
  "meeting_summary": "Create options",
  "outline": [
    {
      "tool_type": "brainstorming",
      "title": "Generate ideas",
      "duration_minutes": 15,
      "collaboration_pattern": "Generate",
      "rationale": "Diverge first"
    }
  ]
}
"""


VALID_AGENDA_JSON = """
{
  "meeting_summary": "Create options",
  "design_rationale": "Diverge then converge",
  "agenda": [
    {
      "tool_type": "brainstorming",
      "title": "Generate ideas",
      "instructions": "List many possibilities quickly.",
      "duration_minutes": 15,
      "collaboration_pattern": "Generate",
      "rationale": "Diverge first",
      "config_overrides": {}
    }
  ]
}
"""


def _valid_outline_json(n: int = 3) -> str:
    """Build a valid outline JSON string with n activities."""
    sequence = [
        ("brainstorming", "Generate Ideas", "Generate"),
        ("categorization", "Group Ideas", "Organize"),
        ("voting", "Dot Vote", "Evaluate"),
        ("rank_order_voting", "Rank Priorities", "Build Consensus"),
        ("voting", "Final Confirm", "Evaluate"),
    ]
    selected = sequence[:n]
    outline = [
        {
            "tool_type": tool_type,
            "title": title,
            "duration_minutes": 10 + idx * 5,
            "collaboration_pattern": pattern,
            "rationale": f"Step {idx + 1} rationale.",
        }
        for idx, (tool_type, title, pattern) in enumerate(selected)
    ]
    return json.dumps({"meeting_summary": f"Pipeline with {n} steps", "outline": outline})


def _valid_agenda_json(n: int = 3) -> str:
    """Build a valid full agenda JSON string with n activities."""
    outline_data = json.loads(_valid_outline_json(n))
    agenda = []
    for item in outline_data["outline"]:
        agenda.append(
            {
                "tool_type": item["tool_type"],
                "title": item["title"],
                "instructions": f"Run activity: {item['title']}.",
                "duration_minutes": item["duration_minutes"],
                "collaboration_pattern": item["collaboration_pattern"],
                "rationale": item["rationale"],
                "config_overrides": {},
            }
        )
    return json.dumps(
        {
            "meeting_summary": outline_data["meeting_summary"],
            "design_rationale": "Sequence follows diverge-converge flow.",
            "agenda": agenda,
        }
    )


def _mock_chat_complete_two_stage(outline_json: str, agenda_json: str) -> AsyncMock:
    """Create a two-stage chat_complete mock for outline then full agenda."""
    return AsyncMock(side_effect=[outline_json, agenda_json])


def test_pipeline_error_has_stage_and_detail() -> None:
    error = GenerationPipelineError(
        stage="outline",
        detail="outline failed",
        validation_errors=["x"],
        raw_output="abc",
    )

    assert error.stage == "outline"
    assert error.detail == "outline failed"
    assert error.validation_errors == ["x"]
    assert error.raw_output == "abc"


def test_format_validation_errors_single_error() -> None:
    result = AgendaValidationResult(
        valid=False,
        errors=[
            AgendaFieldError(
                activity_index=1,
                field="tool_type",
                message="not registered",
                level="error",
            )
        ],
        warnings=[],
    )

    pipeline_error = _format_validation_errors(result, "outline")

    assert pipeline_error.stage == "outline"
    assert "1 error(s)" in pipeline_error.detail
    assert "Activity 1: tool_type" in pipeline_error.detail
    assert "not registered" in pipeline_error.detail
    assert len(pipeline_error.validation_errors) == 1


def test_format_validation_errors_multiple_errors() -> None:
    result = AgendaValidationResult(
        valid=False,
        errors=[
            AgendaFieldError(0, "tool_type", "invalid", "error"),
            AgendaFieldError(1, "title", "missing", "error"),
            AgendaFieldError(2, "instructions", "missing", "error"),
        ],
        warnings=[],
    )

    pipeline_error = _format_validation_errors(result, "full_json")

    assert "Stage 'full_json' failed validation with 3 error(s)" in pipeline_error.detail
    assert "Activity 0: tool_type" in pipeline_error.detail
    assert "Activity 1: title" in pipeline_error.detail
    assert "Activity 2: instructions" in pipeline_error.detail
    assert len(pipeline_error.validation_errors) == 3


def test_format_validation_errors_ignores_warnings() -> None:
    result = AgendaValidationResult(
        valid=False,
        errors=[
            AgendaFieldError(0, "title", "missing", "error"),
            AgendaFieldError(1, "tool_type", "invalid", "error"),
        ],
        warnings=[
            AgendaFieldError(0, "duration_minutes", "outside recommended range", "warning"),
            AgendaFieldError(1, "rationale", "missing", "warning"),
            AgendaFieldError(2, "meeting_summary", "missing", "warning"),
        ],
    )

    pipeline_error = _format_validation_errors(result, "outline")

    assert len(pipeline_error.validation_errors) == 2
    assert "duration_minutes" not in pipeline_error.detail
    assert "meeting_summary" not in pipeline_error.detail


@pytest.mark.asyncio
async def test_stage1_valid_outline() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ) as chat_complete_mock:
        result = await _run_generation_pipeline(
            settings={"provider": "openai"},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert result["meeting_summary"] == "Create options"
    assert result["design_rationale"] == "Diverge then converge"
    assert result["agenda"][0]["tool_type"] == "brainstorming"
    assert chat_complete_mock.call_count == 2


@pytest.mark.asyncio
async def test_stage1_unparseable_json() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(return_value="not json at all"),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert exc_info.value.stage == "outline"


@pytest.mark.asyncio
async def test_stage1_invalid_tool_type() -> None:
    raw_outline = """
    {
      "meeting_summary": "Create options",
      "outline": [
        {
          "tool_type": "brainstorming_deluxe",
          "title": "Generate ideas",
          "duration_minutes": 15,
          "collaboration_pattern": "Generate",
          "rationale": "Diverge first"
        }
      ]
    }
    """
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(return_value=raw_outline),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert exc_info.value.stage == "outline"
    assert "brainstorming_deluxe" in exc_info.value.detail


@pytest.mark.asyncio
async def test_stage1_missing_title() -> None:
    raw_outline = """
    {
      "meeting_summary": "Create options",
      "outline": [
        {
          "tool_type": "brainstorming",
          "title": "",
          "duration_minutes": 15,
          "collaboration_pattern": "Generate",
          "rationale": "Diverge first"
        }
      ]
    }
    """
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(return_value=raw_outline),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert exc_info.value.stage == "outline"
    assert "title" in exc_info.value.detail


@pytest.mark.asyncio
async def test_stage1_calls_chat_complete_once() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ) as chat_complete_mock:
        await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert chat_complete_mock.call_count == 2


@pytest.mark.asyncio
async def test_stage2_valid_full_agenda() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert result["meeting_summary"] == "Create options"
    assert result["design_rationale"] == "Diverge then converge"
    assert len(result["agenda"]) == 1
    activity = result["agenda"][0]
    assert activity["tool_type"] == "brainstorming"
    assert activity["title"] == "Generate ideas"
    assert activity["instructions"] == "List many possibilities quickly."
    assert activity["duration_minutes"] == 15
    assert activity["collaboration_pattern"] == "Generate"
    assert activity["rationale"] == "Diverge first"
    assert activity["config_overrides"] == {}


@pytest.mark.asyncio
async def test_stage2_unparseable_json() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, "not-json"]),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert exc_info.value.stage == "full_json"


@pytest.mark.asyncio
async def test_stage2_hallucinated_tool_type() -> None:
    invalid_agenda = """
    {
      "meeting_summary": "Create options",
      "design_rationale": "Diverge then converge",
      "agenda": [
        {
          "tool_type": "fishbowl",
          "title": "Discuss ideas",
          "instructions": "Discuss",
          "duration_minutes": 10,
          "collaboration_pattern": "Clarify",
          "rationale": "Review options",
          "config_overrides": {}
        }
      ]
    }
    """
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, invalid_agenda]),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert exc_info.value.stage == "full_json"
    assert "fishbowl" in exc_info.value.detail


@pytest.mark.asyncio
async def test_stage2_empty_instructions() -> None:
    invalid_agenda = """
    {
      "meeting_summary": "Create options",
      "design_rationale": "Diverge then converge",
      "agenda": [
        {
          "tool_type": "brainstorming",
          "title": "Generate ideas",
          "instructions": "",
          "duration_minutes": 15,
          "collaboration_pattern": "Generate",
          "rationale": "Diverge first",
          "config_overrides": {}
        }
      ]
    }
    """
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, invalid_agenda]),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert exc_info.value.stage == "full_json"
    assert "instructions" in exc_info.value.detail


@pytest.mark.asyncio
async def test_pipeline_calls_chat_complete_twice() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ) as chat_complete_mock:
        await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert chat_complete_mock.call_count == 2


@pytest.mark.asyncio
async def test_pipeline_passes_outline_to_generation_messages() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ) as chat_complete_mock:
        await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    second_call_messages = chat_complete_mock.call_args_list[1].args[1]
    assert isinstance(second_call_messages, list)
    assert second_call_messages[-1]["role"] == "user"
    assert "Generate ideas" in second_call_messages[-1]["content"]


@pytest.mark.asyncio
async def test_response_shape_matches_original() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert set(result.keys()) == {"success", "meeting_summary", "design_rationale", "agenda"}


def test_endpoint_returns_200_on_valid_pipeline(authenticated_client) -> None:
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert set(body.keys()) == {"success", "meeting_summary", "design_rationale", "agenda"}


def test_endpoint_returns_502_on_outline_failure(authenticated_client) -> None:
    invalid_outline = """
    {
      "meeting_summary": "Create options",
      "outline": [
        {"tool_type": "unknown_type", "title": "Bad", "duration_minutes": 10}
      ]
    }
    """
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(return_value=invalid_outline),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 502
    assert "outline" in response.json()["detail"]


def test_endpoint_returns_502_on_full_json_failure(authenticated_client) -> None:
    bad_full_json = """
    {
      "meeting_summary": "Create options",
      "design_rationale": "Diverge then converge",
      "agenda": [
        {
          "tool_type": "brainstorming",
          "title": "Generate ideas",
          "instructions": "",
          "duration_minutes": 15,
          "collaboration_pattern": "Generate",
          "rationale": "Diverge first"
        }
      ]
    }
    """
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, bad_full_json]),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 502
    assert "full_json" in response.json()["detail"]


def test_endpoint_returns_503_when_not_configured(authenticated_client) -> None:
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer._run_generation_pipeline",
        new=AsyncMock(side_effect=AIProviderNotConfiguredError("not configured")),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 503


def test_endpoint_returns_502_on_provider_error(authenticated_client) -> None:
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer._run_generation_pipeline",
        new=AsyncMock(side_effect=AIProviderError("provider failure")),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 502
    assert "AI provider error" in response.json()["detail"]


def test_chat_endpoint_unchanged(authenticated_client) -> None:
    """Ensure chat SSE endpoint still returns event-stream response."""
    async def _fake_stream(*_args, **_kwargs):
        yield "hello"

    payload = {
        "messages": [{"role": "assistant", "content": "Hi"}],
        "new_message": "Plan a workshop",
    }
    with patch("app.routers.meeting_designer.chat_stream", new=_fake_stream):
        response = authenticated_client.post("/api/meeting-designer/chat", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_e2e_5_activity_pipeline() -> None:
    """Verify 5-activity two-stage pipeline preserves outline tool_type sequence."""
    outline_json = _valid_outline_json(5)
    agenda_json = _valid_agenda_json(5)
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_two_stage(outline_json, agenda_json),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Design a full session"}],
            system_prompt="system",
        )

    expected_tool_types = [item["tool_type"] for item in json.loads(outline_json)["outline"]]
    returned_tool_types = [item["tool_type"] for item in result["agenda"]]
    assert result["success"] is True
    assert len(result["agenda"]) == 5
    assert returned_tool_types == expected_tool_types


@pytest.mark.asyncio
async def test_e2e_1_activity_pipeline() -> None:
    """Verify minimal one-activity two-stage pipeline succeeds."""
    outline_json = _valid_outline_json(1)
    agenda_json = _valid_agenda_json(1)
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_two_stage(outline_json, agenda_json),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need a short meeting"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert len(result["agenda"]) == 1
    assert result["agenda"][0]["tool_type"] == "brainstorming"


def test_response_contract_unchanged(authenticated_client) -> None:
    """Ensure endpoint response contract keys/types match original shape."""
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_two_stage(_valid_outline_json(3), _valid_agenda_json(3)),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    body = response.json()
    assert response.status_code == 200
    assert isinstance(body.get("success"), bool)
    assert isinstance(body.get("meeting_summary"), str)
    assert isinstance(body.get("design_rationale"), str)
    assert isinstance(body.get("agenda"), list)
    assert body["agenda"] and isinstance(body["agenda"][0], dict)
    for key in [
        "tool_type",
        "title",
        "instructions",
        "duration_minutes",
        "collaboration_pattern",
        "rationale",
        "config_overrides",
    ]:
        assert key in body["agenda"][0]


def test_status_endpoint_unaffected(authenticated_client) -> None:
    """Ensure status endpoint behavior remains intact after pipeline rewiring."""
    response = authenticated_client.get("/api/meeting-designer/status")
    body = response.json()
    assert response.status_code == 200
    assert "configured" in body
    assert isinstance(body["configured"], bool)


def test_pipeline_error_detail_is_actionable(authenticated_client) -> None:
    """Ensure 502 detail names stage, activity index, and failed field."""
    invalid_outline = json.dumps(
        {
            "meeting_summary": "Bad outline",
            "outline": [{"tool_type": "bad_tool", "title": "X", "duration_minutes": 10}],
        }
    )
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(return_value=invalid_outline),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    detail = response.json()["detail"]
    assert response.status_code == 502
    assert "outline" in detail
    assert "Activity 0" in detail
    assert "tool_type" in detail


def test_system_prompt_built_once_per_request(authenticated_client) -> None:
    """Ensure generate-agenda builds one system prompt per request."""
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    call_counter = {"count": 0}

    def _fake_system_prompt() -> str:
        call_counter["count"] += 1
        return "system-prompt"

    with (
        patch("app.routers.meeting_designer.build_system_prompt", side_effect=_fake_system_prompt),
        patch(
            "app.routers.meeting_designer._run_generation_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "meeting_summary": "Summary",
                    "design_rationale": "Rationale",
                    "agenda": [],
                }
            ),
        ),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 200
    assert call_counter["count"] == 1
