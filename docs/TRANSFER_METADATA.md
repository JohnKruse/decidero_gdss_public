Transfer Metadata Contract
==========================

Purpose
-------
Transfer bundles carry a metadata block that documents the transfer context,
ensures consistent round indexing, and appends a history trail for auditing.

Top-Level Schema
----------------
```
{
  "schema_version": 1,
  "meeting_id": "<meeting id>",
  "created_at": "<ISO-8601 UTC timestamp>",
  "round_index": <non-negative integer>,
  "source": {
    "activity_id": "<donor activity id>",
    "tool_type": "<donor tool type>"
  },
  "history": [
    {
      "tool_type": "transfer_draft|transfer_commit|<tool type>",
      "activity_id": "<activity id>",
      "created_at": "<ISO-8601 UTC timestamp>",
      "round_index": <non-negative integer>,
      "details": { ... }
    }
  ],
  "tools": {
    "<tool_type>": { ... }
  },
  "...": "transfer-specific fields (include_comments, comments_by_parent, etc.)"
}
```

Round Index Rules
-----------------
- `round_index` is 0-based and always non-negative.
- If a client supplies `metadata.round_index`, that value is normalized and
  preserved.
- Otherwise, the server derives it from the donor activity order index:
  `max(donor.order_index - 1, 0)`.
- Updates re-use the existing `round_index` stored in metadata.

History Trail Rules
-------------------
- Each transfer draft save appends a `transfer_draft` history entry with
  timestamp, round_index, and basic counts.
- Each transfer commit appends a `transfer_commit` history entry describing
  the target tool type and transfer counts.
- History entries include `created_at` timestamps in UTC ISO-8601 format.

Per-Tool Metadata Blocks
------------------------
- The `tools` map contains per-tool metadata blocks keyed by tool type.
- The transfer pipeline records:
  - `tools.transfer`: counts and include_comments flags.
  - `tools.<target tool type>`: activity id and title of the newly created
    activity.
