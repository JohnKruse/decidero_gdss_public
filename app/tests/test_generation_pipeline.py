"""Tests for BRASS-PELICAN-7 / IRON-OSPREY-4 / BRONZE-MERLIN-2 / STEEL-KINGFISHER-5 pipeline behavior."""

import inspect
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.meeting_designer import (
    GenerationPipelineError,
    _AGENDA_MAX_ATTEMPTS,
    _build_correction_prompt,
    _estimate_stage2_max_tokens,
    _format_validation_errors,
    _OUTLINE_MAX_ATTEMPTS,
    _run_generation_pipeline,
    _run_stage_with_retry,
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


def _valid_6_activity_outline_json() -> str:
    """Build a valid 6-activity outline with live registry tool types."""
    outline = [
        {
            "tool_type": "brainstorming",
            "title": "Diverge Ideas",
            "duration_minutes": 10,
            "collaboration_pattern": "Generate",
            "rationale": "Open broad option space.",
        },
        {
            "tool_type": "categorization",
            "title": "Cluster Themes",
            "duration_minutes": 10,
            "collaboration_pattern": "Organize",
            "rationale": "Group related ideas for clarity.",
        },
        {
            "tool_type": "voting",
            "title": "Initial Signal Vote",
            "duration_minutes": 10,
            "collaboration_pattern": "Evaluate",
            "rationale": "Find promising candidates quickly.",
        },
        {
            "tool_type": "brainstorming",
            "title": "Refine Top Options",
            "duration_minutes": 10,
            "collaboration_pattern": "Generate",
            "rationale": "Improve strongest candidates.",
        },
        {
            "tool_type": "rank_order_voting",
            "title": "Rank Tradeoffs",
            "duration_minutes": 15,
            "collaboration_pattern": "Build Consensus",
            "rationale": "Force comparative prioritization.",
        },
        {
            "tool_type": "voting",
            "title": "Final Commitment Vote",
            "duration_minutes": 10,
            "collaboration_pattern": "Evaluate",
            "rationale": "Confirm preferred direction.",
        },
    ]
    return json.dumps({"meeting_summary": "Six-step decision flow", "outline": outline})


def _valid_6_activity_agenda_json() -> str:
    """Build a valid 6-activity full agenda with enriched metadata fields."""
    outline = json.loads(_valid_6_activity_outline_json())["outline"]
    phases = [
        {
            "phase_id": "phase_1",
            "title": "Discovery",
            "description": "Diverge and organize candidate options.",
            "phase_type": "plenary",
            "suggested_duration_minutes": 30,
        },
        {
            "phase_id": "phase_2",
            "title": "Selection",
            "description": "Converge on a decision.",
            "phase_type": "plenary",
            "suggested_duration_minutes": 35,
        },
    ]
    agenda = []
    for idx, item in enumerate(outline):
        agenda.append(
            {
                "tool_type": item["tool_type"],
                "title": item["title"],
                "instructions": f"Run activity {idx + 1}: {item['title']}.",
                "duration_minutes": item["duration_minutes"],
                "collaboration_pattern": item["collaboration_pattern"],
                "rationale": item["rationale"],
                "config_overrides": {},
                "phase_id": "phase_1" if idx < 3 else "phase_2",
                "track_id": None,
            }
        )

    return json.dumps(
        {
            "meeting_summary": "Six-step decision flow",
            "session_name": "Steering Committee Decision Session",
            "evaluation_criteria": ["impact", "feasibility", "speed"],
            "design_rationale": "Diverge, cluster, then converge through ranking and confirmation.",
            "complexity": "multi_phase",
            "phases": phases,
            "agenda": agenda,
        }
    )


def _mock_chat_complete_two_stage(outline_json: str, agenda_json: str) -> AsyncMock:
    """Create a two-stage chat_complete mock for outline then full agenda."""
    return AsyncMock(side_effect=[outline_json, agenda_json])


def _mock_chat_complete_sequence(*responses: str) -> AsyncMock:
    """Create a sequential chat_complete mock that returns raw responses in order."""
    return AsyncMock(side_effect=list(responses))


def _invalid_outline_json(error: str = "hallucinated_type") -> str:
    """Build outline JSON with a deterministic validation failure."""
    outline = {
        "meeting_summary": "Create options",
        "outline": [
            {
                "tool_type": "brainstorming",
                "title": "Generate ideas",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Diverge first",
            }
        ],
    }
    if error == "hallucinated_type":
        outline["outline"][0]["tool_type"] = "workshop"
    elif error == "missing_title":
        outline["outline"][0]["title"] = ""
    return json.dumps(outline)


def _invalid_agenda_json(error: str = "empty_instructions") -> str:
    """Build full-agenda JSON with a deterministic validation failure."""
    agenda = {
        "meeting_summary": "Create options",
        "session_name": "Decision Workshop",
        "evaluation_criteria": ["clarity", "alignment"],
        "design_rationale": "Diverge then converge",
        "complexity": "simple",
        "phases": [],
        "agenda": [
            {
                "tool_type": "brainstorming",
                "title": "Generate ideas",
                "instructions": "List many possibilities quickly.",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Diverge first",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": None,
            }
        ],
    }
    if error == "empty_instructions":
        agenda["agenda"][0]["instructions"] = ""
    elif error == "hallucinated_type":
        agenda["agenda"][0]["tool_type"] = "roundtable"
    return json.dumps(agenda)


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


def test_pipeline_error_carries_attempts_made() -> None:
    error = GenerationPipelineError(stage="outline", detail="x", attempts_made=3)
    assert error.attempts_made == 3


def test_pipeline_error_carries_error_trail() -> None:
    trail = [["first error"], ["second error", "third error"]]
    error = GenerationPipelineError(stage="outline", detail="x", error_trail=trail)
    assert error.error_trail is trail
    assert len(error.error_trail) == 2


def test_pipeline_error_defaults() -> None:
    error = GenerationPipelineError(stage="outline", detail="x")
    assert error.attempts_made == 1
    assert error.error_trail is None


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

    assert "Stage 'full_json' failed validation after 1 attempt(s) with 3 error(s)" in pipeline_error.detail
    assert "Activity 0: tool_type" in pipeline_error.detail
    assert "Activity 1: title" in pipeline_error.detail
    assert "Activity 2: instructions" in pipeline_error.detail
    assert len(pipeline_error.validation_errors) == 3


def test_format_validation_errors_includes_attempt_count() -> None:
    result = AgendaValidationResult(
        valid=False,
        errors=[AgendaFieldError(0, "title", "missing", "error")],
        warnings=[],
    )

    pipeline_error = _format_validation_errors(result, "outline", attempts_made=3)

    assert "3 attempt(s)" in pipeline_error.detail
    assert pipeline_error.attempts_made == 3


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


def test_retry_constants_values() -> None:
    assert _OUTLINE_MAX_ATTEMPTS == 3
    assert _AGENDA_MAX_ATTEMPTS == 2


def test_correction_prompt_parse_failure_outline() -> None:
    prompt = _build_correction_prompt(
        stage="outline",
        parse_failed=True,
        parse_snippet="not-json-output",
        validation_errors=None,
    )

    assert "not valid JSON" in prompt
    assert "not-json-output" in prompt
    assert "top-level \"outline\" array" in prompt


def test_correction_prompt_parse_failure_full_json() -> None:
    prompt = _build_correction_prompt(
        stage="full_json",
        parse_failed=True,
        parse_snippet="bad-json",
        validation_errors=None,
    )

    assert "not valid JSON" in prompt
    assert "meeting_summary" in prompt
    assert "agenda" in prompt
    assert "top-level \"outline\" array" not in prompt


def test_correction_prompt_validation_errors() -> None:
    prompt = _build_correction_prompt(
        stage="full_json",
        parse_failed=False,
        parse_snippet="",
        validation_errors=[
            AgendaFieldError(0, "tool_type", "invalid value", "error"),
            AgendaFieldError(2, "title", "missing", "error"),
        ],
    )

    assert "2 validation error(s)" in prompt
    assert "Activity 0: tool_type - invalid value" in prompt
    assert "Activity 2: title - missing" in prompt


def test_correction_prompt_no_hardcoded_tool_types() -> None:
    source = inspect.getsource(_build_correction_prompt)
    for disallowed in ["brainstorming", "voting", "rank_order_voting", "categorization"]:
        assert disallowed not in source


def test_correction_prompt_truncates_raw_snippet() -> None:
    raw = "x" * 500
    prompt = _build_correction_prompt(
        stage="outline",
        parse_failed=True,
        parse_snippet=raw,
        validation_errors=None,
    )

    assert "x" * 300 in prompt
    assert "x" * 301 not in prompt


def _json_parser(raw_text: str) -> dict:
    """Simple JSON parser for stage-runner unit tests."""
    return json.loads(raw_text)


def _validator_requires_valid_true(data: dict) -> AgendaValidationResult:
    """Validator for stage-runner tests: requires valid=true."""
    if data.get("valid") is True:
        return AgendaValidationResult(valid=True, errors=[], warnings=[])
    return AgendaValidationResult(
        valid=False,
        errors=[AgendaFieldError(0, "tool_type", "invalid", "error")],
        warnings=[],
    )


@pytest.mark.asyncio
async def test_stage_runner_succeeds_first_attempt() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(return_value='{"valid": true}'),
    ) as chat_complete_mock:
        result, attempts_used = await _run_stage_with_retry(
            stage="outline",
            messages=messages,
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=3,
            settings={},
            system_prompt="system",
    )

    assert result["valid"] is True
    assert attempts_used == 1
    assert chat_complete_mock.call_count == 1


@pytest.mark.asyncio
async def test_stage_runner_succeeds_after_retry() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["not-json", '{"valid": true}']),
    ) as chat_complete_mock:
        result, attempts_used = await _run_stage_with_retry(
            stage="outline",
            messages=messages,
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=3,
            settings={},
            system_prompt="system",
    )

    assert result["valid"] is True
    assert attempts_used == 2
    assert chat_complete_mock.call_count == 2


@pytest.mark.asyncio
async def test_stage_runner_returns_attempt_count() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(return_value='{"valid": true}'),
    ):
        parsed_data, attempts_used = await _run_stage_with_retry(
            stage="outline",
            messages=messages,
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=3,
            settings={},
            system_prompt="system",
        )

    assert parsed_data["valid"] is True
    assert attempts_used == 1


@pytest.mark.asyncio
async def test_stage_runner_returns_attempt_count_after_retry() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["not-json", '{"valid": true}']),
    ):
        parsed_data, attempts_used = await _run_stage_with_retry(
            stage="outline",
            messages=messages,
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=3,
            settings={},
            system_prompt="system",
        )

    assert parsed_data["valid"] is True
    assert attempts_used == 2


@pytest.mark.asyncio
async def test_stage_runner_parse_error_then_recovery() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["Here is your outline: {...", '{"valid": true}']),
    ):
        result, attempts_used = await _run_stage_with_retry(
            stage="outline",
            messages=messages,
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=3,
            settings={},
            system_prompt="system",
        )

    assert result["valid"] is True
    assert attempts_used == 2
    assert messages[-2]["role"] == "assistant"
    assert messages[-1]["role"] == "user"
    assert "not valid JSON" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_stage_runner_validation_error_then_recovery() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=['{"valid": false}', '{"valid": true}']),
    ):
        result, attempts_used = await _run_stage_with_retry(
            stage="full_json",
            messages=messages,
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=2,
            settings={},
            system_prompt="system",
        )

    assert result["valid"] is True
    assert attempts_used == 2


@pytest.mark.asyncio
async def test_stage_runner_exhausts_all_attempts() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["not-json-1", "not-json-2", "not-json-3"]),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_stage_with_retry(
                stage="outline",
                messages=messages,
                parser_fn=_json_parser,
                validator_fn=_validator_requires_valid_true,
                max_attempts=3,
                settings={},
                system_prompt="system",
            )

    assert exc_info.value.attempts_made == 3
    assert exc_info.value.error_trail


@pytest.mark.asyncio
async def test_stage_runner_appends_correction_messages() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["not-json", '{"valid": true}']),
    ):
        await _run_stage_with_retry(
            stage="outline",
            messages=messages,
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=3,
            settings={},
            system_prompt="system",
        )

    assert messages[-2]["role"] == "assistant"
    assert messages[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_stage_runner_does_not_catch_provider_error() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=AIProviderError("provider down")),
    ):
        with pytest.raises(AIProviderError):
            await _run_stage_with_retry(
                stage="outline",
                messages=messages,
                parser_fn=_json_parser,
                validator_fn=_validator_requires_valid_true,
                max_attempts=3,
                settings={},
                system_prompt="system",
            )


@pytest.mark.asyncio
async def test_stage_runner_error_trail_accumulates() -> None:
    messages = [{"role": "user", "content": "generate"}]
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=['{"valid": false}', '{"valid": false}', '{"valid": false}']),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_stage_with_retry(
                stage="full_json",
                messages=messages,
                parser_fn=_json_parser,
                validator_fn=_validator_requires_valid_true,
                max_attempts=3,
                settings={},
                system_prompt="system",
            )

    assert exc_info.value.attempts_made == 3
    assert exc_info.value.error_trail is not None
    assert len(exc_info.value.error_trail) == 3


@pytest.mark.asyncio
async def test_pipeline_outline_retry_then_success() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["not-json", VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ) as chat_complete_mock:
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert chat_complete_mock.call_count == 3


@pytest.mark.asyncio
async def test_pipeline_agenda_retry_then_success() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, "not-json", VALID_AGENDA_JSON]),
    ) as chat_complete_mock:
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert chat_complete_mock.call_count == 3


@pytest.mark.asyncio
async def test_pipeline_both_stages_retry() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(
            side_effect=["not-json-outline", VALID_OUTLINE_JSON, "not-json-agenda", VALID_AGENDA_JSON]
        ),
    ) as chat_complete_mock:
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert chat_complete_mock.call_count == 4


@pytest.mark.asyncio
async def test_pipeline_meta_present_in_response() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[_valid_outline_json(3), _valid_agenda_json(3)]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert "_pipeline_meta" in result
    assert set(result["_pipeline_meta"].keys()) == {
        "outline_attempts",
        "agenda_attempts",
        "outline_activity_count",
        "total_seconds",
    }


@pytest.mark.asyncio
async def test_pipeline_meta_attempt_counts_correct() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["not-json", _valid_outline_json(3), _valid_agenda_json(3)]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert result["_pipeline_meta"]["outline_attempts"] == 2
    assert result["_pipeline_meta"]["agenda_attempts"] == 1


@pytest.mark.asyncio
async def test_pipeline_meta_total_seconds_is_number() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[_valid_outline_json(2), _valid_agenda_json(2)]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert isinstance(result["_pipeline_meta"]["total_seconds"], float)
    assert result["_pipeline_meta"]["total_seconds"] >= 0.0


@pytest.mark.asyncio
async def test_pipeline_meta_outline_activity_count() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[_valid_outline_json(4), _valid_agenda_json(4)]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert result["_pipeline_meta"]["outline_activity_count"] == 4


@pytest.mark.asyncio
async def test_generate_agenda_response_is_json_serializable() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[_valid_outline_json(3), _valid_agenda_json(3)]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    encoded = json.dumps(result)
    decoded = json.loads(encoded)
    assert decoded["success"] is True
    assert isinstance(decoded.get("agenda"), list)


@pytest.mark.asyncio
async def test_original_response_keys_unchanged() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[_valid_outline_json(3), _valid_agenda_json(3)]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    for key in [
        "success",
        "meeting_summary",
        "session_name",
        "evaluation_criteria",
        "design_rationale",
        "complexity",
        "phases",
        "agenda",
    ]:
        assert key in result


def test_estimate_tokens_small_agenda() -> None:
    assert _estimate_stage2_max_tokens(activity_count=2, base_max_tokens=2048) == 2048


def test_estimate_tokens_large_agenda() -> None:
    assert _estimate_stage2_max_tokens(activity_count=8, base_max_tokens=2048) > 2048


def test_estimate_tokens_never_shrinks() -> None:
    assert _estimate_stage2_max_tokens(activity_count=1, base_max_tokens=4096) == 4096


def test_estimate_tokens_ceiling() -> None:
    assert _estimate_stage2_max_tokens(activity_count=100, base_max_tokens=2048) == 16384


@pytest.mark.asyncio
async def test_pipeline_passes_scaled_tokens_to_stage2() -> None:
    with (
        patch(
            "app.routers.meeting_designer._estimate_stage2_max_tokens",
            return_value=7777,
        ) as estimate_mock,
        patch(
            "app.routers.meeting_designer.chat_complete",
            new=AsyncMock(side_effect=[_valid_outline_json(5), _valid_agenda_json(5)]),
        ) as chat_complete_mock,
    ):
        await _run_generation_pipeline(
            settings={"max_tokens": 2048},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    estimate_mock.assert_called_once()
    assert chat_complete_mock.call_args_list[1].args[0]["max_tokens"] == 7777


@pytest.mark.asyncio
async def test_pipeline_stage1_uses_original_tokens() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[_valid_outline_json(3), _valid_agenda_json(3)]),
    ) as chat_complete_mock:
        await _run_generation_pipeline(
            settings={"max_tokens": 4096},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert chat_complete_mock.call_args_list[0].args[0]["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_pipeline_outline_exhausted() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["bad-1", "bad-2", "bad-3"]),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert exc_info.value.stage == "outline"
    assert exc_info.value.attempts_made == 3


@pytest.mark.asyncio
async def test_pipeline_agenda_exhausted() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, "bad-1", "bad-2"]),
    ):
        with pytest.raises(GenerationPipelineError) as exc_info:
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert exc_info.value.stage == "full_json"
    assert exc_info.value.attempts_made == 2


@pytest.mark.asyncio
async def test_pipeline_response_shape_unchanged() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=["not-json", VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert set(result.keys()) == {
        "success",
        "meeting_summary",
        "session_name",
        "evaluation_criteria",
        "design_rationale",
        "complexity",
        "phases",
        "agenda",
        "_pipeline_meta",
    }


@pytest.mark.asyncio
async def test_pipeline_provider_error_no_retry() -> None:
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=AIProviderError("provider failure")),
    ) as chat_complete_mock:
        with pytest.raises(AIProviderError):
            await _run_generation_pipeline(
                settings={},
                history=[{"role": "user", "content": "Need agenda"}],
                system_prompt="system",
            )

    assert chat_complete_mock.call_count == 1


@pytest.mark.asyncio
async def test_logging_first_attempt_success() -> None:
    with (
        patch(
            "app.routers.meeting_designer.chat_complete",
            new=AsyncMock(return_value='{"valid": true}'),
        ),
        patch("app.routers.meeting_designer.logger") as logger_mock,
    ):
        await _run_stage_with_retry(
            stage="outline",
            messages=[{"role": "user", "content": "generate"}],
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=3,
            settings={},
            system_prompt="system",
        )

    assert any("passed on first attempt" in str(call.args[0]) for call in logger_mock.info.call_args_list)


@pytest.mark.asyncio
async def test_logging_retry_recovery() -> None:
    with (
        patch(
            "app.routers.meeting_designer.chat_complete",
            new=AsyncMock(side_effect=["not-json", '{"valid": true}']),
        ),
        patch("app.routers.meeting_designer.logger") as logger_mock,
    ):
        await _run_stage_with_retry(
            stage="outline",
            messages=[{"role": "user", "content": "generate"}],
            parser_fn=_json_parser,
            validator_fn=_validator_requires_valid_true,
            max_attempts=3,
            settings={},
            system_prompt="system",
        )

    info_templates = [str(call.args[0]) for call in logger_mock.info.call_args_list]
    assert any("retrying" in template for template in info_templates)
    assert any("recovered on attempt" in template for template in info_templates)


def test_logging_exhausted_attempts(authenticated_client) -> None:
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with (
        patch(
            "app.routers.meeting_designer._run_generation_pipeline",
            new=AsyncMock(
                side_effect=GenerationPipelineError(
                    stage="outline",
                    detail="Stage 'outline' failed after 3 attempt(s): validation failed",
                    raw_output="bad-json",
                    attempts_made=3,
                )
            ),
        ),
        patch("app.routers.meeting_designer._persist_meeting_designer_log"),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 502
    assert "3 attempt(s)" in response.json()["detail"]


def test_502_detail_contains_stage_and_attempts(authenticated_client) -> None:
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    invalid_outline = _invalid_outline_json("hallucinated_type")
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence(invalid_outline, invalid_outline, invalid_outline),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    detail = response.json()["detail"]
    assert response.status_code == 502
    assert "Stage 'outline'" in detail
    assert "3 attempt(s)" in detail


def test_502_detail_contains_individual_errors(authenticated_client) -> None:
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    bad_full_json = _invalid_agenda_json("empty_instructions")
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence(_valid_outline_json(3), bad_full_json, bad_full_json),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    detail = response.json()["detail"]
    assert response.status_code == 502
    assert "instructions" in detail
    assert "Activity 0" in detail


@pytest.mark.asyncio
async def test_logging_pipeline_timing() -> None:
    with (
        patch(
            "app.routers.meeting_designer.chat_complete",
            new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
        ),
        patch("app.routers.meeting_designer.logger") as logger_mock,
    ):
        await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    info_templates = [str(call.args[0]) for call in logger_mock.info.call_args_list]
    assert any("Outline stage completed in" in template for template in info_templates)
    assert any("Full generation completed in" in template for template in info_templates)


@pytest.mark.asyncio
async def test_logging_warnings_at_debug() -> None:
    def _validator_valid_with_warning(_data: dict) -> AgendaValidationResult:
        return AgendaValidationResult(
            valid=True,
            errors=[],
            warnings=[AgendaFieldError(0, "rationale", "recommended tweak", "warning")],
        )

    with (
        patch(
            "app.routers.meeting_designer.chat_complete",
            new=AsyncMock(return_value='{"valid": true}'),
        ),
        patch("app.routers.meeting_designer.logger") as logger_mock,
    ):
        await _run_stage_with_retry(
            stage="outline",
            messages=[{"role": "user", "content": "generate"}],
            parser_fn=_json_parser,
            validator_fn=_validator_valid_with_warning,
            max_attempts=3,
            settings={},
            system_prompt="system",
        )

    assert any("warnings" in str(call.args[0]) for call in logger_mock.debug.call_args_list)


@pytest.mark.asyncio
async def test_audit_log_not_called_per_retry() -> None:
    with (
        patch(
            "app.routers.meeting_designer.chat_complete",
            new=AsyncMock(side_effect=["not-json", VALID_OUTLINE_JSON, VALID_AGENDA_JSON]),
        ),
        patch("app.routers.meeting_designer._persist_meeting_designer_log") as audit_mock,
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need agenda"}],
            system_prompt="system",
        )

    assert result["success"] is True
    audit_mock.assert_not_called()


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
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, "not-json", "still-not-json"]),
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
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, invalid_agenda, invalid_agenda]),
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
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, invalid_agenda, invalid_agenda]),
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

    assert set(result.keys()) == {
        "success",
        "meeting_summary",
        "session_name",
        "evaluation_criteria",
        "design_rationale",
        "complexity",
        "phases",
        "agenda",
        "_pipeline_meta",
    }


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
    assert set(body.keys()) == {
        "success",
        "meeting_summary",
        "session_name",
        "evaluation_criteria",
        "design_rationale",
        "complexity",
        "phases",
        "agenda",
        "_pipeline_meta",
    }


def test_endpoint_uses_generation_system_prompt(authenticated_client) -> None:
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    mocked_result = {
        "success": True,
        "meeting_summary": "Summary",
        "session_name": "Session",
        "evaluation_criteria": [],
        "design_rationale": "Rationale",
        "complexity": "simple",
        "phases": [],
        "agenda": [],
        "_pipeline_meta": {
            "outline_attempts": 1,
            "agenda_attempts": 1,
            "outline_activity_count": 0,
            "total_seconds": 0.1,
        },
    }
    with patch(
        "app.routers.meeting_designer.build_generation_system_prompt",
        return_value="GENERATION_SYSTEM_PROMPT",
    ), patch(
        "app.routers.meeting_designer._run_generation_pipeline",
        new=AsyncMock(return_value=mocked_result),
    ) as pipeline_mock:
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 200
    assert pipeline_mock.call_args.kwargs["system_prompt"] == "GENERATION_SYSTEM_PROMPT"


def test_pipeline_meta_in_endpoint_response(authenticated_client) -> None:
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_two_stage(_valid_outline_json(3), _valid_agenda_json(3)),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    body = response.json()
    assert response.status_code == 200
    assert "_pipeline_meta" in body
    assert set(body["_pipeline_meta"].keys()) == {
        "outline_attempts",
        "agenda_attempts",
        "outline_activity_count",
        "total_seconds",
    }


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
        new=AsyncMock(side_effect=[VALID_OUTLINE_JSON, bad_full_json, bad_full_json]),
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


# Phase 5 (STEEL-KINGFISHER-5): Integration, hardening, and end-to-end verification
@pytest.mark.asyncio
async def test_e2e_6_activity_agenda_succeeds() -> None:
    """Verify six-activity end-to-end pipeline succeeds with metadata."""
    outline_json = _valid_6_activity_outline_json()
    agenda_json = _valid_6_activity_agenda_json()
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_two_stage(outline_json, agenda_json),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Design a full steering session"}],
            system_prompt="system",
        )

    returned_tool_types = [item["tool_type"] for item in result["agenda"]]
    assert result["success"] is True
    assert len(result["agenda"]) == 6
    assert returned_tool_types == [
        "brainstorming",
        "categorization",
        "voting",
        "brainstorming",
        "rank_order_voting",
        "voting",
    ]
    assert "_pipeline_meta" in result


@pytest.mark.asyncio
async def test_e2e_6_activity_with_retry_and_metadata() -> None:
    """Verify retry metadata for six-activity outline-retry scenario."""
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence(
            "not-json",
            _valid_6_activity_outline_json(),
            _valid_6_activity_agenda_json(),
        ),
    ):
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need robust agenda"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert result["_pipeline_meta"]["outline_attempts"] == 2
    assert result["_pipeline_meta"]["agenda_attempts"] == 1


@pytest.mark.asyncio
async def test_e2e_max_tokens_scaled_for_large_agenda() -> None:
    """Verify Stage 2 max_tokens is scaled above 2048 for six activities."""
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_two_stage(
            _valid_6_activity_outline_json(),
            _valid_6_activity_agenda_json(),
        ),
    ) as chat_complete_mock:
        await _run_generation_pipeline(
            settings={"max_tokens": 2048},
            history=[{"role": "user", "content": "Need robust agenda"}],
            system_prompt="system",
        )

    assert chat_complete_mock.call_args_list[1].args[0]["max_tokens"] > 2048


@pytest.mark.asyncio
async def test_e2e_max_tokens_not_scaled_for_small_agenda() -> None:
    """Verify Stage 2 max_tokens does not shrink below configured base."""
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=[_valid_outline_json(2), _valid_agenda_json(2)]),
    ) as chat_complete_mock:
        await _run_generation_pipeline(
            settings={"max_tokens": 4096},
            history=[{"role": "user", "content": "Need short agenda"}],
            system_prompt="system",
        )

    assert chat_complete_mock.call_args_list[1].args[0]["max_tokens"] == 4096


def test_e2e_pipeline_meta_not_leaked_to_audit_log(authenticated_client) -> None:
    """Verify endpoint audit payload omits response-only pipeline metadata."""
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with (
        patch(
            "app.routers.meeting_designer.chat_complete",
            new=_mock_chat_complete_two_stage(
                _valid_6_activity_outline_json(),
                _valid_6_activity_agenda_json(),
            ),
        ),
        patch("app.routers.meeting_designer._persist_meeting_designer_log") as audit_mock,
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 200
    assert audit_mock.called
    parsed_output = audit_mock.call_args.kwargs.get("parsed_output")
    assert isinstance(parsed_output, dict)
    assert "agenda" in parsed_output
    assert "_pipeline_meta" not in parsed_output


def test_response_contract_backward_compatible(authenticated_client) -> None:
    """Verify response keeps original keys and adds only _pipeline_meta."""
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_two_stage(
            _valid_6_activity_outline_json(),
            _valid_6_activity_agenda_json(),
        ),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    body = response.json()
    assert response.status_code == 200
    for key in [
        "success",
        "meeting_summary",
        "session_name",
        "evaluation_criteria",
        "design_rationale",
        "complexity",
        "phases",
        "agenda",
    ]:
        assert key in body
    assert "_pipeline_meta" in body


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


@pytest.mark.asyncio
async def test_e2e_outline_self_corrects_hallucinated_type() -> None:
    """Verify outline stage retries and self-corrects an invalid tool_type."""
    outline_invalid = _invalid_outline_json("hallucinated_type")
    outline_valid = _valid_outline_json(3)
    agenda_valid = _valid_agenda_json(3)
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence(outline_invalid, outline_valid, agenda_valid),
    ) as chat_complete_mock:
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Design a workshop"}],
            system_prompt="system",
        )

    outline_tool_types = [item["tool_type"] for item in json.loads(outline_valid)["outline"]]
    agenda_tool_types = [item["tool_type"] for item in result["agenda"]]
    assert result["success"] is True
    assert agenda_tool_types == outline_tool_types
    assert chat_complete_mock.call_count == 3


@pytest.mark.asyncio
async def test_e2e_agenda_self_corrects_empty_instructions() -> None:
    """Verify full-json stage retries and fixes empty instructions."""
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence(
            _valid_outline_json(3),
            _invalid_agenda_json("empty_instructions"),
            _valid_agenda_json(3),
        ),
    ) as chat_complete_mock:
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Need clear instructions"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert all(item["instructions"] for item in result["agenda"])
    assert chat_complete_mock.call_count == 3


@pytest.mark.asyncio
async def test_e2e_parse_error_then_valid_json() -> None:
    """Verify prose-wrapped output is corrected into valid JSON on retry."""
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence(
            "Sure! Here's your outline: {...",
            _valid_outline_json(3),
            _valid_agenda_json(3),
        ),
    ) as chat_complete_mock:
        result = await _run_generation_pipeline(
            settings={},
            history=[{"role": "user", "content": "Generate agenda"}],
            system_prompt="system",
        )

    assert result["success"] is True
    assert chat_complete_mock.call_count == 3


def test_e2e_all_retries_exhausted_returns_502(authenticated_client) -> None:
    """Verify outline retry exhaustion returns HTTP 502 with actionable detail."""
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    invalid_outline = _invalid_outline_json("hallucinated_type")
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence(invalid_outline, invalid_outline, invalid_outline),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    detail = response.json()["detail"]
    assert response.status_code == 502
    assert "3 attempt(s)" in detail
    assert "tool_type" in detail
    assert "workshop" in detail


def test_e2e_provider_error_returns_502_no_retry(authenticated_client) -> None:
    """Verify provider failures return 502 and are not retried."""
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=AsyncMock(side_effect=AIProviderError("provider failure")),
    ) as chat_complete_mock:
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    assert response.status_code == 502
    assert chat_complete_mock.call_count == 1


@pytest.mark.asyncio
async def test_e2e_5_activity_pipeline_with_retry() -> None:
    """Verify 5-activity pipeline recovers from one invalid full-json attempt."""
    outline_json = _valid_outline_json(5)
    invalid_agenda_data = json.loads(_valid_agenda_json(5))
    invalid_agenda_data["agenda"][2]["tool_type"] = "roundtable"
    invalid_agenda_json = json.dumps(invalid_agenda_data)
    corrected_agenda_json = _valid_agenda_json(5)

    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence(outline_json, invalid_agenda_json, corrected_agenda_json),
    ) as chat_complete_mock:
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
    assert "roundtable" not in returned_tool_types
    assert chat_complete_mock.call_count == 3


def test_response_contract_unchanged_after_retry(authenticated_client) -> None:
    """Verify successful retries do not leak retry metadata into endpoint payload."""
    payload = {"messages": [{"role": "user", "content": "Need an agenda"}]}
    with patch(
        "app.routers.meeting_designer.chat_complete",
        new=_mock_chat_complete_sequence("not-json", _valid_outline_json(3), _valid_agenda_json(3)),
    ):
        response = authenticated_client.post("/api/meeting-designer/generate-agenda", json=payload)

    body = response.json()
    assert response.status_code == 200
    assert set(body.keys()) == {
        "success",
        "meeting_summary",
        "session_name",
        "evaluation_criteria",
        "design_rationale",
        "complexity",
        "phases",
        "agenda",
        "_pipeline_meta",
    }
    assert "attempts_made" not in body
    assert "error_trail" not in body
    assert "validation_errors" not in body


def test_chat_endpoint_unaffected_by_retry(authenticated_client) -> None:
    """Verify chat SSE endpoint behavior remains unchanged by retry logic."""
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


def test_status_endpoint_unaffected_by_retry(authenticated_client) -> None:
    """Verify status endpoint response shape remains unchanged by retry logic."""
    response = authenticated_client.get("/api/meeting-designer/status")
    body = response.json()
    assert response.status_code == 200
    assert "configured" in body
    assert isinstance(body["configured"], bool)


def test_logs_endpoint_unaffected_by_retry(authenticated_client) -> None:
    """Verify logs endpoint response shape remains unchanged by retry logic."""
    response = authenticated_client.get("/api/meeting-designer/logs")
    body = response.json()
    assert response.status_code == 200
    assert isinstance(body.get("items"), list)
    assert isinstance(body.get("count"), int)


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
    """Ensure generate-agenda delegates prompt construction to the pipeline."""
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
    # Route delegates to _run_generation_pipeline(), which owns prompt assembly.
    assert call_counter["count"] == 0


# ---------------------------------------------------------------------------
# Phase 1 — Pattern Library Unification (Quartz Bramble)
# ---------------------------------------------------------------------------

def test_system_prompt_contains_pattern_library() -> None:
    """Step 1: system_suffix uses a unified COLLABORATION PATTERN LIBRARY.

    Verifies:
    - Output contains the unified section header.
    - Old separate section headers are absent.
    - At least the three anchor patterns (Simple Consensus, Classic,
      Deep Evaluation) are named in the output.
    """
    from app.services.meeting_designer_prompt import build_system_prompt

    prompt = build_system_prompt()

    # Unified section must be present
    assert "COLLABORATION PATTERN LIBRARY" in prompt

    # Old separate section headers must NOT appear
    assert "STANDARD SEQUENCES" not in prompt
    assert "EXTENDED SEQUENCES" not in prompt

    # At least the three anchor patterns must be present
    assert "Simple Consensus" in prompt
    assert "Classic" in prompt
    assert "Deep Evaluation" in prompt


def test_system_prompt_no_formulaic_track_rules() -> None:
    """Step 2: system_suffix BREAKOUT TRACK DESIGN GUIDELINES are pattern-aware.

    Verifies:
    - Formulaic arc language is absent.
    - Formulaic Activity 1/2 labels are absent.
    - Hard single-activity constraint is present.
    - Collaboration Pattern Library reference is present.
    """
    from app.services.meeting_designer_prompt import build_system_prompt

    prompt = build_system_prompt()

    # Formulaic prescriptions must be gone
    assert "diverge \u2192 organize \u2192 converge arc" not in prompt
    assert "Activity 1 (Generate)" not in prompt
    assert "Activity 2 (Organize" not in prompt

    # Hard constraint and pattern-library reference must be present
    assert "single-activity" in prompt
    assert "Collaboration Pattern Library" in prompt


def test_yaml_generate_agenda_pattern_library() -> None:
    """Step 3: generate_agenda YAML template uses pattern-selection guide.

    Verifies:
    - Quick Convergence and Nested Decomposition patterns are named.
    - Old Activity 1 (Generate) label is absent.
    - New section heading is present.
    """
    from app.config.loader import get_meeting_designer_prompt_templates

    templates = get_meeting_designer_prompt_templates()
    generate_agenda = templates["generate_agenda"]

    # Named patterns must be present
    assert "Quick Convergence" in generate_agenda
    assert "Nested Decomposition" in generate_agenda

    # Old fixed-recipe label must be gone
    assert "Activity 1 (Generate)" not in generate_agenda

    # Updated section heading must be present
    assert "Within-track pattern selection" in generate_agenda


def test_build_generation_prompt_pattern_library() -> None:
    """Step 4: build_generation_prompt() uses pattern-selection guide.

    Verifies:
    - Quick Convergence and Nested Decomposition patterns are named.
    - Old Activity 1 (Generate) label is absent.
    - Old diverge arc prescription is absent.
    - Collaboration Pattern Library reference is present.
    """
    from app.services.meeting_designer_prompt import build_generation_prompt

    prompt = build_generation_prompt()

    # Named patterns must be present
    assert "Quick Convergence" in prompt
    assert "Nested Decomposition" in prompt

    # Old fixed-recipe labels must be gone
    assert "Activity 1 (Generate)" not in prompt
    assert "diverge \u2192 organize/reduce \u2192 converge arc" not in prompt

    # Pattern Library reference must be present
    assert "Collaboration Pattern Library" in prompt


def test_build_outline_prompt_pattern_library() -> None:
    """Step 5: build_outline_prompt() uses pattern-aware multi-track rules.

    Verifies:
    - Collaboration Pattern Library reference is present.
    - Old diverge arc prescription is absent.
    """
    from app.services.meeting_designer_prompt import build_outline_prompt

    prompt = build_outline_prompt()

    # Pattern Library reference must be present
    assert "Collaboration Pattern Library" in prompt

    # Old arc prescription must be gone
    assert "diverge \u2192 organize/reduce \u2192 converge arc" not in prompt


def test_outline_prompt_includes_track_schema() -> None:
    """Phase 3 Step 1: build_outline_prompt() includes optional track metadata schema."""
    from app.services.meeting_designer_prompt import build_outline_prompt

    prompt = build_outline_prompt()

    assert '"track_id"' in prompt
    assert '"tracks"' in prompt
    assert '"goal"' in prompt
    assert "only when the conversation discussed breakout" in prompt


def test_outline_prompt_pattern_library_guidance() -> None:
    """Phase 3 Step 2: build_outline_prompt() includes pattern-library guidance."""
    from app.services.meeting_designer_prompt import build_outline_prompt

    prompt = build_outline_prompt()

    assert "Quick Convergence" in prompt
    assert "Collaboration Pattern Library" in prompt
    assert "diverge \u2192 organize/reduce \u2192 converge arc" not in prompt


def test_validate_outline_multi_track_enforcement() -> None:
    """Phase 3 Step 3: validate_outline() enforces multi-track structural rules."""
    from app.services.agenda_validator import validate_outline

    # (a) Valid: 2 tracks, each with 2+ activities
    valid_outline = {
        "meeting_summary": "Multi-track planning",
        "tracks": [
            {"track_id": "track_a", "label": "Budget"},
            {"track_id": "track_b", "label": "Technology"},
        ],
        "outline": [
            {
                "tool_type": "brainstorming",
                "title": "Budget options",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Open budget possibilities.",
                "track_id": "track_a",
            },
            {
                "tool_type": "voting",
                "title": "Budget shortlist",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Down-select budget options.",
                "track_id": "track_a",
            },
            {
                "tool_type": "brainstorming",
                "title": "Tech options",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Open technology possibilities.",
                "track_id": "track_b",
            },
            {
                "tool_type": "voting",
                "title": "Tech shortlist",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Down-select technology options.",
                "track_id": "track_b",
            },
        ],
    }
    valid_result = validate_outline(valid_outline)
    assert valid_result.valid is True
    assert valid_result.errors == []

    # (b) Invalid: one declared track has only one activity
    invalid_outline = {
        "meeting_summary": "Multi-track planning",
        "tracks": [
            {"track_id": "track_a", "label": "Budget"},
            {"track_id": "track_b", "label": "Technology"},
        ],
        "outline": [
            {
                "tool_type": "brainstorming",
                "title": "Budget options",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Open budget possibilities.",
                "track_id": "track_a",
            },
            {
                "tool_type": "voting",
                "title": "Budget shortlist",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Down-select budget options.",
                "track_id": "track_a",
            },
            {
                "tool_type": "brainstorming",
                "title": "Tech options",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Open technology possibilities.",
                "track_id": "track_b",
            },
        ],
    }
    invalid_result = validate_outline(invalid_outline)
    assert invalid_result.valid is False
    assert any(
        err.message == "Track 'track_b' (Technology) has 1 activity but must have at least 2."
        for err in invalid_result.errors
    )

    # (c) Warning: activity references undeclared track_id
    warning_outline = {
        "meeting_summary": "Multi-track planning",
        "tracks": [
            {"track_id": "track_a", "label": "Budget"},
            {"track_id": "track_b", "label": "Technology"},
        ],
        "outline": [
            {
                "tool_type": "brainstorming",
                "title": "Budget options",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Open budget possibilities.",
                "track_id": "track_a",
            },
            {
                "tool_type": "voting",
                "title": "Budget shortlist",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Down-select budget options.",
                "track_id": "track_a",
            },
            {
                "tool_type": "brainstorming",
                "title": "Tech options",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Open technology possibilities.",
                "track_id": "track_b",
            },
            {
                "tool_type": "voting",
                "title": "Tech shortlist",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Down-select technology options.",
                "track_id": "track_b",
            },
            {
                "tool_type": "brainstorming",
                "title": "Unmapped deep dive",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Extra track experiment.",
                "track_id": "track_z",
            },
        ],
    }
    warning_result = validate_outline(warning_outline)
    assert warning_result.valid is True
    assert any(
        w.message == "Activity 'Unmapped deep dive' references undeclared track_id 'track_z'."
        for w in warning_result.warnings
    )

    # (d) No tracks array: backward-compatible pass
    no_tracks_outline = {
        "meeting_summary": "Simple planning",
        "outline": [
            {
                "tool_type": "brainstorming",
                "title": "Generate ideas",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Collect options.",
            },
            {
                "tool_type": "voting",
                "title": "Choose next step",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Pick a direction.",
            },
        ],
    }
    no_tracks_result = validate_outline(no_tracks_outline)
    assert no_tracks_result.valid is True
    assert no_tracks_result.errors == []


def test_generation_prompt_renders_track_grouped_outline() -> None:
    """Phase 3 Step 4: build_generation_prompt() groups outline by tracks when provided."""
    from app.services.meeting_designer_prompt import build_generation_prompt

    outline_payload = {
        "tracks": [
            {"track_id": "track_a", "label": "Budget Review", "goal": "Prioritize budget options"},
            {"track_id": "track_b", "label": "Technology Assessment", "goal": "Prioritize tech options"},
        ],
        "outline": [
            {"tool_type": "brainstorming", "title": "Opening Discussion", "track_id": None},
            {"tool_type": "brainstorming", "title": "Generate Budget Ideas", "track_id": "track_a"},
            {"tool_type": "categorization", "title": "Group Budget Ideas", "track_id": "track_a"},
            {"tool_type": "voting", "title": "Vote Budget Priorities", "track_id": "track_a"},
            {"tool_type": "brainstorming", "title": "Generate Tech Options", "track_id": "track_b"},
            {"tool_type": "voting", "title": "Evaluate Tech Options", "track_id": "track_b"},
        ],
    }

    grouped_prompt = build_generation_prompt(outline=outline_payload)
    assert "track groupings" in grouped_prompt
    assert "Plenary activities:" in grouped_prompt
    assert 'Track "Budget Review" (track_a):' in grouped_prompt
    assert 'Track "Technology Assessment" (track_b):' in grouped_prompt
    assert grouped_prompt.find("Plenary activities:") < grouped_prompt.find('Track "Budget Review" (track_a):')

    # Fallback: outline list without tracks remains flat.
    flat_prompt = build_generation_prompt(outline=outline_payload["outline"])
    assert "Plenary activities:" not in flat_prompt
    assert 'Track "Budget Review" (track_a):' not in flat_prompt
    assert "1. Opening Discussion [brainstorming]" in flat_prompt


def test_outline_prompt_track_reasoning_guidance() -> None:
    """Phase 3 Step 5: outline prompt includes conversation-aware track reasoning guidance."""
    from app.services.meeting_designer_prompt import build_outline_prompt

    prompt = build_outline_prompt()

    assert "Track-aware reasoning" in prompt
    assert "breakout" in prompt
    assert "rationale" in prompt


def test_extract_phase_track_maps_basic() -> None:
    """Phase 4 Step 1: _extract_phase_track_maps() returns expected maps/sets."""
    from app.services.agenda_validator import _extract_phase_track_maps

    agenda_payload = {
        "phases": [
            {
                "phase_id": "phase_1",
                "title": "Open",
                "phase_type": "plenary",
            },
            {
                "phase_id": "phase_2",
                "title": "Breakout",
                "phase_type": "parallel",
                "tracks": [
                    {"track_id": "track_2a", "label": "Budget"},
                    {"track_id": "track_2b", "label": "Technology"},
                ],
            },
            {
                "phase_id": "phase_3",
                "title": "Reconverge",
                "phase_type": "plenary",
            },
        ],
        "agenda": [],
    }

    declared_phases, declared_tracks, parallel_phase_ids = _extract_phase_track_maps(agenda_payload)

    assert len(declared_phases) == 3
    assert set(declared_phases.keys()) == {"phase_1", "phase_2", "phase_3"}
    assert declared_tracks == {"track_2a": "phase_2", "track_2b": "phase_2"}
    assert parallel_phase_ids == {"phase_2"}

    empty_declared_phases, empty_declared_tracks, empty_parallel_phase_ids = _extract_phase_track_maps(
        {"phases": []}
    )
    assert empty_declared_phases == {}
    assert empty_declared_tracks == {}
    assert empty_parallel_phase_ids == set()


def test_validate_agenda_dangling_phase_id() -> None:
    """Phase 4 Step 2: validate_agenda() flags agenda items with undeclared phase_id."""
    from app.services.agenda_validator import validate_agenda

    invalid_agenda = {
        "meeting_summary": "Phase reference checks",
        "design_rationale": "Test dangling phase IDs.",
        "phases": [
            {
                "phase_id": "phase_1",
                "title": "Opening",
                "phase_type": "plenary",
            }
        ],
        "agenda": [
            {
                "tool_type": "brainstorming",
                "title": "Generate options",
                "instructions": "Generate ideas.",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Create options.",
                "config_overrides": {},
                "phase_id": "phase_1",
            },
            {
                "tool_type": "voting",
                "title": "Select options",
                "instructions": "Vote on ideas.",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Pick winners.",
                "config_overrides": {},
                "phase_id": "phase_99",
            },
        ],
    }

    invalid_result = validate_agenda(invalid_agenda)
    assert invalid_result.valid is False
    phase_errors = [e for e in invalid_result.errors if e.field == "phase_id"]
    assert len(phase_errors) == 1
    assert "phase_99" in phase_errors[0].message
    assert "not declared" in phase_errors[0].message

    valid_agenda = {
        **invalid_agenda,
        "agenda": [
            {**invalid_agenda["agenda"][0]},
            {**invalid_agenda["agenda"][1], "phase_id": "phase_1"},
        ],
    }
    valid_result = validate_agenda(valid_agenda)
    assert valid_result.valid is True
    assert not any(e.field == "phase_id" for e in valid_result.errors)


def test_validate_agenda_dangling_track_id() -> None:
    """Phase 4 Step 3: validate_agenda() flags agenda items with undeclared track_id."""
    from app.services.agenda_validator import validate_agenda

    invalid_agenda = {
        "meeting_summary": "Track reference checks",
        "design_rationale": "Test dangling track IDs.",
        "phases": [
            {
                "phase_id": "phase_1",
                "title": "Breakout",
                "phase_type": "parallel",
                "tracks": [{"track_id": "track_2a", "label": "Budget"}],
            },
            {
                "phase_id": "phase_2",
                "title": "Reconverge",
                "phase_type": "plenary",
            },
        ],
        "agenda": [
            {
                "tool_type": "brainstorming",
                "title": "Plenary kickoff",
                "instructions": "Set context.",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Create shared frame.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": None,
            },
            {
                "tool_type": "brainstorming",
                "title": "Budget options",
                "instructions": "Generate budget ideas.",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Create options.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": "track_2a",
            },
            {
                "tool_type": "voting",
                "title": "Budget shortlist",
                "instructions": "Vote on budget ideas.",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Select budget candidates.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": "track_2a",
            },
            {
                "tool_type": "voting",
                "title": "Ghost track vote",
                "instructions": "Vote in ghost track.",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Simulate dangling reference.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": "track_GHOST",
            },
        ],
    }

    invalid_result = validate_agenda(invalid_agenda)
    assert invalid_result.valid is False
    track_errors = [e for e in invalid_result.errors if e.field == "track_id"]
    assert len(track_errors) == 1
    assert "track_GHOST" in track_errors[0].message
    assert "not declared" in track_errors[0].message

    valid_agenda = {
        **invalid_agenda,
        "agenda": [
            {**invalid_agenda["agenda"][0]},
            {**invalid_agenda["agenda"][1]},
            {**invalid_agenda["agenda"][2]},
            {**invalid_agenda["agenda"][3], "track_id": "track_2a"},
        ],
    }
    valid_result = validate_agenda(valid_agenda)
    assert valid_result.valid is True
    assert not any(e.field == "track_id" for e in valid_result.errors)


def test_validate_agenda_single_activity_track() -> None:
    """Phase 4 Step 4: validate_agenda() enforces minimum 2 activities per parallel track."""
    from app.services.agenda_validator import validate_agenda

    invalid_agenda = {
        "meeting_summary": "Parallel track checks",
        "design_rationale": "Enforce multi-activity track invariant.",
        "phases": [
            {
                "phase_id": "phase_1",
                "title": "Breakout Work",
                "phase_type": "parallel",
                "tracks": [
                    {"track_id": "track_2a", "label": "Budget"},
                    {"track_id": "track_2b", "label": "Technology"},
                ],
            },
            {
                "phase_id": "phase_2",
                "title": "Reconverge",
                "phase_type": "plenary",
            }
        ],
        "agenda": [
            {
                "tool_type": "brainstorming",
                "title": "Budget options",
                "instructions": "Generate budget options.",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Open budget idea space.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": "track_2a",
            },
            {
                "tool_type": "categorization",
                "title": "Budget clustering",
                "instructions": "Group budget options by theme.",
                "duration_minutes": 10,
                "collaboration_pattern": "Organize",
                "rationale": "Prepare for selection.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": "track_2a",
            },
            {
                "tool_type": "voting",
                "title": "Budget shortlist vote",
                "instructions": "Vote top budget options.",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Create shortlist.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": "track_2a",
            },
            {
                "tool_type": "brainstorming",
                "title": "Tech options",
                "instructions": "Generate technology options.",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Open technology idea space.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": "track_2b",
            },
        ],
    }

    invalid_result = validate_agenda(invalid_agenda)
    assert invalid_result.valid is False
    assert any("track_2b" in err.message and "requires at least 2" in err.message for err in invalid_result.errors)

    valid_agenda = {
        **invalid_agenda,
        "agenda": [
            *invalid_agenda["agenda"],
            {
                "tool_type": "voting",
                "title": "Tech shortlist vote",
                "instructions": "Vote top technology options.",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Create shortlist.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": "track_2b",
            },
        ],
    }
    valid_result = validate_agenda(valid_agenda)
    assert valid_result.valid is True
    assert not any("track_2b" in err.message and "requires at least 2" in err.message for err in valid_result.errors)


def test_validate_agenda_missing_reconvergence() -> None:
    """Phase 4 Step 5: validate_agenda() enforces parallel-phase reconvergence ordering."""
    from app.services.agenda_validator import validate_agenda

    def _agenda_with_phases(phases: list[dict]) -> dict:
        return {
            "meeting_summary": "Reconvergence checks",
            "design_rationale": "Ensure parallel phases reconverge to plenary.",
            "phases": phases,
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Track A ideation",
                    "instructions": "Generate ideas for track A.",
                    "duration_minutes": 10,
                    "collaboration_pattern": "Generate",
                    "rationale": "Open options.",
                    "config_overrides": {},
                    "phase_id": "phase_2",
                    "track_id": "track_2a",
                },
                {
                    "tool_type": "voting",
                    "title": "Track A selection",
                    "instructions": "Vote top options for track A.",
                    "duration_minutes": 10,
                    "collaboration_pattern": "Evaluate",
                    "rationale": "Converge track A.",
                    "config_overrides": {},
                    "phase_id": "phase_2",
                    "track_id": "track_2a",
                },
                {
                    "tool_type": "brainstorming",
                    "title": "Track B ideation",
                    "instructions": "Generate ideas for track B.",
                    "duration_minutes": 10,
                    "collaboration_pattern": "Generate",
                    "rationale": "Open options.",
                    "config_overrides": {},
                    "phase_id": "phase_2",
                    "track_id": "track_2b",
                },
                {
                    "tool_type": "voting",
                    "title": "Track B selection",
                    "instructions": "Vote top options for track B.",
                    "duration_minutes": 10,
                    "collaboration_pattern": "Evaluate",
                    "rationale": "Converge track B.",
                    "config_overrides": {},
                    "phase_id": "phase_2",
                    "track_id": "track_2b",
                },
            ],
        }

    # (a) Valid: plenary -> parallel -> plenary
    valid_phases = [
        {"phase_id": "phase_1", "title": "Open", "phase_type": "plenary"},
        {
            "phase_id": "phase_2",
            "title": "Breakout",
            "phase_type": "parallel",
            "tracks": [{"track_id": "track_2a"}, {"track_id": "track_2b"}],
        },
        {"phase_id": "phase_3", "title": "Reconverge", "phase_type": "plenary"},
    ]
    valid_result = validate_agenda(_agenda_with_phases(valid_phases))
    assert valid_result.valid is True

    # (b) Invalid: plenary -> parallel (last phase)
    missing_reconvergence_phases = [
        {"phase_id": "phase_1", "title": "Open", "phase_type": "plenary"},
        {
            "phase_id": "phase_2",
            "title": "Breakout",
            "phase_type": "parallel",
            "tracks": [{"track_id": "track_2a"}, {"track_id": "track_2b"}],
        },
    ]
    missing_reconvergence_result = validate_agenda(_agenda_with_phases(missing_reconvergence_phases))
    assert missing_reconvergence_result.valid is False
    assert any(
        "phase_2" in err.message and "last phase" in err.message
        for err in missing_reconvergence_result.errors
    )

    # (c) Invalid: parallel -> parallel -> plenary
    parallel_then_parallel_phases = [
        {
            "phase_id": "phase_1",
            "title": "Parallel A",
            "phase_type": "parallel",
            "tracks": [{"track_id": "track_2a"}, {"track_id": "track_2b"}],
        },
        {
            "phase_id": "phase_2",
            "title": "Parallel B",
            "phase_type": "parallel",
            "tracks": [{"track_id": "track_2a"}, {"track_id": "track_2b"}],
        },
        {"phase_id": "phase_3", "title": "Reconverge", "phase_type": "plenary"},
    ]
    parallel_then_parallel_result = validate_agenda(_agenda_with_phases(parallel_then_parallel_phases))
    assert parallel_then_parallel_result.valid is False
    assert any(
        "phase_1" in err.message and "followed by another parallel phase ('phase_2')" in err.message
        for err in parallel_then_parallel_result.errors
    )


def test_validate_agenda_structural_checks_wired() -> None:
    """Phase 4 Step 6: validate_agenda() runs structural checks without false positives on valid input."""
    from app.services.agenda_validator import validate_agenda

    valid_agenda = {
        "meeting_summary": "Well-formed multi-track session",
        "design_rationale": "Plenary framing, parallel work, plenary reconvergence.",
        "phases": [
            {"phase_id": "phase_1", "title": "Open", "phase_type": "plenary"},
            {
                "phase_id": "phase_2",
                "title": "Breakout",
                "phase_type": "parallel",
                "tracks": [
                    {"track_id": "track_2a", "label": "Budget"},
                    {"track_id": "track_2b", "label": "Technology"},
                ],
            },
            {"phase_id": "phase_3", "title": "Reconverge", "phase_type": "plenary"},
        ],
        "agenda": [
            {
                "tool_type": "brainstorming",
                "title": "Kickoff framing",
                "instructions": "Frame goals and constraints.",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Align participants before breakouts.",
                "config_overrides": {},
                "phase_id": "phase_1",
                "track_id": None,
            },
            {
                "tool_type": "brainstorming",
                "title": "Budget ideas",
                "instructions": "Generate budget options.",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Open budget option space.",
                "config_overrides": {},
                "phase_id": "phase_2",
                "track_id": "track_2a",
            },
            {
                "tool_type": "categorization",
                "title": "Budget clustering",
                "instructions": "Cluster budget options.",
                "duration_minutes": 10,
                "collaboration_pattern": "Organize",
                "rationale": "Prepare budget options for evaluation.",
                "config_overrides": {},
                "phase_id": "phase_2",
                "track_id": "track_2a",
            },
            {
                "tool_type": "voting",
                "title": "Budget shortlist",
                "instructions": "Vote budget shortlist.",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Converge budget choices.",
                "config_overrides": {},
                "phase_id": "phase_2",
                "track_id": "track_2a",
            },
            {
                "tool_type": "brainstorming",
                "title": "Technology ideas",
                "instructions": "Generate technology options.",
                "duration_minutes": 10,
                "collaboration_pattern": "Generate",
                "rationale": "Open technology option space.",
                "config_overrides": {},
                "phase_id": "phase_2",
                "track_id": "track_2b",
            },
            {
                "tool_type": "voting",
                "title": "Technology shortlist",
                "instructions": "Vote technology shortlist.",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Converge technology choices.",
                "config_overrides": {},
                "phase_id": "phase_2",
                "track_id": "track_2b",
            },
            {
                "tool_type": "voting",
                "title": "Reconvergence synthesis",
                "instructions": "Share outcomes and align final priorities.",
                "duration_minutes": 10,
                "collaboration_pattern": "Evaluate",
                "rationale": "Merge track outcomes into a single direction.",
                "config_overrides": {},
                "phase_id": "phase_3",
                "track_id": None,
            },
        ],
    }

    result = validate_agenda(valid_agenda)
    assert result.valid is True
    assert result.errors == []


# ---------------------------------------------------------------------------
# Phase 2 — Sequencing Intelligence (Velvet Anchor)
# ---------------------------------------------------------------------------


def test_activity_block_includes_when_not_to_use() -> None:
    """Phase 2 Step 1: _format_activity_block() renders 'Avoid when:' from when_not_to_use.

    Verifies:
    - 'Avoid when:' label appears when when_not_to_use is a non-empty string.
    - The contraindication text is included verbatim.
    - 'Avoid when:' is absent when when_not_to_use is an empty string.
    """
    from app.services.meeting_designer_prompt import _format_activity_block

    activity_with_contraindication = {
        "tool_type": "categorization",
        "label": "Categorization",
        "collaboration_patterns": ["Organize"],
        "description": "Group items into buckets.",
        "thinklets": [],
        "when_to_use": "When ideas need thematic structure.",
        "when_not_to_use": "When no prior items exist; requires input from a prior activity.",
        "bias_mitigation": [],
        "typical_duration_minutes": {"min": 10, "max": 20},
        "default_config": {},
    }

    block = _format_activity_block(1, activity_with_contraindication)

    assert "Avoid when:" in block
    assert "requires input from a prior activity" in block

    # Now verify the field is suppressed when empty
    activity_no_contraindication = {**activity_with_contraindication, "when_not_to_use": ""}
    block_no_avoid = _format_activity_block(1, activity_no_contraindication)

    assert "Avoid when:" not in block_no_avoid


def test_activity_block_includes_input_requirements() -> None:
    """Phase 2 Step 2: _format_activity_block() renders 'Requires:' from input_requirements.

    Verifies:
    - 'Requires:' label appears when input_requirements is a non-empty string.
    - Input requirements text is included verbatim.
    - 'Requires:' is absent when input_requirements is an empty string.
    """
    from app.services.meeting_designer_prompt import _format_activity_block

    activity_with_requirements = {
        "tool_type": "categorization",
        "label": "Categorization",
        "collaboration_patterns": ["Organize"],
        "description": "Group items into buckets.",
        "thinklets": [],
        "when_to_use": "When ideas need thematic structure.",
        "when_not_to_use": "When no prior items exist.",
        "input_requirements": "Requires a set of items from a prior activity.",
        "bias_mitigation": [],
        "typical_duration_minutes": {"min": 10, "max": 20},
        "default_config": {},
    }

    block = _format_activity_block(1, activity_with_requirements)

    assert "Requires: Requires a set of items" in block

    # Now verify the field is suppressed when empty
    activity_no_requirements = {**activity_with_requirements, "input_requirements": ""}
    block_no_requires = _format_activity_block(1, activity_no_requirements)

    assert "Requires:" not in block_no_requires


def test_activity_block_includes_output_characteristics() -> None:
    """Phase 2 Step 3: _format_activity_block() renders 'Produces:' from output_characteristics.

    Verifies:
    - 'Produces:' label appears when output_characteristics is a non-empty string.
    - Output characteristics text is included verbatim.
    - 'Produces:' is absent when output_characteristics is an empty string.
    """
    from app.services.meeting_designer_prompt import _format_activity_block

    activity_with_output = {
        "tool_type": "brainstorming",
        "label": "Brainstorming",
        "collaboration_patterns": ["Generate"],
        "description": "Generate many ideas quickly.",
        "thinklets": [],
        "when_to_use": "When you need broad option generation.",
        "when_not_to_use": "When immediate prioritization is required.",
        "input_requirements": "None required.",
        "output_characteristics": "Produces an unstructured list of candidate ideas.",
        "bias_mitigation": [],
        "typical_duration_minutes": {"min": 5, "max": 20},
        "default_config": {},
    }

    block = _format_activity_block(1, activity_with_output)

    assert "Produces:" in block
    assert "unstructured list of candidate ideas" in block

    # Now verify the field is suppressed when empty
    activity_no_output = {**activity_with_output, "output_characteristics": ""}
    block_no_output = _format_activity_block(1, activity_no_output)

    assert "Produces:" not in block_no_output


def test_all_plugins_have_sequencing_metadata() -> None:
    """Phase 2 Step 4: all catalog activities expose sequencing metadata.

    Verifies every activity has non-empty input_requirements and
    output_characteristics so prompt-level sequencing reasoning remains available.
    """
    from app.services.activity_catalog import get_enriched_activity_catalog

    catalog = get_enriched_activity_catalog()
    assert catalog, "Activity catalog should not be empty."

    for activity in catalog:
        tool_type = str(activity.get("tool_type") or "<unknown>")
        input_requirements = activity.get("input_requirements")
        output_characteristics = activity.get("output_characteristics")

        assert isinstance(input_requirements, str), (
            f"{tool_type} is missing string input_requirements metadata."
        )
        assert input_requirements.strip(), (
            f"{tool_type} has empty input_requirements metadata."
        )

        assert isinstance(output_characteristics, str), (
            f"{tool_type} is missing string output_characteristics metadata."
        )
        assert output_characteristics.strip(), (
            f"{tool_type} has empty output_characteristics metadata."
        )


def test_system_prompt_includes_sequencing_fields() -> None:
    """Phase 2 Step 5: build_system_prompt() exposes sequencing metadata lines."""
    from app.services.meeting_designer_prompt import build_system_prompt

    prompt = build_system_prompt()

    assert "Requires:" in prompt
    assert "Produces:" in prompt
    assert "Avoid when:" in prompt
    assert "None required" in prompt
    assert "prior activity" in prompt


def test_system_prompt_contains_pattern_tradeoff_examples() -> None:
    """Phase 5 Step 1: build_system_prompt() includes within-track pattern trade-off examples."""
    from app.services.meeting_designer_prompt import build_system_prompt

    prompt = build_system_prompt()

    assert "Within-track workflow discussion" in prompt
    assert "Quick Convergence" in prompt
    assert "Organized Convergence" in prompt
    assert "Rigorous Ranking" in prompt


def test_system_prompt_contains_facilitator_confirmation_gate() -> None:
    """Phase 5 Step 2: build_system_prompt() includes facilitator confirmation gate guidance."""
    from app.services.meeting_designer_prompt import build_system_prompt

    prompt = build_system_prompt()

    assert "Facilitator confirmation" in prompt
    assert "Which workflow" in prompt
    assert "Never silently choose a pattern" in prompt


def test_system_prompt_contains_time_budget_reasoning() -> None:
    """Phase 5 Step 3: build_system_prompt() includes time-budget reasoning guidance."""
    from app.services.meeting_designer_prompt import build_system_prompt

    prompt = build_system_prompt()

    assert "Time-budget reasoning" in prompt
    assert "over-budget" in prompt
    assert "estimated total duration" in prompt


def test_system_prompt_contains_per_track_differentiation() -> None:
    """Phase 5 Step 4: build_system_prompt() includes per-track differentiation guidance."""
    from app.services.meeting_designer_prompt import build_system_prompt

    prompt = build_system_prompt()

    assert "Per-track differentiation" in prompt
    assert "Different tracks may have different goals" in prompt
    assert "Shortlist" in prompt
    assert "Ranked priority list" in prompt


def test_build_system_prompt_docstring_reflects_design_discussion() -> None:
    """Phase 5 Step 5: build_system_prompt() docstring reflects design discussion guidance."""
    from app.services.meeting_designer_prompt import build_system_prompt

    doc = inspect.getdoc(build_system_prompt) or ""
    normalized_doc = " ".join(doc.split())
    assert "within-track workflow pattern trade-offs" in normalized_doc
