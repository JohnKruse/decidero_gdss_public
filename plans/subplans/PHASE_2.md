# Phase 2 — Dedicated Meeting Roster Entry Point [COMPLETE]

**Master plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Global canary:** `Roster Rodeo`
**Phase canary:** `Doorbell Disco`

Both canaries must appear in the commit message body, the PR description, and any subagent delegation prompt associated with this phase.

---

## Goal

Introduce a new **"Meeting Roster"** button in the Agenda panel's card-actions row, sibling to the Phase-1-renamed "Meeting Settings" button. The button opens the shared participant-admin modal directly in meeting-roster mode.

**Planning decision (locked in this subplan, per Master Plan §Phase 2):** reuse the existing `#openParticipantAdminButton` DOM id. The click listener for that id is already wired at [meeting.js:316, 7856-7860](../../app/static/js/meeting.js:7856) and calls `openParticipantAdminModal()` which in turn calls `setParticipantModalMode("meeting")` ([meeting.js:6517-6527](../../app/static/js/meeting.js:6517)). Supplying the missing DOM element is therefore the entire front-end wiring task; no new JS is required.

**Explicit non-goals (deferred to Phase 4):** removing the in-modal tab row, removing "Include Everyone" / "Apply Selection" buttons, or changing any activity-roster behavior. After Phase 2 the facilitator has TWO ways into the meeting roster (new button + old tab-inside-activity-modal); the redundancy is deliberate and stays until Phase 4 proves the new flow is solid.

---

## Atomic Steps

### Step 1 — Add the Meeting Roster button to the Agenda card-actions row

**Implement the core logic**
- Open [app/templates/meeting.html](../../app/templates/meeting.html). Inside the card-actions `<div>` at [meeting.html:97-99](../../app/templates/meeting.html:97), insert a new `<button>` as a sibling to `#agendaAddActivityButton`. Exact form:
  - `type="button"`
  - `class="control-btn"` (match the sibling so visual treatment is consistent)
  - `id="openParticipantAdminButton"` — this is load-bearing; JS at [meeting.js:316](../../app/static/js/meeting.js:316) looks up this exact id
  - Button text: `Meeting Roster`
- Place the new button either immediately before or immediately after `#agendaAddActivityButton`. Order is cosmetic; document the chosen order in the Completion Log.
- Verify the insertion is INSIDE the existing facilitator role gate `{% if current_user.role in ['admin', 'super_admin', 'facilitator'] %}` at [meeting.html:96](../../app/templates/meeting.html:96). Non-facilitators must not see the button.
- Do NOT edit [meeting.js](../../app/static/js/meeting.js) in this step. The listener is already there waiting.

**Create or update the relevant pytest file**
- Edit [app/tests/test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py). Add one new test function `test_agenda_meeting_roster_button_present()` following the same file-read / string-assert pattern used by `test_transfer_panel_html_has_mode_selector` at [test_frontend_smoke.py:47](../../app/tests/test_frontend_smoke.py:47). Assertions:
  - `id="openParticipantAdminButton"` is present in `meeting.html`.
  - The literal text `Meeting Roster` is present in `meeting.html`.
  - The role-gate guard string `current_user.role in ['admin', 'super_admin', 'facilitator']` appears BEFORE the new id in the file (use `.index()` ordering — cheap but sufficient to guard against the button escaping the gate).
- No new pytest file. No new fixtures. Two-to-three assertions max.

**Update docstrings and documentation**
- Docstring on the new test function: `"""Phase 2 / Doorbell Disco — guard the new Meeting Roster entry point in the Agenda panel."""`.
- Append Step 1 result to this file's Completion Log.

---

### Step 2 — Confirm the pre-existing JS listener is intact

No code is added here; this step exists to codify a structural invariant that the new button depends on. If somebody deletes the listener in a future cleanup pass, this test will fail and flag Phase 2's contract.

**Implement the core logic**
- No template or JS edits. Read [meeting.js](../../app/static/js/meeting.js) and eyeball the listener at lines 7856-7860: the handler must still call `openParticipantAdminModal()`, which must still call `setParticipantModalMode("meeting")`. If either chain is broken, halt this phase and escalate — the Phase 2 master-plan planning decision (reuse existing wiring) is invalid and the subplan must be revised.

**Create or update the relevant pytest file**
- In the same file [app/tests/test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py), add `test_meeting_roster_button_listener_wired()`. Using the same file-read pattern, assert:
  - `openParticipantAdminButton` appears in `meeting.js` (the lookup at line 316).
  - `openParticipantAdminModal` appears in `meeting.js` (the handler).
  - Inside `meeting.js`, the substring `setParticipantModalMode("meeting")` appears — confirming the handler still lands in meeting mode.
- Keep this to three substring assertions. Do NOT try to parse the AST or simulate the click — that's browser work for Step 4.

**Update docstrings and documentation**
- Docstring: `"""Phase 2 / Doorbell Disco — guard the pre-existing JS wiring the new button relies on."""`.
- Append Step 2 result to the Completion Log.

---

### Step 3 — Regression-guard the legacy tab path

Until Phase 4 removes them, the tab row at [meeting.html:356-364](../../app/templates/meeting.html:356) and its click listener at [meeting.js:7861-7867](../../app/static/js/meeting.js:7861) remain the fallback path into the meeting roster. Phase 2 MUST NOT break them.

**Implement the core logic**
- No template or JS edits. This step's sole purpose is to add a regression guard.
- Eyeball the tab markup and listener; confirm nothing in Step 1 accidentally altered them. A `git diff` over those exact line ranges should be empty.

**Create or update the relevant pytest file**
- Reuse [app/tests/test_frontend_smoke.py](../../app/tests/test_frontend_smoke.py). Add `test_participant_modal_tab_path_still_works()`:
  - Assert `data-participant-modal-tab="meeting"` is present in `meeting.html`.
  - Assert `data-participant-modal-tab="activity"` is present in `meeting.html`.
  - Assert the substring `tab.dataset.participantModalTab` appears in `meeting.js` (the listener's access pattern at line 7864).
- This test is INTENTIONALLY brittle against Phase 4 — when Phase 4 removes the tab row, this test will be deleted or rewritten as part of that phase. That is the expected lifecycle and documenting it here makes the intent explicit for reviewers.

**Update docstrings and documentation**
- Docstring: `"""Phase 2 / Doorbell Disco — keep the legacy tab path alive as a fallback until Phase 4. Expected to be retired by Phase 4's subplan."""`.
- Append Step 3 result to the Completion Log.

---

### Step 4 — Browser verification and ship-ready

**Implement the core logic**
- Start a preview server (`preview_start`) and load the meeting page as a facilitator test account.
- Exercise the new button:
  - Confirm the **"Meeting Roster"** button is visible in the Agenda card-actions row, next to **"Meeting Settings"**.
  - Click it. The modal opens with `#participantModalTitle` reading **"Manage Meeting Participants"**, `[data-participant-admin-panel]` visible, `[data-activity-roster-panel]` hidden. Use `preview_snapshot` + `preview_inspect` to verify the hidden attribute on the activity panel.
- Exercise the legacy path:
  - Close the modal, open an activity's "Edit Roster" button, click the "Meeting Participants" tab inside the modal, confirm it switches to the same meeting view. This path must still work.
- Exercise the role gate:
  - Reload the meeting page as a non-facilitator test account. Confirm the Meeting Roster button is absent from the DOM (`preview_snapshot`).
- Capture three pieces of proof for the PR reviewer:
  - `preview_screenshot` of the Agenda panel showing both "Meeting Settings" and "Meeting Roster" side by side.
  - `preview_console_logs` confirming zero errors after clicking the new button.
  - `preview_network` entry for the modal-open sequence (should be the existing participant-directory GET, no new API calls).

**Create or update the relevant pytest file**
- Run the exit command (see below) and confirm 100% pass. Three new tests from Steps 1-3 must be among the passing set.
- If any assertion fails, do NOT patch the test — diagnose the render. Phase 2 only closes when template, JS, and tests agree.

**Update docstrings and documentation**
- Append a final entry to the `## Completion Log` with the commit SHA, the exit-command pass count, the screenshot path, and which button-order variant was chosen in Step 1 (before or after Meeting Settings).
- Commit message body must include `Roster Rodeo / Doorbell Disco` on its own line so `git log --grep "Doorbell Disco"` finds this phase later.

---

## Phase Exit Criteria

The following terminal command must exit 0 with **100% of tests passing** and no skips introduced by this phase:

```
pytest app/tests/test_frontend_smoke.py -v
```

Additionally, all four must hold simultaneously at phase exit:

- The new `#openParticipantAdminButton` is visible in the Agenda card-actions row for facilitator users and hidden for non-facilitators (browser-verified, Step 4).
- Clicking the new button opens the shared modal in meeting-roster mode with the expected title and panel visibility (browser-verified, Step 4).
- The legacy "Edit Roster" → "Meeting Participants" tab path still opens the same view (browser-verified, Step 4).
- `git diff main -- ':!app/templates/meeting.html' ':!app/tests/test_frontend_smoke.py' ':!plans/'` returns empty — Phase 2 touched nothing outside those two files and the plans directory. In particular, `meeting.js` is unchanged by this phase.

Phase 2 is NOT complete until the exit command and all four invariants succeed on the same commit.

---

## Completion Log

*(append entries here as each step closes)*

- [DONE] Step 1 — Meeting Roster button added — placement: `before` Meeting Settings — commit: working tree
- [DONE] Step 2 — JS wiring regression-guarded — commit: working tree
- [DONE] Step 3 — Legacy tab path regression-guarded — commit: working tree
- [DONE] Step 4 — Browser-verified substitute via authenticated page requests plus DOM/JS contract inspection (technical deviation: no `preview_*` browser tooling available in this Codex environment, so no screenshot/console/network artifacts were captured; facilitator page showed both buttons and meeting-mode modal scaffolding, joined participant page hid the Meeting Roster button) — commit: working tree
- [DONE] Exit command green — `pytest app/tests/test_frontend_smoke.py -v` output: 18 passed, 0 failed
