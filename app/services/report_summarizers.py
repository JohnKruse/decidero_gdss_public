"""Report summarizers registry and reference implementations.

Canary: Plainspoken Marmot

A report summarizer is the human-facing dual of a convergence predicate
(`app/services/convergence_predicates.py`): both are read-only projections over
a round bundle. The predicate reads it and emits a verdict; the summarizer reads
it and emits a **flat namespace of named scalar facts** for a facilitator (or
participant) report-out — and, downstream, for the declarative recommender rule
to branch on (the Layer-A contract described in the HICSS outline, section L.3).

Summarizers are looked up by name + config, mirroring the convergence-predicate
and bundle-transform registries, so reports are not Delphi-specific: a new method
registers its own summarizer rather than special-casing report code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ReportSummarizer(ABC):
    """Abstract base class for report summarizers.

    `summarize` takes a round bundle (`{"items": [...], "metadata": {...}}`) and
    a config dict, and returns a flat dict of named scalar facts. The scalar
    namespace is the contract consumed by report-out UIs and by the Layer-B
    recommender rule, so implementations must return JSON-serializable scalars.
    """

    @abstractmethod
    def summarize(self, bundle: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def __call__(self, bundle: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        return self.summarize(bundle, config)


class DelphiRoundAgreementSummarizer(ReportSummarizer):
    """Aggregate a Delphi round's ranking bundle into an agreement summary.

    Runs the Delphi statistical aggregation on the round's ranking output (the
    same transform that feeds the next round's feedback) and reduces it to
    counts + an agreement label — no per-idea detail.

    Config (all optional):
        strong_iqr:    IQR (rank positions) at or below which an item counts as
                       strong agreement, and the median-IQR cutoff for the
                       "Strong agreement" label. Default 1.0.
        contested_iqr: IQR above which an item counts as contested, and the
                       median-IQR cutoff for "Moderate agreement". Default 2.0.

    Returns the scalar namespace: item_count, participant_count, median_iqr,
    strong_agreement_items, contested_items, outlier_instances,
    participants_with_outliers, agreement_label.
    """

    _DEFAULT_STRONG_IQR = 1.0
    _DEFAULT_CONTESTED_IQR = 2.0

    def summarize(self, bundle: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.bundle_transforms import get_bundle_transform_registry

        strong_iqr = float(config.get("strong_iqr", self._DEFAULT_STRONG_IQR))
        contested_iqr = float(config.get("contested_iqr", self._DEFAULT_CONTESTED_IQR))

        transform = get_bundle_transform_registry().get_transform(
            "delphi_statistical_aggregation"
        )
        aggregated = transform.transform(
            {
                "items": list(bundle.get("items") or []),
                "metadata": dict(bundle.get("metadata") or {}),
            },
            {},
        )
        items: List[Dict[str, Any]] = aggregated.get("items") or []

        votes = dict(bundle.get("metadata") or {}).get("votes") or []
        participant_ids = {v.get("user_id") for v in votes if v.get("user_id")}

        iqrs: List[float] = []
        strong = 0
        contested = 0
        outlier_instances = 0
        flagged_participants: set = set()
        for item in items:
            delphi = (item.get("metadata") or {}).get("delphi") or {}
            iqr = float(delphi.get("iqr", 0.0) or 0.0)
            iqrs.append(iqr)
            if iqr <= strong_iqr:
                strong += 1
            if iqr > contested_iqr:
                contested += 1
            outliers = delphi.get("outliers") or []
            outlier_instances += len(outliers)
            flagged_participants.update(outliers)

        median_iqr = 0.0
        if iqrs:
            ordered = sorted(iqrs)
            mid = len(ordered) // 2
            median_iqr = (
                ordered[mid]
                if len(ordered) % 2 == 1
                else (ordered[mid - 1] + ordered[mid]) / 2.0
            )

        if not items:
            agreement_label = "No items"
        elif median_iqr <= strong_iqr:
            agreement_label = "Strong agreement"
        elif median_iqr <= contested_iqr:
            agreement_label = "Moderate agreement"
        else:
            agreement_label = "Divergent — several items contested"

        return {
            "item_count": len(items),
            "participant_count": len(participant_ids),
            "median_iqr": round(median_iqr, 2),
            "strong_agreement_items": strong,
            "contested_items": contested,
            "outlier_instances": outlier_instances,
            "participants_with_outliers": len(flagged_participants),
            "agreement_label": agreement_label,
        }


class ReportSummarizerRegistry:
    """Registry for looking up ReportSummarizer instances by string name."""

    def __init__(self) -> None:
        self._summarizers: Dict[str, ReportSummarizer] = {}
        self.register("delphi_round_agreement", DelphiRoundAgreementSummarizer())

    def register(self, name: str, summarizer: ReportSummarizer) -> None:
        self._summarizers[name.strip().lower()] = summarizer

    def get_summarizer(self, name: str) -> ReportSummarizer | None:
        return self._summarizers.get(name.strip().lower())

    def list_summarizers(self) -> List[str]:
        return list(self._summarizers.keys())


_registry = ReportSummarizerRegistry()


def get_report_summarizer_registry() -> ReportSummarizerRegistry:
    return _registry
