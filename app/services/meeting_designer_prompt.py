"""
PRISM-structured prompt assembly for the AI Meeting Designer.

Prompt templates are loaded from config (`ai.prompts.meeting_designer`) so
prompt content can be changed without editing Python source.

The STRUCTURE section (available activities) is generated dynamically from the
plugin registry via get_enriched_activity_catalog(), so it stays in sync with
the Activity Library automatically whenever a new activity is added or changed.

Public API:
  - build_system_prompt()
  - build_generation_system_prompt()
  - build_generation_prompt()
  - build_generation_messages()
  - build_outline_prompt()
  - build_outline_messages()
  - parse_agenda_json()
  - parse_outline_json()
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config.loader import get_meeting_designer_prompt_templates


def _get_prompt_templates() -> Dict[str, str]:
    return get_meeting_designer_prompt_templates()


_INTERNAL_CONFIG_KEYS = {"options", "ideas", "items", "buckets", "mode", "vote_type"}


# ---------------------------------------------------------------------------
# Activity block builder
# ---------------------------------------------------------------------------

def _format_config_options(default_config: Dict[str, Any]) -> str:
    """Render the config_overrides the AI may set, derived from default_config keys."""
    # Skip internal/structural keys that aren't meaningful design choices for the AI
    parts = []
    for key, val in default_config.items():
        if key in _INTERNAL_CONFIG_KEYS:
            continue
        type_name = type(val).__name__
        parts.append(f"{key} ({type_name})")
    return ", ".join(parts) if parts else "none"


def _build_tool_type_enum(catalog: List[Dict[str, Any]]) -> str:
    """Build a pipe-separated tool_type enum from a caller-provided catalog list for testability and single-fetch efficiency."""
    tool_types = [
        tool_type.strip()
        for entry in catalog
        for tool_type in [entry.get("tool_type")]
        if isinstance(tool_type, str) and tool_type.strip()
    ]
    return "|".join(tool_types)


def _build_config_overrides_block(catalog: List[Dict[str, Any]]) -> str:
    """Build per-tool config_overrides guidance from a caller-provided catalog list for testability and single-fetch efficiency."""
    lines: List[str] = []
    for entry in catalog:
        tool_type = entry.get("tool_type")
        if not isinstance(tool_type, str) or not tool_type.strip():
            continue
        default_config = entry.get("default_config")
        config_items: List[str] = []
        if isinstance(default_config, dict):
            for key, value in default_config.items():
                if key in _INTERNAL_CONFIG_KEYS:
                    continue
                config_items.append(f'"{key}" ({type(value).__name__})')
        rendered = ", ".join(config_items) if config_items else "none"
        lines.append(f"// {tool_type}: {rendered}")
    return "\n".join(lines)


def _build_duration_guidance(catalog: List[Dict[str, Any]]) -> str:
    """Build duration guidance from a caller-provided catalog list for testability and single-fetch efficiency."""
    parts: List[str] = []
    for entry in catalog:
        tool_type = entry.get("tool_type")
        if not isinstance(tool_type, str) or not tool_type.strip():
            continue
        typical = entry.get("typical_duration_minutes")
        if isinstance(typical, dict):
            min_value = typical.get("min")
            max_value = typical.get("max")
            if isinstance(min_value, (int, float)) and isinstance(max_value, (int, float)):
                parts.append(f"{tool_type}: {int(min_value)}-{int(max_value)} min")
                continue
        parts.append(f"{tool_type}: varies")
    return ", ".join(parts)


def _format_activity_block(index: int, activity: Dict[str, Any]) -> str:
    """Render a single activity's description block for the system prompt."""
    tool_type = activity.get("tool_type", "")
    label = activity.get("label", tool_type)
    patterns = activity.get("collaboration_patterns") or []
    description = activity.get("description", "")
    thinklets = activity.get("thinklets") or []
    when_to_use = activity.get("when_to_use", "")
    bias_mitigation = activity.get("bias_mitigation") or []
    duration = activity.get("typical_duration_minutes") or {}
    default_config = activity.get("default_config") or {}

    duration_str = (
        f"{duration['min']}–{duration['max']} min"
        if "min" in duration and "max" in duration
        else "varies"
    )

    lines = [
        f"{index}. {tool_type}",
        f"   Label: {label}",
        f"   Patterns: {', '.join(patterns)}",
        f"   Description: {description}",
    ]

    if thinklets:
        lines.append(f"   ThinkLets: {'; '.join(thinklets)}")

    if when_to_use:
        lines.append(f"   Best for: {when_to_use}")

    if bias_mitigation:
        # Join multiple bias items into a single readable line
        bias_text = "; ".join(b.split("\n")[0] for b in bias_mitigation)
        lines.append(f"   Bias mitigated: {bias_text}")

    lines.append(f"   Typical duration: {duration_str}")
    lines.append(f"   Config options: {_format_config_options(default_config)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_system_prompt() -> str:
    """Build the Meeting Designer system prompt with the live activity catalog.

    The STRUCTURE section is generated at call time from the plugin registry,
    so it stays in sync with the Activity Library automatically.
    """
    from app.services.activity_catalog import get_enriched_activity_catalog  # noqa: PLC0415

    catalog = get_enriched_activity_catalog()

    # Rule 4 — comma-separated list of tool_type names
    activity_list = ", ".join(a["tool_type"] for a in catalog)

    # DECIDERO ACTIVITIES block — one numbered entry per plugin
    activity_blocks = "\n\n".join(
        _format_activity_block(i + 1, activity) for i, activity in enumerate(catalog)
    )
    templates = _get_prompt_templates()

    prompt = (
        templates["system_prefix"].format(activity_list=activity_list)
        + activity_blocks
        + templates["system_suffix"]
    )
    return prompt


def build_generation_system_prompt() -> str:
    """Build the dedicated system prompt for agenda generation mode.

    This avoids conflicts with chat-only rules (for example, "never output JSON")
    while remaining provider/model agnostic.
    """
    from app.services.activity_catalog import get_enriched_activity_catalog  # noqa: PLC0415

    catalog = get_enriched_activity_catalog()
    activity_list = ", ".join(a["tool_type"] for a in catalog)

    return (
        "You are the Decidero AI Meeting Designer in AGENDA GENERATION MODE.\n"
        "Your task is to convert the prior conversation into one valid JSON object "
        "that matches the user schema/instructions.\n"
        f"Allowed tool_type values: {activity_list}.\n"
        "Output requirements:\n"
        "- Output ONLY JSON (no prose, no markdown fences, no commentary).\n"
        "- Return exactly one top-level JSON object.\n"
        "- If uncertain, make best-effort assumptions but still return valid JSON."
    )


# ---------------------------------------------------------------------------
# Generation prompt — appended when the facilitator triggers agenda generation
# ---------------------------------------------------------------------------

def build_generation_prompt(outline: Optional[List[Dict[str, Any]]] = None) -> str:
    """Build a catalog-driven generation prompt with optional outline lock-in.

    When ``outline`` is provided, the prompt constrains generation to that
    activity sequence and asks the model to elaborate each activity with
    instructions and config overrides. This replaces the former static
    generation-prompt constant and keeps tool type guidance synchronized with
    the live activity catalog.

    Args:
        outline: Optional Stage-1 outline activity list. When provided, prompt
            text locks sequence, tool types, and titles to this outline.

    Returns:
        A complete generation prompt string for the model.

    Raises:
        None.
    """
    from app.services.activity_catalog import get_enriched_activity_catalog  # noqa: PLC0415

    catalog = get_enriched_activity_catalog()
    tool_type_enum = _build_tool_type_enum(catalog)
    config_overrides_block = _build_config_overrides_block(catalog)
    duration_guidance = _build_duration_guidance(catalog)

    outline_prefix = ""
    if outline is not None:
        outline_lines: List[str] = []
        for index, item in enumerate(outline, start=1):
            if not isinstance(item, dict):
                continue
            tool_type = item.get("tool_type", "")
            title = item.get("title", "")
            outline_lines.append(f"{index}. {title} [{tool_type}]")
        rendered_outline = "\n".join(outline_lines) if outline_lines else "(no outline items)"
        outline_prefix = (
            "The following activity outline has been approved. Generate the full agenda "
            "following this exact sequence, tool_types, and titles. Add instructions and "
            "config_overrides for each.\n\n"
            f"{rendered_outline}\n\n"
        )

    return (
        f"{outline_prefix}"
        "Based on our conversation, generate the meeting agenda now.\n\n"
        "First, assess the complexity level based on our discussion:\n"
        "- \"simple\" — single topic, small group, short session -> flat agenda, no phases needed\n"
        "- \"multi_phase\" — multiple sequential topics or extended session -> group activities into named phases\n"
        "- \"multi_track\" — parallel breakout groups needed -> include phases with parallel tracks\n\n"
        "Output ONLY a valid JSON object with this structure — no preamble, no explanation outside the JSON:\n\n"
        "{\n"
        "  \"meeting_summary\": \"One paragraph summarizing the meeting goal, group, and key design considerations\",\n"
        "  \"session_name\": \"The short session name the facilitator provided. Use exactly what they said.\",\n"
        "  \"evaluation_criteria\": [\"criterion1\", \"criterion2\"],\n"
        "  \"design_rationale\": \"One paragraph explaining the overall structure and why it fits the group\",\n"
        "  \"complexity\": \"simple|multi_phase|multi_track\",\n"
        "  \"phases\": [\n"
        "    {\n"
        "      \"phase_id\": \"phase_1\",\n"
        "      \"title\": \"Short descriptive phase title\",\n"
        "      \"description\": \"What happens in this phase and why\",\n"
        "      \"phase_type\": \"plenary|parallel\",\n"
        "      \"tracks\": [\n"
        "        {\"track_id\": \"track_2a\", \"label\": \"Descriptive track name\", \"participant_subset\": \"Who goes in this track and roughly how many\"}\n"
        "      ],\n"
        "      \"suggested_duration_minutes\": 30\n"
        "    }\n"
        "  ],\n"
        "  \"agenda\": [\n"
        "    {\n"
        f"      \"tool_type\": \"{tool_type_enum}\",\n"
        "      \"title\": \"Facilitator-facing activity title (concise, action-oriented)\",\n"
        "      \"instructions\": \"Instructions shown to participants during the activity. Be specific and welcoming.\",\n"
        "      \"duration_minutes\": 15,\n"
        "      \"collaboration_pattern\": \"Generate|Reduce|Clarify|Organize|Evaluate|Build Consensus\",\n"
        "      \"rationale\": \"Why this activity was chosen at this point in the sequence\",\n"
        "      \"config_overrides\": {},\n"
        "      \"phase_id\": \"phase_1\",\n"
        "      \"track_id\": null\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Complexity rules:\n"
        "- For \"simple\": the phases array may be empty or have one entry.\n"
        "- For \"multi_phase\": phases has 2+ entries with plenary sequencing.\n"
        "- For \"multi_track\": at least one phase has parallel tracks and each parallel phase reconverges into a plenary phase.\n"
        "- Order activities in the agenda array by phase order first, then track order within parallel phases.\n\n"
        "Config-overrides reference (include only keys you want to change from defaults):\n"
        f"{config_overrides_block}\n\n"
        "Activity calibration:\n"
        f"- Set duration_minutes using this guidance: {duration_guidance}\n"
        "- For ballot-based activities, calibrate max_votes to roughly 20-30% of option count.\n"
        "- For activities that support anonymity, enable it when power asymmetry is detected.\n"
        "- For grouping activities, include meaningful bucket names.\n"
        "- For multi-track designs, mirror the activity structure across breakout tracks when possible.\n\n"
        "Reconvergence rules (mandatory for multi_track complexity):\n"
        "- Every parallel phase MUST be immediately followed by a plenary reconvergence phase.\n"
        "- Reconvergence activities must name each track and state what deliverable each track is presenting.\n"
        "- The last activity in each breakout track should instruct the group to prepare a concise summary for reconvergence.\n"
        "- If there are multiple parallel phases, each must have its own subsequent reconvergence phase.\n\n"
        "Session naming rules:\n"
        "- Always include session_name with the name the facilitator provided during the conversation.\n"
        "- If the facilitator did not provide a session name, derive one from the meeting goal.\n\n"
        "Output ONLY the JSON object. Nothing else."
    )


def get_generation_prompt() -> str:
    """Return the default generation prompt (without an outline constraint).

    Args:
        None.

    Returns:
        A complete generation prompt string equivalent to
        ``build_generation_prompt(outline=None)``.

    Raises:
        None.
    """
    return build_generation_prompt()


def build_outline_prompt() -> str:
    """Build the Stage 1 outline prompt for the two-stage generation pipeline.

    Produces a lightweight sequence plan (tool_type, title, duration,
    collaboration pattern, rationale) that is validated before full agenda
    generation.

    Args:
        None.

    Returns:
        A complete outline-stage prompt string for the model.

    Raises:
        None.
    """
    from app.services.activity_catalog import get_enriched_activity_catalog  # noqa: PLC0415

    catalog = get_enriched_activity_catalog()
    tool_type_enum = _build_tool_type_enum(catalog)
    duration_guidance = _build_duration_guidance(catalog)

    return (
        "Based on our conversation, generate a meeting activity outline now.\n\n"
        "Output ONLY a valid JSON object with this structure:\n\n"
        "{\n"
        "  \"meeting_summary\": \"One paragraph summarizing the meeting goal\",\n"
        "  \"outline\": [\n"
        "    {\n"
        f"      \"tool_type\": \"{tool_type_enum}\",\n"
        "      \"title\": \"Concise action-oriented title\",\n"
        "      \"duration_minutes\": 15,\n"
        "      \"collaboration_pattern\": \"Generate|Reduce|Clarify|Organize|Evaluate|Build Consensus\",\n"
        "      \"rationale\": \"Why this activity at this point in the sequence\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Duration guidance: {duration_guidance}\n\n"
        "Output ONLY the JSON object. Do not include instructions or config_overrides; "
        "those will be added in a subsequent step."
    )


def build_outline_messages(
    conversation_history: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Build outline-stage messages by appending the outline prompt.

    Mirrors build_generation_messages() but for Stage 1 outline generation.

    Args:
        conversation_history: Prior chat messages to preserve.

    Returns:
        A new message list with the outline prompt appended as the final user
        message.

    Raises:
        None.
    """
    return list(conversation_history) + [
        {"role": "user", "content": build_outline_prompt()}
    ]


def build_generation_messages(
    conversation_history: List[Dict[str, str]],
    outline: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """Build the message list for agenda generation.

    Appends the generation prompt as a user message after the conversation,
    so the model treats it as the final instruction. When ``outline`` is
    provided, the generation prompt locks in the outline's activity sequence
    and asks the AI to elaborate with instructions and config_overrides.

    Args:
        conversation_history: Prior chat messages to preserve.
        outline: Optional Stage-1 outline activity list used to constrain
            sequence, tool types, and titles in the generation prompt.

    Returns:
        A new message list with the generation prompt appended as the final
        user message.

    Raises:
        None.
    """
    return list(conversation_history) + [
        {"role": "user", "content": build_generation_prompt(outline=outline)}
    ]


def _extract_json_object(raw_text: str) -> str:
    """Extract a JSON object string from raw model output wrappers.

    Uses markdown-fence extraction first, then a brace-span fallback to strip
    surrounding prose while preserving the first top-level JSON object.
    """
    import re

    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and start <= end:
        return text[start : end + 1]
    return text


def parse_outline_json(raw_text: str) -> Dict[str, Any]:
    """Parse Stage 1 outline JSON and validate the required outline schema.

    Extracts JSON from fenced/prose-wrapped model output using the same shared
    strategy as parse_agenda_json(), then validates that ``outline`` exists
    and is a list.

    Args:
        raw_text: Raw model response that should contain an outline JSON object.

    Returns:
        Parsed JSON dictionary containing at least the ``outline`` list.

    Raises:
        ValueError: If parsing fails or ``outline`` is missing/invalid.
    """
    import json

    text = _extract_json_object(raw_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI returned invalid outline JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Outline payload must be a JSON object.")

    outline = data.get("outline")
    if not isinstance(outline, list):
        raise ValueError("Outline payload must include an 'outline' list.")

    return data


def parse_agenda_json(raw_text: str, *, save_dir: str = "/tmp") -> Dict[str, Any]:
    """Extract and parse the JSON agenda from the model's raw output.

    The model should output only JSON, but may occasionally wrap it in
    markdown code fences or produce slightly malformed JSON. This function
    handles those cases gracefully with a two-pass strategy:

    Pass 1 — strict json.loads()
    Pass 2 — json_repair (handles missing commas, trailing commas, etc.)

    The raw AI output is always saved to ``{save_dir}/decidero_last_agenda_raw.txt``
    so failures can be inspected easily. On success the parsed dict is also
    saved to ``{save_dir}/decidero_last_agenda_parsed.json``.

    Normalises the new complexity/phases/track fields for backward
    compatibility — if they are absent the result degrades gracefully to
    a simple flat agenda.

    Returns the parsed dict, or raises ValueError on failure.
    """
    import json
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)

    # ── Always save the raw output so failures can be inspected ──────────
    try:
        Path(save_dir, "decidero_last_agenda_raw.txt").write_text(
            raw_text, encoding="utf-8"
        )
    except OSError:
        pass  # don't let a disk error mask the real problem

    text = _extract_json_object(raw_text)

    import re

    # ── Strip JS-style // line comments ───────────────────────────────────
    # The AI sometimes mirrors them from the schema template.
    # Careful not to strip URLs ("https://...") — only strip after
    # whitespace, comma, or opening brace/bracket.
    text = re.sub(r'(?<=[,\{\[\s])(\s*)//[^\n]*', r'\1', text)

    # ── Pass 1: strict parse ──────────────────────────────────────────────
    try:
        data = json.loads(text)
        logger.debug("Agenda JSON parsed successfully (strict pass).")
    except json.JSONDecodeError as strict_exc:
        # ── Pass 2: lenient repair ────────────────────────────────────────
        logger.warning(
            "Strict JSON parse failed (%s). Attempting repair with json_repair.", strict_exc
        )
        try:
            from json_repair import repair_json  # type: ignore[import]
            repaired = repair_json(text, return_objects=True)
            if not isinstance(repaired, dict):
                raise ValueError("Repaired JSON is not a dict object.")
            data = repaired
            logger.warning("json_repair recovered a valid dict — generation may need review.")
        except Exception as repair_exc:
            logger.error(
                "Both strict parse and json_repair failed.\n"
                "Strict error: %s\nRepair error: %s\n"
                "Full raw output saved to %s/decidero_last_agenda_raw.txt",
                strict_exc, repair_exc, save_dir,
            )
            raise ValueError(
                f"AI returned invalid JSON (strict: {strict_exc}; repair: {repair_exc}). "
                f"Raw output saved to {save_dir}/decidero_last_agenda_raw.txt"
            ) from strict_exc

    # ── Save parsed result on success ─────────────────────────────────────
    try:
        Path(save_dir, "decidero_last_agenda_parsed.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass

    return _normalise_agenda(data)


def _normalise_agenda(data: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in missing complexity/phases/track fields for backward compat."""

    # Ensure session_name exists
    data.setdefault("session_name", "")

    # Ensure evaluation_criteria is a list of strings
    criteria = data.get("evaluation_criteria")
    if not isinstance(criteria, list):
        criteria = []
    data["evaluation_criteria"] = [c for c in criteria if isinstance(c, str)]

    # Ensure complexity field exists
    complexity = data.get("complexity", "simple")
    if complexity not in ("simple", "multi_phase", "multi_track"):
        complexity = "simple"
    data["complexity"] = complexity

    # Ensure phases is a list
    phases = data.get("phases")
    if not isinstance(phases, list):
        phases = []
    data["phases"] = phases

    # Normalise each phase entry
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        phase.setdefault("phase_id", None)
        phase.setdefault("title", "")
        phase.setdefault("description", "")
        phase.setdefault("phase_type", "plenary")
        if phase["phase_type"] not in ("plenary", "parallel"):
            phase["phase_type"] = "plenary"
        phase.setdefault("suggested_duration_minutes", 0)
        # tracks only on parallel phases
        if phase["phase_type"] == "parallel":
            tracks = phase.get("tracks")
            if not isinstance(tracks, list):
                tracks = []
            phase["tracks"] = tracks
        else:
            phase.pop("tracks", None)

    # Normalise each agenda item — ensure phase_id / track_id present
    agenda = data.get("agenda")
    if isinstance(agenda, list):
        for item in agenda:
            if not isinstance(item, dict):
                continue
            item.setdefault("phase_id", None)
            item.setdefault("track_id", None)
    data.setdefault("agenda", [])

    # Auto-detect complexity if AI forgot to set it but produced phases/tracks
    if complexity == "simple" and phases:
        has_parallel = any(
            isinstance(p, dict) and p.get("phase_type") == "parallel"
            for p in phases
        )
        if has_parallel:
            data["complexity"] = "multi_track"
        elif len(phases) >= 2:
            data["complexity"] = "multi_phase"

    return data
