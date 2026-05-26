"""Bundle transforms registry and reference implementations.

Canary: Convergent Yak
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import math
from typing import Any, Dict, List


class BundleTransform(ABC):
    """Abstract base class for bundle transforms."""

    @abstractmethod
    def transform(self, input_bundle: Dict[str, Any], transform_config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the transform to the input bundle, returning a new output bundle."""
        pass

    def __call__(self, input_bundle: Dict[str, Any], transform_config: Dict[str, Any]) -> Dict[str, Any]:
        """Allow calling the transform directly as a function."""
        return self.transform(input_bundle, transform_config)


class IdentityBundleTransform(BundleTransform):
    """Identity transform. Returns the input bundle unchanged."""

    def transform(self, input_bundle: Dict[str, Any], transform_config: Dict[str, Any]) -> Dict[str, Any]:
        return input_bundle


class DelphiStatisticalAggregationTransform(BundleTransform):
    """Delphi Statistical Aggregation Transform.

    Consumes a rank-order-voting output bundle and emits an input-ready bundle
    annotated with per-item median, IQR, dispersion, and per-participant outlier flags
    computed against the IQR.
    """

    def transform(self, input_bundle: Dict[str, Any], transform_config: Dict[str, Any]) -> Dict[str, Any]:
        items = input_bundle.get("items") or []
        metadata = input_bundle.get("metadata") or {}
        votes = metadata.get("votes") or []

        # Group votes by option_id: {option_id: {user_id: rank_position}}
        option_votes: Dict[str, Dict[str, int]] = {}
        for vote in votes:
            opt_id = vote.get("option_id")
            u_id = vote.get("user_id")
            pos = vote.get("rank_position")
            if opt_id and u_id and pos is not None:
                option_votes.setdefault(opt_id, {})[u_id] = int(pos)

        new_items = []
        for item in items:
            new_item = {
                "content": item.get("content"),
                "metadata": dict(item.get("metadata") or {}),
                "source": dict(item.get("source") or {})
            }
            # Copy other optional fields to preserve contract conformance
            for key in ("id", "submitted_name", "parent_id", "created_at", "activity_id", "user_id"):
                if key in item:
                    new_item[key] = item[key]

            ro_meta = new_item["metadata"].get("rank_order_voting") or {}
            option_id = ro_meta.get("option_id") or str(new_item.get("id") or "")

            ranks_by_user = option_votes.get(option_id) or {}
            ranks = list(ranks_by_user.values())

            if ranks:
                ranks_sorted = sorted(ranks)
                n = len(ranks_sorted)

                # Median
                if n % 2 == 1:
                    median = float(ranks_sorted[n // 2])
                else:
                    median = (ranks_sorted[n // 2 - 1] + ranks_sorted[n // 2]) / 2.0

                # Q1, Q3 via linear interpolation (NIST/numpy style)
                def get_p(q: float) -> float:
                    if n == 1:
                        return float(ranks_sorted[0])
                    idx = (q / 100.0) * (n - 1)
                    low = int(idx)
                    high = min(low + 1, n - 1)
                    w = idx - low
                    return ranks_sorted[low] * (1.0 - w) + ranks_sorted[high] * w

                q1 = get_p(25.0)
                q3 = get_p(75.0)
                iqr = q3 - q1

                # Dispersion (standard deviation)
                mean = sum(ranks) / n
                variance = sum((x - mean) ** 2 for x in ranks) / n
                dispersion = math.sqrt(variance)

                # Outliers
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr

                outlier_flags = {}
                outliers = []
                for u_id, r in ranks_by_user.items():
                    is_out = (r < lower_bound) or (r > upper_bound)
                    outlier_flags[u_id] = is_out
                    if is_out:
                        outliers.append(u_id)
            else:
                median = 0.0
                iqr = 0.0
                dispersion = 0.0
                outlier_flags = {}
                outliers = []

            # Annotate with the Delphi statistics
            new_item["metadata"]["delphi"] = {
                "median": median,
                "iqr": iqr,
                "dispersion": dispersion,
                "outlier_flags": outlier_flags,
                "outliers": outliers
            }
            new_items.append(new_item)

        return {
            "items": new_items,
            "metadata": {
                "source": "bundle_transform",
                "transform_type": "delphi_statistical_aggregation",
                "original_metadata": metadata
            }
        }


class BundleTransformRegistry:
    """Registry for looking up BundleTransform instances by string name."""

    def __init__(self) -> None:
        self._transforms: Dict[str, BundleTransform] = {}
        self.register("identity", IdentityBundleTransform())
        self.register("delphi_statistical_aggregation", DelphiStatisticalAggregationTransform())

    def register(self, name: str, transform: BundleTransform) -> None:
        self._transforms[name.strip().lower()] = transform

    def get_transform(self, name: str) -> BundleTransform | None:
        return self._transforms.get(name.strip().lower())

    def list_transforms(self) -> List[str]:
        return list(self._transforms.keys())


_registry = BundleTransformRegistry()


def get_bundle_transform_registry() -> BundleTransformRegistry:
    return _registry
