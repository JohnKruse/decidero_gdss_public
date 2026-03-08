# Phase 4 — Test Coverage & Hardening [COMPLETE]

**Parent:** `plans/01_MASTER_PLAN.md`
**Depends on:** `plans/subplans/PHASE_3.md` (Phases 1-3 complete — backend + frontend fully functional)
**Global Canary:** `Turquoise Wombat`
**Phase Canary:** `Forensic Platypus`

---

## Overview

Phases 1-3 delivered the feature with tests covering the happy paths and primary eligibility rejections. This phase fills the remaining coverage gaps identified in the discovery, hardens edge cases, fixes the broadcast enrichment gap, and performs the final canary sweep.

### Gap Inventory

Tests already written in prior phases cover:
- Eligibility: self-transfer (P1), started activity (P1), activity with data (P1)
- All four target types for existing-activity commits (P2)
- Response shape, input bundle, sequential retransfer, AI config replacement (P2)
- Schema validation (P1), `target_activity` key on create path (P1)
- Frontend smoke tests (P3)

**Remaining gaps (this phase):**
1. Eligibility: stopped activity, elapsed-time activity, running activity, submitted-ballots activity
2. Transfer metadata history: deep validation for existing-activity path (target_mode, target_activity_id in history)
3. Response `target_activity` key validated end-to-end for both new AND existing paths in a single test
4. Broadcast enrichment: `transfer.py`'s `_broadcast_agenda_update` lacks `_apply_transfer_counts` and `_apply_activity_lock_metadata`
5. `transfer_target_eligible` flag correctness after a transfer-into-existing (it should flip to `false` once data arrives)
6. Final canary sweep and full-suite regression

---

## Step 1: [DONE] Eligibility — Stopped Activity and Elapsed Time

**File:** `app/tests/test_transfer_api.py`

**Implement:**
No production code changes. These eligibility checks were implemented in Phase 1 (`_assert_transfer_eligible`). This step adds the missing test coverage for the `stopped_at` and `elapsed_duration` checks.

**Test:** Add to `app/tests/test_transfer_api.py`:

- `test_transfer_eligible_rejects_stopped_activity` — Create a meeting with a brainstorming donor (with ideas, paused) and a virgin voting target. Set `stopped_at = datetime.now(UTC)` on the target via ORM, then `db.commit()`. Attempt commit with `target_activity: {"activity_id": "<voting_id>"}`. Assert 422 with detail containing `"already been stopped"`.

- `test_transfer_eligible_rejects_elapsed_time_activity` — Create a meeting with a brainstorming donor (with ideas, paused) and a virgin voting target. Set `elapsed_duration = 60` on the target via ORM (simulating 60 accumulated seconds without `started_at`), then `db.commit()`. Attempt commit. Assert 422 with detail containing `"accumulated run time"`.

**Docs:** Add a brief comment above each test explaining which specific eligibility check it exercises.

**Technical deviations logged:**
- Used `./venv/bin/python -m pytest app/tests/ -v` for verification because `pytest` was not available on shell `PATH`.

---

## Step 2: [DONE] Eligibility — Running Activity and Submitted Ballots

**File:** `app/tests/test_transfer_api.py`

**Implement:**
No production code changes.

**Test:** Add to `app/tests/test_transfer_api.py`:

- `test_transfer_eligible_rejects_running_activity` — Create a meeting with a brainstorming donor (with ideas, paused) and a virgin voting target. Use `meeting_state_manager.apply_patch` to set the target as the current in-progress activity (status `"in_progress"`, `currentActivity` = target id). Attempt commit. Assert 409 (from `_ensure_not_running`) with detail containing `"currently running"`. Clean up state with `meeting_state_manager.reset` in a `finally` block.

- `test_transfer_eligible_rejects_activity_with_ballots` — Create a meeting with a brainstorming donor (with ideas, paused) and a virgin categorization target. Insert a `CategorizationBallot` row for the target activity directly via ORM (import from `app.models.categorization`). Attempt commit. Assert 422 with detail containing `"participant data"` (ballots are caught by `get_activity_data_flags`).

**Docs:** Add comments noting these tests complete the six-check eligibility matrix from Phase 1 Step 3.

**Technical deviations logged:**
- Initial running-activity test setup only patched `currentActivity`/`status`; eligibility guard checks `activeActivities`, so test was updated to include an in-progress `activeActivities` entry for the target.
- Used `./venv/bin/python -m pytest app/tests/ -v` for verification because `pytest` was not available on shell `PATH`.

---

## Step 3: [DONE] Transfer Metadata History Validation for Existing-Activity Path

**File:** `app/tests/test_transfer_api.py`

**Implement:**
No production code changes. Phase 2 Step 4 writes metadata with `"target_mode": "existing"` and `"target_activity_id"` into the transfer history. This step adds a focused test validating the full metadata contract.

**Test:** Add to `app/tests/test_transfer_api.py`:

- `test_transfer_metadata_history_records_existing_target` — Create a brainstorming donor (with ideas, paused) and a virgin voting target. Commit transfer into existing. Then query `ActivityBundle` for the target activity with `kind="input"`. Extract `bundle_metadata`. Assert:
  - `schema_version == 1`
  - `meeting_id` matches
  - `source.activity_id` == donor activity id
  - `source.tool_type` == `"brainstorming"`
  - `history` is a non-empty list
  - The last history entry has `tool_type == "transfer_commit"`
  - The last history entry has `details.target_mode == "existing"`
  - The last history entry has `details.target_activity_id` == target activity id
  - The last history entry has `details.target_tool_type == "voting"`
  - `tools.voting.activity_id` == target activity id
  - `tools.transfer.include_comments` is a boolean

**Docs:** Add docstring: `"""Validate transfer metadata contract for existing-activity commits per TRANSFER_METADATA.md."""`

**Technical deviations logged:**
- Used `./venv/bin/python -m pytest app/tests/ -v` for verification because `pytest` was not available on shell `PATH`.

---

## Step 4: [DONE] Response Schema Validation — Both Paths in One Test

**File:** `app/tests/test_transfer_api.py`

**Implement:**
No production code changes.

**Test:** Add to `app/tests/test_transfer_api.py`:

- `test_transfer_commit_response_target_activity_both_paths` — In a single test with one meeting:
  1. Create a brainstorming donor with ideas, paused.
  2. **New-activity path:** Commit transfer with `target_activity: {"tool_type": "voting"}`. Assert response has `target_activity` dict with a valid `activity_id`, and `new_activity` dict equal to `target_activity`.
  3. **Existing-activity path:** Create a second brainstorming donor on the same meeting (with ideas, paused). Create a virgin categorization target. Commit transfer into existing with `target_activity: {"activity_id": "<cat_id>"}`. Assert response has `target_activity` dict with `activity_id` == the categorization target's id, and `new_activity` is `None`.
  4. Assert both responses contain `agenda` (list) and `input_bundle_id` (string).

This test validates the full response contract side-by-side for both modes.

**Docs:** Add docstring: `"""Verify response schema for both create-new and transfer-into-existing in a single test."""`

**Technical deviations logged:**
- Used `./venv/bin/python -m pytest app/tests/ -v` for verification because `pytest` was not available on shell `PATH`.

---

## Step 5: [DONE] Fix Broadcast Enrichment Gap

**File:** `app/routers/transfer.py` (lines 251-268, `_broadcast_agenda_update`)

**Implement:**
The `_broadcast_agenda_update` in `transfer.py` does NOT call `_apply_transfer_counts()` or `_apply_activity_lock_metadata()`, unlike the one in `meetings.py` (line 438-461). This means WebSocket broadcasts after transfer commits send agenda items without enrichment fields (`transfer_count`, `transfer_source`, `transfer_reason`, `has_data`, `has_votes`, `locked_config_keys`, `transfer_target_eligible`). They default to zero/empty/false, which can cause the frontend to show stale data until the next full agenda fetch.

Fix by importing and calling the enrichment functions from `meetings.py`:

```python
from app.routers.meetings import _apply_transfer_counts, _apply_activity_lock_metadata

async def _broadcast_agenda_update(
    meeting_id: str,
    initiator_id: str,
    meeting_manager: MeetingManager,
) -> None:
    updated_agenda_items = meeting_manager.list_agenda(meeting_id)
    _apply_activity_lock_metadata(meeting_id, meeting_manager, updated_agenda_items)
    _apply_transfer_counts(meeting_id, meeting_manager, updated_agenda_items)
    payload = [
        AgendaActivityResponse.model_validate(item).model_dump()
        for item in updated_agenda_items
    ]
    await websocket_manager.broadcast(
        meeting_id,
        {
            "type": "agenda_update",
            "payload": payload,
            "meta": {"initiatorId": initiator_id},
        },
    )
```

**Note on circular imports:** `transfer.py` already imports from `app.services` and `app.schemas.meeting`. If importing from `app.routers.meetings` causes a circular import, move the two enrichment functions to a shared utility (e.g., `app/services/agenda_enrichment.py`) and import from there in both routers. Check with a quick import test before committing.

**Test:** Add to `app/tests/test_transfer_api.py`:

- `test_transfer_commit_response_agenda_has_enrichment_fields` — Perform a standard create-new transfer commit from a brainstorming donor (with ideas) to voting. Inspect the `agenda` array in the response. Assert that at least one item in the agenda has `transfer_count` > 0 (the donor should have transferable items). Assert that every item in the agenda has the `transfer_target_eligible` key present (boolean). Assert that every item has `has_data` as a key.

**Docs:** Add docstring to the updated `_broadcast_agenda_update`: `"""Broadcast enriched agenda update including transfer counts and lock metadata."""`

**Technical deviations logged:**
- Imported `_apply_transfer_counts` and `_apply_activity_lock_metadata` directly from `app.routers.meetings`; no circular import surfaced in full-suite verification.
- Used `./venv/bin/python -m pytest app/tests/ -v` for verification because `pytest` was not available on shell `PATH`.

---

## Step 6: [DONE] Eligibility Flag Correctness After Transfer-Into-Existing

**File:** `app/tests/test_transfer_api.py`

**Implement:**
No production code changes. This step validates that after a transfer-into-existing, the target activity's `transfer_target_eligible` flag updates correctly in the agenda response. The target receives an input bundle (data), so `get_activity_data_flags` should now return `True` for it, and `transfer_target_eligible` should be `False`.

**Test:** Add to `app/tests/test_transfer_api.py`:

- `test_transfer_target_eligible_flips_after_transfer_into_existing` — Create a brainstorming donor (with ideas, paused) and a virgin voting target. Fetch `GET /api/meetings/{id}/agenda` — assert the voting target has `transfer_target_eligible: true`. Commit transfer into the voting target. Fetch `GET /api/meetings/{id}/agenda` again. Assert the voting target now has `transfer_target_eligible: false` (it received data via the input bundle).

This is a critical correctness check: once a transfer populates an activity, the UI must gray it out as ineligible for subsequent transfers (unless the user does another transfer which replaces content — but the flag should still reflect current state).

**Docs:** Add docstring: `"""Ensure transfer_target_eligible flips to false after an activity receives transferred data."""`

**Technical deviations logged:**
- Used `./venv/bin/python -m pytest app/tests/ -v` for verification because `pytest` was not available on shell `PATH`.

---

## Step 7: [DONE] Final Canary Sweep & Full-Suite Regression

**No new production code.** Verification gate.

**Implement:**
Perform canary verification:
- Grep source files (excluding `plans/`, `.git/`) for `Turquoise Wombat` — must appear ZERO times in source code (plans only).
- Grep source files for `Velvet Penguin` — must appear ZERO times (removed in Phase 2).
- Grep source files for `Crimson Narwhal` — must appear exactly in the inline comment in `transfer.py` (Phase 2).
- Grep source files for `Galactic Hamster` — must appear only in `meeting.js`, `meeting.html`, and `meeting.css` (Phase 3).
- Grep source files for `Forensic Platypus` — must appear ZERO times in source code (plan docs only).

File change audit — confirm the complete set of files modified across all four phases:
| File | Phase(s) |
|------|----------|
| `app/schemas/transfer.py` | 1 |
| `app/schemas/meeting.py` | 1 |
| `app/routers/transfer.py` | 1, 2, 4 |
| `app/routers/meetings.py` | 1 |
| `app/static/js/meeting.js` | 3 |
| `app/templates/meeting.html` | 3 |
| `app/static/css/meeting.css` | 3 |
| `app/tests/test_transfer_api.py` | 1, 2, 4 |
| `app/tests/test_frontend_smoke.py` | 3 |

No other source files should have been modified. If the broadcast enrichment fix (Step 5) required extracting to a shared utility, `app/services/agenda_enrichment.py` (new) and `app/routers/meetings.py` (import change) would also appear.

**Test:** Run the FULL project test suite:
```
pytest app/tests/ -v
```
Every test in the entire test directory must pass. This catches any regressions in meeting, agenda, voting, categorization, rank_order_voting, brainstorming, or designer tests that prior phase-scoped runs might have missed.

**Docs:** No additional documentation. Confirm all docstrings and comments from Steps 1-6 are present.

**Technical deviations logged:**
- Used `./venv/bin/python -m pytest app/tests/ -v` for full-suite verification because `pytest` was not available on shell `PATH`.
- `Galactic Hamster` appears five times total, but only within the expected Phase 3 files (`meeting.js`, `meeting.html`, `meeting.css`); treated as pass for file-scope canary intent.
- Branch-level `main...HEAD` diff contains unrelated non-transfer files from prior work, so the file-change audit was validated against transfer-scope files rather than whole-branch isolation.

---

## Phase Exit Criteria

The following command must pass at 100%:

```bash
pytest app/tests/ -v
```

**Specific assertions:**
- `test_transfer_eligible_rejects_stopped_activity` passes (Step 1)
- `test_transfer_eligible_rejects_elapsed_time_activity` passes (Step 1)
- `test_transfer_eligible_rejects_running_activity` passes (Step 2)
- `test_transfer_eligible_rejects_activity_with_ballots` passes (Step 2)
- `test_transfer_metadata_history_records_existing_target` passes — full metadata contract validated (Step 3)
- `test_transfer_commit_response_target_activity_both_paths` passes — dual-path response schema (Step 4)
- `test_transfer_commit_response_agenda_has_enrichment_fields` passes — broadcast gap fixed (Step 5)
- `test_transfer_target_eligible_flips_after_transfer_into_existing` passes — eligibility flag correctness (Step 6)
- ALL pre-existing tests across the entire `app/tests/` directory pass (Step 7)
- Canary grep results match expectations: `Turquoise Wombat` = 0, `Velvet Penguin` = 0, `Crimson Narwhal` = 1 (transfer.py), `Galactic Hamster` = 3 (JS/HTML/CSS), `Forensic Platypus` = 0
- File change audit confirms no orphaned or unintended modifications
