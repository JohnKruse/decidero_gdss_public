"""Convergence predicates registry and reference implementations.

Canary: Convergent Yak
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ConvergencePredicate(ABC):
    """Abstract base class for convergence predicates."""

    @abstractmethod
    def evaluate(self, bundle_history: List[Any], predicate_config: Dict[str, Any]) -> bool:
        """Evaluate the predicate against the bundle history and return True if converged."""
        pass

    def __call__(self, bundle_history: List[Any], predicate_config: Dict[str, Any]) -> bool:
        """Allow calling the predicate directly as a function."""
        return self.evaluate(bundle_history, predicate_config)


class FixedNPredicate(ConvergencePredicate):
    """Fires after a configured number of rounds."""

    def evaluate(self, bundle_history: List[Any], predicate_config: Dict[str, Any]) -> bool:
        max_rounds = (
            predicate_config.get("max_rounds")
            or predicate_config.get("n")
            or predicate_config.get("limit")
            or 0
        )
        return len(bundle_history) >= max_rounds


class IQRStabilityPredicate(ConvergencePredicate):
    """Fires when the median IQR across items changes by less than or equal to threshold

    across two consecutive rounds.
    """

    def evaluate(self, bundle_history: List[Any], predicate_config: Dict[str, Any]) -> bool:
        if len(bundle_history) < 2:
            return False

        threshold = (
            predicate_config.get("threshold")
            if predicate_config.get("threshold") is not None
            else predicate_config.get("epsilon")
            if predicate_config.get("epsilon") is not None
            else 0.0
        )

        def get_median_iqr_for_round(bundle: Any) -> float:
            if isinstance(bundle, dict):
                items = bundle.get("items") or []
            elif hasattr(bundle, "items"):
                items = bundle.items
            else:
                items = []

            iqrs = []
            for item in items:
                if isinstance(item, dict):
                    delphi = item.get("metadata", {}).get("delphi") or {}
                    iqrs.append(float(delphi.get("iqr", 0.0)))
                elif hasattr(item, "metadata"):
                    metadata = getattr(item, "metadata", {}) or {}
                    delphi = metadata.get("delphi") or {}
                    iqrs.append(float(delphi.get("iqr", 0.0)))

            if not iqrs:
                return 0.0

            iqrs_sorted = sorted(iqrs)
            n = len(iqrs_sorted)
            if n % 2 == 1:
                return float(iqrs_sorted[n // 2])
            else:
                return (iqrs_sorted[n // 2 - 1] + iqrs_sorted[n // 2]) / 2.0

        median_iqr_prev = get_median_iqr_for_round(bundle_history[-2])
        median_iqr_curr = get_median_iqr_for_round(bundle_history[-1])

        return abs(median_iqr_curr - median_iqr_prev) <= threshold


class ConvergencePredicateRegistry:
    """Registry for looking up ConvergencePredicate instances by string name."""

    def __init__(self) -> None:
        self._predicates: Dict[str, ConvergencePredicate] = {}
        self.register("fixed_n", FixedNPredicate())
        self.register("iqr_stability", IQRStabilityPredicate())

    def register(self, name: str, predicate: ConvergencePredicate) -> None:
        self._predicates[name.strip().lower()] = predicate

    def get_predicate(self, name: str) -> ConvergencePredicate | None:
        return self._predicates.get(name.strip().lower())

    def list_predicates(self) -> List[str]:
        return list(self._predicates.keys())


_registry = ConvergencePredicateRegistry()


def get_convergence_predicate_registry() -> ConvergencePredicateRegistry:
    return _registry
