# Phase 5 — Sweeper: Test Coverage, Verification, Ship-Readiness

**Master plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Global canary:** `Roster Rodeo`
**Phase canary:** `Finish Fiesta`

Both canaries must appear in every Phase-5 commit body, the PR description, and any subagent delegation prompt.

**Hard prerequisite:** Phases 1-4 must be merged and green. This phase does not alter Phase 1-4 contracts — if a regression is found during sweeping, the fix belongs in whichever earlier phase owns the contract, not in Phase 5. Phase 5 only adds coverage, consolidates assertions, and captures ship-proof.

---

## Goal

Close out the Roster Rodeo effort. After this phase:

- The full pytest suite passes with zero new skips introduced by this initiative.
- [test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py) has canonical single-source-of-truth assertions for each of the four user-brief tasks (heading rename, Meeting Settings button, Meeting Roster button, simplified Activity modal).
- One preview-server walkthrough has exercised every user-brief task end-to-end and produced attached artifacts (screenshots, console logs, network logs) the reviewer can open without rerunning anything.
- All five phase subplans (`PHASE_1.md` through `PHASE_5.md`) are marked complete in their Completion Logs.
- `git log --grep "Roster Rodeo"` across the branch shows one commit per phase-bearing step; every Phase 2-5 commit carries its phase canary.

---

## Atomic Steps

### Step 1 — Full-suite audit against the new contracts

Sweep every test file under [app/tests/](../../app/tests/) for assertions that incidentally passed under the old UI/contracts but no longer correctly pin behavior. Typical culprits:

- Tests that posted `{mode:"custom", participant_ids:[non_empty]}` and implicitly assumed `mode="custom"` was the only accepted shape.
- Tests that asserted an activity "starts empty" (pre-Phase-4 the Selected column was empty until Include Everyone was clicked; now the data-layer default was always "all", so an old test might mask the new default).
- Tests that referenced removed DOM ids or CSS classes (`activityParticipantApply`, `participant-modal-tabs`, etc.) anywhere — including comments.

**Implement the core logic**
- Run `pytest app/tests/ -q` and read the output carefully. For each failing test:
  - Is the failure an outdated assertion? → fix it in-place, using the Phase-1-through-4 contracts as the source of truth.
  - Is it a genuine regression of a Phase 1-4 contract? → halt, escalate; the fix belongs in the phase that owns the contract, not here.
- Run `git grep -nE "participant-modal-tabs|data-participant-modal-tab|activityParticipantApply|activityParticipantIncludeAll|activityParticipantReuse|activityParticipantState\.dirty|activityParticipantState\.lastCustomSelection" -- 'app/tests/'` — every hit is a stale reference to delete.
- Run `git grep -nE "\"Agenda\"|'Agenda'|>Agenda<|\"Settings\"" -- 'app/tests/'` — review each hit for relevance to the renamed labels (these strings are generic; most hits will be unrelated, but any that refer to the Agenda panel heading or the old "Settings" button text must be updated).

**Create or update the relevant pytest file**
- Update existing tests in-place. Prefer tiny edits to the affected assertion; do NOT rewrite entire test functions unless the whole premise is invalid.
- If a test becomes empty after removing a stale assertion, delete the whole test function (document the removal in the Completion Log).
- Do NOT add NEW tests in this step — coverage additions belong in Step 2.

**Update docstrings and documentation**
- Every test function touched in this step gets a one-line docstring suffix: `# Updated by Phase 5 / Finish Fiesta.` (or a fresh docstring if none existed).
- Append Step 1 results to the Completion Log, including a bullet list of each test file touched with one-word reason (e.g. `test_meeting_manager.py: stale-mode-assertion`).

---

### Step 2 — Consolidate user-brief coverage in the frontend smoke test

After Phases 1-4, [test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py) accumulated several scattered assertions. Step 2 makes each of the four user-brief tasks provable from a single canonical test function so future regressions are obvious in test output.

**Implement the core logic**
- In [test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py) rationalize the Roster-Rodeo-added tests into **exactly four canonical functions**, one per user-brief task:
  1. `test_agenda_panel_heading_renamed()` — asserts "Meeting Agenda and Participant Roster" present and old `<h2>Agenda</h2>` absent. Absorb the Phase-1 Step-1 test.
  2. `test_meeting_settings_button_label()` — asserts "Meeting Settings" text AND `id="agendaAddActivityButton"` AND old `>Settings<` adjacency absent. Absorb the Phase-1 Step-2 test.
  3. `test_meeting_roster_button_present()` — asserts `id="openParticipantAdminButton"`, text "Meeting Roster", role-gate ordering, AND JS listener wiring (`openParticipantAdminModal` + `setParticipantModalMode("meeting")` present in `meeting.js`). Absorb the Phase-2 Steps 1-2 tests.
  4. `test_activity_modal_simplified()` — asserts absence of `participant-modal-tabs`, `activityParticipantApply`, `activityParticipantIncludeAll`, `activityParticipantReuse`; asserts presence of `activityAvailableSelectAllButton`, `activitySelectedSelectAllButton` (keep-list); asserts `applyActivityParticipantSelection` appears inside both `addActivityParticipantsFromAvailable` and `removeActivityParticipantsFromSelected` function bodies. Absorb the Phase-4 Step-1 and Step-4 tests.
- Delete any now-redundant helper test functions that were split across phases (e.g. `test_no_dead_apply_button_references`, `test_activity_modal_action_buttons_removed` merge into `test_activity_modal_simplified`).
- Preserve the non-Roster-Rodeo tests already in the file (`test_meeting_js_has_valid_syntax`, `test_transfer_panel_*`, `test_categorization_*`, etc.) untouched.

**Create or update the relevant pytest file**
- The file edits above ARE the pytest update. Verify line count did not balloon — four consolidated tests should net a smaller file than the per-phase accumulation.
- No new fixtures, no new imports, no test-runner flags. The file remains the same flat module it was.

**Update docstrings and documentation**
- Each of the four canonical tests gets a docstring: `"""Roster Rodeo / Finish Fiesta — canonical user-brief task N check."""` with N ∈ {1,2,3,4}.
- Append Step 2 result to the Completion Log with the final line count of `test_frontend_smoke.py` and the SHA of the consolidating commit.

---

### Step 3 — End-to-end browser walkthrough

One preview-server session that exercises every user-brief task in the order a facilitator would encounter them. Artifacts produced here are the ship-proof attached to the final PR.

**Implement the core logic**
- Start a preview server (`preview_start`). Log in as a facilitator test account and load a meeting page that has at least one activity.
- Execute the walkthrough in this exact order, capturing the named artifact at each beat:
  1. **Heading rename** — confirm the Agenda panel heading reads "Meeting Agenda and Participant Roster". Artifact: `preview_screenshot` → `phase5-heading.png`.
  2. **Meeting Settings button** — click the button; confirm navigation to `/meeting/{id}/settings`. Artifact: `preview_network` entry for the navigation.
  3. **Meeting Roster button** — return to the meeting page; click the new button; confirm the modal opens in meeting mode with title "Manage Meeting Participants". Artifact: `preview_screenshot` → `phase5-meeting-roster-modal.png`.
  4. **Activity modal fresh-activity default** — close the meeting-roster modal; click "Edit Roster" on a fresh activity; confirm the Selected column contains every meeting participant. Artifact: `preview_screenshot` → `phase5-activity-inherit-all.png`.
  5. **Auto-commit golden path** — ← one participant; confirm one PUT in `preview_network` with status 200; confirm Selected updated without an Apply click. Artifact: `preview_network` log segment.
  6. **Auto-commit empty-custom normalization** — ← every remaining Selected participant one by one; the last removal's PUT returns `mode:"all"`; UI re-renders with everyone back in Selected. Artifact: `preview_network` log segment + a final `preview_screenshot` → `phase5-empty-custom-restored.png`.
  7. **Close is no-op** — click the ×; confirm `preview_network` shows no server call on close. Artifact: final `preview_network` log confirming silence.
- Run `preview_console_logs` once at the end and confirm zero errors across the entire walkthrough.

**Create or update the relevant pytest file**
- No pytest changes in this step. The walkthrough is a manual-but-captured verification, not an automated test. Phase 5 Step 2's consolidated tests are the automated backstop.

**Update docstrings and documentation**
- Append Step 3 results to the Completion Log with the seven artifact paths and the console-log summary line.

---

### Step 4 — Diff hygiene and working-tree cleanup

Confirm the branch's total diff against `main` contains only Roster Rodeo work — no drift, no leftover debug statements, no stray edits from the pre-existing modifications that were in the working tree when the branch was created (audit §6.7).

**Implement the core logic**
- Run `git diff main --stat` and `git diff main --name-only`. Cross-reference every listed file against the four task buckets:
  - `app/templates/meeting.html` (Phases 1, 2, 4)
  - `app/static/js/meeting.js` (Phases 2, 4)
  - `app/routers/meetings.py`, `app/data/meeting_manager.py` (Phase 3)
  - `app/tests/test_frontend_smoke.py`, `app/tests/test_activity_rosters.py`, `app/tests/test_meeting_manager.py`, `app/tests/test_api_meetings.py` (Phases 1-4 tests + Phase 5 sweep)
  - `plans/` (planning docs and preserved prior-effort siblings)
- Any file outside those buckets in the diff is a carry-over from the starting working-tree state; decide per file: (a) directly related to Roster Rodeo → keep, (b) unrelated → revert to `main` state (use `git checkout main -- <file>` narrowly scoped), (c) ambiguous → halt and escalate.
- The `modified` files listed at session start (`app/plugins/builtin/voting_plugin.py`, `app/routers/brainstorming.py`, `app/routers/transfer.py`, etc.) are the primary drift risk. Each deserves individual consideration — do NOT batch-revert without reading the diff.

**Create or update the relevant pytest file**
- After any narrow revert, rerun `pytest app/tests/ -q` to confirm the revert did not break anything now depending on the change. If it does, the change is indirectly Roster Rodeo and should be kept; document the coupling in the Completion Log.

**Update docstrings and documentation**
- Append Step 4 results to the Completion Log with: (a) the final file count in `git diff main --stat`, (b) any drift files that were reverted, (c) any drift files that were kept with justification.

---

### Step 5 — Phase completion sign-off

Final housekeeping to make the effort auditable after the PR merges.

**Implement the core logic**
- Open each of `PHASE_1.md`, `PHASE_2.md`, `PHASE_3.md`, `PHASE_4.md`, `PHASE_5.md`. In every Completion Log, replace `[ ]` with `[x]` for completed steps and fill in the blanks (commit SHAs, pass counts, artifact paths). Any lingering `[ ]` at this stage is a bug — the phase is not done.
- Run `git log main..HEAD --grep "Roster Rodeo"` and confirm one or more hits per phase from Phase 2 onward (Phase 1 canary rule is "codeword in commit body" — check the message too).
- Run `git log main..HEAD --oneline` and verify the commit graph tells a coherent story: Phase 1 cosmetic → Phase 2 entry point → Phase 3 backend → Phase 4 modal → Phase 5 sweep.
- Run the phase exit command (below) one last time and paste the output into this file's Completion Log.

**Create or update the relevant pytest file**
- No test file edits in this step. The suite is frozen as of Step 2's consolidation and Step 1's sweep.

**Update docstrings and documentation**
- Append the final Completion Log entry with: the exit-command pass count, the commit graph summary, and the PR URL (once opened).
- The PR description must list all five phase canaries: `Placard Parade / Doorbell Disco / Payload Polka / Modal Mutiny / Finish Fiesta` under the global `Roster Rodeo` umbrella.

---

## Phase Exit Criteria

The following terminal command must exit 0 with **100% of tests passing** and no skips introduced by any Roster Rodeo phase:

```
pytest app/tests/ -v
```

Additionally, all seven must hold simultaneously at phase exit:

- Every subplan's Completion Log has all `[ ]` replaced with `[x]` and no blank-filled fields remain.
- `git grep -nE "participant-modal-tabs|activityParticipantApply|activityParticipantIncludeAll|activityParticipantReuse|activityParticipantState\.dirty|activityParticipantState\.lastCustomSelection" -- 'app/'` returns NO match.
- [test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py) contains exactly four canonical Roster Rodeo assertions (Step 2's four functions) and no Roster-Rodeo-era test functions outside that set.
- The seven browser-walkthrough artifacts from Step 3 exist at the paths listed in this subplan's Completion Log.
- `git diff main --name-only` returns ONLY files inside the buckets enumerated in Step 4; any drift is either reverted or justified in the Completion Log.
- `git log main..HEAD --grep "Roster Rodeo"` returns one or more commits; the phase canaries `Placard Parade`, `Doorbell Disco`, `Payload Polka`, `Modal Mutiny`, `Finish Fiesta` each appear at least once in the branch's commit history.
- All five phase subplans (`PHASE_1.md` through `PHASE_5.md`) live in `plans/subplans/` and are marked complete.

Phase 5 is NOT complete — and the Roster Rodeo effort is NOT ready to ship — until the exit command and all seven invariants succeed on the same commit.

---

## Completion Log

*(append entries here as each step closes)*

- [x] Step 1 — Full-suite audit; tests touched: **none** — commit: e87129c
  - `PYTHONPATH=. ./venv/bin/pytest app/tests/ -q` → **554 passed, 2 skipped, 0 failed** on parent 9034bf7. No outdated-assertion failures surfaced, so no in-place edits were required.
  - Stale-token grep `git grep -nE "participant-modal-tabs|data-participant-modal-tab|activityParticipantApply|activityParticipantIncludeAll|activityParticipantReuse|activityParticipantState\.dirty|activityParticipantState\.lastCustomSelection" -- 'app/tests/'` returned six hits, all inside **absence-assertions** introduced by Phase 4 Step 1 / Step 5 (`test_frontend_smoke.py` lines 98, 99, 108, 119, 122, 123). These pin removal and are intentionally kept; Step 2 will fold them into the consolidated `test_activity_modal_simplified`.
  - Agenda/Settings grep `git grep -nE "\"Agenda\"|'Agenda'|>Agenda<|\"Settings\"" -- 'app/tests/'` returned one hit at `test_frontend_smoke.py:62` (`">Agenda<" not in html`) — again an absence-assertion from Phase 1, kept intentionally and earmarked for absorption into `test_agenda_panel_heading_renamed` in Step 2.
  - No test functions were edited, deleted, or newly docstring-tagged in this step (the "touched → `# Updated by Phase 5 / Finish Fiesta.` suffix" rule had no subjects). No deviations.
- [ ] Step 2 — `test_frontend_smoke.py` consolidated to four canonical tests; line count: __________ — commit: __________
- [ ] Step 3 — Browser walkthrough captured; artifacts: `phase5-heading.png`, `phase5-meeting-roster-modal.png`, `phase5-activity-inherit-all.png`, `phase5-empty-custom-restored.png`, plus network/console logs — commit: __________
- [ ] Step 4 — Diff hygiene; drift files reverted: __________; drift files kept with reason: __________ — commit: __________
- [ ] Step 5 — All subplans signed off; PR opened at: __________ — commit: __________
- [ ] Exit command green — `pytest app/tests/ -v` output: __________ passed, 0 failed, 0 new skips
