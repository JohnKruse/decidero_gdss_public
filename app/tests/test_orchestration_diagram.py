"""Tests for the orchestration AST -> diagram exporter.

The figures are generated from the real document, so these assert that the
recursive structure (nested iterate/sequence + loop-back) is faithfully rendered.
"""

from __future__ import annotations

from pathlib import Path

from app.services.orchestration_diagram import to_graphviz, to_mermaid
from app.services.orchestration_loader import (
    load_orchestration_data,
    load_orchestration_path,
)

_DELPHI_PATH = Path(__file__).resolve().parents[2] / "orchestrations" / "delphi.json"


def test_mermaid_renders_delphi_nested_subcycle():
    document = load_orchestration_path(_DELPHI_PATH)
    mermaid = to_mermaid(document)

    assert mermaid.startswith("flowchart TD")
    # Top sequence, the iterate, and the nested round subcycle are all present.
    assert "Sequence" in mermaid
    assert "Iterate" in mermaid
    assert "iqr_stability" in mermaid
    assert "Sequence (subcycle)" in mermaid
    # Both leaf activities, in rank-first order. The comment step is the generic
    # brainstorming activity configured as a comment surface.
    assert "Rank Delphi Items" in mermaid
    assert "Comment on Disputed Ideas" in mermaid
    assert "rank_order_voting" in mermaid
    assert "brainstorming" in mermaid
    # The ranking carries the feedback annotation and is the loop-back target.
    assert "feedback" in mermaid
    assert ".-> n0_1_0_0" in mermaid  # dashed loop-back to the ranking step


def test_mermaid_gate_caption_shows_report_and_recommender():
    """Plainspoken Marmot: the iterate caption surfaces the embedded gate's
    report summarizer/audience and that a recommender rule drives the suggestion."""
    document = load_orchestration_path(_DELPHI_PATH)
    mermaid = to_mermaid(document)

    assert "gate: facilitator decision" in mermaid
    assert "report: delphi_round_agreement→facilitator" in mermaid
    assert "recommends via rule" in mermaid


def test_graphviz_renders_delphi_clusters_and_loopback():
    document = load_orchestration_path(_DELPHI_PATH)
    dot = to_graphviz(document)

    assert dot.startswith('digraph "Classical Delphi"')
    # Nested clusters: top sequence -> iterate -> subcycle sequence.
    assert dot.count("subgraph cluster_") >= 3
    assert "iterate ·" in dot
    assert "sequence (subcycle)" in dot
    # Loop-back edge returns to the ranking node from the subcycle's last step
    # (now [rank, in-round decision, justify]).
    assert '"n0_1_0_2" -> "n0_1_0_0"' in dot
    assert "style=dashed" in dot


def test_mermaid_handles_flat_iterate_without_nested_sequence():
    document = load_orchestration_data({
        "name": "flat", "version": "1", "author": "t", "citation": "c",
        "metadata": {
            "thinklets": ["t"], "collaboration_patterns": ["p"], "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 60},
        },
        "steps": [{
            "type": "iterate", "max_rounds": 3,
            "convergence_predicate": {"name": "fixed_n", "config": {"max_rounds": 3}},
            "bundle_transform": {"name": "identity", "config": {}},
            "steps": [{"type": "activity", "tool_type": "brainstorming", "title": "Round"}],
        }],
    })
    mermaid = to_mermaid(document)
    assert "Iterate" in mermaid
    assert "fixed_n" in mermaid
    assert "Round" in mermaid
    # Single-activity iterate body loops back onto itself.
    assert "n0_0 -. " in mermaid
