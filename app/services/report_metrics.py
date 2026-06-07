"""Report statistics: cited consensus metrics for the terminal report.

Canary: Plainspoken Marmot

Layer-A metrics (HICSS outline §L.3 / §N): cited, config-parameterized statistical
primitives. These are the *report's* consensus measures, the dual of the in-round
convergence predicates. They are pure functions over plain data — no DB, no bundle
plumbing — so the report builder and the summarizer registry can both call them.

Paradigm note (sanity-test finding, 2026-06-07): consensus statistics must match
the input paradigm. For **rank-order** data (Decidero's Delphi), Kendall's W and
median/IQR over rank positions are the right measures. For **rating** data
(Likert), median/IQR and percent-agreement are clearer and Kendall's W (which needs
rankings) understates consensus on saturated scales. `agreement_band` and the
median/IQR helpers are paradigm-agnostic; `kendalls_w` is ranking-specific.

Citations:
- Kendall, M. G., and Babington Smith, B. "The Problem of m Rankings."
  The Annals of Mathematical Statistics 10(3), 1939, 275-287.
- Spearman, C. "The Proof and Measurement of Association between Two Things."
  The American Journal of Psychology 15(1), 1904, 72-101.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

KENDALLS_W_CITATION = (
    "Kendall, M. G., & Babington Smith, B. (1939). The Problem of m Rankings. "
    "The Annals of Mathematical Statistics, 10(3), 275-287."
)
SPEARMAN_CITATION = (
    "Spearman, C. (1904). The Proof and Measurement of Association between Two "
    "Things. The American Journal of Psychology, 15(1), 72-101."
)

# Default IQR (rank-position) cutoffs for agreement bands; mirror the Delphi
# feedback policy's agreement_bands defaults (green_max / yellow_max).
DEFAULT_GREEN_MAX_IQR = 1.0
DEFAULT_YELLOW_MAX_IQR = 2.0


def agreement_band(
    iqr: float,
    green_max: float = DEFAULT_GREEN_MAX_IQR,
    yellow_max: float = DEFAULT_YELLOW_MAX_IQR,
) -> str:
    """Classify an item's spread into a green/yellow/red agreement band.

    Lower IQR (rank positions) = tighter agreement. Paradigm-agnostic: works for
    rank-position IQR or rating IQR, with appropriate cutoffs.
    """
    if iqr <= green_max:
        return "green"
    if iqr <= yellow_max:
        return "yellow"
    return "red"


def _average_ranks(values: Sequence[float]) -> List[float]:
    """Rank `values` high-to-low (largest value = rank 1), averaging ties.

    Returns a rank per input position. Used to turn one judge's ratings into a
    ranking when computing Kendall's W over rating data.
    """
    n = len(values)
    order = sorted(range(n), key=lambda k: -values[k])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # ranks are 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _tie_correction(ranks: Sequence[float]) -> float:
    """Sum of (t^3 - t) over tie groups in one judge's rank vector."""
    counts: Dict[float, int] = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    return float(sum(t ** 3 - t for t in counts.values() if t > 1))


def kendalls_w(rank_matrix: Sequence[Sequence[float]]) -> Optional[float]:
    """Kendall's coefficient of concordance W over a complete block of rankings.

    `rank_matrix`: judges x items, each row a judge's *ranking* of the items
    (1 = best). With ties, the tie-corrected formula is used. Returns a value in
    [0, 1] (0 = no agreement, 1 = perfect), or None when undefined (< 2 judges,
    < 2 items, or a degenerate all-tie matrix).
    """
    m = len(rank_matrix)
    if m < 2:
        return None
    n = len(rank_matrix[0])
    if n < 2 or any(len(row) != n for row in rank_matrix):
        return None

    column_sums = [sum(rank_matrix[j][i] for j in range(m)) for i in range(n)]
    mean_rank = sum(column_sums) / n
    s = sum((rsum - mean_rank) ** 2 for rsum in column_sums)
    tie_total = sum(_tie_correction(row) for row in rank_matrix)

    denom = (m ** 2) * (n ** 3 - n) - m * tie_total
    if denom <= 0:
        return None
    return 12.0 * s / denom


def kendalls_w_from_ratings(rating_matrix: Sequence[Sequence[float]]) -> Optional[float]:
    """Kendall's W where each judge supplied *ratings* (not a ranking).

    Converts each judge's ratings to a within-judge ranking (ties averaged), then
    applies `kendalls_w`. Useful for rating-paradigm data, with the caveat that
    saturated scales (many tied top scores) compress W downward.
    """
    if len(rating_matrix) < 2:
        return None
    return kendalls_w([_average_ranks(row) for row in rating_matrix])


def spearman_rho(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation between two equal-length rank vectors.

    Used as the round-to-round rank-stability metric: how little the group's order
    churned between consecutive rounds. Assumes `a`/`b` are already ranks (no ties
    handling beyond the standard d^2 form). Returns None if undefined.
    """
    n = len(a)
    if n < 2 or len(b) != n:
        return None
    d2 = sum((a[i] - b[i]) ** 2 for i in range(n))
    return 1.0 - (6.0 * d2) / (n * (n ** 2 - 1))
