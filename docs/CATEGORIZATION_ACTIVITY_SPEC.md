# Categorization Activity Spec (V1)

This document is the implementation gate for Task Master `#83.1`.
It translates current Decidero contracts into concrete acceptance criteria for the new
`categorization` activity.

## Canonical Sources Reviewed

- `docs/PLUGIN_DEV_GUIDE.md`
- `docs/TRANSFER_METADATA.md`
- `README.md`
- `app/plugins/base.py`
- `app/services/activity_pipeline.py`
- `app/services/transfer_source.py`
- `app/routers/transfer.py`
- `app/plugins/builtin/voting_plugin.py`
- `app/services/voting_manager.py`
- `app/services/meeting_state.py`
- `app/routers/realtime.py`
- `app/utils/websocket_manager.py`
- `app/templates/create_meeting.html`
- `app/static/js/meeting.js`

## Naming And Scope

- Canonical tool type: `categorization`
- UI label: `Bucketing / Categorization`
- V1 delivery gate: fully functional `FACILITATOR_LIVE`
- V1.1 milestone: `PARALLEL_BALLOT` with aggregation and disputed-item resolution

## Standard In/Out Contract (STDIN/STDOUT Bundles)

- Input uses activity bundle `kind=input` from `ActivityPipeline.ensure_input_bundle`.
- Output uses activity bundle `kind=output` finalized on activity stop.
- Optional autosave uses `kind=draft` if `snapshot_activity` is implemented.
- Bundle payload format remains `items: []` + optional `metadata: {}`.
- Transfer metadata must be retained; UI toggles must not remove metadata from payloads.

## Transfer And Provenance Rules

- Transfer intake behavior must match existing transfer conventions in `app/routers/transfer.py`.
- Source item `metadata` and `source` fields must be preserved.
- `include_comments=true` behavior must support comments appended in parentheses format:
  `... (Comments: c1; c2; c3)`.
- `include_comments=false` excludes comment items from transfer content but does not strip metadata history.

## Core Activity Rules

- Always include an implicit `UNSORTED` bucket.
- Facilitator/admin can create/edit/delete/reorder buckets live.
- V1 category deletion policy: moving contained items to `UNSORTED` (Option A).
- Participants cannot edit bucket definitions in V1.
- Bucket and assignment IDs must be stable and scoped to `(meeting_id, activity_id)`.

## Runtime Modes

### FACILITATOR_LIVE (V1 Required)

- Facilitator/admin performs all item moves.
- Participants/observers are view-only.
- All changes broadcast through websocket refresh events.

### PARALLEL_BALLOT (V1.1 Target)

- Each participant assigns each item to one bucket.
- Ballots are private until reveal (default).
- Aggregation fields: `top_category_id`, `top_count`, `top_share`, `second_share`, `margin`, `status_label`.

## RBAC And Participant Scope

- Follow `voting` route pattern for access enforcement:
  - meeting membership checks
  - facilitator/admin elevated permissions
  - per-activity participant scope from realtime metadata, fallback to `activity.config.participant_ids`
- Participants out of scope receive `403`.

## Realtime Contract

- Use `meeting_state_manager` + `websocket_manager` patterns already used by existing activities.
- Broadcast a categorization refresh event after mutations (example type: `categorization_update`).
- Broadcast payload should contain refresh context (`activity_id`) and avoid leaking private ballot contents.

## API Surface (Current)

- Base path: `/api/meetings/{meeting_id}/categorization`
- Read:
  - `GET /state?activity_id=...`
  - `GET /ballot?activity_id=...` (parallel mode participant ballot view)
  - `GET /disputed?activity_id=...` (facilitator, parallel mode)
- Facilitator-live mutations:
  - `POST /buckets`
  - `PATCH /buckets/{category_id}`
  - `DELETE /buckets/{category_id}`
  - `POST /buckets/reorder`
  - `POST /assignments`
- Parallel mutations:
  - `POST /ballot/assignments`
  - `POST /ballot/submit`
  - `POST /ballot/unsubmit`
  - `POST /reveal`
  - `POST /final-assignments`
- Lock:
  - `POST /lock`
  - Once locked, mutation endpoints return conflict/forbidden responses.

## Lock / Finalize

- Facilitator can lock/finalize activity.
- Lock prevents further category edits, item moves, and ballot edits/submissions.
- Finalization emits output bundle including:
  - categories and final assignments
  - finalization metadata (mode, thresholds, timestamp, facilitator id, counts)
  - optional tallies/ballots audit layer (privacy-aware)

## Data Hygiene Requirements

- Reset stale state on reseed/reuse of `activity_id` (same principle as voting reset helper).
- Ensure no stale bundle/assignment/ballot leakage across reused activity IDs.
- Preserve upstream provenance and add derived fields in namespaced metadata only.

## Required Test Coverage (Minimum)

- Manager state transitions and invariants (`UNSORTED`, CRUD/reorder, move semantics)
- Transfer parity and metadata retention (including comments-in-parentheses)
- RBAC and scoped participant enforcement
- Websocket update signaling on mutations
- Lock/finalize behavior and output bundle schema correctness
- Regression test for stale-state reset when reusing `activity_id`
