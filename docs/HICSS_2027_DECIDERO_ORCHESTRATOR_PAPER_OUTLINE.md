# HICSS 2027 Decidero Orchestrator Paper Outline

This outline is intended to remain close to the implementation plan. As the
system changes, the outline should be updated so that product work, technical
validation, and paper claims continue to reinforce one another.

## Working Title

Decidero Orchestrator: Executable Collaboration Engineering Through Activity
Contracts, Flow Control, and Reusable Meeting Templates

## Working Thesis

Although group decision support systems have long promised repeatable and
well-structured collaboration, complex facilitated methods still tend to depend
on experienced facilitators who can translate method guidance into moment by
moment meeting action. Decidero addresses this gap by treating collaboration
methods as executable and reusable software artifacts. Activity plugins provide
contracted building blocks, orchestration documents compose those blocks into
multi-step and multi-round flows, AI and facilitator decision points support
judgment-heavy transitions, and templates expose the resulting methods to
facilitators as ordinary meeting designs.

The paper should not present Delphi as the primary contribution. Delphi is the
reference case that lets us examine whether the Decidero architecture can
express and execute a known complex collaboration method without creating a
special-purpose Delphi activity.

## Contribution Frame

The paper likely makes four related contributions.

1. It defines an activity contract and harness for fielding custom
   collaboration activities. This includes manifests, ThinkLet metadata,
   bundle input and output, provenance, lifecycle idempotency, and reliability
   policy.
2. It introduces a small orchestration layer that composes activities into
   executable collaboration methods. The layer uses sequence, iteration,
   activity steps, facilitator decisions, AI decisions, transforms, and
   convergence predicates rather than method-specific activity plugins.
3. It uses AI as a facilitation aid inside flow control rather than only as a
   meeting agenda generator. The preferred pattern is that AI proposes and the
   facilitator disposes, especially where judgment or methodological risk is
   high.
4. It adds a meeting-template layer so reusable method designs can be selected,
   configured, saved, and reused by facilitators who should not need to
   understand orchestration internals.

## Reader Problem

Facilitators often need to run structured collaboration methods in settings
where the method matters, but training, time, and local expertise are limited.
The ThinkLet and collaboration-engineering traditions help by naming reusable
patterns of group interaction. Nevertheless, there remains a practical gap
between a reusable pattern in prose and a runnable meeting that can guide
participants, preserve handoffs, recover from failures, and help a facilitator
make the next move.

Decidero is positioned as an attempt to narrow that gap. The system does not
try to replace facilitation judgment. Rather, it attempts to encode enough of
the method structure, activity handoff, state management, and decision support
that less experienced facilitators can run more sophisticated meetings with
less bespoke preparation.

## Proposed Paper Structure

### 1. Introduction

Open with the practical problem: complex facilitated meetings can be valuable,
but they tend to be fragile when facilitation expertise is scarce. The
introduction should connect this problem to GDSS and collaboration engineering
without over-claiming that software alone solves facilitation.

The section should introduce Decidero as an implemented platform that explores
whether collaboration methods can be represented as executable artifacts. It
should close by stating that the paper summarizes the design of the activity
contract, orchestration layer, decision-support steps, and template path, then
uses a Delphi-style process as the reference implementation.

### 2. Background and Motivation

This section should briefly cover three threads.

First, ThinkLets and collaboration engineering provide a vocabulary for
reusable patterns of group interaction. They are useful because they move
facilitation knowledge from tacit expertise toward repeatable designs.

Second, GDSS tools often implement useful activities, but the connection among
activities is frequently left to the facilitator. As a result, the hard part of
complex methods often lives between activities rather than inside any single
activity.

Third, modern AI can assist with synthesis, review, and threshold detection,
but unreviewed AI automation is a poor fit for many facilitation decisions.
This motivates an architecture in which AI outputs can become structured inputs
to facilitator decisions.

### 3. Design Objectives

The design objectives should be stated as practical requirements rather than
abstract ideals.

1. Custom activities should be fieldable without changing the rest of the
   platform.
2. Activity outputs should be portable, provenance-preserving, and usable as
   downstream inputs.
3. Multi-step methods should be represented as reusable process artifacts, not
   as one-off code paths.
4. Iterative methods should support transforms, convergence checks, and bounded
   repetition.
5. AI should support, but not silently replace, facilitator judgment.
6. Reusable methods should be exposed through templates so they can be selected
   and configured by ordinary facilitators.

### 4. System Architecture

This section should describe Decidero in layers.

The first layer is the activity plugin contract. Each activity declares a
manifest, lifecycle hooks, collaboration metadata, and reliability policy. The
input, draft, and output bundle model provides the common handoff mechanism.

The second layer is the agenda strategy seam. The existing linear agenda is
one strategy, while the orchestration engine is another. This distinction is
important because it lets ordinary meetings remain simple while allowing
packaged methods to use richer flow control.

The third layer is the orchestration document. A document names a collaboration
method, records metadata and citation information, and defines a small control
flow over activities, transforms, predicates, AI decisions, and facilitator
decisions.

The fourth layer is the template surface. Templates are user-facing designs,
not meeting archives. They carry reusable structure and references to
orchestration artifacts, while excluding participant responses, votes, rankings,
timers, and other runtime data.

This section should distinguish ordinary agenda templates from orchestration
templates. An agenda template can pre-fill a relatively fixed activity
sequence. An orchestration template should instead expose a planned method
outline, runtime gates, possible decision points, and bounds. The system should
not overstate its knowledge of the future meeting by filling in activities that
may or may not be created depending on convergence, AI review, or facilitator
choice.

### 5. Reference Method: Delphi as a Composition

This section should explain why Delphi was chosen and what it demonstrates.
Delphi is useful because it is recognizable, multi-round, and dependent on
feedback between rounds. It therefore stresses exactly the parts of Decidero
that are supposed to matter: activity handoff, iteration, synthesis,
convergence, and facilitator oversight.

The key claim is that Delphi is represented as a composition rather than as a
special-purpose activity. The current reference document starts with
brainstorming, then iterates rank-order voting. Between rounds, a statistical
aggregation transform computes item-level median, interquartile range,
dispersion, and outlier flags. A convergence predicate evaluates whether the
median IQR has stabilized, while a maximum-round bound prevents open-ended
execution.

Crucially, the convergence predicate is a *recommendation*, not an automatic
gate. At each round boundary below the cap, the engine pauses and presents the
facilitator with the round evidence (round number, whether responses have
stabilized) and a plain continue/conclude recommendation; the facilitator
retains continue/conclude authority, and the maximum-round bound remains a hard
backstop. This is the concrete realization of the facilitation-support claim:
AI and statistical analysis inform a decision that a human still owns, rather
than silently automating method termination.

The user-facing Classical Delphi template should therefore be described as a
method outline rather than a completed agenda. The facilitator can see that the
meeting will generate items, enter an iterative ranking loop, produce feedback,
check convergence, decide round by round whether to continue, and stop at a
bound. The actual number of ranking rounds is not known at creation time; it is
materialized one round at a time as the facilitator advances the method, with a
per-request engine that reconstructs round state (including the prior round's
statistical feedback) from persisted data.

The section should be careful about method language. The implemented reference
case is a Delphi-style executable witness focused on iterative ranking and
statistical feedback. It is not a field evaluation of Delphi facilitation, and
it should not imply that every Delphi variant has been modeled.

### 6. Evidence and Validation

This section should separate implemented evidence from planned evidence.

Implemented evidence includes:

1. Activity manifest, bundle, provenance, idempotency, and reliability tests.
2. A ThinkLet audit that constrains built-in activity metadata claims.
3. Orchestration schema and loader tests.
4. Bundle transform and convergence predicate tests.
5. An end-to-end synthetic Delphi run.
6. A Delphi validation document that reports the synthetic cohort behavior.
7. A meeting-template contract and runtime-stripping tests.
8. An orchestration-backed template path: the Classical Delphi built-in template
   references the packaged Delphi orchestration document rather than a
   hand-authored Delphi-like agenda. A service layer turns the template into an
   orchestration-bound meeting with safe defaults for title, topic, participants,
   maximum rounds, and convergence threshold.
9. A complete v1 template CRUD surface: facilitators can browse built-in and
   custom templates, start a meeting from any active template, save an existing
   meeting as a custom template (with runtime data stripped), and rename,
   archive, or delete custom templates. Ordinary agenda templates and
   orchestration-backed templates are visually and functionally distinct.
10. A runnable facilitator cycle gate. An orchestration-backed meeting advances
    through the UI one engine-materialized step at a time, and at each iterate
    round boundary the facilitator is presented with round evidence, a
    convergence-backed continue/conclude recommendation, and authority to steer
    the loop. The choice genuinely changes execution: continue materializes the
    next round (with the prior round's statistical feedback carried forward),
    conclude ends the method, and the maximum-round bound is a hard backstop.
    The engine state is reconstructed per request from persisted rows, so this
    holds across the stateless web request boundary. Covered by per-request
    rehydration tests, round-gate steering tests, and an end-to-end Classical
    Delphi run driven through the gate.

Planned or incomplete evidence includes:

1. A pilot or internal dry run that examines whether facilitators understand
   Start from Template, Design with AI, Design Yourself, and Import Meeting
   without explanation, and whether the cycle-gate evidence and recommendation
   make the continue/conclude choice obvious without coaching.
2. Usability evidence about whether templates and decision-support surfaces
   lower the barrier for inexperienced facilitators, and whether the
   orchestration-backed method outline sets accurate expectations at runtime.

### 7. Discussion

The discussion should return to the ThinkLet vision. Decidero's contribution is
not that it invents new collaboration methods, but that it explores how method
knowledge can be made executable, reusable, testable, and easier to operate.
As a result, the system may help move from isolated activity tools toward
libraries of runnable collaboration processes.

The discussion should also be explicit about the tradeoffs. A small
orchestration language avoids the complexity of a general workflow engine, but
it also means the system currently supports only a limited set of flow-control
patterns. Similarly, AI can assist synthesis and review, but the architecture
intentionally keeps high-risk decisions reviewable by a facilitator.

### 8. Conclusion

The conclusion should be modest and forward looking. Decidero provides the
beginnings of an executable collaboration-engineering environment in which
activities, flow controls, AI assistance, and templates can be composed into
reusable meeting methods. Delphi provides the first substantive reference case.
The template layer — including the orchestration-backed Classical Delphi path,
save-as-template reuse, and the v1 management surface — is now implemented. The
remaining gap is pilot evidence: whether facilitators understand the four
creation paths without training, and whether the orchestration guidance at
runtime sets accurate expectations. That evidence, when collected, can
strengthen the claim that such methods are not only executable but also usable
by facilitators who do not have deep collaboration-engineering training.

## Implementation Work That Supports the Paper

Items 1–6 below are complete as of Phase 7 (Copper Compass). The remaining
work is the pilot.

1. ~~Replace the current hardcoded Delphi-like template with a template that
   references or instantiates the packaged Delphi orchestration.~~ Done.
2. ~~Add a service path from a meeting template to an orchestration-backed
   meeting, including safe defaults for title, topic, participants, maximum
   rounds, convergence threshold, and optional AI review.~~ Done.
3. ~~Keep ordinary agenda templates distinct from orchestration-backed templates.~~ Done.
4. ~~Show orchestration-backed templates as method outlines with runtime gates,
   not as fully pre-filled final agendas.~~ Done.
5. ~~Finish save-as-template and custom-template management for the reuse claim.~~ Done.
6. ~~Update the pilot guide so observations map to the paper claims.~~ Done.

Remaining:

7. Run a pilot or internal dry run using the session guide in
   `docs/USER_TESTING_GUIDE.md`. Record findings against the template path and
   the paper claims. Fix any blockers before a wider session.

## Terms To Keep Stable

- Activity plugin
- Activity contract
- Bundle
- Provenance
- Reliability policy
- Agenda strategy
- Orchestration document
- Bundle transform
- Convergence predicate
- AI decision
- Facilitator decision
- Meeting template
- Template
- Import
- Delphi reference case

## Current Risk To The Argument

The orchestration bridge risk is resolved: the Classical Delphi built-in
template now instantiates the packaged orchestration rather than a hand-authored
Delphi-like agenda. The template and orchestration paths are tested and the
meeting page shows the facilitator the planned method outline and runtime gates.

The remaining risk is in the UI and in the pilot. A complex flow is partly
preplanned and partly contingent. The UI should show the planned method and its
control logic, while making clear that later activities are materialized by the
engine as the meeting unfolds. If observational pilot findings show that
facilitators misread the orchestration guidance as a fixed final agenda, that is
a bug to fix before broader testing.

A second remaining risk is the evidence gap. The paper's usability claim rests
on pilot observation that the template and orchestration surfaces lower the
training burden. Without at least one observed session, the claim must be
qualified as architectural rather than empirical.

## Session Design Notes — 2026-06-04 (capture so it is not lost)

These notes capture a working session that materially strengthened the design
argument. Tags: [DONE] = implemented + tested in the repo; [FUTURE] = explicitly
deferred / Future Directions; [FIGURE] = paper graphic idea; [VENUE] = publishing
strategy. The throughline: **a collaboration method is a recursive composition,
and the engine is a small stack interpreter that already supports it.**

### A. The reframe: a round is a cycle of subcycles [DONE for Delphi]

The earlier framing treated the Delphi loop as a single repeated activity
(`iterate[rank_order_voting]`). The corrected, stronger framing: each Delphi
*round* is itself a multi-step **subcycle** — review the prior round's feedback,
(optionally) justify outlier positions, then re-rank. So the method is a
*cycle of subcycles*, not a flat loop.

Implemented: the Delphi round body is now a nested
`iterate -> sequence([Review-and-Justify (brainstorming), Re-rank
(rank_order_voting)])`. The justification step reuses the brainstorming tool. It
is placed first so the re-rank stays last and the IQR convergence predicate reads
the ranking output. (`orchestrations/delphi.json`.)

### B. The engine is a recursion (stack) machine — one level now [DONE]

Key realization: the orchestration engine (`_PlanWalker` in
`app/services/agenda_strategy.py`) is **already a stack-based interpreter** — a
frame stack where each frame holds its steps + a pointer ("where it started, is
now, is going"). Descending = push (call); finishing = pop (return). Sequences
already nested arbitrarily; the only thing blocking deeper nesting was a single
deliberate guard.

Implemented this session (one level of recursion):
- Lifted the "no nested control flow in iterate" guard so an iterate body may
  contain a `sequence`, which the walker pushes as a frame.
- Propagated the enclosing iterate's **round context** (round_index + frame) to
  leaf activities inside a nested sequence, so feedback injection and iteration
  metadata keep working.
- `_collect_round_output` now descends to the round's **terminal leaf** activity
  (`_last_leaf_logical_step_id`) so round-output lookup works on the per-request
  rehydration path (the same path that caused an earlier premature-"complete"
  bug — now fixed and regression-tested).

Deliberately deferred [FUTURE]: `iterate`-inside-`iterate` (nested loops with
independent convergence). One level of nesting fully backs the "recursion engine"
claim; Delphi does not need nested loops.

### C. Control flow recurses for free; data does not [partly DONE, design FUTURE]

Recursion handles **control flow** cheaply. **Data flow** needs an explicit
model. The elegant design (mirror of the control stack): each frame also carries
an **input slot, an output slot, and a scope** — i.e., a thinkLet is a *function
with a typed bundle contract* (input = parameters, output = return value,
internals = locals). This maps onto pieces that already exist:
`transform_input` ≈ parameters, `bundle_transform` ≈ return transform,
`_collect_round_output` ≈ return value, `_IterateFrame.bundle_history` is already
frame-local (so convergence composes under nesting for free), and
`contract_schemas.validate_bundle_payload` can type the ports. Recommendation:
**explicit named bindings, not implicit lexical scope** (predictable + validatable
for a research tool). Citation hook: scientific-workflow systems (Taverna, Kepler,
Pegasus) solve exactly this with typed ports + nested-loop scoping. The general
I/O-contract layer is [FUTURE].

### D. ThinkLets as composable fragments — the composition tool is FUTURE

Per Collaboration Engineering (Briggs / de Vreede / Nunamaker), a thinkLet is
the smallest reusable unit that yields a predictable pattern of collaboration —
*tool + configuration + rules/script*, not just a tool. Today in the codebase
`thinklet` is only a descriptive tag (`ActivityPluginManifest.thinklets`,
document metadata), not a building block. The vision: a **palette of thinkLets**
that are combinations of activities, which the composer drops in and **expands**
at authoring time into the existing step grammar — so the engine never changes
(thinkLets resolve to plain steps). The Delphi round subcycle is itself a
thinkLet. NOTE: the user explicitly is *not* asking for the authoring/composition
tool now — it is Future Directions. Start with a small curated library before a
general nested composer (over-abstraction risk).

### E. Runaway safety: static for #1, dynamic for #2 [FUTURE, clean theory split]

A tidy theoretical contrast worth writing up:
- **Static composition (#1, what we built):** thinkLet references form a
  directed graph; safety = the graph is a **DAG**. Detect cycles at author/save
  time (DFS gray/black coloring, or Kahn topological sort, O(V+E)) + a max
  expansion-depth cap. Runaway is eliminated *by construction* — same mechanism
  as build systems (Make/Bazel), package managers, spreadsheet circular-ref
  detection, compiler include/`-ftemplate-depth` limits.
- **Dynamic dispatch (#2, FUTURE):** a thinkLet picks its successor at runtime;
  the call graph is data-dependent, so static acyclicity is insufficient. Needs
  runtime **resource budgets / "fuel"** (cf. Ethereum gas; the repo already has
  `max_rounds` caps and a 20-round runaway trip in tests) and optionally
  **termination analysis** (well-founded ranking functions / size-change).

Frame in the paper as **static safety vs dynamic safety** — a clean methods
contribution.

### F. Controlled feedback + outlier justification (Delphi fidelity)

- **Feedback display [DONE]:** the engine already computes per-item median, IQR,
  dispersion, and outlier flags between rounds (`DelphiStatisticalAggregation`)
  and feeds them forward as `previous_round_feedback`. This session surfaced them
  to participants: rounds after the first now show the prior round's group median
  rank + spread (IQR) beside each item in the re-rank UI. This is the visible
  feedback loop that makes it behave like real Delphi.
- **Outlier rationales [FUTURE, justification step is DONE structurally]:** in
  classical Delphi the *outlier participants themselves* write the rationales
  (not the facilitator, not AI). Anonymity is **peer-anonymity, not
  system-anonymity** — the system must know identities to route the "please
  justify" prompt and compute outliers; peers see unattributed rationales.
  Caveat to state in the paper: **small-N panels leak** (with ~6 participants and
  one outlier, peers can infer identity) — mitigate by only ever showing
  aggregates + unattributed text. The structural justification step exists; the
  anonymized cross-round display of rationales is the next increment.
- **Facilitator 3-way gate [FUTURE]:** "conclude / revote / revote-with-
  justification" needs per-round branching = the deferred `conditional` step /
  dynamic dispatch. Current gate is binary continue/conclude.

#### F.1 Justification activity — design spec [FUTURE; current step is a placeholder]

Decided 2026-06-04: the shipped Delphi's justification step currently *reuses the
brainstorming tool* as a thin placeholder (a free-text "Explain Your Ranking" box
that follows the ranking). That is not the real thing and must not be presented
as the finished method — it is a stand-in so the round subcycle exists and the
recursion engine is exercised. The proper step is a **purpose-built justification
activity**, specified here so it can be built later (it slots into the existing
subcycle where the placeholder sits — **no engine change needed**):

- **Per-viewer content, one activity (not N activities).** A single activity that
  renders different content per participant — the same pattern `rank_order_voting`
  already uses (shared state, per-user ballot). Each participant sees only *their*
  items needing justification.
- **Outlier-driven queue.** The set of items participant P must justify is already
  derivable: every item where `metadata.delphi.outlier_flags[P] == True` (computed
  by `DelphiStatisticalAggregation`; no new computation). Render it as a
  drive-to-action queue: per item, show the item, P's own rank, the group median +
  IQR, and a comment box — "You ranked X at 2; the group median was 7. Why?"
- **Comment-only, seeded set, no new items.** The activity is constrained to
  commenting on the flagged items; no idea creation. This is precisely what
  brainstorming cannot enforce, which is why a new activity type is required
  rather than configured brainstorming.
- **Zero-outlier participants** see "nothing needs your justification this round"
  and are done.
- **Cross-round anonymized display.** Collected rationales attach to their items
  and surface in the *next* round's ranking view, **unattributed** ("others who
  ranked this differently said: …"). Peer-anonymous only; per the small-N caveat,
  show aggregate + unattributed text, never per-person.
- **Build surface (multi-day):** new plugin (manifest + lifecycle +
  comment-only validation), storage for per-user-per-item rationales (a bundle or
  small table), a new UI panel with the per-viewer queue, outlier derivation from
  the input bundle, and the next-round anonymized display. The recursion engine
  already hosts it; this is activity-layer + UI work, not engine work.

### G. Per-phase interstitials [DONE]

Because the participant's task *changes* across the subcycle (review feedback →
justify → re-rank), each phase shows a short click-through "what to do now" note.
Implemented as a dismiss-once inline notice above the active activity. The
facilitator-decision rows also dropped their run controls (no participant
session), and the advance/continue control moved to a panel below the current
activity.

### H. [FIGURE] Communicating recursion via graphics + JSON

This is highly doable and is the most communicable part of the design, because
**the recursion is literally a tree in the JSON** — structure and figure are the
same object.
- **Anchor figure:** `delphi.json` on the left (nested `iterate -> sequence ->
  [justify, re-rank]` highlighted) ↔ a diagram on the right, color-keyed node to
  JSON block.
- **Diagram idiom:** nested containment boxes (iterate = box with loop-back arrow
  containing the subcycle box containing the activity tiles) — same idea as the
  indented agenda tiles in the UI, so figure and product reinforce each other.
  Alternative: a node-link AST tree.
- **Optional runtime figure:** the stack machine pushing/popping frames as it
  materializes round 1 then round 2 — visualizes "where it started / is now / is
  going" and shows static structure unfolding into the round-by-round agenda.
- **Methods clincher [DONE]:** an exporter walks the parsed AST
  (`SequenceStep`/`IterateStep`/`ActivityStep`) and emits **Mermaid and Graphviz
  DOT directly from any orchestration document**, so figures are *generated from
  the real artifact* (cannot drift) and reusable for every method. Implemented in
  `app/services/orchestration_diagram.py` (`to_mermaid` / `to_graphviz`); CLI at
  `scripts/export_orchestration_diagram.py`; generated Delphi figure +
  regeneration/rendering instructions in `docs/figures/` (README embeds the
  Mermaid, which renders on GitHub). This is also the seed of a future "show the
  DAG in the UI" feature.

### I. [VENUE] Conference vs journal

The contribution has journal-level depth as **Design Science Research** (artifact
+ design theory: recursion engine, thinkLet composition, static-vs-dynamic
safety). But it is not either/or, and the HICSS deadline dominates: **ship the
focused HICSS 2027 conference paper** (priority, GDSS-community feedback, forcing
function; recursion/thinkLet/DAG material framed as design + Future Directions),
then **extend to a journal** post-deadline with the composition engine built out
and real (ideally multi-cohort) pilot data. Journal homes: **Group Decision and
Negotiation (best fit)**, JMIS, Decision Support Systems, or DSR-framed JAIS/MISQ.
HICSS best papers are often invited to journal special issues; IS journals expect
~30%+ new material over a conference version. Do not let journal ambition bloat
the conference scope.

### J. Status summary for the paper's "implemented vs future" split

- [DONE] Delphi round as a nested subcycle (rank → justify); one-level recursion
  in the engine; prior-round median/IQR feedback shown to participants; per-phase
  interstitials; premature-"complete" gate bug fixed; dashboard focus-refresh; the
  AST→Mermaid/Graphviz figure exporter (generates the recursion figure from the
  real document).
- [FUTURE / Future Directions] nested iterate-in-iterate; the general I/O-contract
  data model; the thinkLet authoring/composition tool + curated library; the DAG
  validator + cycle/depth safety; dynamic dispatch (the 3-way facilitator gate);
  the purpose-built justification activity (per-viewer outlier queue, F.1) +
  anonymized cross-round display of rationales; the in-UI DAG visualization;
  the unified decision primitive + generic report summarizer + two-layer
  recommender (section L).

### K. Post-paper backlog (circle back after the deadline)

Explicit "do later" list captured 2026-06-04 so it is not lost:

- **Skip-the-justification control.** Let the facilitator choose, at the round
  boundary, to *skip* the justification sub-step (run-justification vs continue
  directly). The decision surface is easy; making the engine actually *skip* an
  activity from a choice needs conditional/branching execution (the deferred
  `conditional` step / dynamic dispatch, section E/F). Defer.
- **Anonymized cross-round display of rationales.** Collected justification text
  shown back to the group, unattributed, on the next round's ranking screen
  (peer-anonymous; mind the small-N leak). Pairs with the justification activity
  (F.1). Defer.
- **Justification activity itself** beyond the MVP — richer review surface,
  optional comments on non-outlier items, etc. (F.1 is the spec.)

## Session Design Notes — 2026-06-05 (genericizing flow controls + reports)

Continuation of the 2026-06-04 notes. Working frame from this session: the
orchestration has **three load-bearing features** — (1) recursiveness, (2)
control/flow controls, (3) flow reports back to the facilitator (and sometimes
participants) — and *most reports are attached to a flow control* (the facilitator
gets a read-out in order to decide continue/skip/conclude). Recursion (1) is
[DONE] (sections A/B). This session designed how to **genericize (2) and (3)** so
they are first-class grammar primitives rather than Delphi-specific bolt-ons.
Status: design [FUTURE]; the pre-unification forms (`round_gate` enum,
`round_statistics.py` report-out) are [DONE] but are the things being generalized.

### L. Unify the decision primitive; make reports + recommendations generic [design FUTURE]

#### L.1 Unify `round_gate` into `facilitator-decision` [design FUTURE]

Today there are two decision shapes: the authored `facilitator-decision` step
(prompt + options + `context_bundle_keys`) and the inline `round_gate` on
`iterate` (an enum `recommendation: convergence|ai`). These are the *same
primitive* — a branch point where a human chooses — in two shapes. Unify so the
`facilitator-decision` schema is the single decision shape, and `round_gate`
**embeds** it rather than being a parallel enum:

```jsonc
// iterate node
"round_gate": {
  "decision": {                          // ← the shared facilitator-decision shape
    "prompt": "Continue to another round, or conclude?",
    "options": ["continue", "conclude"],
    "context_bundle_keys": ["round_ranking"],
    "report": { ... },                   // L.2
    "recommender": { ... }               // L.3
  },
  "recommended_option": "continue"       // resolved at runtime; references decision.options
}
```

Important: unify ≠ flatten into the `steps` array. The gate keeps two properties
an authored step lacks — it is **engine-injected at iterate boundaries** (fires
each round below the cap), and `max_rounds` stays on `iterate` as the hard
backstop. What moves is the *schema*: one decision shape, reused.

**Paper story:** the grammar goes from "5 step kinds, one carrying a special gate
field with its own recommendation enum" to **"4 orthogonal step kinds; iteration
boundaries reuse the decision primitive."** Reviewers reward grammar minimality.
Cost to acknowledge: `iterate` now references the decision schema, so they evolve
together (minor, right trade). This also subsumes the F/section-E "3-way
facilitator gate" cleanly — extra branches are just more `options`.

#### L.2 Reports as a named summarizer (the dual of the convergence predicate) [design FUTURE]

`round_statistics.py` is the tell for the gap: the report-out is **hardcoded to
Delphi** (reaches for `delphi_statistical_aggregation`, bakes in IQR agreement
labels) and **invisible to the grammar** — it's a side REST endpoint auto-opened
"at the justification step" by frontend convention, so the AST and the diagram
exporter (section H) can't see it.

Genericize it with the registry pattern already used for `convergence_predicate`
and `bundle_transform`: a **report = a named summarizer (registry) + config + an
`audience`** (`facilitator | participants`).

```jsonc
"report": {
  "summarizer": "delphi_round_agreement",   // registry name
  "config": { "strong_iqr": 1.0, "contested_iqr": 2.0 },
  "audience": "facilitator"
}
```

Framing sentence for the paper: a report is the **human-facing dual of a
convergence predicate** — both are read-only projections over the same round
bundle; the predicate reads it → verdict, the report reads it → display. This
pulls the Delphi specifics out of core code into a registered summarizer, and
makes the report first-class to the AST (so the diagram exporter draws it).
Placement: an optional `report` on the unified `facilitator-decision` (the
motivating case — read-out informs the gate, reuses `context_bundle_keys`), and
later a standalone `report` step kind for participant-facing report-outs not
gated on a decision.

#### L.3 The recommendation seam: split computation from decision; never carry code [design FUTURE]

Question that prompted this: do we need a "code-carrying" capability for counts /
statistics / selections in the recommender? **No — resist doc-carried code** (it
wrecks reproducibility, muddies provenance, forces sandboxing). Instead recognize
two layers wanting two mechanisms:

- **Layer A — metrics (statistics, counts, outlier detection).** Genuinely
  methodological and *citable* (median/IQR, IQR-stability, tallies). Keep as a
  **registry of named, cited, config-parameterized Python primitives** — same seam
  as `convergence_predicate`/`bundle_transform`. New statistical method = reviewed
  registry entry with a citation (rare, *should* require rigor). The one contract
  change: primitives emit a **flat namespace of named scalar facts**
  (`median_iqr`, `contested_items`, `participant_count`, `converged: bool`) —
  which `round_statistics.py` already computes; we just name the outputs.
- **Layer B — selection/recommendation.** "Given those facts, which option do I
  suggest?" Safe to make **declarative** *because it operates on scalars, not raw
  data*. A small ordered guard rule, no code:

```jsonc
"recommender": {
  "metrics": ["delphi_round_agreement", "iqr_stability"],   // Layer A refs
  "rule": [
    { "when": "converged",         "recommend": "conclude" },
    { "when": "median_iqr <= 1.0", "recommend": "conclude" },
    { "default":                    "continue" }
  ]
}
```

This produces the `recommended_option` on the unified decision (L.1). Two
payoffs: (a) it **absorbs `convergence_predicate`** — the verdict (`converged`)
is just one fact in the namespace, so the old `recommendation: convergence|ai`
enum becomes a generic `recommended_option` pointer suppliable by *any*
recommender (convergence rule today, AI later — same seam, no special case);
(b) authors compose new *policies* in pure JSON while new *methods* extend a
reviewed library.

**Guardrail to write down (scope-creep defense):** Layer B is **ordered
`when`/`default` guards, comparisons and booleans over scalar metrics only — no
arithmetic, no loops, no data access.** When an author wants more than the rule
can express, that is the signal to add a **registered Layer-A metric**, not to
grow the DSL. This keeps the expressiveness ceiling fixed and the mini-language
tiny (the only way it stays maintainable).

**Paper framing:** "a curated, literature-grounded library of metrics + a thin
declarative recommendation rule" is reproducible and citable; "documents carry
arbitrary code" is a reviewer red flag. The split is a contribution, not a
limitation — and it lines up with the static-safety theme (section E): bounded,
inspectable composition over executable payloads.

#### L.4 Build order when this is picked up [FUTURE]

Schema + loader (`orchestration.schema.json`, `orchestration_loader.py`): add the
`report` and `recommender` sub-objects to `facilitator-decision`; make
`round_gate` embed the decision shape + `recommended_option`; retire the
`recommendation` enum. Engine: resolve `recommended_option` from the recommender
at the iterate boundary; render the `report` to its `audience`. Registries: a
summarizer registry (seed with `delphi_round_agreement`, migrating the logic out
of `round_statistics.py`) and the Layer-A metric-namespace contract. Diagram
exporter (section H): draw report/decision nodes. All activity/engine-layer; no
new recursion machinery.
