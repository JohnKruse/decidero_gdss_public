# Phase 1 — Schema & Eligibility Foundation [COMPLETE]

**Parent:** `plans/01_MASTER_PLAN.md`
**Global Canary:** `Turquoise Wombat`
**Phase Canary:** `Velvet Penguin`

---

## Step 1: [DONE] Extend `TransferTargetActivity` Schema

**File:** `app/schemas/transfer.py` (lines 28-32)

**Implement:**
- Add `activity_id: Optional[str] = None` to `TransferTargetActivity`.
- Change `tool_type` from `str` (required) to `Optional[str] = None`.
- Add a Pydantic `model_validator(mode="after")` that enforces: at least one of `activity_id` or `tool_type` must be provided. If neither is set, raise `ValueError("Either tool_type or activity_id must be provided")`.

**Test:** Add tests to `app/tests/test_transfer_api.py`:
- `test_transfer_target_schema_accepts_tool_type_only` — instantiate `TransferTargetActivity(tool_type="voting")`, assert valid.
- `test_transfer_target_schema_accepts_activity_id_only` — instantiate `TransferTargetActivity(activity_id="VO-0003")`, assert valid.
- `test_transfer_target_schema_accepts_both` — instantiate with both fields, assert valid.
- `test_transfer_target_schema_rejects_neither` — instantiate with neither, assert `ValidationError`.

**Docs:** Update the docstring on `TransferTargetActivity` to describe the two modes: new-activity (tool_type required) vs. existing-activity (activity_id required, tool_type derived from target).

---

## Step 2: [DONE] Extend `TransferCommit` Response Contract

**File:** `app/schemas/transfer.py` (lines 35-40)

**Implement:**
- No change to `TransferCommit` request schema itself (the `target_activity: TransferTargetActivity` field already carries the new `activity_id`).
- Create a new Pydantic response model `TransferCommitResponse` in the same file:
  ```
  class TransferCommitResponse(BaseModel):
      target_activity: Dict[str, Any]
      new_activity: Optional[Dict[str, Any]] = None  # backward compat alias
      agenda: List[Dict[str, Any]]
      input_bundle_id: str
  ```
- The `target_activity` field replaces the current `new_activity` as the canonical key. `new_activity` is retained as a backward-compatible alias (set to the same value when a new activity is created; set to `None` when transferring into an existing activity).

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_transfer_commit_response_contains_target_activity` — perform an existing "create new" transfer commit (any existing test pattern), assert the response dict contains both `target_activity` and `new_activity` keys, and that they are equal.

**Docs:** Add docstring to `TransferCommitResponse` explaining the dual-key contract and backward compatibility.

**Technical Deviations Logged:**
- To keep the Step 2 response contract test executable, `commit_transfer` now returns both `target_activity` and `new_activity` in this phase. This behavior was originally called out again in Step 5, so Step 5 will be reduced to compatibility assertion updates/refinement rather than first introduction of the key.

---

## Step 3: [DONE] Build the `_assert_transfer_eligible` Helper

**File:** `app/routers/transfer.py` (new function, place after `_ensure_not_running` at ~line 249)

**Implement:**
Create `async def _assert_transfer_eligible(target: AgendaActivity, donor_activity_id: str, meeting_id: str, meeting_manager: MeetingManager) -> None` that raises `HTTPException` when the target activity is ineligible. Checks, in order:

1. **Not the donor:** `target.activity_id == donor_activity_id` → 422, `"Cannot transfer into the donor activity itself."`
2. **Never started:** `target.started_at is not None` → 422, `"Target activity has already been started."`
3. **Never stopped:** `target.stopped_at is not None` → 422, `"Target activity has already been stopped."`
4. **No elapsed time:** `(target.elapsed_duration or 0) > 0` → 422, `"Target activity has accumulated run time."`
5. **No user data:** `meeting_manager.get_activity_data_flags(meeting_id).get(target.activity_id)` → 422, `"Target activity already has participant data."`
6. **Not running:** call `await _ensure_not_running(meeting_id, target.activity_id)` (reuse existing helper; it raises 409 on its own).

Each check produces a clear, distinct error detail string so tests can assert on the message.

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_transfer_eligible_rejects_self_transfer` — create a meeting with one brainstorming activity, submit an idea, stop it. Attempt commit with `donor_activity_id` == `target_activity.activity_id`. Assert 422 with "donor activity itself".
- `test_transfer_eligible_rejects_started_activity` — create a meeting with a brainstorming donor (with ideas) and a voting target. Set `started_at` on the target via ORM. Attempt commit with `activity_id` pointing to the target. Assert 422 with "already been started".
- `test_transfer_eligible_rejects_activity_with_data` — create a meeting with a brainstorming donor and a voting target. Add a `VotingVote` row to the target. Attempt commit. Assert 422 with "participant data".

These tests call the commit endpoint; the eligibility helper is exercised through the endpoint, not tested in isolation. This keeps the test pattern consistent with the rest of `test_transfer_api.py`.

**Docs:** Add a docstring to `_assert_transfer_eligible` listing all six checks and their HTTP status codes.

**Technical Deviations Logged:**
- To exercise Step 3 tests through the `/transfer/commit` endpoint (as specified), the endpoint now invokes `_assert_transfer_eligible` when `target_activity.activity_id` is provided.
- The explicit `501` placeholder for eligible existing-target commits is still deferred to Step 4 as planned.

---

## Step 4: [DONE] Wire Eligibility Into `commit_transfer` (Guard Only)

**File:** `app/routers/transfer.py` (within `commit_transfer`, ~lines 452-467)

**Implement:**
After the existing donor validation block (line 445) and before the target resolution block (line 452), add a conditional guard:

```python
if target.activity_id:
    existing_target = _resolve_activity(meeting, target.activity_id)
    await _assert_transfer_eligible(
        existing_target, payload.donor_activity_id, meeting_id, meeting_manager
    )
    # Phase 2 will add the existing-activity commit path here.
    # For now, fall through to raise NotImplementedError so tests can
    # verify eligibility without accidentally creating duplicate activities.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Transfer into existing activity is not yet implemented.",
    )
```

This placement means eligibility is checked BEFORE any config mapping or activity creation. The 501 is a temporary sentinel — Phase 2 replaces it with the real logic.

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_transfer_commit_into_existing_returns_501_placeholder` — create a meeting with a brainstorming donor (with ideas, stopped) and a virgin voting target. Commit with `target_activity: {"activity_id": "<voting_id>"}`. Assert 501 with "not yet implemented". This confirms the wiring is correct and eligibility passed.

**Docs:** Add an inline comment at the 501 line: `# Velvet Penguin: Phase 1 placeholder — replaced in Phase 2`.

**Technical Deviations Logged:**
- Step 3 had already introduced the eligibility helper invocation in `commit_transfer`; Step 4 completed the planned guard behavior by adding the explicit `501` placeholder branch and regression test.

---

## Step 5: [DONE] Adopt `TransferCommitResponse` in the Existing Create Path

**File:** `app/routers/transfer.py` (lines 741-749)

**Implement:**
Replace the raw dict return at the end of `commit_transfer` with:

```python
response = {
    "target_activity": AgendaActivityResponse.model_validate(created).model_dump(),
    "new_activity": AgendaActivityResponse.model_validate(created).model_dump(),
    "agenda": [
        AgendaActivityResponse.model_validate(item).model_dump()
        for item in agenda_items
    ],
    "input_bundle_id": input_bundle.bundle_id,
}
return response
```

This adds the `target_activity` key alongside the existing `new_activity` key so the frontend can begin consuming `target_activity` without breaking on the current `new_activity` key.

Add the import for `TransferCommitResponse` if using it for response_model typing (optional — the dict return is sufficient and avoids serialization surprises with the dynamic agenda items).

**Test:** Update existing test assertions in `app/tests/test_transfer_api.py` that check `commit_resp.json()["new_activity"]` to **also** assert `commit_resp.json()["target_activity"]` is present and equal to `new_activity`. Specifically, add a parallel assertion in `test_transfer_commit_copies_config_and_ideas` and `test_transfer_draft_and_commit_preserve_item_metadata`. Do NOT remove the existing `new_activity` assertions — backward compat.

**Docs:** Add inline comment above the response dict: `# target_activity is the canonical key; new_activity retained for backward compatibility`.

**Technical Deviations Logged:**
- Core Step 5 behavior (returning both `target_activity` and `new_activity`) was introduced earlier in Step 2 to satisfy the response-contract test at that stage.
- This step finalized the intended compatibility contract by adding the explicit inline comment and the required equality assertions in:
  - `test_transfer_commit_copies_config_and_ideas`
  - `test_transfer_draft_and_commit_preserve_item_metadata`

---

## Step 6: [DONE] Add `AgendaActivityResponse` Eligibility Signal

**File:** `app/schemas/meeting.py` (line 185, `AgendaActivityResponse`)

**Implement:**
- Add `transfer_target_eligible: bool = False` to `AgendaActivityResponse`.
- In `app/routers/meetings.py`, within `_apply_transfer_counts()` (~line 464), after computing `has_data` / `has_votes` / `has_submitted_ballots`, compute and set `transfer_target_eligible` for each activity:
  ```python
  item.transfer_target_eligible = (
      item.started_at is None
      and item.stopped_at is None
      and (item.elapsed_duration or 0) == 0
      and not data_flags.get(item.activity_id, False)
  )
  ```
  (The "not running" and "not donor" checks are context-dependent and handled at commit time, not in the agenda listing.)

This gives the frontend everything it needs to gray out ineligible activities in Phase 3 without an extra API call.

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_agenda_includes_transfer_target_eligible_flag` — create a meeting with two activities: one brainstorming (submit ideas, stop it) and one virgin voting. Fetch `GET /api/meetings/{id}/agenda`. Assert the brainstorming activity has `transfer_target_eligible: false` (it has data) and the voting activity has `transfer_target_eligible: true`.

**Docs:** Add field description to `AgendaActivityResponse`: `transfer_target_eligible: Whether this activity can receive transferred ideas (never started, no user data).`

**Technical Deviations Logged:**
- The eligibility flag is computed in `_apply_activity_lock_metadata()` (where `has_data`/`has_votes` are already derived) rather than `_apply_transfer_counts()`. This keeps related per-activity lock/eligibility metadata in one pass.

---

## Step 7: [DONE] Phase Canary Verification & Regression Sweep

**No new files.** This step is a verification gate.

**Implement:**
- Grep the codebase for `Velvet Penguin` to confirm it appears only in the expected locations (the 501 placeholder comment in `transfer.py`).
- Grep for `Turquoise Wombat` to confirm it does not appear in source code (it belongs only in plan docs).

**Test:** Run the full existing test suite to confirm no regressions:
```
pytest app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_transfer_comment_format_parity.py -v
```
All pre-existing tests must pass alongside the new Phase 1 tests.

**Docs:** No additional documentation. Confirm that all docstrings added in Steps 1-6 are present.

**Technical Deviations Logged:**
- Canary verification was executed against source/test paths (`app`, `app/tests`, `docs`, `scripts`) to avoid plan-doc matches; `Velvet Penguin` appears only in `app/routers/transfer.py`, and `Turquoise Wombat` appears in no source files.

---

## Phase Exit Criteria

The following command must pass at 100%:

```bash
pytest app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_transfer_comment_format_parity.py -v
```

**Specific assertions:**
- All new `test_transfer_target_schema_*` tests pass (Step 1)
- `test_transfer_commit_response_contains_target_activity` passes (Step 2)
- All `test_transfer_eligible_rejects_*` tests pass (Step 3)
- `test_transfer_commit_into_existing_returns_501_placeholder` passes (Step 4)
- Existing commit tests now also assert `target_activity` key (Step 5)
- `test_agenda_includes_transfer_target_eligible_flag` passes (Step 6)
- All pre-existing transfer tests pass without modification to their core assertions (Step 7)
- `Velvet Penguin` canary appears only in the Phase 1 placeholder comment
