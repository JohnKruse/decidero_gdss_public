# Categorization Activity Spec

This document defines the current production contract for the `categorization` activity.

## Scope

- Canonical tool type: `categorization`
- Runtime mode: `FACILITATOR_LIVE`
- Participant behavior: view-only
- Facilitator/admin behavior: all categorization mutations

## Data And Transfer Contract

- Input bundle uses activity pipeline `kind=input`.
- Output bundle uses activity pipeline `kind=output` on finalize/stop.
- Draft persistence may use `kind=draft`.
- Payload format remains `items: []` with optional `metadata: {}`.
- Source `metadata` and `source` provenance fields are preserved through categorization and transfer.

## Core Rules

- `UNSORTED` bucket is always present.
- Bucket/item/assignment IDs must remain stable within `(meeting_id, activity_id)`.
- Bucket deletion moves contained items to `UNSORTED`.
- Re-seeding/reusing an `activity_id` must clear stale categorization state.

## RBAC And Participant Scope

- Meeting access and participant scope checks follow existing meeting-state rules.
- Facilitator/admin can mutate buckets, items, and assignments.
- Participants can read activity state but cannot mutate categorization data.
- Out-of-scope participants receive `403`.

## Realtime Contract

- Mutations broadcast a `categorization_update` websocket event with `activity_id` refresh context.
- Broadcast payloads must not leak private user-only internals.

## API Surface

Base path: `/api/meetings/{meeting_id}/categorization`

Supported read endpoints:

- `GET /state?activity_id=...`

Supported facilitator mutation endpoints:

- `POST /buckets`
- `PATCH /buckets/{category_id}`
- `DELETE /buckets/{category_id}`
- `POST /buckets/reorder`
- `POST /items`
- `PATCH /items/{item_key}`
- `DELETE /items/{item_key}`
- `POST /assignments`
- `POST /lock`

Deprecated legacy parallel endpoints:

- `GET /ballot`
- `POST /ballot/assignments`
- `POST /ballot/submit`
- `POST /ballot/unsubmit`
- `POST /reveal`
- `GET /disputed`
- `POST /final-assignments`

Deprecation behavior:

- Legacy parallel endpoints return `410 Gone` with detail code `parallel_workflow_removed`.

## Lock / Finalization

- Facilitator can lock activity via `POST /lock`.
- Lock metadata captures facilitator action and finalization context.
- Output artifacts remain transfer-compatible.

## Required Regression Coverage

- Facilitator-only mutation enforcement for buckets/items/assignments.
- Participant read-only behavior and scope enforcement.
- Deprecated parallel endpoint responses (`410` + deprecation code).
- Lock/finalization behavior and output bundle integrity.
- Transfer metadata/provenance retention.
