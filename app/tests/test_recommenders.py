"""Tests for the Layer-B recommender rule evaluator."""

from __future__ import annotations

import pytest

from app.services.recommenders import (
    RecommenderRuleError,
    evaluate_condition,
    evaluate_rule,
)

_NS = {
    "converged": True,
    "median_iqr": 1.5,
    "contested_items": 2,
    "agreement_label": "Moderate agreement",
}


# --- conditions -------------------------------------------------------------

def test_bare_boolean_metric():
    assert evaluate_condition("converged", _NS) is True
    assert evaluate_condition("converged", {**_NS, "converged": False}) is False


def test_numeric_comparisons():
    assert evaluate_condition("median_iqr <= 2.0", _NS) is True
    assert evaluate_condition("median_iqr <= 1.0", _NS) is False
    assert evaluate_condition("contested_items > 1", _NS) is True


def test_string_equality():
    assert evaluate_condition("agreement_label == 'Moderate agreement'", _NS) is True


def test_boolean_combinations():
    assert evaluate_condition("converged and median_iqr <= 2.0", _NS) is True
    assert evaluate_condition("converged and median_iqr <= 1.0", _NS) is False
    assert evaluate_condition("not converged or contested_items > 1", _NS) is True


def test_unknown_metric_is_an_error():
    with pytest.raises(RecommenderRuleError):
        evaluate_condition("stability_index <= 0.1", _NS)


@pytest.mark.parametrize(
    "expr",
    [
        "median_iqr + 1 <= 3",        # arithmetic (BinOp)
        "len(contested_items) > 0",    # function call
        "agreement_label.lower() == 'x'",  # attribute + call
        "metrics['median_iqr'] <= 1",  # subscript
        "median_iqr in (1, 2)",        # disallowed operator
    ],
)
def test_disallowed_constructs_are_rejected(expr):
    ns = {**_NS, "metrics": {}}
    with pytest.raises(RecommenderRuleError):
        evaluate_condition(expr, ns)


def test_empty_condition_is_an_error():
    with pytest.raises(RecommenderRuleError):
        evaluate_condition("   ", _NS)


# --- rules ------------------------------------------------------------------

def test_first_matching_guard_wins():
    rule = [
        {"when": "converged", "recommend": "conclude"},
        {"when": "median_iqr <= 2.0", "recommend": "conclude"},
        {"default": "continue"},
    ]
    assert evaluate_rule(rule, _NS) == "conclude"


def test_falls_through_to_default():
    rule = [
        {"when": "not converged", "recommend": "continue"},
        {"default": "conclude"},
    ]
    assert evaluate_rule(rule, _NS) == "conclude"


def test_no_match_no_default_returns_none():
    rule = [{"when": "not converged", "recommend": "continue"}]
    assert evaluate_rule(rule, _NS) is None


def test_default_must_be_terminal_only_key():
    with pytest.raises(RecommenderRuleError):
        evaluate_rule([{"default": "x", "when": "converged"}], _NS)


def test_guard_missing_required_keys():
    with pytest.raises(RecommenderRuleError):
        evaluate_rule([{"when": "converged"}], _NS)


def test_rule_must_be_list():
    with pytest.raises(RecommenderRuleError):
        evaluate_rule({"when": "converged", "recommend": "x"}, _NS)
