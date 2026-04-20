# Technical Audit: Agenda Panel & Roster UI Separation

**Objective (context only — no code suggested):** map every module, data flow, and breaking point touched by four planned UI changes:

1. Rename Agenda-panel **"Settings"** button → **"Meeting Settings"**.
2. Add a new **"Meeting Roster"** button in the Agenda panel that ONLY edits the overall meeting roster (i.e. a dedicated entry point, separated from the per-activity flow).
3. Rename the panel heading **"Agenda"** → **"Meeting Agenda and Participant Roster"**.
4. Simplify the **Activity Participants** modal:
   - Remove the "Meeting Participants" / "Activity Roster" tab row.
   - Remove the "Include Everyone" and "Apply Selection" buttons.
   - Default an activity to inherit all meeting-roster participants.
   - Commit every left/right move immediately (no Apply step).
   - Keep the two "Select All" buttons.

---

## 1. Current UI Architecture

### 1.1 The single shared modal

There is **one** modal (`#participantAdminModal`) that currently handles BOTH the meeting roster and the per-activity roster. It has two panels switched by a tab row. This is the root cause of the user's "edited in the same place" complaint.

| Element | File:Line | Role |
|---|---|---|
| Modal container | [meeting.html:341](app/templates/meeting.html:341) | Shared overlay |
| Modal title | [meeting.html:345](app/templates/meeting.html:345) | Flips between "Manage Meeting Participants" and "Activity Participants" |
| Activity metadata row | [meeting.html:346-351](app/templates/meeting.html:346) | Hidden in meeting mode, shown in activity mode |
| Tab row (to be removed) | [meeting.html:356-364](app/templates/meeting.html:356) | `data-participant-modal-tab="meeting"` / `"activity"` |
| Meeting roster panel | [meeting.html:365-444](app/templates/meeting.html:365) | `data-participant-admin-panel` |
| Activity roster panel | [meeting.html:445-504](app/templates/meeting.html:445) | `data-activity-roster-panel`, `hidden` by default |
| Activity action row (to be removed) | [meeting.html:449-456](app/templates/meeting.html:449) | Include Everyone / Reuse Last / Apply Selection |
| Activity "Include Everyone" | [meeting.html:450](app/templates/meeting.html:450) | `#activityParticipantIncludeAll` |
| Activity "Reuse Last" (hidden by default) | [meeting.html:452](app/templates/meeting.html:452) | `#activityParticipantReuse` — see §6.1 open question |
| Activity "Apply Selection" | [meeting.html:454](app/templates/meeting.html:454) | `#activityParticipantApply` — primary, starts disabled |
| Activity "Select All" left (keep) | [meeting.html:464](app/templates/meeting.html:464) | `#activityAvailableSelectAllButton` |
| Activity "Select All" right (keep) | [meeting.html:489](app/templates/meeting.html:489) | `#activitySelectedSelectAllButton` |
| Activity move → | [meeting.html:478-479](app/templates/meeting.html:478) | `#activityMoveToSelectedButton` |
| Activity move ← | [meeting.html:480-481](app/templates/meeting.html:480) | `#activityMoveToAvailableButton` |

### 1.2 The Agenda panel

| Element | File:Line |
|---|---|
| Section container | [meeting.html:76](app/templates/meeting.html:76) `<section class="content-card meeting-agenda-card">` |
| Heading to rename (`<h2>Agenda</h2>`) | [meeting.html:80](app/templates/meeting.html:80) |
| Agenda summary pills | [meeting.html:81-84](app/templates/meeting.html:81) |
| "Settings" button to rename | [meeting.html:98](app/templates/meeting.html:98) `id="agendaAddActivityButton"` |
| Card-actions row (host for new Meeting Roster button) | [meeting.html:97-99](app/templates/meeting.html:97) |
| Facilitator role gate | [meeting.html:96](app/templates/meeting.html:96) `{% if current_user.role in ['admin', 'super_admin', 'facilitator'] %}` |

The Settings button currently navigates the whole page to `/meeting/{id}/settings` (handled at [meeting.js:7994-7998](app/static/js/meeting.js:7994)) — it does NOT open a modal. The server route is [pages.py:353](app/routers/pages.py:353).

### 1.3 Important invariant: there is no explicit "Meeting Roster" entry point today

`ui.openParticipantAdminButton` is wired in JS at [meeting.js:316, 7856-7860](app/static/js/meeting.js:316), but the DOM element `#openParticipantAdminButton` **does not exist in `meeting.html`**. Confirmed by grep — only two places reference the meeting-roster modal title, both inside the modal itself.

**Consequence:** today the only way to reach the meeting-roster editor from the meeting page is to open an activity's "Edit Roster" button and then click the "Meeting Participants" tab. This is exactly the coupling the user wants broken. Task 2 requires adding a real DOM button and the JS listener already exists waiting for it.

### 1.4 Per-activity entry point ("Edit Roster")

Each agenda row renders an "Edit Roster" button dynamically at [meeting.js:6261-6272](app/static/js/meeting.js:6261). Its click handler calls `openActivityParticipantModal(activity_id)` which:
- Shows the shared modal ([meeting.js:6495](app/static/js/meeting.js:6495))
- Calls `setParticipantModalMode("activity")` ([meeting.js:6507](app/static/js/meeting.js:6507))
- Loads the activity assignment via GET

`setParticipantModalMode()` at [meeting.js:6460-6493](app/static/js/meeting.js:6460) is the switch that swaps title, toggles panel visibility, and sets tab `data-active`. Removing the tab row does NOT remove the need for this function — the activity flow still calls it with `"activity"` and the meeting flow with `"meeting"`. The mode flag remains the load-bearing abstraction; only the in-modal tab UI is retired.

---

## 2. JavaScript State & Event Map

### 2.1 `activityParticipantState`

Defined at [meeting.js:857](app/static/js/meeting.js:857). Fields:

| Field | Meaning |
|---|---|
| `currentActivityId` | Which activity's roster is loaded |
| `selection` | `Set<userId>` — currently selected participants |
| `availableHighlighted` / `selectedHighlighted` | Transient highlight sets for the arrow-button move |
| `mode` | `"all"` or `"custom"` — source of truth for "inherit everyone" vs subset |
| `dirty` | True if local edits pending — gates Apply button |
| `loading` | True during GET/PUT |
| `lastCustomSelection` | Cached last-custom selection; feeds the hidden "Reuse Last" button |
| `lastLoadFailed` | Retry gate |

### 2.2 Handlers that change behavior under task 4

| Handler | Current behavior | Impact |
|---|---|---|
| `addActivityParticipantsFromAvailable()` [meeting.js:2053-2069] | Sets `dirty=true`, `mode="custom"`, local-only until Apply | Must call PUT immediately if auto-commit lands |
| `removeActivityParticipantsFromSelected()` [meeting.js:2070-2085] | Same — local, requires Apply | Same |
| `selectAllActivityAvailable()` [meeting.js:2031] / `selectAllActivitySelected()` [meeting.js:2048] | Toggle highlight only; the subsequent → / ← is the actual move | Unchanged — user explicitly keeps Select All |
| `applyActivityParticipantSelection(modeOverride)` [meeting.js:1928-1986] | Issues PUT, syncs state on success | Becomes the core commit primitive, called per move instead of per Apply click |
| `updateActivityParticipantButtons()` [meeting.js:~1599-1650] | Enables/disables Apply + Include Everyone based on `dirty` and `mode` | Dead code once buttons are gone |

### 2.3 Tab click listener (to be removed)

[meeting.js:7861-7867](app/static/js/meeting.js:7861) binds clicks on `[data-participant-modal-tab]` to `setParticipantModalMode(tab.dataset.participantModalTab)`. Remove the markup and this listener has nothing to find — but the *function* `setParticipantModalMode` itself must remain, because the per-activity and per-meeting open functions both still call it to configure the modal.

---

## 3. Back-End Contract

### 3.1 Activity roster endpoints

| Method & Path | File:Line | Payload |
|---|---|---|
| `GET /api/meetings/{mid}/agenda/{aid}/participants` | [meetings.py:1241](app/routers/meetings.py:1241) | Returns `{activity_id, mode, participant_ids, available_participants}` |
| `PUT /api/meetings/{mid}/agenda/{aid}/participants` | [meetings.py:1282](app/routers/meetings.py:1282) | Accepts `ActivityParticipantUpdatePayload` |

### 3.2 `ActivityParticipantUpdatePayload` — **critical constraint**

Defined at [meetings.py:113-139](app/routers/meetings.py:113). Validator:

- `mode: Literal["all", "custom"]` (default `"custom"`)
- `participant_ids: Optional[List[str]]`
- **If `mode == "custom"`, `participant_ids` MUST be a non-empty list** ([meetings.py:131-135](app/routers/meetings.py:131)).

**Implication for auto-commit:** if the user removes the LAST person from Selected via the ← button, the UI would need to issue a PUT that the server currently rejects. This is the single biggest behavioral seam in task 4. Options to consider (for the planning stage, not here):
- Auto-switch to `mode="all"` when the selection empties.
- Relax the validator to accept `{mode:"custom", participant_ids:[]}`.
- Block the last ← move client-side.

No choice is made here — this audit only flags the collision.

### 3.3 Meeting roster endpoints (already well-separated at the API layer)

| Method & Path | File:Line |
|---|---|
| `GET /api/meetings/{mid}/participants` | [meetings.py:1092](app/routers/meetings.py:1092) |
| `POST /api/meetings/{mid}/participants` | [meetings.py:1123](app/routers/meetings.py:1123) |
| `DELETE /api/meetings/{mid}/participants/{uid}` | [meetings.py:1170](app/routers/meetings.py:1170) |
| `POST /api/meetings/{mid}/participants/bulk` | [meetings.py:1206](app/routers/meetings.py:1206) |

**Conclusion:** the back-end already has a clean separation between meeting-roster and activity-roster endpoints. The coupling the user wants to break is purely in the UI.

### 3.4 Collision detection & real-time broadcast

- PUT activity roster does a conflict check if the activity is running ([meetings.py:1344-1390](app/routers/meetings.py:1344)), returning `409 Conflict` with a list of overlapping participants. Current UI surfaces this via the `#collisionModal` ([meeting.js:8001+]).
- On success, if activity is live, `_apply_live_roster_patch()` broadcasts the new roster over WebSocket ([meetings.py:639, 1404-1422]). Metadata includes `participantScope` and `participantIds`.

**Auto-commit amplification:** today one Apply click = one PUT = one potential 409 = one broadcast. Under auto-commit every → / ← could trigger the same. Two downstream risks flagged for planning:
1. A 409 returned *after* the user visually moved a chip will force a revert-UX that doesn't exist today.
2. WebSocket broadcast cadence rises from "once per facilitator decision" to "once per click." Rooms with many consumers see proportionally more traffic.

---

## 4. Data Model

### 4.1 Where activity rosters live

`AgendaActivity.config` is a JSON column. Per-activity roster state is encoded as:

- `config["participant_ids"]` **absent or removed** → `mode = "all"` (inherit meeting roster).
- `config["participant_ids"] = [ ... ]` → `mode = "custom"`.

Confirmed at [meeting_manager.py:1387-1441](app/data/meeting_manager.py:1387) (`set_activity_participants`): passing `None` pops the key; passing an iterable sets it. The assignment builder at [meetings.py:191](app/routers/meetings.py:191) reads `"custom" if participant_ids else "all"`.

### 4.2 Default for new activities

Freshly created activities have no `participant_ids` key in `config`, so they already resolve to `mode="all"` at read time. **No data migration is needed** to make "inherit all" the default — it already is, at the persistence layer. The UI's current "Include Everyone" button is a redundant re-assertion of a default the data already implies.

### 4.3 Roster pruning on meeting-participant removal

When a participant is removed from the meeting, [meeting_manager.py:1365-1371](app/data/meeting_manager.py:1365) strips their id from every activity's `config["participant_ids"]` and pops the key if the list empties. This integrity rule is orthogonal to the UI changes but must continue to hold.

### 4.4 Plugin read surface

Plugins (`voting_plugin.py`, `brainstorming_plugin.py`, `categorization_plugin.py`, `rank_order_voting_plugin.py`) do **not** read `participant_ids` directly — confirmed by grep over `app/plugins/`. Scope-aware logic (`participantScope`) is handled upstream in routers, e.g. [voting.py:92,118](app/routers/voting.py:92), [categorization.py:114,134](app/routers/categorization.py:114), [rank_order_voting.py:121,147](app/routers/rank_order_voting.py:121), [brainstorming.py:155](app/routers/brainstorming.py:155). No plugin change required by tasks 1-4.

---

## 5. Tests

### 5.1 Files in scope

| File | Coverage |
|---|---|
| [test_activity_rosters.py](app/tests/test_activity_rosters.py) | Primary: PUT with `mode="custom"`/`"all"`, validation |
| [test_api_meetings.py](app/tests/test_api_meetings.py) | Meeting-level participant CRUD |
| [test_api_participants.py](app/tests/test_api_participants.py) | Participant endpoints |
| [test_meeting_manager.py](app/tests/test_meeting_manager.py) | `set_activity_participants`, pruning |
| [test_api_user_directory.py](app/tests/test_api_user_directory.py) | Directory search feeding the meeting-roster "Add" form |
| [test_transfer_api.py](app/tests/test_transfer_api.py), [test_brainstorming_api.py](app/tests/test_brainstorming_api.py), [test_voting_api.py](app/tests/test_voting_api.py), [test_categorization_api.py](app/tests/test_categorization_api.py) | Read `participantScope` indirectly |
| [test_frontend_smoke.py](app/tests/test_frontend_smoke.py) | Does not reference any of the button labels or tab markup (grep confirmed) |

### 5.2 Likely-at-risk assertions

- Any test that posts `{mode: "custom", participant_ids: []}` and expects success — will still fail validation today, and the UI change may force a relaxation (§3.2). Grep shows `test_activity_rosters.py` only posts non-empty custom lists, so currently safe.
- No test currently asserts the presence of `#activityParticipantApply`, `#activityParticipantIncludeAll`, or the tab buttons.
- Nothing asserts the string "Agenda", "Settings", or "Edit Roster" as a heading/button label (grep of `test_frontend_smoke.py` returned no matches).

**Net:** the test surface is small. Risk is concentrated on **new** tests required for auto-commit semantics (especially the "remove last selected" case) and any Playwright-style smoke test that asserts the new Meeting Roster button exists.

---

## 6. Seams & Breaking Points

### 6.1 Open question: Reuse Last

The "Reuse Last" button at [meeting.html:452](app/templates/meeting.html:452) is in the same action row the user asked to remove, but the user's description only explicitly calls out "Include Everyone" and "Apply Selection." It's hidden by default and becomes visible when `lastCustomSelection` exists ([meeting.js:1870]). Whether it survives the cleanup is a scope decision, not a technical blocker. Flagged here; not resolved.

### 6.2 Shared `setParticipantModalMode` stays

Even after the tabs are gone, the meeting-roster open path ([meeting.js:6517-6527]) and the activity-roster open path ([meeting.js:6495-6515]) both call `setParticipantModalMode()`. The function's *caller* set changes (tabs stop calling it), but the function itself remains the contract that configures the modal. Removing it would break both flows.

### 6.3 New button needs a new DOM id

JS already listens for `#openParticipantAdminButton` ([meeting.js:316, 7856-7860]) but no such element exists in any template today. Task 2's new "Meeting Roster" button can either reuse this id (lowest-effort wire-up) or take a new id. Either way, the Agenda panel's action row at [meeting.html:97-99](app/templates/meeting.html:97) is the natural host, and the role gate at line 96 already restricts it to admin/super_admin/facilitator.

### 6.4 Auto-commit collision points

- **Empty-selection PUT rejected** — see §3.2.
- **409 after optimistic move** — current UX assumes a deliberate Apply; per-click would need a rollback pattern.
- **Last-write-wins races** — two quick → clicks could overlap PUTs; the back-end is idempotent on full-state replace, but ordering still matters.
- **WebSocket cadence** — every commit broadcasts; noisy under rapid edits.

### 6.5 Default-semantics drift

The data layer *already* defaults to `mode="all"`. Removing "Include Everyone" makes the UI finally match the storage truth — but it also removes the only visible affordance that *undoes* a custom selection back to "all." Once the button is gone, the only path back to "inherit all" is "remove every person from Selected," which collides with §3.2. This tension is the single most important design decision deferred to the planning stage.

### 6.6 Agenda-panel rename is label-only

The `<h2>Agenda</h2>` at [meeting.html:80](app/templates/meeting.html:80) is referenced by no JS selector, no test, no CSS rule by text (classes are `agenda-header`, `agenda-title-row`). Renaming it is cosmetically safe. If the new label "Meeting Agenda and Participant Roster" suggests the roster should be rendered *inline* in the panel, that is a larger reshape the user has not requested — this audit assumes only the heading text changes.

### 6.7 Uncommitted working-tree changes

`git status` at session start showed modifications to [meeting.js](app/static/js/meeting.js), [create_meeting.html](app/templates/create_meeting.html), [meeting_manager.py](app/data/meeting_manager.py), and assorted router/test files — all carried forward to this branch. Spot-check showed no in-flight edits to the Agenda panel, the participant modal, or the activity-participant handlers. Low collision risk, but a real `git diff` review is warranted before planning edits overlap these regions.

---

## 7. Summary Map

| Concern | Location |
|---|---|
| Agenda heading rename | [meeting.html:80](app/templates/meeting.html:80) |
| "Settings" button rename | [meeting.html:98](app/templates/meeting.html:98) |
| New "Meeting Roster" button host row | [meeting.html:97-99](app/templates/meeting.html:97) |
| Already-wired JS listener awaiting button | [meeting.js:316, 7856-7860](app/static/js/meeting.js:7856) |
| Modal tab row removal | [meeting.html:356-364](app/templates/meeting.html:356) |
| Modal tab listener removal | [meeting.js:7861-7867](app/static/js/meeting.js:7861) |
| Action-row removal (Include Everyone / Apply / ?Reuse Last) | [meeting.html:449-456](app/templates/meeting.html:449) |
| Select All buttons (keep) | [meeting.html:464, 489](app/templates/meeting.html:464) |
| Auto-commit entry points | [meeting.js:2053-2085](app/static/js/meeting.js:2053) (move handlers) + [meeting.js:1928-1986](app/static/js/meeting.js:1928) (PUT) |
| Empty-custom validation blocker | [meetings.py:131-135](app/routers/meetings.py:131) |
| Collision + live-patch amplification | [meetings.py:1344-1422](app/routers/meetings.py:1344), [meetings.py:639](app/routers/meetings.py:639) |
| Data-layer default already "all" | [meeting_manager.py:1387-1441](app/data/meeting_manager.py:1387), [meetings.py:191](app/routers/meetings.py:191) |

---

*End of terrain audit. No code changes or design choices are made here — the planning document will resolve §6.1 (Reuse Last fate), §6.4 (auto-commit race/validation strategy), and §6.5 (how a facilitator returns to "inherit all" after a custom edit).*
