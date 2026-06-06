"""Adaptive Delphi controlled-feedback selection.

Computes item-level disagreement bands and the facilitator's suggested comment
workload for the next feedback pass. This is a read-only projection over a
Delphi statistical feedback bundle; it does not advance orchestration state.
"""

from __future__ import annotations

from math import ceil
from typing import Any, Dict, List


DEFAULT_FEEDBACK_POLICY: Dict[str, Any] = {
    "comment_selection": {
        "strategy": "adaptive_least_converged",
        "default_fraction": 0.25,
        "max_fraction": 0.5,
        "low_disagreement_fraction": 0.0,
        "moderate_disagreement_fraction": 0.15,
        "high_disagreement_fraction": 0.25,
        "min_items_when_disputed": 1,
        "allow_skip": True,
    },
    "agreement_bands": {
        "score_source": "iqr",
        "green_max": 1.0,
        "yellow_max": 2.0,
    },
}


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _policy_section(policy: Dict[str, Any], key: str) -> Dict[str, Any]:
    section = policy.get(key)
    if isinstance(section, dict):
        return section
    default = DEFAULT_FEEDBACK_POLICY.get(key)
    return dict(default) if isinstance(default, dict) else {}


def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = {key: dict(value) if isinstance(value, dict) else value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _band_for(score: float, bands: Dict[str, Any]) -> str:
    green_max = _as_float(bands.get("green_max"), 1.0)
    yellow_max = _as_float(bands.get("yellow_max"), 2.0)
    if score <= green_max:
        return "green"
    if score <= yellow_max:
        return "yellow"
    return "red"


def _suggestion_fraction(counts: Dict[str, int], selection: Dict[str, Any]) -> float:
    if counts.get("red", 0) > 0:
        return _as_float(selection.get("high_disagreement_fraction"), 0.25)
    if counts.get("yellow", 0) > 0:
        return _as_float(selection.get("moderate_disagreement_fraction"), 0.15)
    return _as_float(selection.get("low_disagreement_fraction"), 0.0)


def _ensure_aggregated(bundle: Dict[str, Any]) -> Dict[str, Any]:
    items = list(bundle.get("items") or [])
    if any(
        isinstance((item.get("metadata") or {}).get("delphi"), dict)
        for item in items
        if isinstance(item, dict)
    ):
        return {"items": items, "metadata": dict(bundle.get("metadata") or {})}

    from app.services.bundle_transforms import get_bundle_transform_registry

    transform = get_bundle_transform_registry().get_transform("delphi_statistical_aggregation")
    if transform is None:
        return {"items": items, "metadata": dict(bundle.get("metadata") or {})}
    return transform.transform(
        {"items": items, "metadata": dict(bundle.get("metadata") or {})},
        {},
    )


def build_delphi_feedback_selection(
    bundle: Dict[str, Any],
    policy: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return item disagreement bands and suggested comment selection.

    The result is intentionally JSON-serializable so it can be embedded in a
    facilitator report or activity config without further translation.
    """
    effective_policy = _merge_dicts({}, DEFAULT_FEEDBACK_POLICY)
    if isinstance(policy, dict):
        effective_policy = _merge_dicts(effective_policy, policy)
    selection = _policy_section(effective_policy, "comment_selection")
    bands = _policy_section(effective_policy, "agreement_bands")

    aggregated = _ensure_aggregated(bundle)
    rows: List[Dict[str, Any]] = []
    counts = {"green": 0, "yellow": 0, "red": 0}

    for index, item in enumerate(aggregated.get("items") or []):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        delphi = metadata.get("delphi") if isinstance(metadata.get("delphi"), dict) else {}
        score = _as_float(delphi.get("iqr"), 0.0)
        dispersion = _as_float(delphi.get("dispersion"), 0.0)
        band = _band_for(score, bands)
        counts[band] += 1
        option_meta = metadata.get("rank_order_voting")
        option_id = (
            option_meta.get("option_id")
            if isinstance(option_meta, dict)
            else item.get("id")
        )
        rows.append(
            {
                "item_key": str(option_id or item.get("content") or index),
                "content": item.get("content"),
                "median": delphi.get("median"),
                "iqr": score,
                "dispersion": dispersion,
                "band": band,
                "rank": index + 1,
            }
        )

    total = len(rows)
    max_fraction = max(_as_float(selection.get("max_fraction"), 0.5), 0.0)
    max_count = min(total, ceil(total * max_fraction)) if total else 0
    fraction = max(_suggestion_fraction(counts, selection), 0.0)
    suggested_count = min(total, ceil(total * fraction)) if total else 0
    if suggested_count > 0:
        suggested_count = max(
            suggested_count,
            min(total, _as_int(selection.get("min_items_when_disputed"), 1)),
        )
    suggested_count = min(suggested_count, max_count)

    ordered = sorted(
        rows,
        key=lambda row: (
            -_as_float(row["iqr"]),
            -_as_float(row["dispersion"]),
            str(row.get("content") or "").casefold(),
        ),
    )
    selected = ordered[:suggested_count]

    return {
        "strategy": selection.get("strategy", "adaptive_least_converged"),
        "item_count": total,
        "band_counts": counts,
        "suggested_count": suggested_count,
        "max_selectable_count": max_count,
        "allow_skip": bool(selection.get("allow_skip", True)),
        "items": ordered,
        "selected_item_keys": [row["item_key"] for row in selected],
    }
