# PHASE 9 — Facilitator-Shaped Authoring of Control Points

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Predecessor:** [plans/subplans/PHASE_8.md](PHASE_8.md) — generic runtime for advancement and cycle control
**Compile target:** [docs/schemas/orchestration.schema.json](../../docs/schemas/orchestration.schema.json)
**Paper outline:** [docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md](../../docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md)

## Phase Canary

**Plainspoken Marmot**

Use this exact two-word canary in Phase 9 notes, UI tests, authoring fixtures,
pilot reports, and commits tied to this phase.

## Why This Phase Exists

Phase 8 makes control points (iterate loops, decision gates, recommendation
sources) *runnable*. But today the only way to author them is to hand-edit the
Layer-2 orchestration JSON, which is an expert/developer task. The HICSS thesis is
that *facilitators* — who are typically not technical — can field reusable methods.
If instantiating a control point feels like editing JSON, that claim fails in
practice no matter how good the runtime is.

This phase builds the front-end translation layer that lets a non-technical
facilitator instantiate control patterns in meeting language, compiling their
choices down to a valid orchestration document they never see.

## Foundational Principle

**Never show JSON. Translate, don't expose.** The orchestration document is an
export/debug artifact, never the editing surface. The facilitator edits in meeting
vocabulary ("round", "stop when", "who decides"); the system compiles that to the
Layer-2 document. Every surface below is a different translation path onto the same
standardized schema. Nothing in this phase touches activities (Layer 1), the bundle
format (Layer 4), or invents a new document format.

## Iterative Posture

UX for non-technical authoring cannot be specified correctly up front; it must be
discovered by putting surfaces in front of facilitators. This phase is therefore
explicitly **evolutionary**: each step ships the smallest usable surface, runs it
in a facilitator pilot, and records findings that re-shape the next step. Step
ordering is by *risk-reduction and coverage*, not by ambition. Expect the later
steps to be re-planned from pilot evidence rather than built as written.

## Design Tenets (cross-cutting; apply to every surface)

- **Outcomes, not algorithms.** "When people stop changing their answers", never
  "IQR < 0.15". Curated, meeting-meaningful options map to Layer-3 primitives with
  sensible default configs under the hood.
- **One card per control point.** A loop + decision gate + recommendation source is
  instantiated through a single plain-language card (see Step 2), not a tree of
  nodes.
- **The recommendation duality is one question.** "Pick a common stop condition" vs
  "describe it in your own words" is a single choice in the UI; the first compiles
  to a computational predicate, the second to an `ai-decision` rubric. Same slot,
  two backends.
- **Show it back two ways.** After every change, render a plain-language summary
  *and* a simple visual flow for confirmation. Round-trip comprehension is the
  trust mechanism.
- **Validate in their language.** "This loop never stops — add a round limit or a
  stop condition", not a schema violation.
- **Default heavily, reveal progressively.** Everything pre-filled from a known-good
  method; advanced knobs stay collapsed.
- **AI drafts, human confirms.** When AI authoring is involved, the AI produces a
  first draft and an explanation; the facilitator is always the final authority and
  confirms via the show-it-back views, never by reading JSON.

## Reused Assets

This phase is mostly front-end plus one compile service. It reuses: the Phase 7
template fork/save loop, the `thinklets` and `collaboration_patterns` metadata
fields already in the orchestration schema, the Phase 8 `ai-decision` rubric engine
and recommendation-source seam, and `orchestration.schema.json` as the compile
target and validator.

## Atomic Steps

### Step 1 — [DONE] Fork-and-Tune (the default path, highest coverage)

Make modifying a known-good method the easy, primary authoring path, since most
facilitators will fork rather than author from scratch. Build on the existing
template loop: start from a template, adjust labeled meeting-language parameters in
a form, save as a new custom template.

Conclude this step by:

- [DONE] Exposing the method's tunable parameters (round limit, stop threshold, who
  decides each round) as a plain-language **Fork & tune** action on
  orchestration-backed template cards, with control-point internals pre-wired and
  hidden behind meeting-language prompts.
- [DONE] Compiling the choices into a valid orchestration document via a single
  compile service (`app/services/orchestration_authoring.py::apply_tuning`),
  validated through the loader (`orchestration.schema.json`) before save. The tuned
  document is stored **inline** on a new custom template and resolved at run time via
  a `template://<id>` path (no repo files, no schema migration).
- [DONE] Rendering the plain-language summary of the resulting method
  (`summarize_orchestration`) for confirmation, returned by the fork API and shown
  to the facilitator; also persisted as the template's method outline.
- [DONE] An end-to-end pass (automated): fork Delphi (change round limit / who
  decides) → create a meeting from the fork → the engine resolves the inline document
  and materializes the first step; the forked template starts like any other.

Technical deviations:
- The v1 form uses `prompt`/`confirm` interactions on the Meeting Templates page,
  consistent with the Phase 7 custom-template management style. A richer inline form
  with live preview is deferred until pilot feedback shows which knobs facilitators
  actually reach for — this phase is explicitly evolutionary.
- Tuning is parameter-level (round limit, stop threshold, who-decides). Editing
  activity titles/instructions and adding/removing steps is left to the Step 4
  pattern-block canvas; v1 fork-and-tune intentionally covers the highest-value knobs
  only.
- The facilitator pilot pass is recorded as automated end-to-end verification rather
  than a live naive-user session (the agent cannot run a human pilot), mirroring the
  Phase 7/8 handling. A live fork-and-run session remains a recommended next pilot.

### Step 2 — [PARTIAL] The Control-Point Card

Build the single plain-language card that instantiates a loop + decision gate +
recommendation source, as designed:

```
After each round of  [ activity ▾ ] …
  Who decides whether to do another round?
    ○ I'll decide   ◉ I'll decide — but show me a suggestion   ○ Decide automatically
  Base the suggestion on:
    ◉ Whether people's rankings have stopped changing   (common)
    ○ Whether most people now agree                      (common)
    ○ A fixed number of rounds
    ○ Describe it in your own words → [ … ]
  Stop no matter what after  [ N ]  rounds.
```

Conclude this step by:

- [DONE] Mapping "who decides" to the Phase 8 gate mode and common stop-condition
  options to named computational predicates for the v1 supported modes.
- [DONE] Mapping "describe it in your own words" to an `ai-decision` rubric
  (prompt + output schema generated behind the scenes). The compiled iterate
  sequence now runs the selected activity and then a schema-governed AI rubric
  verdict while retaining the existing convergence predicate as the hard fallback
  / round-cap guardrail; decompile reads the custom text back from the rubric
  instead of private metadata.
- [DONE] Compiling the card to the iterate + gate structure and round-tripping it
  back into the card when editing an existing method, via
  `app/services/orchestration_authoring.py` and the stateless template control
  point API.
- [PENDING] Full inline card UI and meeting-language validation surfaced on the
  authoring page. The server-side compile/decompile path and schema tests exist;
  the facilitator-facing edit surface remains to be completed.
- A facilitator pilot pass on building one control point from the card, with
  findings recorded.

Implementation record:
- Commit `eaaf903` added the control-point card schema, compile/decompile service,
  stateless API endpoints, validation through the orchestration loader, and focused
  tests. It also injects the activity catalog and stop-condition labels needed by
  the future UI.

### Step 3 — [PENDING] Show-It-Back Views

Provide the two confirmation views that every surface depends on.

Conclude this step by:

- A plain-language summary renderer for an orchestration document ("Repeat ranking
  up to 4 times, stopping when rankings stabilize; you decide each round").
- A simple read-only visual flow of the method (phases, loops, decision points).
- A dry-run/preview that shows what the next round/step would look like without
  running a live meeting.
- Wiring both views into Steps 1 and 2 as the confirmation surface.

### Step 3A — [DONE] Adaptive Delphi Controlled-Feedback Pass

Testing on 2026-06-06 changed the Delphi feedback direction. The next Delphi
increment should stop targeting participants as "outliers" and instead target
**least-converged ideas**. The facilitator chooses how many disputed ideas to open
for comment before reranking; everyone sees the same selected ideas; choosing zero
skips comments and moves directly to reranking.

Conclude this step by:

- Adding a Delphi feedback policy config to `orchestrations/delphi.json`, with
  defaults for `adaptive_least_converged`, a 25% high-disagreement suggestion,
  a 50% facilitator-selectable cap, and a zero-comments skip path.
- Computing item-level disagreement bands after each ranking round:
  green = low spread / high agreement, yellow = moderate disagreement, red = high
  disagreement. Start with IQR/spread as the primary score and rank variance as a
  tie-breaker.
- Showing the facilitator a compact agreement report at the round decision point:
  agreement trend, green/yellow/red counts, suggested number of ideas to open for
  comments, and a numeric selector from 0 to the configured cap.
- Reworking the comment phase into a comment-only selected-ideas activity:
  no new ideas, everyone comments on the same selected ideas, comments remain
  peer-anonymous, and each user can privately identify their own comments.
- Ordering Round 2+ ranking by the prior **group** result rather than each
  participant's private prior ranking. Show compact visual feedback instead of
  verbose stats: agreement color, prior group rank/median, the user's prior rank,
  round progression, and anonymized comments.
- Exposing the default comment workload during Delphi template instantiation:
  recommended adaptive mode, default suggestion fraction, and maximum comment cap,
  all phrased in meeting language.

Stage discipline:

1. [DONE] Config + docs: update `orchestrations/delphi.json`, schema/contract docs if new
   config fields need documenting, this plan, and the HICSS outline. Add validation
   tests proving the Delphi document still loads. Implemented by adding the
   `feedback_policy` config to the Delphi comment activity, exposing the defaults
   in the built-in Classical Delphi template metadata, and documenting the policy
   in `docs/DELPHI_VALIDATION.md`.
2. [DONE] Scoring service: add unit tests for band assignment, tie-breaking, small-N
   behavior, all-converged behavior, and adaptive suggested counts.
3. [DONE] Facilitator report/API: add API tests for agreement report payloads and
   skip / selected-count decisions; update plan and paper notes with exact
   semantics. The round-gate report now carries `feedback_selection` from the
   authored policy, and the orchestration advance / facilitator-decision state
   endpoints expose that payload.
4. [DONE] Comment-only selected-ideas UI/API: add backend tests for selected
   ideas only, no new ideas, anonymity, and user-owned comment labeling; add
   frontend smoke tests for hooks/rendering. The backend/API now supports
   `comment_scope: "selected_items"` with `selected_comment_items`, opens the
   same selected ideas to every participant, rejects non-selected submissions,
   reports selected-item progress to facilitators, and keeps the existing
   outlier-only mode intact. The meeting panel now uses selected-item-aware copy
   for progress, empty state, instructions, and comment placeholders. The
   facilitator round-gate report now renders a numeric selected-comment count
   control from `feedback_selection` and persists the chosen count in the
   facilitator-decision bundle, including max-count validation. Private "your
   comment" labeling is now done: the Round 2+ rank-order summary returns prior
   comments as `{text, mine}`, flagging the viewer's own comment from their
   private `OutlierRationale` rows without ever attributing peers in the bundle,
   and the meeting UI renders a "Your comment" badge. The selected-count decision
   is now applied before the comment activity opens: the next round's
   `outlier_justification` plugin reads the prior gate's `selected_comment_count`,
   scores the just-completed ranking, switches into `selected_items` mode, and
   seeds the top-N most-disputed ideas for everyone (count 0 → empty queue, a soft
   skip to reranking; no recorded decision → default outlier mode). This is
   Layer-1 plugin logic reading bundles, not an engine change. A true auto-advance
   past a zero-comment step remains future engine work; today the facilitator
   advances past the empty step.
5. [DONE] Group-ordered reranking + visual feedback: add regression tests
   showing all participants receive the same group-ordered Round 2+ list; add JS
   syntax/smoke checks for feedback badges and progression display. The backend
   rank-order summary now orders unsubmitted Round 2+ Delphi items by prior group
   median/IQR for every participant. The UI renders green/yellow/red agreement
   badges with compact group-rank text. Round progression is now done: the
   summary carries `delphi_round` ({round_number, max_rounds}) from the engine's
   read-only `round_progress_for`, and the rank-order panel leads with
   "Round N of M".
6. [DONE] Template instantiation controls: add fork/start-template tests proving
   selected defaults compile into the inline orchestration/template config; update
   facilitator-facing docs and Phase 9 status. `apply_tuning` now accepts
   `comment_default_fraction` / `comment_max_fraction`, validates them in meeting
   terms (0–100%, suggested ≤ maximum), and writes them onto every feedback-policy
   comment step. The fork API/manager expose the same two knobs, the inline forked
   document carries the tuned fractions, and `summarize_orchestration` describes
   the comment workload in plain language ("the most-disputed ideas are opened for
   comment — about N% suggested, up to M%").
7. [DONE] End-to-end Delphi regression: rank Round 1 with disagreement, facilitator
   opens N least-converged ideas, participants comment, reranking opens group-ordered
   with visual feedback, and continue/conclude still works. Verified by
   `app/tests/test_pages.py::test_adaptive_delphi_feedback_end_to_end`, which drives
   the real HTTP advance/control flow: Round 1 ranks with disagreement; the
   facilitator picks `selected_comment_count = 1` at the gate; starting the next
   round's comment step applies that decision (selected_items mode opens the single
   most-disputed idea to everyone); a participant comments through the justification
   API; and the Round 2 rank summary returns `delphi_round = {round_number: 2,
   max_rounds: 4}`. Full app regression green.

**Step 3A is complete.** All seven stages are DONE; the adaptive least-converged
controlled-feedback pass replaces the participant-outlier MVP end to end (config,
scoring, facilitator report/API, selected-idea comment apply-on-open, private
own-comment labeling, group-ordered reranking with round progression, fork-time
workload tuning, and the e2e regression). Future engine work (not blocking): a
true auto-advance past a zero-comment step instead of the current soft skip.

### Step 4 — [PENDING] Pattern Blocks on a Meeting-Flow Canvas (compose recognized patterns)

For facilitators who want to compose rather than fork, provide a palette of named
facilitation patterns (thinklets) pre-wired with their control structure, dragged
onto a meeting-flow canvas and parameterized in meeting language. Scope and shape
to be re-planned from Steps 1–3 pilot findings.

Conclude this step by:

- A palette of pattern blocks sourced from the `thinklets`/`collaboration_patterns`
  vocabulary, each compiling to a known-valid orchestration fragment.
- A canvas that sequences blocks and compiles the whole to a validated document.
- The control-point card (Step 2) used to parameterize loop/decision blocks.
- A facilitator pilot pass, with findings recorded.

### Step 5 — [PENDING] AI Co-Author (the on-ramp)

Let a facilitator describe a meeting in words and have the AI draft the document,
confirmed through the show-it-back views. This is the "Design with AI" surface
Phase 7 named. Scope and shape to be re-planned from earlier pilot findings.

Conclude this step by:

- A describe-your-meeting input that produces a draft orchestration document via the
  compile target, never exposing JSON to the facilitator.
- Confirmation/correction through the Step 3 summary and flow views, with the
  pattern blocks / control-point card as the editing fallback.
- Guardrails: AI output is validated against the schema; the facilitator confirms
  before anything is saved or run.
- A facilitator pilot pass, with findings recorded.

## Phase Exit Criteria

Phase 9 clears only when:

- A non-technical facilitator can instantiate at least one control point (loop +
  decision gate + recommendation source) without seeing JSON, via fork-and-tune and
  the control-point card.
- Both recommendation-source paths are authorable from the same UI slot: a curated
  computational stop condition, and a plain-prose AI rubric.
- Every authoring surface confirms changes through a plain-language summary and a
  visual flow; validation errors are stated in meeting language.
- All compiled documents validate against `orchestration.schema.json` before save
  or run; no authoring surface modifies an activity plugin or the bundle format.
- At least one facilitator pilot pass per shipped surface is recorded, and the plan
  has been re-tuned from those findings.

## Scope Boundary

This phase does not cover:

- Any change to activities (Layer 1), the bundle format (Layer 4), or the
  orchestration document format itself — Phase 9 is a translation layer onto the
  existing schema.
- New runtime/engine behavior — that is Phase 8.
- A live LLM advisor inside a running method's gate (Phase 8 seam; deferred there).
- Publication-grade evaluation of the authoring UX.
- A final, locked authoring UX — this phase is explicitly evolutionary and expects
  re-planning from pilot evidence.
