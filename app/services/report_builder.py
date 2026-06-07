"""Deterministic report builder: round bundles -> canonical report_payload.

Canary: Plainspoken Marmot

Turns a method's per-round output bundles into the canonical report model
(`docs/schemas/report_payload.schema.json`). Pure and deterministic — same input
always yields the same model; no AI, no I/O. Renderers (`report_renderers`) are
pure functions of what this produces.

v1 handles the **rank-order** paradigm (Decidero's Delphi): each round bundle is a
`rank_order_voting` output (`metadata.votes` = option_id/user_id/rank_position).
Consensus metrics are chosen for that paradigm (Kendall's W, median/IQR over rank
positions). The structure leaves room for a rating paradigm later (see
`report_metrics` paradigm note).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.bundle_transforms import get_bundle_transform_registry
from app.services.report_metrics import agreement_band, spearman_rho
from app.services.report_summarizers import get_report_summarizer_registry

REPORT_VERSION = "1.0"
_DEFAULT_SPEC: Dict[str, Any] = {
    "green_max_iqr": 1.0,
    "yellow_max_iqr": 2.0,
    "bump_top_n": 8,
}


def _item_key(item: Dict[str, Any]) -> str:
    """Activity-independent identity for an item, stable across rounds.

    Mirrors RankOrderVotingManager._stable_option_key: option ids are prefixed
    `{activity_id}:...` and each round is a new activity, so strip that prefix.
    Fall back to explicit stable_key, then to a content slug.
    """
    meta = item.get("metadata") or {}
    if meta.get("stable_key"):
        return str(meta["stable_key"])
    ro = meta.get("rank_order_voting") or {}
    option_id = ro.get("option_id") or item.get("id")
    if option_id:
        text = str(option_id)
        return text.split(":", 1)[1] if ":" in text else text
    return str(item.get("content") or "").strip().lower()


def _aggregate_round(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Annotate a round bundle's items with Delphi median/IQR, return item records."""
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
    records: List[Dict[str, Any]] = []
    for item in aggregated.get("items") or []:
        delphi = (item.get("metadata") or {}).get("delphi") or {}
        iqr = float(delphi.get("iqr", 0.0) or 0.0)
        records.append(
            {
                "key": _item_key(item),
                "label": str(item.get("content") or "").strip(),
                "median": float(delphi.get("median", 0.0) or 0.0),
                "iqr": round(iqr, 2),
                "band": agreement_band(
                    iqr, _DEFAULT_SPEC["green_max_iqr"], _DEFAULT_SPEC["yellow_max_iqr"]
                ),
            }
        )
    return records


def _rank_round(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Group ranking within a round: lower median (then IQR) = better rank."""
    ordered = sorted(records, key=lambda r: (r["median"], r["iqr"]))
    return {r["key"]: i + 1 for i, r in enumerate(ordered)}


def _kendalls_w(bundle: Dict[str, Any]) -> Optional[float]:
    summ = get_report_summarizer_registry().get_summarizer("kendalls_w")
    return summ.summarize(bundle, {}).get("kendalls_w")


def _band_counts(records: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"green": 0, "yellow": 0, "red": 0}
    for r in records:
        counts[r["band"]] = counts.get(r["band"], 0) + 1
    return counts


def build_report(
    round_bundles: List[Dict[str, Any]],
    meeting: Dict[str, Any],
    spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a canonical report_payload from ordered per-round bundles."""
    cfg = {**_DEFAULT_SPEC, **(spec or {})}
    if not round_bundles:
        raise ValueError("build_report requires at least one round bundle")

    # Per-round derived data.
    per_round_records = [_aggregate_round(b) for b in round_bundles]
    per_round_ranks = [_rank_round(recs) for recs in per_round_records]
    per_round_w = [_kendalls_w(b) for b in round_bundles]
    per_round_bands = [_band_counts(recs) for recs in per_round_records]
    n_rounds = len(round_bundles)
    cats = [f"Round {i + 1}" for i in range(n_rounds)]

    final_records = per_round_records[-1]
    final_ranks = per_round_ranks[-1]
    first_ranks = per_round_ranks[0]
    # Label lookup (final round preferred, else any round it appeared in).
    label_by_key: Dict[str, str] = {}
    for recs in per_round_records:
        for r in recs:
            label_by_key.setdefault(r["key"], r["label"])
    for r in final_records:
        label_by_key[r["key"]] = r["label"]
    final_by_key = {r["key"]: r for r in final_records}

    # Union of items, ordered by final rank then first appearance.
    ordered_keys = sorted(final_by_key, key=lambda k: final_ranks[k])
    for recs in per_round_records:
        for r in recs:
            if r["key"] not in final_by_key and r["key"] not in ordered_keys:
                ordered_keys.append(r["key"])

    # --- headline ranked list (final round) ---
    ranked_items = [
        {
            "rank": final_ranks[r["key"]],
            "label": r["label"],
            "stable_key": r["key"],
            "stats": {"median": r["median"], "iqr": r["iqr"], "agreement_band": r["band"]},
        }
        for r in sorted(final_records, key=lambda r: final_ranks[r["key"]])
    ]

    # --- full trajectory table (every item, all rounds, no truncation) ---
    columns = (
        [{"key": "item", "label": "Item"}]
        + [{"key": f"r{i + 1}", "label": f"R{i + 1}"} for i in range(n_rounds)]
        + [
            {"key": "delta", "label": "Net move"},
            {"key": "median", "label": "Final median"},
            {"key": "iqr", "label": "Final IQR"},
            {"key": "band", "label": "Agreement"},
        ]
    )
    rows: List[Dict[str, Any]] = []
    for key in ordered_keys:
        row: Dict[str, Any] = {"item": label_by_key.get(key, key)}
        ranks_seq: List[Optional[int]] = []
        for i in range(n_rounds):
            rk = per_round_ranks[i].get(key)
            row[f"r{i + 1}"] = rk
            ranks_seq.append(rk)
        present = [r for r in ranks_seq if r is not None]
        row["delta"] = (present[0] - present[-1]) if len(present) >= 2 else 0
        fr = final_by_key.get(key)
        row["median"] = fr["median"] if fr else None
        row["iqr"] = fr["iqr"] if fr else None
        row["band"] = fr["band"] if fr else None
        rows.append(row)

    # --- round-to-round rank stability (first vs final, common items) ---
    common = [k for k in first_ranks if k in final_ranks]
    stability = (
        spearman_rho([first_ranks[k] for k in common], [final_ranks[k] for k in common])
        if len(common) >= 2
        else None
    )

    final_bands = per_round_bands[-1]
    first_bands = per_round_bands[0]
    final_w = per_round_w[-1]

    sections: List[Dict[str, Any]] = []

    # narrative
    w_phrase = (
        f"inter-rater agreement (Kendall's W) moved from {per_round_w[0]} to {final_w}"
        if per_round_w[0] is not None and final_w is not None
        else "agreement was computed per round"
    )
    sections.append(
        {
            "id": "overview",
            "type": "narrative",
            "title": "Overview",
            "body": {
                "markdown": (
                    f"Over {n_rounds} round(s), the group evaluated "
                    f"{len(ordered_keys)} item(s). {w_phrase[0].upper()}{w_phrase[1:]}; "
                    f"items in the agreement zone (green) went from {first_bands['green']} "
                    f"to {final_bands['green']}."
                    + (
                        f" Round-to-round rank stability (Spearman) was {round(stability, 2)}."
                        if stability is not None
                        else ""
                    )
                ),
                "ai_drafted": False,
            },
        }
    )

    # summary key-value
    pairs = [
        {"label": "Rounds", "value": n_rounds},
        {"label": "Items", "value": len(ordered_keys)},
    ]
    if final_w is not None:
        pairs.append({"label": "Final Kendall's W", "value": final_w})
    if stability is not None:
        pairs.append({"label": "Rank stability (Spearman)", "value": round(stability, 2)})
    pairs.append({"label": "Consensus (green) items", "value": final_bands["green"]})
    sections.append(
        {"id": "summary", "type": "key_value", "title": "Run Summary", "body": {"pairs": pairs}}
    )

    # headline ranked list
    sections.append(
        {
            "id": "final_ranking",
            "type": "ranked_list",
            "title": "Final Ranking",
            "body": {"items": ranked_items},
        }
    )

    # full trajectory table
    sections.append(
        {
            "id": "trajectory",
            "type": "table",
            "title": "Item Trajectory (all items, all rounds)",
            "body": {"columns": columns, "rows": rows},
        }
    )

    # convergence chart (Kendall's W per round)
    if any(w is not None for w in per_round_w):
        sections.append(
            {
                "id": "convergence",
                "type": "chart",
                "title": "Convergence: Kendall's W by round",
                "body": {
                    "chart_kind": "line",
                    "x_axis": {"label": "Round", "categories": cats},
                    "y_axis": {"label": "Kendall's W"},
                    "series": [{"name": "Kendall's W", "points": list(per_round_w)}],
                },
            }
        )

    # agreement bands stacked bar
    sections.append(
        {
            "id": "bands",
            "type": "chart",
            "title": "Agreement bands by round",
            "body": {
                "chart_kind": "stacked_bar",
                "x_axis": {"label": "Round", "categories": cats},
                "y_axis": {"label": "Item count"},
                "series": [
                    {"name": b, "points": [per_round_bands[i][b] for i in range(n_rounds)]}
                    for b in ("green", "yellow", "red")
                ],
            },
        }
    )

    # rank-trajectory bump chart (top-N by final rank)
    top_keys = ordered_keys[: cfg["bump_top_n"]]
    sections.append(
        {
            "id": "rank_trajectory",
            "type": "chart",
            "title": "Rank trajectory (top items)",
            "body": {
                "chart_kind": "bump",
                "x_axis": {"label": "Round", "categories": cats},
                "y_axis": {"label": "Rank", "invert": True},
                "series": [
                    {
                        "name": label_by_key.get(k, k)[:40],
                        "stable_key": k,
                        "points": [per_round_ranks[i].get(k) for i in range(n_rounds)],
                    }
                    for k in top_keys
                ],
            },
        }
    )

    # per-round trace
    sections.append(
        {
            "id": "rounds",
            "type": "rounds",
            "title": "Round-by-round",
            "body": {
                "rounds": [
                    {
                        "round_number": i + 1,
                        "summary": f"Kendall's W {per_round_w[i]}; "
                        f"green {per_round_bands[i]['green']}, "
                        f"yellow {per_round_bands[i]['yellow']}, "
                        f"red {per_round_bands[i]['red']}",
                        "stats": {
                            "kendalls_w": per_round_w[i],
                            **per_round_bands[i],
                        },
                    }
                    for i in range(n_rounds)
                ]
            },
        }
    )

    method = meeting.get("method")
    return {
        "report_version": REPORT_VERSION,
        "title": meeting.get("title") or "Meeting Report",
        "meeting": {
            "meeting_id": meeting.get("meeting_id") or "",
            "title": meeting.get("title") or "",
            "description": meeting.get("description"),
            "method": method,
            "participant_count": meeting.get("participant_count"),
            "round_count": n_rounds,
        },
        "generated_at": meeting.get("generated_at")
        or datetime.now(timezone.utc).isoformat(),
        "generated_by": meeting.get("generated_by"),
        "sections": sections,
    }
