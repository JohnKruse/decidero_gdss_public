"""Plainspoken Marmot: the AI round-gate advisor (orchestration decision support).

When an orchestration round-gate's recommender opts in with ``"source": "ai"``, the
engine asks a configured AI provider to recommend one of the gate's finite options
(e.g. continue/conclude) and to explain the choice in a sentence or two for the
facilitator. The facilitator always decides — this only advises — and the engine
falls back to the computational convergence rule whenever this returns ``None``
(disabled, provider error, malformed output, or a recommendation outside the
allowed options). Nothing here raises into the gate.

This keeps the method/prompt logic out of the engine core: the engine passes the
runtime context and an injected ``ai_caller`` (tests stub it, so no network), and
the prompts + model live in tunable config (``gate_recommender_model`` →
``app/config/loader.py::get_gate_recommender_settings``).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Output contract the model must satisfy; reuses the engine's minimal validator.
_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["recommendation", "rationale"],
    "properties": {
        "recommendation": {"type": "string"},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
}

_DEFAULT_SYSTEM_PROMPT = (
    "You advise a meeting facilitator running a structured, multi-round group "
    "method. At each round boundary you recommend whether to run another round or "
    "conclude. You only advise; the facilitator decides. Be concise and neutral."
)

_DEFAULT_PROMPT_TEMPLATE = (
    "Method: {method_summary}\n\n"
    "Current state:\n{round_evidence}\n\n"
    "Round report (group agreement metrics):\n{report}\n\n"
    "The facilitator must choose exactly one of these options: {options}.\n\n"
    "Recommend one option and explain in one or two short sentences a facilitator "
    "would understand (no statistics jargon). Respond with ONLY a JSON object: "
    '{"recommendation": "<one of the options>", "rationale": "<1-2 sentences>", '
    '"confidence": <0.0-1.0>}'
)


@dataclass
class AiGateRecommendation:
    """An advisory gate recommendation produced by the AI."""

    recommended_option: str
    rationale: str
    confidence: Optional[float] = None


def _render_prompt(template: str, context: Dict[str, str]) -> str:
    """Substitute ``{key}`` placeholders, leaving unknown braces untouched."""
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def recommend_via_ai(
    *,
    options: List[str],
    method_summary: str,
    round_evidence: str,
    report_data: Optional[Dict[str, Any]],
    ai_caller: Callable[[str, Dict[str, Any]], str],
    settings: Dict[str, Any],
) -> Optional[AiGateRecommendation]:
    """Ask the AI to recommend one of ``options`` with a short rationale.

    Returns ``None`` (so the caller falls back to the computational rule) when the
    advisor is disabled, the call fails, the output is malformed, or the
    recommendation is not one of ``options``. Never raises.
    """
    if not settings or not settings.get("enabled"):
        return None
    if not options:
        return None

    # Import here to avoid a module-level cycle with the engine.
    from app.services.agenda_strategy import _validate_output_schema

    template = settings.get("prompt_template") or _DEFAULT_PROMPT_TEMPLATE
    system_prompt = settings.get("system_prompt") or _DEFAULT_SYSTEM_PROMPT
    prompt = _render_prompt(
        template,
        {
            "method_summary": method_summary or "(unnamed method)",
            "round_evidence": round_evidence or "(no evidence)",
            "report": json.dumps(report_data) if report_data else "(no report)",
            "options": ", ".join(options),
        },
    )

    # `ai_caller` reads its provider config from `settings`; carry the system prompt
    # through the same channel the default caller (and tests) expect.
    call_settings = dict(settings)
    call_settings.setdefault("system_prompt", system_prompt)

    try:
        raw = ai_caller(prompt, call_settings)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:  # provider/parse error must never break the gate
        logger.warning("AI gate recommender call failed; falling back: %s", exc)
        return None

    valid, errors = _validate_output_schema(parsed, _OUTPUT_SCHEMA)
    if not valid or not isinstance(parsed, dict):
        logger.warning("AI gate recommender output failed validation: %s", errors)
        return None

    recommendation = str(parsed.get("recommendation") or "").strip()
    if recommendation not in options:
        logger.warning(
            "AI gate recommender returned an out-of-set option %r (allowed: %s)",
            recommendation,
            options,
        )
        return None

    confidence = parsed.get("confidence")
    return AiGateRecommendation(
        recommended_option=recommendation,
        rationale=str(parsed.get("rationale") or "").strip(),
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
    )
