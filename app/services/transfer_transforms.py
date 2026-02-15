from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


DEFAULT_PROFILE = "standard"
CATEGORIZATION_DEFAULT_PROFILE = "bucket_rollup"
PROFILE_BUCKET_ROLLUP = "bucket_rollup"
PROFILE_BUCKET_SUFFIX = "bucket_suffix"
PROFILE_STANDARD = "standard"


@dataclass(frozen=True)
class TransferTransformResult:
    items: List[Dict[str, Any]]
    profile: str


def normalize_transfer_profile(donor_tool_type: str, requested_profile: str | None) -> str:
    tool_type = str(donor_tool_type or "").strip().lower()
    profile = str(requested_profile or "").strip().lower()
    if tool_type == "categorization":
        if profile in {PROFILE_BUCKET_ROLLUP, PROFILE_BUCKET_SUFFIX, PROFILE_STANDARD}:
            return profile
        return CATEGORIZATION_DEFAULT_PROFILE
    return PROFILE_STANDARD


def apply_transfer_transform(
    *,
    items: List[Dict[str, Any]],
    donor_tool_type: str,
    requested_profile: str | None,
    source_metadata: Dict[str, Any] | None = None,
) -> TransferTransformResult:
    profile = normalize_transfer_profile(donor_tool_type, requested_profile)
    if profile == PROFILE_STANDARD:
        return TransferTransformResult(items=list(items or []), profile=profile)
    if str(donor_tool_type or "").strip().lower() != "categorization":
        return TransferTransformResult(items=list(items or []), profile=PROFILE_STANDARD)
    if profile == PROFILE_BUCKET_SUFFIX:
        return TransferTransformResult(
            items=_categorization_bucket_suffix(items or []),
            profile=PROFILE_BUCKET_SUFFIX,
        )
    return TransferTransformResult(
        items=_categorization_bucket_rollup(items or [], source_metadata or {}),
        profile=PROFILE_BUCKET_ROLLUP,
    )


def _categorization_bucket_rollup(
    items: List[Dict[str, Any]],
    source_metadata: Dict[str, Any],
) -> List[Dict[str, Any]]:
    bucket_order = _extract_bucket_order(source_metadata)
    bucket_by_id = {entry[0]: entry[1] for entry in bucket_order}
    grouped: Dict[str, List[str]] = {bucket_id: [] for bucket_id, _ in bucket_order}

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("parent_id") is not None:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        category = _extract_category(item)
        bucket_id = category["bucket_id"]
        bucket_title = category["bucket_title"]
        if bucket_id not in grouped:
            grouped[bucket_id] = []
            bucket_by_id[bucket_id] = bucket_title
        grouped[bucket_id].append(content)

    sortable: List[Tuple[int, str, str]] = []
    for bucket_id, title in bucket_by_id.items():
        count = len(grouped.get(bucket_id, []))
        sortable.append((count, str(title or bucket_id), bucket_id))
    sortable.sort(key=lambda row: (-row[0], row[1].casefold(), row[1]))

    rolled_up: List[Dict[str, Any]] = []
    for _, title, bucket_id in sortable:
        bucket_items = grouped.get(bucket_id, [])
        if bucket_id == "UNSORTED" and not bucket_items:
            continue
        suffix = "; ".join(bucket_items)
        content = f"Category: {title} (Ideas: {suffix})"
        rolled_up.append(
            {
                "id": f"bucket:{bucket_id}",
                "content": content,
                "submitted_name": None,
                "parent_id": None,
                "timestamp": None,
                "updated_at": None,
                "meeting_id": None,
                "activity_id": None,
                "user_id": None,
                "user_color": None,
                "metadata": {
                    "transfer_transform": {
                        "profile": PROFILE_BUCKET_ROLLUP,
                        "bucket_id": bucket_id,
                        "bucket_title": title,
                        "idea_count": len(bucket_items),
                    }
                },
                "source": {
                    "transform_profile": PROFILE_BUCKET_ROLLUP,
                    "bucket_id": bucket_id,
                },
            }
        )
    return rolled_up


def _categorization_bucket_suffix(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sortable: List[Tuple[int, str, str, Dict[str, Any]]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if item.get("parent_id") is not None:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        category = _extract_category(item)
        bucket_title = category["bucket_title"]
        bucket_order = _extract_bucket_order_value(item)
        sortable.append((bucket_order, bucket_title.casefold(), f"{index:08d}", item))

    sortable.sort(key=lambda row: (row[0], row[1], row[2]))

    transformed: List[Dict[str, Any]] = []
    for _, _, _, item in sortable:
        category = _extract_category(item)
        bucket_title = category["bucket_title"]
        content = str(item.get("content") or "").strip()
        transformed_item = dict(item)
        transformed_item["content"] = f"{content} (Category: {bucket_title})"
        metadata = dict(transformed_item.get("metadata") or {})
        metadata["transfer_transform"] = {
            "profile": PROFILE_BUCKET_SUFFIX,
            "bucket_id": category["bucket_id"],
            "bucket_title": bucket_title,
        }
        transformed_item["metadata"] = metadata
        source = dict(transformed_item.get("source") or {})
        source["transform_profile"] = PROFILE_BUCKET_SUFFIX
        transformed_item["source"] = source
        transformed.append(transformed_item)
    return transformed


def _extract_bucket_order(source_metadata: Dict[str, Any]) -> List[Tuple[str, str]]:
    buckets = source_metadata.get("categorization_buckets") if isinstance(source_metadata, dict) else None
    ordered: List[Tuple[int, str, str]] = []
    if isinstance(buckets, list):
        for index, entry in enumerate(buckets):
            if not isinstance(entry, dict):
                continue
            bucket_id = str(entry.get("category_id") or "").strip()
            if not bucket_id:
                continue
            title = str(entry.get("title") or bucket_id).strip() or bucket_id
            raw_order = entry.get("order_index", index)
            try:
                order_index = int(raw_order)
            except (TypeError, ValueError):
                order_index = index
            ordered.append((order_index, title, bucket_id))
    if not ordered:
        return [("UNSORTED", "Unsorted")]
    ordered.sort(key=lambda row: (row[0], row[1].casefold(), row[1]))
    return [(bucket_id, title) for _, title, bucket_id in ordered]


def _extract_category(item: Dict[str, Any]) -> Dict[str, str]:
    metadata = item.get("metadata") if isinstance(item, dict) else {}
    categorization = metadata.get("categorization") if isinstance(metadata, dict) else {}
    bucket_id = str(
        (categorization.get("bucket_id") if isinstance(categorization, dict) else "")
        or "UNSORTED"
    ).strip() or "UNSORTED"
    bucket_title = str(
        (categorization.get("bucket_title") if isinstance(categorization, dict) else "")
        or ("Unsorted" if bucket_id == "UNSORTED" else bucket_id)
    ).strip() or bucket_id
    return {"bucket_id": bucket_id, "bucket_title": bucket_title}


def _extract_bucket_order_value(item: Dict[str, Any]) -> int:
    metadata = item.get("metadata") if isinstance(item, dict) else {}
    categorization = metadata.get("categorization") if isinstance(metadata, dict) else {}
    raw = categorization.get("bucket_order_index") if isinstance(categorization, dict) else None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 10**9
