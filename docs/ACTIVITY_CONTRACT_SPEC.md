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

Under Phase 3, this principle is extended to the server: [run_with_retry](file:///Users/john/Documents/Python/decidero_gdss_public/app/services/reliable_writes.py) provides the server-side execution analogue to `runReliableWriteAction`, enforcing the same normalized policies, jittered backoffs, and idempotency guarantees for server-driven actions (such as LLM calls).

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

### DP7-DP9 — Orchestration Principles (Authoritative in Master Plan)

DP7 (Collaboration Processes as Declarative, Composable Artifacts),
DP8 (Closed Control Flow, Open Step Vocabulary), and
DP9 (Method-Specific Concerns Do Not Belong in Activity Plugins) are
defined in [plans/02_ORCHESTRATION_ENGINE.md §1.2](../plans/02_ORCHESTRATION_ENGINE.md).
They govern the orchestration grammar and the engine's relationship to the
activity-plugin contract; this spec does not redefine them.

### DP10 - Composable Bundle Transforms

To support iterative collaboration (such as Delphi), bundle data is transformed between rounds using named `BundleTransform` implementations, which preserve item-level provenance.

### DP11 - Declarative Convergence Predicates

Instead of hardcoded exit conditions, iterative processes evaluate their history using named `ConvergencePredicate` implementations to determine convergence.

## DP-to-Test Mapping

| DP | Invariant | Executable witness |
| --- | --- | --- |
| DP1 | Stable manifest identity and startup validation | `app/tests/test_activity_plugins.py::test_builtin_activity_manifests_conform_to_schema`; `app/tests/test_activity_plugins.py::test_activity_registry_rejects_invalid_manifest` |
| DP2 | Portable bundle shape with provenance and Phase 3 iteration slot | `app/tests/test_activity_plugins.py::test_bundle_payload_schema_accepts_provenance_and_iteration_extension`; `app/tests/test_activity_plugins.py::test_activity_bundle_manager_roundtrip`; `app/tests/test_activity_plugins.py::test_activity_bundle_iteration_storage_is_round_discriminated`; `app/tests/test_activity_plugins.py::test_activity_bundle_legacy_latest_path_is_deterministic`; `app/tests/test_transfer_metadata.py::test_transfer_metadata_schema_conformance_for_normalized_payload` |
| DP3 | Idempotent `open_activity` under restart | `app/tests/test_activity_plugins.py::test_brainstorming_open_activity_is_idempotent`; `app/tests/test_activity_plugins.py::test_voting_open_activity_is_idempotent`; `app/tests/test_activity_plugins.py::test_rank_order_voting_open_activity_is_idempotent`; `app/tests/test_categorization_open_activity_is_idempotent` |
| DP4 | Manifest-declared, server-normalized reliability policy | `app/tests/test_activity_plugins.py::test_activity_catalog_includes_core_tools`; `app/tests/test_activity_plugins.py::test_reliability_policy_normalisation_applies_safe_defaults`; `app/tests/test_reliable_writes.py` |
| DP5 | ThinkLet claims are structured and auditable | `docs/THINKLET_AUDIT.md`; `app/tests/test_activity_plugins.py::test_builtin_manifest_thinklets_match_audit_document`; `app/tests/test_activity_plugins.py::test_builtin_activity_manifests_conform_to_schema` |
| DP6 | Config validation disposition is explicit and tested | `app/tests/test_activity_plugins.py::test_validate_config_is_documented_plugin_controlled_passthrough` |
| DP10 | Composable bundle transforms | `app/tests/test_bundle_transforms.py` |
| DP11 | Composable convergence predicates | `app/tests/test_convergence_predicates.py` |
| DP9 | Engine does not alter plugin manifests or lifecycle methods | `app/tests/test_orchestration_engine.py::test_engine_brainstorm_vote_end_to_end` |

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

Convergent Yak Phase 3 resolves BP-1 by changing the prior-activity hook from
"activity adjacency means previous bundle" to an explicit donor request. Callers
construct a `PriorActivityReference` with the consumer activity and, when known,
a donor `activity_id`, `logical_step_id`, `round_index`, or future document
handle. Strategies answer with a `PriorActivityResolution` that names the donor
activity and the optional iteration discriminator the bundle lookup must use.
`activity_pipeline.ensure_input_bundle` consumes that resolution directly, so
the pipeline no longer owns linear topology semantics. `LinearAgendaStrategy`
preserves observable Phase 2 behavior by resolving adjacency only when the
request omits an explicit donor activity; explicit donor requests pass through
with their round discriminator intact.

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

## Orchestration Substrate

### Bundle Transform Seam

`BundleTransform` is an abstract interface for data transformations between activity iterations.
The canonical implementations are:
- `IdentityBundleTransform` at [IdentityBundleTransform](file:///Users/john/Documents/Python/decidero_gdss_public/app/services/bundle_transforms.py): Returns the input bundle unchanged.
- `DelphiStatisticalAggregationTransform` at [DelphiStatisticalAggregationTransform](file:///Users/john/Documents/Python/decidero_gdss_public/app/services/bundle_transforms.py): Consumes rank-order-voting output bundles (including individual voter rankings in the bundle metadata) and computes item-level median, IQR, standard deviation, and participant outlier flags.

### Convergence Predicate Seam

`ConvergencePredicate` is an abstract interface that evaluates the iteration history to decide if execution should terminate.
The canonical implementations are:
- `FixedNPredicate` at [FixedNPredicate](file:///Users/john/Documents/Python/decidero_gdss_public/app/services/convergence_predicates.py): Fires after a set number of rounds.
- `IQRStabilityPredicate` at [IQRStabilityPredicate](file:///Users/john/Documents/Python/decidero_gdss_public/app/services/convergence_predicates.py): Fires when the change in median IQR across items between two consecutive rounds is less than or equal to a threshold.

### Phase 3 Substrate Composition

The four primitives composed in Phase 3—the iteration storage model, the prior activity resolution seam, named bundle transforms/convergence predicates, and server-side retry logic—are demonstrated to integrate seamlessly. 
The executable witness for this composition is the test `app/tests/test_activity_plugins.py::test_substrate_integration_smoke`, which runs an end-to-end Delphi iteration loop against simulated participants, validates data persistence and prior activity lookup, processes a statistical transform with outlier detection, applies a reliability retry, and evaluates convergence stability.

## Process Orchestration Document Grammar and Loader

### Orchestration Document Schema

The orchestration document grammar (governed by the Phase 4 `Insolent Metronome` canary) is formally specified at [orchestration.schema.json](file:///Users/john/Documents/Python/decidero_gdss_public/docs/schemas/orchestration.schema.json). It mandates:
- Top-level metadata describing the collaboration process.
- A sequential step list, where each step can represent a closed control-flow block (`sequence`, `iterate`, and reserved `conditional`) or a primitive step kind (`activity`, `facilitator-decision`, `ai-decision`).

### Loader and Parser

The process orchestration document loader at [orchestration_loader.py](file:///Users/john/Documents/Python/decidero_gdss_public/app/services/orchestration_loader.py) is the exclusive entry point for loading process configurations. It performs:
- Schema validation against all mandatory structure and type rules.
- Structural checking for review-required AI decision step pairing (requiring an immediately following facilitator approval step).
- AST construction returning typed in-memory representations (`SequenceStep`, `IterateStep`, `ActivityStep`, etc.) for engine execution.

### Forward Contracts for Engine Steps (Phase 4 Steps 4-5)

These contracts are recorded now so Phase 4 Steps 4 and 5 land against
explicit expectations rather than re-deriving them at implementation time.

**ai-decision retry contract.** Phase 4 Step 5 reuses `run_with_retry` from
[reliable_writes.py](file:///Users/john/Documents/Python/decidero_gdss_public/app/services/reliable_writes.py)
to retry malformed AI responses. The default `should_retry_result` and
`should_retry_exception` inspect HTTP-style status fields only and will not
treat schema-validation failures as retryable on their own. The `ai-decision`
step kind must therefore wire one of:

1. Raise a typed exception on schema-validation failure whose `status_code`
   attribute is listed in the effective policy's `retryable_statuses`
   (default-detected path), or
2. Pass a custom `should_retry_result` to `run_with_retry` that returns
   `True` when the parsed AI response does not validate against the
   declared `output_schema`.

The idempotency key for the retry must be derived deterministically from the
engine's step pointer plus the current iteration round so retries collapse
to the same logical write, per Phase 3 Step 4.

**facilitator-decision options shape.** The current schema and loader treat
`options` as a list of non-empty strings. Phase 4 Step 4 may need typed
options (label + value, or label + payload schema) once the facilitator UI
is wired in Phase 5. Any such widening must update both the JSON Schema
file and the loader (see the schema/loader correspondence test in
`app/tests/test_orchestration_schema.py`).

## Orchestration Engine

### Interpreter Loop

Phase 4 Step 2 (Insolent Metronome) delivers `OrchestrationEngineStrategy` in
`app/services/agenda_strategy.py`, alongside `LinearAgendaStrategy` as the
second reference implementation of the `AgendaStrategy` seam. Callers that
drive an orchestration document construct `OrchestrationEngineStrategy(document)`
directly; `get_agenda_strategy(meeting)` continues to return `LinearAgendaStrategy`
for all existing meetings.

The engine maintains a flattened **execution plan** — an ordered list of
`(logical_step_id, step)` pairs derived from the document's `steps` tree at
construction time. `SequenceStep` nodes are expanded in-place; leaf steps
(`ActivityStep`, and future `FacilitatorDecisionStep` / `AIDecisionStep`) become
plan entries. The step pointer is derived from the database rather than held in
memory: the number of materialized `AgendaActivity` rows for the meeting
determines the next step to execute, and the number of distinct activities with
an `output` bundle determines completion.

Each call to `create_activity` materializes the current plan step as an
`AgendaActivity` row. `on_activity_close` is a no-op; the pointer advances
automatically as output bundles are written. `is_complete` returns `True` when
the completed-activity count equals the plan length.

### `activity` Step Kind

The `activity` step kind carries:
- `tool_type` — lowercase snake_case, must be registered in the activity catalog.
- `title` — human-readable activity label passed verbatim to `AgendaActivity.title`.
- `config` — merged with the plugin's `default_config`; the merged result is
  passed through `plugin.validate_config()` per DP6 before the row is written.
- `transform_input` (optional) — reserved for Phase 4 Step 3's `iterate` kind.

No existing plugin manifest or lifecycle method is altered; DP9 holds.

### `iterate` Step Kind

The `iterate` step kind (Phase 4 Step 3, canary `Insolent Metronome`) loops a
child sequence of activity steps for up to `max_rounds` rounds. Each round runs
the child steps once; on round end the engine collects the last child
activity's output bundle, applies the named `BundleTransform`, appends the
transformed payload to a per-iterate `bundle_history`, and evaluates the named
`ConvergencePredicate`. If the predicate fires the loop exits; otherwise the
loop advances to the next round, bounded by `max_rounds` as a hard ceiling
enforced regardless of predicate state.

`BundleTransform` and `ConvergencePredicate` are resolved from string names
declared in the orchestration document against Phase 3's registries at
[`app/services/bundle_transforms.py`](../app/services/bundle_transforms.py)
(`get_bundle_transform_registry().get_transform(name)`) and
[`app/services/convergence_predicates.py`](../app/services/convergence_predicates.py)
(`get_convergence_predicate_registry().get_predicate(name)`). Unknown names
fall through to the identity case at the engine layer — round outputs pass
untransformed and the predicate never fires — so authors should rely on the
loader to reject unrecognized names at document-load time.

Round-N bundles are kept distinct from round-(N-1) bundles via the Phase 3
iteration storage model: each activity materialized inside an iterate is
tagged on the strategy with a stable `logical_step_id` (shared across rounds
for the same child position) and a `round_index` (0-based). Callers obtain
these values via `OrchestrationEngineStrategy.iteration_metadata_for(activity_id)`
and pass them to `ActivityBundleManager.finalize_output_bundle` so the bundle
row carries the iteration discriminator. `resolve_prior_activity` surfaces the
donor's `logical_step_id` and `round_index` on the resolution to satisfy the
Phase 3 explicit-donor-reference hook signature.

### `facilitator-decision` Step Kind

The `facilitator-decision` step kind (Phase 4 Step 4, canary `Insolent
Metronome`) pauses the engine until a facilitator selects one of a declared
list of typed options. Configuration: `prompt` (the question posed), `options`
(non-empty list of strings), and `context_bundle_keys` (which prior bundles
the UI should surface alongside the prompt — Phase 5 owns the rendering).

When `OrchestrationEngineStrategy.create_activity` ticks onto a
`facilitator-decision` step it materializes a placeholder `AgendaActivity`
with `tool_type="facilitator_decision"` (see
`OrchestrationEngineStrategy.FACILITATOR_DECISION_TOOL_TYPE`) and sets the
engine's pause state. Subsequent `create_activity` calls raise an
`HTTPException(409, ...)` until the pause is cleared. `pending_decision()`
returns the pause descriptor (or `None`); `is_paused()` is its boolean form.

Resumption goes through `resume_with_facilitator_decision(meeting,
chosen_option, ...)`. The chosen option is captured as a single typed bundle
item with provenance that satisfies
[`bundle_payload.schema.json`](schemas/bundle_payload.schema.json):
`metadata.facilitator_decision` records the prompt, options, the chosen
value, and the optional actor user; `source` carries the meeting / activity /
tool-type triple. Invalid options raise `HTTPException(400, ...)` and leave
the engine paused so the caller can retry. Calling resume when no decision is
pending also raises a structured error.

**UI is out of scope here.** Phase 5 owns the dashboard surface that lets a
facilitator actually respond; Phase 4 Step 4 only ships the service-layer
resumption entry point. The executable contract for that entry point is the
`test_facilitator_decision_*` family in
[`app/tests/test_orchestration_engine.py`](../app/tests/test_orchestration_engine.py).

### Prior-Activity Resolution

`OrchestrationEngineStrategy.resolve_prior_activity` uses plan order rather
than `order_index` adjacency. When no explicit `donor_activity_id` is supplied,
the engine walks the materialized agenda in `order_index` order and returns the
immediately preceding activity. Explicit donor references pass through with
their `logical_step_id` and `round_index` intact, as with `LinearAgendaStrategy`.

### Reference Fixture

The two-step brainstorm → vote fixture used as the executable witness for Phase
4 Step 2 lives at `docs/fixtures/brainstorm_vote.orchestration.json` and carries
the `Insolent Metronome` canary in its `metadata.notes` slot. The end-to-end
test at `app/tests/test_orchestration_engine.py::test_engine_brainstorm_vote_end_to_end`
validates that the loader, engine strategy, both plugins, and Phase 1's bundle
schema all compose correctly across a live in-memory meeting.


