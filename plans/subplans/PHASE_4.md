# PHASE 4 — Engine and Step Kinds

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Discovery reference:** [plans/00_DISCOVERY.md](../00_DISCOVERY.md)
**Elaboration reference:** [plans/02_ORCHESTRATION_ENGINE.md](../02_ORCHESTRATION_ENGINE.md)

**Phase objective:** Turn the substrate produced in Phases 1 through 3 into a runnable orchestration engine. Phase 4 authors the JSON document grammar that describes collaboration processes, the validator that enforces it on load, the `OrchestrationEngineStrategy` that interprets it, and the three step kinds the master plan commits to: `activity`, `facilitator-decision`, and `ai-decision`. The `iterate` control-flow primitive becomes a working composition over Phase 3's `BundleTransform` and `ConvergencePredicate` registries. When this phase clears, a trivial multi-step orchestration runs end-to-end through the engine without modifying any existing built-in plugin — the executable witness for DP9.

## Phase Canary

**Insolent Metronome**

Use this exact two-word canary in Phase 4 notes, commit messages, module docstrings introduced by this phase, schema header lines, orchestration-document fixtures, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — [DONE] Author the Orchestration Document Schema and Loader
Author `docs/schemas/orchestration.schema.json` covering the closed control-flow grammar (`sequence`, `iterate`) and the open-but-disciplined step-kind vocabulary (`activity`, `facilitator-decision`, `ai-decision`) committed to by the master plan. The schema must also reserve the `conditional` control-flow primitive as a defined-but-deferred shape so a future minor release can ship it without breaking documents authored under this phase; deferral is explicit in the schema description, not a silent omission. Top-level orchestration metadata is required: `name`, `version`, `author`, `citation`, plus a `metadata` object carrying `thinklets`, `collaboration_patterns`, `deliverables`, `group_size_range`, and `typical_duration_minutes` (mirroring the manifest field shapes already validated by Phase 1's `activity_manifest.schema.json`). The schema header must carry the `Insolent Metronome` canary line.

Author a corresponding loader in `app/services/orchestration_loader.py` (name suggestive only; the implementer may pick any colocation that does not violate the existing `app/services/` conventions) that validates every orchestration document on load and emits structured error reporting comparable to `AgendaValidationResult` already produced by [`app/services/agenda_validator.py:41-47`](../../app/services/agenda_validator.py). The loader is the only path through which the engine in Step 2 ingests documents; ad-hoc parsing in tests or routers is not permitted. Round-tripping a fixture document through the loader must produce a typed in-memory representation (small AST or equivalent) that the engine walks step-by-step.

The orchestration document schema does not collide with the existing meeting-designer agenda grammar enforced by `agenda_validator.py` ([plans/00_DISCOVERY.md §11](../00_DISCOVERY.md)); the two coexist, and the loader is responsible only for orchestration documents.

Conclude this step by:
- Implementing the core logic as the new schema file, the loader module, and the typed in-memory representation, with the `Insolent Metronome` canary in the schema header and the loader's module docstring.
- Creating or updating the relevant pytest file by extending `app/tests/test_agenda_validator.py` if its shape accommodates orchestration-document validation cases; otherwise authoring a focused module (such as `app/tests/test_orchestration_schema.py`) and documenting in the new module's header why the existing validator suite was not a fit. Bias toward the extension path.
- Updating docstrings and documentation so `docs/ACTIVITY_CONTRACT_SPEC.md` gains a section pointing at the orchestration document grammar, and so the new loader module cross-references both the schema file and the agenda validator (to make the coexistence clear).

Technical deviations logged:
- Authored a focused test module `app/tests/test_orchestration_schema.py` rather than extending `app/tests/test_agenda_validator.py`. The agenda validator is coupled to user-configured meeting designer schemas, whereas this step requires loading and AST parsing of process orchestration grammar, justifying an isolated test file.
- Used custom Python types and validation helpers instead of `jsonschema` library, matching the project's zero-dependency runtime strategy established in Phase 1 manifest validation.

### Step 2 — [DONE] Implement the `OrchestrationEngineStrategy` Skeleton and the `activity` Step Kind
Author `OrchestrationEngineStrategy` inside `app/services/agenda_strategy.py` (alongside `LinearAgendaStrategy` from Phase 2). The strategy implements the `AgendaStrategy` interface from Phase 2 — and only that interface — by interpreting a loaded orchestration document via a step-pointer / iteration-counter / bundle-history state machine. Each tick examines the current step, instantiates the next activity if the step kind is `activity` (or pauses, in step kinds added by later steps in this phase), and advances the pointer when the underlying activity closes. The strategy uses Phase 3's prior-activity hook signature (explicit donor reference, not `order_index` adjacency) and the iteration storage model from Phase 3 Step 1 whenever it materializes a new activity row.

Ship the `activity` step kind in the same step. Its configuration is `tool_type`, `config` (passed verbatim to the plugin's `validate_config()` per Phase 1's DP6 disposition), an optional named `transform_input` resolved against Phase 3's `BundleTransform` registry, and a display `title`. The `activity` step is the only one that drives existing built-in plugins, and it must do so via the plugin ABC at [`app/plugins/base.py:38-81`](../../app/plugins/base.py) without altering any plugin manifest or lifecycle method beyond what Phase 1 authorized. DP9 holds.

Demonstrate the skeleton plus the `activity` step kind by running a trivial two-step orchestration end-to-end: a `sequence` containing two `activity` steps (brainstorm → vote), produced from a fixture document, validated by the Step 1 loader, executed by `OrchestrationEngineStrategy` against an in-memory meeting, producing the expected sequence of `input` / `output` bundles with provenance intact and Phase 1's bundle schema continuing to validate every bundle written.

Conclude this step by:
- Implementing the core logic as the `OrchestrationEngineStrategy` class, the `activity` step kind handler, the supporting state-machine scaffolding, and the brainstorm→vote fixture document carrying the `Insolent Metronome` canary in its `metadata.notes` slot.
- Creating or updating the relevant pytest file by authoring a focused module `app/tests/test_orchestration_engine.py`; this new module is warranted because no existing suite owns engine concerns — `test_meeting_manager.py` handles linear-agenda data shape, `test_meeting_state.py` handles the in-memory state singleton, and neither is the right home for engine-document interpretation.
- Updating docstrings and documentation so `app/services/agenda_strategy.py` records both `LinearAgendaStrategy` and `OrchestrationEngineStrategy` as the two reference implementations of the seam, so `docs/ACTIVITY_CONTRACT_SPEC.md` gains an "Engine" section describing the interpreter loop and the `activity` step kind, and so the brainstorm→vote fixture's location is cited from the spec.

### Step 3 — [DONE] Implement the `iterate` Step Kind
Add `iterate` to `OrchestrationEngineStrategy`. Configuration: child steps (a sequence executed each round), a max-rounds bound, a named `ConvergencePredicate` (with config) resolved against Phase 3's predicate registry, and a named inter-round `BundleTransform` (with config) resolved against Phase 3's transform registry. Each iteration runs the child steps once, applies the transform to the round's output, evaluates the predicate against accumulated bundle history, and either loops to the next round or exits. The iteration storage model from Phase 3 Step 1 governs how round-N bundles are kept distinct from round-(N-1) bundles; the engine does not invent a parallel mechanism.

Surface the iteration counter through the engine's prior-activity hook so transforms and predicates can address round-specific donors by explicit reference per Phase 3 Step 2. The `max-rounds` bound is enforced as a hard ceiling regardless of predicate state, so a degenerate predicate cannot run the engine forever.

Conclude this step by:
- Implementing the core logic as the `iterate` step kind handler inside `OrchestrationEngineStrategy`, with the canary `Insolent Metronome` in the step-kind dispatcher's comment for `iterate` and in any new fixture documents authored to exercise it.
- Creating or updating the relevant pytest file by extending `app/tests/test_orchestration_engine.py` with iterate-specific coverage: a fixed-rounds run that exits on `FixedNPredicate`, a stability-driven run that exits on `IQRStabilityPredicate`, and a degenerate run that hits `max-rounds` because the predicate never fires.
- Updating docstrings and documentation so the spec's Engine section gains an `iterate` subsection that cites the two Phase 3 registries and identifies the resolution path from a document name string to a registered Python class.

Technical deviations logged:
- Replaced the eager `_flatten_plan` helper with a lazy `_PlanWalker` state machine because iterate rounds depend on runtime predicate evaluation against accumulated bundle history; an eager flatten cannot know how many rounds will run. Round 0 leaves are still emitted at `__init__` time so the existing `strategy.plan` shape is preserved for non-iterate documents.
- `iteration_metadata_for` was added to expose `(logical_step_id, round_index)` to callers (tests and bundle-writers) so they can pass the Phase 3 iteration storage discriminators to `ActivityBundleManager.finalize_output_bundle`. The strategy does not write bundles itself — that responsibility stays with the bundle manager — so callers must opt in. Metadata is recorded only for activities materialized inside an iterate, preserving the non-iterate donor-bundle lookup path used by the brainstorm→vote integration test.
- Updated `app/tests/test_meeting_manager.py::test_phase4_documentation_tracks_completed_facilitator_model_collapse` to tolerate the `[DONE]` marker added by the implementation workflow to step headers. Without this change the test failed pre-existingly after Step 2 was marked [DONE].

### Step 4 — Implement the `facilitator-decision` Step Kind
Add `facilitator-decision` to `OrchestrationEngineStrategy`. Configuration: a `prompt` (the question posed to the facilitator), a typed list of `options` (the discrete responses the facilitator may choose from), and `context_bundle_keys` (which prior bundles to surface alongside the prompt). When the engine ticks onto a `facilitator-decision` step it pauses — the strategy's `next_activity` hook returns no new activity and the engine waits in a paused state that is observable to callers. On resumption (driven by an externally-supplied facilitator response that names one of the typed options), the chosen option is captured as a typed bundle item in the bundle stream and the engine advances. The bundle item must carry provenance that survives Phase 1's `bundle_payload.schema.json`.

The UI surface that lets a facilitator actually respond is explicitly out of scope here and belongs to Phase 5; this step exposes the resumption entry point (a service-layer call that accepts a meeting reference, the engine's current step pointer, and the chosen option) and tests the entry point directly. Until Phase 5 ships, the only consumer is the test suite.

If a `facilitator-decision` step is reached but the orchestration document never specified valid options (or all options are exhausted by prior selections in the same step instance), the engine surfaces a structured error rather than silently advancing.

Conclude this step by:
- Implementing the core logic as the `facilitator-decision` step kind handler, the pause-state representation inside the engine's state machine, and the resumption entry-point function, all tagged with the `Insolent Metronome` canary at the dispatch site and in the resumption function's docstring.
- Creating or updating the relevant pytest file by extending `app/tests/test_orchestration_engine.py` with assertions that the engine pauses correctly, that the resumption entry-point captures the chosen option into the bundle stream with valid provenance, and that an invalid option name yields a structured error.
- Updating docstrings and documentation so the spec's Engine section gains a `facilitator-decision` subsection that explicitly notes Phase 5 owns the UI surface, and so the resumption entry point's docstring cites the integration test as its executable contract.

### Step 5 — Implement the `ai-decision` Step Kind
Add `ai-decision` to `OrchestrationEngineStrategy`. Configuration: a `prompt_template`, `context_bundle_keys` (which prior bundles to render into the prompt), an `output_schema` (the JSON Schema the AI response must validate against), and a `review_required` boolean. The engine renders the prompt with the named bundle context, calls the configured AI provider via the existing `app/services/ai_provider.py` (no new provider integration is authored in this phase), parses the response, validates it against the declared `output_schema`, and captures the validated result as a typed bundle item in the bundle stream.

Schema-validation failures are retried via the server-side reliability execution analogue authored in Phase 3 Step 4 — the orchestration document's effective `reliability_policy` declaration treats "schema validation failure" as a retryable condition and uses an idempotency key derived from the engine's step pointer plus round index. This is the canonical reuse case the Phase 3 reliability path was built for; it must work without modifying that path.

When `review_required` is `true`, the validated AI output is held pending the next `facilitator-decision` step's approval — the engine does not advance the pointer beyond the `ai-decision` step until the immediately-following `facilitator-decision` (which the orchestration document is responsible for authoring) resolves. If `review_required` is `true` and no `facilitator-decision` follows in the document, the loader from Step 1 must surface a structured validation error at document-load time rather than at runtime.

Conclude this step by:
- Implementing the core logic as the `ai-decision` step kind handler, the prompt-rendering helper that consumes `context_bundle_keys`, the schema-validation invocation, and the `review_required` composition glue, all tagged with the `Insolent Metronome` canary at the dispatch site.
- Creating or updating the relevant pytest file by extending `app/tests/test_orchestration_engine.py` with assertions that cover the happy path (valid response captured into the bundle stream), the schema-violation retry path (one retryable failure followed by success, demonstrating Phase 3 Step 4 reuse), the budget-exhaustion structured-failure path, and the `review_required` composition (engine holds the result pending the following `facilitator-decision`); also extend the Step 1 loader test coverage to confirm a document with `review_required: true` but no following `facilitator-decision` is rejected at load time.
- Updating docstrings and documentation so the spec's Engine section gains an `ai-decision` subsection that explicitly cites the Phase 3 reliability path as the retry substrate, names the `review_required` composition pattern as the recommended methodological response to AI unreliability, and cross-references `app/services/ai_provider.py` for the provider integration.

## Phase Exit Criteria

Phase 4 clears only when the following command reaches `[100%]` and finishes without failures:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_orchestration_engine.py app/tests/test_agenda_validator.py app/tests/test_bundle_transforms.py app/tests/test_convergence_predicates.py app/tests/test_reliability_rehearsal.py app/tests/test_activity_plugins.py app/tests/test_meeting_manager.py app/tests/test_meeting_state.py app/tests/test_api_meetings.py app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_rank_order_voting_api.py app/tests/test_categorization_api.py app/tests/test_ai_provider_config.py app/tests/test_frontend_smoke.py -v
```

(If Step 1's orchestration-document validator coverage is housed in a focused new module such as `app/tests/test_orchestration_schema.py` rather than appended to `test_agenda_validator.py`, append that module to the command before clearing the phase.)

Passing this command means:

- `docs/schemas/orchestration.schema.json` exists, covers `sequence`, `iterate`, `activity`, `facilitator-decision`, and `ai-decision`, reserves `conditional` as deferred, and is enforced on document load by the Step 1 loader with structured error reporting.
- `OrchestrationEngineStrategy` exists alongside `LinearAgendaStrategy` in `app/services/agenda_strategy.py` and implements the Phase 2 `AgendaStrategy` interface without adding any new public hook beyond what Phases 2 and 3 specified.
- The `activity`, `iterate`, `facilitator-decision`, and `ai-decision` step kinds are implemented; the trivial brainstorm→vote orchestration runs end-to-end and produces bundles that conform to Phase 1's `bundle_payload.schema.json`; the iterate step uses Phase 3's `BundleTransform` and `ConvergencePredicate` registries; the ai-decision step uses Phase 3's server-side reliability execution analogue.
- DP9 holds in practice: `app/plugins/base.py` is unchanged, every built-in plugin manifest is unchanged from its Phase 1 audited state, and the trivial demonstration plus every step-kind test passes without touching plugin internals.
- No test that previously passed regresses, and no test docstring, module docstring, schema header, or fixture introduced under Phase 4 omits the `Insolent Metronome` canary where the step requirements call for it.

## Scope Boundary

This phase covers only the engine, the loader, and the three master-plan-committed step kinds plus the `iterate` control-flow primitive. The following items are explicitly deferred to later phases of [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md):

- The `conditional` control-flow primitive — defined-but-deferred at the schema layer in this phase; runtime implementation is future work and may not ship at all, per the master plan and the `02_ORCHESTRATION_ENGINE.md` stretch-goal designation.
- The realtime broadcast envelope that informs connected clients when the engine mutates the agenda (creates iteration rounds, advances past a decision); the frontend cache-invalidation work; and the facilitator-decision UI surface that lets a facilitator actually respond from the dashboard — Phase 5.
- `orchestrations/delphi.json`, the end-to-end Delphi run with synthetic participants, the `IQR-stability`-driven convergence demonstration as a real method instantiation, and `docs/DELPHI_VALIDATION.md` — Phase 6.
- Empirical evaluation with real participant groups, additional step kinds beyond the three named here, parallel branches, sub-orchestration invocation, variable bindings, expression evaluation, event handlers, timers, and compensation/rollback — out of scope for the entire master plan per its Scope Boundary.
