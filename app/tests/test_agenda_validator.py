"""Tests for COPPER-HERON-3 validator skeleton."""

import inspect

import app.services.agenda_validator as agenda_validator_module
from app.services.agenda_validator import (
    AgendaFieldError,
    AgendaValidationResult,
    validate_agenda,
    validate_outline,
)


def _make_activity(**overrides):
    activity = {
        "tool_type": "brainstorming",
        "title": "Collect ideas",
        "instructions": "Generate options.",
        "duration_minutes": 15,
        "collaboration_pattern": "Generate",
        "rationale": "Diverge first.",
        "config_overrides": {},
    }
    activity.update(overrides)
    return activity


def _make_agenda(activities, **envelope_overrides):
    payload = {
        "meeting_summary": "Summary",
        "design_rationale": "Rationale",
        "agenda": activities,
    }
    payload.update(envelope_overrides)
    return payload


def test_result_dataclasses_exist() -> None:
    error = AgendaFieldError(
        activity_index=1,
        field="tool_type",
        message="Unknown tool_type",
        level="error",
    )
    result = AgendaValidationResult(valid=False, errors=[error], warnings=[])

    assert error.activity_index == 1
    assert error.field == "tool_type"
    assert error.message == "Unknown tool_type"
    assert error.level == "error"
    assert result.valid is False
    assert result.errors == [error]
    assert result.warnings == []


def test_missing_agenda_key() -> None:
    result = validate_agenda({})

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].field == "agenda"
    assert result.errors[0].level == "error"
    assert result.warnings == []


def test_agenda_not_a_list() -> None:
    result = validate_agenda({"agenda": "oops"})

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].field == "agenda"
    assert result.errors[0].level == "error"


def test_empty_agenda_list() -> None:
    result = validate_agenda({"agenda": []})

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].field == "agenda"
    assert "no activities" in result.errors[0].message.lower()


def test_missing_meeting_summary_warns() -> None:
    result = validate_agenda(
        {
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                }
            ],
            "design_rationale": "Choose activities by goal.",
        }
    )

    assert result.valid is True
    assert result.errors == []
    assert len(result.warnings) == 1
    assert result.warnings[0].field == "meeting_summary"
    assert result.warnings[0].level == "warning"


def test_missing_design_rationale_warns() -> None:
    result = validate_agenda(
        {
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                }
            ],
            "meeting_summary": "Drive idea generation and synthesis.",
        }
    )

    assert result.valid is True
    assert result.errors == []
    assert len(result.warnings) == 1
    assert result.warnings[0].field == "design_rationale"
    assert result.warnings[0].level == "warning"


def test_validate_agenda_is_importable() -> None:
    assert callable(validate_agenda)


def test_valid_tool_type_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is True
    assert not [err for err in result.errors if err.field == "tool_type"]


def test_hallucinated_tool_type_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {"tool_type": "brainstorming"},
            {"tool_type": "voting"},
        ],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "discussion",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is False
    tool_errors = [err for err in result.errors if err.field == "tool_type"]
    assert len(tool_errors) == 1
    assert "available types are: brainstorming, voting" in tool_errors[0].message


def test_missing_tool_type_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [{"title": "Missing type"}],
        }
    )

    assert result.valid is False
    tool_errors = [err for err in result.errors if err.field == "tool_type"]
    assert len(tool_errors) == 1


def test_tool_type_case_insensitive(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "BRAINSTORMING",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is True
    assert not [err for err in result.errors if err.field == "tool_type"]


def test_multiple_activities_mixed_validity(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {"tool_type": "brainstorming"},
            {"tool_type": "voting"},
            {"tool_type": "rank_order_voting"},
        ],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                },
                {
                    "tool_type": "discussion",
                    "title": "Discuss options",
                    "instructions": "Discuss top ideas.",
                    "duration_minutes": 12,
                    "rationale": "Refine choices.",
                },
                {
                    "tool_type": "voting",
                    "title": "Vote",
                    "instructions": "Prioritize ideas.",
                    "duration_minutes": 8,
                    "rationale": "Converge to shortlist.",
                },
            ],
        }
    )

    assert result.valid is False
    tool_errors = [err for err in result.errors if err.field == "tool_type"]
    assert len(tool_errors) == 1
    assert tool_errors[0].activity_index == 1


def _mock_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}],
    )


def test_complete_activity_passes(monkeypatch) -> None:
    _mock_catalog(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate as many options as possible.",
                    "duration_minutes": 15,
                    "rationale": "Diverge before converging.",
                }
            ],
        }
    )

    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []


def test_missing_title_fails(monkeypatch) -> None:
    _mock_catalog(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "",
                    "instructions": "Prompt the group.",
                    "duration_minutes": 10,
                    "rationale": "Needed for direction.",
                }
            ],
        }
    )

    assert result.valid is False
    title_errors = [err for err in result.errors if err.field == "title"]
    assert len(title_errors) == 1


def test_missing_instructions_fails(monkeypatch) -> None:
    _mock_catalog(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [{"tool_type": "brainstorming", "title": "Capture ideas"}],
        }
    )

    assert result.valid is False
    instruction_errors = [err for err in result.errors if err.field == "instructions"]
    assert len(instruction_errors) == 1


def test_missing_duration_warns(monkeypatch) -> None:
    _mock_catalog(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Capture ideas",
                    "instructions": "Prompt the group.",
                    "rationale": "Needed for direction.",
                }
            ],
        }
    )

    assert result.valid is True
    duration_warnings = [warn for warn in result.warnings if warn.field == "duration_minutes"]
    assert len(duration_warnings) == 1


def test_missing_rationale_warns(monkeypatch) -> None:
    _mock_catalog(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Capture ideas",
                    "instructions": "Prompt the group.",
                    "duration_minutes": 15,
                }
            ],
        }
    )

    assert result.valid is True
    rationale_warnings = [warn for warn in result.warnings if warn.field == "rationale"]
    assert len(rationale_warnings) == 1


def test_whitespace_only_title_fails(monkeypatch) -> None:
    _mock_catalog(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "   ",
                    "instructions": "Prompt the group.",
                    "duration_minutes": 10,
                    "rationale": "Needed for direction.",
                }
            ],
        }
    )

    assert result.valid is False
    title_errors = [err for err in result.errors if err.field == "title"]
    assert len(title_errors) == 1


def test_valid_config_overrides_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "default_config": {"allow_anonymous": False, "allow_subcomments": True},
            }
        ],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                    "config_overrides": {"allow_anonymous": True},
                }
            ],
        }
    )

    assert result.valid is True
    assert not [warn for warn in result.warnings if warn.field == "config_overrides"]


def test_unknown_config_key_warns(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "default_config": {"allow_anonymous": False},
            }
        ],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                    "config_overrides": {"enable_reactions": True},
                }
            ],
        }
    )

    assert result.valid is True
    config_warnings = [warn for warn in result.warnings if warn.field == "config_overrides"]
    assert len(config_warnings) == 1
    assert "enable_reactions" in config_warnings[0].message


def test_config_overrides_not_a_dict_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "default_config": {"allow_anonymous": False},
            }
        ],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                    "config_overrides": "oops",
                }
            ],
        }
    )

    assert result.valid is False
    config_errors = [err for err in result.errors if err.field == "config_overrides"]
    assert len(config_errors) == 1


def test_missing_config_overrides_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "default_config": {"allow_anonymous": False},
            }
        ],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is True
    assert not [err for err in result.errors if err.field == "config_overrides"]
    assert not [warn for warn in result.warnings if warn.field == "config_overrides"]


def test_config_validation_skipped_for_invalid_tool_type(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "default_config": {"allow_anonymous": False},
            }
        ],
    )
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "discussion",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "rationale": "Diverge first.",
                    "config_overrides": {"enable_reactions": True},
                }
            ],
        }
    )

    assert result.valid is False
    tool_errors = [err for err in result.errors if err.field == "tool_type"]
    assert len(tool_errors) == 1
    assert not [err for err in result.errors if err.field == "config_overrides"]
    assert not [warn for warn in result.warnings if warn.field == "config_overrides"]


def _mock_catalog_with_ranges(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "default_config": {"allow_anonymous": False},
                "typical_duration_minutes": {"min": 5, "max": 30},
                "collaboration_patterns": ["Generate", "Clarify"],
            }
        ],
    )


def test_duration_in_range_no_warning(monkeypatch) -> None:
    _mock_catalog_with_ranges(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "collaboration_pattern": "Generate",
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is True
    assert not [warn for warn in result.warnings if warn.field == "duration_minutes"]


def test_duration_out_of_range_warns(monkeypatch) -> None:
    _mock_catalog_with_ranges(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 120,
                    "collaboration_pattern": "Generate",
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is True
    duration_warnings = [warn for warn in result.warnings if warn.field == "duration_minutes"]
    assert len(duration_warnings) == 1
    assert "outside typical range" in duration_warnings[0].message


def test_duration_zero_warns(monkeypatch) -> None:
    _mock_catalog_with_ranges(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 0,
                    "collaboration_pattern": "Generate",
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is True
    duration_warnings = [warn for warn in result.warnings if warn.field == "duration_minutes"]
    assert len(duration_warnings) >= 1
    assert any("outside typical range" in warn.message for warn in duration_warnings)


def test_valid_collaboration_pattern_passes(monkeypatch) -> None:
    _mock_catalog_with_ranges(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "collaboration_pattern": "Generate",
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is True
    assert not [warn for warn in result.warnings if warn.field == "collaboration_pattern"]


def test_invalid_collaboration_pattern_warns(monkeypatch) -> None:
    _mock_catalog_with_ranges(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "brainstorming",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 15,
                    "collaboration_pattern": "Synthesize",
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is True
    pattern_warnings = [warn for warn in result.warnings if warn.field == "collaboration_pattern"]
    assert len(pattern_warnings) == 1
    assert "Generate, Clarify" in pattern_warnings[0].message


def test_range_check_skipped_for_invalid_tool_type(monkeypatch) -> None:
    _mock_catalog_with_ranges(monkeypatch)
    result = validate_agenda(
        {
            "meeting_summary": "Summary",
            "design_rationale": "Rationale",
            "agenda": [
                {
                    "tool_type": "discussion",
                    "title": "Collect ideas",
                    "instructions": "Generate options.",
                    "duration_minutes": 120,
                    "collaboration_pattern": "Synthesize",
                    "rationale": "Diverge first.",
                }
            ],
        }
    )

    assert result.valid is False
    tool_errors = [err for err in result.errors if err.field == "tool_type"]
    assert len(tool_errors) == 1
    assert not [warn for warn in result.warnings if warn.field == "duration_minutes"]
    assert not [warn for warn in result.warnings if warn.field == "collaboration_pattern"]


def test_realistic_valid_5_activity_agenda(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "default_config": {"allow_anonymous": False, "allow_subcomments": True},
                "typical_duration_minutes": {"min": 5, "max": 30},
                "collaboration_patterns": ["Generate", "Clarify"],
            },
            {
                "tool_type": "categorization",
                "default_config": {"buckets": []},
                "typical_duration_minutes": {"min": 10, "max": 30},
                "collaboration_patterns": ["Organize", "Reduce"],
            },
            {
                "tool_type": "voting",
                "default_config": {"max_votes": 3},
                "typical_duration_minutes": {"min": 5, "max": 20},
                "collaboration_patterns": ["Evaluate", "Build Consensus"],
            },
            {
                "tool_type": "rank_order_voting",
                "default_config": {"randomize_order": False},
                "typical_duration_minutes": {"min": 5, "max": 20},
                "collaboration_patterns": ["Evaluate"],
            },
        ],
    )

    result = validate_agenda(
        _make_agenda(
            [
                _make_activity(
                    tool_type="brainstorming",
                    title="Generate ideas",
                    collaboration_pattern="Generate",
                    duration_minutes=15,
                ),
                _make_activity(
                    tool_type="categorization",
                    title="Cluster options",
                    collaboration_pattern="Organize",
                    duration_minutes=15,
                    config_overrides={"buckets": ["Now", "Later"]},
                ),
                _make_activity(
                    tool_type="voting",
                    title="Vote shortlist",
                    collaboration_pattern="Evaluate",
                    duration_minutes=10,
                    config_overrides={"max_votes": 3},
                ),
                _make_activity(
                    tool_type="rank_order_voting",
                    title="Rank finalists",
                    collaboration_pattern="Evaluate",
                    duration_minutes=10,
                    config_overrides={"randomize_order": True},
                ),
                _make_activity(
                    tool_type="voting",
                    title="Final commit vote",
                    collaboration_pattern="Build Consensus",
                    duration_minutes=8,
                    config_overrides={"max_votes": 1},
                ),
            ]
        )
    )

    assert result.valid is True
    assert result.errors == []


def test_realistic_invalid_agenda_multiple_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "default_config": {"allow_anonymous": False},
                "typical_duration_minutes": {"min": 5, "max": 30},
                "collaboration_patterns": ["Generate", "Clarify"],
            }
        ],
    )

    result = validate_agenda(
        _make_agenda(
            [
                _make_activity(tool_type="discussion"),  # hallucinated tool_type
                _make_activity(title=""),  # empty title
                _make_activity(config_overrides={"enable_reactions": True}),  # unknown config key
                _make_activity(duration_minutes=120),  # out-of-range duration
            ]
        )
    )

    assert result.valid is False
    assert len(result.errors) == 2
    assert any("tool_type 'discussion' is not registered" in err.message for err in result.errors)
    assert any("Missing or invalid title" in err.message for err in result.errors)
    assert any("Unknown config_overrides key 'enable_reactions'" in warn.message for warn in result.warnings)
    assert any("outside typical range" in warn.message for warn in result.warnings)


def test_single_activity_agenda_valid(monkeypatch) -> None:
    _mock_catalog_with_ranges(monkeypatch)
    result = validate_agenda(_make_agenda([_make_activity()]))

    assert result.valid is True
    assert result.errors == []


def test_validator_import_isolation() -> None:
    source = inspect.getsource(agenda_validator_module)

    assert "from app.services.activity_catalog import get_enriched_activity_catalog" in source
    forbidden_imports = [
        "from app.routers",
        "import app.routers",
        "from app.services.ai_provider",
        "from app.services.meeting_designer_prompt",
        "from app.templates",
        "from app.data",
        "from app.models",
    ]
    for forbidden in forbidden_imports:
        assert forbidden not in source


def test_error_messages_include_context() -> None:
    result = validate_agenda(
        _make_agenda(
            [_make_activity(tool_type="discussion")],
        )
    )

    assert result.valid is False
    tool_error = next(err for err in result.errors if err.field == "tool_type")
    assert "Activity 0" in tool_error.message
    assert "tool_type" in tool_error.message


def _make_outline(activities, **envelope_overrides):
    payload = {
        "meeting_summary": "Outline summary",
        "outline": activities,
    }
    payload.update(envelope_overrides)
    return payload


def _make_outline_activity(**overrides):
    activity = {
        "tool_type": "brainstorming",
        "title": "Collect ideas",
        "duration_minutes": 15,
        "collaboration_pattern": "Generate",
        "rationale": "Diverge first.",
    }
    activity.update(overrides)
    return activity


def _mock_outline_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        agenda_validator_module,
        "get_enriched_activity_catalog",
        lambda: [
            {
                "tool_type": "brainstorming",
                "typical_duration_minutes": {"min": 5, "max": 30},
                "collaboration_patterns": ["Generate", "Clarify"],
            },
            {
                "tool_type": "voting",
                "typical_duration_minutes": {"min": 3, "max": 15},
                "collaboration_patterns": ["Evaluate", "Build Consensus"],
            },
            {
                "tool_type": "categorization",
                "typical_duration_minutes": {"min": 5, "max": 25},
                "collaboration_patterns": ["Organize", "Reduce"],
            },
        ],
    )


def test_valid_outline_passes(monkeypatch) -> None:
    _mock_outline_catalog(monkeypatch)
    result = validate_outline(
        _make_outline(
            [
                _make_outline_activity(tool_type="brainstorming", title="Open", collaboration_pattern="Generate"),
                _make_outline_activity(tool_type="categorization", title="Cluster", collaboration_pattern="Organize"),
                _make_outline_activity(tool_type="voting", title="Down-select", collaboration_pattern="Evaluate"),
            ]
        )
    )

    assert result.valid is True
    assert result.errors == []


def test_outline_missing_outline_key(monkeypatch) -> None:
    _mock_outline_catalog(monkeypatch)
    result = validate_outline({})

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].field == "outline"


def test_outline_empty_list(monkeypatch) -> None:
    _mock_outline_catalog(monkeypatch)
    result = validate_outline({"outline": [], "meeting_summary": "Summary"})

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].field == "outline"


def test_outline_hallucinated_tool_type(monkeypatch) -> None:
    _mock_outline_catalog(monkeypatch)
    result = validate_outline(
        _make_outline(
            [
                _make_outline_activity(tool_type="roundtable"),
            ]
        )
    )

    assert result.valid is False
    tool_errors = [err for err in result.errors if err.field == "tool_type"]
    assert len(tool_errors) == 1
    assert "available types are: brainstorming, voting, categorization" in tool_errors[0].message


def test_outline_missing_title(monkeypatch) -> None:
    _mock_outline_catalog(monkeypatch)
    result = validate_outline(_make_outline([_make_outline_activity(title="")]))

    assert result.valid is False
    title_errors = [err for err in result.errors if err.field == "title"]
    assert len(title_errors) == 1


def test_outline_does_not_check_instructions(monkeypatch) -> None:
    _mock_outline_catalog(monkeypatch)
    result = validate_outline(_make_outline([_make_outline_activity()]))

    assert result.valid is True
    assert not [err for err in result.errors if err.field == "instructions"]
    assert not [warn for warn in result.warnings if warn.field == "instructions"]


def test_outline_does_not_check_config_overrides(monkeypatch) -> None:
    _mock_outline_catalog(monkeypatch)
    result = validate_outline(_make_outline([_make_outline_activity()]))

    assert result.valid is True
    assert not [err for err in result.errors if err.field == "config_overrides"]
    assert not [warn for warn in result.warnings if warn.field == "config_overrides"]


def test_outline_duration_out_of_range_warns(monkeypatch) -> None:
    _mock_outline_catalog(monkeypatch)
    result = validate_outline(
        _make_outline([_make_outline_activity(duration_minutes=999)])
    )

    assert result.valid is True
    warnings = [warn for warn in result.warnings if warn.field == "duration_minutes"]
    assert len(warnings) == 1
    assert "outside typical range" in warnings[0].message
