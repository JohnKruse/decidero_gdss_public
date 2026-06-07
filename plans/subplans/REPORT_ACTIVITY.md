# Report Activity — Terminal Deliverable + Reusable Brick

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Schema (data shape, pin first):**
[docs/schemas/report_payload.schema.json](../../docs/schemas/report_payload.schema.json)
**Paper outline:** [docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md](../../docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md)
(see the 2026-06-07 report note)

Status: **IMPLEMENTED THROUGH STEP 5.** Steps 0, 1, 2, 3, 4, and 5 are done,
including the live HTTP Delphi conclude-to-report-download pass. Remaining
optional cleanup: a synthetic in-repo example payload.

## Why

Two needs, one brick:

1. **Decidero needs a general Report activity.** A facilitator should be able to
   produce, and let participants download, something useful going forward —
   independent of method.
2. **Delphi has no designed ending.** Today the iterate loop just runs out of
   steps and `is_complete()` flips true; the de-facto deliverable is the last
   ranking bundle, with no consolidated results surface. Adding a terminal
   `report` activity to `delphi.json` makes the *ending a configured step* — which
   reinforces the paper's core claim that the whole method, including its
   conclusion, is Layer-2 data, not special-cased engine logic.

This is **not** the in-method facilitator read-out (the round-gate report, paper
§L.2). That informs a continue/conclude decision mid-run. This is the **terminal,
exportable deliverable**.

## Architectural placement

- **A new generic activity plugin (Layer 1): `report`.** Reusable in any meeting.
  Mirror the `rank_order_voting` skeleton (plugin + manager + router + schemas +
  meeting.js panel), but it is a **consume-and-synthesize** activity: it takes
  **no participant input**. It reads upstream output bundles (Layer 4) and emits a
  report.
- **Method-agnostic.** A small set of generic section renderers (narrative,
  key_value, table, ranked_list, comment_thread, rounds). Which bundle feeds which
  section, and which columns/labels appear, is **Layer-2 config** (+ the existing
  summarizer/transform registries). No `if delphi:` in the activity — same
  guardrail as the generic comment work.

## JSON is canonical; everything else derives from it

The report is built **once** into a structured model conforming to
`report_payload.schema.json`, finalized as the activity's **output bundle**, and
**re-rendered on demand from the stored model** (never recomputed). Format tiers:

- **JSON** — the payload verbatim. Lossless, schema'd, the source of truth. It is
  Decidero's own data type (bundles/orchestrations are JSON), so it round-trips:
  re-ingestable, diffable across runs, machine-addressable. Treat as **primary**.
- **Markdown** — human-readable rendering of the model (jinja2; already a dep).
- **DOCX** — polished/shareable rendering (needs `python-docx`; see decisions).
- **CSV** — the **tabular slice only** (`table` + `ranked_list` sections). Narrative
  and threaded comments are out of scope for CSV by design.

Renderers are pure functions of the model: `render_json`, `render_markdown`,
`render_docx`, `render_csv`. The on-screen preview is `render_html` over the same
model. Adding a format = one renderer, no new data path.

### Human formats render the COMPLETE sorted dataset — no truncation

Non-negotiable for CSV / DOCX / MD: each tabular section renders **every row from
the meeting**, sorted (final rank order), with **no top-N truncation** and no
"…" elision. Truncation/preview is only allowed in the on-screen `render_html`
preview, never in a downloaded artifact — the whole point of a download is the
full data.

The **primary table is the full item set + insight columns**, not a bare ranked
list. For the Delphi case that is one comprehensive table, one row per item, sorted
by final rank, with insight columns alongside:

`final rank · item · rank each round (R1…Rn) · net Δ · final median · final IQR ·
agreement band · % agreement · responses (n) · stable_key`

(The clean headline ranked list still exists for the "just the outcome" reader; the
full table is for the deep-dive reader.) Each renderer maps this one table model to
its idiom: CSV → the rows verbatim (a row per item, a column per field; one CSV per
tabular section), DOCX → a Word table, MD → a Markdown table. Column set comes from
the `table` section's `columns`, so adding an insight column is a builder change,
not a renderer change.

## Resolved decisions

1. **Narrative source — DETERMINISTIC ONLY.** No AI in the report. Prose is
   produced by jinja2 templates over the model, but it must *describe what
   happened* (per-round movement, convergence story), not just dump facts. The
   `body.ai_drafted` flag stays in the schema as a reserved slot but is unused in
   v1.
2. **DOCX — DONE.** `python-docx==1.1.2` added to `requirements.in` + lockfile.
3. **Charts — matplotlib (PNG).** `matplotlib` added to `requirements.in` +
   lockfile. Charts are stored as **data series in the canonical JSON**
   (`chart` section type) and rendered to PNG for DOCX/HTML; the underlying series
   is always also emitted as a table (CSV/MD/accessibility). **Use the headless
   `Agg` backend** (`matplotlib.use("Agg")`) — no display on the server.
4. **v1 scope.** Build the generic activity + Delphi as its first consumer
   together (cheap, pays the paper claim), rather than a Delphi-only one-off.

## What the report must convey (two audiences)

- **Headline (most consumers):** the final converged ranked list — clean, just the
  outcome.
- **Deep-dive (some consumers):** the *movement of the group toward consensus*.
  Concretely:
  - **Rank-trajectory table** — ideas as rows, a column per round + final + net
    move (Δ) + final median/IQR + agreement band. CSV-friendly (one column/round).
  - **Per-round narrative** — deterministic sentences: items entering agreement,
    median-IQR drop, top-spot swaps, why it concluded (convergence vs cap).
  - **Charts** (see below).

## Standard statistics + charts (the consensus story)

Most are already computed per round (median, IQR, dispersion, agreement bands);
two are new and worth adding as **registered, cited Layer-A metrics** (the §L.3
seam — `app/services/report_summarizers.py` registry), not bespoke code:

- **Kendall's W (coefficient of concordance)** per round + final — the canonical
  Delphi inter-rater agreement statistic (0→1, rising toward consensus). NEW
  metric; add with citation.
- **Round-to-round rank stability** — Spearman/Kendall-τ between consecutive
  rounds (how much the order churned). NEW metric.
- Per-item: final median/IQR/band, full per-round trajectory, net rank change,
  settled/volatile flag. Participation: responses per round, dropout.

Three standard charts, each stored as a `chart` section (data series) + drawn to
PNG, with the series table beside it:

1. **Convergence curve** (line) — median IQR and/or Kendall's W vs round.
2. **Rank-trajectory bump chart** (bump) — one series per idea, y = rank
   (`invert: true`); crossovers show the group dynamics.
3. **Agreement-band stacked bar** — green/yellow/red counts per round.

## The one real engine/contract extension

A report usually needs **more than the immediately-prior bundle** — for Delphi,
the whole round history (the `rounds` section / convergence trace), not just the
last ranking. Today `resolve_prior_activity` hands an activity its single input
bundle. So the genuinely new generic capability is **letting a consuming activity
read a set/lineage of upstream bundles**. Design this once, carefully — it serves
every future synthesis activity. Options to weigh:
- a config-declared set of `context_bundle_keys` (the decision/ai-decision steps
  already use this idea), resolved by the engine to a bundle list; vs
- a manager-side lineage walk by `logical_step_id` / `round_index`.
Prefer the config-declared, grammar-visible route so the AST/diagram exporter can
see the report's inputs.

## Sanity test against real data (2026-06-07)

Validated the schema + stats + render pipeline against a **real two-round Delphi
dataset** (BLS quality-appraisal checklist, 47/45 experts × 72/79 items, CC BY 4.0,
Mendeley `kjzvzt8b7h`). A `report_payload` built from the real data **validates
against the schema with zero changes**, all 8 section types populated; matplotlib
(Agg) rendered the three charts and `python-docx` produced a DOCX — all driven from
the canonical JSON. The validated payload + renderings were derived from
third-party CC BY 4.0 data, so they are **not committed** (regenerable from the
dataset); a small **synthetic** fixture should be authored in Step 0 as the
permanent in-repo example.

Findings that shape the build:

1. **Rating vs ranking — pick consensus metrics to match the paradigm.** Real
   Delphi here used Likert *ratings* (1–9) with consensus = median + IQR + %-agreement,
   not full *rankings*. Decidero models Delphi as `rank_order_voting`. The
   median/IQR/agreement-band/trajectory sections are paradigm-agnostic and worked
   well. But **Kendall's W needs rankings**: computed over saturated ratings (many
   9s → heavy ties) it compressed to 0.148→0.162 and *understated* the visible
   consensus, whereas the band shift (green 27→37) told the story clearly. So: W is
   the right consensus stat for **rank_order** data (Decidero's actual case); the
   report builder should select metrics by input paradigm rather than always
   computing W. The report consumes whatever the upstream activity produced.
2. **Items change between rounds (real).** 72→79 items, reworded/added/split;
   label-matching spanned 67. Confirms the design's reliance on **`stable_key`**
   (reuse the comment-seeding key) and **nullable trajectory points** for items that
   don't span every round — both already in the schema.
3. **Show multiple convergence signals.** Median IQR was flat (2.0→2.0) even as W
   rose and bands shifted green-ward — a single convergence number would have missed
   real progress. Validates the three-chart / multi-stat approach over one metric.

## Atomic steps (build order)

### Step 0 — [DONE] Pin the data shape
- `report_payload.schema.json` drafted (canonical model; generic section types;
  source provenance; round trace). Validated as well-formed; round-trips a
  Delphi-style example and a **real two-round Delphi dataset** (see Sanity test).
  **Pressure-test before writing renderers.**
- TODO: author a small **synthetic** in-repo example payload (`docs/schemas/examples/`)
  as the permanent fixture, since the real-data one is third-party and uncommitted.

### Step 1 — [DONE] Metrics, report model + renderers (no engine yet)

Implemented: `app/services/report_metrics.py` (cited Kendall's W + Spearman rank
stability + agreement bands), `kendalls_w` registered in the summarizer registry,
`app/services/report_builder.py` (deterministic round-bundles → canonical
`report_payload`, rank-order paradigm; full trajectory table, three charts, round
trace), `app/services/report_renderers.py` (JSON/CSV/Markdown/DOCX + chart PNGs via
matplotlib Agg; complete tables, no truncation). Tests: `test_report_metrics.py`,
`test_report_builder.py` (incl. no-truncation guard, W-rises-to-consensus). Builder
output validated against `report_payload.schema.json`. Deferred to Step 3:
`render_html` preview (lands with the UI).

Original spec:
- **Metrics** (registered, cited): add `kendalls_w` and `rank_stability`
  (Spearman/Kendall-τ) to the summarizer registry (`report_summarizers.py`),
  mirroring `delphi_round_agreement`. Each emits flat named scalars; each carries a
  citation. Unit tests: known-input agreement, all-agree → W=1, small-N.
- `app/services/report_builder.py`: build a `report_payload` dict (deterministic)
  from a list of round bundles + a Layer-2 report spec — including the
  rank-trajectory table, per-round narrative, and the three `chart` series
  (convergence curve, bump, agreement bands).
- `app/services/report_renderers.py`: `render_json/markdown/csv/html/docx` as pure
  functions of the model. Charts: `render_chart_png` via matplotlib with
  `matplotlib.use("Agg")` (headless); always also render the chart's series as a
  table so CSV/MD/accessibility are covered. DOCX embeds the PNGs (`python-docx`).
- Unit tests: model build from fixture round bundles; each renderer; CSV covers
  only tabular sections + chart series; renderer output stable for a fixed model;
  a chart PNG is produced headlessly. **Assert no truncation**: for a fixture with
  N items, the CSV/DOCX/MD primary table has exactly N data rows (regression guard
  against any top-N/"…" elision in a downloaded artifact); rows are in final-rank
  order; the insight columns are present.

### Step 2 — [DONE] `report` activity plugin (Layer 1)
- `app/plugins/builtin/report_plugin.py` + `PLUGIN` instance, registered in
  `loader.py`. Consume-and-synthesize: `open_activity` resolves the round history
  (`strategy.round_history`, falling back to the single input bundle for linear
  meetings), builds the model via `build_report`, and finalizes it as the output
  bundle (full report in `metadata.report_payload`; headline ranking mirrored as
  bundle items for export). No per-user submission surface.
- Test: `test_report_activity.py` drives a synthetic iterate+report doc through two
  rounds → the report step materializes after the loop concludes and builds a valid
  report (round_count, method, all section types, consensus winner first).

### Step 3 — [DONE] Download + preview API
- [DONE] Router `app/routers/report.py`:
  `GET .../activities/{aid}/report.{json|md|csv|docx}` renders the stored
  `metadata.report_payload` via the pure renderers and returns a
  `StreamingResponse` with `Content-Disposition`.
- [DONE] v1 access rule: report downloads are **facilitator-only** for now,
  matching the meeting export posture until participant download rights are
  deliberately broadened.
- [DONE] Backend tests: `test_report_api.py` covers each format's content type and
  payload, unsupported formats, missing output bundles, and facilitator-only auth.
- [DONE] `render_html` preview renderer over the same canonical model. Preview may
  elide long tables; downloaded artifacts remain complete.
- [DONE] `meeting.js` panel: facilitator-facing terminal report panel with server
  HTML preview and JSON/Markdown/CSV/DOCX download buttons.
- [DONE] Frontend smoke for the panel + buttons; `node --check`.

### Step 4 — [DONE] Engine: multi-bundle input for consuming activities
- `agenda_strategy.fetch_round_history(db, meeting_id, logical_step_id)`: all
  output bundles for a logical_step_id, ascending by round_index, deduped per round
  (latest id wins — re-entrant materialization never double-counts).
- `OrchestrationEngineStrategy.round_history(meeting, db)`: locates the document's
  iterate round-output series (`_find_iterates` + `_round_output_logical_step_id`,
  paths matching the walker) and returns its full per-round history. This is the
  multi-bundle input the report builder consumes — the whole history, not just the
  prior bundle. Tests: `test_round_history.py` (ordering/dedup; engine driven two
  rounds returns the ranking series in order; empty before any round).
- Note: kept as an engine read-side helper (no new grammar field needed for the
  single-iterate Delphi case). If a future report must target a *specific* one of
  several iterates, add a grammar-visible selector then.

### Step 5 — [DONE] Wire Delphi's terminal report

Fixed and wired (2026-06-07). `_completed_count` now counts the plan-aligned
population (excludes out-of-band gate decision rows, mirroring `_materialize_count`),
so `is_complete` is exact: a terminal in-plan step holds the method open until its
output bundle exists. Added the terminal `report` step to `orchestrations/delphi.json`
(after the iterate). Updated `test_phase6_delphi_synthetic_cohort_end_to_end` for
both the conclude path and the round-cap (runaway) path to the new
`conclude/cap → report materializes → report closes → complete` flow. Full suite:
801 passed, 2 skipped after Step 3 UI/API work. The live HTTP Delphi
conclude-to-report-download path is now covered by
`test_delphi_http_conclude_materializes_report_and_downloads`; the round-history
pieces remain covered by `test_report_activity` + `test_round_history` + the
engine completion tests.

#### History (the blocker, now resolved)

**Blocker found (2026-06-07): engine completion accounting.** Adding the terminal
`report` to `delphi.json` exposed that `OrchestrationEngineStrategy.is_complete`
can return True while the report is still pending. `is_complete` =
`walker.exhausted and _completed_count >= len(_plan)`, but `_completed_count`
counts **distinct activity_ids with an output bundle including out-of-band
facilitator-decision activities**, while `_plan` excludes those decisions. In real
Delphi the decision output bundles inflate `_completed_count` past `len(_plan)`, so
the `>=` heuristic reads complete even with an unmaterialized in-plan report step.
(A synthetic iterate+report doc with no decisions behaves correctly — is_complete
stays False until the report's output bundle exists — confirming the cause is the
decision-bundle surplus, not the plugin.) Only one existing test encodes the old
"conclude = complete" contract: `test_phase6_delphi_synthetic_cohort_end_to_end`.

**Fix direction (do first, separately):** make `_completed_count` count the same
population `_plan` does — plan-aligned activities only, excluding facilitator/gate
decision rows (mirror `_materialize_count`'s exclusion) — so `is_complete` is exact:
True iff every in-plan step has a closed output bundle. Then a terminal report
correctly holds the method open until it runs. Re-run the single phase6 test and
update it to the new `conclude → report materializes → report closes → complete`
flow. Only then add the terminal `report` step to `delphi.json`.

Original spec:
- Add a terminal `{"type":"activity","tool_type":"report", "config": {…spec…}}`
  after the iterate loop in `orchestrations/delphi.json`: headline converged ranked
  list (median/IQR/agreement band), run summary (incl. final Kendall's W),
  rank-trajectory table, per-round narrative, the three charts (convergence curve,
  bump, agreement bands), and cross-round comments.
- Update `docs/DELPHI_VALIDATION.md`; regenerate figures if the flow diagram
  changes. End-to-end: conclude Delphi → report materializes → downloads work.

## Guardrails (hold these)

- **One activity, configured — never fork.** No `report_delphi`, no `if delphi:`.
  New behavior becomes a generic section type or a config knob.
- **Canonical model first.** Never render a format from anything but the stored
  `report_payload`. No format-specific recompute.
- Comments stay peer-anonymous; `mine` is per-viewer at render time, never in the
  canonical model (the schema enforces this — no identity field on comments).
- Don't break Layer boundaries. The engine extension (Step 4) is *generic* bundle
  plumbing, not Delphi logic.

## Conventions
- Tests must pass before a change is done:
  `PYTHONPATH=. ./venv/bin/pytest <files> -v`; `node --check meeting.js`.
- Mirror `rank_order_voting` for the plugin/manager/router/panel skeleton.
