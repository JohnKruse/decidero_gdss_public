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
        "label": "Whether people's rankings have stopped changing",
        "common": True,
    },
    "agreement": {
        "predicate": "iqr_stability",
        "phrase": "most people now agree",
        "label": "Whether most people now agree",
        "common": True,
    },
    "fixed_rounds": {
        "predicate": "fixed_n",
        "phrase": "a fixed number of rounds have run",
        "label": "A fixed number of rounds",
        "common": False,
    },
    "custom": {
        "predicate": "iqr_stability",
        "phrase": "the facilitator's custom criteria are met",
        "label": "Describe it in your own words",
        "common": False,
    },
}

# Reverse map: convergence predicate name → stop condition key (best match).
_PREDICATE_TO_STOP_CONDITION: Dict[str, str] = {
    "iqr_stability": "responses_stabilize",
    "fixed_n": "fixed_rounds",
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


def compile_control_point_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Compile a plain-language control-point card to a validated iterate step.

    The card payload keys mirror ``ControlPointCardRequest``:

    - ``activity_tool_type`` (str, required)
    - ``activity_title`` (str, optional)
    - ``who_decides`` ("facilitator" | "assisted" | "auto")
    - ``stop_condition`` ("responses_stabilize" | "agreement" | "fixed_rounds" | "custom")
    - ``stop_condition_text`` (str, for custom)
    - ``max_rounds`` (int >= 1)
    - ``threshold`` (float, optional)

    Returns a dict representing the iterate step, suitable for embedding in an
    orchestration document's ``steps`` list.

    Raises ``ValueError`` on invalid input.
    """
    tool_type = (card.get("activity_tool_type") or "").strip()
    if not tool_type:
        raise ValueError("Choose an activity for the repeated round.")

    max_rounds = card.get("max_rounds")
    if not isinstance(max_rounds, int) or max_rounds < 1:
        raise ValueError("A round limit of at least 1 is required.")

    who_decides = card.get("who_decides", "facilitator")
    if who_decides not in ("facilitator", "assisted", "auto"):
        raise ValueError(f"Invalid who_decides value: {who_decides!r}")

    stop_key = card.get("stop_condition", "responses_stabilize")
    stop_spec = STOP_CONDITIONS.get(stop_key)
    if stop_spec is None:
        raise ValueError(f"Unknown stop condition: {stop_key!r}")

    threshold = card.get("threshold")

    # --- Build the convergence predicate ---
    predicate_config: Dict[str, Any] = {}
    if threshold is not None:
        predicate_config["threshold"] = float(threshold)
    if stop_key == "fixed_rounds":
        predicate_config["max_rounds"] = max_rounds

    convergence_predicate = {
        "name": stop_spec["predicate"],
        "config": predicate_config,
    }

    # --- Build the activity step ---
    activity_title = (card.get("activity_title") or "").strip()
    activity_step: Dict[str, Any] = {
        "type": "activity",
        "tool_type": tool_type,
        "title": activity_title or tool_type.replace("_", " ").title(),
    }

    # --- Build the round gate (if not auto) ---
    round_gate: Optional[Dict[str, Any]] = None
    if who_decides in ("facilitator", "assisted"):
        decision_body: Dict[str, Any] = {
            "prompt": "Run another round, or conclude the method?",
            "options": ["continue", "conclude"],
        }
        if who_decides == "assisted":
            # Wire the recommender from the stop condition predicate.
            decision_body["recommender"] = {
                "metrics": [],
                "rule": [
                    {"when": "converged", "recommend": "conclude"},
                    {"default": "continue"},
                ],
            }
        round_gate = {"decision": decision_body}

    # --- Preserve custom stop-condition text as a note ---
    custom_text = (card.get("stop_condition_text") or "").strip()

    # --- Assemble the iterate step ---
    iterate: Dict[str, Any] = {
        "type": "iterate",
        "max_rounds": max_rounds,
        "convergence_predicate": convergence_predicate,
        "bundle_transform": {
            "name": "delphi_statistical_aggregation",
            "config": {},
        },
        "steps": [
            {
                "type": "sequence",
                "steps": [activity_step],
            }
        ],
    }
    if round_gate is not None:
        iterate["round_gate"] = round_gate
    if custom_text:
        iterate["_custom_stop_description"] = custom_text

    return iterate


def decompile_control_point_card(iterate_step: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse-engineer a card payload from an existing iterate step.

    Used to populate the control-point card form when editing an existing
    orchestration method. Returns a dict whose keys match
    ``ControlPointCardDecompileResponse``.
    """
    max_rounds = iterate_step.get("max_rounds", 4)

    # --- Determine who_decides ---
    gate = iterate_step.get("round_gate")
    if gate is None:
        who_decides = "auto"
    elif isinstance(gate, dict):
        decision = gate.get("decision") or {}
        if isinstance(decision, dict) and decision.get("recommender"):
            who_decides = "assisted"
        else:
            who_decides = "facilitator"
    else:
        who_decides = "facilitator"

    # --- Determine stop condition ---
    pred = iterate_step.get("convergence_predicate") or {}
    pred_name = (pred.get("name") or "").strip().lower()
    pred_config = pred.get("config") or {}

    stop_condition = _PREDICATE_TO_STOP_CONDITION.get(pred_name, "responses_stabilize")

    # If a custom description was stored, treat it as custom.
    custom_text = (iterate_step.get("_custom_stop_description") or "").strip()
    if custom_text:
        stop_condition = "custom"

    threshold = pred_config.get("threshold")

    # --- Extract activity ---
    activity_tool_type: Optional[str] = None
    activity_title: Optional[str] = None
    steps = iterate_step.get("steps") or []
    for step in steps:
        if isinstance(step, dict):
            if step.get("type") == "activity":
                activity_tool_type = step.get("tool_type")
                activity_title = step.get("title")
                break
            # Walk into sequences.
            inner = step.get("steps") or []
            for inner_step in inner:
                if isinstance(inner_step, dict) and inner_step.get("type") == "activity":
                    activity_tool_type = inner_step.get("tool_type")
                    activity_title = inner_step.get("title")
                    break
            if activity_tool_type:
                break

    return {
        "activity_tool_type": activity_tool_type,
        "activity_title": activity_title,
        "who_decides": who_decides,
        "stop_condition": stop_condition,
        "stop_condition_text": custom_text or None,
        "max_rounds": max_rounds,
        "threshold": threshold,
    }


def summarize_control_point(iterate_step: Dict[str, Any]) -> List[str]:
    """Plain-language summary of a single compiled control-point iterate step."""
    card = decompile_control_point_card(iterate_step)
    lines: List[str] = []

    activity = card.get("activity_title") or (
        (card.get("activity_tool_type") or "the activity").replace("_", " ").title()
    )
    max_rounds = card.get("max_rounds", 4)
    lines.append(f"Repeat {activity} up to {max_rounds} times.")

    stop_key = card.get("stop_condition", "responses_stabilize")
    stop_spec = STOP_CONDITIONS.get(stop_key)
    if stop_spec:
        lines.append(f"Stop when {stop_spec['phrase']}.")

    who = card.get("who_decides", "facilitator")
    if who == "facilitator":
        lines.append("You decide each round whether to continue or conclude.")
    elif who == "assisted":
        lines.append("You decide each round, with a suggestion based on the stop condition.")
    elif who == "auto":
        lines.append("Rounds continue automatically until the stop condition or the round limit.")

    custom = card.get("stop_condition_text")
    if custom:
        lines.append(f'Custom criteria: "{custom}"')

    return lines
