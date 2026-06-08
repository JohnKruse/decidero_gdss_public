# PHASE 9 — Facilitator-Shaped Authoring of Control Points

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Predecessor:** [plans/subplans/PHASE_8.md](PHASE_8.md) — generic runtime for advancement and cycle control
**Compile target:** [docs/schemas/orchestration.schema.json](../../docs/schemas/orchestration.schema.json)
**Paper outline:** [docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md](../../docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md)

## ⛔ SCOPE FREEZE (owner decision, 2026-06-08)

**No further facilitator-facing authoring is being built for the paper.** The
single goal now is to **ship the HICSS 2027 paper describing the orchestrator work
as it already stands.** Concretely, until the owner says otherwise:

- **Do not build, re-expose, or extend** any template authoring, forking, or
  tuning UI. The Step 1 fork-and-tune and Step 2 control-point-card *backends* exist
  and stay as-is; their visible entry points stay **hidden** (see
  [[do-not-reexpose-fork-tune]] / `test_..._without_fork_tune`). Do not wire them
  back in.
- **Do not build the AI co-author** (Step 5) or the pattern-block canvas (Step 4).
  Both are **CUT from the paper scope** and reframed as Future Directions — see
  those steps below.
- What remains for the paper is **prose + one pilot**, not new features. The
  orchestrator, the Delphi reference method, the decision/recommender primitives,
  the show-it-back views (Step 3), and the terminal report are all implemented and
  are the contribution the paper describes.

Anything an agent surveying this plan is "tempted to finish" is almost certainly
out of scope. When in doubt, the answer is: write the paper, don't build more.

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
- [DEFERRED] Full inline card UI and meeting-language validation surfaced on the
  template authoring page. The backend compile/decompile and fork-persistence
  path exists, but the visible `FORK & TUNE` entry point has been removed from
  the template page pending paper/pilot review of the correct authoring surface.

  > **DO NOT re-expose the `FORK & TUNE` / control-point-card entry point on the
  > template page.** This is an explicit owner decision (2026-06-08), not an
  > oversight or a leftover TODO. The backend (compile/decompile, fork persistence)
  > and the Step 3 show-it-back views exist, so an agent will be tempted to "finish
  > the loop" by wiring the button back in — don't. It stays hidden until the owner
  > says otherwise from pilot evidence. Keep `test_frontend_smoke.py::
  > test_meeting_templates_page_uses_horizontal_cards_without_fork_tune` passing.
- A facilitator pilot pass on building one control point from the card, with
  findings recorded.

Implementation record:
- Commit `eaaf903` added the control-point card schema, compile/decompile service,
  stateless API endpoints, validation through the orchestration loader, and focused
  tests. It also injects the activity catalog and stop-condition labels needed by
  the future UI.

### Step 3 — [PARTIAL] Show-It-Back Views

Provide the two confirmation views that every surface depends on.

Conclude this step by:

- [DONE] A plain-language summary renderer for an orchestration document ("Repeat
  ranking up to 4 times, stopping when rankings stabilize; you decide each round").
  `summarize_orchestration` (`app/services/orchestration_authoring.py`) now also
  surfaces on the template page (not just the fork API response).
- [DONE] A simple read-only visual flow of the method (phases, loops, decision
  points). New `app/services/orchestration_flow.py::build_flow_tree` walks the
  orchestration **document dict** into a JSON-serializable node tree; the template
  page renders it as nested plain-language boxes (sequence/iterate containers, an
  iterate loop-back accent, and decision pills for facilitator/AI/round-gate
  points). Rendered server-side as lightweight HTML/CSS — no Mermaid.js vendor, no
  graphviz binary, no committed images — so a just-created **fork** renders
  dynamically from its inline tuned document. (The paper-figure path remains the
  separate `to_mermaid`/`to_graphviz` exporter.)
- [DONE] A dry-run/preview that shows what the next round/step would look like
  without running a live meeting. For a *running* meeting this is the read-only
  next-step preview (`/orchestration/preview`, Step 3A advance-preview guardrails).
  For *authoring*, the static summary + flow above is the dry-run of the whole
  method.
- [DONE] Wiring both views into Step 1 as the confirmation surface: the new
  `GET /meeting/templates/{id}/flow` endpoint returns `{summary, flow}` for any
  orchestration-backed template (built-in or fork), lazy-loaded behind a "Method
  flow" disclosure on each card. Step 2's inline card UI re-exposure stays
  [DEFERRED] (see Step 2); when it returns it confirms through these same views.
- [PENDING] A facilitator pilot pass on the show-it-back views, with findings
  recorded (agent-run e2e + UI smoke stand in for now, per the Phase 7/8 handling).

Implementation record:
- New service `app/services/orchestration_flow.py` + endpoint
  `app/routers/pages.py::meeting_template_flow` + public accessor
  `MeetingTemplateManager.orchestration_document_dict`. UI: `meeting_templates.html`
  (disclosure + inline renderer) and `dashboard.css` (`.flow-node*` styles). Tests:
  `test_orchestration_flow.py`, flow API tests in `test_pages.py`, hook smoke test
  in `test_frontend_smoke.py`. Full suite green (816 passed, 2 skipped).

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

Operational UI guardrails added 2026-06-08:
- Orchestrated meetings now carry an explicit `data-meeting-is-orchestration`
  context flag into the meeting page.
- Past orchestrated agenda steps lock their Start buttons after the engine advances
  beyond them, while still allowing the current stopped step to restart before
  advance.
- Manual "Transfer Ideas" controls are hidden and the transfer panel is suppressed
  for orchestrated meetings, preserving transfer as a facilitator-driven linear
  meeting affordance rather than a templated-method control.
- If a facilitator is still selected on a past orchestration row, live state
  updates now auto-follow the current engine activity; this prevents the Delphi
  selected-comment phase from appearing as an empty/wrong facilitator panel.
- The generic brainstorming selected-comment surface now has a specific empty
  state for "no selected ideas open" to distinguish a real zero-comment decision
  from a loading or selection problem.

Operational UI guardrails added 2026-06-08 (advance preview):
- The orchestration strategy exposes a read-only next-step preview so the
  facilitator sees the likely upcoming activity or decision before clicking
  Advance.
- The Advance endpoint now rejects attempts to skip a materialized orchestration
  activity that has not produced an output bundle. In practice: Start/Stop the
  current activity first; it may be restarted while stopped until Advance is
  actually pressed.
- The Next Step panel consumes the preview endpoint and disables Advance with
  copy that explains both the immediate requirement and the likely next step.

### Step 4 — [CUT — Future Directions] Pattern Blocks on a Meeting-Flow Canvas

**Not being built for the paper** (scope freeze, 2026-06-08). A palette of named
facilitation patterns (thinklets) dragged onto a meeting-flow canvas was the
"compose rather than fork" surface. It is reframed as **Future Directions** in the
paper (the thinkLet composition tool / curated library — already tagged [FUTURE] in
the HICSS outline §D). Original sketch retained for the post-paper backlog:

- A palette of pattern blocks sourced from the `thinklets`/`collaboration_patterns`
  vocabulary, each compiling to a known-valid orchestration fragment.
- A canvas that sequences blocks and compiles the whole to a validated document.
- The control-point card (Step 2) used to parameterize loop/decision blocks.

### Step 5 — [CUT — Future Directions] AI Co-Author (the on-ramp)

**Not being built for the paper** (scope freeze, 2026-06-08). Letting a facilitator
describe a meeting in words and having AI draft the orchestration document is
reframed as **Future Directions**. The architectural seam exists and is described
as design, not as a demonstrated feature: the `ai-decision` step type, the
custom-stop-rubric compile path (Step 2 backend), and the recommender seam that can
take an AI-supplied `recommended_option` (HICSS outline §L.3) are the paper's
"AI proposes, facilitator disposes" story — as a *designed seam*, not a running
co-author. Original sketch retained for the post-paper backlog:

- A describe-your-meeting input that produces a draft orchestration document via the
  compile target, never exposing JSON to the facilitator.
- Confirmation/correction through the Step 3 summary and flow views.
- Guardrails: AI output validated against the schema; facilitator confirms first.

## Phase Exit Criteria (revised under the 2026-06-08 scope freeze)

The original exit criteria assumed a shipped, facilitator-facing authoring UX with
a pilot per surface. Under the scope freeze, **Phase 9's paper-supporting work is
considered complete**; the phase does not aim to ship a facilitator authoring UI.
What "done for the paper" means:

- The control-point primitives (loop + decision gate + recommendation source, both
  the computational stop condition and the prose AI rubric) are **authorable in the
  backend compiler** and validate against `orchestration.schema.json` before save or
  run — implemented (Steps 1–2 backends). No activity plugin or bundle format is
  modified by the compile path.
- Every method (built-in or fork) can be **shown back** through a plain-language
  summary and a read-only visual flow without exposing JSON — implemented (Step 3).
- The facilitator-facing authoring entry points (fork-and-tune, control-point card,
  canvas, AI co-author) are **deliberately not exposed**; whether/how to expose them
  is a post-paper, pilot-driven question, framed in the paper as Future Directions.

Remaining for the paper is **prose + one pilot/dry-run** (HICSS outline §6 item 9),
not new authoring features.

## Scope Boundary

This phase does not cover:

- Any change to activities (Layer 1), the bundle format (Layer 4), or the
  orchestration document format itself — Phase 9 is a translation layer onto the
  existing schema.
- New runtime/engine behavior — that is Phase 8.
- A live LLM advisor inside a running method's gate (Phase 8 seam; deferred there).
- **Any facilitator-facing authoring UI** — fork/tune, control-point card, pattern
  canvas, or AI co-author (scope freeze; Steps 1–2 stay backend-only, 4–5 are CUT).
- Publication-grade evaluation of the authoring UX.
