from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.plugins.registry import get_activity_registry
from app.utils.identifiers import derive_activity_prefix

_DEFAULT_WRITE_POLICY: Dict[str, Any] = {
    "retryable_statuses": [429, 502, 503, 504],
    "max_retries": 2,
    "base_delay_ms": 350,
    "max_delay_ms": 1800,
    "jitter_ratio": 0.2,
    "idempotency_header": "X-Idempotency-Key",
}
_DEFAULT_WRITE_POLICY_KEY = "write_default"


def _normalise_reliability_action_policy(raw_policy: Dict[str, Any]) -> Dict[str, Any]:
    normalised = dict(_DEFAULT_WRITE_POLICY)
    retryable_statuses = raw_policy.get("retryable_statuses")
    if isinstance(retryable_statuses, list):
        statuses: List[int] = []
        for value in retryable_statuses:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if 100 <= parsed <= 599 and parsed not in statuses:
                statuses.append(parsed)
        if statuses:
            normalised["retryable_statuses"] = statuses

    for key in ("max_retries", "base_delay_ms", "max_delay_ms"):
        value = raw_policy.get(key)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            normalised[key] = parsed

    normalised["base_delay_ms"] = max(1, int(normalised["base_delay_ms"]))
    normalised["max_delay_ms"] = max(
        int(normalised["base_delay_ms"]), int(normalised["max_delay_ms"])
    )

    jitter = raw_policy.get("jitter_ratio")
    try:
        parsed_jitter = float(jitter)
    except (TypeError, ValueError):
        parsed_jitter = float(_DEFAULT_WRITE_POLICY["jitter_ratio"])
    normalised["jitter_ratio"] = max(0.0, min(1.0, parsed_jitter))

    idem = raw_policy.get("idempotency_header")
    if isinstance(idem, str) and idem.strip():
        normalised["idempotency_header"] = idem.strip()

    return normalised


def normalise_reliability_policy(raw_policy: Any) -> Dict[str, Any]:
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    normalised: Dict[str, Any] = {}
    for action, value in policy.items():
        if not isinstance(action, str) or not action.strip() or not isinstance(value, dict):
            continue
        normalised[action.strip()] = _normalise_reliability_action_policy(value)

    fallback = (
        normalised.get(_DEFAULT_WRITE_POLICY_KEY)
        or normalised.get("submit")
        or normalised.get("submit_idea")
    )
    if isinstance(fallback, dict):
        normalised[_DEFAULT_WRITE_POLICY_KEY] = dict(fallback)
    else:
        normalised[_DEFAULT_WRITE_POLICY_KEY] = dict(_DEFAULT_WRITE_POLICY)

    return normalised


def get_activity_catalog() -> List[Dict[str, Any]]:
    """Return the catalog of available agenda modules enriched with identifier stems."""
    catalog: List[Dict[str, Any]] = []
    registry = get_activity_registry()
    for plugin in registry.list_plugins():
        entry = {
            "tool_type": plugin.manifest.tool_type,
            "label": plugin.manifest.label,
            "description": plugin.manifest.description,
            "default_config": dict(plugin.manifest.default_config or {}),
            "reliability_policy": normalise_reliability_policy(
                plugin.manifest.reliability_policy
            ),
        }
        enriched = dict(entry)
        enriched["stem"] = derive_activity_prefix(entry["tool_type"])
        catalog.append(enriched)
    return catalog


def get_activity_definition(tool_type: str) -> Optional[Dict[str, Any]]:
    """Return the catalog entry for the given tool type, if registered."""
    normalised = (tool_type or "").strip().lower()
    registry = get_activity_registry()
    plugin = registry.get_plugin(normalised)
    if not plugin:
        return None
    entry = {
        "tool_type": plugin.manifest.tool_type,
        "label": plugin.manifest.label,
        "description": plugin.manifest.description,
        "default_config": dict(plugin.manifest.default_config or {}),
        "reliability_policy": normalise_reliability_policy(
            plugin.manifest.reliability_policy
        ),
    }
    enriched = dict(entry)
    enriched["stem"] = derive_activity_prefix(normalised)
    return enriched
