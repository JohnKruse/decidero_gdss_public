"""Tests for convergence predicates.

Canary: Convergent Yak
"""

from app.services.convergence_predicates import (
    get_convergence_predicate_registry,
    FixedNPredicate,
    IQRStabilityPredicate,
)


def test_registry_contains_expected_predicates():
    registry = get_convergence_predicate_registry()
    assert "fixed_n" in registry.list_predicates()
    assert "iqr_stability" in registry.list_predicates()

    assert isinstance(registry.get_predicate("fixed_n"), FixedNPredicate)
    assert isinstance(registry.get_predicate("iqr_stability"), IQRStabilityPredicate)


def test_fixed_n_predicate():
    predicate = FixedNPredicate()
    config = {"max_rounds": 3}

    # 0 rounds
    assert not predicate.evaluate([], config)
    # 2 rounds
    assert not predicate.evaluate([{}, {}], config)
    # 3 rounds
    assert predicate.evaluate([{}, {}, {}], config)
    # 4 rounds
    assert predicate.evaluate([{}, {}, {}, {}], config)


def test_iqr_stability_predicate():
    predicate = IQRStabilityPredicate()
    config = {"threshold": 0.1}

    # Under 2 rounds -> False
    assert not predicate.evaluate([], config)
    assert not predicate.evaluate([{}], config)

    # 2 rounds, stable IQR (both have median IQR = 0.5, change = 0.0 <= 0.1) -> True
    bundle_1 = {
        "items": [
            {"metadata": {"delphi": {"iqr": 0.5}}},
            {"metadata": {"delphi": {"iqr": 0.5}}},
        ]
    }
    bundle_2 = {
        "items": [
            {"metadata": {"delphi": {"iqr": 0.5}}},
            {"metadata": {"delphi": {"iqr": 0.5}}},
        ]
    }
    assert predicate.evaluate([bundle_1, bundle_2], config)

    # 2 rounds, unstable IQR (median IQR changes from 0.5 to 0.7 -> diff 0.2 > 0.1) -> False
    bundle_3 = {
        "items": [
            {"metadata": {"delphi": {"iqr": 0.7}}},
            {"metadata": {"delphi": {"iqr": 0.7}}},
        ]
    }
    assert not predicate.evaluate([bundle_1, bundle_3], config)

    # 2 rounds, change is exactly threshold (0.5 to 0.6 -> diff 0.1 <= 0.1) -> True
    bundle_4 = {
        "items": [
            {"metadata": {"delphi": {"iqr": 0.6}}},
            {"metadata": {"delphi": {"iqr": 0.6}}},
        ]
    }
    assert predicate.evaluate([bundle_1, bundle_4], config)
