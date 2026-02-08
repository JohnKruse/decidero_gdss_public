from app.utils.transfer_metadata import append_transfer_history


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
