"""Aggregate a Delphi round's ranking statistics for a facilitator report-out.

When the facilitator reaches the per-round justification step, this produces an
*aggregated* sense of where the group landed — counts and an agreement summary,
not per-idea detail — by running the Delphi statistical aggregation on the
round's ranking output on demand (the transform that normally feeds the next
round's feedback). Used by the round-statistics endpoint behind the facilitator
report-out dialog.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting

# IQR thresholds (in rank positions) for the qualitative agreement summary.
_STRONG_AGREEMENT_IQR = 1.0
_CONTESTED_IQR = 2.0


def _round_index_for(activity: AgendaActivity) -> int:
    orchestration = (activity.config or {}).get("_orchestration") or {}
    try:
        return int(orchestration.get("round_index", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _find_round_ranking_bundle(
    db: Session, meeting: Meeting, round_index: int
) -> Optional[ActivityBundle]:
    """The round's rank-order output bundle (carries the votes the transform reads)."""
    candidates = (
        db.query(ActivityBundle)
        .filter(
            ActivityBundle.meeting_id == meeting.meeting_id,
            ActivityBundle.kind == "output",
            ActivityBundle.round_index == round_index,
        )
        .order_by(ActivityBundle.id.desc())
        .all()
    )
    for bundle in candidates:
        source = dict(bundle.bundle_metadata or {}).get("source")
        if source == "rank_order_voting":
            return bundle
    return None


def compute_round_statistics(
    db: Session, meeting: Meeting, activity: AgendaActivity
) -> Dict[str, Any]:
    """Return an aggregated statistics summary for the round `activity` sits in.

    Shape (always includes `available`):
        {available: bool, round_number, item_count, participant_count,
         median_iqr, strong_agreement_items, contested_items, outlier_instances,
         participants_with_outliers, agreement_label}
    """
    from app.services.bundle_transforms import get_bundle_transform_registry

    round_index = _round_index_for(activity)
    bundle = _find_round_ranking_bundle(db, meeting, round_index)
    if bundle is None:
        return {
            "available": False,
            "round_number": round_index + 1,
            "detail": "No ranking results for this round yet.",
        }

    transform = get_bundle_transform_registry().get_transform(
        "delphi_statistical_aggregation"
    )
    aggregated = transform.transform(
        {"items": list(bundle.items or []), "metadata": dict(bundle.bundle_metadata or {})},
        {},
    )
    items: List[Dict[str, Any]] = aggregated.get("items") or []

    votes = dict(bundle.bundle_metadata or {}).get("votes") or []
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
        if iqr <= _STRONG_AGREEMENT_IQR:
            strong += 1
        if iqr > _CONTESTED_IQR:
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
    elif median_iqr <= _STRONG_AGREEMENT_IQR:
        agreement_label = "Strong agreement"
    elif median_iqr <= _CONTESTED_IQR:
        agreement_label = "Moderate agreement"
    else:
        agreement_label = "Divergent — several items contested"

    return {
        "available": True,
        "round_number": round_index + 1,
        "item_count": len(items),
        "participant_count": len(participant_ids),
        "median_iqr": round(median_iqr, 2),
        "strong_agreement_items": strong,
        "contested_items": contested,
        "outlier_instances": outlier_instances,
        "participants_with_outliers": len(flagged_participants),
        "agreement_label": agreement_label,
    }
