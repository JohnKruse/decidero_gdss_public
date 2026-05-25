from app.services.contract_schemas import validate_transfer_metadata
from app.utils.transfer_metadata import append_transfer_history, ensure_transfer_metadata


def test_append_transfer_history_uses_created_at_and_increments_per_tool():
    metadata = {
        "created_at": "2025-01-01T00:00:00+00:00",
        "round_index": 0,
        "history": [],
    }

    append_transfer_history(
        metadata=metadata,
        tool_type="transfer_commit",
        activity_id="activity-1",
        details={"count": 1},
    )
    history = metadata.get("history") or []
    assert history[-1]["created_at"] == metadata["created_at"]
    assert history[-1]["round_index"] == 0

    append_transfer_history(
        metadata=metadata,
        tool_type="transfer_commit",
        activity_id="activity-1",
    )
    history = metadata.get("history") or []
    assert history[-1]["round_index"] == 1

    append_transfer_history(
        metadata=metadata,
        tool_type="transfer_draft",
        activity_id="activity-1",
    )
    history = metadata.get("history") or []
    assert history[-1]["round_index"] == 0

    append_transfer_history(
        metadata=metadata,
        tool_type="transfer_commit",
        activity_id="activity-1",
    )
    history = metadata.get("history") or []
    assert history[-1]["round_index"] == 2


def test_transfer_metadata_schema_conformance_for_normalized_payload():
    """Tangerine Larynx: normalized transfer metadata conforms to the Phase 1 schema."""
    metadata = ensure_transfer_metadata(
        base={},
        meeting_id="M-XFER",
        source_activity_id="M-XFER-BRAIN-0001",
        source_tool_type="brainstorming",
        round_index=0,
        tool_type="transfer",
        tool_details={"include_comments": True},
    )
    append_transfer_history(
        metadata=metadata,
        tool_type="transfer_draft",
        activity_id="M-XFER-BRAIN-0001",
        details={"item_count": 1},
    )

    assert validate_transfer_metadata(metadata)["source"]["tool_type"] == "brainstorming"
