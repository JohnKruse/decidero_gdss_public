# PHASE 2 — Strategy Seam Introduction

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Discovery reference:** [plans/00_DISCOVERY.md](../00_DISCOVERY.md)
**Elaboration reference:** [plans/02_ORCHESTRATION_ENGINE.md](../02_ORCHESTRATION_ENGINE.md)

**Phase objective:** Introduce the `AgendaStrategy` abstraction between the routers / realtime broadcasts / activity-pipeline and the underlying agenda data, and reproduce all existing linear-agenda behavior behind it without any observable change. This phase converts a load-bearing absence — there is no server-side "advance" function today (see [plans/00_DISCOVERY.md §4.2](../00_DISCOVERY.md)) — into a single well-defined extension point that Phases 3 through 6 will build on. It also guarantees that mid-meeting `AgendaActivity` row creation is safe regardless of which caller initiates it, so the future orchestration engine can mint iteration rounds without violating uniqueness constraints.

## Phase Canary

**Smug Otter**

Use this exact two-word canary in Phase 2 notes, commit messages, module docstrings introduced by this phase, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — [DONE] Author the `AgendaStrategy` Interface and Binding
Author `app/services/agenda_strategy.py` containing the `AgendaStrategy` abstract base class. The interface must expose exactly the consultation points the existing codebase needs, framed so a future `OrchestrationEngineStrategy` can answer the same questions over a non-linear topology without altering the interface: a hook that resolves the prior activity for a given activity (replacing the implicit definition baked into [`_find_previous_activity`](../../app/services/activity_pipeline.py) at `app/services/activity_pipeline.py:59-68`), a hook that lists the agenda in the order the strategy considers canonical (which `LinearAgendaStrategy` will define as `order_index`-sorted), a hook that reports whether the agenda is logically complete (currently no such concept exists per [00_DISCOVERY.md §3.6](../00_DISCOVERY.md) — the linear strategy will model completion as "last `order_index` row has closed"), an `on_activity_close` hook so the strategy can record completion events that future engine strategies will need, and a hook that admits mid-meeting activity creation through the manager (so callers do not insert rows behind the strategy's back).

A binding mechanism must select which strategy a given meeting uses. The default for every existing meeting and every new meeting authored in Phase 2 is `LinearAgendaStrategy`; engine-strategy binding is out of scope here. The mechanism may be a per-meeting accessor, a service-locator function keyed off meeting attributes, or any equivalent design, provided that exactly one strategy is bound to a meeting at any time and the binding is deterministic. The interface module must carry the `Smug Otter` canary in its module docstring.

This step authors the interface and the binding shell only; no consumer is rewired yet. The interface should not assume linearity even though the only implementation in this phase is linear.

Conclude this step by:
- Implementing the core logic as the new `app/services/agenda_strategy.py` module with the `AgendaStrategy` ABC, the binding mechanism, and a `Smug Otter`-tagged module docstring.
- Creating or updating the relevant pytest file by extending `app/tests/test_meeting_state.py` with assertions that confirm the binding mechanism produces a strategy for every meeting touched by the existing meeting-state fixtures; do not introduce a new pytest module since `test_meeting_state.py` already houses meeting-scoped state coverage.
- Updating docstrings and documentation so the new interface module, the activity-pipeline module (`app/services/activity_pipeline.py`), and `docs/ACTIVITY_CONTRACT_SPEC.md` (authored in Phase 1) each cross-reference the strategy seam and identify Phase 2 by its `Smug Otter` canary.

Technical deviations logged:
- `LinearAgendaStrategy` was implemented as the deterministic default binding shell in this step so `get_agenda_strategy(meeting)` can return a concrete strategy for tests. Step 2 still owns expanded parity coverage and any final behavior hardening.
- The Phase 2 gate exposed stale documentation-audit tests from an earlier facilitator-model planning cycle; those tests now also accept the current orchestration subplans without weakening their legacy assertions.
- The Phase 2 gate also exposed an order-dependent transfer eligibility failure where a paused current activity could retain a stale `activeActivities` entry. `_ensure_not_running` now treats the current activity's paused global state as not running.

### Step 2 — [DONE] Implement `LinearAgendaStrategy` with Behavior Parity
Implement `LinearAgendaStrategy` inside `app/services/agenda_strategy.py` so it reproduces the current linear behavior exclusively through the interface authored in Step 1: prior-activity resolution uses `order_index` adjacency (matching today's `_find_previous_activity` semantics line-for-line), the canonical agenda ordering is `order_index`-sorted, completion is defined as "the highest-`order_index` activity has produced an `output` bundle", and the `on_activity_close` hook is a no-op for the linear case (it records the close for later strategies but performs no progression action, since today's progression is client-driven per [00_DISCOVERY.md §4.2](../00_DISCOVERY.md)). The mid-meeting creation hook delegates straight to `app/data/meeting_manager.py`'s existing `add_agenda_activity`, which already handles `_resequence_agenda` correctly per [00_DISCOVERY.md §3.4](../00_DISCOVERY.md).

Author a dedicated parity test that compares, for a representative set of agenda topologies (single activity, two activities, an activity followed by a deleted-then-re-added activity, an activity reordered after creation), the answers produced by `LinearAgendaStrategy` against the answers produced by direct walks of `meeting.agenda_activities` sorted by `order_index`. The parity test is the load-bearing evidence that Step 3's consumer rewiring will not introduce behavioral drift.

Conclude this step by:
- Implementing the core logic as the `LinearAgendaStrategy` class inside `app/services/agenda_strategy.py` and routing the binding mechanism's default to it.
- Creating or updating the relevant pytest file by extending `app/tests/test_meeting_manager.py` with the parity-coverage assertions described above; this module already houses agenda-shape coverage, so no new pytest module is required.
- Updating docstrings and documentation so `app/services/agenda_strategy.py`, the activity-pipeline module, and `docs/ACTIVITY_CONTRACT_SPEC.md` each describe `LinearAgendaStrategy` as the canonical reference implementation of the seam and identify it under the `Smug Otter` canary.

Technical deviations logged:
- None.

### Step 3 — [DONE] Channel All Existing Consumers Through the Strategy
Refactor every site enumerated in [plans/00_DISCOVERY.md §3.3 and §9](../00_DISCOVERY.md) so it consults the strategy bound to the meeting rather than walking `meeting.agenda_activities` and `order_index` directly. The sites in scope are: the activity-pipeline's `_find_previous_activity` (which becomes a call to the strategy's prior-activity hook); the GET handler at [`app/routers/meetings.py:970`](../../app/routers/meetings.py); the export iteration at [`app/routers/meetings.py:298`](../../app/routers/meetings.py); the realtime broadcast at [`app/routers/realtime.py:52-54`](../../app/routers/realtime.py); the transfer-router resolver at [`app/routers/transfer.py:56-64`](../../app/routers/transfer.py); the meeting-manager's `list_agenda` at [`app/data/meeting_manager.py:349-353`](../../app/data/meeting_manager.py); and any other site grep reveals that walks the relationship or assumes `order_index` total ordering.

The narrow exception is presentation-only sorts that have no behavioral consequence — for example, a final cosmetic sort applied to a list the strategy already returned in canonical order. Such sorts are acceptable but must be commented in code as presentation-only and must not gate behavior. The `_resequence_agenda` two-pass renumbering at `app/data/meeting_manager.py:265-291` remains in the data layer and is consulted by the strategy's mid-meeting creation hook; it is not rewired through the strategy because its concern is storage-layer uniqueness, not agenda interpretation.

The activity-pipeline's `_find_previous_activity` is removed in favor of strategy consultation, but its linear semantics are preserved by `LinearAgendaStrategy` — the load-bearing assumption that breaks under iteration (BP-1 in [00_DISCOVERY.md §16](../00_DISCOVERY.md)) is moved behind the seam, not yet fixed; Phase 3 will replace it.

Conclude this step by:
- Implementing the core logic as the consumer rewiring across `app/services/activity_pipeline.py`, `app/routers/meetings.py`, `app/routers/realtime.py`, `app/routers/transfer.py`, and `app/data/meeting_manager.py`, with each rewired call site marked by a brief `Smug Otter` comment so the seam introduction is auditable.
- Creating or updating the relevant pytest file by extending `app/tests/test_meeting_manager.py`, `app/tests/test_api_meetings.py`, `app/tests/test_activity_plugins.py`, and `app/tests/test_transfer_api.py` with assertions that the rewired consumers produce identical observable behavior under `LinearAgendaStrategy`; introducing a new pytest module is not warranted because each rewired site already has a pinning suite.
- Updating docstrings and documentation so each rewired module's docstring records that agenda consultation now flows through `AgendaStrategy`, and so `docs/ACTIVITY_CONTRACT_SPEC.md` cross-references the seam from its DP-relevant sections.

Technical deviations logged:
- None.

### Step 4 — Mid-Meeting Creation Safety and Full-Suite Regression
Establish explicit test coverage that confirms `AgendaActivity` rows can be created safely while a meeting is running, from every legitimate caller path: router-driven (`POST /api/meetings/{id}/agenda`), strategy-driven (calls into the strategy's mid-meeting creation hook from within service code), and manager-direct (the future engine path that will invoke `add_agenda_activity` through the strategy seam). The test must exercise insertion into a non-empty agenda, immediate resequence behavior, ID minting via `_next_activity_identifier` per [00_DISCOVERY.md §3.5](../00_DISCOVERY.md), and the realtime broadcast envelope so connected clients learn about the inserted row through the existing `agenda_update` path. These assertions are the foundation Phase 3 will rely on when it introduces iteration-driven row creation; if any of them are weak now, BP-5 in [00_DISCOVERY.md §16](../00_DISCOVERY.md) becomes a Phase 3 surprise.

After mid-meeting creation safety is pinned, execute the complete pre-existing test suite and confirm zero regressions. Any test that fails under the rewiring must be diagnosed: a test that legitimately encoded a since-changed assumption is updated with the change called out in its docstring; a test that fails because of a behavioral drift in the strategy is a blocker that Step 2 or Step 3 must repair. Phase 2's central success criterion is "no observable behavior change to API clients, realtime clients, or the activity pipeline" — Step 4 is where that criterion is enforced.

Conclude this step by:
- Implementing the core logic as the mid-meeting-creation test scaffolding (placed in `app/tests/test_meeting_manager.py` and `app/tests/test_api_meetings.py`) plus any final wiring corrections the full-suite run surfaces, all carrying `Smug Otter` in their docstrings.
- Creating or updating the relevant pytest file by extending the two suites named above; do not introduce a new test module since the existing modules already own agenda-mutation coverage.
- Updating docstrings and documentation so the activity-pipeline, the strategy module, the meeting-manager, and `docs/ACTIVITY_CONTRACT_SPEC.md` each record that mid-meeting `AgendaActivity` insertion via the strategy seam is contractually safe under `LinearAgendaStrategy`.

## Phase Exit Criteria

Phase 2 clears only when the following command reaches `[100%]` and finishes without failures:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_meeting_state.py app/tests/test_meeting_manager.py app/tests/test_api_meetings.py app/tests/test_activity_plugins.py app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_rank_order_voting_api.py app/tests/test_categorization_api.py app/tests/test_frontend_smoke.py -v
```

Passing this command means:

- The `AgendaStrategy` interface exists at `app/services/agenda_strategy.py` and `LinearAgendaStrategy` is bound by default to every meeting touched by the suite.
- Every consumer enumerated in Step 3 routes through the strategy seam, with the narrow presentation-sort exception documented in code where it is used.
- The parity test in `app/tests/test_meeting_manager.py` confirms that `LinearAgendaStrategy` produces the same answers as direct `agenda_activities` walks across the representative topologies.
- The mid-meeting creation tests in `app/tests/test_meeting_manager.py` and `app/tests/test_api_meetings.py` confirm safe insertion under the seam from every legitimate caller.
- No test that previously passed regresses, and no test docstring or fixture name introduced under Phase 2 omits the `Smug Otter` canary where the step requirements call for it.

## Scope Boundary

This phase covers only the introduction of the agenda strategy seam and the channeling of existing consumers through it. The following items are explicitly deferred to later phases of [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md):

- Replacing the linear "previous activity" assumption with a non-linear resolution (BP-1) and admitting iteration discriminators on `ActivityBundle` (BP-3) — Phase 3.
- Authoring `BundleTransform` or `ConvergencePredicate` interfaces and the server-side reliability execution analogue (BP-7) — Phase 3.
- Authoring the orchestration-document schema, `OrchestrationEngineStrategy`, or any step kind beyond what `LinearAgendaStrategy` already represents — Phase 4.
- Engine-driven realtime broadcast envelopes that go beyond the existing `agenda_update` shape, and any facilitator-decision UI work — Phase 5.
- `orchestrations/delphi.json`, the end-to-end Delphi test, or `docs/DELPHI_VALIDATION.md` — Phase 6.
