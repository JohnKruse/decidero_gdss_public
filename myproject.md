# Decidero GDSS Project

Decidero is a FastAPI and SQLite group decision support system for facilitated,
activity-based meetings. Its current research reference method is Classical
Delphi, expressed as an orchestration document rather than hardcoded workflow
logic.

For the authoritative architecture, project status, and coding constraints, read
[`AGENTS.md`](AGENTS.md). For user and developer documentation, start with
[`docs/INDEX.md`](docs/INDEX.md).

## Current Capabilities

- Username-first authentication, role-based authorization, and participant
  management.
- Manual, template-based, imported, and AI-assisted meeting creation.
- Brainstorming, voting, rank-order voting, categorization, transfer/curation,
  and terminal report activities.
- Per-activity participant rosters, realtime meeting updates, reliable writes,
  and SQLite burst-handling controls.
- Declarative orchestration with generic predicates, transforms, summarizers,
  recommenders, and facilitator decision points.
- A packaged multi-round Classical Delphi method using the generic brainstorming
  activity as its controlled-comment surface.

## Architecture

Keep the four project layers separate:

1. Frozen activity plugins in `app/plugins/builtin/`.
2. Method definitions in `orchestrations/` using the orchestration schema.
3. The generic engine and shared primitives in `app/services/`.
4. Portable activity bundles governed by `docs/schemas/bundle_payload.schema.json`.

The web application lives in `app/routers/`, `app/templates/`, and `app/static/`;
the regression suite lives in `app/tests/`.

## Status

The engine, Delphi reference method, decision/recommender primitives,
show-it-back views, and terminal report are implemented and frozen for the HICSS
2027 paper package. The paper draft and detailed engineering record live in the
separate HICSS research repository described in [`plans/RELOCATED.md`](plans/RELOCATED.md).

Recently completed product work includes:

- [x] Ask for a real session name and group question when starting a template.
- [x] Show the brainstorming question separately from activity run status.
- [x] Carry the group question into the first Delphi brainstorming activity.
- [x] Distinguish activity run state (`Live`/`Stopped`) from participant access
  (`Not in this round`).
- [x] Allow facilitators to curate an eligible activity's idea package before it
  has ever run.
- [x] Let Settings-page AI provider/model choices configure the optional
  orchestration round-gate advisor.

## Known Boundaries

- Do not build a new orchestration-authoring UI for the paper package.
- The deprecated bespoke `outlier_justification` activity remains in the tree for
  reference but is not used by `orchestrations/delphi.json`.
- External OAuth identity association remains future product work.
- The public SQLite deployment target remains conservative; consult
  [`README.md`](README.md) and the reliability documents before larger sessions.

## Validation

Run the agreed regression suite before considering a change complete:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/ -q
```

On Windows PowerShell, after activating `venv`, the equivalent is:

```powershell
$env:PYTHONPATH = "."
python -m pytest app/tests -q
```
