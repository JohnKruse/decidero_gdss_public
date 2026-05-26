# Activity Contract Specification

Tangerine Larynx Phase 1 normative specification for Decidero activity plugins,
portable activity bundles, transfer metadata, and reliability policy.

This document is normative. Implementation guidance lives in
`docs/ACTIVITY_CONTRACT_GUIDE.md`.

## Schema Authority

The authoritative JSON Schemas are:

- `docs/schemas/activity_manifest.schema.json`
- `docs/schemas/bundle_payload.schema.json`
- `docs/schemas/transfer_metadata.schema.json`

Runtime validation helpers live in `app/services/contract_schemas.py`.

## Design Principles

### DP1 - Stable Manifest Identity

Every plugin declares a stable `ActivityPluginManifest` with a unique,
lowercase-normalizable `tool_type`, display metadata, collaboration metadata,
and a server-readable reliability policy. The manifest is validated before
registration by `app/plugins/registry.py`.

### DP2 - Portable Bundle Shape

Activities exchange JSON payloads through `input`, `draft`, and `output`
bundles. Portable bundle payloads contain `items` and `metadata`; item payloads
preserve `metadata` and `source` provenance so downstream tools can audit where
content originated. The bundle schema also reserves an `iteration` object for
Phase 3 without requiring Phase 1 consumers to understand it.

### DP3 - Restart Idempotency

Calling `open_activity(context, input_bundle)` more than once with the same
input must not duplicate plugin-owned state. This protects browser refreshes,
activity restarts, and future engine replay. Built-in plugins must either make
`open_activity` a no-op when state is already seeded, or use unique persisted
keys so reseeding skips existing rows.

### DP4 - Reliability Policy as Manifest Contract Surface

Reliability policy is part of the plugin manifest, normalized by the server,
and applied by clients through the shared reliable-write wrapper. This is a
first-class contract surface, not an implementation detail.

This design is deliberately server-declared and client-applied. The classical
GDSS and ThinkLet literature names repeatable collaboration patterns and
facilitation moves, but it does not define a reusable machine-readable retry,
backoff, and idempotency policy that travels with a collaboration activity.
Decidero's manifest-declared policy fills that gap: activity authors publish
the write semantics once, the catalog normalizes a safe `write_default`, and
browser clients execute the same bounded retry behavior without custom logic per
tool. That makes DP4 reusable by future server-driven step kinds, including
engine steps that need the same "retry only under declared conditions" behavior
without inventing a parallel policy shape.

### DP5 - ThinkLet Claims Are Auditable

Manifest `thinklets` are claims about the collaboration pattern embodied by a
plugin. They must remain visible in the manifest, validated as structured
metadata, and reconciled against `docs/THINKLET_AUDIT.md`.

### DP6 - Config Validation Disposition Is Explicit

`ActivityPlugin.validate_config()` must have an explicit framework disposition:
it is a plugin-controlled extension point. The base implementation is a
passthrough, and current framework lifecycle wiring does not invoke it
automatically before `open_activity`. Plugins that require strict validation
must call their validators from lifecycle methods or from the router/service
that owns the relevant configuration write.

## DP-to-Test Mapping

| DP | Invariant | Executable witness |
| --- | --- | --- |
| DP1 | Stable manifest identity and startup validation | `app/tests/test_activity_plugins.py::test_builtin_activity_manifests_conform_to_schema`; `app/tests/test_activity_plugins.py::test_activity_registry_rejects_invalid_manifest` |
| DP2 | Portable bundle shape with provenance and Phase 3 iteration slot | `app/tests/test_activity_plugins.py::test_bundle_payload_schema_accepts_provenance_and_iteration_extension`; `app/tests/test_activity_plugins.py::test_activity_bundle_manager_roundtrip`; `app/tests/test_activity_plugins.py::test_activity_bundle_iteration_storage_is_round_discriminated`; `app/tests/test_activity_plugins.py::test_activity_bundle_legacy_latest_path_is_deterministic`; `app/tests/test_transfer_metadata.py::test_transfer_metadata_schema_conformance_for_normalized_payload` |
| DP3 | Idempotent `open_activity` under restart | `app/tests/test_activity_plugins.py::test_brainstorming_open_activity_is_idempotent`; `app/tests/test_activity_plugins.py::test_voting_open_activity_is_idempotent`; `app/tests/test_activity_plugins.py::test_rank_order_voting_open_activity_is_idempotent`; `app/tests/test_activity_plugins.py::test_categorization_open_activity_is_idempotent` |
| DP4 | Manifest-declared, server-normalized reliability policy | `app/tests/test_activity_plugins.py::test_activity_catalog_includes_core_tools`; `app/tests/test_activity_plugins.py::test_reliability_policy_normalisation_applies_safe_defaults` |
| DP5 | ThinkLet claims are structured and auditable | `docs/THINKLET_AUDIT.md`; `app/tests/test_activity_plugins.py::test_builtin_manifest_thinklets_match_audit_document`; `app/tests/test_activity_plugins.py::test_builtin_activity_manifests_conform_to_schema` |
| DP6 | Config validation disposition is explicit and tested | `app/tests/test_activity_plugins.py::test_validate_config_is_documented_plugin_controlled_passthrough` |

## Normative Invariants

1. Plugin `tool_type` values are stable, unique, and lowercase snake_case.
2. Plugin manifests conform to `docs/schemas/activity_manifest.schema.json`
   before registration.
3. Activity bundle payloads conform to `docs/schemas/bundle_payload.schema.json`
   when emitted by contract-aware tests or future engine code.
4. Transfer metadata conforms to `docs/schemas/transfer_metadata.schema.json`.
5. Output items preserve incoming `metadata` and `source` provenance unless a
   specific plugin documents a narrower transformation.
6. Reliability policy is declared on the manifest and normalized by
   `app/services/activity_catalog.py` before clients consume it.
7. Transfer source/count methods fail soft by returning empty results or zero
   counts rather than breaking meeting or agenda payloads.

## Related Implementer Docs

- `docs/ACTIVITY_CONTRACT_GUIDE.md` - how to implement this specification.
- `docs/PLUGIN_DEV_GUIDE.md` - plugin structure, examples, and testing.
- `docs/TRANSFER_METADATA.md` - transfer metadata prose companion.
- `docs/THINKLET_AUDIT.md` - audited built-in plugin ThinkLet claims.
- `docs/CATEGORIZATION_CONTRACT.md` - categorization-specific contract.

## Agenda Strategy Seam

Smug Otter Phase 2 introduces `app/services/agenda_strategy.py` as the
extension point for agenda interpretation. Existing meetings bind
deterministically to `LinearAgendaStrategy`, which preserves order-index agenda
semantics while creating a single consultation surface for future orchestration
strategies. In Phase 2 Step 2, `LinearAgendaStrategy` is the canonical reference
implementation: it resolves prior activities by direct `order_index` adjacency,
returns the canonical agenda in `order_index` order, treats the agenda as
complete only when the highest-order activity has an `output` bundle, performs
no progression on close, and delegates mid-meeting activity creation to
`MeetingManager.add_agenda_activity`.

Phase 2 Step 3 routes existing behavioral consumers through that seam. The
activity-pipeline prior lookup, meeting export and agenda API reads, realtime
initial agenda snapshots, transfer activity resolution, and
`MeetingManager.list_agenda` all consult the meeting's bound `AgendaStrategy`.
Storage-layer resequencing and activity-id lookup mechanics may still touch
`agenda_activities` directly when they are not interpreting agenda topology.

Phase 2 Step 4 pins mid-meeting creation safety for `LinearAgendaStrategy`.
Router-driven `POST /api/meetings/{id}/agenda`, strategy-driven
`create_activity`, and manager-direct `add_agenda_activity` calls all share the
same identifier minting and resequence path, and router-driven creation emits
the existing `agenda_update` realtime envelope with the resequenced agenda.

## Iteration Storage Model

Convergent Yak Phase 3 stores iteration state on `ActivityBundle` rows rather
than minting round-scoped `AgendaActivity` rows. Each bundle has an optional
`logical_step_id` and a non-negative `round_index` that defaults to `0` for
all Phase 2 and legacy behavior. Portable payloads mirror the same values in
the schema-blessed `iteration` object from `bundle_payload.schema.json`.

This model keeps operator-authored agenda IDs and `LinearAgendaStrategy`
unchanged: iteration is an orchestration concern, not a general agenda concern.
The existing `(meeting_id, activity_id, kind)` retrieval path remains
deterministic by returning the highest `round_index` and then the newest row,
while callers that need a specific round can pass `round_index` and
`logical_step_id` to `ActivityBundleManager.get_latest_bundle`. Round-N bundles
therefore never overwrite round-(N-1) bundles, and the complete round history is
available through `ActivityBundleManager.list_bundles_for_step`.
