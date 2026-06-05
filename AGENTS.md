# AGENTS.md

Entry point for coding agents (Codex, Gemini, Claude). This is a navigation hub —
the detail lives in the linked artifacts; keep this file short.

## What this is
Decidero GDSS — a group decision support system (Python/FastAPI, SQLite) for
facilitated meetings with activity-based workflows. North star: a **HICSS 2027
paper** on executable collaboration engineering (Delphi as the reference method).
Judge implementation choices against which paper claim they support.

## Architecture — the 4 layers (do not blur them)
1. **Activities** (Layer 1) — frozen "Lego bricks": `app/plugins/builtin/`.
2. **Orchestration document** (Layer 2) — the method as DATA: `orchestrations/*.json`,
   grammar in `docs/schemas/orchestration.schema.json`, loader
   `app/services/orchestration_loader.py`.
3. **Engine + shared primitives** (Layer 3) — generic runtime:
   `app/services/agenda_strategy.py` + the predicate / transform / summarizer /
   recommender registries.
4. **Bundles** (Layer 4) — `docs/schemas/bundle_payload.schema.json`.
Method logic and control points live in **Layer-2 data, never in activities or the
engine**. Delphi is just one data file; everything coded is generic.

## Start here
- **Paper (north star):** `docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md`
  — the working design log; "implemented vs future" status lives here.
- **Active master plan:** `plans/01_MASTER_PLAN.md`; current phase subplan:
  `plans/subplans/PHASE_9.md`.
- **Recent feature record / next hand-off:**
  `plans/subplans/F1_JUSTIFICATION_ACTIVITY.md` — the outlier justification
  activity is implemented through collection API + meeting UI + Delphi
  orchestration swap; next useful increment is anonymized cross-round display of
  collected rationales.

## Key contracts / docs
- Activity plugin contract: `docs/ACTIVITY_CONTRACT_SPEC.md` (+ `_GUIDE.md`),
  manifest schema `docs/schemas/activity_manifest.schema.json`. Base class
  `app/plugins/base.py`; plugins register via `app/plugins/loader.py`.
- Orchestration grammar: `docs/schemas/orchestration.schema.json` (the loader is
  the authoritative runtime validator where they diverge).
- Meeting templates: `docs/MEETING_TEMPLATE_CONTRACT.md`.
- Delphi validation: `docs/DELPHI_VALIDATION.md`.

## Conventions
- **Tests must pass before a change is done.** Regression command (the agreed
  suite) is recorded in the project memory / `plans/01_MASTER_PLAN.md`; run with
  `PYTHONPATH=. ./venv/bin/pytest <files> -v`. Add new test files for new modules.
- Mirror the nearest existing implementation rather than inventing patterns
  (e.g. new per-user activity → mirror `rank_order_voting`: plugin + manager +
  `app/routers/rank_order_voting.py` + `app/schemas/` + the `meeting.js` panel).
- Don't break Layer boundaries (see above). Don't edit the engine to make one
  method work — push method-specific logic into the Layer-2 document.
- Branch for non-trivial work; keep commits focused; don't commit on the default
  branch.
- The frontend `app/static/js/meeting.js` is large — find the analogous tool block
  and mirror it; run `node --check` after edits.

## Layout
- `app/plugins/builtin/` activities · `app/services/` engine + managers ·
  `app/routers/` HTTP · `app/schemas/` request/response · `app/models/` ORM ·
  `app/templates/` + `app/static/` UI · `app/tests/` · `orchestrations/` methods ·
  `docs/` contracts + paper · `plans/` roadmap.
