from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Iterable, List

from app.plugins.base import ActivityPlugin


def _load_module_from_path(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _extract_plugins(module) -> List[ActivityPlugin]:
    plugins: List[ActivityPlugin] = []
    if hasattr(module, "get_plugin"):
        plugin = module.get_plugin()
        if plugin:
            plugins.append(plugin)
    if hasattr(module, "PLUGIN"):
        plugin = getattr(module, "PLUGIN")
        if plugin:
            plugins.append(plugin)
    if hasattr(module, "PLUGINS"):
        for plugin in getattr(module, "PLUGINS"):
            if plugin:
                plugins.append(plugin)
    return plugins


def load_dropin_plugins(directory: Path) -> Iterable[ActivityPlugin]:
    if not directory.exists() or not directory.is_dir():
        return []
    plugins: List[ActivityPlugin] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"decidero_plugin_{path.stem}"
        module = _load_module_from_path(path, module_name)
        if not module:
            continue
        plugins.extend(_extract_plugins(module))
    return plugins


def load_builtin_plugins() -> Iterable[ActivityPlugin]:
    modules = [
        "app.plugins.builtin.brainstorming_plugin",
        "app.plugins.builtin.voting_plugin",
        "app.plugins.builtin.categorization_plugin",
    ]
    plugins: List[ActivityPlugin] = []
    for module_name in modules:
        module = importlib.import_module(module_name)
        plugins.extend(_extract_plugins(module))
    return plugins
