"""Agenda validation skeleton for BRASS-PELICAN-7 / COPPER-HERON-3.

This module provides pure-function validation entrypoints for AI-generated
agenda payloads. It performs no DB or network calls.

Example:
    >>> payload = {
    ...     "meeting_summary": "Select top ideas",
    ...     "design_rationale": "Diverge then converge",
    ...     "agenda": [
    ...         {
    ...             "tool_type": "brainstorming",
    ...             "title": "Generate Options",
    ...             "instructions": "List ideas quickly.",
    ...             "duration_minutes": 15,
    ...             "rationale": "Create candidate set.",
    ...         }
    ...     ],
    ... }
    >>> result = validate_agenda(payload)
    >>> result.valid
    True
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal

from app.services.activity_catalog import get_enriched_activity_catalog


@dataclass
class AgendaFieldError:
    """Represents a single issue tied to an agenda field."""

    activity_index: int
    field: str
    message: str
    level: Literal["error", "warning"]


@dataclass
class AgendaValidationResult:
    """Result payload returned by agenda validation."""

    valid: bool
    errors: List[AgendaFieldError]
    warnings: List[AgendaFieldError]


def _activity_message(idx: int, field: str, detail: str) -> str:
    """Build a context-rich message for an activity-level validation event."""

    return f"Activity {idx}: {field} - {detail}"


def _extract_duration_bounds(entry: Dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract numeric duration bounds from a catalog entry, if available.

    Range checks are warnings (not errors) because facilitators may
    intentionally deviate from typical durations for contextual reasons.
    """

    typical = entry.get("typical_duration_minutes")
    if not isinstance(typical, dict):
        return None, None
    min_value = typical.get("min")
    max_value = typical.get("max")
    min_bound = float(min_value) if isinstance(min_value, (int, float)) else None
    max_bound = float(max_value) if isinstance(max_value, (int, float)) else None
    return min_bound, max_bound


def _build_catalog_lookup() -> tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Build normalized catalog lookup structures from the live registry."""

    catalog = get_enriched_activity_catalog()
    catalog_lookup: Dict[str, Dict[str, Any]] = {}
    valid_tool_types: List[str] = []
    for entry in catalog:
        tool_type = entry.get("tool_type")
        if not isinstance(tool_type, str):
            continue
        normalized = tool_type.strip().lower()
        if not normalized:
            continue
        catalog_lookup[normalized] = entry
        valid_tool_types.append(tool_type)
    return catalog_lookup, valid_tool_types


def _validate_activity_payload(
    payload: Dict[str, Any],
    *,
    activities_key: str,
    require_design_rationale: bool,
    check_instructions: bool,
    check_config_overrides: bool,
) -> AgendaValidationResult:
    """Validate either agenda or outline payloads using shared activity rules."""

    errors: List[AgendaFieldError] = []
    warnings: List[AgendaFieldError] = []

    activities = payload.get(activities_key)
    if not isinstance(activities, list):
        errors.append(
            AgendaFieldError(
                activity_index=-1,
                field=activities_key,
                message=(
                    f"Activity -1: {activities_key} - Missing or invalid '{activities_key}'; "
                    "expected a list of activities."
                ),
                level="error",
            )
        )
        return AgendaValidationResult(valid=False, errors=errors, warnings=warnings)

    if not activities:
        empty_message = (
            "Agenda contains no activities"
            if activities_key == "agenda"
            else "Outline contains no activities"
        )
        errors.append(
            AgendaFieldError(
                activity_index=-1,
                field=activities_key,
                message=f"Activity -1: {activities_key} - {empty_message}",
                level="error",
            )
        )

    meeting_summary = payload.get("meeting_summary")
    if not isinstance(meeting_summary, str) or not meeting_summary.strip():
        warnings.append(
            AgendaFieldError(
                activity_index=-1,
                field="meeting_summary",
                message="Activity -1: meeting_summary - Missing or empty meeting_summary.",
                level="warning",
            )
        )

    if require_design_rationale:
        design_rationale = payload.get("design_rationale")
        if not isinstance(design_rationale, str) or not design_rationale.strip():
            warnings.append(
                AgendaFieldError(
                    activity_index=-1,
                    field="design_rationale",
                    message="Activity -1: design_rationale - Missing or empty design_rationale.",
                    level="warning",
                )
            )

    catalog_lookup, valid_tool_types = _build_catalog_lookup()

    for idx, activity in enumerate(activities):
        if not isinstance(activity, dict):
            continue

        resolved_entry = None
        raw_tool_type = activity.get("tool_type")
        if not isinstance(raw_tool_type, str) or not raw_tool_type.strip():
            errors.append(
                AgendaFieldError(
                    activity_index=idx,
                    field="tool_type",
                    message=_activity_message(
                        idx,
                        "tool_type",
                        "Missing or invalid tool_type; expected a non-empty string.",
                    ),
                    level="error",
                )
            )
        else:
            normalized_tool_type = raw_tool_type.strip().lower()
            resolved_entry = catalog_lookup.get(normalized_tool_type)
            if not resolved_entry:
                allowed_types = ", ".join(valid_tool_types) if valid_tool_types else "(none)"
                errors.append(
                    AgendaFieldError(
                        activity_index=idx,
                        field="tool_type",
                        message=_activity_message(
                            idx,
                            "tool_type",
                            (
                                f"tool_type '{raw_tool_type}' is not registered; "
                                f"available types are: {allowed_types}"
                            ),
                        ),
                        level="error",
                    )
                )

        title = activity.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(
                AgendaFieldError(
                    activity_index=idx,
                    field="title",
                    message=_activity_message(
                        idx, "title", "Missing or invalid title; expected a non-empty string."
                    ),
                    level="error",
                )
            )

        if check_instructions:
            instructions = activity.get("instructions")
            if not isinstance(instructions, str) or not instructions.strip():
                errors.append(
                    AgendaFieldError(
                        activity_index=idx,
                        field="instructions",
                        message=_activity_message(
                            idx,
                            "instructions",
                            "Missing or invalid instructions; expected a non-empty string.",
                        ),
                        level="error",
                    )
                )

        duration_minutes = activity.get("duration_minutes")
        if not isinstance(duration_minutes, (int, float)) or duration_minutes <= 0:
            warnings.append(
                AgendaFieldError(
                    activity_index=idx,
                    field="duration_minutes",
                    message=_activity_message(
                        idx,
                        "duration_minutes",
                        "Missing or invalid duration_minutes; expected a positive number.",
                    ),
                    level="warning",
                )
            )

        rationale = activity.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            warnings.append(
                AgendaFieldError(
                    activity_index=idx,
                    field="rationale",
                    message=_activity_message(idx, "rationale", "Missing or empty rationale."),
                    level="warning",
                )
            )

        if resolved_entry is None:
            continue

        if isinstance(duration_minutes, (int, float)):
            min_bound, max_bound = _extract_duration_bounds(resolved_entry)
            out_of_range = (min_bound is not None and duration_minutes < min_bound) or (
                max_bound is not None and duration_minutes > max_bound
            )
            if out_of_range:
                warnings.append(
                    AgendaFieldError(
                        activity_index=idx,
                        field="duration_minutes",
                        message=_activity_message(
                            idx,
                            "duration_minutes",
                            (
                                "duration_minutes is outside typical range "
                                f"({min_bound if min_bound is not None else '-inf'}-"
                                f"{max_bound if max_bound is not None else 'inf'})."
                            ),
                        ),
                        level="warning",
                    )
                )

        collaboration_pattern = activity.get("collaboration_pattern")
        if isinstance(collaboration_pattern, str) and collaboration_pattern.strip():
            allowed_patterns = resolved_entry.get("collaboration_patterns")
            pattern_list = (
                [str(p) for p in allowed_patterns if isinstance(p, str)]
                if isinstance(allowed_patterns, list)
                else []
            )
            if pattern_list and collaboration_pattern not in pattern_list:
                warnings.append(
                    AgendaFieldError(
                        activity_index=idx,
                        field="collaboration_pattern",
                        message=_activity_message(
                            idx,
                            "collaboration_pattern",
                            (
                                f"Invalid collaboration_pattern '{collaboration_pattern}'; "
                                f"valid patterns are: {', '.join(pattern_list)}"
                            ),
                        ),
                        level="warning",
                    )
                )

        if not check_config_overrides:
            continue

        config_overrides = activity.get("config_overrides")
        if config_overrides is None:
            continue
        if not isinstance(config_overrides, dict):
            errors.append(
                AgendaFieldError(
                    activity_index=idx,
                    field="config_overrides",
                    message=_activity_message(
                        idx, "config_overrides", "Invalid config_overrides; expected an object/dict."
                    ),
                    level="error",
                )
            )
            continue

        default_config = resolved_entry.get("default_config")
        known_keys = set(default_config.keys()) if isinstance(default_config, dict) else set()
        for key in config_overrides:
            if key in known_keys:
                continue
            warnings.append(
                AgendaFieldError(
                    activity_index=idx,
                    field="config_overrides",
                    message=_activity_message(
                        idx, "config_overrides", f"Unknown config_overrides key '{key}'."
                    ),
                    level="warning",
                )
            )

    return AgendaValidationResult(valid=not errors, errors=errors, warnings=warnings)


def validate_agenda(agenda_data: Dict[str, Any]) -> AgendaValidationResult:
    """Validate the raw dict returned by parse_agenda_json().

    Step 2 envelope checks validate top-level structure before any activity
    checks run: agenda shape, meeting_summary presence, and design_rationale
    presence. Step 4 adds required per-activity field checks.

    Args:
        agenda_data: Raw parsed agenda payload.

    Returns:
        AgendaValidationResult containing pass/fail plus error/warning lists.
        Invalid top-level agenda structure returns an error and exits early.
        Errors block validation success; warnings are informational.

    Raises:
        None.
    """
    return _validate_activity_payload(
        agenda_data,
        activities_key="agenda",
        require_design_rationale=True,
        check_instructions=True,
        check_config_overrides=True,
    )


def validate_outline(outline_data: Dict[str, Any]) -> AgendaValidationResult:
    """Validate Stage 1 outline output against the live activity catalog.

    Validates an AI-generated outline (Stage 1 output) against the live activity
    catalog. Same validation logic as validate_agenda() but does not require
    instructions or config_overrides fields. Returns AgendaValidationResult.

    Args:
        outline_data: Raw parsed outline payload.

    Returns:
        AgendaValidationResult containing pass/fail plus error/warning lists.

    Raises:
        None.
    """
    return _validate_activity_payload(
        outline_data,
        activities_key="outline",
        require_design_rationale=False,
        check_instructions=False,
        check_config_overrides=False,
    )
