# Plugin Developer Guide

This guide explains how to build in-process activity plugins for Decidero GDSS, how idea bundles flow between activities, and how autosave/crash recovery works.

## Core Concepts

### Activities
Activities are agenda items in a meeting (brainstorming, voting, curation, or custom). Each activity is defined by a `tool_type` and configuration.

### Idea Bundles (STDIN/STDOUT)
Activities communicate through **bundles**:
- **input** bundle: the items this activity consumes
- **draft** bundle: autosaved work-in-progress
- **output** bundle: final, immutable snapshot emitted when the activity stops

Bundles are stored in the `activity_bundles` table and identified by `bundle_id`. Bundles are JSON payloads containing `items` and optional `metadata`.

#### Metadata Retention Policy
Transfer payload metadata is always retained as a persistent audit trail. Any include/exclude controls apply only to per-activity display (UI) and must not remove metadata from transfer payloads. The `include_comments` toggle is content-level and only affects whether comment items are included.

### Snapshot Lifecycle
- On **start**, the system can seed the activity with the previous activity's output bundle (input bundle).
- During **run**, plugins can autosave draft bundles.
- On **stop**, plugins should finalize an output bundle.

## Plugin Structure

### Drop-in Folder
Plugins can be placed in the repository `./plugins` folder or any directory defined by the `DECIDERO_PLUGIN_DIR` environment variable. Each `.py` file can export:
- `PLUGIN` (single instance)
- `PLUGINS` (list of instances)
- or a `get_plugin()` function returning an instance

### Base Interface
Plugins implement the `ActivityPlugin` interface (see `app/plugins/base.py`):

- `manifest`: metadata describing the activity
- `open_activity(context, input_bundle)`
- `snapshot_activity(context)` (optional)
- `close_activity(context)`
- `get_autosave_seconds(config)` (provided by base)

### Manifest Fields
Minimal manifest:
```
ActivityPluginManifest(
    tool_type="curation",
    label="Idea Curation",
    description="Review and edit ideas before moving on.",
    default_config={"autosave_seconds": 10},
)
```

`autosave_seconds` is clamped to 5–300 seconds.

## Activity Context API
Plugins receive an `ActivityContext` with DB access and helper methods:

- `load_input_bundle()`
- `load_draft_bundle()`
- `save_draft_bundle(items, metadata=None)`
- `finalize_output_bundle(items, metadata=None)`

See `app/plugins/context.py`.

## Bundle Payload Format
Each `items` entry should be JSON-serializable and commonly includes:
```
{
  "id": 123,
  "content": "Idea text",
  "submitted_name": "Pat",
  "parent_id": null,
  "metadata": {"votes": 5},
  "source": {"meeting_id": "M-1", "activity_id": "M-1-BRAIN-0001"}
}
```

Plugins can add custom fields inside `metadata`.

## Autosave and Crash Recovery
Autosave runs only if `snapshot_activity()` returns a bundle-like payload.
- Start: autosave loop begins when the activity starts.
- Pause/Stop: autosave loop is stopped.
- Restart: draft bundle can be loaded for recovery.

The autosave runner is implemented in `app/plugins/autosave.py`.

## Built-in Examples

### Brainstorming
- Stores each idea in the database as it is submitted.
- On stop, emits an output bundle with all ideas.
- On autosave, emits a draft bundle of current ideas.

### Voting
- Uses input bundle items to seed voting options (if options are not already set).
- On stop/autosave, emits a bundle of options with vote totals.

### Categorization
- Seeds items from input bundle while preserving `metadata` and `source`.
- Supports `FACILITATOR_LIVE` and `PARALLEL_BALLOT` modes.
- Uses an implicit `UNSORTED` bucket and supports lock/finalize semantics.
- On stop, emits output items with `metadata.categorization` plus bundle metadata:
  - `categories`
  - `finalization_metadata`
  - `agreement_metrics` (parallel mode)
  - `final_assignments`

### Curation
- Designed to edit bundle items with facilitator-only endpoints.
- Drafts are saved via API and autosave, output bundle is finalized on stop.

## Curation API Endpoints
Curation endpoints are facilitator-only and live at:

- `GET /api/meetings/{meeting_id}/curation/bundles?activity_id=...`
- `PUT /api/meetings/{meeting_id}/curation/draft?activity_id=...`
- `POST /api/meetings/{meeting_id}/curation/draft/reset?activity_id=...`

These are meant to power a lightweight editing UI for curated idea lists.

## Writing a New Plugin (Checklist)
1. Create a `.py` file in `./plugins`.
2. Define a class implementing `ActivityPlugin`.
3. Fill out `manifest` (tool_type must be unique).
4. Implement `open_activity` and `close_activity`.
5. (Optional) Implement `snapshot_activity` for autosave.
6. Export `PLUGIN = YourPlugin()`.

## Testing
You can add unit tests under `app/tests` and use pytest:
```
python3 -m pytest app/tests/test_activity_plugins.py -q
```

## Notes on Trust and Safety
Plugins run in-process with full access to application code, the DB, and server resources. Treat drop-in plugins as trusted code.
