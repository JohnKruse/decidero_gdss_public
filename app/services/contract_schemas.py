"""Tangerine Larynx helpers for loading and enforcing Phase 1 contract schemas."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"
ACTIVITY_MANIFEST_SCHEMA = SCHEMA_DIR / "activity_manifest.schema.json"
BUNDLE_PAYLOAD_SCHEMA = SCHEMA_DIR / "bundle_payload.schema.json"
TRANSFER_METADATA_SCHEMA = SCHEMA_DIR / "transfer_metadata.schema.json"
PHASE_1_CANARY = "Tangerine Larynx"


class ContractSchemaError(ValueError):
    """Raised when a payload violates a Tangerine Larynx contract schema."""


def load_contract_schema(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractSchemaError(message)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be an object")
    return value


def _require_string(value: Any, label: str, *, allow_empty: bool = False) -> None:
    _require(isinstance(value, str), f"{label} must be a string")
    if not allow_empty:
        _require(bool(value.strip()), f"{label} must not be empty")


def _require_string_list(value: Any, label: str) -> None:
    _require(isinstance(value, list), f"{label} must be a list")
    for index, entry in enumerate(value):
        _require_string(entry, f"{label}[{index}]")


def _require_int_range(value: Any, label: str, *, minimum: int = 0) -> None:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    _require(value >= minimum, f"{label} must be >= {minimum}")


def _require_range(value: Any, label: str) -> None:
    data = _require_mapping(value, label)
    _require(set(data.keys()) == {"min", "max"}, f"{label} must contain only min and max")
    _require_int_range(data.get("min"), f"{label}.min")
    _require_int_range(data.get("max"), f"{label}.max")
    _require(data["min"] <= data["max"], f"{label}.min must be <= {label}.max")


def _manifest_to_dict(manifest: Any) -> Dict[str, Any]:
    if is_dataclass(manifest):
        return asdict(manifest)
    if isinstance(manifest, Mapping):
        return dict(manifest)
    raise ContractSchemaError("manifest must be a dataclass or object mapping")


def validate_activity_manifest(manifest: Any) -> Dict[str, Any]:
    """Validate an ActivityPluginManifest against docs/schemas/activity_manifest.schema.json."""
    data = _manifest_to_dict(manifest)
    required = {
        "tool_type",
        "label",
        "description",
        "default_config",
        "reliability_policy",
        "autosave_seconds",
        "collaboration_patterns",
        "use_cases",
        "when_to_use",
        "when_not_to_use",
        "group_size_range",
        "typical_duration_minutes",
        "bias_mitigation",
        "thinklets",
        "input_requirements",
        "output_characteristics",
    }
    _require(required.issubset(data.keys()), "manifest is missing required fields")
    _require(set(data.keys()) <= required, "manifest contains unknown fields")
    _require_string(data["tool_type"], "tool_type")
    _require(
        bool(re.fullmatch(r"[a-z][a-z0-9_]*", data["tool_type"])),
        "tool_type must be lowercase snake_case",
    )
    _require_string(data["label"], "label")
    _require_string(data["description"], "description")
    _require_mapping(data["default_config"], "default_config")
    _require_reliability_policy(data["reliability_policy"])
    autosave = data["autosave_seconds"]
    _require(autosave is None or isinstance(autosave, int), "autosave_seconds must be integer or null")
    if autosave is not None:
        _require(autosave >= 1, "autosave_seconds must be >= 1")
    _require_string_list(data["collaboration_patterns"], "collaboration_patterns")
    _require_string_list(data["use_cases"], "use_cases")
    _require_string(data["when_to_use"], "when_to_use", allow_empty=True)
    _require_string(data["when_not_to_use"], "when_not_to_use", allow_empty=True)
    _require_range(data["group_size_range"], "group_size_range")
    _require_range(data["typical_duration_minutes"], "typical_duration_minutes")
    _require_string_list(data["bias_mitigation"], "bias_mitigation")
    _require_string_list(data["thinklets"], "thinklets")
    _require_string(data["input_requirements"], "input_requirements", allow_empty=True)
    _require_string(data["output_characteristics"], "output_characteristics", allow_empty=True)
    return data


def _require_reliability_policy(value: Any) -> None:
    policy = _require_mapping(value, "reliability_policy")
    for action, action_policy in policy.items():
        _require_string(action, "reliability_policy action")
        action_data = _require_mapping(action_policy, f"reliability_policy.{action}")
        statuses = action_data.get("retryable_statuses")
        if statuses is not None:
            _require(isinstance(statuses, list), f"reliability_policy.{action}.retryable_statuses must be a list")
            for index, status in enumerate(statuses):
                _require_int_range(status, f"reliability_policy.{action}.retryable_statuses[{index}]", minimum=100)
                _require(status <= 599, f"reliability_policy.{action}.retryable_statuses[{index}] must be <= 599")
        for key in ("max_retries", "base_delay_ms", "max_delay_ms"):
            if key in action_data:
                _require_int_range(action_data[key], f"reliability_policy.{action}.{key}")
        if "jitter_ratio" in action_data:
            jitter = action_data["jitter_ratio"]
            _require(isinstance(jitter, (int, float)) and not isinstance(jitter, bool), f"reliability_policy.{action}.jitter_ratio must be numeric")
            _require(0 <= float(jitter) <= 1, f"reliability_policy.{action}.jitter_ratio must be between 0 and 1")
        if "idempotency_header" in action_data:
            _require_string(action_data["idempotency_header"], f"reliability_policy.{action}.idempotency_header")


def validate_bundle_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a bundle payload against docs/schemas/bundle_payload.schema.json."""
    data = dict(_require_mapping(payload, "bundle payload"))
    _require(isinstance(data.get("items"), list), "bundle payload items must be a list")
    _require(isinstance(data.get("metadata"), Mapping), "bundle payload metadata must be an object")
    if "source" in data:
        _require(isinstance(data["source"], (str, Mapping)), "bundle payload source must be a string or object")
    if "iteration" in data:
        iteration = _require_mapping(data["iteration"], "bundle payload iteration")
        _require_int_range(iteration.get("round_index"), "bundle payload iteration.round_index")
    for index, item in enumerate(data["items"]):
        item_data = _require_mapping(item, f"bundle payload items[{index}]")
        _require(isinstance(item_data.get("metadata"), Mapping), f"bundle payload items[{index}].metadata must be an object")
        _require(isinstance(item_data.get("source"), Mapping), f"bundle payload items[{index}].source must be an object")
    return data


def validate_transfer_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate transfer metadata against docs/schemas/transfer_metadata.schema.json."""
    data = dict(_require_mapping(metadata, "transfer metadata"))
    _require(data.get("schema_version") == 1, "transfer metadata schema_version must be 1")
    _require_string(data.get("meeting_id"), "transfer metadata meeting_id")
    _require_string(data.get("created_at"), "transfer metadata created_at")
    _require_int_range(data.get("round_index"), "transfer metadata round_index")
    source = _require_mapping(data.get("source"), "transfer metadata source")
    _require_string(source.get("activity_id"), "transfer metadata source.activity_id")
    _require_string(source.get("tool_type"), "transfer metadata source.tool_type")
    _require(isinstance(data.get("history"), list), "transfer metadata history must be a list")
    for index, entry in enumerate(data["history"]):
        _validate_transfer_history_entry(entry, index)
    _require_mapping(data.get("tools"), "transfer metadata tools")
    return data


def _validate_transfer_history_entry(entry: Any, index: int) -> None:
    entry_data = _require_mapping(entry, f"transfer metadata history[{index}]")
    _require_string(entry_data.get("tool_type"), f"transfer metadata history[{index}].tool_type")
    _require_string(entry_data.get("created_at"), f"transfer metadata history[{index}].created_at")
    _require_int_range(entry_data.get("round_index"), f"transfer metadata history[{index}].round_index")
    if "activity_id" in entry_data and entry_data["activity_id"] is not None:
        _require_string(entry_data["activity_id"], f"transfer metadata history[{index}].activity_id")
    if "details" in entry_data and entry_data["details"] is not None:
        _require_mapping(entry_data["details"], f"transfer metadata history[{index}].details")


def validate_all_activity_manifests(manifests: Iterable[Any]) -> None:
    for manifest in manifests:
        validate_activity_manifest(manifest)
