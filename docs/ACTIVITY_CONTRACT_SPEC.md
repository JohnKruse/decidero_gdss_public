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
metadata, and reconciled against the ThinkLet audit document introduced in
Phase 1 Step 4.

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
| DP2 | Portable bundle shape with provenance and Phase 3 iteration slot | `app/tests/test_activity_plugins.py::test_bundle_payload_schema_accepts_provenance_and_iteration_extension`; `app/tests/test_activity_plugins.py::test_activity_bundle_manager_roundtrip`; `app/tests/test_transfer_metadata.py::test_transfer_metadata_schema_conformance_for_normalized_payload` |
| DP3 | Idempotent `open_activity` under restart | `app/tests/test_activity_plugins.py::test_brainstorming_open_activity_is_idempotent`; `app/tests/test_activity_plugins.py::test_voting_open_activity_is_idempotent`; `app/tests/test_activity_plugins.py::test_rank_order_voting_open_activity_is_idempotent`; `app/tests/test_activity_plugins.py::test_categorization_open_activity_is_idempotent` |
| DP4 | Manifest-declared, server-normalized reliability policy | `app/tests/test_activity_plugins.py::test_activity_catalog_includes_core_tools`; `app/tests/test_activity_plugins.py::test_reliability_policy_normalisation_applies_safe_defaults` |
| DP5 | ThinkLet claims are structured and auditable | `app/tests/test_activity_plugins.py::test_builtin_activity_manifests_conform_to_schema`; Phase 1 Step 4 will add `docs/THINKLET_AUDIT.md` conformance coverage |
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
- `docs/CATEGORIZATION_CONTRACT.md` - categorization-specific contract.
