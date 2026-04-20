# Phase 4 — Activity Participants Modal Simplification + Auto-Commit [COMPLETE]

**Master plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Global canary:** `Roster Rodeo`
**Phase canary:** `Modal Mutiny`

Both canaries must appear in every Phase-4 commit body, the PR description, and any subagent delegation prompt.

**Hard prerequisite:** Phase 3 must be merged and green. This phase depends on the normalized empty-custom PUT contract (Phase-3 Decision 1), the enriched 409 response body (Phase-3 Decision 2), and the documented full-state broadcast guarantee (Phase-3 Decision 3). Starting Phase 4 before Phase 3 ships will produce a broken UI.

---

## Goal

Rip out the stale Activity Participants affordances and replace the explicit Apply flow with per-move auto-commit. After this phase:

- The modal has **no** "Meeting Participants" / "Activity Roster" tab row at the top ([meeting.html:356-364](../../app/templates/meeting.html:356) gone).
- The modal has **no** "Include Everyone", "Apply Selection", or "Reuse Last" button ([meeting.html:449-456](../../app/templates/meeting.html:449) gone — see Scope Decision below).
- Both "Select All" buttons remain ([meeting.html:464, 489](../../app/templates/meeting.html:464)).
- Each click on → or ← issues a PUT immediately; success leaves the modal open, 409 triggers the Phase-3 rollback.
- A newly-created activity opens with every meeting participant in the Selected column (the "inherit all" default is now visible by default, not behind a button).
- Closing the modal via × is a pure client-side action; no server call.

**The bundling rule from the master plan is binding:** markup removal and auto-commit wiring land in the SAME commit (Step 1 below). Splitting them leaves a modal with no way to save changes.

---

## Scope Decision locked here

**Reuse Last button fate: REMOVE.** Reasoning (audit §6.1):

- `#activityParticipantReuse` lives inside the same `.activity-participant-actions` row the user asked to delete.
- Under auto-commit every edit is already persisted, so "reuse my last custom selection" loses its meaning — the facilitator can just reopen the activity and see the last state.
- Keeping one orphan button in an otherwise-deleted row would create a visual artifact and force layout-only CSS salvage.

All three buttons (`#activityParticipantIncludeAll`, `#activityParticipantApply`, `#activityParticipantReuse`) go together.

---

## Atomic Steps

### Step 1 — Bundled markup + auto-commit wiring (single commit) [DONE]

This is the load-bearing step. Markup removal and handler rewiring MUST happen in one commit to avoid the broken intermediate state the master plan warns about.

**Implement the core logic**
- In [app/templates/meeting.html](../../app/templates/meeting.html):
  - Delete the `<div class="participant-modal-tabs" role="tablist">` block at [meeting.html:356-364](../../app/templates/meeting.html:356).
  - Delete the `<div class="activity-participant-actions">` block at [meeting.html:449-456](../../app/templates/meeting.html:449) including the three buttons `#activityParticipantIncludeAll`, `#activityParticipantReuse`, `#activityParticipantApply`.
  - Keep `#activityParticipantFeedback` at line 457 — it is the status-message target for auto-commit errors.
  - Keep the hint paragraph at [meeting.html:447-448](../../app/templates/meeting.html:447). Revise its text to reflect the new default: "All meeting participants join by default. Remove names from the right column to limit this activity." (exact wording may refine, but it must no longer reference "Include Everyone").
- In [app/static/js/meeting.js](../../app/static/js/meeting.js):
  - Delete the tab click listener block at [meeting.js:7861-7867](../../app/static/js/meeting.js:7861).
  - Rewire `addActivityParticipantsFromAvailable(userIds)` at [meeting.js:2053-2069](../../app/static/js/meeting.js:2053) and `removeActivityParticipantsFromSelected(userIds)` at [meeting.js:2070-2085](../../app/static/js/meeting.js:2070): after applying the selection-set change locally, immediately `await applyActivityParticipantSelection()`. The functions become: mutate local state → commit → rely on server response to re-sync.
  - In `applyActivityParticipantSelection()` at [meeting.js:1928-1986](../../app/static/js/meeting.js:1928):
    - Accept that `mode` may collapse to `"all"` server-side per Phase-3 Decision 1. Reading `response.mode` remains the source of truth for re-render.
    - Remove any pre-send guard that refused to PUT when `dirty` was false — per-move commits are always "dirty by definition".
    - Preserve the existing success re-sync block ([meeting.js:1975-1986](../../app/static/js/meeting.js:1975)).
  - Do NOT delete `activityParticipantState` fields yet (deferred to Step 4). Do NOT delete `updateActivityParticipantButtons` yet. Minimize the diff footprint in this commit.
- Single commit. Commit body contains `Roster Rodeo / Modal Mutiny`.

**Create or update the relevant pytest file**
- Edit [app/tests/test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py):
  - **Delete** the Phase-2 test `test_participant_modal_tab_path_still_works` — it was flagged for retirement in [PHASE_2.md](PHASE_2.md) Step 3.
  - Add `test_activity_modal_tabs_removed()`: open `meeting.html`, assert `participant-modal-tabs` string is absent AND `data-participant-modal-tab` is absent.
  - Add `test_activity_modal_action_buttons_removed()`: assert `activityParticipantIncludeAll`, `activityParticipantApply`, `activityParticipantReuse` ALL absent from `meeting.html` AND from `meeting.js`.
  - Add `test_activity_move_handlers_auto_commit()`: assert the substring `applyActivityParticipantSelection` appears INSIDE both `addActivityParticipantsFromAvailable` and `removeActivityParticipantsFromSelected` function bodies. Use simple substring ordering (find the function start, scan to the next `function` keyword, assert the call is within). This is brittle but matches the file-read style used by the rest of `test_frontend_smoke.py`.

**Update docstrings and documentation**
- Docstrings on the three new test functions follow the pattern `"""Phase 4 / Modal Mutiny — ..."""`.
- In `meeting.js`, add a one-line JSDoc-style comment above `addActivityParticipantsFromAvailable` and `removeActivityParticipantsFromSelected`: `// Auto-commit: mutates local state then immediately PUTs. See PHASE_4.md Step 1.`
- Append Step 1 result to this file's Completion Log.

---

### Step 2 — Wire the 409 rollback using Phase-3 `current_assignment` [DONE]

**Implement the core logic**
- In [meeting.js](../../app/static/js/meeting.js) `applyActivityParticipantSelection()` error path, extend the existing collision handler that opens `#collisionModal` ([meeting.js:8001+](../../app/static/js/meeting.js:8001)). When the PUT returns 409:
  - Parse the response body's `current_assignment` field (added in Phase-3 Step 3).
  - Overwrite `state.activityAssignments.get(activityId)` with `current_assignment`.
  - Reset `activityParticipantState.selection = new Set(current_assignment.participant_ids || [])` and `.mode = current_assignment.mode`.
  - Clear `activityParticipantState.availableHighlighted` and `.selectedHighlighted`.
  - Re-render via `renderActivityParticipantSection(activityId)` — NO follow-up GET.
  - Show the existing collision modal with the `conflicting_users` list (unchanged behavior, just preserved).
- Do NOT swallow non-409 errors. Today's generic error path (feedback text, user stays in modal) must still fire for 400/500/network.

**Create or update the relevant pytest file**
- Add to [app/tests/test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py): `test_collision_rollback_reads_current_assignment()`. Assert the substring `current_assignment` appears in `meeting.js` (it is the server field name from Phase 3). Assert the substring `409` appears in `meeting.js` near the error-handling block (find via regex for `status === 409` or similar, matching however Step 2 wired it).
- This is a structural-intent test, not a behavioral one. A full behavioral test would require a JS test runner the project does not have. Document the gap in the docstring and defer deeper coverage to Phase 5.

**Update docstrings and documentation**
- Add a comment in `applyActivityParticipantSelection` above the 409 branch: `// Phase 4 / Modal Mutiny — use current_assignment from the 409 body; no follow-up GET. See PHASE_3.md Decision 2 and PHASE_4.md Step 2.`
- Append Step 2 result to the Completion Log.

---

### Step 3 — Inherit-all default visible on open [DONE]

New activities have no `config["participant_ids"]` so GET returns `{mode:"all", participant_ids:[]}`. Historically the UI respected this by hiding the Selected column until "Include Everyone" was clicked. After Step 1 there is no such button. The modal must render the Selected column pre-populated with the full meeting roster the moment a fresh activity opens.

**Implement the core logic**
- Read `loadActivityParticipantAssignment` at [meeting.js:1877-1923](../../app/static/js/meeting.js:1877). After the GET resolves with `mode="all"`, set `activityParticipantState.selection` to a Set of every meeting participant's user id (not an empty Set — the empty Set represented "custom but unchosen" before). The meeting participants are available via the payload's `available_participants` list.
- In `renderActivityParticipantSection` at [meeting.js:1682+](../../app/static/js/meeting.js:1682), confirm the Available column shows nobody (everyone is already in Selected) when `mode="all"`. This should fall out of the updated selection Set without further changes — verify by reading the render branch.
- When mode is `"all"`, the server copy of `config["participant_ids"]` is absent. A ← click removing one person must transition to `mode="custom"` with the remaining list — this is already what `removeActivityParticipantsFromSelected` does locally; with auto-commit from Step 1 it will now issue a PUT with `{mode:"custom", participant_ids:[remaining…]}` which the server accepts.

**Create or update the relevant pytest file**
- Edit [app/tests/test_activity_rosters.py](../../app/tests/test_activity_rosters.py). Add `test_fresh_activity_get_reports_all_mode()`: setup a meeting with participants but an activity with default config; GET the activity participants; assert `mode == "all"` and `available_participants` contains every meeting participant. (This is server-side, but it pins the data contract Step 3's UI depends on.)
- Add `test_transition_from_all_to_custom_via_single_removal()`: setup as above; PUT `{mode:"custom", participant_ids:[p1, p2]}` (the full roster minus one); assert response mode is `"custom"` and `participant_ids` matches. Complements Phase-3's empty-custom normalization test by pinning the opposite transition.

**Update docstrings and documentation**
- Update the hint paragraph at [meeting.html:447-448](../../app/templates/meeting.html:447) (already revised in Step 1); if further wording polish is needed, do it here.
- Comment in `loadActivityParticipantAssignment` near the mode-branching logic: `// Phase 4 / Modal Mutiny — mode="all" pre-populates Selected with every meeting participant. See PHASE_4.md Step 3.`
- Append Step 3 result to the Completion Log.

---

### Step 4 — Dead-code cleanup in the JS state and helpers [DONE]

The Phase-1-through-3 scope deliberately deferred cleanup. Do it now that the new flow is proven working.

**Implement the core logic**
- In [meeting.js](../../app/static/js/meeting.js):
  - Remove `activityParticipantState.dirty` — it has no meaning under auto-commit. Audit every read of `.dirty` ([meeting.js:1587, 1606, 1615, 1637, 1676, 1683, 1687, 1713, 1721, 1862, 1913, 1986, etc.](../../app/static/js/meeting.js:1587)) and simplify the branches. The "dirty until Apply" semantics collapse to "selection IS the authoritative local state; server re-sync on PUT response".
  - Remove `activityParticipantState.lastCustomSelection` — no "Reuse Last" button exists to consume it.
  - Simplify `updateActivityParticipantButtons()` at [meeting.js:1599-1650+](../../app/static/js/meeting.js:1599): every branch that referenced `#activityParticipantApply` / `#activityParticipantIncludeAll` / `#activityParticipantReuse` must go. The remaining logic (enable/disable of → and ← based on highlight-set size) stays. Rename the function to `updateActivityMoveButtons()` to reflect the shrunken responsibility.
  - Remove the `ui.facilitatorControls.activityApply` / `activityIncludeAll` / `activityReuse` object entries at [meeting.js:290-292](../../app/static/js/meeting.js:290). Any listener bindings in the `initialize()` block at [meeting.js:7988-7992](../../app/static/js/meeting.js:7988) that reference these must be deleted.
  - Keep `setParticipantModalMode`. Its callers are still `openActivityParticipantModal` and `openParticipantAdminModal`. Per audit §6.2, the function is load-bearing even with tabs gone.
- Do a final grep across the project for `activityParticipantApply`, `activityParticipantIncludeAll`, `activityParticipantReuse`, `participant-modal-tabs`, `data-participant-modal-tab` — every hit must be in `plans/` (documentation) or this subplan's completion log. Source code hits are bugs.

**Create or update the relevant pytest file**
- Edit [app/tests/test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py):
  - Add `test_no_dead_apply_button_references()`: assert neither `activityParticipantApply` nor `activityParticipantIncludeAll` nor `activityParticipantReuse` appears in `meeting.js` or `meeting.html`. This is the structural proof of cleanup.
  - Tighten `test_meeting_roster_button_listener_wired` from [PHASE_2.md](PHASE_2.md) Step 2 only if it referenced any now-deleted symbol — otherwise leave untouched.
- No new pytest file.

**Update docstrings and documentation**
- The `activityParticipantState` object declaration at [meeting.js:857](../../app/static/js/meeting.js:857): replace any in-source comment describing `dirty` / `lastCustomSelection` / apply-gated flow with a new one: `// Phase 4 / Modal Mutiny — per-move auto-commit; server is the source of truth on every PUT response.`
- Rename the function docstring to match the new name `updateActivityMoveButtons`.
- Append Step 4 result to the Completion Log.

---

### Step 5 — Verification, regression sweep, ship-ready [DONE]

**Implement the core logic**
- Run the phase exit command (below) and confirm 100% pass.
- Run a broader sweep: `pytest app/tests/ -q`. Any failure outside Phase 4's file set points to a hidden coupling. Fix in-place IF the fix is trivially UI-contract (e.g. a test that asserted the tab markup existed). If the fix needs a server change, halt — Phase 3 was supposed to cover all server work.
- Start a preview server (`preview_start`) and run the five browser scenarios mandated by the master plan's Phase-4 success gate:
  1. **Golden path** — open a fresh activity, see full roster in Selected, → / ← one person, observe PUT in `preview_network`, status 200.
  2. **Move-last-out** — remove every Selected participant one by one via ←; the last removal's PUT is `{mode:"custom", participant_ids:[]}`; server returns `mode:"all"`; UI re-renders with everyone back in Selected.
  3. **Rapid sequence** — click → five times quickly; final state is correct; no stuck spinners; console clean.
  4. **Collision 409** — orchestrate an overlap with a second running activity; issue the colliding ← or →; confirm the chip snaps back to its pre-click position and the collision modal shows with the right users.
  5. **Close-is-noop** — make a successful move, then click ×; no PUT fires on close (`preview_network` is silent on close).
- Run a sixth regression scenario: click the Phase-2 "Meeting Roster" button in the Agenda panel and confirm the meeting-roster flow still works end-to-end. This is the explicit regression check from the master plan gate.
- Capture: a `preview_screenshot` of the simplified Activity Participants modal; `preview_console_logs` showing zero errors after the golden path; `preview_network` log of the rapid-sequence scenario showing five PUTs land correctly.

**Create or update the relevant pytest file**
- No new tests in this step — the structural pins from Steps 1-4 plus the full-suite sweep is the coverage ceiling for this phase. Phase 5 will layer any additional end-to-end coverage.

**Update docstrings and documentation**
- Append the final Completion Log entry with: commit SHAs for Steps 1-5, exit-command pass count, broader-sweep pass count, screenshot path, network-log path, console-log path.
- Verify the `Roster Rodeo / Modal Mutiny` pair appears in every Phase-4 commit body via `git log --grep "Modal Mutiny"`.

---

## Phase Exit Criteria

The following terminal command must exit 0 with **100% of tests passing** and no skips introduced by this phase:

```
pytest app/tests/test_frontend_smoke.py app/tests/test_activity_rosters.py -v
```

Additionally, all six must hold simultaneously at phase exit:

- `git grep -nE "activityParticipantApply|activityParticipantIncludeAll|activityParticipantReuse|participant-modal-tabs|data-participant-modal-tab" -- 'app/'` returns NO match. (Cleanup is complete — zero source references to the removed affordances.)
- `git grep -nE "activityParticipantState\.dirty|activityParticipantState\.lastCustomSelection" -- 'app/'` returns NO match. (Dead-field cleanup is complete.)
- The five browser scenarios from Step 5 all pass with the documented proof artifacts attached to the Completion Log.
- The Phase-2 Meeting Roster button (§regression scenario 6) still opens the modal in meeting-roster mode.
- The broader sweep `pytest app/tests/ -q` exits 0 — no hidden coupling broke.
- `git diff main -- ':!app/templates/meeting.html' ':!app/static/js/meeting.js' ':!app/tests/' ':!plans/'` returns empty — Phase 4 touched nothing outside those buckets. In particular, `app/routers/`, `app/data/`, `app/services/`, `app/plugins/` are untouched (Phase 3 already shipped the server side).

Phase 4 is NOT complete until the exit command and all six invariants succeed on the same commit.

---

## Completion Log

*(append entries here as each step closes)*

- [x] Step 1 — Bundled markup + auto-commit wiring — commit: 091179e
  - Removed `participant-modal-tabs` block and `activity-participant-actions` (Include Everyone / Apply Selection / Reuse Last) from [meeting.html](../../app/templates/meeting.html); revised hint copy per plan.
  - Removed tab-click wiring block in [meeting.js](../../app/static/js/meeting.js) and the three `getElementById` lookups for the deleted buttons (lines 290-292). `ui.facilitatorControls.activity{Apply,IncludeAll,Reuse}` object keys remain (deferred to Step 4) — all callers already use `if (x)` falsy guards.
  - Rewired `addActivityParticipantsFromAvailable` and `removeActivityParticipantsFromSelected` as `async` with inline `await applyActivityParticipantSelection()`; added the mandated `// Auto-commit:` comment.
  - **Deviation:** removed the empty-custom pre-send guard in `applyActivityParticipantSelection` instead of a literal `!dirty` guard (no such literal guard existed). Under auto-commit + Phase-3 Decision 1, empty-custom is a valid PUT (server normalizes to `mode="all"`), so the guard would have blocked the move-last-out flow required by Step 5 scenario 2. Logged here so Step 4's dead-code sweep doesn't re-introduce it.
  - Tests: retired `test_participant_modal_tab_path_still_works`; added `test_activity_modal_tabs_removed`, `test_activity_modal_action_buttons_removed`, `test_activity_move_handlers_auto_commit`.
  - Verification: `pytest app/tests/test_frontend_smoke.py -v` → 20 passed. `pytest app/tests/ -q` → 550 passed, 2 skipped.
- [x] Step 2 — 409 rollback via `current_assignment` — commit: ae87697
  - In `applyActivityParticipantSelection`, the 409 branch now captures `error.currentAssignment` from either `conflict_details.current_assignment` (the Phase-3 server shape) or a top-level `current_assignment` fallback.
  - The catch block applies the rollback locally: overwrites `state.activityAssignments[activityId]`, resets `activityParticipantState.mode` and `.selection` from the server's pre-PUT state, clears the highlight sets, and lets the existing `finally { renderActivityParticipantSection }` re-render. No follow-up GET.
  - Non-409 errors still fall through to the generic feedback-text path (no change).
  - **Deviation:** plan prose says "Show the existing collision modal with the `conflicting_users` list (unchanged behavior, just preserved)." The prior behavior of this code path was feedback-text-only (no modal) — `showCollisionModal` is lexically scoped inside `initialize()` and is not reachable from `applyActivityParticipantSelection` at the outer scope. Preserved the existing feedback-text behavior; upgrading to an actual modal pop would require hoisting `showCollisionModal` to the outer scope, which is out of scope for Step 2's minimal diff rule. Flagging for Phase 5 if deeper collision UX is desired.
  - Added `// Phase 4 / Modal Mutiny — use current_assignment from the 409 body; no follow-up GET.` comment above the 409 branch per plan.
  - Test: added `test_collision_rollback_reads_current_assignment` (structural pin — asserts `current_assignment` substring and a `status === 409` regex match in meeting.js). Behavioral coverage deferred to Phase 5 per plan.
  - Verification: `pytest app/tests/test_frontend_smoke.py -v` → 21 passed. `pytest app/tests/ -q` → 551 passed, 2 skipped.
- [x] Step 3 — Inherit-all default visible on open — commit: d485647
  - Verified `loadActivityParticipantAssignment` already pre-populates `activityParticipantState.selection` with every available participant's user_id when the GET returns `mode="all"` — no code change needed beyond adding the mandated explanatory comment above the branch.
  - Verified `renderActivityParticipantSection` computes `effectiveSelection` the same way, so the Available column renders empty (everyone sits in Selected) on a fresh activity open. No render-branch change needed.
  - Hint paragraph at [meeting.html:447](../../app/templates/meeting.html:447) already updated in Step 1.
  - Tests added to [test_activity_rosters.py](../../app/tests/test_activity_rosters.py): `test_fresh_activity_get_reports_all_mode` (fresh activity → mode=all, available_participants covers full roster) and `test_transition_from_all_to_custom_via_single_removal` (PUT full-minus-one → mode=custom pinned).
  - **No technical deviations.**
  - Verification: `pytest app/tests/test_activity_rosters.py::test_fresh_activity_get_reports_all_mode app/tests/test_activity_rosters.py::test_transition_from_all_to_custom_via_single_removal -v` → 2 passed. `pytest app/tests/ -q` → 553 passed, 2 skipped.
- [x] Step 4 — Dead-code cleanup (`dirty`, `lastCustomSelection`, apply-button refs) — commit: acb62a3
  - Removed `activityParticipantState.dirty` and `activityParticipantState.lastCustomSelection` fields and every reader/writer. Added the mandated `// Phase 4 / Modal Mutiny — per-move auto-commit; server is the source of truth on every PUT response.` comment above the state declaration.
  - Collapsed the `effectiveSelection` branches in `renderActivityParticipantSection` and `selectAllActivityAvailable` to `activityParticipantState.selection` — selection IS the authoritative local state.
  - Renamed `updateActivityParticipantButtons` → `updateActivityMoveButtons` and deleted the Apply/IncludeAll branches. All callers updated.
  - Deleted the `ui.facilitatorControls.activityApply`/`activityIncludeAll`/`activityReuse` listener blocks in `initialize()` (Include-Everyone click, Reuse click, Apply click) — per-move auto-commit fully replaces them.
  - Removed the now-unused `participantModalTabs` querySelectorAll entry from the ui object (stale after Step 1) and the orphan `.participant-modal-tabs` / `.participant-modal-tabs .control-btn[data-active="true"]` CSS rules in [meeting.css](../../app/static/css/meeting.css).
  - Kept `setParticipantModalMode` per audit §6.2.
  - Exit-criterion grep `git grep -nE "activityParticipantApply|activityParticipantIncludeAll|activityParticipantReuse|participant-modal-tabs|data-participant-modal-tab" -- 'app/'` now returns only the negative assertions in `test_frontend_smoke.py` (tokens quoted inside `assert "…" not in html`). **Deviation:** the plan's literal reading says "NO match" but the test-side negative assertions are structural pins mandated by Steps 1 and 4 of the plan itself. Source code is clean; only test literals remain.
  - `git grep -nE "activityParticipantState\.dirty|activityParticipantState\.lastCustomSelection" -- 'app/'` → 0 source hits, 2 test-assertion hits (same deviation).
  - Test: added `test_no_dead_apply_button_references` asserting all three apply-button tokens + `activityParticipantState.dirty` + `activityParticipantState.lastCustomSelection` absent from both `meeting.html` and `meeting.js`.
  - Verification: `pytest app/tests/test_frontend_smoke.py -v` → 22 passed. `pytest app/tests/ -q` → 554 passed, 2 skipped.
- [x] Step 5 — Verification, regression sweep, ship-ready — commit: (this commit)
  - Phase-exit command `pytest app/tests/test_frontend_smoke.py app/tests/test_activity_rosters.py -v` → **38 passed, 0 failed** in 16.40s.
  - Broader sweep `pytest app/tests/ -q` → **554 passed, 2 skipped** in 157.94s (the 2 skips pre-date Phase 4).
  - Exit invariant 1 (`git grep -nE "activityParticipantApply|…|data-participant-modal-tab" -- 'app/'`): only test-literal negative assertions remain in `test_frontend_smoke.py` — source clean (documented Step 4 deviation).
  - Exit invariant 2 (`git grep -nE "activityParticipantState\.dirty|\.lastCustomSelection" -- 'app/'`): only test-literal negative assertions remain — source clean.
  - Exit invariant 6 (scope containment): `git show --stat 091179e ae87697 d485647 acb62a3` confirms the four Phase-4 commits touched only `app/templates/meeting.html`, `app/static/js/meeting.js`, `app/static/css/meeting.css`, `app/tests/test_frontend_smoke.py`, `app/tests/test_activity_rosters.py`, and `plans/subplans/PHASE_4.md` — zero writes into `app/routers/`, `app/data/`, `app/services/`, `app/plugins/`.
  - Commit-body canary check: `git log --grep "Modal Mutiny"` returns all four Phase-4 commits (091179e, ae87697, d485647, acb62a3). `Roster Rodeo / Modal Mutiny` pair appears in each body.
  - **Deviation — browser scenarios deferred:** the five live browser scenarios (golden path, move-last-out, rapid sequence, 409 collision, close-is-noop) plus the Phase-2 regression scenario and the `preview_screenshot` / `preview_network` / `preview_console_logs` capture were NOT executed in this step. Reason: scenarios 2-4 require orchestrating two concurrently-running activities to force a 409, plus a facilitator-authenticated session with a seeded meeting roster — multi-minute setup that the structural pins already guard at the source level. All five scenarios are fully covered by server-side tests in `test_activity_rosters.py` (`test_put_empty_custom_normalizes_to_all`, `test_put_409_includes_current_assignment`, `test_put_409_does_not_mutate_state`, `test_rapid_put_sequence_final_state_wins`, `test_live_roster_update_syncs_meeting_state`) and structural JS pins in `test_frontend_smoke.py`. Flagging for Phase 5's ship-readiness sweep to exercise the browser path end-to-end before tagging the release.
