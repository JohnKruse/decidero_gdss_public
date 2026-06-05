"""Render an orchestration document's recursive structure as a diagram.

The orchestration document is an abstract syntax tree (sequence / iterate /
activity / decision steps). This module walks that AST and emits **Mermaid** and
**Graphviz DOT** so paper figures are generated directly from the real artifact
(e.g. `orchestrations/delphi.json`) and cannot drift from what the engine runs.

The nesting in the JSON is the recursion; the diagram makes it visible. Control
containers (sequence, iterate) become nested boxes / clusters; activities and
decisions become nodes; an iterate adds a dashed loop-back edge labelled with its
round bound, convergence predicate, and gate.

Public API:
- `to_mermaid(document) -> str`
- `to_graphviz(document) -> str`

`document` is an `OrchestrationDocument` (see `orchestration_loader`).
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from app.services.orchestration_loader import (
    ActivityStep,
    AIDecisionStep,
    ConditionalStep,
    FacilitatorDecisionStep,
    IterateStep,
    OrchestrationDocument,
    SequenceStep,
)


def _node_id(path: str) -> str:
    return "n" + (path.replace(".", "_") if path else "root")


def _cluster_id(path: str) -> str:
    return "c" + (path.replace(".", "_") if path else "root")


def _decision_annotations(report: Optional[dict], recommender: Optional[dict]) -> List[str]:
    """Short annotations for a facilitator-decision's report + recommender.

    Shared by the standalone facilitator-decision node and the iterate round-gate
    caption so the figure shows the report summarizer/audience and that a
    recommender rule supplies the suggestion (HICSS outline L.1–L.3).
    """
    parts: List[str] = []
    if report and report.get("summarizer"):
        parts.append(f"report: {report['summarizer']}→{report.get('audience', '?')}")
    if recommender and recommender.get("rule"):
        parts.append("recommends via rule")
    return parts


def _gate_summary(gate: dict) -> str:
    decision = (gate or {}).get("decision") or {}
    bits = ["facilitator decision"]
    bits.extend(_decision_annotations(decision.get("report"), decision.get("recommender")))
    return " / ".join(bits)


def _iterate_caption(step: IterateStep) -> str:
    bits: List[str] = []
    bits.append(f"≤{step.max_rounds} rounds")
    pred = (step.convergence_predicate or {}).get("name")
    if pred:
        bits.append(f"converge: {pred}")
    transform = (step.bundle_transform or {}).get("name")
    if transform and transform != "identity":
        bits.append(f"transform: {transform}")
    if step.round_gate:
        bits.append(f"gate: {_gate_summary(step.round_gate)}")
    return " · ".join(bits)


def _iterate_loop_label(step: IterateStep) -> str:
    if step.round_gate:
        return "continue · facilitator gate"
    pred = (step.convergence_predicate or {}).get("name") or "predicate"
    return f"repeat until {pred}"


def _mermaid_escape(text: str) -> str:
    # Mermaid quoted labels: drop double quotes, normalise whitespace.
    return " ".join(str(text).replace('"', "'").split())


def _dot_escape(text: str) -> str:
    return str(text).replace('"', "'")


def to_mermaid(document: OrchestrationDocument) -> str:
    """Emit a Mermaid `flowchart TD` for the document's structure."""
    body: List[str] = []
    edges: List[str] = []

    def emit(level: int, line: str) -> None:
        body.append("    " * level + line)

    def walk(step: Any, path: str, level: int) -> Tuple[str, str]:
        """Render a step subtree; return (first_leaf_id, last_leaf_id)."""
        if isinstance(step, ActivityStep):
            nid = _node_id(path)
            label = _mermaid_escape(step.title)
            tool = _mermaid_escape(step.tool_type)
            extra = "<br/>↩ feedback" if step.transform_input else ""
            emit(level, f'{nid}["{label}<br/><small>{tool}</small>{extra}"]')
            return nid, nid
        if isinstance(step, FacilitatorDecisionStep):
            nid = _node_id(path)
            extra = "".join(
                f"<br/><small>{_mermaid_escape(p)}</small>"
                for p in _decision_annotations(step.report, step.recommender)
            )
            emit(level, f'{nid}{{"{_mermaid_escape(step.prompt)}<br/><small>facilitator decision</small>{extra}"}}')
            return nid, nid
        if isinstance(step, AIDecisionStep):
            nid = _node_id(path)
            emit(level, f'{nid}{{"AI decision<br/><small>review_required={str(step.review_required).lower()}</small>"}}')
            return nid, nid
        if isinstance(step, ConditionalStep):
            nid = _node_id(path)
            emit(level, f'{nid}["conditional<br/><small>(reserved)</small>"]')
            return nid, nid
        if isinstance(step, (SequenceStep, IterateStep)):
            cid = _cluster_id(path)
            if isinstance(step, IterateStep):
                caption = f"Iterate · {_iterate_caption(step)}"
            else:
                caption = "Sequence" if level <= 1 else "Sequence (subcycle)"
            emit(level, f'subgraph {cid}["{caption}"]')
            emit(level + 1, "direction TB")
            first_id: Optional[str] = None
            prev_last: Optional[str] = None
            for index, child in enumerate(step.steps):
                child_path = f"{path}.{index}" if path else str(index)
                child_first, child_last = walk(child, child_path, level + 1)
                if first_id is None:
                    first_id = child_first
                if prev_last is not None:
                    edges.append(f"{prev_last} --> {child_first}")
                prev_last = child_last
            emit(level, "end")
            if isinstance(step, IterateStep) and first_id and prev_last:
                edges.append(f'{prev_last} -. "{_iterate_loop_label(step)}" .-> {first_id}')
            return first_id or cid, prev_last or cid
        # Unknown step kind: render a stub node.
        nid = _node_id(path)
        emit(level, f'{nid}["{_mermaid_escape(type(step).__name__)}"]')
        return nid, nid

    # The document's top-level steps form an implicit sequence.
    first_id: Optional[str] = None
    prev_last: Optional[str] = None
    for index, step in enumerate(document.steps):
        f, last = walk(step, str(index), 1)
        if first_id is None:
            first_id = f
        if prev_last is not None:
            edges.append(f"{prev_last} --> {f}")
        prev_last = last

    lines = ["flowchart TD"]
    lines.extend(body)
    if edges:
        lines.append("")
        lines.extend("    " + edge for edge in edges)
    return "\n".join(lines) + "\n"


def to_graphviz(document: OrchestrationDocument) -> str:
    """Emit a Graphviz DOT digraph for the document's structure."""
    body: List[str] = []
    edges: List[str] = []

    def emit(level: int, line: str) -> None:
        body.append("    " * level + line)

    def walk(step: Any, path: str, level: int) -> Tuple[str, str]:
        if isinstance(step, ActivityStep):
            nid = _node_id(path)
            extra = "\\n↩ feedback" if step.transform_input else ""
            label = f"{_dot_escape(step.title)}\\n({_dot_escape(step.tool_type)}){extra}"
            emit(level, f'"{nid}" [label="{label}"];')
            return nid, nid
        if isinstance(step, FacilitatorDecisionStep):
            nid = _node_id(path)
            extra = "".join(
                f"\\n{_dot_escape(p)}"
                for p in _decision_annotations(step.report, step.recommender)
            )
            emit(level, f'"{nid}" [shape=diamond, label="{_dot_escape(step.prompt)}\\n(facilitator decision){extra}"];')
            return nid, nid
        if isinstance(step, AIDecisionStep):
            nid = _node_id(path)
            emit(level, f'"{nid}" [shape=diamond, label="AI decision\\nreview_required={str(step.review_required).lower()}"];')
            return nid, nid
        if isinstance(step, ConditionalStep):
            nid = _node_id(path)
            emit(level, f'"{nid}" [style="rounded,dashed", label="conditional\\n(reserved)"];')
            return nid, nid
        if isinstance(step, (SequenceStep, IterateStep)):
            cid = _cluster_id(path)
            if isinstance(step, IterateStep):
                caption = f"iterate · {_iterate_caption(step)}"
                style = "dashed"
            else:
                caption = "sequence" if level <= 1 else "sequence (subcycle)"
                style = "rounded"
            emit(level, f"subgraph cluster_{cid} {{")
            emit(level + 1, f'label="{_dot_escape(caption)}"; style="{style}"; color="#888888";')
            first_id: Optional[str] = None
            prev_last: Optional[str] = None
            for index, child in enumerate(step.steps):
                child_path = f"{path}.{index}" if path else str(index)
                child_first, child_last = walk(child, child_path, level + 1)
                if first_id is None:
                    first_id = child_first
                if prev_last is not None:
                    edges.append(f'"{prev_last}" -> "{child_first}";')
                prev_last = child_last
            emit(level, "}")
            if isinstance(step, IterateStep) and first_id and prev_last:
                edges.append(
                    f'"{prev_last}" -> "{first_id}" '
                    f'[style=dashed, constraint=false, label="{_dot_escape(_iterate_loop_label(step))}"];'
                )
            return first_id or cid, prev_last or cid
        nid = _node_id(path)
        emit(level, f'"{nid}" [label="{_dot_escape(type(step).__name__)}"];')
        return nid, nid

    first_id: Optional[str] = None
    prev_last: Optional[str] = None
    for index, step in enumerate(document.steps):
        f, last = walk(step, str(index), 1)
        if first_id is None:
            first_id = f
        if prev_last is not None:
            edges.append(f'"{prev_last}" -> "{f}";')
        prev_last = last

    lines = [f'digraph "{_dot_escape(document.name)}" {{']
    lines.append('    rankdir=TB;')
    lines.append('    node [shape=box, style="rounded", fontname="Helvetica"];')
    lines.append('    edge [fontname="Helvetica", fontsize=10];')
    lines.extend(body)
    if edges:
        lines.append("")
        lines.extend("    " + edge for edge in edges)
    lines.append("}")
    return "\n".join(lines) + "\n"
