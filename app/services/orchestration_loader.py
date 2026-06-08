"""Orchestration document loader and validator.

Canary: Insolent Metronome

This module loads, validates, and parses process orchestration JSON documents
into typed AST representations consumed by the orchestration engine.

The authoritative grammar is declared in
`docs/schemas/orchestration.schema.json`; this loader is the exclusive runtime
entry point for orchestration documents and is the source of truth where it
diverges from the JSON Schema file.

Coexistence: orchestration documents and meeting-designer agendas are
distinct grammars. The meeting-designer agenda validator lives in
`app/services/agenda_validator.py`; this loader handles only process
orchestration documents. The two do not overlap.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional

from app.services.activity_catalog import get_enriched_activity_catalog


class OrchestrationValidationError(ValueError):
    """Raised when an orchestration document fails validation."""

    def __init__(self, result: OrchestrationValidationResult):
        self.result = result
        super().__init__(f"Orchestration validation failed: {[e.message for e in result.errors]}")


@dataclass
class OrchestrationFieldError:
    """Represents a single validation error for a field."""

    field: str
    message: str


@dataclass
class OrchestrationValidationResult:
    """The result of validating an orchestration document."""

    valid: bool
    errors: List[OrchestrationFieldError]
    warnings: List[OrchestrationFieldError]


# AST Class Definitions

@dataclass(frozen=True)
class OrchestrationMetadata:
    thinklets: List[str]
    collaboration_patterns: List[str]
    deliverables: List[str]
    group_size_range: Dict[str, int]
    typical_duration_minutes: Dict[str, int]
    notes: Optional[str] = None


class OrchestrationStep:
    pass


@dataclass
class SequenceStep(OrchestrationStep):
    steps: List[OrchestrationStep]
    type: Literal["sequence"] = "sequence"


@dataclass
class IterateStep(OrchestrationStep):
    steps: List[OrchestrationStep]
    max_rounds: int
    convergence_predicate: Dict[str, Any]
    bundle_transform: Dict[str, Any]
    # Deliberate Heron: optional facilitator round-gate. When present the engine
    # pauses at each round boundary (below the cap) for a continue/conclude
    # decision instead of auto-deciding. `recommendation` is an enumerated seam:
    # "convergence" (predicate verdict, implemented) or "ai" (reserved).
    round_gate: Optional[Dict[str, Any]] = None
    type: Literal["iterate"] = "iterate"


@dataclass
class ConditionalStep(OrchestrationStep):
    type: Literal["conditional"] = "conditional"


@dataclass
class ActivityStep(OrchestrationStep):
    tool_type: str
    title: str
    config: Dict[str, Any]
    transform_input: Optional[str] = None
    type: Literal["activity"] = "activity"


@dataclass
class FacilitatorDecisionStep(OrchestrationStep):
    prompt: str
    options: List[str]
    context_bundle_keys: List[str]
    # Plainspoken Marmot: optional report (a named summarizer + audience rendered
    # to inform the choice) and recommender (Layer-A metric refs + a Layer-B
    # declarative rule that resolves a recommended option). Kept as raw dicts,
    # matching the convergence_predicate / bundle_transform registry-spec style.
    report: Optional[Dict[str, Any]] = None
    recommender: Optional[Dict[str, Any]] = None
    type: Literal["facilitator-decision"] = "facilitator-decision"


@dataclass
class AIDecisionStep(OrchestrationStep):
    prompt_template: str
    output_schema: Dict[str, Any]
    review_required: bool
    context_bundle_keys: List[str]
    type: Literal["ai-decision"] = "ai-decision"


@dataclass(frozen=True)
class OrchestrationDocument:
    name: str
    version: str
    author: str
    citation: str
    metadata: OrchestrationMetadata
    steps: List[OrchestrationStep]


def _validate_report(report: Any, path: str, errors: List[OrchestrationFieldError]) -> None:
    """Plainspoken Marmot: validate a report sub-object (summarizer + audience)."""
    if not isinstance(report, dict):
        errors.append(OrchestrationFieldError(field=path, message=f"'{path}' must be a dictionary."))
        return
    summ = report.get("summarizer")
    if not isinstance(summ, str) or not summ.strip():
        errors.append(OrchestrationFieldError(field=f"{path}.summarizer", message=f"'{path}.summarizer' must be a non-empty string."))
    if "config" in report and not isinstance(report["config"], dict):
        errors.append(OrchestrationFieldError(field=f"{path}.config", message=f"'{path}.config' must be a dictionary."))
    if report.get("audience") not in ("facilitator", "participants"):
        errors.append(OrchestrationFieldError(field=f"{path}.audience", message=f"'{path}.audience' must be 'facilitator' or 'participants'."))


def _validate_recommender(rec: Any, path: str, errors: List[OrchestrationFieldError]) -> None:
    """Plainspoken Marmot: validate a recommender sub-object.

    Layer-A `metrics` are registry name references; the Layer-B `rule` is an
    ordered list of guards. Each `when` condition is checked for safe syntax at
    load time (the namespace is unknown until runtime), so an unsafe rule is
    rejected on save rather than at the round boundary.
    """
    from app.services.recommenders import RecommenderRuleError, validate_condition_syntax

    if not isinstance(rec, dict):
        errors.append(OrchestrationFieldError(field=path, message=f"'{path}' must be a dictionary."))
        return
    if "source" in rec:
        source = rec["source"]
        if source not in ("rule", "ai"):
            errors.append(OrchestrationFieldError(
                field=f"{path}.source",
                message=f"'{path}.source' must be 'rule' or 'ai'.",
            ))
    if "metrics" in rec:
        metrics = rec["metrics"]
        if not isinstance(metrics, list):
            errors.append(OrchestrationFieldError(field=f"{path}.metrics", message=f"'{path}.metrics' must be a list of strings."))
        else:
            for i, m in enumerate(metrics):
                if not isinstance(m, str) or not m.strip():
                    errors.append(OrchestrationFieldError(field=f"{path}.metrics[{i}]", message=f"'{path}.metrics[{i}]' must be a non-empty string."))
    rule = rec.get("rule")
    if not isinstance(rule, list) or not rule:
        errors.append(OrchestrationFieldError(field=f"{path}.rule", message=f"'{path}.rule' must be a non-empty list of guards."))
        return
    for i, guard in enumerate(rule):
        gpath = f"{path}.rule[{i}]"
        if not isinstance(guard, dict):
            errors.append(OrchestrationFieldError(field=gpath, message=f"Guard at '{gpath}' must be an object."))
            continue
        if "default" in guard:
            if set(guard) != {"default"}:
                errors.append(OrchestrationFieldError(field=gpath, message=f"A 'default' guard at '{gpath}' must contain only 'default'."))
            elif not isinstance(guard["default"], str) or not guard["default"].strip():
                errors.append(OrchestrationFieldError(field=f"{gpath}.default", message=f"'{gpath}.default' must be a non-empty string."))
            continue
        if "when" not in guard or "recommend" not in guard:
            errors.append(OrchestrationFieldError(field=gpath, message=f"Guard at '{gpath}' must have 'when' + 'recommend', or be a 'default' guard."))
            continue
        when = guard["when"]
        if not isinstance(when, str) or not when.strip():
            errors.append(OrchestrationFieldError(field=f"{gpath}.when", message=f"'{gpath}.when' must be a non-empty string."))
        else:
            try:
                validate_condition_syntax(when)
            except RecommenderRuleError as exc:
                errors.append(OrchestrationFieldError(field=f"{gpath}.when", message=f"'{gpath}.when' is unsafe or invalid: {exc}"))
        if not isinstance(guard["recommend"], str) or not guard["recommend"].strip():
            errors.append(OrchestrationFieldError(field=f"{gpath}.recommend", message=f"'{gpath}.recommend' must be a non-empty string."))


def _validate_decision_body(body: Dict[str, Any], path: str, errors: List[OrchestrationFieldError]) -> None:
    """Plainspoken Marmot: validate a facilitator-decision body.

    Shared by the `facilitator-decision` step and the `round_gate.decision`
    embedded in an iterate, so the two cannot drift (the unification in HICSS
    outline section L.1). Requires a non-empty prompt and a non-empty options
    list; context_bundle_keys, report, and recommender are optional.
    """
    if "prompt" not in body:
        errors.append(OrchestrationFieldError(field=f"{path}.prompt", message=f"Missing required 'prompt' in '{path}'."))
    elif not isinstance(body["prompt"], str) or not body["prompt"].strip():
        errors.append(OrchestrationFieldError(field=f"{path}.prompt", message=f"'{path}.prompt' must be a non-empty string."))

    if "options" not in body:
        errors.append(OrchestrationFieldError(field=f"{path}.options", message=f"Missing required 'options' list in '{path}'."))
    else:
        opts = body["options"]
        if not isinstance(opts, list) or not opts:
            errors.append(OrchestrationFieldError(field=f"{path}.options", message=f"'{path}.options' must be a non-empty list of strings."))
        else:
            for oi, opt in enumerate(opts):
                if not isinstance(opt, str) or not opt.strip():
                    errors.append(OrchestrationFieldError(field=f"{path}.options[{oi}]", message=f"Option at '{path}.options[{oi}]' must be a non-empty string."))

    if "context_bundle_keys" in body:
        cbk = body["context_bundle_keys"]
        if not isinstance(cbk, list):
            errors.append(OrchestrationFieldError(field=f"{path}.context_bundle_keys", message=f"'{path}.context_bundle_keys' must be a list of strings."))
        else:
            for ci, key in enumerate(cbk):
                if not isinstance(key, str) or not key.strip():
                    errors.append(OrchestrationFieldError(field=f"{path}.context_bundle_keys[{ci}]", message=f"Context bundle key at '{path}.context_bundle_keys[{ci}]' must be a non-empty string."))

    if "report" in body:
        _validate_report(body["report"], f"{path}.report", errors)
    if "recommender" in body:
        _validate_recommender(body["recommender"], f"{path}.recommender", errors)


def validate_orchestration(data: Any) -> OrchestrationValidationResult:
    """Validate orchestration data against grammar invariants.

    Enforces metadata shapes, step-kind validation against the activity catalog,
    and structural rules (e.g. ai-decision review_required sequence pairing).
    """
    errors: List[OrchestrationFieldError] = []
    warnings: List[OrchestrationFieldError] = []

    if not isinstance(data, dict):
        errors.append(OrchestrationFieldError(field="", message="Orchestration document must be a dictionary object."))
        return OrchestrationValidationResult(valid=False, errors=errors, warnings=warnings)

    # Top-level required fields
    for field in ["name", "version", "author", "citation", "metadata", "steps"]:
        if field not in data:
            errors.append(OrchestrationFieldError(field=field, message=f"Missing required top-level field '{field}'."))

    # Validate string properties
    for field in ["name", "version", "author", "citation"]:
        if field in data:
            val = data[field]
            if not isinstance(val, str):
                errors.append(OrchestrationFieldError(field=field, message=f"Field '{field}' must be a string."))
            elif not val.strip():
                errors.append(OrchestrationFieldError(field=field, message=f"Field '{field}' must not be empty."))

    # Validate metadata
    if "metadata" in data:
        meta = data["metadata"]
        if not isinstance(meta, dict):
            errors.append(OrchestrationFieldError(field="metadata", message="Field 'metadata' must be a dictionary."))
        else:
            # metadata required fields
            for mfield in ["thinklets", "collaboration_patterns", "deliverables", "group_size_range", "typical_duration_minutes"]:
                if mfield not in meta:
                    errors.append(OrchestrationFieldError(field=f"metadata.{mfield}", message=f"Missing required metadata field '{mfield}'."))

            # lists of strings
            for mfield in ["thinklets", "collaboration_patterns", "deliverables"]:
                if mfield in meta:
                    lst = meta[mfield]
                    if not isinstance(lst, list):
                        errors.append(OrchestrationFieldError(field=f"metadata.{mfield}", message=f"Field 'metadata.{mfield}' must be a list."))
                    else:
                        for idx, item in enumerate(lst):
                            if not isinstance(item, str):
                                errors.append(OrchestrationFieldError(field=f"metadata.{mfield}[{idx}]", message=f"Item at metadata.{mfield}[{idx}] must be a string."))
                            elif not item.strip():
                                errors.append(OrchestrationFieldError(field=f"metadata.{mfield}[{idx}]", message=f"Item at metadata.{mfield}[{idx}] must not be empty."))

            # ranges
            for mfield in ["group_size_range", "typical_duration_minutes"]:
                if mfield in meta:
                    rng = meta[mfield]
                    if not isinstance(rng, dict):
                        errors.append(OrchestrationFieldError(field=f"metadata.{mfield}", message=f"Field 'metadata.{mfield}' must be a dictionary."))
                    else:
                        for rkey in ["min", "max"]:
                            if rkey not in rng:
                                errors.append(OrchestrationFieldError(field=f"metadata.{mfield}.{rkey}", message=f"Missing range limit '{rkey}' in 'metadata.{mfield}'."))
                            else:
                                rval = rng[rkey]
                                if not isinstance(rval, int) or isinstance(rval, bool):
                                    errors.append(OrchestrationFieldError(field=f"metadata.{mfield}.{rkey}", message=f"Range limit '{rkey}' in 'metadata.{mfield}' must be an integer."))
                                elif rval < 0:
                                    errors.append(OrchestrationFieldError(field=f"metadata.{mfield}.{rkey}", message=f"Range limit '{rkey}' in 'metadata.{mfield}' must be non-negative."))
                        if "min" in rng and "max" in rng:
                            min_val = rng["min"]
                            max_val = rng["max"]
                            if isinstance(min_val, int) and not isinstance(min_val, bool) and isinstance(max_val, int) and not isinstance(max_val, bool):
                                if min_val > max_val:
                                    errors.append(OrchestrationFieldError(field=f"metadata.{mfield}", message=f"Range 'min' ({min_val}) cannot exceed 'max' ({max_val}) in 'metadata.{mfield}'."))

    # Get valid activity types
    catalog = get_enriched_activity_catalog()
    valid_tool_types = {entry.get("tool_type").strip().lower() for entry in catalog if isinstance(entry.get("tool_type"), str)}

    # Validate steps
    if "steps" in data:
        steps = data["steps"]
        if not isinstance(steps, list):
            errors.append(OrchestrationFieldError(field="steps", message="Field 'steps' must be a list."))
        else:
            # Recursive step validator
            def validate_step_list(step_list: Any, parent_path: str) -> None:
                if not isinstance(step_list, list):
                    errors.append(OrchestrationFieldError(field=parent_path, message=f"Expected a list of steps at '{parent_path}'."))
                    return

                for idx, step in enumerate(step_list):
                    path = f"{parent_path}[{idx}]" if parent_path else f"steps[{idx}]"
                    if not isinstance(step, dict):
                        errors.append(OrchestrationFieldError(field=path, message="Step must be a dictionary object."))
                        continue

                    if "type" not in step:
                        errors.append(OrchestrationFieldError(field=f"{path}.type", message="Missing step type field 'type'."))
                        continue

                    stype = step["type"]
                    if stype not in ["sequence", "iterate", "conditional", "activity", "facilitator-decision", "ai-decision"]:
                        errors.append(OrchestrationFieldError(field=f"{path}.type", message=f"Invalid step type '{stype}'."))
                        continue

                    if stype == "sequence":
                        if "steps" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.steps", message="Missing required steps list in sequence step."))
                        else:
                            validate_step_list(step["steps"], f"{path}.steps")

                    elif stype == "iterate":
                        if "steps" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.steps", message="Missing required steps list in iterate step."))
                        else:
                            validate_step_list(step["steps"], f"{path}.steps")

                        if "max_rounds" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.max_rounds", message="Missing required 'max_rounds' in iterate step."))
                        else:
                            mr = step["max_rounds"]
                            if not isinstance(mr, int) or isinstance(mr, bool) or mr < 1:
                                errors.append(OrchestrationFieldError(field=f"{path}.max_rounds", message="'max_rounds' in iterate step must be a positive integer >= 1."))

                        for pred_field in ["convergence_predicate", "bundle_transform"]:
                            if pred_field not in step:
                                errors.append(OrchestrationFieldError(field=f"{path}.{pred_field}", message=f"Missing required '{pred_field}' in iterate step."))
                            else:
                                obj = step[pred_field]
                                if not isinstance(obj, dict):
                                    errors.append(OrchestrationFieldError(field=f"{path}.{pred_field}", message=f"'{pred_field}' in iterate step must be a dictionary."))
                                else:
                                    if "name" not in obj:
                                        errors.append(OrchestrationFieldError(field=f"{path}.{pred_field}.name", message=f"Missing required 'name' in iterate step '{pred_field}'."))
                                    elif not isinstance(obj["name"], str) or not obj["name"].strip():
                                        errors.append(OrchestrationFieldError(field=f"{path}.{pred_field}.name", message=f"'{pred_field}' name must be a non-empty string."))
                                    if "config" not in obj:
                                        errors.append(OrchestrationFieldError(field=f"{path}.{pred_field}.config", message=f"Missing required 'config' in iterate step '{pred_field}'."))
                                    elif not isinstance(obj["config"], dict):
                                        errors.append(OrchestrationFieldError(field=f"{path}.{pred_field}.config", message=f"'{pred_field}' config must be a dictionary."))

                        # Plainspoken Marmot: optional facilitator round-gate. The
                        # gate now embeds a full facilitator-decision (unification,
                        # HICSS outline L.1); the old {mode, recommendation} enum
                        # form was removed (clean break). The recommended option is
                        # resolved at runtime from the decision's recommender rule,
                        # so it is not authored here.
                        if "round_gate" in step:
                            gate = step["round_gate"]
                            if not isinstance(gate, dict):
                                errors.append(OrchestrationFieldError(field=f"{path}.round_gate", message="'round_gate' must be a dictionary."))
                            elif "mode" in gate or "recommendation" in gate:
                                errors.append(OrchestrationFieldError(
                                    field=f"{path}.round_gate",
                                    message=(
                                        "'round_gate' now embeds a 'decision' (a facilitator-decision body); "
                                        "the {'mode','recommendation'} form was removed. Wrap the decision in "
                                        "'round_gate.decision' and express the suggestion as a 'recommender' rule."
                                    ),
                                ))
                            elif "decision" not in gate:
                                errors.append(OrchestrationFieldError(field=f"{path}.round_gate.decision", message="Missing required 'decision' in 'round_gate'."))
                            elif not isinstance(gate["decision"], dict):
                                errors.append(OrchestrationFieldError(field=f"{path}.round_gate.decision", message="'round_gate.decision' must be a dictionary."))
                            else:
                                _validate_decision_body(gate["decision"], f"{path}.round_gate.decision", errors)

                    elif stype == "conditional":
                        errors.append(OrchestrationFieldError(
                            field=f"{path}.type",
                            message="conditional step is reserved and deferred; currently unsupported at runtime"
                        ))

                    elif stype == "activity":
                        if "tool_type" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.tool_type", message="Missing required 'tool_type' in activity step."))
                        else:
                            tt = step["tool_type"]
                            if not isinstance(tt, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", tt):
                                errors.append(OrchestrationFieldError(field=f"{path}.tool_type", message="'tool_type' must be a lowercase snake_case string."))
                            elif tt.strip().lower() not in valid_tool_types:
                                errors.append(OrchestrationFieldError(
                                    field=f"{path}.tool_type",
                                    message=f"tool_type '{tt}' is not registered; available types are: {', '.join(sorted(valid_tool_types))}"
                                ))

                        if "title" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.title", message="Missing required 'title' in activity step."))
                        else:
                            t = step["title"]
                            if not isinstance(t, str) or not t.strip():
                                errors.append(OrchestrationFieldError(field=f"{path}.title", message="'title' in activity step must be a non-empty string."))

                        if "config" in step:
                            if not isinstance(step["config"], dict):
                                errors.append(OrchestrationFieldError(field=f"{path}.config", message="'config' in activity step must be a dictionary."))

                        if "transform_input" in step:
                            ti = step["transform_input"]
                            if not isinstance(ti, str) or not ti.strip():
                                errors.append(OrchestrationFieldError(field=f"{path}.transform_input", message="'transform_input' in activity step must be a non-empty string."))

                    elif stype == "facilitator-decision":
                        _validate_decision_body(step, path, errors)

                    elif stype == "ai-decision":
                        if "prompt_template" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.prompt_template", message="Missing required 'prompt_template' in ai-decision step."))
                        else:
                            pt = step["prompt_template"]
                            if not isinstance(pt, str) or not pt.strip():
                                errors.append(OrchestrationFieldError(field=f"{path}.prompt_template", message="'prompt_template' in ai-decision step must be a non-empty string."))

                        if "output_schema" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.output_schema", message="Missing required 'output_schema' in ai-decision step."))
                        else:
                            if not isinstance(step["output_schema"], dict):
                                errors.append(OrchestrationFieldError(field=f"{path}.output_schema", message="'output_schema' in ai-decision step must be a dictionary."))

                        if "review_required" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.review_required", message="Missing required 'review_required' boolean in ai-decision step."))
                        else:
                            if not isinstance(step["review_required"], bool):
                                errors.append(OrchestrationFieldError(field=f"{path}.review_required", message="'review_required' in ai-decision step must be a boolean."))

                        if "context_bundle_keys" in step:
                            cbk = step["context_bundle_keys"]
                            if not isinstance(cbk, list):
                                errors.append(OrchestrationFieldError(field=f"{path}.context_bundle_keys", message="'context_bundle_keys' must be a list of strings."))
                            else:
                                for cidx, key in enumerate(cbk):
                                    if not isinstance(key, str) or not key.strip():
                                        errors.append(OrchestrationFieldError(field=f"{path}.context_bundle_keys[{cidx}]", message=f"Context bundle key at '{path}.context_bundle_keys[{cidx}]' must be a non-empty string."))

                    # Check that if review_required is True, the immediately following step is a facilitator-decision
                    if stype == "ai-decision" and step.get("review_required") is True:
                        has_following_facilitator = False
                        if idx + 1 < len(step_list):
                            next_step = step_list[idx + 1]
                            if isinstance(next_step, dict) and next_step.get("type") == "facilitator-decision":
                                has_following_facilitator = True
                        if not has_following_facilitator:
                            errors.append(OrchestrationFieldError(
                                field=path,
                                message="ai-decision step with review_required=true must be immediately followed by a facilitator-decision step."
                            ))

            validate_step_list(steps, "steps")

    return OrchestrationValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings
    )


def _parse_step(data: Dict[str, Any]) -> OrchestrationStep:
    stype = data["type"]
    if stype == "sequence":
        return SequenceStep(steps=[_parse_step(s) for s in data["steps"]])
    elif stype == "iterate":
        return IterateStep(
            steps=[_parse_step(s) for s in data["steps"]],
            max_rounds=data["max_rounds"],
            convergence_predicate=data["convergence_predicate"],
            bundle_transform=data["bundle_transform"],
            round_gate=data.get("round_gate"),
        )
    elif stype == "conditional":
        return ConditionalStep()
    elif stype == "activity":
        return ActivityStep(
            tool_type=data["tool_type"],
            title=data["title"],
            config=data.get("config", {}),
            transform_input=data.get("transform_input")
        )
    elif stype == "facilitator-decision":
        return FacilitatorDecisionStep(
            prompt=data["prompt"],
            options=data["options"],
            context_bundle_keys=data.get("context_bundle_keys", []),
            report=data.get("report"),
            recommender=data.get("recommender"),
        )
    elif stype == "ai-decision":
        return AIDecisionStep(
            prompt_template=data["prompt_template"],
            output_schema=data["output_schema"],
            review_required=data["review_required"],
            context_bundle_keys=data.get("context_bundle_keys", [])
        )
    else:
        raise ValueError(f"Unsupported step type: {stype}")


def load_orchestration_data(data: Any) -> OrchestrationDocument:
    """Validate and parse an in-memory orchestration document.

    Raises:
        OrchestrationValidationError: If validation fails.
    """
    result = validate_orchestration(data)
    if not result.valid:
        raise OrchestrationValidationError(result)

    metadata_dict = data["metadata"]
    metadata = OrchestrationMetadata(
        thinklets=metadata_dict["thinklets"],
        collaboration_patterns=metadata_dict["collaboration_patterns"],
        deliverables=metadata_dict["deliverables"],
        group_size_range=metadata_dict["group_size_range"],
        typical_duration_minutes=metadata_dict["typical_duration_minutes"],
        notes=metadata_dict.get("notes"),
    )

    steps = [_parse_step(s) for s in data["steps"]]

    return OrchestrationDocument(
        name=data["name"],
        version=data["version"],
        author=data["author"],
        citation=data["citation"],
        metadata=metadata,
        steps=steps
    )


def load_orchestration_path(path: str | Path) -> OrchestrationDocument:
    """Load, validate, and parse a JSON orchestration file from disk.

    Raises:
        OrchestrationValidationError: If validation fails.
        FileNotFoundError: If the path does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    return load_orchestration_data(data)


def load_orchestration_file(path_or_str: str | Path) -> OrchestrationDocument:
    """Deprecated combined entry point. Prefer load_orchestration_path or
    load_orchestration_data. Accepts a filesystem path, a Path object, or a
    raw JSON string; dispatches based on whether the string parses as JSON.
    """
    if isinstance(path_or_str, Path):
        return load_orchestration_path(path_or_str)
    if isinstance(path_or_str, str):
        try:
            data = json.loads(path_or_str)
        except json.JSONDecodeError:
            return load_orchestration_path(path_or_str)
        return load_orchestration_data(data)
    raise TypeError("path_or_str must be a string or Path object")
