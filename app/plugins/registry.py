from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Optional

from app.plugins.base import ActivityPlugin
from app.plugins.loader import load_builtin_plugins, load_dropin_plugins


class ActivityRegistry:
    def __init__(self) -> None:
        self._plugins: Dict[str, ActivityPlugin] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        for plugin in load_builtin_plugins():
            self.register(plugin)
        plugin_dir = os.getenv("DECIDERO_PLUGIN_DIR")
        if plugin_dir:
            dropin_path = Path(plugin_dir).expanduser()
        else:
            dropin_path = Path(__file__).resolve().parents[2] / "plugins"
        for plugin in load_dropin_plugins(dropin_path):
            self.register(plugin)
        self._loaded = True

    def register(self, plugin: ActivityPlugin) -> None:
        tool_type = plugin.manifest.tool_type.strip().lower()
        if tool_type:
            self._plugins[tool_type] = plugin

    def get_plugin(self, tool_type: str) -> Optional[ActivityPlugin]:
        self.load()
        return self._plugins.get((tool_type or "").strip().lower())

    def list_plugins(self) -> Iterable[ActivityPlugin]:
        self.load()
        return list(self._plugins.values())


_registry = ActivityRegistry()


def get_activity_registry() -> ActivityRegistry:
    return _registry
