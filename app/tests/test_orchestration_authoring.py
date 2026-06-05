"""Plainspoken Marmot: Phase 9 Step 1 fork-and-tune compile service tests."""
import json
from pathlib import Path

import pytest

from app.services.orchestration_authoring import apply_tuning, summarize_orchestration

_DELPHI_PATH = Path(__file__).resolve().parents[2] / "orchestrations" / "delphi.json"


def _delphi_dict():
    return json.loads(_DELPHI_PATH.read_text(encoding="utf-8"))


def test_apply_tuning_sets_round_limit_and_threshold():
    tuned = apply_tuning(_delphi_dict(), max_rounds=6, convergence_threshold=0.25)
    iterate = tuned["steps"][0]["steps"][1]
    assert iterate["max_rounds"] == 6
    assert iterate["convergence_predicate"]["config"]["threshold"] == 0.25


def test_apply_tuning_does_not_mutate_the_base_document():
    base = _delphi_dict()
    before = base["steps"][0]["steps"][1]["max_rounds"]
    apply_tuning(base, max_rounds=before + 3)
    assert base["steps"][0]["steps"][1]["max_rounds"] == before


def test_apply_tuning_who_decides_toggles_round_gate():
    automatic = apply_tuning(_delphi_dict(), who_decides="automatic")
    assert "round_gate" not in automatic["steps"][0]["steps"][1]

    facilitator = apply_tuning(automatic, who_decides="facilitator")
    gate = facilitator["steps"][0]["steps"][1]["round_gate"]
    # Plainspoken Marmot: the gate embeds a facilitator-decision; the suggestion
    # is a recommender rule over the convergence verdict, not a mode/enum.
    decision = gate["decision"]
    assert decision["options"] == ["continue", "conclude"]
    assert decision["recommender"]["rule"][0] == {"when": "converged", "recommend": "conclude"}


def test_apply_tuning_rejects_invalid_round_limit():
    with pytest.raises(ValueError):
        apply_tuning(_delphi_dict(), max_rounds=0)


def test_apply_tuning_output_validates_against_loader():
    # An out-of-range threshold the loader/predicate accepts still yields a doc that
    # loads; a structurally broken tuning would raise. Here we assert the happy path
    # produces a loadable document.
    from app.services.orchestration_loader import load_orchestration_data

    tuned = apply_tuning(_delphi_dict(), max_rounds=3, convergence_threshold=0.1)
    document = load_orchestration_data(tuned)
    assert document.name == "Classical Delphi"


def test_summarize_orchestration_is_plain_language():
    lines = summarize_orchestration(_delphi_dict())
    text = " ".join(lines).lower()
    assert any("start with" in line.lower() for line in lines)
    assert "repeat" in text
    # Delphi ships with a facilitator gate, so the summary mentions the decision.
    assert "decide whether to run another round or conclude" in text


def test_summarize_reflects_automatic_when_gate_removed():
    automatic = apply_tuning(_delphi_dict(), who_decides="automatic")
    text = " ".join(summarize_orchestration(automatic)).lower()
    assert "automatically" in text
