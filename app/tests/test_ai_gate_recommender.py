"""Tests for the AI round-gate advisor helper (Plainspoken Marmot).

The helper is advisory and must never raise into the gate: it returns an
``AiGateRecommendation`` on a valid response and ``None`` (→ engine falls back to
the computational rule) on disabled settings, provider/parse errors, malformed
output, or a recommendation outside the allowed options. No network — the
``ai_caller`` is a stub.
"""

from __future__ import annotations

import json

from app.services.ai_gate_recommender import recommend_via_ai

_OPTIONS = ["continue", "conclude"]
_ENABLED_SETTINGS = {
    "enabled": True,
    "provider": "openrouter",
    "model": "test/model",
    "prompt_template": "Method: {method_summary}\nState:\n{round_evidence}\n"
    "Report: {report}\nOptions: {options}",
    "system_prompt": "advise the facilitator",
}


def _caller_returning(payload):
    captured = {}

    def _caller(prompt, settings):
        captured["prompt"] = prompt
        captured["settings"] = settings
        return payload if isinstance(payload, str) else json.dumps(payload)

    return _caller, captured


def _recommend(caller, settings=None):
    return recommend_via_ai(
        options=_OPTIONS,
        method_summary="Classical Delphi: repeats 'Rank' each round.",
        round_evidence="Round 2 of up to 4 complete. Responses still changing.",
        report_data={"agreement_label": "yellow"},
        ai_caller=caller,
        settings=settings if settings is not None else _ENABLED_SETTINGS,
    )


def test_valid_response_returns_recommendation_with_rationale():
    caller, captured = _caller_returning(
        {"recommendation": "continue", "rationale": "The group is still moving.", "confidence": 0.7}
    )
    result = _recommend(caller)
    assert result is not None
    assert result.recommended_option == "continue"
    assert result.rationale == "The group is still moving."
    assert result.confidence == 0.7
    # The config-supplied template was rendered with runtime context + options.
    assert "Classical Delphi" in captured["prompt"]
    assert "continue, conclude" in captured["prompt"]
    assert captured["settings"].get("system_prompt") == "advise the facilitator"


def test_disabled_settings_returns_none():
    caller, _ = _caller_returning({"recommendation": "continue", "rationale": "x"})
    assert _recommend(caller, settings={"enabled": False}) is None


def test_option_not_in_set_returns_none():
    caller, _ = _caller_returning({"recommendation": "maybe", "rationale": "unsure"})
    assert _recommend(caller) is None


def test_missing_required_field_returns_none():
    caller, _ = _caller_returning({"recommendation": "continue"})  # no rationale
    assert _recommend(caller) is None


def test_malformed_json_returns_none():
    caller, _ = _caller_returning("not json at all")
    assert _recommend(caller) is None


def test_provider_error_returns_none():
    def _boom(prompt, settings):
        raise RuntimeError("provider unreachable")

    assert _recommend(_boom) is None
