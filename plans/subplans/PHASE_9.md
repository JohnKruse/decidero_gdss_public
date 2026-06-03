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

### Step 1 — [PENDING] Fork-and-Tune (the default path, highest coverage)

Make modifying a known-good method the easy, primary authoring path, since most
facilitators will fork rather than author from scratch. Build on the existing
template loop: start from a template, adjust labeled meeting-language parameters in
a form, save as a new custom template.

Conclude this step by:

- Exposing the method's tunable parameters (round limit, stop condition, who
  decides each round, activity titles/instructions) as a plain-language form on the
  template, with control-point internals pre-wired and hidden.
- Compiling form values back into a valid orchestration document via a single
  compile service, validated against `orchestration.schema.json` before save.
- Rendering the plain-language summary of the resulting method for confirmation.
- A facilitator pilot pass on "fork Delphi, change the stop condition and round
  limit, run it", with findings recorded.

### Step 2 — [PENDING] The Control-Point Card

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

- Mapping "who decides" to the Phase 8 gate mode; the "common" options to named
  computational predicates with default configs; "describe it in your own words" to
  an `ai-decision` rubric (prompt + output schema generated behind the scenes).
- Compiling the card to the iterate + gate structure and round-tripping it back
  into the card when editing an existing method.
- Plain-language validation (e.g. unbounded loop without a stop condition) surfaced
  inline.
- A facilitator pilot pass on building one control point from the card, with
  findings recorded.

### Step 3 — [PENDING] Show-It-Back Views

Provide the two confirmation views that every surface depends on.

Conclude this step by:

- A plain-language summary renderer for an orchestration document ("Repeat ranking
  up to 4 times, stopping when rankings stabilize; you decide each round").
- A simple read-only visual flow of the method (phases, loops, decision points).
- A dry-run/preview that shows what the next round/step would look like without
  running a live meeting.
- Wiring both views into Steps 1 and 2 as the confirmation surface.

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
