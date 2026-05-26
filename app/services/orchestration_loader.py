"""Orchestration document loader and validator for COPPER-HERON / Insolent Metronome.

This module provides functions to load, validate, and parse process
orchestration JSON files into typed AST representations.
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
    """Represents a single validation error or warning for a field."""

    field: str
    message: str
    level: Literal["error", "warning"] = "error"


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

                    elif stype == "conditional":
                        errors.append(OrchestrationFieldError(
                            field=f"{path}.type",
                            message="conditional step is reserved and deferred; currently unsupported at runtime",
                            level="error"
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
                        if "prompt" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.prompt", message="Missing required 'prompt' in facilitator-decision step."))
                        else:
                            p = step["prompt"]
                            if not isinstance(p, str) or not p.strip():
                                errors.append(OrchestrationFieldError(field=f"{path}.prompt", message="'prompt' in facilitator-decision step must be a non-empty string."))

                        if "options" not in step:
                            errors.append(OrchestrationFieldError(field=f"{path}.options", message="Missing required 'options' list in facilitator-decision step."))
                        else:
                            opts = step["options"]
                            if not isinstance(opts, list) or not opts:
                                errors.append(OrchestrationFieldError(field=f"{path}.options", message="'options' in facilitator-decision step must be a non-empty list of strings."))
                            else:
                                for oidx, opt in enumerate(opts):
                                    if not isinstance(opt, str) or not opt.strip():
                                        errors.append(OrchestrationFieldError(field=f"{path}.options[{oidx}]", message=f"Option at '{path}.options[{oidx}]' must be a non-empty string."))

                        if "context_bundle_keys" in step:
                            cbk = step["context_bundle_keys"]
                            if not isinstance(cbk, list):
                                errors.append(OrchestrationFieldError(field=f"{path}.context_bundle_keys", message="'context_bundle_keys' must be a list of strings."))
                            else:
                                for cidx, key in enumerate(cbk):
                                    if not isinstance(key, str) or not key.strip():
                                        errors.append(OrchestrationFieldError(field=f"{path}.context_bundle_keys[{cidx}]", message=f"Context bundle key at '{path}.context_bundle_keys[{cidx}]' must be a non-empty string."))

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
            bundle_transform=data["bundle_transform"]
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
            context_bundle_keys=data.get("context_bundle_keys", [])
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


def load_orchestration_file(path_or_str: str | Path) -> OrchestrationDocument:
    """Load, validate, and parse a JSON orchestration file.

    Raises:
        OrchestrationValidationError: If validation fails.
    """
    if isinstance(path_or_str, Path):
        with path_or_str.open(encoding="utf-8") as f:
            data = json.load(f)
    elif isinstance(path_or_str, str):
        # Could be path or raw JSON string
        try:
            data = json.loads(path_or_str)
        except json.JSONDecodeError:
            path = Path(path_or_str)
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
    else:
        raise TypeError("path_or_str must be a string or Path object")

    result = validate_orchestration(data)
    if not result.valid:
        raise OrchestrationValidationError(result)

    metadata_dict = data["metadata"]
    metadata = OrchestrationMetadata(
        thinklets=metadata_dict["thinklets"],
        collaboration_patterns=metadata_dict["collaboration_patterns"],
        deliverables=metadata_dict["deliverables"],
        group_size_range=metadata_dict["group_size_range"],
        typical_duration_minutes=metadata_dict["typical_duration_minutes"]
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
