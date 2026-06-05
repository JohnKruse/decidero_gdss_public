"""Aggregate a Delphi round's ranking statistics for a facilitator report-out.

When the facilitator reaches the per-round justification step, this produces an
*aggregated* sense of where the group landed — counts and an agreement summary,
not per-idea detail. The aggregation itself is delegated to the
`delphi_round_agreement` report summarizer
(`app/services/report_summarizers.py`); this module only locates the round's
ranking bundle and wraps the summarizer output with availability + round number.
Used by the round-statistics endpoint behind the facilitator report-out dialog.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting


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
    from app.services.report_summarizers import get_report_summarizer_registry

    round_index = _round_index_for(activity)
    bundle = _find_round_ranking_bundle(db, meeting, round_index)
    if bundle is None:
        return {
            "available": False,
            "round_number": round_index + 1,
            "detail": "No ranking results for this round yet.",
        }

    summarizer = get_report_summarizer_registry().get_summarizer(
        "delphi_round_agreement"
    )
    summary = summarizer.summarize(
        {"items": list(bundle.items or []), "metadata": dict(bundle.bundle_metadata or {})},
        {},
    )

    return {
        "available": True,
        "round_number": round_index + 1,
        **summary,
    }
