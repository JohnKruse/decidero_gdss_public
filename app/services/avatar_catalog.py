from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("avatars")

_MANIFEST_CACHE: dict[str, Any] | None = None
_INDEX_CACHE: dict[str, dict[str, Any]] | None = None


def _manifest_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent / "static" / "avatars" / "fluent" / "manifest.json"
    )


def load_avatar_manifest(force_reload: bool = False) -> dict[str, Any]:
    global _MANIFEST_CACHE, _INDEX_CACHE

    if _MANIFEST_CACHE is not None and not force_reload:
        return _MANIFEST_CACHE

    path = _manifest_path()
    if not path.exists():
        logger.warning("Avatar manifest not found at %s", path)
        _MANIFEST_CACHE = {"schema_version": 1, "count": 0, "avatars": []}
        _INDEX_CACHE = {}
        return _MANIFEST_CACHE

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load avatar manifest %s: %s", path, exc)
        manifest = {"schema_version": 1, "count": 0, "avatars": []}

    avatars = manifest.get("avatars")
    if not isinstance(avatars, list):
        avatars = []
    manifest["avatars"] = avatars
    manifest["count"] = len(avatars)

    index: dict[str, dict[str, Any]] = {}
    for entry in avatars:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if isinstance(key, str) and key.strip():
            index[key.strip()] = entry

    _MANIFEST_CACHE = manifest
    _INDEX_CACHE = index
    return manifest


def list_avatar_entries() -> list[dict[str, Any]]:
    manifest = load_avatar_manifest()
    avatars = manifest.get("avatars")
    return avatars if isinstance(avatars, list) else []


def is_valid_avatar_key(avatar_key: str | None) -> bool:
    if not avatar_key:
        return False
    load_avatar_manifest()
    return bool(_INDEX_CACHE and avatar_key in _INDEX_CACHE)


def get_avatar_entry(avatar_key: str | None) -> dict[str, Any] | None:
    if not avatar_key:
        return None
    load_avatar_manifest()
    if not _INDEX_CACHE:
        return None
    return _INDEX_CACHE.get(avatar_key)


def get_avatar_path(avatar_key: str | None) -> str | None:
    entry = get_avatar_entry(avatar_key)
    if not entry:
        return None
    path = entry.get("path")
    if isinstance(path, str) and path.strip():
        return path
    return None


def _hash_index(seed: str, length: int) -> int:
    if length <= 0:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest, 16) % length


def pick_avatar_key(user_id: str, avatar_seed: int = 0) -> str | None:
    avatars = list_avatar_entries()
    if not avatars:
        return None
    safe_seed = int(avatar_seed or 0)
    idx = _hash_index(f"{user_id}:{safe_seed}", len(avatars))
    entry = avatars[idx]
    key = entry.get("key")
    if isinstance(key, str) and key.strip():
        return key
    return None
