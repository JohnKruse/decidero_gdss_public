"""Plainspoken Marmot: Phase 9 Step 2 — control-point card compile/decompile tests."""
import json
from pathlib import Path

import pytest

from app.services.orchestration_authoring import (
    compile_control_point_card,
    decompile_control_point_card,
    summarize_control_point,
)

_DELPHI_PATH = Path(__file__).resolve().parents[2] / "orchestrations" / "delphi.json"


def _delphi_dict():
    return json.loads(_DELPHI_PATH.read_text(encoding="utf-8"))


def _base_card(**overrides):
    card = {
        "activity_tool_type": "rank_order_voting",
        "activity_title": "Rank Options",
        "who_decides": "assisted",
        "stop_condition": "responses_stabilize",
        "max_rounds": 4,
        "threshold": 0.15,
    }
    card.update(overrides)
    return card


def test_compile_facilitator_mode_no_recommender():
    step = compile_control_point_card(_base_card(who_decides="facilitator"))
    assert step["type"] == "iterate"
    gate = step["round_gate"]["decision"]
    assert gate["options"] == ["continue", "conclude"]
    assert "recommender" not in gate


def test_compile_assisted_mode_with_recommender():
    step = compile_control_point_card(_base_card(who_decides="assisted"))
    gate = step["round_gate"]["decision"]
    assert "recommender" in gate
    rule = gate["recommender"]["rule"]
    assert rule[0] == {"when": "converged", "recommend": "conclude"}
    assert rule[1] == {"default": "continue"}


def test_compile_auto_mode_no_gate():
    step = compile_control_point_card(_base_card(who_decides="auto"))
    assert "round_gate" not in step


def test_compile_responses_stabilize_maps_to_iqr_stability():
    step = compile_control_point_card(
        _base_card(stop_condition="responses_stabilize", threshold=0.2)
    )
    pred = step["convergence_predicate"]
    assert pred["name"] == "iqr_stability"
    assert pred["config"]["threshold"] == 0.2


def test_compile_fixed_rounds_maps_to_fixed_n():
    step = compile_control_point_card(
        _base_card(stop_condition="fixed_rounds", max_rounds=3)
    )
    pred = step["convergence_predicate"]
    assert pred["name"] == "fixed_n"
    assert pred["config"]["max_rounds"] == 3


def test_compile_custom_stop_condition_adds_ai_decision_rubric():
    step = compile_control_point_card(
        _base_card(
            stop_condition="custom",
            stop_condition_text="When the facilitator is satisfied with convergence.",
        )
    )
    sequence_steps = step["steps"][0]["steps"]
    assert [item["type"] for item in sequence_steps] == ["activity", "ai-decision"]
    assert sequence_steps[0]["transform_input"] == "previous_round_feedback"
    ai_step = sequence_steps[1]
    assert "When the facilitator is satisfied with convergence." in ai_step["prompt_template"]
    assert ai_step["review_required"] is False
    assert ai_step["context_bundle_keys"] == []
    assert ai_step["output_schema"]["required"] == [
        "recommendation",
        "rationale",
        "confidence",
    ]
    assert "_custom_stop_description" not in step


def test_compile_custom_stop_condition_validates_against_loader():
    from app.services.orchestration_loader import load_orchestration_data

    delphi = _delphi_dict()
    step = compile_control_point_card(
        _base_card(
            stop_condition="custom",
            stop_condition_text="Conclude once the top three options are stable enough to report.",
        )
    )
    delphi["steps"][0]["steps"][1] = step
    doc = load_orchestration_data(delphi)
    iterate = doc.steps[0].steps[1]
    assert iterate.steps[0].steps[1].type == "ai-decision"


def test_compile_output_validates_against_loader():
    from app.services.orchestration_loader import load_orchestration_data

    delphi = _delphi_dict()
    step = compile_control_point_card(_base_card())
    # Replace the Delphi iterate step with the compiled one.
    delphi["steps"][0]["steps"][1] = step
    doc = load_orchestration_data(delphi)
    assert doc.name == "Classical Delphi"


def test_decompile_round_trips_all_modes():
    for mode in ("facilitator", "assisted", "auto"):
        card_in = _base_card(who_decides=mode)
        step = compile_control_point_card(card_in)
        card_out = decompile_control_point_card(step)
        assert card_out["who_decides"] == mode
        assert card_out["max_rounds"] == card_in["max_rounds"]
        assert card_out["activity_tool_type"] == card_in["activity_tool_type"]


def test_decompile_custom_stop_condition_round_trips_ai_rubric():
    card_in = _base_card(
        stop_condition="custom",
        stop_condition_text="Conclude when comments no longer change the shortlist.",
    )
    step = compile_control_point_card(card_in)
    card_out = decompile_control_point_card(step)
    assert card_out["stop_condition"] == "custom"
    assert card_out["stop_condition_text"] == card_in["stop_condition_text"]


def test_decompile_delphi_iterate():
    delphi = _delphi_dict()
    iterate = delphi["steps"][0]["steps"][1]
    card = decompile_control_point_card(iterate)
    assert card["who_decides"] == "assisted"
    assert card["max_rounds"] == 4
    assert card["activity_tool_type"] == "rank_order_voting"
    assert card["threshold"] == 0.15


def test_compile_rejects_missing_activity():
    with pytest.raises(ValueError, match="Choose an activity"):
        compile_control_point_card(_base_card(activity_tool_type=""))


def test_compile_rejects_zero_rounds():
    with pytest.raises(ValueError, match="round limit"):
        compile_control_point_card(_base_card(max_rounds=0))


def test_summarize_control_point_is_plain_language():
    step = compile_control_point_card(_base_card())
    lines = summarize_control_point(step)
    text = " ".join(lines).lower()
    assert "repeat" in text
    assert "rank options" in text
    assert "4" in text
