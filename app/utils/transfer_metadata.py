from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

TRANSFER_METADATA_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_round_index(value: Any) -> int:
    if value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed >= 0 else 0


def build_transfer_history_entry(
    *,
    tool_type: str,
    activity_id: Optional[str],
    round_index: Optional[int],
    details: Optional[Dict[str, Any]] = None,
    created_at: Optional[Any] = None,
) -> Dict[str, Any]:
    if isinstance(created_at, datetime):
        created_at_value = created_at.astimezone(timezone.utc).isoformat()
    elif isinstance(created_at, str) and created_at.strip():
        created_at_value = created_at
    else:
        created_at_value = _utc_now_iso()
    entry: Dict[str, Any] = {
        "tool_type": tool_type,
        "created_at": created_at_value,
    }
    if activity_id:
        entry["activity_id"] = activity_id
    if round_index is not None:
        entry["round_index"] = _normalize_round_index(round_index)
    if details:
        entry["details"] = details
    return entry


def append_transfer_history(
    *,
    metadata: Dict[str, Any],
    tool_type: str,
    activity_id: Optional[str],
    details: Optional[Dict[str, Any]] = None,
    created_at: Optional[Any] = None,
) -> Dict[str, Any]:
    history = list(metadata.get("history") or [])
    base_round = _normalize_round_index(metadata.get("round_index"))
    next_round = base_round
    for entry in reversed(history):
        if entry.get("tool_type") != tool_type:
            continue
        next_round = _normalize_round_index(entry.get("round_index")) + 1
        break

    history_entry = build_transfer_history_entry(
        tool_type=tool_type,
        activity_id=activity_id,
        round_index=next_round,
        details=details,
        created_at=created_at or metadata.get("created_at"),
    )
    history.append(history_entry)
    metadata["history"] = history
    return metadata


def ensure_transfer_metadata(
    *,
    base: Optional[Dict[str, Any]],
    meeting_id: str,
    source_activity_id: Optional[str],
    source_tool_type: Optional[str],
    round_index: Optional[int],
    history_entry: Optional[Dict[str, Any]] = None,
    tool_type: Optional[str] = None,
    tool_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = dict(base or {})
    metadata["schema_version"] = TRANSFER_METADATA_SCHEMA_VERSION
    metadata["meeting_id"] = meeting_id

    if "created_at" not in metadata:
        metadata["created_at"] = _utc_now_iso()

    normalized_round = _normalize_round_index(
        round_index if round_index is not None else metadata.get("round_index")
    )
    metadata["round_index"] = normalized_round

    if source_activity_id or source_tool_type:
        source = dict(metadata.get("source") or {})
        if source_activity_id:
            source["activity_id"] = source_activity_id
        if source_tool_type:
            source["tool_type"] = source_tool_type
        metadata["source"] = source

    history = list(metadata.get("history") or [])
    if history_entry:
        history.append(history_entry)
    metadata["history"] = history

    tools = dict(metadata.get("tools") or {})
    if tool_type:
        tool_block = dict(tools.get(tool_type) or {})
        if tool_details:
            tool_block.update(tool_details)
        tools[tool_type] = tool_block
    metadata["tools"] = tools

    return metadata
