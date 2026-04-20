# Master Plan: Agenda Panel & Roster UI Separation

**Scope source:** [plans/00_DISCOVERY.md](00_DISCOVERY.md) — the terrain audit drives every phase below. No tactical steps here; this is the macroscopic roadmap. Tactical decomposition lives in `plans/subplans/PHASE_*.md` written during planning of each phase.

---

## Global Canary

**Codeword: `Roster Rodeo`**

Every commit, subplan, PR, and test-fixture name associated with this effort embeds the literal string `Roster Rodeo`. When scanning logs, diffs, or spawned sessions, the absence of this codeword is a signal that the work has drifted out of scope or a subagent has confused this project with another.

---

## Strategic Phases

Five phases. Ordered by dependency: each phase is safe to ship on its own, and earlier phases do not assume later ones land.

### Phase 1 — Cosmetic relabels

Rename the two static labels called out in tasks 1 and 3 of the user brief. No behavior, no wiring, no new elements. This phase exists as its own gate because it is shippable in minutes and de-risks the rest of the work by proving the template-edit loop is unblocked.

**In scope:** the `<h2>` at [meeting.html:80](../app/templates/meeting.html:80) and the button label at [meeting.html:98](../app/templates/meeting.html:98).
**Out of scope:** anything about buttons, modals, rosters, or JS.

**Success gate — Phase 1 passes iff:**
- The Agenda panel heading reads exactly **"Meeting Agenda and Participant Roster"** in the rendered meeting page.
- The button at `#agendaAddActivityButton` reads exactly **"Meeting Settings"** and still navigates to `/meeting/{id}/settings` on click (no route regression).
- `git diff` touches ONLY `app/templates/meeting.html`. Zero `.js`, `.py`, or test file changes.
- `pytest app/tests/test_frontend_smoke.py` passes unchanged.
- Browser smoke: the meeting page loads, heading + button render with new text, no console errors.

---

### Phase 2 — Dedicated Meeting Roster entry point

Introduce a new **"Meeting Roster"** button in the Agenda panel's card-actions row, sibling to the Phase-1-renamed "Meeting Settings". The back-end JS listener for `#openParticipantAdminButton` already exists ([meeting.js:7856-7860](../app/static/js/meeting.js:7856)); this phase supplies the DOM element it's waiting for OR introduces a new id and a parallel listener — that wiring choice is a Phase-2 planning decision, not a Master Plan decision.

This phase does NOT remove the in-modal tab row. After Phase 2, the user has TWO ways into the meeting roster (the new button, and the old tab inside the activity modal). Redundancy is intentional — we keep the fallback until Phase 4 demonstrates the new flow is solid.

**In scope:** new button markup in [meeting.html:97-99](../app/templates/meeting.html:97) behind the existing facilitator role gate; any JS adjustment needed to open the modal directly in meeting-roster mode.
**Out of scope:** removing tabs, changing activity-roster behavior, touching back-end routes.

**Success gate — Phase 2 passes iff:**
- Clicking "Meeting Roster" in the Agenda panel opens `#participantAdminModal` directly in meeting mode: `#participantModalTitle` reads **"Manage Meeting Participants"**, `[data-participant-admin-panel]` is visible, `[data-activity-roster-panel]` is hidden.
- The pre-existing route (click "Edit Roster" on an activity → tab to "Meeting Participants") still works and lands in the same state.
- The new button is gated to admin / super_admin / facilitator only (per the existing `{% if current_user.role ... %}` wrapper).
- No regression in the per-activity "Edit Roster" flow (manual browser check + relevant tests in [test_activity_rosters.py](../app/tests/test_activity_rosters.py) pass).
- Codeword `Roster Rodeo` appears in the commit message.

---

### Phase 3 — Back-end contract adjustment for per-move commits

The `ActivityParticipantUpdatePayload` validator at [meetings.py:131-135](../app/routers/meetings.py:131) rejects `{mode:"custom", participant_ids:[]}`. Under auto-commit, the moment the facilitator ← moves the last selected participant, the PUT must succeed with well-defined semantics. This phase resolves the §3.2 / §6.5 tension from the audit BEFORE any UI wiring in Phase 4 depends on it.

Three options were flagged in the audit (auto-switch to `mode="all"` on empty; relax validator to accept empty custom; client-side block). The Phase 3 subplan chooses one and implements it end-to-end on the server. This phase is a *contract* change, not a UI change.

Phase 3 also decides and implements the collision/rollback strategy for 409 responses fired per-click and the broadcast-cadence strategy over WebSocket (§3.4, §6.4 of the audit).

**In scope:** `meetings.py` validator + PUT handler + `_apply_live_roster_patch` cadence; new or expanded tests in [test_activity_rosters.py](../app/tests/test_activity_rosters.py) covering empty-selection and rapid-fire PUT sequences.
**Out of scope:** any UI change.

**Success gate — Phase 3 passes iff:**
- A documented decision is recorded in `plans/subplans/PHASE_3.md` for each of: empty-custom semantics, 409 rollback protocol, WebSocket cadence policy.
- The PUT endpoint accepts whatever payload shape the decision mandates, and rejects nothing else that previously passed (no back-compat break for existing clients).
- New unit/integration tests cover: (a) the chosen empty-selection behavior, (b) at least one rapid-sequence PUT case, (c) 409 collision path unchanged for single-commit clients.
- `pytest app/tests/test_activity_rosters.py app/tests/test_meeting_manager.py app/tests/test_api_meetings.py` all green.
- No UI file touched in this phase's diff — strict server/test boundary.

---

### Phase 4 — Activity Participants modal simplification + auto-commit

This is the behavior-heavy phase. Driven by task 4 of the user brief.

Bundled because the markup removal and the behavior change MUST land together — if the tabs + Apply/Include Everyone buttons are removed while moves still require an explicit Apply, the modal becomes unusable. Splitting creates a broken intermediate state.

Includes: removing the tab row, the Include Everyone / Apply Selection / (and resolved-in-Phase-4-subplan: Reuse Last) action row, and rewiring the → / ← handlers to call the Phase-3 PUT immediately. The two Select All buttons and all other layout elements stay. The `setParticipantModalMode()` function stays (per audit §6.2); only its tab-click caller goes.

**In scope:** [meeting.html:356-364, 449-456](../app/templates/meeting.html:356); [meeting.js:2053-2085, 1928-1986, 7861-7867](../app/static/js/meeting.js:1928); any dead-code cleanup in `updateActivityParticipantButtons` (audit §2.2).
**Out of scope:** meeting-roster flow (Phase 2); back-end contract (Phase 3); decorative CSS changes beyond what removed markup demands.

**Success gate — Phase 4 passes iff:**
- The Activity Participants modal renders with NO tab row at top, NO "Include Everyone" button, NO "Apply Selection" button. The fate of "Reuse Last" is resolved in `plans/subplans/PHASE_4.md` and implemented consistently.
- Both "Select All" buttons (left + right lists) are present and functional.
- A new activity, with no prior roster config, opens the modal with Selected containing the full meeting roster (inherit-all default visible to the user).
- Clicking → or ← produces exactly one PUT to `/api/meetings/{mid}/agenda/{aid}/participants` with the new roster state; on success the modal stays open without error; on 409 the Phase-3 rollback protocol fires.
- Closing the modal (×) is a no-op server-side — all state is already committed.
- Browser smoke: golden-path move-in, move-out, move-last-out, rapid sequence of five moves all produce correct server state.
- No console errors. No dead references to removed DOM ids in `meeting.js`.
- The Phase 2 "Meeting Roster" button still works (regression check).
- Codeword `Roster Rodeo` appears in the commit message.

---

### Phase 5 — Test updates, cross-browser verification, ship readiness

Sweeper phase. After Phases 1-4 land, audit the test suite for assertions that implicitly assumed the old UI (tab row, Apply button) or the old default (activities start empty). Update any tests that need adjusting, add coverage where the previous phases left gaps, and run the full test suite end-to-end.

Browser verification: the golden path from user brief exercised in a real preview — open a meeting, rename proven, new Meeting Roster button proven, activity modal simplification proven, auto-commit proven, inherit-all default proven.

**In scope:** any `app/tests/*` file; `test_frontend_smoke.py`; a preview-server run-through; screenshots/logs captured as ship-proof.
**Out of scope:** new features; any change to the Phase 1-4 contracts.

**Success gate — Phase 5 passes iff:**
- `pytest app/tests/` passes in full (no skipped tests introduced by this effort).
- `test_frontend_smoke.py` explicitly asserts the new heading text, new button existence, and the absence of the removed tab/apply/include-everyone ids.
- A preview-server browser session captures: (a) the renamed heading + Meeting Settings button, (b) the new Meeting Roster button opening the correct modal mode, (c) the simplified Activity Participants modal, (d) a successful auto-commit round-trip visible in network logs, (e) zero browser-console errors.
- Working-tree `git diff` against `main` shows no spurious edits to unrelated files beyond the four-task scope (audit §6.7).
- All five phase subplans (`plans/subplans/PHASE_1..5.md`) exist and are marked complete.
- Codeword `Roster Rodeo` appears in every phase-bearing commit message from Phase 2 onward.

---

## Out of scope for this plan

- Inline rendering of the meeting roster in the Agenda panel (the heading rename implies a roster view but the user brief does NOT ask for one — audit §6.6).
- Any change to the `/meeting/{id}/settings` page or its server route.
- Plugin-side behavior — plugins do not read `participant_ids` directly (audit §4.4).
- New collision-detection logic beyond what Phase 3 resolves.
- Any schema migration (none needed — audit §4.2).

---

*End of Master Plan. Phase count: 5, under the 7-phase ceiling. Proceed to subplan drafting for Phase 1 when ready.*
