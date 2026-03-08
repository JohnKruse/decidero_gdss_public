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
from typing import Any, Dict, List, Literal, Set

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


def _extract_phase_track_maps(
    agenda_data: Dict[str, Any],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, str], Set[str]]:
    """Extract declared phases, tracks, and parallel phase IDs from an agenda payload.

    Returns (declared_phases, declared_tracks, parallel_phase_ids). Handles missing
    or malformed phases gracefully by returning empty structures.
    """

    phases = agenda_data.get("phases")
    if not isinstance(phases, list) or not phases:
        return {}, {}, set()

    declared_phases: Dict[str, Dict[str, Any]] = {}
    declared_tracks: Dict[str, str] = {}
    parallel_phase_ids: Set[str] = set()

    for phase in phases:
        if not isinstance(phase, dict):
            continue
        raw_phase_id = phase.get("phase_id")
        if not isinstance(raw_phase_id, str):
            continue
        phase_id = raw_phase_id.strip()
        if not phase_id:
            continue

        declared_phases[phase_id] = phase

        raw_phase_type = phase.get("phase_type")
        if isinstance(raw_phase_type, str) and raw_phase_type.strip().lower() == "parallel":
            parallel_phase_ids.add(phase_id)

        tracks = phase.get("tracks")
        if not isinstance(tracks, list):
            continue
        for track in tracks:
            if not isinstance(track, dict):
                continue
            raw_track_id = track.get("track_id")
            if not isinstance(raw_track_id, str):
                continue
            track_id = raw_track_id.strip()
            if not track_id:
                continue
            declared_tracks[track_id] = phase_id

    return declared_phases, declared_tracks, parallel_phase_ids


def _check_dangling_phase_refs(
    activities: List[Dict[str, Any]],
    declared_phases: Dict[str, Dict[str, Any]],
    errors: List[AgendaFieldError],
) -> None:
    """Append errors for any agenda activity whose phase_id is not declared in the phases array.

    Skips activities with null or absent phase_id.
    """

    for idx, activity in enumerate(activities):
        if not isinstance(activity, dict):
            continue
        raw_phase_id = activity.get("phase_id")
        if not isinstance(raw_phase_id, str):
            continue
        phase_id = raw_phase_id.strip()
        if not phase_id or phase_id in declared_phases:
            continue
        raw_title = activity.get("title")
        title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else f"Activity {idx}"
        errors.append(
            AgendaFieldError(
                activity_index=idx,
                field="phase_id",
                message=f"Activity {idx} ('{title}'): phase_id '{phase_id}' is not declared in the phases array.",
                level="error",
            )
        )


def _check_dangling_track_refs(
    activities: List[Dict[str, Any]],
    declared_tracks: Dict[str, str],
    errors: List[AgendaFieldError],
) -> None:
    """Append errors for any agenda activity whose track_id is not declared in any phase's tracks array.

    Skips activities with null or absent track_id.
    """

    for idx, activity in enumerate(activities):
        if not isinstance(activity, dict):
            continue
        raw_track_id = activity.get("track_id")
        if not isinstance(raw_track_id, str):
            continue
        track_id = raw_track_id.strip()
        if not track_id or track_id in declared_tracks:
            continue
        raw_title = activity.get("title")
        title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else f"Activity {idx}"
        errors.append(
            AgendaFieldError(
                activity_index=idx,
                field="track_id",
                message=(
                    f"Activity {idx} ('{title}'): track_id '{track_id}' is not declared "
                    "in any phase's tracks array."
                ),
                level="error",
            )
        )


def _check_min_activities_per_track(
    activities: List[Dict[str, Any]],
    declared_tracks: Dict[str, str],
    parallel_phase_ids: Set[str],
    errors: List[AgendaFieldError],
) -> None:
    """Append errors for any declared track in a parallel phase that has fewer than 2 agenda activities.

    Enforces the multi-activity-per-track invariant.
    """

    track_counts: Dict[str, int] = {track_id: 0 for track_id in declared_tracks}

    for activity in activities:
        if not isinstance(activity, dict):
            continue
        raw_track_id = activity.get("track_id")
        if not isinstance(raw_track_id, str):
            continue
        track_id = raw_track_id.strip()
        if not track_id or track_id not in track_counts:
            continue
        track_counts[track_id] += 1

    for track_id, phase_id in declared_tracks.items():
        if phase_id not in parallel_phase_ids:
            continue
        count = track_counts.get(track_id, 0)
        if count >= 2:
            continue
        errors.append(
            AgendaFieldError(
                activity_index=-1,
                field="track_id",
                message=(
                    f"Track '{track_id}' in parallel phase '{phase_id}' has {count} activity "
                    "but requires at least 2."
                ),
                level="error",
            )
        )


def _check_reconvergence(phases: List[Dict[str, Any]], errors: List[AgendaFieldError]) -> None:
    """Append errors for any parallel phase not immediately followed by a plenary phase.

    Enforces the reconvergence invariant.
    """

    for idx, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        raw_phase_type = phase.get("phase_type")
        phase_type = raw_phase_type.strip().lower() if isinstance(raw_phase_type, str) else ""
        if phase_type != "parallel":
            continue

        raw_phase_id = phase.get("phase_id")
        phase_id = raw_phase_id.strip() if isinstance(raw_phase_id, str) and raw_phase_id.strip() else f"phase_{idx}"
        raw_title = phase.get("title")
        title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else phase_id

        if idx + 1 >= len(phases):
            errors.append(
                AgendaFieldError(
                    activity_index=-1,
                    field="phases",
                    message=(
                        f"Parallel phase '{phase_id}' ('{title}') is the last phase but must be followed "
                        "by a plenary reconvergence phase."
                    ),
                    level="error",
                )
            )
            continue

        next_phase = phases[idx + 1]
        if not isinstance(next_phase, dict):
            continue
        raw_next_phase_type = next_phase.get("phase_type")
        next_phase_type = (
            raw_next_phase_type.strip().lower() if isinstance(raw_next_phase_type, str) else ""
        )
        if next_phase_type == "plenary":
            continue
        raw_next_phase_id = next_phase.get("phase_id")
        next_phase_id = (
            raw_next_phase_id.strip()
            if isinstance(raw_next_phase_id, str) and raw_next_phase_id.strip()
            else f"phase_{idx + 1}"
        )
        errors.append(
            AgendaFieldError(
                activity_index=-1,
                field="phases",
                message=(
                    f"Parallel phase '{phase_id}' ('{title}') is followed by another parallel phase "
                    f"('{next_phase_id}') but must be followed by a plenary reconvergence phase."
                ),
                level="error",
            )
        )


def _validate_structural_invariants(agenda_data: Dict[str, Any]) -> List[AgendaFieldError]:
    """Run structural agenda checks that rely on phase/track declarations."""

    declared_phases, declared_tracks, parallel_phase_ids = _extract_phase_track_maps(agenda_data)
    if not declared_phases:
        return []

    activities = agenda_data.get("agenda")
    if not isinstance(activities, list):
        return []
    phases = agenda_data.get("phases")
    if not isinstance(phases, list):
        phases = []

    errors: List[AgendaFieldError] = []
    _check_dangling_phase_refs(activities, declared_phases, errors)
    _check_dangling_track_refs(activities, declared_tracks, errors)
    _check_min_activities_per_track(activities, declared_tracks, parallel_phase_ids, errors)
    _check_reconvergence(phases, errors)
    return errors


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

    Performs per-activity field validation (tool_type, title, instructions,
    duration, config_overrides) and structural invariant checks (dangling
    phase_id/track_id references, minimum 2 activities per parallel-phase
    track, parallel-phase reconvergence requirement). Errors block validation
    success; warnings are informational.
    Phase 6 integration tests confirm this function correctly accepts
    well-formed multi-track agendas and rejects structurally defective ones
    (single-activity tracks, dangling references, missing reconvergence).
    """
    result = _validate_activity_payload(
        agenda_data,
        activities_key="agenda",
        require_design_rationale=True,
        check_instructions=True,
        check_config_overrides=True,
    )
    if not result.valid:
        return result

    structural_errors = _validate_structural_invariants(agenda_data)
    if structural_errors:
        result.errors.extend(structural_errors)
        result.valid = False

    return result


def validate_outline(outline_data: Dict[str, Any]) -> AgendaValidationResult:
    """Validate Stage 1 outline output against the live activity catalog.

    Validates tool_types, titles, and durations. When a tracks array is
    present, enforces that each declared track has at least 2 activities and
    flags undeclared track_id references.

    Args:
        outline_data: Raw parsed outline payload.

    Returns:
        AgendaValidationResult containing pass/fail plus error/warning lists.

    Raises:
        None.
    """
    result = _validate_activity_payload(
        outline_data,
        activities_key="outline",
        require_design_rationale=False,
        check_instructions=False,
        check_config_overrides=False,
    )

    tracks = outline_data.get("tracks")
    if not result.valid or not isinstance(tracks, list) or not tracks:
        return result

    outline_items = outline_data.get("outline")
    if not isinstance(outline_items, list):
        return result

    declared_tracks: Dict[str, str] = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        raw_track_id = track.get("track_id")
        if not isinstance(raw_track_id, str):
            continue
        track_id = raw_track_id.strip()
        if not track_id:
            continue
        raw_label = track.get("label")
        label = raw_label.strip() if isinstance(raw_label, str) and raw_label.strip() else track_id
        declared_tracks[track_id] = label

    if not declared_tracks:
        return result

    track_counts = {track_id: 0 for track_id in declared_tracks}
    for idx, activity in enumerate(outline_items):
        if not isinstance(activity, dict):
            continue
        raw_track_id = activity.get("track_id")
        if not isinstance(raw_track_id, str):
            continue
        track_id = raw_track_id.strip()
        if not track_id:
            continue

        if track_id in track_counts:
            track_counts[track_id] += 1
            continue

        title = activity.get("title")
        activity_title = title.strip() if isinstance(title, str) and title.strip() else f"Activity {idx}"
        result.warnings.append(
            AgendaFieldError(
                activity_index=idx,
                field="track_id",
                message=f"Activity '{activity_title}' references undeclared track_id '{track_id}'.",
                level="warning",
            )
        )

    for track_id, label in declared_tracks.items():
        count = track_counts[track_id]
        if count >= 2:
            continue
        result.errors.append(
            AgendaFieldError(
                activity_index=-1,
                field="tracks",
                message=f"Track '{track_id}' ({label}) has {count} activity but must have at least 2.",
                level="error",
            )
        )

    result.valid = not result.errors
    return result
