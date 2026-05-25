# PHASE 3 — Iteration Substrate

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Discovery reference:** [plans/00_DISCOVERY.md](../00_DISCOVERY.md)
**Elaboration reference:** [plans/02_ORCHESTRATION_ENGINE.md](../02_ORCHESTRATION_ENGINE.md)

**Phase objective:** Build the typed primitives that make non-linear flow representable in the data model and the service layer. Phase 3 resolves three breaking points enumerated in [plans/00_DISCOVERY.md §16](../00_DISCOVERY.md): the linear "previous activity" assumption (BP-1), the missing iteration discriminator on `ActivityBundle` (BP-3), and the absence of a server-side execution analogue to `runReliableWriteAction` (BP-7). When this phase clears, the substrate exists for an orchestration engine to repeatedly invoke the same logical step across rounds, transform bundles between iterations, evaluate convergence, and survive malformed AI responses without a parallel retry framework.

This is the architecturally heaviest phase of the master plan and the only phase that changes data-model semantics on the activity-bundle row. Decisions made here bind every later phase.

## Phase Canary

**Convergent Yak**

Use this exact two-word canary in Phase 3 notes, commit messages, module docstrings introduced by this phase, schema header lines, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — Resolve the Iteration Storage Model
Decide and implement how the system represents multiple iterations of a logically-recurring step. The master plan permits three families of answer: iteration-scoped `AgendaActivity` rows (one row per round, IDs derived from a stem plus a round counter), an explicit iteration-discriminator column on `ActivityBundle`, or any equivalent mechanism. The decision must be defended in writing in `docs/ACTIVITY_CONTRACT_SPEC.md` and must satisfy two non-negotiable invariants: (a) Phase 1's `bundle_payload.schema.json` continues to validate every bundle written by Phase 3, with the discriminator either absent (Phase 2 behavior) or carried in a schema-blessed slot; and (b) the existing `(activity_id, kind)` access pattern surfaced in [plans/00_DISCOVERY.md §6.1](../00_DISCOVERY.md) yields deterministic, non-shadowing results for every round of every step.

If the chosen design mints iteration-scoped activity rows, the ID-minting path through `_next_activity_identifier` ([plans/00_DISCOVERY.md §3.5](../00_DISCOVERY.md)) must extend to derive round-scoped identifiers without colliding with operator-authored agendas; the `AgendaActivity` uniqueness constraints at [`app/models/meeting.py:123-126`](../../app/models/meeting.py) must remain satisfied. If the chosen design adds a discriminator column, the schema change is introduced here, with the consequence that deployment to existing instances is a manual schema-change step (Alembic is out of scope per [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md) Scope Boundary). Either way, `LinearAgendaStrategy` (authored in Phase 2) must continue to operate without referencing iteration concepts; iteration is a property of orchestrations, not of agendas in general.

This step does not yet introduce transforms, predicates, or the new prior-activity resolution; it only puts the data substrate in place so the following steps have a stable target.

Conclude this step by:
- Implementing the core logic as the chosen iteration storage model (model change, ID-minting extension, or both), with the design rationale recorded in `docs/ACTIVITY_CONTRACT_SPEC.md` and tagged with the `Convergent Yak` canary.
- Creating or updating the relevant pytest file by extending `app/tests/test_activity_plugins.py` with assertions that round-N bundles never overwrite round-(N-1) bundles, that the existing `(activity_id, kind)` retrieval path returns the expected round, and that the `LinearAgendaStrategy` parity tests from Phase 2 still pass under the new model; no new pytest module is warranted because plugin-lifecycle and bundle-pipeline coverage already lives here.
- Updating docstrings and documentation so `app/models/activity_bundle.py`, `app/data/meeting_manager.py` (specifically the ID-minting region), and `docs/ACTIVITY_CONTRACT_SPEC.md` each describe the iteration storage model and its invariants under the `Convergent Yak` canary.

### Step 2 — Replace the Linear "Previous Activity" Assumption
Refactor the prior-activity hook on `AgendaStrategy` so callers identify which prior bundle they want by explicit reference (donor activity_id plus optional iteration discriminator, or a named handle the orchestration document will later supply) rather than by `order_index` adjacency. `LinearAgendaStrategy` continues to honor `order_index` adjacency under the hood for its own implementation of the hook, so linear meetings behave exactly as they do at the end of Phase 2; but the hook's signature is now permissive enough that `OrchestrationEngineStrategy` will be able to point at "the brainstorm step that ran before this iterate block" or "round 2 of the rank-order-voting step" without lying about meaning.

The `_find_previous_activity` semantics that Phase 2 channeled through the seam are split: the call shape used by `activity_pipeline.ensure_input_bundle` becomes an explicit "resolve donor for this consumer" request, and the strategy answers it. The result is that BP-1 from [plans/00_DISCOVERY.md §16](../00_DISCOVERY.md) is no longer a load-bearing linear assumption inside the pipeline — it is a property of the linear strategy, which the engine strategy will not inherit.

Conclude this step by:
- Implementing the core logic as the refactored hook signature on `AgendaStrategy`, the updated `LinearAgendaStrategy` implementation that preserves observable behavior, and the updated `activity_pipeline.ensure_input_bundle` call shape, all tagged with `Convergent Yak` comments at the refactor sites.
- Creating or updating the relevant pytest file by extending `app/tests/test_activity_plugins.py` and `app/tests/test_meeting_manager.py` so the prior-activity parity tests authored in Phase 2 are reframed in terms of the new signature and the iteration storage model from Step 1; do not introduce a new pytest module, as both suites already own the relevant coverage.
- Updating docstrings and documentation so `app/services/agenda_strategy.py`, `app/services/activity_pipeline.py`, and `docs/ACTIVITY_CONTRACT_SPEC.md` each describe the new prior-activity resolution semantics and cite BP-1 as resolved under `Convergent Yak`.

### Step 3 — Author `BundleTransform` and `ConvergencePredicate` Interfaces
Author two new service modules: `app/services/bundle_transforms.py` containing the `BundleTransform` ABC plus a name-keyed registry, and `app/services/convergence_predicates.py` containing the `ConvergencePredicate` ABC plus a name-keyed registry. Each registry parallels the existing plugin-registry pattern at [`app/plugins/registry.py:11-48`](../../app/plugins/registry.py) so that orchestration documents can later reference transforms and predicates by string name and resolve them deterministically.

`BundleTransform` is a typed function `(input_bundle, transform_config) → output_bundle` that preserves provenance per the rules enforced by Phase 1's `bundle_payload.schema.json`. Ship two reference implementations: `IdentityBundleTransform` (returns its input unchanged, used as the default inter-step bridge and as a no-op control in tests) and `DelphiStatisticalAggregationTransform` (consumes a rank-order-voting `output` bundle and emits an `input`-ready bundle annotated with per-item median, IQR, dispersion, and per-participant outlier flags computed against the IQR; the simplest defensible aggregation per the Phase 3 risk discussion in [plans/02_ORCHESTRATION_ENGINE.md §3](../02_ORCHESTRATION_ENGINE.md)).

`ConvergencePredicate` is a typed function `(bundle_history, predicate_config) → bool` that examines the iteration storage model from Step 1. Ship two reference implementations: `FixedNPredicate` (fires after a configured number of rounds, the trivial guard) and `IQRStabilityPredicate` (fires when the median IQR across items changes by less than a configured threshold across two consecutive rounds, the substantive Delphi convergence signal).

Both interfaces are authored as Python classes registered by name, with no DSL or expression evaluation — per DP8 in [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md) and the Scope Boundary there.

Conclude this step by:
- Implementing the core logic as the two new modules, the two ABCs, the two registries, and four reference implementations, with the `Convergent Yak` canary in every module docstring.
- Creating or updating the relevant pytest file as `app/tests/test_bundle_transforms.py` and `app/tests/test_convergence_predicates.py`; these new modules are warranted because no existing suite has the right scope — `test_activity_plugins.py` is about plugin lifecycle, `test_transfer_transforms.py` is about the unrelated UI-side transfer transforms, and the registries are first-class concepts that deserve focused coverage.
- Updating docstrings and documentation so `docs/ACTIVITY_CONTRACT_SPEC.md` gains a section describing the two interfaces and links to the canonical implementations, and so the DP-to-test mapping table is extended to cite the new test modules where they enforce design-principle invariants relevant to the orchestration grammar.

### Step 4 — Author the Server-Side Reliability Execution Analogue
Implement a server-side execution path that mirrors the semantics of the client-side `runReliableWriteAction` at [`app/static/js/reliable_actions.js`](../../app/static/js/reliable_actions.js): exponential backoff with jitter, retry only on configured retryable conditions, idempotency-keyed re-execution, and structured failure when the retry budget is exhausted. The path consumes the manifest-declared `reliability_policy` already normalized by `activity_catalog.normalise_reliability_policy` at [`app/services/activity_catalog.py:62-80`](../../app/services/activity_catalog.py); it must not duplicate the normalization logic.

The new path must be general enough that the `ai-decision` step kind authored in Phase 4 will reuse it without modification when validating malformed LLM responses against an output schema — the canonical use case is "AI provider returned something that does not parse against the declared output schema; retry with the same idempotency key up to the policy's max-retries, then surface a structured failure". The retry-on-schema-violation condition is itself a configured retryable condition expressible in the existing policy shape.

The path remains independent of any specific plugin or AI provider; it is service-layer infrastructure, not a plugin-internal helper. No existing built-in plugin is modified by this step.

Conclude this step by:
- Implementing the core logic as the new server-side reliability execution module (named to match the existing `reliable_actions.js` mirror — e.g., `app/services/reliable_writes.py` — with the `Convergent Yak` canary in the module docstring) and any service-layer wiring needed to make it callable by future step kinds.
- Creating or updating the relevant pytest file by extending `app/tests/test_reliability_rehearsal.py` if its existing shape accommodates the new coverage; otherwise authoring a focused module (such as `app/tests/test_reliable_writes.py`) and documenting in the new module's header why the existing rehearsal suite was not a fit. Bias toward the extension path per the Phase 3 doctrine of minimizing new test modules.
- Updating docstrings and documentation so `docs/ACTIVITY_CONTRACT_SPEC.md` records the server-side reliability path as the DP4 execution analogue, and so the activity-catalog and the new module each cross-reference each other and the client-side `runReliableWriteAction` for symmetry.

### Step 5 — Substrate Integration Smoke
Without yet introducing the orchestration engine or any step kind, demonstrate that the four primitives composed in Steps 1 through 4 fit together. Author a substrate-level integration test that performs the following sequence end-to-end against a synthetic meeting: open an activity, close it with an `output` bundle, apply `DelphiStatisticalAggregationTransform` to that bundle, materialize the transformed bundle as the `input` for a second iteration of the same logical step (using the iteration storage model from Step 1 and the new prior-activity resolution from Step 2), close the second iteration, and evaluate `IQRStabilityPredicate` against the two-round history. The test must also exercise the server-side reliability path from Step 4 by simulating one retryable failure during the transform-then-materialize step and confirming a successful idempotent retry. This smoke test is the load-bearing evidence that Phase 3 ships a usable substrate; without it, Phase 4 inherits unknowns it cannot economically diagnose.

Conclude this step by:
- Implementing the core logic as the integration smoke test, which lives inside the substrate it exercises — by extending `app/tests/test_activity_plugins.py` (which already owns the activity-pipeline and bundle-roundtrip coverage), so no new pytest module is introduced.
- Creating or updating the relevant pytest file is the extension named above; the test docstring carries the `Convergent Yak` canary and explicitly names BP-1, BP-3, and BP-7 as the breaking points whose resolution it validates.
- Updating docstrings and documentation so `docs/ACTIVITY_CONTRACT_SPEC.md` gains a closing "Phase 3 substrate composition" subsection that summarizes how transforms, predicates, the iteration storage model, and server-side reliability compose, with the smoke test cited as the executable witness.

## Phase Exit Criteria

Phase 3 clears only when the following command reaches `[100%]` and finishes without failures:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_activity_plugins.py app/tests/test_meeting_manager.py app/tests/test_meeting_state.py app/tests/test_api_meetings.py app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_bundle_transforms.py app/tests/test_convergence_predicates.py app/tests/test_reliability_rehearsal.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_rank_order_voting_api.py app/tests/test_categorization_api.py app/tests/test_frontend_smoke.py -v
```

(If Step 4's reliability coverage is housed in a focused new module such as `app/tests/test_reliable_writes.py` rather than in `test_reliability_rehearsal.py`, append that module to the command before clearing the phase.)

Passing this command means:

- The iteration storage model from Step 1 is in place, documented in `docs/ACTIVITY_CONTRACT_SPEC.md`, and exercised so that round-N bundles never overwrite round-(N-1) bundles for any built-in plugin.
- `AgendaStrategy`'s prior-activity hook accepts explicit donor references; `LinearAgendaStrategy` continues to honor `order_index` adjacency internally; Phase 2's parity tests pass under the new signature.
- `app/services/bundle_transforms.py` and `app/services/convergence_predicates.py` exist, are registered by name, and ship `IdentityBundleTransform`, `DelphiStatisticalAggregationTransform`, `FixedNPredicate`, and `IQRStabilityPredicate` with focused test coverage in their own modules.
- The server-side reliability execution analogue authored in Step 4 consumes normalized `reliability_policy` declarations, performs idempotency-keyed retry with exponential backoff under configured conditions, and is reusable by Phase 4's `ai-decision` step kind.
- The Step 5 substrate integration smoke test passes, demonstrating end-to-end composition of all four primitives and explicitly validating the resolution of BP-1, BP-3, and BP-7.
- No test that previously passed regresses, and no test docstring, module docstring, or schema header introduced under Phase 3 omits the `Convergent Yak` canary where the step requirements call for it.

## Scope Boundary

This phase covers only the substrate that makes iteration representable; it does not introduce the engine. The following items are explicitly deferred to later phases of [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md):

- The orchestration-document JSON Schema, `OrchestrationEngineStrategy`, and the `activity` / `facilitator-decision` / `ai-decision` step kinds — Phase 4.
- Engine-driven realtime broadcasts when iteration rounds mint new agenda rows, and the facilitator-decision UI surface — Phase 5.
- `orchestrations/delphi.json`, the end-to-end Delphi run, and `docs/DELPHI_VALIDATION.md` — Phase 6.
- Any parallel-branch, sub-orchestration, variable-binding, expression-evaluation, event-handler, or compensation/rollback primitive — out of scope for the entire master plan per its Scope Boundary.
