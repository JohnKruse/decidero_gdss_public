"""Tests for the report summarizer registry and delphi_round_agreement."""

from __future__ import annotations

from app.services.report_summarizers import (
    ReportSummarizer,
    get_report_summarizer_registry,
)


def _ranking_bundle():
    """A two-item ranking bundle with three participants (mirrors test_round_statistics)."""
    items = [
        {"content": "A", "metadata": {"rank_order_voting": {"option_id": "o1"}}},
        {"content": "B", "metadata": {"rank_order_voting": {"option_id": "o2"}}},
    ]
    votes = [
        {"user_id": "u1", "option_id": "o1", "rank_position": 1},
        {"user_id": "u2", "option_id": "o1", "rank_position": 1},
        {"user_id": "u3", "option_id": "o1", "rank_position": 2},
        {"user_id": "u1", "option_id": "o2", "rank_position": 2},
        {"user_id": "u2", "option_id": "o2", "rank_position": 2},
        {"user_id": "u3", "option_id": "o2", "rank_position": 1},
    ]
    return {"items": items, "metadata": {"source": "rank_order_voting", "votes": votes}}


def test_registry_resolves_delphi_round_agreement():
    summarizer = get_report_summarizer_registry().get_summarizer("delphi_round_agreement")
    assert isinstance(summarizer, ReportSummarizer)
    assert "delphi_round_agreement" in get_report_summarizer_registry().list_summarizers()


def test_registry_lookup_is_case_insensitive_and_misses_cleanly():
    registry = get_report_summarizer_registry()
    assert registry.get_summarizer("  Delphi_Round_Agreement ") is not None
    assert registry.get_summarizer("nonexistent") is None


def test_delphi_round_agreement_emits_scalar_namespace():
    summarizer = get_report_summarizer_registry().get_summarizer("delphi_round_agreement")
    summary = summarizer.summarize(_ranking_bundle(), {})

    # Flat scalar namespace contract (Layer-A): all keys present, all scalar.
    expected_keys = {
        "item_count",
        "participant_count",
        "median_iqr",
        "strong_agreement_items",
        "contested_items",
        "outlier_instances",
        "participants_with_outliers",
        "agreement_label",
    }
    assert expected_keys == set(summary)
    assert summary["item_count"] == 2
    assert summary["participant_count"] == 3
    assert isinstance(summary["median_iqr"], float)
    assert summary["strong_agreement_items"] + summary["contested_items"] <= 2


def test_empty_bundle_reports_no_items():
    summarizer = get_report_summarizer_registry().get_summarizer("delphi_round_agreement")
    summary = summarizer.summarize({"items": [], "metadata": {}}, {})
    assert summary["item_count"] == 0
    assert summary["participant_count"] == 0
    assert summary["agreement_label"] == "No items"


def test_config_thresholds_shift_agreement_label():
    summarizer = get_report_summarizer_registry().get_summarizer("delphi_round_agreement")
    bundle = _ranking_bundle()
    # A contested_iqr of 0 forces any non-zero-IQR round out of strong/moderate.
    strict = summarizer.summarize(bundle, {"strong_iqr": 0.0, "contested_iqr": 0.0})
    assert strict["agreement_label"] in {
        "Strong agreement",
        "Divergent — several items contested",
        "No items",
    }
