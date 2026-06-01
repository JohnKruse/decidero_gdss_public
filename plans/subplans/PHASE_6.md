# PHASE 6 — Delphi Instantiation and Evaluation

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Discovery reference:** [plans/00_DISCOVERY.md](../00_DISCOVERY.md)
**Elaboration reference:** [plans/02_ORCHESTRATION_ENGINE.md](../02_ORCHESTRATION_ENGINE.md)

**Phase objective:** Prove that the orchestration engine and its primitives compose into a real collaboration-engineering method by authoring Delphi as a JSON document, running it end-to-end with synthetic participants, and producing a paper-ready validation artifact. Phase 6 is the executable witness for DP9 on the central evaluation case: instantiating Delphi must not require modifying `app/plugins/base.py`, any built-in plugin's lifecycle method, or any built-in plugin's manifest beyond what Phase 1 audited. When this phase clears, the master plan's architectural claim — that collaboration processes can be expressed as declarative, composable JSON artifacts over a minimal grammar — is demonstrated against the method that motivated the design.

**Paper-scope boundary:** The Phase 6 evaluation is deliberately about the packaged-method path. It does not claim to evaluate the full space of live facilitator improvisation, nor does it require solving arbitrary hybrid insertion into an active orchestration. Conventional facilitator-driven meetings remain supported by the Phase 2 linear strategy and are protected by Phase 5's manual-facilitation invariant; the HICSS evidence focuses on whether Delphi can be represented, executed, and validated as a reusable declarative process over the existing plugin substrate.

## Phase Canary

**Oracular Quokka**

Use this exact two-word canary in Phase 6 notes, commit messages, the `metadata.notes` slot of every orchestration document authored in this phase, fixture and synthetic-participant docstrings, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — [DONE] Author `orchestrations/delphi.json`
Author a complete Delphi orchestration document at `orchestrations/delphi.json` composed of: a round-one brainstorming step (instantiated through Phase 4's `activity` step kind against the existing brainstorming plugin), followed by an `iterate` block containing a rank-order-voting step whose `transform_input` resolves to Phase 3's `DelphiStatisticalAggregationTransform`, with an `IQRStabilityPredicate` (also from Phase 3) and a `max_rounds` bound of four. The document optionally includes an `ai-decision` step that summarizes qualitative justifications between rounds with `review_required: true`, followed by a `facilitator-decision` step that surfaces the AI's proposed summary alongside a typed continue / stop / re-run option per the master plan; if shipped, this composition is the canonical demonstration of the `ai-decision`/`facilitator-decision` pairing introduced in Phase 4. A second optional `facilitator-decision` step at the close of each round lets a facilitator override the predicate's automatic continue / stop decision; if shipped, it is documented as the human-override pattern that complements the algorithmic convergence signal.

Top-level metadata is fully populated: `name` (e.g., "Classical Delphi"), `version`, `author` (the implementing maintainer), `citation` (Linstone & Turoff, *The Delphi Method*, with publisher and year), and the `metadata` object carrying `thinklets` composed (the underlying plugin's tags, surfaced at the orchestration level), `collaboration_patterns` covered (Evaluate, Build Consensus, optionally Clarify), `deliverables` produced (a converged ranked list with per-item dispersion statistics and per-participant outlier flags), `group_size_range`, and `typical_duration_minutes`. The `metadata.notes` slot carries the `Oracular Quokka` canary.

The document must validate cleanly against Phase 4's `docs/schemas/orchestration.schema.json` and must load through the Phase 4 loader without warnings. If the loader surfaces a validation error, the fix is to either correct the document or, if the document is correct and the schema is too restrictive, surface a defect against Phase 4 — Phase 6 does not loosen Phase 4's schema unilaterally.

Conclude this step by:
- Implementing the core logic as the new `orchestrations/delphi.json` document carrying the `Oracular Quokka` canary in its `metadata.notes` slot.
- Creating or updating the relevant pytest file by extending `app/tests/test_orchestration_engine.py` with assertions that the shipped document validates against the orchestration schema, loads through the Phase 4 loader without warnings, and resolves every named transform and predicate to a real registered Python class; no new pytest module is required, as the engine-integration suite already owns document-load concerns.
- Updating docstrings and documentation so [docs/ACTIVITY_CONTRACT_SPEC.md](../../docs/ACTIVITY_CONTRACT_SPEC.md) gains a "Reference orchestrations" subsection citing `orchestrations/delphi.json` as the canonical Delphi instantiation, and so the document itself includes a top-of-file comment block summarizing its construction and its source citation.

Technical deviations:
- `orchestrations/delphi.json` remains strict JSON, so it cannot include a portable top-of-file comment block. The construction summary, citation, and `Oracular Quokka` canary are recorded in `metadata.notes`, and `docs/ACTIVITY_CONTRACT_SPEC.md` documents this placement in the "Reference Orchestrations" subsection.
- `docs/schemas/orchestration.schema.json` was updated to admit the already-loader-supported `metadata.notes` field so schema validation and the Phase 6 canary requirement agree.

### Step 2 — [DONE] End-to-End Delphi Run with Synthetic Participants
Author an end-to-end test that runs `orchestrations/delphi.json` against an in-memory meeting populated with a synthetic participant cohort whose responses are deterministic across rounds in a way that exercises the `IQRStabilityPredicate` honestly. Round one is brainstorming — synthetic participants submit a fixed set of ideas drawn from a Phase 6 fixture. Subsequent rounds are rank-order voting, with the synthetic cohort's ranking distribution authored to deliberately exercise three regimes: (a) a high-IQR opening round where the predicate must not fire; (b) one or more intermediate rounds where IQR contracts but not enough to fire; (c) a terminal round where IQR contraction crosses the configured threshold and the predicate fires. The test must run the orchestration through at least two full rounds and must assert:

- The round-2 `input` bundle for the rank-order-voting step contains the round-1 aggregate statistics (per-item median, IQR, dispersion) produced by `DelphiStatisticalAggregationTransform`.
- Participants whose round-1 ranking falls outside the round-1 IQR are flagged in the per-participant outlier annotations, and the specific participants flagged match the cohort fixture's authored expectations.
- `IQRStabilityPredicate` does not fire under the IQR conditions defined for regimes (a) and (b), and fires under the condition defined for regime (c).
- The `max_rounds` bound is enforced when the test is parameterized to a cohort whose IQR never stabilizes; the engine exits at the bound regardless of predicate state, matching the Phase 4 hard-ceiling behavior.
- Every bundle written through the run validates against Phase 1's `bundle_payload.schema.json`, and every broadcast envelope emitted by the engine matches the shape pinned in Phase 5 Step 1.
- DP9 holds: the test runs without `app/plugins/base.py` having been modified beyond its Phase 1 state and without any built-in plugin's lifecycle method or manifest having been touched in this phase.

If the orchestration document includes the optional `ai-decision` summary step, the test exercises it under the same fixture by stubbing the AI provider (per the Phase 4 patterns) to return a schema-valid summary; the `review_required` composition is exercised through the Phase 5 resumption entry point with a facilitator-driven approval that resumes the engine.

Conclude this step by:
- Implementing the core logic as the new synthetic-cohort fixtures (under `app/tests/fixtures/` or the existing fixture conventions) and the end-to-end test inside `app/tests/test_orchestration_engine.py`, both carrying the `Oracular Quokka` canary in their docstrings.
- Creating or updating the relevant pytest file is the extension to `app/tests/test_orchestration_engine.py` named above; this is the natural home because it already owns engine-driven E2E coverage from Phase 5 Step 4, and a new module would fracture the engine-integration surface.
- Updating docstrings and documentation so the spec records the synthetic-cohort fixture's location and its three IQR regimes, and so each fixture file carries a header citing the regime it exercises.

Technical deviations:
- The engine previously evaluated the iterate walker before materializing an already-planned round, which could collect an empty round output. `OrchestrationEngineStrategy.create_activity` now advances the walker only after the materialized agenda count catches up with the known plan.
- The Phase 4 iterate implementation transformed round outputs in memory for predicate evaluation but did not persist transformed feedback as the next round's `input` bundle. Step 2 persists that transformed bundle when an iterate child declares `transform_input`, so the round-2 rank-order activity carries the round-1 Delphi statistics required by the validation.
- The max-rounds parameterization uses the shipped Delphi document with an impossible predicate threshold (`-1.0`) so the test isolates the `max_rounds` hard ceiling from the normal stable-cohort convergence path while still running the same synthetic fixture through the real plugins.

### Step 3 — [DONE] Author `docs/DELPHI_VALIDATION.md`
Capture the synthetic-evaluation result in `docs/DELPHI_VALIDATION.md` in a form suitable for inclusion in the conference paper. The document must contain: a description of the synthetic-cohort fixture and the three IQR regimes from Step 2, a presentation of the round-by-round aggregate statistics observed under each regime (per-item median, IQR, dispersion), a summary of the predicate-firing decisions and their reasoning, an explicit confirmation that DP9 held during the run with the file paths that *did not* change as evidence, and an analytical discussion of what the run demonstrates and what it does not (notably, that this is an analytical / synthetic validation in the Hevner sense, not a field study — empirical evaluation with real participant groups is future work per the master plan's Scope Boundary). The discussion must avoid claiming methodological coverage the test does not provide; the document is paper-ready precisely because it is honest about its evaluation modality.

The document also names, in a closing subsection, the breaking points whose resolution it indirectly attests to: BP-1 (linear "previous activity") because Delphi requires round-to-round prior-bundle resolution; BP-3 (iteration discriminator on bundles) because Delphi keeps multiple rounds of the same logical step distinct; BP-7 (server-side reliability) because the optional `ai-decision` summary exercises it; BP-5 and BP-10 (realtime + frontend coherence) because the run executes through Phase 5's broadcast and UI surfaces. The document does not re-derive these resolutions — it cites the respective phase tests as the executable witnesses.

The validation document must also state what the run does not demonstrate: it is not a field study, it is not a claim that every facilitator improvisation pattern has been modeled, and it does not settle how ad hoc activities inserted into a running orchestration should affect bundle history or convergence. Those tuning decisions are future product work informed by facilitator feedback after the paper package is complete.

The header carries the `Oracular Quokka` canary.

Conclude this step by:
- Implementing the core logic as the new `docs/DELPHI_VALIDATION.md` document with the structure described above and the canary in its header.
- Creating or updating the relevant pytest file by extending `app/tests/test_orchestration_engine.py` with a small assertion that confirms `docs/DELPHI_VALIDATION.md` exists, carries the canary, and references the Step 2 test by function name; this keeps the writeup and the witness from drifting apart. No new pytest module is required.
- Updating docstrings and documentation so `docs/INDEX.md` lists `DELPHI_VALIDATION.md` under a "Reference evaluations" or equivalent heading, and so `docs/ACTIVITY_CONTRACT_SPEC.md` cross-references the validation document from its "Reference orchestrations" subsection introduced in Step 1.

Technical deviations:
- None. The validation writeup remains an analytical synthetic evaluation artifact and explicitly avoids claiming field-study coverage.

### Step 4 — [DONE] Generalization Decision: Estimate-Talk-Estimate or Formal Deferral
Decide and execute one of the two terminal paths the master plan permits for the generalization-beyond-Delphi success criterion: either ship `orchestrations/estimate_talk_estimate.json` as a second reference orchestration that composes the same Phase 3 / Phase 4 primitives in a different shape (initial individual estimation, group discussion through a brainstorming step, revised estimation through rank-order voting, no formal aggregation transform required — the same `iterate` primitive composes it cleanly), with a parallel-shape end-to-end test asserting that the engine drives the document without modifying any plugin; or formally defer ETE to post-master-plan future work, recording the deferral with reasoning in `docs/DELPHI_VALIDATION.md` and stating explicitly that the engine's generalization claim rests on Delphi alone for this submission cycle.

If the ETE path is chosen, the document is authored at `orchestrations/estimate_talk_estimate.json`, validates against the Phase 4 schema and loader, and exercises the iterate primitive without depending on `DelphiStatisticalAggregationTransform` or `IQRStabilityPredicate` — `IdentityBundleTransform` and `FixedNPredicate` from Phase 3 are the minimum-viable resolution. The accompanying test extension in `app/tests/test_orchestration_engine.py` asserts that the second document loads, runs through two rounds, and produces bundles conformant with Phase 1's bundle schema; the assertion volume is intentionally lighter than Delphi's, since the engine-integration claims have already been established and ETE is here to demonstrate composition rather than to re-validate the substrate.

If the deferral path is chosen, the deferral subsection in `docs/DELPHI_VALIDATION.md` explicitly names ETE, NGT, and any other collaboration-engineering method the maintainer considered for inclusion, and explains why Delphi alone is a defensible generalization basis for the conference submission. The deferral is itself a master-plan-permitted outcome and clears the phase as cleanly as the ship path; the master plan's Phase 6 success gate names both terminal paths.

The choice between ship and defer is made on engineering grounds — schedule, fixture-authoring cost, and whether the test extension will surface anything the Delphi run did not. There is no preferred path at the plan layer.

Conclude this step by:
- Implementing the core logic as either the new `orchestrations/estimate_talk_estimate.json` document plus the accompanying test extension, or the deferral subsection in `docs/DELPHI_VALIDATION.md`; whichever artifact is produced carries the `Oracular Quokka` canary.
- Creating or updating the relevant pytest file by extending `app/tests/test_orchestration_engine.py` with the ETE assertions if the ship path is chosen, or with a small assertion that confirms the deferral subsection exists in `docs/DELPHI_VALIDATION.md` if the deferral path is chosen.
- Updating docstrings and documentation so the spec's "Reference orchestrations" subsection lists whichever artifact was produced (the second orchestration document on the ship path, or the deferral subsection's location on the deferral path), and so the closing chapter of `docs/DELPHI_VALIDATION.md` reflects the chosen outcome.

Technical deviations:
- The master-plan-permitted deferral path was chosen. `docs/DELPHI_VALIDATION.md` now records that Estimate-Talk-Estimate, Nominal Group Technique, and additional packaged methods are deferred to post-master-plan work, while the conference-submission generalization claim rests on the Delphi witness alone.
- No `orchestrations/estimate_talk_estimate.json` document was authored because the ETE path was not selected. The deferral is covered by `app/tests/test_orchestration_engine.py::test_phase6_generalization_deferral_is_documented` and cross-referenced from `docs/ACTIVITY_CONTRACT_SPEC.md`.

## Phase Exit Criteria

Phase 6 clears only when the following command reaches `[100%]` and finishes without failures:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_orchestration_engine.py app/tests/test_agenda_validator.py app/tests/test_bundle_transforms.py app/tests/test_convergence_predicates.py app/tests/test_reliability_rehearsal.py app/tests/test_activity_plugins.py app/tests/test_meeting_state.py app/tests/test_meeting_manager.py app/tests/test_api_meetings.py app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_frontend_smoke.py app/tests/test_pages.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_rank_order_voting_api.py app/tests/test_categorization_api.py app/tests/test_ai_provider_config.py -v
```

Passing this command means:

- `orchestrations/delphi.json` exists, validates against Phase 4's orchestration schema, and loads through the Phase 4 loader without warnings; every named transform and predicate resolves to a registered Python class.
- The end-to-end Delphi run with synthetic participants passes, exercises the three IQR regimes authored in the fixture, demonstrates that `DelphiStatisticalAggregationTransform` flags the expected outlier participants, demonstrates correct firing and non-firing of `IQRStabilityPredicate`, and enforces the `max_rounds` hard ceiling.
- Every bundle written during the Delphi run validates against `bundle_payload.schema.json`; every realtime broadcast emitted matches the Phase 5 envelope shape.
- DP9 holds in practice for the central evaluation case: `app/plugins/base.py` is unchanged from its Phase 1 state, no built-in plugin's lifecycle method has been modified in this phase, and no built-in plugin manifest has been touched beyond Phase 1's audited declarations.
- `docs/DELPHI_VALIDATION.md` exists, carries the canary, reports the synthetic-cohort results honestly, names the breaking points whose resolution it indirectly attests to, explicitly bounds the evaluation to packaged-method execution rather than live-facilitation improvisation, and is cross-referenced from `docs/ACTIVITY_CONTRACT_SPEC.md` and `docs/INDEX.md`.
- The generalization decision is executed: either `orchestrations/estimate_talk_estimate.json` exists and its lighter-weight test extension passes, or the deferral subsection in `docs/DELPHI_VALIDATION.md` explicitly records the deferral and names the methods considered.
- No test that previously passed regresses, and no test docstring, document header, fixture, or orchestration `metadata.notes` slot introduced under Phase 6 omits the `Oracular Quokka` canary where the step requirements call for it.

## Master-Plan Closure

When this phase clears, the master plan defined in [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md) is complete. The orchestration engine ships, the substrate is documented and tested across DP1 through DP9, Delphi instantiates without modifying any existing plugin, and the architectural claim is demonstrated against the method that motivated the design. Subsequent work — empirical evaluation with real participant groups, additional reference orchestrations, the `conditional` control-flow primitive's runtime implementation, journal-extension manuscripts, and any UI polish beyond the minimal facilitator-decision surface from Phase 5 — lives outside this master plan and is addressed by separate planning efforts.

## Scope Boundary

This phase covers only the Delphi instantiation and its evaluation. The following items remain explicitly out of scope:

- Empirical evaluation with real participant groups in a field setting — future work for a journal extension.
- Reference orchestrations beyond Delphi (and optionally Estimate-Talk-Estimate per Step 4) — post-master-plan work.
- Rich hybrid facilitation semantics — especially arbitrary ad hoc activity insertion into a running orchestration and its effect on bundle history, convergence, and provenance — post-HICSS product tuning informed by facilitator feedback.
- Aesthetic polish, accessibility coverage, or mobile-specific work on any UI surface — post-master-plan work.
- Runtime implementation of the `conditional` control-flow primitive — defined-but-deferred at the Phase 4 schema layer; out of scope unless separately authorized.
- Parallel branches, sub-orchestration invocation, variable bindings, expression evaluation, event handlers, timers, and compensation/rollback — out of scope for the entire master plan per its Scope Boundary.
