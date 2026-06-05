"""Plainspoken Marmot: facilitator-shaped authoring of orchestration methods.

Phase 9 Step 1 (fork-and-tune). This module is the compile layer between plain,
meeting-language tuning choices and a valid Layer-2 orchestration document. It
never exposes JSON to the facilitator: callers pass simple values (round limit,
stop condition, who decides each round) and receive a validated orchestration
document plus a plain-language summary for confirmation.

It does not touch activities (Layer 1) or invent a new document format — the
output is an ordinary orchestration document validated against
``docs/schemas/orchestration.schema.json`` via the existing loader.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


def _iterate_steps(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return every iterate step dict in document order (depth-first)."""
    found: List[Dict[str, Any]] = []

    def _walk(steps: Any) -> None:
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("type") == "iterate":
                found.append(step)
            _walk(step.get("steps"))

    _walk(document.get("steps"))
    return found


def _activity_steps(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return every activity step dict in document order (depth-first)."""
    found: List[Dict[str, Any]] = []

    def _walk(steps: Any) -> None:
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("type") == "activity":
                found.append(step)
            _walk(step.get("steps"))

    _walk(document.get("steps"))
    return found


# Plain-language stop conditions mapped to convergence predicates. The facilitator
# picks an outcome; the predicate is wired under the hood.
STOP_CONDITIONS = {
    "responses_stabilize": {
        "predicate": "iqr_stability",
        "phrase": "the group's responses stop changing much",
    },
    "fixed_rounds": {
        "predicate": "fixed_n",
        "phrase": "a fixed number of rounds have run",
    },
}


def apply_tuning(
    base_document: Dict[str, Any],
    *,
    max_rounds: Optional[int] = None,
    convergence_threshold: Optional[float] = None,
    who_decides: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a new orchestration document with plain tuning applied and validated.

    - ``max_rounds``: the hard round cap on each iterate loop.
    - ``convergence_threshold``: stability threshold for the stop condition.
    - ``who_decides``: ``"facilitator"`` adds a continue/conclude round-gate;
      ``"automatic"`` removes it so the predicate decides.

    Raises ``OrchestrationValidationError`` (via the loader) if the result is not a
    valid orchestration document.
    """
    from app.services.orchestration_loader import load_orchestration_data

    document = copy.deepcopy(base_document)
    iterates = _iterate_steps(document)
    if (max_rounds is not None or convergence_threshold is not None or who_decides is not None) and not iterates:
        raise ValueError("This method has no iterative loop to tune.")

    for iterate in iterates:
        if max_rounds is not None:
            mr = int(max_rounds)
            if mr < 1:
                raise ValueError("Round limit must be at least 1.")
            iterate["max_rounds"] = mr
        if convergence_threshold is not None:
            predicate = iterate.setdefault("convergence_predicate", {})
            config = predicate.setdefault("config", {})
            config["threshold"] = float(convergence_threshold)
        if who_decides is not None:
            if who_decides == "facilitator":
                iterate["round_gate"] = {
                    "decision": {
                        "prompt": "Run another round, or conclude the method?",
                        "options": ["continue", "conclude"],
                        "recommender": {
                            "metrics": [],
                            "rule": [
                                {"when": "converged", "recommend": "conclude"},
                                {"default": "continue"},
                            ],
                        },
                    }
                }
            elif who_decides == "automatic":
                iterate.pop("round_gate", None)
            else:
                raise ValueError("who_decides must be 'facilitator' or 'automatic'.")

    # Validate by loading; raises on an invalid result so callers never persist
    # a broken document.
    load_orchestration_data(document)
    return document


def _stop_condition_phrase(iterate: Dict[str, Any]) -> str:
    name = str((iterate.get("convergence_predicate") or {}).get("name") or "")
    for spec in STOP_CONDITIONS.values():
        if spec["predicate"] == name:
            return spec["phrase"]
    return "the method's stop condition is met"


def summarize_orchestration(document: Dict[str, Any]) -> List[str]:
    """Return plain-language lines describing what the method will do.

    Used as the show-it-back confirmation surface so a facilitator can sanity-check
    a tuned method without reading JSON.
    """
    lines: List[str] = []
    activities = _activity_steps(document)
    iterates = _iterate_steps(document)

    if activities:
        first = activities[0]
        lines.append(f"Start with: {first.get('title') or first.get('tool_type') or 'an activity'}.")

    for iterate in iterates:
        inner = _activity_steps(iterate)
        inner_title = (inner[0].get("title") or inner[0].get("tool_type")) if inner else "the round activity"
        max_rounds = iterate.get("max_rounds")
        cap = f"up to {max_rounds} times" if max_rounds else "repeatedly"
        lines.append(
            f"Then repeat {inner_title} {cap}, stopping when {_stop_condition_phrase(iterate)}."
        )
        gate = iterate.get("round_gate")
        if isinstance(gate, dict) and isinstance(gate.get("decision"), dict):
            lines.append("After each round you decide whether to run another round or conclude.")
        else:
            lines.append("Rounds continue automatically until the stop condition or the round limit.")

    if not lines:
        lines.append("This method runs its activities in order.")
    return lines
