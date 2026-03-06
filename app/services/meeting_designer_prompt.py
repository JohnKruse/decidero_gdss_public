"""
PRISM-structured prompt assembly for the AI Meeting Designer.

Prompt templates are loaded from config (`ai.prompts.meeting_designer`) so
prompt content can be changed without editing Python source.

The STRUCTURE section (available activities) is generated dynamically from the
plugin registry via get_enriched_activity_catalog(), so it stays in sync with
the Activity Library automatically whenever a new activity is added or changed.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.config.loader import get_meeting_designer_prompt_templates


def _get_prompt_templates() -> Dict[str, str]:
    return get_meeting_designer_prompt_templates()


# ---------------------------------------------------------------------------
# Activity block builder
# ---------------------------------------------------------------------------

def _format_config_options(default_config: Dict[str, Any]) -> str:
    """Render the config_overrides the AI may set, derived from default_config keys."""
    # Skip internal/structural keys that aren't meaningful design choices for the AI
    skip = {"options", "ideas", "items", "buckets", "mode", "vote_type"}
    parts = []
    for key, val in default_config.items():
        if key in skip:
            continue
        type_name = type(val).__name__
        parts.append(f"{key} ({type_name})")
    return ", ".join(parts) if parts else "none"


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

def get_generation_prompt() -> str:
    return _get_prompt_templates()["generate_agenda"]


def build_generation_messages(
    conversation_history: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Build the message list for agenda generation.

    Appends the generation prompt as a user message after the conversation,
    so the model treats it as the final instruction.
    """
    return list(conversation_history) + [
        {"role": "user", "content": get_generation_prompt()}
    ]


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
    import re
    from pathlib import Path

    logger = logging.getLogger(__name__)

    # ── Always save the raw output so failures can be inspected ──────────
    try:
        Path(save_dir, "decidero_last_agenda_raw.txt").write_text(
            raw_text, encoding="utf-8"
        )
    except OSError:
        pass  # don't let a disk error mask the real problem

    text = raw_text.strip()

    # ── Extract the JSON object from any surrounding prose / fences ───────
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]

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
