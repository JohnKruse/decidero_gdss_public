from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config.loader import get_autosave_seconds


@dataclass(frozen=True)
class TransferSourceResult:
    items: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "plugin"


@dataclass(frozen=True)
class ActivityPluginManifest:
    tool_type: str
    label: str
    description: str
    default_config: Dict[str, Any] = field(default_factory=dict)
    autosave_seconds: Optional[int] = None


class ActivityPlugin(ABC):
    manifest: ActivityPluginManifest

    @abstractmethod
    def open_activity(self, context, input_bundle=None) -> None:
        """Initialize the activity when it starts."""

    @abstractmethod
    def close_activity(self, context) -> Optional[Dict[str, Any]]:
        """Finalize the activity and return an output bundle payload."""

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize the config payload."""
        return config

    def snapshot_activity(self, context) -> Optional[Dict[str, Any]]:
        """Return a draft bundle payload for autosave."""
        return None

    def get_transfer_source(
        self,
        context,
        include_comments: bool = True,
    ) -> Optional[TransferSourceResult]:
        """Return transfer items for this activity, or None to use defaults."""
        return None

    def get_transfer_count(self, context) -> Optional[int]:
        """Return transfer item count, or None to use defaults."""
        return None

    def get_autosave_seconds(self, config: Optional[Dict[str, Any]] = None) -> int:
        config = config or {}
        autosave = config.get("autosave_seconds")
        if autosave is None:
            autosave = self.manifest.autosave_seconds
        if autosave is None:
            autosave = get_autosave_seconds()
        try:
            autosave = int(autosave)
        except (TypeError, ValueError):
            autosave = get_autosave_seconds()
        return max(5, min(300, autosave))
