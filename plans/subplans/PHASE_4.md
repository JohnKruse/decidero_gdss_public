# Phase 4 — Structural Validation [COMPLETE]

**Phase Canary**: Iron Thistle

**Parent**: `plans/01_MASTER_PLAN.md` (Cobalt Fennel)

**Objective**: Add validator checks to `validate_agenda()` that enforce the structural invariants currently expressed only as prompt instructions. Catch three classes of structural defect at validation time — single-activity tracks, dangling phase/track references, and missing reconvergence phases — rather than relying on prompt compliance alone. These checks produce errors (not warnings), causing the retry loop to fire a correction prompt when the AI generates a structurally invalid multi-track agenda.

---

## Files Modified

| File | Functions/Sections |
|------|-------------------|
| `app/services/agenda_validator.py` | `validate_agenda()` (lines 343–367), new helper `_validate_structural_invariants()` |
| `app/tests/test_generation_pipeline.py` | New test functions (7 tests) |

---

## Step 1: Extract phase/track declarations from the agenda payload [DONE]

**Implement**: In `app/services/agenda_validator.py`, create a new private helper function `_extract_phase_track_maps()` that takes the full agenda payload and returns three data structures needed by subsequent validation steps:

1. `declared_phases`: a `Dict[str, Dict[str, Any]]` mapping each `phase_id` to its phase dict (from the top-level `phases` array). If `phases` is absent or empty, return an empty dict.
2. `declared_tracks`: a `Dict[str, str]` mapping each `track_id` to its parent `phase_id`, derived by iterating `phases` and each phase's `tracks` array. If a phase has no `tracks` key, skip it.
3. `parallel_phase_ids`: a `Set[str]` containing the `phase_id` of every phase where `phase_type == "parallel"`.

This helper performs no validation itself — it is a pure extraction utility that simplifies the validation steps that follow.

Handle edge cases:
- `phases` key missing → all three structures are empty.
- `phases` is not a list → all three structures are empty.
- A phase dict missing `phase_id` → skip that entry.
- A track dict missing `track_id` → skip that entry.

**Test**: Add `test_extract_phase_track_maps_basic()` to `app/tests/test_generation_pipeline.py`. Build a minimal agenda payload with 3 phases (plenary → parallel with 2 tracks → plenary) and call `_extract_phase_track_maps()`. Assert:
- `declared_phases` has 3 entries keyed by `phase_id`.
- `declared_tracks` has 2 entries, both mapping to the parallel phase's `phase_id`.
- `parallel_phase_ids` contains exactly the parallel phase's `phase_id`.
- Also test with an empty `phases` array and assert all three structures are empty.

**Docstring**: Add docstring to `_extract_phase_track_maps()`: `"Extract declared phases, tracks, and parallel phase IDs from an agenda payload. Returns (declared_phases, declared_tracks, parallel_phase_ids). Handles missing or malformed phases gracefully by returning empty structures."`

**Technical deviations**: None.

---

## Step 2: Validate dangling phase_id references on agenda activities [DONE]

**Implement**: In `app/services/agenda_validator.py`, create a new private helper function `_check_dangling_phase_refs()` that takes the agenda activity list, the `declared_phases` dict from Step 1, and an errors list. For each activity that has a non-null `phase_id` value:

- If the `phase_id` is not present in `declared_phases`, append an error: `"Activity {idx} ('{title}'): phase_id '{phase_id}' is not declared in the phases array."`.

Skip activities where `phase_id` is null or absent (valid for simple-complexity agendas that have no phases).

This check catches the case where the AI hallucinates a phase_id (e.g., `"phase_3"`) that doesn't exist in the `phases` array — a structural inconsistency that would cause frontend rendering failures.

**Test**: Add `test_validate_agenda_dangling_phase_id()` to `app/tests/test_generation_pipeline.py`. Build an agenda with:
- `phases`: `[{phase_id: "phase_1", ...}]`
- `agenda`: 2 activities, one with `phase_id: "phase_1"` (valid), one with `phase_id: "phase_99"` (dangling).
Call `validate_agenda()` and assert:
- `result.valid` is `False`.
- Exactly one error mentioning `"phase_99"` and `"not declared"`.
- Also test with all valid `phase_id` references → `result.valid` is `True` (no structural errors).

**Docstring**: Add docstring to `_check_dangling_phase_refs()`: `"Append errors for any agenda activity whose phase_id is not declared in the phases array. Skips activities with null or absent phase_id."`

**Technical deviations**: Added a minimal `_validate_structural_invariants()` scaffold and `validate_agenda()` hook in this step (ahead of Step 6) so the new dangling phase_id check is executable through the public validation path without test-only wiring.

---

## Step 3: Validate dangling track_id references on agenda activities [DONE]

**Implement**: In `app/services/agenda_validator.py`, create a new private helper function `_check_dangling_track_refs()` that takes the agenda activity list, the `declared_tracks` dict from Step 1, and an errors list. For each activity that has a non-null `track_id` value:

- If the `track_id` is not present in `declared_tracks`, append an error: `"Activity {idx} ('{title}'): track_id '{track_id}' is not declared in any phase's tracks array."`.

Skip activities where `track_id` is null or absent (valid for plenary activities).

This check catches the case where an activity references a `track_id` like `"track_3c"` that no phase declares — another structural inconsistency that breaks the hierarchical rendering.

**Test**: Add `test_validate_agenda_dangling_track_id()` to `app/tests/test_generation_pipeline.py`. Build an agenda with:
- `phases`: one parallel phase declaring `tracks: [{track_id: "track_2a", ...}]`.
- `agenda`: 3 activities — one plenary (track_id null), one with `track_id: "track_2a"` (valid), one with `track_id: "track_GHOST"` (dangling).
Call `validate_agenda()` and assert:
- `result.valid` is `False`.
- Exactly one error mentioning `"track_GHOST"` and `"not declared"`.
- Also test with all valid references → no structural errors.

**Docstring**: Add docstring to `_check_dangling_track_refs()`: `"Append errors for any agenda activity whose track_id is not declared in any phase's tracks array. Skips activities with null or absent track_id."`

**Technical deviations**: Reused the Step 2 structural-orchestrator scaffold and extended it to run `_check_dangling_track_refs()` in this step (ahead of full Step 6 wiring).

---

## Step 4: Validate minimum activity count per parallel-phase track [DONE]

**Implement**: In `app/services/agenda_validator.py`, create a new private helper function `_check_min_activities_per_track()` that takes the agenda activity list, the `declared_tracks` dict, the `parallel_phase_ids` set, and an errors list.

1. Build a counter: for each `track_id` in `declared_tracks`, count how many agenda activities reference that `track_id`.
2. For each declared track with fewer than 2 activities, append an error: `"Track '{track_id}' in parallel phase '{phase_id}' has {n} activity but requires at least 2."`.

This enforces the hard invariant that every breakout track must have a multi-activity sequence. A single-activity track produces divergent output with no convergence, making the track's deliverable undefined.

**Test**: Add `test_validate_agenda_single_activity_track()` to `app/tests/test_generation_pipeline.py`. Build an agenda with:
- 1 parallel phase with 2 tracks (`track_2a`, `track_2b`).
- `track_2a` has 3 activities (brainstorming → categorization → voting).
- `track_2b` has only 1 activity (brainstorming).
Call `validate_agenda()` and assert:
- `result.valid` is `False`.
- Error message mentions `"track_2b"` and `"requires at least 2"`.
- Also test with both tracks having 2+ activities → no structural errors.

**Docstring**: Add docstring to `_check_min_activities_per_track()`: `"Append errors for any declared track in a parallel phase that has fewer than 2 agenda activities. Enforces the multi-activity-per-track invariant."`

**Technical deviations**: Updated the Step 3 dangling-track test fixture to keep declared track activity counts at 2+ so that test remains isolated to undeclared `track_id` behavior after Step 4 adds minimum-count enforcement.

---

## Step 5: Validate parallel phase reconvergence requirement [DONE]

**Implement**: In `app/services/agenda_validator.py`, create a new private helper function `_check_reconvergence()` that takes the full `phases` list and an errors list.

1. Iterate the phases array in order by index.
2. For each phase where `phase_type == "parallel"`, check whether the immediately next phase (index + 1) exists and has `phase_type == "plenary"`.
3. If the parallel phase is the last in the array (no next phase), append an error: `"Parallel phase '{phase_id}' ('{title}') is the last phase but must be followed by a plenary reconvergence phase."`.
4. If the next phase exists but is also `"parallel"`, append an error: `"Parallel phase '{phase_id}' ('{title}') is followed by another parallel phase ('{next_phase_id}') but must be followed by a plenary reconvergence phase."`.

This enforces the structural rule that breakout work must always reconverge before the session continues.

**Test**: Add `test_validate_agenda_missing_reconvergence()` to `app/tests/test_generation_pipeline.py`. Test three cases:
- (a) Valid: plenary → parallel → plenary → result passes.
- (b) Invalid: plenary → parallel (last phase) → error about missing reconvergence.
- (c) Invalid: parallel → parallel → plenary → error about first parallel not followed by plenary.

**Docstring**: Add docstring to `_check_reconvergence()`: `"Append errors for any parallel phase not immediately followed by a plenary phase. Enforces the reconvergence invariant."`

**Technical deviations**: Updated Step 3/Step 4 test fixtures to include a trailing plenary phase so their "valid" branches remain isolated to dangling-reference and minimum-track-count checks after reconvergence enforcement was introduced.

---

## Step 6: Wire structural checks into validate_agenda() [DONE]

**Implement**: In `app/services/agenda_validator.py`, modify `validate_agenda()` (lines 343–367). After the existing `_validate_activity_payload()` call, add a call to a new orchestrating function `_validate_structural_invariants()` that runs all four structural checks in sequence:

```python
def validate_agenda(agenda_data: Dict[str, Any]) -> AgendaValidationResult:
    result = _validate_activity_payload(...)

    # Run structural checks only on payloads that passed basic validation
    # and declare phases (simple agendas skip structural checks).
    structural_errors = _validate_structural_invariants(agenda_data)
    if structural_errors:
        result.errors.extend(structural_errors)
        result.valid = False

    return result
```

`_validate_structural_invariants()` calls:
1. `_extract_phase_track_maps()` — if the result is all-empty, return immediately (no phases to validate).
2. `_check_dangling_phase_refs()` on the agenda activities.
3. `_check_dangling_track_refs()` on the agenda activities.
4. `_check_min_activities_per_track()` for each parallel-phase track.
5. `_check_reconvergence()` on the phases list.

Return the collected errors list.

**Test**: Add `test_validate_agenda_structural_checks_wired()` to `app/tests/test_generation_pipeline.py`. Build a well-formed multi-track agenda (plenary → parallel with 2 tracks × 3 activities each → plenary reconvergence) and call `validate_agenda()`. Assert `result.valid` is `True` and `result.errors` is empty. This confirms the structural checks are wired in and don't produce false positives on valid agendas.

**Docstring**: Update `validate_agenda()` docstring to: `"Validate the raw dict returned by parse_agenda_json(). Performs per-activity field validation (tool_type, title, instructions, duration, config_overrides) and structural invariant checks (dangling phase_id/track_id references, minimum 2 activities per parallel-phase track, parallel-phase reconvergence requirement). Errors block validation success; warnings are informational."`

**Technical deviations**: Structural wiring was introduced incrementally in Steps 2–5; this step formalized it by adding the dedicated `test_validate_agenda_structural_checks_wired()` coverage and updating the `validate_agenda()` docstring to the final spec. The test fixture used `voting` for reconvergence (instead of non-registered `presentation`) to align with the live activity registry.

---

## Step 7: Regression — Verify all existing tests still pass [DONE]

**Implement**: No code changes. Run the full existing test suite to confirm the new structural checks do not break existing tests. The structural checks only activate when the `phases` array is present and non-empty, so all existing test agendas (which either have no phases or have well-formed phases) will continue to pass. Simple-complexity agendas with no `phases` key skip structural validation entirely.

**Test**: Execute:
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
venv/bin/python -m pytest app/tests/test_config_loader.py -q -k meeting_designer
```
All must pass.

**Docstring**: No changes needed.

---

## Phase Exit Criteria

**New tests** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q -k "phase_track_maps or dangling_phase_id or dangling_track_id or single_activity_track or missing_reconvergence or structural_checks_wired" --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 7 passed
1. `test_extract_phase_track_maps_basic`
2. `test_validate_agenda_dangling_phase_id`
3. `test_validate_agenda_dangling_track_id`
4. `test_validate_agenda_single_activity_track`
5. `test_validate_agenda_missing_reconvergence`
6. `test_validate_agenda_structural_checks_wired`
7. Regression (all existing tests pass)

**Full regression** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py app/tests/test_config_loader.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 117+ passed (94 existing + 5 Phase 1 + 5 Phase 2 + 6 Phase 3 + 7 Phase 4)
