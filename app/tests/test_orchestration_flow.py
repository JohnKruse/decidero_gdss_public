"""Tests for the show-it-back flow renderer (Phase 9 Step 3, Plainspoken Marmot).

These assert that ``build_flow_tree`` walks the real orchestration document dict
into the nested node tree the template page renders, and that a tuned fork's flow
reflects the facilitator's choices (the dynamic path).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.orchestration_authoring import apply_tuning
from app.services.orchestration_flow import build_flow_tree

_DELPHI_PATH = Path(__file__).resolve().parents[2] / "orchestrations" / "delphi.json"


def _delphi_dict():
    return json.loads(_DELPHI_PATH.read_text(encoding="utf-8"))


def _find(node, predicate):
    """Depth-first search of the node tree (including gate nodes)."""
    if predicate(node):
        return node
    if node.get("gate"):
        hit = _find(node["gate"], predicate)
        if hit:
            return hit
    for child in node.get("children") or []:
        hit = _find(child, predicate)
        if hit:
            return hit
    return None


def test_build_flow_tree_renders_delphi_structure():
    tree = build_flow_tree(_delphi_dict())

    assert tree["kind"] == "method"
    # Top-level is a sequence: Round 1 activity -> iterate -> Final Report.
    iterate = _find(tree, lambda n: n.get("kind") == "iterate")
    assert iterate is not None
    # The loop carries its round cap and a plain-language stop condition.
    assert "Repeat up to" in iterate["label"]
    assert "stopping when" in iterate.get("detail", "")
    # The loop's facilitator round-gate surfaces as a decision node.
    assert iterate.get("gate") and iterate["gate"]["kind"] == "decision"

    # Both leaf activities and the terminal report are present.
    activities = []

    def _collect(node):
        if node.get("kind") == "activity":
            activities.append(node["label"])
        if node.get("gate"):
            _collect(node["gate"])
        for child in node.get("children") or []:
            _collect(child)

    _collect(tree)
    assert any("Rank" in label for label in activities)
    assert any("Report" in label for label in activities)


def test_build_flow_tree_reflects_tuning():
    tuned = apply_tuning(_delphi_dict(), max_rounds=7, who_decides="automatic")
    tree = build_flow_tree(tuned)

    iterate = _find(tree, lambda n: n.get("kind") == "iterate")
    assert iterate is not None
    # Tuned round cap shows in the label; "automatic" removed the round-gate.
    assert "7" in iterate["label"]
    assert iterate.get("gate") is None


def test_build_flow_tree_handles_empty_document():
    tree = build_flow_tree({"name": "Empty", "steps": []})
    assert tree == {"kind": "method", "label": "Empty", "children": []}
