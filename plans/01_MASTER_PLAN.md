# 01 — MASTER PLAN: Declarative Orchestration Engine

**Depends on:** [plans/00_DISCOVERY.md](00_DISCOVERY.md)
**Elaborated by:** [plans/02_ORCHESTRATION_ENGINE.md](02_ORCHESTRATION_ENGINE.md)

**Target state:** Decidero supports a declarative orchestration layer above the existing activity-plugin contract. Collaboration processes — beginning with Delphi — are expressed as JSON documents over a closed control-flow grammar (`sequence`, `iterate`, optionally `conditional`) and a disciplined step-kind vocabulary (`activity`, `facilitator-decision`, `ai-decision`). The existing linear agenda becomes one strategy implementation. The activity-plugin ABC, manifest fields, and bundle pipeline remain semantically unchanged; no built-in plugin is modified to make orchestrations work.

## Global Canary

**Recursive Goose**

Use this exact two-word canary in planning notes, implementation logs, schema headers, test fixtures, and validation artifacts tied to this effort.

## Strategic Phases

### Phase 1 — Contract Hardening
Tighten and formalize the existing activity-plugin contract so that the orchestration layer composes over a specification, not over informal conventions. This phase ships value independent of any engine work.

**Success Gate**
- A single canonical specification document defines the activity-plugin contract, separating formal invariants and JSON Schemas from implementer-facing how-to prose.
- Design principles DP1–DP6 are explicitly named in the specification and each has a corresponding enforced test in the suite.
- The previously unenforced idempotency invariant on `open_activity` (gap noted in [plans/00_DISCOVERY.md §12.2](00_DISCOVERY.md)) is closed by direct test coverage for every built-in plugin.
- Plugin manifests, bundle payloads, and transfer-metadata payloads validate against published JSON Schemas at application startup; violations fail loudly rather than silently.
- A faithfulness audit maps every declared `thinklets` tag in every built-in plugin to a canonical Briggs / de Vreede / Kolfschoten description, and any tag that cannot be defended is either tightened in implementation or removed from the manifest. The double-claim of `FastFocus` across VotingPlugin and CategorizationPlugin (flagged in [00_DISCOVERY.md §13.5](00_DISCOVERY.md)) is explicitly resolved.
- The reliability-policy contract surface (DP4) is documented as a first-class architectural principle, not as an implementation detail.

### Phase 2 — Strategy Seam Introduction
Introduce the `AgendaStrategy` abstraction between the meeting state machine / routers and the plugin lifecycle, and reproduce all existing linear-agenda behavior behind it without observable change. This phase converts a load-bearing absence (no server-side "advance" function — [00_DISCOVERY.md §4.2](00_DISCOVERY.md)) into a single well-defined extension point, and enables agenda activities to be created safely while a meeting is running.

**Success Gate**
- A single `AgendaStrategy` interface exists at the service layer and is the only path through which the meeting state machine and the activity-pipeline consult agenda position, next-activity selection, completion, and on-close handling.
- A `LinearAgendaStrategy` implements current behavior exclusively through this interface and is the default strategy bound to every meeting unless another is specified.
- Every router, service, and realtime broadcast path identified in [00_DISCOVERY.md §3.3 and §9](00_DISCOVERY.md) consults the strategy rather than walking `agenda_activities` ordered by `order_index` directly, with the narrow exception of presentation-only sort operations that have no behavioral consequence.
- Mid-meeting creation of `AgendaActivity` rows is supported by the meeting manager and the data layer without violating uniqueness constraints, regardless of whether the request originates from a router, the linear strategy, or a future engine strategy.
- The entire pre-existing test suite passes unmodified. No behavioral regression is observable to clients of the meeting API, the realtime broadcast, or the activity-pipeline.

### Phase 3 — Iteration Substrate
Build the typed primitives that make non-linear flow representable in the data model and the service layer. This phase resolves the breaking points that would otherwise force the engine to violate the activity-plugin contract: the linear "previous activity" assumption (BP-1), the missing iteration discriminator on bundles (BP-3), and the absence of a server-side reliability execution analogue (BP-7).

**Success Gate**
- A registered, typed `BundleTransform` interface exists in the service layer, populated with at minimum an identity transform and a Delphi statistical-aggregation transform (per-item median, IQR, dispersion, outlier flags).
- A registered, typed `ConvergencePredicate` interface exists in the service layer, populated with at minimum a fixed-N predicate and an IQR-stability predicate.
- The "previous activity" concept used by the activity-pipeline is no longer implicitly defined by `order_index` adjacency; the resolution of which prior bundle feeds the next step is explicit and addressable by an orchestration document or a transform configuration.
- The `ActivityBundle` storage model and its `(activity_id, kind)` access pattern support multiple iterations of a logically-recurring step without overwriting or shadowing prior-round bundles, by whatever mechanism the implementation chooses (iteration-scoped activity rows, a discriminator column, or equivalent).
- A server-side reliability execution path exists that mirrors the client-side `runReliableWriteAction` semantics: declared retry policy, idempotency-keyed re-execution, structured-failure handling. The path is general enough to be reused by `ai-decision` and any future server-driven step kind, and does not duplicate the manifest-side normalization already present.
- Each new interface has its own focused test module and contributes to the DP-to-test mapping table referenced in the Phase 1 specification.

### Phase 4 — Engine and Step Kinds
Implement the orchestration engine itself: the JSON document grammar, its validator, the engine strategy that interprets documents, and the three step kinds in the planned vocabulary. This is the phase where the architectural claim of [02_ORCHESTRATION_ENGINE.md](02_ORCHESTRATION_ENGINE.md) becomes a runnable artifact.

**Success Gate**
- An orchestration-document JSON Schema exists, covers the closed control-flow grammar (`sequence`, `iterate`, and `conditional` if shipped) and the step-kind vocabulary (`activity`, `facilitator-decision`, `ai-decision`), and is enforced on document load with structured error reporting comparable to the existing agenda validator.
- An `OrchestrationEngineStrategy` implements the `AgendaStrategy` interface from Phase 2 by interpreting an orchestration document, maintains explicit step-pointer and iteration state, and selects activities, decisions, and AI invocations purely from document structure plus accumulated bundle history.
- The `activity` step kind composes existing built-in plugins without modification; the `facilitator-decision` step kind pauses the engine pending a structured, typed facilitator response captured into the bundle stream; the `ai-decision` step kind invokes the AI provider with bundle context, validates against a declared output schema, supports the `review_required` composition pattern, and uses the Phase 3 server-side reliability path for malformed responses.
- The `iterate` step kind composes child steps, applies its configured inter-round `BundleTransform`, evaluates its configured `ConvergencePredicate`, and respects the declared max-rounds bound.
- A trivial multi-step orchestration (for example, brainstorm → vote) runs end-to-end through the engine strategy, drives the existing plugins, and produces the correct sequence of input / output bundles with provenance intact.
- DP9 holds in practice: instantiating this trivial orchestration required no changes to `app/plugins/base.py` signatures and no changes to any built-in plugin's manifest beyond what Phase 1 already authorized.

### Phase 5 — Realtime and Frontend Coherence
Ensure that engine-driven agenda mutations and engine-driven state transitions reach connected clients with the same fidelity as facilitator-driven ones. This phase resolves the breaking points around server-initiated agenda changes (BP-5) and frontend cache invalidation (BP-10), and supplies the facilitator-facing UI surface that the `facilitator-decision` step kind requires.

**Success Gate**
- Every engine-driven change to the agenda — including activity rows created for new iteration rounds and pointer advancement past decisions — produces the same realtime broadcast envelope that an equivalent HTTP-driven change would produce. Connected clients are never required to reconnect or poll to learn about engine activity.
- The frontend agenda cache and `currentActivity` state correctly reflect engine-driven mutations in real time, and the rendered agenda accommodates whatever non-linear topology Phase 3 chose to expose (for example, iteration rounds rendered as siblings, derived activities labeled by round).
- A minimal facilitator-decision UI exists: when the engine pauses on a `facilitator-decision` step, the facilitator dashboard surfaces the prompt, the configured prior-bundle context, and the typed response options. Responding to the prompt resumes the engine without further intervention.
- The `ai-decision` step kind's `review_required` flow is observable end-to-end: an AI-produced result held pending review is visible to the facilitator, can be approved or rejected through the decision UI, and the engine resumes correctly on either outcome.
- The frontend treats orchestration-driven meetings and linear-agenda meetings consistently from the participant's perspective; no orchestration-specific concept leaks into participant-only views unless the orchestration document explicitly demands it.

### Phase 6 — Delphi Instantiation and Evaluation
Prove that the engine and its primitives compose into a real collaboration-engineering method, by authoring Delphi as a JSON document and exercising it end-to-end. This is the phase whose output is the central evaluation artifact for the [HICSS submission](https://www.example.invalid) and the public demonstration of the platform.

**Success Gate**
- A complete `delphi.json` orchestration document exists, composed of a round-one brainstorming step, an `iterate` block containing a rank-order-voting step with the Delphi statistical-aggregation transform, an IQR-stability convergence predicate, and a max-rounds bound; optionally augmented by an `ai-decision` summary step with `review_required` and a per-round facilitator-decision continue/stop override.
- The document validates against the Phase 4 schema, parses without warnings, and loads cleanly into the engine strategy.
- An automated end-to-end test runs the document with synthetic participants through at least two full rounds. Round 2 input bundles contain round 1 aggregate statistics; participants ranking outside the IQR are correctly flagged; the convergence predicate fires under the conditions it should fire under and does not fire under conditions it should not.
- A `docs/DELPHI_VALIDATION.md` artifact captures the synthetic test setup, the observed behavior, and the analytical results in a form suitable for inclusion in the paper.
- Instantiating Delphi required no modification to `app/plugins/base.py`, no modification to any built-in plugin's lifecycle methods, and no modification to any built-in plugin's manifest beyond what Phase 1 authorized. DP9 holds for the central evaluation case, not only for the trivial demonstration of Phase 4.
- A second orchestration (Estimate-Talk-Estimate) is either shipped as `estimate_talk_estimate.json` exercising the same primitives, or is explicitly declared deferred future work with the engine's generalization claim defended on Delphi alone.

## Phase Count Check

This plan contains **6 strategic phases**. Scope remains under the 7-phase ceiling, so no halt is required.

## Ambition Posture

All six phases are committed work targeting full delivery for the HICSS-60 submission cycle (the sibling private repository tracks this as "Tier 1"). Descoping decisions — dropping the optional `ai-decision` step kind, deferring Estimate-Talk-Estimate to future work, or any other phase-level reduction — are taken only in response to a concrete, demonstrated blocker surfaced during execution, not pre-emptively. Where individual phase subplans permit deferral paths (e.g., Phase 6 Step 4's ETE-or-deferral fork), the default election is the ship path.

## Scope Boundary

This master plan covers only the orchestration-engine extension described in discovery and elaboration. The following items are explicitly out of scope unless separately authorized:

- Parallel branches, joins, synchronization primitives, sub-orchestration invocation with parameter passing, variable bindings, expression evaluation, event handlers, timers, and compensation/rollback (per DP8 in [02_ORCHESTRATION_ENGINE.md §1.4](02_ORCHESTRATION_ENGINE.md)).
- A general-purpose DSL for transforms or predicates; transforms and predicates are Python classes registered by name.
- An Alembic / versioned-migration framework. New tables or columns introduced by Phase 3 may proceed without one, with the consequence that deployment to existing instances is a manual schema-change step until a migration framework is separately adopted.
- A fourth step kind beyond `activity`, `facilitator-decision`, and `ai-decision`. New step kinds may not be added without a published collaboration-engineering pattern that justifies them (per DP8).
- Empirical evaluation with real participant groups. The Phase 6 evaluation is analytical and synthetic; field study is a future-work item suitable for a journal extension.
- Public outreach, paper drafting, and conference-submission strategy. These live in the sibling private repository and are not represented in this codebase.
