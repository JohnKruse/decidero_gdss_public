"""Tests for report consensus metrics (Plainspoken Marmot)."""

from app.services.report_metrics import (
    agreement_band,
    kendalls_w,
    kendalls_w_from_ratings,
    spearman_rho,
)
from app.services.report_summarizers import get_report_summarizer_registry


def test_kendalls_w_perfect_agreement_is_one():
    # 3 judges, identical ranking of 4 items -> W = 1.0
    m = [[1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4]]
    assert kendalls_w(m) == 1.0


def test_kendalls_w_opposed_rankings_is_zero():
    # Two exactly opposed rankings cancel -> W = 0.0
    assert kendalls_w([[1, 2, 3, 4], [4, 3, 2, 1]]) == 0.0


def test_kendalls_w_partial_agreement_between_zero_and_one():
    w = kendalls_w([[1, 2, 3, 4], [1, 2, 4, 3], [2, 1, 3, 4]])
    assert w is not None
    assert 0.0 < w < 1.0


def test_kendalls_w_undefined_cases_return_none():
    assert kendalls_w([[1, 2, 3]]) is None          # < 2 judges
    assert kendalls_w([[1], [1]]) is None            # < 2 items
    assert kendalls_w([[1, 1], [1, 1]]) is None      # degenerate all-tie


def test_kendalls_w_from_ratings_handles_ties():
    # Saturated ratings (all top) are a degenerate all-tie -> None
    assert kendalls_w_from_ratings([[9, 9, 9], [9, 9, 9]]) is None
    # Clear, consistent rating order -> high W
    w = kendalls_w_from_ratings([[9, 5, 1], [8, 4, 2], [9, 6, 3]])
    assert w is not None and w > 0.9


def test_spearman_rho_perfect_and_reversed():
    assert spearman_rho([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0
    assert spearman_rho([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert spearman_rho([1], [1]) is None


def test_agreement_band_thresholds():
    assert agreement_band(0.0) == "green"
    assert agreement_band(1.0) == "green"
    assert agreement_band(1.5) == "yellow"
    assert agreement_band(2.0) == "yellow"
    assert agreement_band(2.5) == "red"


def test_kendalls_w_summarizer_reads_votes_bundle():
    # Two judges, perfectly agreeing on 3 options -> W = 1.0 via the registry.
    votes = []
    for uid in ("u1", "u2"):
        for opt, pos in (("a", 1), ("b", 2), ("c", 3)):
            votes.append({"user_id": uid, "option_id": opt, "rank_position": pos})
    bundle = {"items": [], "metadata": {"votes": votes}}
    summ = get_report_summarizer_registry().get_summarizer("kendalls_w")
    out = summ.summarize(bundle, {})
    assert out["kendalls_w"] == 1.0
    assert out["judge_count"] == 2
    assert out["item_count"] == 3
