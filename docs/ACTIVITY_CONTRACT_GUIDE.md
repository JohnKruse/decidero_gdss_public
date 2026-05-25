# Activity Contract Guide

This guide explains how to implement activities that satisfy
`docs/ACTIVITY_CONTRACT_SPEC.md`. The SPEC is normative; this guide is the
practical checklist.

## Who Should Read This

- Developers creating a brand-new activity type.
- Maintainers changing activity lifecycle, transfer, or autosave behavior.
- Reviewers validating compatibility and regression risk before merge.

## Fast Path

1. Implement `ActivityPlugin` from `app/plugins/base.py`.
2. Define a stable manifest with a unique lowercase `tool_type`.
3. Fill out collaboration metadata, ThinkLet tags, and reliability policy.
4. Implement lifecycle methods:
   - `open_activity(context, input_bundle)`
   - `close_activity(context)`
   - optional `snapshot_activity(context)`
5. Preserve transfer provenance and metadata from input to output items.
6. Keep emitted IDs deterministic and scoped to the current `activity_id`.
7. Run the contract matrix before merging.

## Core Interfaces

- Normative contract: `docs/ACTIVITY_CONTRACT_SPEC.md`
- Base plugin interface: `app/plugins/base.py`
- Plugin context helpers: `app/plugins/context.py`
- Registry and loading:
  - `app/plugins/registry.py`
  - `app/plugins/loader.py`
- Input-seeding pipeline: `app/services/activity_pipeline.py`
- Activity catalog metadata for UI/API: `app/services/activity_catalog.py`
- JSON Schemas:
  - `docs/schemas/activity_manifest.schema.json`
  - `docs/schemas/bundle_payload.schema.json`
  - `docs/schemas/transfer_metadata.schema.json`

## Lifecycle Notes

### `open_activity(context, input_bundle)`

Use `input_bundle` to seed runnable activity state. Repeated calls should not
duplicate state; see the SPEC's DP3 invariant.

### `snapshot_activity(context)`

Return a bundle-like payload to enable autosave. Return `None` to disable
autosave for the plugin.

### `close_activity(context)`

Finalize transfer-compatible output through `ActivityContext` or
`ActivityBundleManager`.

## ActivityContext Methods

- `load_input_bundle()`
- `load_draft_bundle()`
- `save_draft_bundle(items, metadata=None)`
- `finalize_output_bundle(items, metadata=None)`

## Registration and Discovery

1. Add plugin code in built-ins or drop-ins:
   - built-ins are loaded from `app/plugins/builtin/*.py`
   - drop-ins are loaded from `./plugins` or `DECIDERO_PLUGIN_DIR`
2. Export one of:
   - `PLUGIN`
   - `PLUGINS`
   - `get_plugin()`
3. Confirm discovery in `GET /api/meetings/modules`.
4. Confirm manifest validation passes at registration.

## Reliability Policy

Declare action-specific reliability policy in the manifest when an operation
needs custom retry/backoff settings. The server normalizes the declaration and
publishes `write_default` in the module catalog; clients apply the policy
through `runReliableWriteAction`.

## Verify

Run the narrow matrix for new or changed activity-contract work:

```bash
python3 -m pytest app/tests/test_activity_plugins.py -q
python3 -m pytest app/tests/test_transfer_metadata.py -q
python3 -m pytest app/tests/test_transfer_transforms.py -q
```

For categorization contract changes:

```bash
python3 -m pytest app/tests/test_categorization_contract.py -q
python3 -m pytest app/tests/test_categorization_api.py -q
```

## Related Docs

- `docs/ACTIVITY_CONTRACT_SPEC.md`
- `docs/PLUGIN_DEV_GUIDE.md`
- `docs/TRANSFER_METADATA.md`
- `docs/CATEGORIZATION_CONTRACT.md`
- `docs/CATEGORIZATION_ACTIVITY_SPEC.md`
