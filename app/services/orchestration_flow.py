"""Plainspoken Marmot: a read-only "show-it-back" flow of an orchestration method.

Phase 9 Step 3. This is the visual-flow companion to ``summarize_orchestration``
(the plain-language summary). It walks an orchestration **document dict** — the
same dict shape the authoring helpers in ``orchestration_authoring`` already walk —
into a JSON-serializable node tree that the template page renders as nested,
plain-language boxes (phases, loops, decision points). The facilitator confirms a
method (including a just-created fork) without ever reading JSON.

Presentation stays in the template/CSS; this module emits structure only, so it
works on the inline tuned fork document with no loading/validation (the document is
already validated at fork/save time).

Public API:
- ``build_flow_tree(document: dict) -> dict``
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.orchestration_authoring import (
    _custom_stop_text_from_ai_decision,
    _stop_condition_phrase,
)


def _activity_label(step: Dict[str, Any]) -> Dict[str, Any]:
    title = step.get("title")
    tool = step.get("tool_type")
    label = title or tool or "Activity"
    detail = tool if (title and tool and tool != title) else None
    node: Dict[str, Any] = {"kind": "activity", "label": label, "children": []}
    if detail:
        node["detail"] = detail
    if step.get("transform_input"):
        node["detail"] = (node.get("detail") + " · " if node.get("detail") else "") + "uses prior-round feedback"
    return node


def _decision_detail(report: Any, recommender: Any) -> Optional[str]:
    """Plain-language note for a decision's report + recommender (mirrors the
    diagram's ``_decision_annotations`` but phrased for facilitators)."""
    parts: List[str] = []
    if isinstance(report, dict) and report.get("summarizer"):
        audience = report.get("audience") or "the facilitator"
        parts.append(f"shows {audience} a summary first")
    if isinstance(recommender, dict) and recommender.get("rule"):
        parts.append("suggests a choice")
    return "; ".join(parts) or None


def _facilitator_decision_node(step: Dict[str, Any]) -> Dict[str, Any]:
    node: Dict[str, Any] = {
        "kind": "decision",
        "label": step.get("prompt") or "Facilitator decides",
        "children": [],
    }
    detail = _decision_detail(step.get("report"), step.get("recommender"))
    if detail:
        node["detail"] = detail
    return node


def _ai_decision_node(step: Dict[str, Any]) -> Dict[str, Any]:
    node: Dict[str, Any] = {"kind": "decision", "label": "AI suggestion", "children": []}
    custom = _custom_stop_text_from_ai_decision(step)
    if custom:
        node["detail"] = f'evaluates: "{custom}"'
    return node


def _iterate_node(step: Dict[str, Any]) -> Dict[str, Any]:
    max_rounds = step.get("max_rounds")
    cap = f"Repeat up to {max_rounds} times" if max_rounds else "Repeat"
    node: Dict[str, Any] = {
        "kind": "iterate",
        "label": cap,
        "detail": f"stopping when {_stop_condition_phrase(step)}",
        "children": [_build_node(child) for child in step.get("steps") or [] if isinstance(child, dict)],
    }
    gate = step.get("round_gate")
    if isinstance(gate, dict) and isinstance(gate.get("decision"), dict):
        decision = gate["decision"]
        gate_node: Dict[str, Any] = {
            "kind": "decision",
            "label": decision.get("prompt") or "After each round: continue or conclude?",
            "children": [],
        }
        detail = _decision_detail(decision.get("report"), decision.get("recommender"))
        node["gate"] = gate_node | ({"detail": detail} if detail else {})
    return node


def _sequence_node(step: Dict[str, Any], *, top_level: bool = False) -> Dict[str, Any]:
    return {
        "kind": "sequence",
        "label": "In order" if top_level else "Sub-steps",
        "children": [_build_node(child) for child in step.get("steps") or [] if isinstance(child, dict)],
    }


def _build_node(step: Dict[str, Any]) -> Dict[str, Any]:
    kind = step.get("type")
    if kind == "activity":
        return _activity_label(step)
    if kind == "iterate":
        return _iterate_node(step)
    if kind == "sequence":
        return _sequence_node(step)
    if kind == "facilitator-decision":
        return _facilitator_decision_node(step)
    if kind == "ai-decision":
        return _ai_decision_node(step)
    if kind == "conditional":
        return {"kind": "conditional", "label": "Conditional (reserved)", "children": []}
    return {"kind": "step", "label": str(kind or "step"), "children": []}


def build_flow_tree(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return a JSON-serializable node tree describing the method's flow.

    The root carries the method name; its ``children`` are the document's
    top-level steps rendered as nested ``{kind, label, detail?, children}`` nodes.
    An ``iterate`` node additionally carries a ``gate`` decision node when the loop
    has a facilitator round-gate.
    """
    steps = document.get("steps")
    children = [_build_node(step) for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []
    return {
        "kind": "method",
        "label": document.get("name") or "Method",
        "children": children,
    }
