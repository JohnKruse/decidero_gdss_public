from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.plugins.registry import get_activity_registry
from app.utils.identifiers import derive_activity_prefix


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
    }
    enriched = dict(entry)
    enriched["stem"] = derive_activity_prefix(normalised)
    return enriched
