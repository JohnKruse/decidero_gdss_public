# Activity Contract Guide

This is the canonical implementation contract for creating reliable new Decidero activities.

## Who Should Read This

- Developers creating a brand-new activity type.
- Maintainers changing activity lifecycle, transfer, or autosave behavior.
- Reviewers validating compatibility and regression risk before merge.

## Human Overview

If you are new to Decidero activity development, here is the big picture in plain terms:

- An activity is one phase of a meeting (for example brainstorming, voting, or categorization).
- Each activity receives ideas from a previous phase, works on them, and emits results for the next phase.
- The "contract" is the shared structure that keeps this handoff reliable so activities can be swapped, extended, or added without breaking the meeting flow.

Think of each activity as a "tool head" in a pipeline:

1. It starts with input from upstream.
2. It may autosave work-in-progress while running.
3. It publishes final output when stopped.

If your new activity follows this contract, it behaves predictably with existing transfer, autosave, and meeting controls.

## Fast Path

### Actions

1. Implement `ActivityPlugin` in a plugin module.
2. Define a stable `manifest` with unique `tool_type`.
3. Implement lifecycle methods:
   - `open_activity(context, input_bundle)`
   - `close_activity(context)`
   - optional `snapshot_activity(context)`
4. Preserve transfer provenance and metadata from input to output items.
5. Keep all emitted IDs deterministic and scoped to the current `activity_id`.
6. Run contract and integration tests before merging.

### Verify

```bash
python3 -m pytest app/tests/test_activity_plugins.py -q
python3 -m pytest app/tests/test_transfer_metadata.py -q
python3 -m pytest app/tests/test_transfer_transforms.py -q
```

## Core Interfaces

- Base plugin interface: `app/plugins/base.py`
- Plugin context helpers: `app/plugins/context.py`
- Registry and loading:
  - `app/plugins/registry.py`
  - `app/plugins/loader.py`
- Input-seeding pipeline: `app/services/activity_pipeline.py`
- Activity catalog metadata for UI/API: `app/services/activity_catalog.py`

## Required Invariants

> Explanation: These are compatibility requirements, not style preferences.

1. `tool_type` must be unique, lowercase-normalizable, and stable over time.
2. Bundle contract must stay compatible:
   - `input` consumed at activity start
   - `draft` used for autosave/recovery
   - `output` finalized on activity close
3. Transfer provenance must be preserved:
   - keep `item.metadata`
   - keep `item.source`
   - do not strip metadata based on UI-only include/exclude toggles
4. Plugin behavior must be idempotent across restarts:
   - avoid duplicating seeded state on repeated `open_activity`
   - avoid stale draft/output contamination when reseeding
5. Output should be portable to downstream activities through standard bundle shape:
   - `items: []`
   - optional `metadata: {}`

## Interface Lifecycle

### `open_activity(context, input_bundle)`

- Runs when a meeting activity is started.
- Use `input_bundle` to seed state.
- Use `ActivityContext` helper methods for bundle IO.

### `snapshot_activity(context)` (optional)

- If this returns a bundle-like payload, autosave can persist `draft` bundles.
- Return `None` to disable autosave for this plugin.

### `close_activity(context)`

- Runs when the activity is stopped.
- Must emit transfer-compatible output via finalized bundle payloads.

## ActivityContext Methods

- `load_input_bundle()`
- `load_draft_bundle()`
- `save_draft_bundle(items, metadata=None)`
- `finalize_output_bundle(items, metadata=None)`

## Registration and Discovery

### Actions

1. Add plugin in built-ins or drop-ins:
   - built-ins are loaded from `app/plugins/builtin/*.py`
   - drop-ins are loaded from `./plugins` or `DECIDERO_PLUGIN_DIR`
2. Export one of:
   - `PLUGIN`
   - `PLUGINS`
   - `get_plugin()`
3. Confirm discovery in module catalog:
   - `GET /api/meetings/modules`

### Verify

1. New `tool_type` appears in module catalog with `label`, `description`, `default_config`, `stem`.
2. Creating an agenda item with that `tool_type` starts/stops cleanly.

## Contract Test Matrix

Run the narrow matrix for new/changed activities:

```bash
python3 -m pytest app/tests/test_activity_plugins.py -q
python3 -m pytest app/tests/test_transfer_comment_format_parity.py -q
python3 -m pytest app/tests/test_transfer_api.py -q
```

For categorization contract changes:

```bash
python3 -m pytest app/tests/test_categorization_contract.py -q
python3 -m pytest app/tests/test_categorization_api.py -q
```

## Related Specs

- `docs/PLUGIN_DEV_GUIDE.md`
- `docs/TRANSFER_METADATA.md`
- `docs/CATEGORIZATION_CONTRACT.md`
- `docs/CATEGORIZATION_ACTIVITY_SPEC.md`
