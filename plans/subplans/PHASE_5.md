# PHASE 5 — Realtime and Frontend Coherence

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Discovery reference:** [plans/00_DISCOVERY.md](../00_DISCOVERY.md)
**Elaboration reference:** [plans/02_ORCHESTRATION_ENGINE.md](../02_ORCHESTRATION_ENGINE.md)

**Phase objective:** Ensure that engine-driven agenda mutations and engine-driven state transitions reach connected clients with the same fidelity as facilitator-driven ones, and supply the minimal facilitator-facing UI surface that the `facilitator-decision` and `ai-decision review_required` step kinds require to function in practice. Phase 5 resolves the two client-coherence breaking points identified in [plans/00_DISCOVERY.md §16](../00_DISCOVERY.md): the realtime broadcast assumption around a stable linear agenda (BP-5) and the frontend agenda cache that refreshes only on `agenda_update` envelopes (BP-10). When this phase clears, the engine authored in Phase 4 is operable through the existing meeting UI without participants experiencing divergent server-client state and without facilitators needing to refresh the page to respond to a decision.

**Manual-facilitation invariant:** Traditional facilitator-driven meetings remain a peer mode, not a legacy fallback. Phase 5 must not remove, weaken, or hide the existing linear-agenda controls that let facilitators add, reorder, start, stop, and transfer activities while a meeting is running. Packaged orchestration support is additive for the HICSS paper: it proves that a structured method can be executed declaratively over existing plugins while preserving the conventional live-facilitation path for ordinary meetings.

**Hybrid-scope decision for HICSS:** The paper-bound implementation only needs minimal, explicit human intervention points: `facilitator-decision` steps, `ai-decision review_required` approval, and the continued availability of ordinary facilitator-driven meetings. General ad hoc insertion into a running orchestration, and the rules for whether such inserted activities contribute to an orchestration's bundle history, convergence predicate, or provenance trail, are deferred until post-HICSS product tuning and facilitator feedback.

## Phase Canary

**Loquacious Pelican**

Use this exact two-word canary in Phase 5 notes, commit messages, module docstrings introduced by this phase, UI-template comments, JavaScript module headers, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — [DONE] Backend Broadcast Envelope for Engine-Driven Mutations
Every engine-driven change to the agenda — minting an `AgendaActivity` row for a new iteration round (per Phase 3's iteration storage model), advancing the engine's step pointer past a `facilitator-decision` or `ai-decision` resolution, or returning to the prior step inside an `iterate` block — must produce a realtime broadcast envelope identical in shape to the one a facilitator-initiated HTTP call already produces today at [`app/routers/realtime.py:52-55`](../../app/routers/realtime.py) and via the meeting-state patch path at [`app/routers/realtime.py:165-172`](../../app/routers/realtime.py). The engine must not invent a parallel envelope, a new WebSocket message type, or a new state-update verb; clients must learn about engine activity through the same pipes they already listen on.

The implementation work is therefore the inverse of inventing a new surface: it is wiring every engine-side mutation through the existing broadcast helpers. The `OrchestrationEngineStrategy` from Phase 4 emits broadcasts only as a side effect of its existing hooks (`next_activity`, `on_activity_close`) plus the new resumption entry point for `facilitator-decision`; no new public hook is added to the `AgendaStrategy` interface. The narrow exception is the resumption entry point itself, which must broadcast the chosen decision option (so paused clients see the resume reflected immediately) — this broadcast reuses the `agenda_update` envelope plus a meeting-state patch identical in shape to a facilitator-driven `currentActivity` advance.

Connected clients that do nothing must never need to reconnect or poll to learn about engine-driven changes; this is the load-bearing assertion the test extensions will pin.

Conclude this step by:
- Implementing the core logic as the wiring inside `OrchestrationEngineStrategy` and the surrounding meeting state path that ensures engine-driven mutations emit existing broadcast envelopes, with the `Loquacious Pelican` canary appearing at each emit site as a brief code comment so the wiring is auditable.
- Creating or updating the relevant pytest file by extending `app/tests/test_meeting_state.py` and `app/tests/test_api_meetings.py` with assertions that confirm an engine-driven mutation produces a broadcast envelope identical in shape to the facilitator-driven equivalent; no new pytest module is warranted, since both modules already own realtime-adjacent coverage.
- Updating docstrings and documentation so `app/routers/realtime.py`, `app/services/agenda_strategy.py`, and `docs/ACTIVITY_CONTRACT_SPEC.md` each record that engine-driven mutations reuse the existing broadcast envelope and explicitly identify BP-5 as resolved under `Loquacious Pelican`.

Technical deviations logged:
- Broadcast wiring was implemented as `app/services/orchestration_realtime.py` rather than directly inside `OrchestrationEngineStrategy`. The strategy is synchronous while websocket broadcasting and meeting-state patching are async, so the helper is invoked from async router/service boundaries after `create_activity` or `resume_with_facilitator_decision` returns. This preserves the Phase 2 strategy interface and avoids embedding event-loop concerns in the engine.
- Focused Step 1 assertions live in `app/tests/test_meeting_state.py` rather than `app/tests/test_api_meetings.py` because no orchestration router endpoint exists yet. The tests exercise the real engine strategy, meeting manager, meeting-state manager, and websocket broadcast helper directly; endpoint-level coverage remains appropriate for Phase 5 Step 3 when the facilitator-decision UI/resumption route is introduced.

### Step 2 — Frontend Cache Invalidation and Non-Linear Topology Rendering
Update the meeting-page JavaScript so that `state.agenda` and `state.agendaMap` accept the agenda topology produced by Phase 3's iteration storage model and Phase 4's engine — specifically, multiple activities that share a logical step identity but differ by iteration round, and activity rows minted mid-meeting by the engine. The frontend must continue to reflect engine-driven mutations purely through the existing `agenda_update` listener at the location identified in [plans/00_DISCOVERY.md §14](../00_DISCOVERY.md); it must not need a new WebSocket subscription or a polling path. When the engine mints a round-N activity row, the rendered agenda must surface that row in the right position relative to its round-(N-1) predecessor (rendered as a sibling, labeled by round, or whatever presentation choice the implementer takes, provided the choice is consistent and documented). The `currentActivity` resolution path at [`app/static/js/meeting.js`](../../app/static/js/meeting.js) must continue to identify exactly one active activity row at any time, matching the in-memory `MeetingState.current_activity` field surfaced by the backend.

Participants who are not facilitators must see no orchestration-specific UI affordances unless the orchestration document explicitly requests it; the participant view continues to behave as it did before the engine existed, with the only observable difference being whichever rendering choice the agenda topology takes for iteration rounds.

For non-orchestrated meetings bound to `LinearAgendaStrategy`, the existing facilitator agenda affordances remain visible and behaviorally unchanged. The frontend changes in this step are constrained to accepting engine-driven agenda topology; they do not redesign the manual meeting workflow or require facilitators to choose a packaged process when they want to improvise.

Conclude this step by:
- Implementing the core logic as the meeting.js (and any adjacent JavaScript module) changes that accept the engine-driven topology and render iteration rounds in a consistent, documented form, with the `Loquacious Pelican` canary appearing in the header comment of any JavaScript module substantially modified.
- Creating or updating the relevant pytest file by extending `app/tests/test_frontend_smoke.py` and `app/tests/test_pages.py` with assertions that the rendered agenda accommodates iteration rounds and engine-driven inserts without throwing or producing duplicated entries; no new pytest module is warranted, as both modules already own meeting-page rendering coverage.
- Updating docstrings and documentation so [docs/FRONTEND_DEV_GUIDE.md](../../docs/FRONTEND_DEV_GUIDE.md) records the agreed rendering convention for iteration rounds, so any HTML template comment relevant to the agenda region cites the convention, and so the spec's Engine section gains a "Frontend coherence" subsection that names BP-10 as resolved.

### Step 3 — Facilitator-Decision and AI-Decision Review UI Surface
Author the minimal facilitator-facing UI surface that lets a facilitator respond to a paused `facilitator-decision` step and approve or reject a `review_required` `ai-decision` result. Because the master plan ties these together — `ai-decision review_required` is resolved by the immediately-following `facilitator-decision` step authored in the orchestration document, per Phase 4 — they share a single UI surface rather than two parallel ones.

The minimal viable shape is a modal (or equivalent disclosed region) in the facilitator dashboard that appears when the engine pauses on a `facilitator-decision` step. The modal surfaces the `prompt` declared in the document, the `context_bundle_keys` rendered in a readable form (item content plus provenance per Phase 1's bundle schema), and the typed `options` as discrete affordances. Selecting an option calls the resumption entry point authored in Phase 4 Step 4 and immediately reflects the resumption in the agenda through the Step 1 broadcast envelope. When the preceding step in the document was an `ai-decision` with `review_required: true`, the modal additionally surfaces the AI's proposed result (validated against its `output_schema` per Phase 4 Step 5) so the facilitator's decision is informed by it. Approval and rejection are themselves expressible as typed options on the `facilitator-decision` step — the document author, not the UI, chooses the option labels.

The UI does not invent any new wire format. It calls existing endpoints (or one new endpoint that fits the existing router conventions if no existing endpoint accommodates the resumption call) and reacts to the standard broadcast envelopes. Aesthetic polish, animation, accessibility coverage beyond what the rest of the meeting UI already provides, and mobile-specific affordances are out of scope here — those are post-master-plan work.

Conclude this step by:
- Implementing the core logic as the new modal/disclosure component in the meeting templates and the JavaScript that drives it, plus any router endpoint required for the resumption call (named to fit existing router conventions), all carrying the `Loquacious Pelican` canary in their headers.
- Creating or updating the relevant pytest file by extending `app/tests/test_frontend_smoke.py` for the rendering coverage and `app/tests/test_api_meetings.py` for the resumption-endpoint coverage; the `ai-decision review_required` composition is exercised through the same fixtures by routing a Phase 4-authored orchestration document containing an `ai-decision` followed by a `facilitator-decision` through the end-to-end path.
- Updating docstrings and documentation so `docs/FRONTEND_DEV_GUIDE.md` records the decision-UI component's contract, so `docs/ACTIVITY_CONTRACT_SPEC.md` records the `review_required` user-facing flow alongside its existing engine description, and so the meeting template's region for the new modal carries a comment naming the canary and citing the spec.

### Step 4 — End-to-End Coherence Validation
Execute an end-to-end coherence run that exercises every Phase 5 surface against a real orchestration document: an engine-driven `iterate` block produces a round-2 agenda row whose mint triggers a broadcast that the frontend handles correctly; an embedded `ai-decision` with `review_required: true` produces a proposed result that the decision UI surfaces; the facilitator selects an option through the decision UI; the resumption broadcast advances the agenda; participant-view smoke confirms no orchestration-specific UI leaks to non-facilitators; and the entire flow occurs without any client needing to reconnect or poll. This run is the executable witness for the Phase 5 success gates in [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md), and it is the prerequisite for Phase 6's Delphi instantiation, which assumes that the engine's outputs are observable to a facilitator running an orchestration in practice.

Any drift discovered between the broadcast envelope shape (Step 1), the frontend's handling of it (Step 2), or the decision UI's interaction with the engine (Step 3) is diagnosed and repaired in the originating step rather than papered over here; this step's role is to surface drift, not to absorb it.

Conclude this step by:
- Implementing the core logic as any final wiring corrections the end-to-end run surfaces, with each correction tagged at its origin site under `Loquacious Pelican`.
- Creating or updating the relevant pytest file by extending `app/tests/test_orchestration_engine.py` with an end-to-end integration test that drives the engine through a fixture document containing `iterate`, `ai-decision (review_required: true)`, and `facilitator-decision` steps, asserts the broadcast envelopes, exercises the resumption endpoint, and verifies that participant-view and facilitator-view rendering each behave as specified; no new pytest module is needed because `test_orchestration_engine.py` already owns the engine integration concern.
- Updating docstrings and documentation so the spec's Engine section gains a closing "Phase 5 coherence witness" subsection that cites the end-to-end test as the executable proof, and so the master plan's Phase 5 row in any DP-to-test mapping reflects the test's location.

## Phase Exit Criteria

Phase 5 clears only when the following command reaches `[100%]` and finishes without failures:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_orchestration_engine.py app/tests/test_meeting_state.py app/tests/test_api_meetings.py app/tests/test_frontend_smoke.py app/tests/test_pages.py app/tests/test_meeting_manager.py app/tests/test_bundle_transforms.py app/tests/test_convergence_predicates.py app/tests/test_reliability_rehearsal.py app/tests/test_activity_plugins.py app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_rank_order_voting_api.py app/tests/test_categorization_api.py app/tests/test_ai_provider_config.py app/tests/test_agenda_validator.py -v
```

Passing this command means:

- Engine-driven agenda mutations produce broadcast envelopes identical in shape to facilitator-driven ones; connected clients learn about engine activity without reconnecting or polling.
- The meeting-page JavaScript correctly renders iteration rounds and engine-driven inserts; the `currentActivity` resolution continues to identify exactly one active row.
- The facilitator-decision / `ai-decision review_required` UI surface exists in the facilitator dashboard, calls the resumption entry point through existing wire formats, and observably advances the agenda on response.
- Existing facilitator-driven linear meetings still expose the current agenda controls and retain mid-meeting flexibility; orchestration support has not converted the traditional meeting path into a packaged-only workflow.
- The Step 4 end-to-end integration test drives a document containing `iterate`, `ai-decision (review_required: true)`, and `facilitator-decision` steps through the full engine + broadcast + UI pipeline and passes.
- No test that previously passed regresses, no participant-view smoke shows orchestration-specific UI affordances leaking to non-facilitators, and no test docstring, JavaScript module header, template comment, or fixture introduced under Phase 5 omits the `Loquacious Pelican` canary where the step requirements call for it.

## Scope Boundary

This phase covers only the realtime and frontend coherence required to operate the engine through the existing meeting UI. The following items are explicitly deferred to later phases of [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md):

- `orchestrations/delphi.json`, the synthetic-participant Delphi run, the IQR-stability convergence demonstration as a real method instantiation, and `docs/DELPHI_VALIDATION.md` — Phase 6.
- A second orchestration document (such as `estimate_talk_estimate.json`) demonstrating engine generalization beyond Delphi — Phase 6.
- Full hybrid facilitation semantics — including arbitrary facilitator-inserted activities inside a running orchestration and whether their outputs feed declared transforms, predicates, or paper-trace provenance — are deferred to post-HICSS feedback. Phase 5 protects the manual meeting path and ships explicit decision/review intervention points only.
- Aesthetic polish, animation, accessibility coverage beyond existing meeting-UI conventions, and mobile-specific affordances on the decision UI surface — post-master-plan work.
- Runtime implementation of the `conditional` control-flow primitive (defined-but-deferred at the schema layer in Phase 4) — out of scope for the entire master plan unless separately authorized.
- Empirical evaluation with real participant groups, parallel branches, sub-orchestration invocation with parameter passing, variable bindings, expression evaluation, event handlers, timers, and compensation/rollback — out of scope for the entire master plan per its Scope Boundary.
