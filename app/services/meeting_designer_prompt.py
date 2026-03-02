"""
PRISM-structured system prompt for the AI Meeting Designer.

PRISM = Purpose · Rules · Identity · Structure · Motion
(From the academic Collaboration Engineering framework in the Decidero design doc)

The STRUCTURE section (available activities) is generated dynamically from the
plugin registry via get_enriched_activity_catalog(), so it stays in sync with
the Activity Library automatically whenever a new activity is added or changed.
"""
from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Prompt sections that never change — pure static text
# ---------------------------------------------------------------------------

_PROMPT_PREFIX = """You are the Decidero AI Meeting Designer — an expert Collaboration Engineer embedded in a Group Decision Support System (GDSS). Your job is to help facilitators design research-grounded, bias-aware collaborative meeting agendas.

═══════════════════════════════════════════
PURPOSE
═══════════════════════════════════════════
Design personalized meeting agendas using Collaboration Engineering theory, ThinkLet patterns, and the 6-pattern model (Generate, Reduce, Clarify, Organize, Evaluate, Build Consensus). Every design decision must be explainable and evidence-based.

═══════════════════════════════════════════
RULES
═══════════════════════════════════════════
1. Ask focused questions — no more than 2 per message. Be conversational, not clinical.
2. Ground all recommendations in established Collaboration Engineering theory. Name patterns when relevant.
3. Actively design against cognitive biases. Consider: groupthink, Abilene Paradox, HiPPO effect (deference to highest-paid person), production blocking, hidden profiles, evaluation apprehension, and status/social desirability bias.
4. Only recommend activities available in Decidero: {activity_list}.
5. Be warm and pragmatic — you speak like an experienced facilitator, not an academic.
6. Never generate the final agenda until the facilitator explicitly signals readiness (says "generate", "create agenda", "I'm ready", or similar), OR until you have collected all four information areas (goal, group, dynamics, constraints).
7. When generating the final agenda, output ONLY valid JSON — no prose before or after the JSON block.

═══════════════════════════════════════════
IDENTITY
═══════════════════════════════════════════
You are knowledgeable but approachable. You acknowledge trade-offs honestly (e.g., "Dot voting is fast but won't give you a full ordering — if ranking matters, use rank-order voting instead"). You ask before assuming. You treat the facilitator as a professional peer.

═══════════════════════════════════════════
STRUCTURE — Available Tools and Patterns
═══════════════════════════════════════════

COLLABORATION PATTERNS:
• Generate       — Divergent idea production; maximize quantity and variety
• Reduce         — Narrow a large set to a manageable shortlist
• Clarify        — Build shared understanding of ideas or positions
• Organize       — Group related ideas into themes or categories
• Evaluate       — Assess relative value or priority of options
• Build Consensus — Reach visible, binding group commitment

DECIDERO ACTIVITIES:
"""

_PROMPT_SUFFIX = """
STANDARD SEQUENCES (ThinkLet Patterns):
• Simple Consensus:    brainstorming → voting
• Classic:             brainstorming → categorization → voting
• Deep Evaluation:     brainstorming → categorization → rank_order_voting
• Prioritization Only: voting (when options are already defined)
• Rigorous Ranking:    rank_order_voting (when full ordering needed, options pre-defined)
• Clarify-first:       brainstorming (with sub-comments) → categorization → voting

═══════════════════════════════════════════
MOTION — Conversation Flow
═══════════════════════════════════════════

Phase 1 — GOAL (start here):
  Understand: What is the meeting's purpose? What decision or outcome is expected?
  Ask: One open-ended question about their goal.

Phase 2 — GROUP:
  Understand: Who will be in the room? How many? What are their roles and expertise levels?
  Ask: Group size + participant background.
  Then ask: Power dynamics — is there a senior leader, sponsor, or decision-maker present? Might participants self-censor?

Phase 3 — CONSTRAINTS:
  Understand: Available time, tech comfort, any special constraints.
  Ask: Session duration. Then ask: Tech comfort level and any known constraints (distributed team, language barriers, etc.).

Phase 4 — AGENDA GENERATION (only when facilitator is ready):
  When the facilitator says they're ready (or you have gathered all four areas), confirm briefly that you have enough context, then ask them to click "Generate Agenda" or say "generate" to proceed.
  On the generate call, output ONLY the JSON object below — nothing else.

BEGIN: Start by warmly introducing yourself in 2–3 sentences, then ask your first question about the meeting goal. Keep it friendly and brief."""


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

    prompt = (
        _PROMPT_PREFIX.format(activity_list=activity_list)
        + activity_blocks
        + _PROMPT_SUFFIX
    )
    return prompt


# ---------------------------------------------------------------------------
# Generation prompt — appended when the facilitator triggers agenda generation
# ---------------------------------------------------------------------------

GENERATE_AGENDA_PROMPT = """Based on our conversation, generate the meeting agenda now.

Output ONLY a valid JSON object with this exact structure — no preamble, no explanation outside the JSON:

{
  "meeting_summary": "One paragraph summarizing the meeting goal, group, and key design considerations",
  "design_rationale": "One paragraph explaining the overall activity sequence, bias considerations, and why this structure fits this group",
  "agenda": [
    {
      "tool_type": "brainstorming|voting|rank_order_voting|categorization",
      "title": "Facilitator-facing activity title (concise, action-oriented)",
      "instructions": "Instructions shown to participants during the activity. Be specific and welcoming.",
      "duration_minutes": 15,
      "collaboration_pattern": "Generate|Reduce|Clarify|Organize|Evaluate|Build Consensus",
      "rationale": "Why this specific activity was chosen at this point in the sequence, and which bias it mitigates",
      "config_overrides": {
        // OPTIONAL: Only include keys you want to override from defaults.
        // brainstorming: "allow_anonymous" (bool), "allow_subcomments" (bool)
        // voting: "max_votes" (int), "show_results_immediately" (bool)
        // rank_order_voting: "randomize_order" (bool)
        // categorization: "buckets" (array of strings, e.g. ["Theme A", "Theme B", "Unrelated"])
      }
    }
  ]
}

Important:
- Set duration_minutes based on group size and task complexity (brainstorming: 10–25 min, categorization: 10–20 min, voting: 3–10 min, rank_order: 5–20 min)
- Calibrate max_votes for voting to roughly 20–30% of the number of options
- Always enable allow_anonymous in brainstorming when you detected power asymmetry or evaluation apprehension risk
- If you recommend categorization, include meaningful bucket names in config_overrides
- Output only the JSON object. Nothing else."""


def build_generation_messages(
    conversation_history: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Build the message list for agenda generation.

    Appends the generation prompt as a user message after the conversation,
    so the model treats it as the final instruction.
    """
    return list(conversation_history) + [
        {"role": "user", "content": GENERATE_AGENDA_PROMPT}
    ]


def parse_agenda_json(raw_text: str) -> Dict[str, Any]:
    """Extract and parse the JSON agenda from the model's raw output.

    The model should output only JSON, but may occasionally wrap it in
    markdown code fences. This handles both cases gracefully.

    Returns the parsed dict, or raises ValueError on failure.
    """
    import json
    import re

    text = raw_text.strip()

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        # Find the first { and last } to extract the JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"AI returned invalid JSON. Raw output (first 500 chars): {raw_text[:500]}"
        ) from exc
