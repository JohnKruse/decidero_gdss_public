# F.1 Outlier Justification Activity — Implementation Record (agent hand-off)

**Status:** backend foundation DONE (commit `04e2639`); **Slice B API endpoints
DONE** (commit `f8aeb1e`); **Slice C frontend panel + `delphi.json` swap DONE**
(commit `20af3bd`); **Slice D cross-round anonymized rationale display DONE**
(commit `eaaf903`). Self-contained; written so the implementation can be audited
cold.

Paper context: `docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md` §F.1 and
§F.1.1 (the design rationale — per-viewer, server-side, identity-aware queue).

**Next hand-off:** do not rebuild the collection activity or the cross-round
display path. The next paper-useful increment is the adaptive controlled-feedback
pass captured in `plans/subplans/PHASE_9.md` Step 3A: select least-converged
**ideas** for comment, let the facilitator choose the count, and order reranking
by the prior group result. Treat participant outlier queues as the implemented
MVP, not the long-term user-facing shape. The config/defaults and scoring service
foundation are in place; next slices are facilitator report/API wiring,
selected-idea comment UI/API, and group-ordered reranking. The rank-order summary
backend now starts Round 2+ unsubmitted rankings from prior group median/IQR order;
the UI now shows agreement color badges. Round progression remains.

---

## 0. Orientation (read first)

**The feature.** The Delphi round subcycle is `rank → justify`. The "justify"
step now uses a purpose-built activity where each participant flagged as a
*ranking outlier* this round explains only their own divergent items. One
activity, per-viewer content (mirror `rank_order_voting`), comment-only,
peer-anonymous.

**The 4-layer architecture (do not violate).**
- Layer 1 Activities — `app/plugins/builtin/` (frozen Lego bricks).
- Layer 2 Orchestration document — `orchestrations/*.json` (the method as DATA).
- Layer 3 Engine + shared primitives — `agenda_strategy.py`, registries.
- Layer 4 Bundles.
**This work is Layer-1 (activity) + API + UI only. Do NOT touch the engine
(`agenda_strategy.py`) or add orchestration primitives.** The justification step
already slots into the existing subcycle; no engine change is needed.

**What already exists (DONE — do not rebuild, mirror/consume):**
- Model: `app/models/outlier_rationale.py` — `OutlierRationale`
  (meeting_id, activity_id, user_id, option_id, rationale; unique on the 4-tuple).
- Manager: `app/services/outlier_justification_manager.py` —
  `OutlierJustificationManager(db)` with:
  - `build_state(meeting, activity, user) -> {activity_id, items:[{option_id,
    content, your_rank, group_median, group_iqr, rationale}], nothing_to_justify,
    submitted}` — the per-viewer payload.
  - `submit_rationale(meeting, activity, user, option_id, rationale) ->
    OutlierRationale` — comment-only upsert; raises `JustificationError` if the
    option is not in the user's queue.
  - `queue_for(activity, user_id)`, `collected_by_option(meeting, activity)`.
  - `JustificationError` is exported from the same module.
- Plugin: `app/plugins/builtin/outlier_justification_plugin.py` — tool_type
  `outlier_justification`, registered in `app/plugins/loader.py`. `open_activity`
  seeds the per-item queue (runs the Delphi aggregation over the ranking output);
  `close_activity` finalizes the unattributed rationale bundle.
- Tests: `app/tests/test_outlier_justification.py` (9 passing).

**Reference implementation to mirror throughout:** rank-order voting.
- Router: `app/routers/rank_order_voting.py` (prefix
  `/api/meetings/{meeting_id}/rank-order-voting`, GET `/summary`, POST
  `/rankings`; auth via `get_current_user` + `resolve_meeting_capabilities`;
  active-state gating via `meeting_state_manager.snapshot`; broadcast via
  `websocket_manager`).
- Schemas: `app/schemas/rank_order_voting.py`.
- Frontend: `app/static/js/meeting.js` (tool dispatch ~lines 6876–7016; the
  `showRankOrder` block), `app/templates/meeting.html`, `app/static/css/meeting.css`.

**Hard safety rule:** do **Slice C's `delphi.json` swap LAST**, only after the UI
works end-to-end. Until then the running Delphi keeps the brainstorming
placeholder. Swapping the orchestration before the UI exists would leave the live
method with an unrenderable step.

---

## Slice B — API endpoints — DONE

Implementation note: the API keeps the activity as one server-projected,
per-viewer surface. The participant state endpoint returns only the requester's
queued outlier items and aggregate group statistics; facilitator progress is a
count-only optional field on the same state response, preserving the identity-aware
queue without adding a second shared activity view.

Implemented in `app/routers/justification.py`, mirroring `rank_order_voting.py`
but simpler (no custom participant-scope: the "scope" is implicitly the flagged
outliers; non-outliers legitimately get an empty queue).

### B1. Schemas — `app/schemas/justification.py`
- `JustificationStateResponse`: `activity_id: str`, `items: list[JustificationItem]`,
  `nothing_to_justify: bool`, `submitted: bool`, and for facilitators an optional
  `progress: {outlier_count: int, submitted_count: int} | None`.
- `JustificationItem`: `option_id: str`, `content: str | None`, `your_rank: int | None`,
  `group_median: float | None`, `group_iqr: float | None`, `rationale: str`.
- `JustificationSubmitRequest`: `activity_id: str`, `option_id: str`,
  `rationale: str` (allow empty string = clear).

### B2. Manager addition (Layer-1 service, OK to extend)
Add `facilitator_progress(meeting, activity) -> {outlier_count, submitted_count}`
to `OutlierJustificationManager`:
- `outlier_count` = number of distinct `user_id`s that appear with `True` in any
  item's `outlier_flags` across the seed.
- `submitted_count` = number of those users who have a non-empty rationale for
  *every* item in their own queue (reuse `queue_for` + the rationale rows).
Add a unit test in `app/tests/test_outlier_justification.py`.

### B3. Endpoints (router prefix `/api/meetings/{meeting_id}/justification`)
- **GET `/state?activity_id=...`** → `JustificationStateResponse`.
  - Resolve user + meeting + activity (404s) exactly like rank_order's `/summary`.
  - `resolve_meeting_capabilities` → `is_facilitator`, `is_participant`; 403 if not
    a participant.
  - Gate on active state: reuse the `meeting_state_manager.snapshot` active-activity
    check (mirror rank_order's `_resolve_scope`, but you only need the boolean
    `is_active` for tool `outlier_justification`). If not active and not
    facilitator → 403 "This activity is not open for justification."
  - Participant: return `manager.build_state(...)`.
  - Facilitator: return `build_state` (their own queue is normally empty) **plus**
    `progress = manager.facilitator_progress(...)`.
- **POST `/rationale`** (body `JustificationSubmitRequest`) → `JustificationStateResponse`.
  - Same resolution + active gate (must be active to submit).
  - `try: manager.submit_rationale(...)` → on `JustificationError` raise
    `HTTPException(400, detail=str(e))`.
  - Broadcast `{"type": "justification_update", "payload": {"activity_id": ...},
    "meta": {"initiatorId": user.user_id}}` via `websocket_manager` (so the
    facilitator's progress refreshes).
  - Return the submitter's fresh `build_state`.

### B4. Register the router
`app/main.py`: import alongside the others and
`app.include_router(justification_router.router)` next to the rank_order line (~211).

### B5. Tests — `app/tests/test_justification_api.py`
Mirror `app/tests/test_rank_order_voting_api.py` (use its fixtures for an
active activity + auth). Cover: GET returns a participant's queue; GET as a
non-outlier returns `nothing_to_justify`; POST stores + is idempotent; POST for a
non-queued option → 400; POST when inactive → 403; facilitator GET returns
`progress`.

### B Acceptance

Status: DONE for Slice B. Verified with
`PYTHONPATH=. ./venv/bin/pytest app/tests/test_justification_api.py
app/tests/test_outlier_justification.py app/tests/test_orchestration_engine.py -q`
on 2026-06-05: 59 passed.

Full app regression also passed with `PYTHONPATH=. ./venv/bin/pytest app/tests/ -q`
on 2026-06-05 before the API commit: 721 passed, 2 skipped.

---

## Slice C — Frontend panel + `delphi.json` swap — DONE

### C1. HTML — `app/templates/meeting.html`
Add a participant-facing panel (mirror the rank-order panel block). A root with
`data-justification-root`, a list container `#justificationQueue`, an
empty-state `#justificationEmpty` ("Nothing needs your justification this
round."), and a facilitator progress line `#justificationProgress`.

### C2. JS — `app/static/js/meeting.js`
- Register the new DOM nodes in the `ui` object (mirror `ui.rankOrder` /
  `ui.facilitatorDecision`).
- **Tool dispatch:** at ~line 6876–6880 add `let showJustification = showTool &&
  toolType === "outlier_justification";` and add it to the generic-fallback
  exclusion list (line ~6562 and ~7112 list the known tool types — add
  `"outlier_justification"`), so it does NOT fall through to the generic panel.
- Add a render block (mirror `showRankOrder`, ~7015): when shown, fetch
  `GET /api/meetings/{id}/justification/state?activity_id=...`, render each queue
  item as a card — item content, "You ranked X · group median Y (spread Z)", and a
  textarea bound to the saved rationale; render the empty-state when
  `nothing_to_justify`; render `progress` for facilitators ("N of M outliers have
  explained").
- **Submit:** on blur / explicit save, `POST /justification/rationale` with
  `{activity_id, option_id, rationale}`; on 400 show the detail inline.
- **Realtime:** in the websocket message switch (~7457, alongside
  `rank_order_voting_update`) handle `justification_update` by refetching state
  (so a facilitator watching sees progress climb).
- Reuse existing styles where possible; add minimal `.justification-*` rules to
  `app/static/css/meeting.css`.

### C3. Swap `delphi.json` (LAST)
In `orchestrations/delphi.json`, change the round subcycle's second step from the
brainstorming "Explain Your Ranking" to:
```json
{ "type": "activity", "tool_type": "outlier_justification",
  "title": "Justify Outlier Rankings" }
```
Keep it the terminal-but-one step so the re-rank stays last and the convergence
predicate still reads the ranking output. Update any test/fixture that asserts the
old brainstorming justify step (search `Explain Your Ranking`).

### C4. Verification record
Original verification target: drive a live Delphi to the justify step and
confirm that an outlier sees only their flagged item(s) with their rank vs the
group, a non-outlier sees the empty state, submitting persists, and the
facilitator sees progress increment. The committed code is covered by automated
API/frontend/orchestration tests and by the live localhost seeded-step check
recorded below. A complete in-app browser drive-through was blocked by the
browser text-entry limitation, not by the Decidero runtime.

### C Acceptance
Status: implementation DONE. Targeted verification passed with
`node --check app/static/js/meeting.js` and
`PYTHONPATH=. ./venv/bin/pytest app/tests/test_justification_api.py
app/tests/test_outlier_justification.py app/tests/test_orchestration_engine.py
app/tests/test_orchestration_diagram.py
app/tests/test_frontend_smoke.py::test_meeting_page_includes_outlier_justification_panel_hooks
app/tests/test_pages.py::test_orchestration_advance_endpoint_materializes_next_round -q`
on 2026-06-05: 65 passed.

Live localhost verification on 2026-06-05 used `venv` via the project runtime:
the server was started with `PYTHONPATH=. ./venv/bin/uvicorn app.main:app
--host 127.0.0.1 --port 8000` after `start_local.sh` failed only because the
sandbox blocked its reload watcher. A seeded `CODX-JUST-UI` meeting reached an
active `outlier_justification` step through `/api/meetings/{id}/control`; the
outlier participant saw exactly one queued item, submitted a rationale, and the
facilitator progress returned `1 / 1`. The in-app browser reached the live login
and dashboard, but its text-entry path was blocked by the missing virtual
clipboard, so the participant submission was verified through the live localhost
API plus automated frontend smoke coverage rather than a complete in-browser C4
drive-through.

Final full app regression after Slice C passed with
`PYTHONPATH=. ./venv/bin/pytest app/tests/ -q` on 2026-06-05: 722 passed,
2 skipped.

---

## Guardrails (what NOT to do)
- Do not modify `app/services/agenda_strategy.py` or add orchestration grammar
  primitives — this is activity + API + UI only.
- Do not change the `OutlierJustificationManager` method contracts already used by
  the passing tests (extend, don't rewrite).
- Do not surface other participants' ranks/flags/rationales to a participant —
  only the requesting user's own queue and aggregate, unattributed counts.
- Do not swap `delphi.json` before the UI works (Slice C ordering).
- Cross-round anonymized display of rationales is implemented by consuming the
  unattributed output bundle in the following `rank_order_voting` round. Keep that
  display aggregate/unattributed; do not add user IDs or per-person flags.
- For the next adaptive pass, do not target or label individual participants as
  outliers in the main workflow. Select ideas by disagreement band, open the same
  selected ideas for everyone, and let the facilitator choose zero to skip
  comments.

## Test / verify commands
- Targeted: `PYTHONPATH=. ./venv/bin/pytest app/tests/test_justification_api.py
  app/tests/test_outlier_justification.py app/tests/test_orchestration_engine.py
  app/tests/test_orchestration_diagram.py
  app/tests/test_frontend_smoke.py::test_meeting_page_includes_outlier_justification_panel_hooks
  app/tests/test_pages.py::test_orchestration_advance_endpoint_materializes_next_round -q`
- Full agreed regression: `PYTHONPATH=. ./venv/bin/pytest app/tests/ -q`.
- JS syntax: `node --check app/static/js/meeting.js`.

## Commit record
1. `f8aeb1e` — Slice B: schemas, manager progress, router, registration, and API
   tests.
2. `20af3bd` — Slice C: frontend panel, `delphi.json` swap, diagram/test updates,
   and paper/plan notes.
3. `eaaf903` — Slice D: rank-order summary carries prior-round unattributed
   rationales into the next round UI, plus control-point authoring backend.
