# 02 — Orchestration Engine

**Status:** Design plan
**Scope:** Extend Decidero from a linear-agenda GDSS into a declarative orchestration platform in which collaboration processes (Delphi, NGT, Estimate-Talk-Estimate, scenario-conditional flows) are first-class artifacts expressed as JSON documents.

The existing activity-plugin contract is preserved unchanged. A new orchestration layer sits between the meeting state machine and the activity plugins, and the existing linear agenda becomes one strategy implementation among others.

---

## 1. Architectural Direction

### 1.1 Target layers

```
Meeting state machine                       (existing, lightly touched)
  │
  ├── AgendaStrategy interface              (NEW — pluggable)
  │     ├── LinearAgendaStrategy            (existing behavior, refactored)
  │     └── OrchestrationEngineStrategy     (NEW — interprets JSON)
  │
  ├── Orchestration primitives              (NEW)
  │     ├── Control flow:  sequence, iterate, conditional
  │     ├── Step kinds:    activity, facilitator-decision, ai-decision
  │     ├── BundleTransform interface       (named, typed)
  │     └── ConvergencePredicate interface  (named, typed)
  │
  ├── Activity plugin contract              (existing — UNCHANGED)
  │     ├── ActivityPlugin ABC
  │     ├── Manifest with ThinkLet metadata
  │     └── Bundle pipeline (input/draft/output)
  │
  └── Bundle storage and provenance         (existing — UNCHANGED)
```

### 1.2 Design principles

Numbered for cross-reference from tests and documentation.

- **DP1 — Phased Bundle Flow with Typed Roles.** Activities communicate through `input`, `draft`, `output` bundles. Roles are typed. *(Already implemented.)*
- **DP2 — Provenance Preservation Across Phase Boundaries.** Metadata and source fields are preserved across transfer; never stripped by display toggles. *(Already implemented; verified by `test_transfer_metadata.py`.)*
- **DP3 — Idempotent Lifecycle Operations.** `open_activity` must not duplicate state on restart. *(Documented; needs a dedicated test — see Task 1.3.)*
- **DP4 — Reliability Policy as Manifest Contract Surface.** Client retry/idempotency policy is declared by the plugin, normalized server-side, and applied uniformly via `runReliableWriteAction`. *(Already implemented.)*
- **DP5 — Collaboration-Method Metadata as Machine-Readable ThinkLet Annotation.** Plugins carry `collaboration_patterns`, `thinklets`, `bias_mitigation`, `when_to_use`, `when_not_to_use`, group-size and duration ranges. *(Already implemented.)*
- **DP6 — Plugin-Local Config Validation.** Activity-specific invariants are enforced inside plugin lifecycle methods, not by a uniform schema validator.
- **DP7 — Collaboration Processes as Declarative, Composable Artifacts.** Orchestrations are JSON documents over a deliberately minimal language. *(NEW.)*
- **DP8 — Closed Control Flow, Open Step Vocabulary.** The orchestration grammar is intentionally closed (sequence, iterate, conditional, and stop). The step-kind vocabulary is open but disciplined: each new step kind must be justified by a published collaboration-engineering pattern. *(NEW — the minimalism principle that defends against BPMN-style bloat.)*
- **DP9 — Method-Specific Concerns Do Not Belong in Activity Plugins.** Methods are sequences over activities; they are not properties of activities. Validated by instantiating Delphi without modifying any existing plugin. *(NEW — negative principle.)*

### 1.3 The orchestration language

Three control-flow primitives, no more:

- `sequence` — run a list of child steps in order
- `iterate` — repeat a child sub-sequence until a convergence predicate fires or a max-rounds bound is reached
- `conditional` — run sub-sequence A or B based on a predicate over the prior bundle *(stretch — defer if needed)*

Three step kinds:

- `activity` — instantiates a registered activity plugin by `tool_type`, with config
- `facilitator-decision` — pauses for a typed, structured facilitator choice; result is captured in the bundle stream
- `ai-decision` — invokes an LLM with a typed prompt + bundle context, validates against an output schema, captures result

Two bridging primitives, registered by name:

- `BundleTransform` — typed function `(input_bundle, transform_config) → output_bundle`
- `ConvergencePredicate` — typed function `(bundle_history, predicate_config) → bool`

Orchestration metadata at the top level: name, version, author, citation, ThinkLets composed, patterns covered, deliverables produced, group-size range, time estimate. This metadata is what makes orchestrations library-able artifacts.

### 1.4 Explicitly out of scope (DP8)

- No parallel branches, no joins, no synchronization primitives
- No sub-orchestration invocation with parameter passing
- No variable bindings or expression evaluation
- No event handlers, no timers, no compensation/rollback
- No DSL for transforms or predicates; they are Python classes registered by name
- No general-purpose conditionals — `conditional` (if shipped) takes a named predicate, not an expression

---

## 2. Implementation Plan

Tasks are organized so that work is safe-to-truncate: every completed task improves the codebase regardless of whether subsequent phases ship. Phase 1 strengthens what exists; Phases 2–4 build the engine and a first orchestration.

### Phase 1 — Strengthen the existing contract

**Task 1.1 — Split `ACTIVITY_CONTRACT_GUIDE.md` into spec + guide.**
- Create `docs/ACTIVITY_CONTRACT_SPEC.md` containing formal invariants, numbered design principles (DP1–DP6), JSON Schema for the manifest, JSON Schema for the bundle payload, and the contract-test matrix.
- Keep `docs/ACTIVITY_CONTRACT_GUIDE.md` as the implementer-facing how-to. Cross-reference the spec.

**Task 1.2 — Author JSON Schemas.**
- `docs/schemas/activity_manifest.schema.json` — all fields including the ThinkLet metadata.
- `docs/schemas/bundle_payload.schema.json` — `items` shape and required `metadata` / `source` provenance fields.
- `docs/schemas/transfer_metadata.schema.json` — formalize what `docs/TRANSFER_METADATA.md` already describes.
- Wire schemas into a startup validation pass for built-in plugins (fail loudly if a plugin's manifest violates the schema).

**Task 1.3 — Add the DP3 idempotency test.**
- New test in `app/tests/test_activity_plugins.py`: for each built-in plugin, instantiate an activity, call `open_activity` twice with the same input bundle, assert no state duplication.

**Task 1.4 — Promote `validate_config()` to explicit principle (DP6).**
- Either wire `validate_config()` into the plugin lifecycle so it is invoked automatically (preferred if cheap), or explicitly document that plugin-local validation is the intentional design choice and explain why.

**Task 1.5 — ThinkLet faithfulness audit.**
- For each built-in plugin, locate the canonical ThinkLet description in Briggs/de Vreede/Kolfschoten literature.
- Write `docs/THINKLET_AUDIT.md` mapping plugin behavior to canonical specification. Where the implementation diverges from the canonical spec, either tighten the implementation or remove the unjustified ThinkLet tag from the manifest.
- Expected outcome: the brainstorming plugin's claim to implement `FreeBrainstorm` and `LeafHopper` is probably mostly accurate but may need tightening around anonymity guarantees. The voting plugin's claim to `StrawPoll` and `FastFocus` is more straightforward. The categorization plugin will be the hardest to map.

**Task 1.6 — Document the reliability-policy contract surface.**
- The existing `reliability_policy` manifest field, normalized by `activity_catalog.normalise_reliability_policy`, and applied client-side by `runReliableWriteAction`, is genuinely novel relative to the GDSS literature.
- Promote it from "implementation detail" to "named design principle" (DP4) in the spec.

### Phase 2 — Engine prep

**Task 2.1 — Define the `AgendaStrategy` interface.**
- New module `app/services/agenda_strategy.py` with an ABC defining the hooks needed:
  - `next_activity(meeting, bundle_history) -> Optional[AgendaActivity]`
  - `is_complete(meeting, bundle_history) -> bool`
  - `on_activity_close(meeting, completed_activity, output_bundle) -> None`
- Implement `LinearAgendaStrategy` that reproduces current behavior using only these hooks.
- Refactor the meeting state machine to consult an `AgendaStrategy` rather than walking `agenda_activities` directly.
- Test: existing meeting tests should pass unmodified.

**Task 2.2 — Make mid-meeting activity creation work.**
- Extend the activity model / data layer so new `AgendaActivity` rows can be inserted while a meeting is running, with IDs minted on demand.
- Activity IDs derived from a stem + counter, scoped per strategy invocation.

**Task 2.3 — `BundleTransform` interface.**
- New module `app/services/bundle_transforms.py` with ABC for typed transforms.
- Implement `IdentityBundleTransform` and `DelphiStatisticalAggregationTransform`.
- The Delphi transform: given a rank-order-voting output bundle, computes per-item median, IQR, and dispersion; identifies which participants ranked outside the IQR; produces an output bundle annotated with aggregate statistics and per-participant outlier flags.
- Registry pattern matching the existing plugin registry — transforms are registered by name and looked up by orchestration documents.
- Tests under `app/tests/test_bundle_transforms.py`.

**Task 2.4 — `ConvergencePredicate` interface.**
- New module `app/services/convergence_predicates.py` with ABC.
- Implement `FixedNPredicate` (fires after N rounds) and `IQRStabilityPredicate` (fires when median IQR changes by less than threshold across two consecutive rounds).
- Registry pattern, registration by name.
- Tests under `app/tests/test_convergence_predicates.py`.

### Phase 3 — Engine implementation

**Task 3.1 — Orchestration document schema.**
- New schema: `docs/schemas/orchestration.schema.json`.
- Top-level: `name`, `version`, `author`, `citation`, `metadata` (including ThinkLets, patterns, deliverables), `steps`.
- `steps` is a list of step objects, each typed by a `kind` discriminator: `sequence`, `iterate`, `conditional`, `activity`, `facilitator-decision`, `ai-decision`.
- Validate every orchestration document on load.

**Task 3.2 — `OrchestrationEngineStrategy`.**
- New strategy implementation in `app/services/agenda_strategy.py` that interprets an orchestration document by walking a small AST.
- Internal state: current step pointer, iteration counter for `iterate` steps, accumulated bundle history.
- Each tick: examine the current step, instantiate the next activity (or pause for a decision), advance the pointer when the activity closes.
- Test: a trivial two-activity orchestration (brainstorm → vote) runs and produces the right bundles.

**Task 3.3 — `activity` step kind.**
- The most basic step kind. Wraps an existing plugin invocation.
- Configuration: `tool_type`, `config` (passed to the plugin), `transform_input` (optional name of a transform to apply to the input bundle before the activity opens), `title` (display).

**Task 3.4 — `iterate` step kind with transform-between-rounds.**
- Configuration: child steps, max rounds, convergence predicate (named, with config), inter-round transform (named, with config).
- Each iteration: run child steps once, apply transform to the output, check predicate, decide to loop or exit.
- Critical for Delphi.

**Task 3.5 — `facilitator-decision` step kind.**
- Configuration: `prompt` (the question to the facilitator), `options` (list of typed responses), `context_bundle_keys` (which prior bundles to display).
- Engine pauses; UI shows the prompt and bundle context to the facilitator; on response, the choice is recorded as a typed bundle item and the engine resumes.
- Minimal UI: a modal in the facilitator dashboard. Stretch: integrated into the meeting flow with audit trail.

**Task 3.6 — `ai-decision` step kind.**
- Configuration: `prompt_template`, `context_bundle_keys`, `output_schema`, `review_required` (boolean — if true, must be followed by a facilitator-decision step in the orchestration).
- Engine renders the prompt with the bundle context, calls the configured AI provider, validates the response against the output schema, captures the result.
- If `review_required` is true, the result is held pending the next facilitator-decision step's approval.
- Failure handling: malformed AI responses use the existing reliability-policy retry pattern — reuse `runReliableWriteAction`-equivalent server-side infrastructure rather than building a parallel retry framework.

**Task 3.7 — `conditional` step kind. (Stretch.)**
- Configuration: `predicate` (named), child sub-sequences `if_true` and `if_false`.
- Useful for repair loops ("if categorization quality is low, repeat brainstorming") but Delphi does not strictly require it.
- Drop without ceremony if behind schedule.

### Phase 4 — Delphi instantiation

**Task 4.1 — Author `orchestrations/delphi.json`.**
- Composed of: a brainstorming step (round-1 idea generation), then an `iterate` block containing a rank-order-voting step (followed by the Delphi statistical aggregation transform), with an IQR stability predicate and max rounds of 4.
- Optionally: an `ai-decision` step that summarizes qualitative justifications between rounds, with `review_required: true` and a `facilitator-decision` step for review.
- Optionally: a `facilitator-decision` step at the end of each round letting the facilitator override the predicate's continue/stop decision.

**Task 4.2 — End-to-end Delphi test.**
- Synthetic test with simulated participants. Run the orchestration through two full rounds. Assert: round 2 input bundle contains aggregate statistics from round 1; outlier participants are flagged; convergence predicate fires correctly.
- Document the test, the synthetic participants, and the observed behavior in `docs/DELPHI_VALIDATION.md`.

**Task 4.3 — Author `orchestrations/estimate_talk_estimate.json`. (Stretch.)**
- ETE: initial individual estimation, group discussion (brainstorm step), revised estimation (rank-order voting), no formal aggregation transform required — but the same `iterate` primitive composes it cleanly.
- Demonstrates that the orchestration primitives generalize beyond Delphi.

---

## 3. Risks and Mitigations

**Risk 1 — Agenda extraction is more tangled than expected.**
*Mitigation:* Phase 2 begins with refactoring `LinearAgendaStrategy` to consult the new interface while leaving all existing tests green. If that refactor cannot be done cleanly, the engine work is paused until the coupling is addressed; the existing tests are the regression net.

**Risk 2 — Delphi statistical aggregation has more subtleties than expected.**
*Mitigation:* Implement the simplest possible version first (median + IQR per item). Extensions (Kendall's W, weighted aggregation) are future work.

**Risk 3 — AI-decision step reliability is variable.**
*Mitigation:* The `review_required` flag and the composition pattern (AI proposes, facilitator approves) is the methodological answer. Make it the recommended pattern in the spec.

**Risk 4 — Scope creep on step kinds.**
*Mitigation:* Three step kinds, justified by named patterns, is the discipline. No fourth step kind without a published collaboration-engineering pattern that justifies it (DP8).

---

## 4. Standing Conventions for Implementation

- **Preserve the existing activity-plugin contract.** No changes to `app/plugins/base.py` interface signatures, no changes to existing built-in plugins' manifests except as specified in the ThinkLet faithfulness audit (Task 1.5). DP9 is load-bearing: the engine must work without modifying any existing plugin.
- **New code locations:** `app/services/` for engine infrastructure, `app/orchestrations/` (or `orchestrations/` at the repo root) for JSON orchestration documents, `docs/schemas/` for JSON Schemas.
- **All new functionality must have tests.** Every new principle gets a corresponding test; the DP-to-test mapping table lives in `docs/ACTIVITY_CONTRACT_SPEC.md`.
- **Reliability policy infrastructure must be reused, not duplicated.**
- **Stop and report at every Phase boundary.** Phases 1, 2, 3, 4 each end with a checkpoint.

---

*End of plan.*
