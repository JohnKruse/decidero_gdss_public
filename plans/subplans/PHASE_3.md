# Phase 3 — Back-End Contract for Per-Move Commits

**Master plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Global canary:** `Roster Rodeo`
**Phase canary:** `Payload Polka`

Both canaries must appear in every Phase-3 commit body, the PR description, and any subagent delegation prompt.

---

## Goal

Make the activity-roster PUT endpoint safe to call once per ← / → click from Phase 4. Today the endpoint enforces `{mode:"custom", participant_ids:[]}` as invalid ([meetings.py:131-135](../../app/routers/meetings.py:131)) and broadcasts a full-state roster patch per PUT ([meetings.py:639](../../app/routers/meetings.py:639), §3.4 / §6.4 of the audit). Phase 4's auto-commit UI will drive these paths orders-of-magnitude more often than Apply-click-driven calls do today. This phase settles the server-side contract before that UI lands.

**Strict scope rule:** zero UI files touched. No edits under `app/templates/`, `app/static/`, or any `.html`/`.js`/`.css`. If you find yourself opening one, stop — that's Phase 4.

---

## Decisions locked in this phase

The Master Plan deferred three choices here. They are resolved now so downstream steps and Phase 4 can assume them.

### Decision 1 — Empty-custom semantics: **server normalizes to `mode="all"`**

When the client PUTs `{mode:"custom", participant_ids:[]}` (i.e. the last ← move that empties Selected), the router normalizes to `{mode:"all", participant_ids:None}` BEFORE calling `MeetingManager.set_activity_participants`. The response body reflects the normalized mode, so the client sees `mode="all"` and re-renders the Selected column with the full meeting roster.

**Why this option over the other two (audit §3.2, §6.5):**
- *Relaxing the validator to accept empty-custom as "activity has nobody"* would invent a new state (zero-participant activity) that plugins and downstream views do not currently handle. Rejected.
- *Client-side block on the last ←* leaves a facilitator staring at an empty Selected column with no way to recover except closing and reopening. Rejected.
- *Server normalization* matches the data-layer truth that `config["participant_ids"]` absence already means "inherit all" (audit §4.1, §4.2). The empty-custom state is a transient UI artifact; the server collapses it to the canonical representation.

### Decision 2 — 409 collision response: **enriched body, client reverts via refetch**

When PUT returns `409 Conflict` on a running-activity collision, the response body includes: the list of conflicting users (already present today), plus the authoritative current assignment (`mode`, `participant_ids`, `available_participants`) the client can use to re-render without issuing a follow-up GET. The client-side rollback protocol (implemented in Phase 4) is: on 409, render using the `current_assignment` field from the 409 body; do NOT issue a follow-up GET.

**Why:** per-click auto-commit will occasionally race. A facilitator should see their doomed move snap back to the last authoritative state in one round-trip, not two.

### Decision 3 — Broadcast cadence: **per-PUT, full-state, idempotent**

`_apply_live_roster_patch` already emits full participant-state on every PUT ([meetings.py:639](../../app/routers/meetings.py:639)). No server-side debounce is introduced. The contract is explicit: each broadcast is a full replacement of `participantScope` + `participantIds`, so receivers may drop, dedupe, or collapse intermediate broadcasts safely. Documented here so Phase 4 and any plugin consumer can rely on the guarantee.

**Why not debounce:** debounce adds server-side state and latency, and the broadcast payload is already cheap. The correct place to absorb chatter is the receiver, not the emitter. A follow-up effort can add a rate-limit if WebSocket traffic proves problematic in practice — but this phase does not speculate.

---

## Atomic Steps

### Step 1 — Normalize empty-custom at the PUT boundary (Decision 1)

**Implement the core logic**
- In [app/routers/meetings.py](../../app/routers/meetings.py), locate `ActivityParticipantUpdatePayload` at [meetings.py:113-139](../../app/routers/meetings.py:113). Remove the validator branch that raises when `mode=="custom"` and `participant_ids` is empty — replace with a post-parse normalization: if `mode=="custom"` and `participant_ids` is falsy (None or empty list), set `mode="all"` and `participant_ids=None` on the validated object (or return a fresh normalized payload if the model prohibits mutation). Keep all other validation (per-id string cleanup, meeting-membership check) intact.
- In the PUT handler at [meetings.py:1282+](../../app/routers/meetings.py:1282), route the post-normalization payload through the existing `payload.mode == "custom"` branches. Confirm `set_activity_participants(participant_ids=None)` is called for the normalized all-path — [meeting_manager.py:1424-1425](../../app/data/meeting_manager.py:1424) already pops the config key, so no data-layer change is needed.
- Confirm the response builder at [meetings.py:191](../../app/routers/meetings.py:191) returns `mode="all"` in this case (it derives from `participant_ids` truthiness — already correct).

**Create or update the relevant pytest file**
- Edit [app/tests/test_activity_rosters.py](../../app/tests/test_activity_rosters.py). Add `test_put_empty_custom_normalizes_to_all()` modelled on the existing PUT test at [test_activity_rosters.py:145-161](../../app/tests/test_activity_rosters.py:145). Scenario:
  - Setup: meeting with ≥2 participants, activity with `{mode:"custom", participant_ids:[p1]}` pre-set.
  - Action: PUT `{mode:"custom", participant_ids:[]}`.
  - Assert: response status 200, `data["mode"] == "all"`, `data["participant_ids"]` is empty or null (per existing response schema), and a follow-up GET also reports `mode=="all"`.
- Also add `test_put_empty_custom_still_rejects_invalid_ids()`: PUT `{mode:"custom", participant_ids:["not-a-real-user"]}` must still fail (the membership check is preserved).

**Update docstrings and documentation**
- Update the `ActivityParticipantUpdatePayload` class docstring to state: "An empty participant_ids under mode='custom' is normalized server-side to mode='all'. See plans/subplans/PHASE_3.md Decision 1."
- Update the PUT handler's docstring (or add one if absent) with the same one-liner plus the `Roster Rodeo / Payload Polka` canary.
- Append Step 1 result to the Completion Log below.

---

### Step 2 — Verify MeetingManager invariants under the new normalization

Server-side normalization relies on `set_activity_participants(participant_ids=None)` popping the config key. That is tested today, but not specifically under the "was custom, now all via empty PUT" transition. Close the gap.

**Implement the core logic**
- No code change expected in this step. Read [meeting_manager.py:1387-1441](../../app/data/meeting_manager.py:1387) and confirm:
  - Passing `participant_ids=None` pops the config key.
  - Passing an empty iterable also pops the key (current code: `if cleaned: config[...] = cleaned; else: config.pop(...)`).
- Confirm the roster-prune path at [meeting_manager.py:1365-1371](../../app/data/meeting_manager.py:1365) still pops the key when pruning empties a custom list. If it does not, halt and escalate — that would indicate a hidden bug the UI change would expose.

**Create or update the relevant pytest file**
- Edit [app/tests/test_meeting_manager.py](../../app/tests/test_meeting_manager.py). Add `test_set_activity_participants_empty_list_pops_key()`:
  - Setup: activity with `config["participant_ids"] = [p1]`.
  - Action: `set_activity_participants(meeting_id, activity_id, participant_ids=[])`.
  - Assert: `config` no longer contains the `participant_ids` key; the subsequent GET via the router returns `mode="all"`.
- Add `test_remove_meeting_participant_pops_empty_custom()`:
  - Setup: activity with `config["participant_ids"] = [p1]`.
  - Action: remove `p1` from the meeting.
  - Assert: the activity config now has no `participant_ids` key (meaning the prune branch took the pop path, not the "set to empty list" path).

**Update docstrings and documentation**
- Add a docstring on both new test functions with the `Roster Rodeo / Payload Polka` canary and a one-sentence description.
- If `set_activity_participants` has a docstring, append the line: "Empty or None participant_ids both collapse to inherit-all; callers must not rely on the list existing as an empty array in config."
- Append Step 2 result to the Completion Log.

---

### Step 3 — Enrich the 409 collision response (Decision 2)

**Implement the core logic**
- In the PUT handler's collision-detection block at [meetings.py:1344-1390](../../app/routers/meetings.py:1344), the current HTTPException returns conflicting-user info. Extend the 409 response body with a `current_assignment` field containing the authoritative `{mode, participant_ids, available_participants}` for the target activity — built from the SAME helper (`_build_activity_participant_assignment`) the GET endpoint uses at [meetings.py:191](../../app/routers/meetings.py:191). Do NOT mutate server state before raising.
- Preserve the existing `conflicting_users` field (or whatever name it uses — match the current key exactly) so today's collision-modal JS at [meeting.js:8001+](../../app/static/js/meeting.js:8001) is not broken. The change must be additive only.

**Create or update the relevant pytest file**
- Edit [app/tests/test_activity_rosters.py](../../app/tests/test_activity_rosters.py). Add `test_put_409_includes_current_assignment()`:
  - Setup: two running activities with overlapping participant pools, configured so a PUT on one would create a prohibited overlap with the other.
  - Action: PUT the colliding roster.
  - Assert: status 409, body contains both `conflicting_users` (existing) and `current_assignment` (new). `current_assignment.mode` + `current_assignment.participant_ids` match the pre-PUT state (not the attempted state).
- Add `test_put_409_does_not_mutate_state()`:
  - After the 409, issue a fresh GET on the activity. The returned assignment equals the pre-PUT state.

**Update docstrings and documentation**
- Update the PUT handler docstring to document the 409 response schema: "On collision, the 409 response body contains `conflicting_users` (unchanged) and `current_assignment` (the authoritative pre-PUT state). See Decision 2 in PHASE_3.md. Clients may render from `current_assignment` directly without a follow-up GET."
- Append Step 3 result to the Completion Log.

---

### Step 4 — Lock the broadcast cadence contract (Decision 3)

**Implement the core logic**
- Read `_apply_live_roster_patch` at [meetings.py:639](../../app/routers/meetings.py:639) and confirm every broadcast includes full `participantScope` + `participantIds`. If the function currently emits a delta rather than a full state, halt — Decision 3 is invalid and the subplan must be revised.
- No debounce, no rate-limit, no new queue. The only change in this step is documenting the guarantee and adding a regression test.

**Create or update the relevant pytest file**
- Edit [app/tests/test_activity_rosters.py](../../app/tests/test_activity_rosters.py). Add `test_rapid_put_sequence_final_state_wins()`:
  - Setup: running activity with a known roster.
  - Action: issue three PUTs in quick succession (sequential is fine — FastAPI TestClient is synchronous): `[p1]` → `[p1, p2]` → `[p1, p2, p3]`.
  - Assert: a final GET returns `participant_ids` equal to `[p1, p2, p3]` (order-insensitive compare). No intermediate request should have returned non-200.
- Add `test_broadcast_payload_is_full_state()` — reach into the broadcast queue/mock used by the existing rank-order / voting router tests (copy the fixture pattern from [test_api_meetings.py](../../app/tests/test_api_meetings.py) or a sibling), and assert the broadcast captured after a PUT contains both `participantScope` and `participantIds` keys. If no such broadcast fixture exists in the test suite, mark this assertion TODO and add a unit-level assertion against the helper directly.

**Update docstrings and documentation**
- Add/extend the docstring on `_apply_live_roster_patch` with: "Each call broadcasts the full roster state. Receivers must treat consecutive broadcasts as idempotent replacements, not deltas. See Decision 3 in PHASE_3.md."
- Append Step 4 result to the Completion Log.

---

### Step 5 — Full regression sweep and ship-ready

**Implement the core logic**
- Run the phase exit command (below) and confirm 100% pass.
- Run a broader sanity sweep — `pytest app/tests/test_transfer_api.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_categorization_api.py -q` — to catch any router consumer that implicitly assumed the old validator behavior. Fix any fallout in-place; extending the sweep is part of Phase 3's scope. If a fix would require a UI touch, halt and escalate — Phase 3's no-UI rule holds.
- Do NOT touch [meeting.js](../../app/static/js/meeting.js), [meeting.html](../../app/templates/meeting.html), or any CSS. If any test fails because the UI assumes a pre-normalization payload shape, note it for Phase 4's subplan and move on — Phase 4 will adjust the UI.

**Create or update the relevant pytest file**
- No new tests in this step — the sweep exercises everything added in Steps 1-4 plus the broader suite. If the sweep reveals a gap (e.g. an endpoint that swallows 409 bodies), ADD a test to pin the gap but only where it is strictly server-side.

**Update docstrings and documentation**
- Append the final Completion Log entry with commit SHA, exit-command pass count, broader-sweep pass count, and any carry-forward notes for Phase 4.
- Commit message body must include `Roster Rodeo / Payload Polka` on its own line.

---

## Phase Exit Criteria

The following terminal command must exit 0 with **100% of tests passing** and no skips introduced by this phase:

```
pytest app/tests/test_activity_rosters.py app/tests/test_meeting_manager.py app/tests/test_api_meetings.py -v
```

Additionally, all five must hold simultaneously at phase exit:

- Every new test added in Steps 1-4 is present, passing, and carries the `Roster Rodeo / Payload Polka` canary in its docstring.
- `git diff main -- ':!app/routers/meetings.py' ':!app/data/meeting_manager.py' ':!app/tests/' ':!plans/'` returns empty — Phase 3 touched nothing outside those four buckets. In particular, `app/templates/`, `app/static/`, and `app/plugins/` are untouched.
- A `git grep -nP "must include at least one member"` (the old validator error text) returns NO match under `app/` — confirming the strict empty-custom rejection is fully removed.
- The 409 collision response body contains a `current_assignment` field (new test from Step 3 pins this).
- The broader sweep `pytest app/tests/test_transfer_api.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_categorization_api.py -q` also exits 0.

Phase 3 is NOT complete until the exit command and all five invariants succeed on the same commit.

---

## Completion Log

- [DONE] Step 1 — Empty-custom PUT payloads normalized server-side to `mode="all"`; invalid participant IDs still rejected (technical deviation: shell lacked `pytest` on PATH, so verification ran via `venv/bin/python -m pytest`) — commit: working tree
- [DONE] Step 2 — MeetingManager invariants verified for empty-list and prune-to-empty transitions; router GET confirms inherit-all fallback (technical deviation: shell lacked `pytest` on PATH, so verification ran via `venv/bin/python -m pytest`) — commit: working tree
- [DONE] Step 3 — 409 collision response enriched with `current_assignment`; rejected roster updates leave persisted state unchanged (technical deviation: shell lacked `pytest` on PATH, so verification ran via `venv/bin/python -m pytest`) — commit: working tree

*(append entries here as each step closes)*

- [ ] Step 1 — Empty-custom normalization in router — commit: __________
- [ ] Step 2 — MeetingManager invariants verified — commit: __________
- [ ] Step 3 — 409 response enriched with `current_assignment` — commit: __________
- [ ] Step 4 — Broadcast cadence contract locked — commit: __________
- [ ] Step 5 — Regression sweep clean; carry-forward notes: __________ — commit: __________
- [ ] Exit command green — `pytest app/tests/test_activity_rosters.py app/tests/test_meeting_manager.py app/tests/test_api_meetings.py -v` output: __________ passed, 0 failed
