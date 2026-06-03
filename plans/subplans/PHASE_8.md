# PHASE 8 — Orchestration Runtime Advancement and Facilitator Cycle Control

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Predecessor:** [plans/subplans/PHASE_7.md](PHASE_7.md) — surfaced during the Copper Compass pilot dry-run
**Engine design lineage:** [plans/archive/orchestration_engine/subplans/PHASE_4.md](../archive/orchestration_engine/subplans/PHASE_4.md) (step kinds), [PHASE_5.md](../archive/orchestration_engine/subplans/PHASE_5.md) (decision UI + realtime broadcast)
**Paper outline:** [docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md](../../docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md)

## Phase Canary

**Deliberate Heron**

Use this exact two-word canary in Phase 8 notes, schema headers, engine dispatch
sites, UI tests, and commits tied to this phase.

## Why This Phase Exists

The first live Classical Delphi run in the Copper Compass pilot stopped dead after
Round 1. Three findings, in order of discovery:

1. **`activity_bundles` schema drift (FIXED).** The `ActivityBundle` model gained
   `logical_step_id` and `round_index` columns with no startup migration, so any
   pre-existing SQLite database raised `no such column` on every bundle read. A
   migration was added to `ensure_sqlite_schema` and applied to the live
   `decidero.db`. Recorded here as the prerequisite that unblocked everything else.

2. **Runtime advancement is never wired.** `OrchestrationEngineStrategy.create_activity`
   — the method that materializes the next method step, evaluates convergence, and
   honors decision gates — is fully built and unit-tested, but at runtime it is
   called in exactly one place: `meeting_template_manager.py` seeds the **first**
   activity at meeting creation. Nothing advances the engine after an activity
   closes. The facilitator has no control to reach Round 2.

3. **Decisions record but do not branch.** The `facilitator-decision` and
   `ai-decision` step kinds exist and the decision UI is wired, but
   `resume_with_facilitator_decision` captures the chosen option into the bundle
   stream and then advances **linearly** regardless of the choice. The primitive
   that would let a choice steer flow (`conditional`) was deliberately deferred in
   Phase 4 and flagged "may not ship at all." Today the only thing that decides
   "another cycle?" in Delphi is the automated IQR-stability predicate plus the
   `max_rounds` cap. `orchestrations/delphi.json` authors no decision step at all.

The HICSS paper's facilitation-support claim (master plan UF8 — "decision points
should state the current evidence, the available next choices, and what will
happen after each choice") is therefore not reachable through the product today.

## Locked Design Decisions

Decided during planning with the maintainer:

- **Scope = C + A.** Wire runtime advancement (**C**) and give a facilitator
  decision at the iterate round boundary real continue/conclude authority (**A**),
  a narrow slice of branching scoped to the loop. Do **not** build the general
  `conditional` primitive (**B**) — a skilled facilitator already gets arbitrary
  branching from the transfer/curation system, so the value is *narrowing* the
  choice for a less-skilled facilitator, not generalizing it.
- **Advancement is facilitator-triggered, not automatic.** Stopping an activity
  stops it. The facilitator advances explicitly. Within a round this is a plain
  "advance" action; at a round boundary the advance affordance *is* the cycle gate.
- **"Conclude" = stop.** There is no separate force-complete artifact. Concluding a
  method early means choosing "conclude" at the gate (or simply stopping and not
  advancing); the last round's output bundle is the result.
- **The recommendation source is pluggable (AI-ready seam).** At the gate the
  facilitator is shown a machine-computed recommendation. In v1 that recommendation
  is the deterministic convergence predicate (e.g. "IQR 0.31 vs 0.15 target — not
  yet stable; recommend another round"). The seam is built so a later phase can
  swap in an `ai-decision` (with `review_required`) as the recommendation source
  via a document change plus a prompt, with no engine refactor.
- **The live LLM advisor is deferred.** Coupling a live-AI reliability/latency/cost
  surface to a pilot whose job is to test facilitator comprehension would confound
  the experiment, and the deterministic predicate already supplies the advice
  channel. Deferred until after the pilot shows what advice facilitators want.

## Load-Bearing Architectural Constraint

`get_agenda_strategy(meeting)` constructs a **fresh** `OrchestrationEngineStrategy`
on every request; its constructor only prefetches the plan. Most engine state is
already DB-derived (`_materialize_count` counts activity rows; the walker re-reads
prior round output bundles by the persisted `logical_step_id`/`round_index`
columns). But two pieces are in-memory only and reset to empty each request:

- **`_activity_iteration`** (activity_id → (logical_step_id, round_index)). Empty on
  a fresh strategy, so Delphi rounds 2+ cannot locate the previous round's activity
  to inject `previous_round_feedback` — the statistical carry-forward silently
  breaks even though Round 1 works.
- **`_pending_decision`**. Once round boundaries become real pause points, a stop in
  one request and a resume in another must agree on whether the engine is paused.

Therefore **engine state rehydration from persisted bundles is the load-bearing
prerequisite** for everything else in this phase, and is sequenced first.

## Atomic Steps

### Step 0 — [DONE] `activity_bundles` migration

Add `logical_step_id` and `round_index` to `ensure_sqlite_schema` in
`app/database.py`, matching the existing `ALTER TABLE ... ADD COLUMN` pattern, and
apply to the live database. Done during the pilot session that surfaced this phase.

### Step 1 — [DONE] Engine state rehydration

Make a freshly constructed `OrchestrationEngineStrategy` reproduce the in-memory
state an in-process-accumulated instance would hold, from persisted rows alone.

Conclude this step by:

- [DONE] Adding a rehydration path (`OrchestrationEngineStrategy.rehydrate_from_db`,
  invoked from `get_agenda_strategy`) that rebuilds `_activity_iteration` from
  persisted `AgendaActivity` rows carrying the `_orchestration` discriminator, and
  restores `_pending_decision` when the last materialized step is a
  `facilitator_decision` activity with no output bundle.
- [DONE] `previous_round_feedback` injection now matches in-process: the empirical
  failure (a fresh strategy produced empty feedback input bundles in iterate rounds
  2+) is fixed and guarded by a regression test.
- [DONE] Proving with a unit test that a per-request (fresh + rehydrated) strategy
  yields identical feedback carry-forward as an in-process instance
  (`test_per_request_reconstruction_matches_in_process_feedback`), plus a
  decision-pause survival test (`test_rehydrate_restores_pending_facilitator_decision`).

Technical deviations:
- The "rebuild each `_IterateFrame`'s round history" sub-goal was not implemented as
  explicit frame-state restoration. Empirical investigation showed the walker
  already rebuilds round history from persisted output bundles (`_collect_round_output`
  queries by `logical_step_id`/`round_index`), so the only genuinely lost state was
  `_activity_iteration` (the prior-round activity lookup) and `_pending_decision`.
  Rehydrating those two is sufficient for feedback parity; reconstructing live frame
  objects would have been redundant.
- `_materialize_facilitator_decision` now persists `_orchestration.logical_step_id`
  into the decision activity's config so the pause is rehydratable from the row
  alone (previously `logical_step_id` lived only in the in-memory `_pending_decision`).
- A residual convergence-timing discrepancy remains for content-sensitive predicates:
  with `iqr_stability`, an in-process strategy can mint one extra "lookahead" round
  because `_extend_plan` evaluates convergence against a not-yet-closed round's empty
  output, whereas a per-request strategy reads only closed rounds and stops one round
  earlier. The per-request count is the more correct one. This is a convergence-timing
  artifact, not a state-rehydration bug, and is left to Phase 8 Step 3, where the
  facilitator round-gate replaces the automatic lookahead entirely. The oracle test
  therefore uses a content-independent `fixed_n` predicate to assert exact parity of
  the state this step governs (feedback carry-forward and round identity).

### Step 2 — [DONE] Runtime advancement wiring (C)

Let the facilitator advance the engine after an activity closes.

Conclude this step by:

- [DONE] Adding a facilitator-only advance entry point
  (`POST /api/meetings/{meeting_id}/orchestration/advance`,
  `advance_orchestration` in `app/routers/meetings.py`) that calls `create_activity`
  for an orchestration-backed meeting when it is not paused on a decision and the
  plan is not complete, then broadcasts via `broadcast_engine_agenda_mutation`.
- [DONE] Triggered by an explicit facilitator action, never automatically on stop;
  facilitator-only (403 otherwise). Refuses cleanly with a structured `status`
  (`"complete"` / `"paused"`) rather than an error when the plan is complete or a
  decision is pending.
- [DONE] End-to-end test
  (`test_orchestration_advance_endpoint_materializes_next_round`): create Delphi
  meeting → finalize brainstorm output → advance materializes the Round 1
  rank-order vote with correct `_orchestration` config and no stale runtime data;
  advancing again reaches Round 2 with a non-empty `previous_round_feedback` input
  bundle (the Step 1 rehydration is what makes round 2 correct). Plus an
  authorization test (`test_orchestration_advance_rejects_non_facilitator`).

Technical deviations:
- The endpoint mints the next activity and broadcasts the agenda update but does
  **not** auto-start it; the facilitator starts it through the existing control
  action. This keeps "advance" (materialize) and "start" (run) as distinct
  facilitator gestures, consistent with the explicit-action design.
- Paused/complete are reported as HTTP 200 with a `status` field rather than a 4xx,
  so the (Step 4) facilitator UI can render the gate/complete state from a normal
  response. If `create_activity` itself materializes a facilitator-decision step,
  the endpoint reports `status: "paused"` with the decision prompt/options rather
  than presenting the decision row as a runnable activity.

### Step 3 — [DONE] Loop-control decision at the iterate boundary (A)

Give a facilitator decision at the round boundary real continue/conclude authority,
with the convergence predicate as the recommendation.

Conclude this step by:

- [DONE] Adding a `round_gate` declaration on the `iterate` step (mode `facilitator`,
  recommendation source `convergence`), defined in
  `docs/schemas/orchestration.schema.json`, parsed onto `IterateStep`, and validated
  by the loader. The recommendation source is an enumerated seam (`convergence`
  implemented; `ai` accepted by schema/loader but reserved) so the AI advisor slots
  in later without engine changes.
- [DONE] The walker **pauses** at the iterate boundary when the gate is present
  instead of auto-deciding, materializing a continue/conclude decision whose config
  carries the predicate verdict (`recommendation`) and round evidence.
- [DONE] The resumed choice **steers** the loop: "conclude" pops the iterate frame;
  "continue" starts the next round. `max_rounds` is a hard backstop that auto-
  concludes at the cap without a pause.
- [DONE] Authored the gate into `orchestrations/delphi.json`.
- [DONE] Tests (`test_round_gate_*`): pauses-with-recommendation,
  continue-steers-to-next-round, conclude-steers-to-method-end, cap backstop, and
  survives a fresh-strategy rehydration. The shipped-Delphi e2e
  (`test_phase6_delphi_synthetic_cohort_end_to_end`) and the advance-endpoint e2e
  now drive through the gate.

Technical deviations:
- The gate reuses the `facilitator_decision` tool type and pause/resume contract
  rather than a new step kind; the options are the loop-control verbs
  `continue`/`conclude`. Gate decisions are materialized out-of-band (they are not
  plan entries), so they are excluded from the plan-aligned `_materialize_count`,
  and `order_index` is now assigned from the total row count to respect the unique
  `(meeting, order_index)` constraint.
- The Step 1 convergence-timing lookahead artifact is resolved **for gated iterates**:
  the walker now stops at an unfinished round boundary instead of appending an empty
  round output and evaluating on stale data, so a gate's recommendation reflects the
  actually-closed round. Gate-less iterates keep their prior lookahead behavior, so
  this is a scoped change that leaves existing non-gated iterate tests unchanged.
- Fixed a latent cross-meeting bug surfaced by the gate: round-gate and round-output
  bundle lookups previously matched on `(logical_step_id, round_index)` alone, which
  collide across meetings built from the same document. They are now scoped by
  `meeting_id` (threaded onto the walker), and `respond_facilitator_decision` now
  tags the decision bundle with `logical_step_id`/`round_index` so a per-request
  walker can read the steer back.

### Step 4 — [PENDING] Plain facilitator gate UI (UF8)

Surface the cycle gate on the meeting page so a less-skilled facilitator picks A or
B with full context, reusing the existing facilitator-decision UI surface.

Conclude this step by:

- Rendering current evidence (round N of max, convergence metric vs target,
  recommendation), the two choices, and a plain statement of what each does next.
- Selecting the newly materialized activity on "continue"; showing a clear
  method-complete state on "conclude" or plan exhaustion.
- Adding a frontend smoke test and updating
  [docs/USER_TESTING_GUIDE.md](../../docs/USER_TESTING_GUIDE.md) with the cycle-gate
  flow.

### Step 5 — [PENDING] Regression, pilot evidence, and outline alignment

Conclude this step by:

- Extending the agreed regression command with the new/changed test modules and
  reaching `[100%]`.
- Re-running the Classical Delphi pilot path end-to-end and recording findings
  against UF8 and the facilitation-support paper claim.
- Updating the HICSS outline so the facilitation-support claim reflects a runnable
  facilitator cycle gate rather than scaffolding.

## Phase Exit Criteria

Phase 8 clears only when:

- A fresh per-request strategy reproduces multi-round Delphi state from persisted
  data (no reliance on in-process accumulation).
- A facilitator can drive a Classical Delphi meeting end-to-end through the UI:
  brainstorm → ranked rounds → cycle gate → conclude, with correct statistical
  feedback on every round past the first.
- At each round boundary the facilitator sees the evidence, the A/B choice, and the
  consequence of each choice, and the choice actually steers the loop.
- `max_rounds` remains a hard backstop.
- The recommendation source is a pluggable seam with `convergence` implemented and
  `ai` reserved but unimplemented.
- The agreed regression command reaches `[100%]` and a pilot pass is recorded.
- The HICSS outline agrees with the implemented facilitation-support behavior.

## Scope Boundary

This phase does not cover:

- The general `conditional` control-flow primitive (arbitrary branching).
- A live LLM advisor or any networked AI call in the cycle gate (seam only).
- New step kinds beyond those already shipped.
- Re-running or editing a completed round in place ("repeat round" as a distinct
  feature) — taking manual control via the existing transfer/curation tools is the
  escape hatch for a method that has genuinely gone off the rails.
- Enriching the Delphi method content with a distinct eval/sort/bin step — a
  document change that may follow once the cycle mechanism is proven.
- Publication-grade empirical evaluation.
