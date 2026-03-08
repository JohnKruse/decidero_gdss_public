# Phase 6 — Integration Verification [COMPLETE]

**Phase Canary**: Tungsten Yarrow

**Parent**: `plans/01_MASTER_PLAN.md` (Cobalt Fennel)

**Objective**: End-to-end validation of the full pipeline (conversation → outline → generation → validation → report rendering) with real multi-track generation scenarios. Confirm that Phases 1–5 work together: structurally sound multi-track agendas emerge with context-appropriate within-track workflows, the validator catches intentionally malformed test cases, and the report script renders the hierarchical tree correctly. No new production logic is introduced — this phase is purely verification and test-hardening.

---

## Files Modified

| File | Functions/Sections |
|------|-------------------|
| `app/tests/test_generation_pipeline.py` | New test functions (6 tests) |
| `scripts/meeting_designer_report.py` | `_outline_lines()` — docstring update only |
| `app/services/agenda_validator.py` | `validate_agenda()` — docstring update only |
| `app/services/meeting_designer_prompt.py` | `build_generation_prompt()` — docstring update only |

---

## Step 1: Build a multi-track agenda fixture and verify pipeline acceptance [DONE]

**Implement**: In `app/tests/test_generation_pipeline.py`, create a new helper function `_valid_multitrack_agenda_json()` that returns a JSON string representing a well-formed multi-track agenda modeled after the Colorado River scenario. The payload must contain:

1. `meeting_summary`, `session_name`, `complexity: "multi-track"`, `evaluation_criteria`, `design_rationale`.
2. `phases`: three phases in order — plenary opener (`phase_type: "plenary"`), parallel breakout (`phase_type: "parallel"` with 2 tracks, each containing `track_id`, `label`, `participant_subset`), plenary reconvergence (`phase_type: "plenary"`).
3. `agenda`: 7+ activities — 1 plenary opener activity (referencing the plenary phase), 3 activities for track A (brainstorming → categorization → voting), 2 activities for track B (brainstorming → rank_order_voting), and 1 plenary reconvergence activity. Each activity must have valid `tool_type`, `title`, `instructions` (non-empty), `duration_minutes`, `collaboration_pattern`, `rationale`, `config_overrides`, and correct `phase_id` / `track_id` references.

Every `tool_type` must be drawn from the live plugin registry. Use `get_enriched_activity_catalog()` in the helper (or hardcode types known from the registry: `brainstorming`, `categorization`, `voting`, `rank_order_voting`, `presentation`).

Add test `test_e2e_multitrack_pipeline_accepted()`: call `validate_agenda()` on the parsed payload. Assert `result.valid is True` and `result.errors == []`. This confirms the validator accepts a well-formed multi-track agenda end-to-end.

**Test**: `test_e2e_multitrack_pipeline_accepted` — assertions described above.

**Docstring**: Add a docstring to `_valid_multitrack_agenda_json()`: `"Build a valid multi-track agenda JSON string modeling a Colorado River–style scenario with plenary → parallel (2 tracks, 2–3 activities each) → plenary reconvergence."`

**Technical deviations**: Used a live-catalog assertion for required tool types (`brainstorming`, `categorization`, `voting`, `rank_order_voting`) and set plenary reconvergence activity `tool_type` to `voting` (registry-safe) instead of `presentation` to avoid environment-specific plugin assumptions. Ran focused test plus full-suite `venv/bin/python -m pytest -q` to satisfy thread-level verification.

---

## Step 2: Validate the structural checks catch intentionally malformed multi-track agendas [DONE]

**Implement**: In `app/tests/test_generation_pipeline.py`, add test `test_e2e_multitrack_structural_defects_caught()`. Start from the valid payload produced by `_valid_multitrack_agenda_json()` (parsed to dict), then create three mutated copies, each introducing exactly one structural defect:

1. **Single-activity track**: Remove all but one activity from track B (leaving only 1 activity for `track_2a`). Call `validate_agenda()` → assert `result.valid is False` and at least one error message contains `"requires at least 2"`.
2. **Dangling phase reference**: Change one activity's `phase_id` to `"phase_GHOST"`. Call `validate_agenda()` → assert `result.valid is False` and at least one error message contains `"not declared"` and `"phase_GHOST"`.
3. **Missing reconvergence**: Remove the final plenary phase from the `phases` array so the parallel phase is last. Call `validate_agenda()` → assert `result.valid is False` and at least one error message contains `"reconvergence"`.

Each mutation is tested independently — parse the original, mutate, validate, assert.

**Test**: `test_e2e_multitrack_structural_defects_caught` — three sub-assertions within a single test function.

**Docstring**: Add inline comments explaining each mutation. No new function docstrings needed since the test name is self-documenting.

**Technical deviations**: Kept all three defects in one test function as specified, but used JSON round-trip cloning (`json.loads(json.dumps(...))`) for deterministic deep copies without adding new imports.

---

## Step 3: Verify the report script renders multi-track tree structure correctly [DONE]

**Implement**: In `app/tests/test_generation_pipeline.py`, add test `test_report_outline_lines_multitrack()`. Import `_outline_lines` from `scripts.meeting_designer_report` (adjust sys.path if needed, or use a relative import). Build the multi-track payload from `_valid_multitrack_agenda_json()` (parsed to dict) and call `_outline_lines(payload)`. Assert:

1. The rendered lines contain `"Agenda tree (phase -> track -> activity):"` — confirming the hierarchical rendering path was taken (not the flat list path).
2. At least one line contains `"Phase 1:"` and at least one line contains `"Phase 2:"` and `"Phase 3:"` — all three phases rendered.
3. At least one line contains `"Track:"` — confirming track headers were rendered.
4. No line contains `"(no activities listed for this track)"` — confirming activities were matched to their tracks.
5. No line contains `"Unassigned/unknown track activities:"` — confirming no orphaned activities.
6. The total number of activity lines (lines containing `"Activity "` or lines matching the `_activity_lines` format with the activity index e.g. `"1."`) is ≥ 7.

**Test**: `test_report_outline_lines_multitrack` — assertions described above.

**Docstring**: Update `_outline_lines()` docstring in `scripts/meeting_designer_report.py` to: `"Render a human-readable outline from an agenda payload. Produces a hierarchical tree (phase → track → activity) for multi-phase agendas with parallel tracks, or a flat activity list for simple agendas. Returns a list of formatted strings."`

**Technical deviations**: Imported `_outline_lines` directly via `from scripts.meeting_designer_report import _outline_lines` without `sys.path` adjustments (package import already resolves in the test environment). Activity-line count assertion was implemented by matching the report's concrete `- N. [tool]` line format rather than looking for literal `"Activity "` text.

---

## Step 4: Verify the two-stage pipeline produces a multi-track agenda end-to-end [DONE]

**Implement**: In `app/tests/test_generation_pipeline.py`, add test `test_e2e_multitrack_two_stage_pipeline()`. This test runs the full two-stage pipeline (outline → generation) with mocked LLM responses that return multi-track payloads.

1. Create a valid multi-track outline JSON (using `_valid_multitrack_agenda_json()` with only `tool_type`, `title`, `collaboration_pattern`, and `rationale` per activity — matching outline schema).
2. Create the full multi-track agenda JSON (from `_valid_multitrack_agenda_json()`).
3. Use `_mock_chat_complete_two_stage(outline_json, agenda_json)` to mock the LLM.
4. Call `generate_agenda()` with standard test parameters.
5. Assert: `response["agenda"]` has ≥ 7 items, `response["phases"]` has 3 items, `response["_pipeline_meta"]["outline_attempts"]` == 1, and `response["_pipeline_meta"]["agenda_attempts"]` == 1.

**Test**: `test_e2e_multitrack_two_stage_pipeline` — assertions described above.

**Docstring**: No new function docstrings needed. Add an inline comment: `# Phase 6: end-to-end multi-track pipeline smoke test`.

**Technical deviations**: Added a small helper `_valid_multitrack_outline_json()` to derive Stage 1 output from the validated multi-track agenda fixture while keeping outline activities constrained to `tool_type`, `title`, `collaboration_pattern`, and `rationale`. Executed this as an endpoint-level test via `authenticated_client.post("/api/meeting-designer/generate-agenda")` (which exercises `generate_agenda()` directly) instead of calling the route function manually with dependency objects.

---

## Step 5: Verify per-track activity count and pattern appropriateness [DONE]

**Implement**: In `app/tests/test_generation_pipeline.py`, add test `test_e2e_multitrack_per_track_activity_counts()`. Parse the multi-track agenda from `_valid_multitrack_agenda_json()`. For each track declared in the `phases` array:

1. Count the number of activities in the `agenda` array whose `track_id` matches this track. Assert count ≥ 2 for every track.
2. Assert no track has a single-activity sequence. This is a higher-level semantic check (complementing Phase 4's validator check) that confirms the fixture itself models the desired behavior.
3. For track A (3 activities): assert the `tool_type` sequence is `["brainstorming", "categorization", "voting"]` — a structured convergence pattern.
4. For track B (2 activities): assert the `tool_type` sequence is `["brainstorming", "rank_order_voting"]` — a quick convergence pattern.

This test verifies that the fixture embodies context-appropriate within-track workflow patterns as described in the master plan success gate.

**Test**: `test_e2e_multitrack_per_track_activity_counts` — assertions described above.

**Docstring**: No new function docstrings needed. Add an inline comment: `# Phase 6: verify context-appropriate workflow patterns per track`.

**Technical deviations**: Implemented track counting by deriving declared track IDs from the phase `tracks` arrays and mapping `agenda` activities into `track_id -> [tool_type]` lists, then asserting count and sequence invariants. This preserves deterministic sequence checks while avoiding duplicate fixture declarations in the test.

---

## Step 6: Final regression and docstring updates [DONE]

**Implement**: No new test logic. Update docstrings on the following functions to reflect the completed Phases 1–6 integration:

1. `validate_agenda()` in `app/services/agenda_validator.py` — append to the existing docstring: `"Phase 6 integration tests confirm this function correctly accepts well-formed multi-track agendas and rejects structurally defective ones (single-activity tracks, dangling references, missing reconvergence)."`
2. `build_generation_prompt()` in `app/services/meeting_designer_prompt.py` — append to the existing docstring: `"Integration-verified in Phase 6 with multi-track generation scenarios."`

Run the full regression suite to confirm all Phases 1–6 tests pass together and no existing tests broke.

**Test**: Execute:
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
venv/bin/python -m pytest app/tests/test_config_loader.py -q -k meeting_designer
```
All must pass.

**Docstring**: This step IS the docstring update (described above).

**Technical deviations**: In addition to the two required regression commands, executed full-suite `venv/bin/python -m pytest -q` to satisfy the thread-level verification gate. Docstring text was appended as wrapped lines within existing docstrings for style consistency; semantic content matches Step 6 requirements.

---

## Phase Exit Criteria

**New tests** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q -k "multitrack_pipeline_accepted or multitrack_structural_defects or report_outline_lines_multitrack or multitrack_two_stage_pipeline or multitrack_per_track_activity_counts" --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 5 passed
1. `test_e2e_multitrack_pipeline_accepted`
2. `test_e2e_multitrack_structural_defects_caught`
3. `test_report_outline_lines_multitrack`
4. `test_e2e_multitrack_two_stage_pipeline`
5. `test_e2e_multitrack_per_track_activity_counts`

**Full regression** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py app/tests/test_config_loader.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 127+ passed (94 existing + 5 Phase 1 + 5 Phase 2 + 6 Phase 3 + 7 Phase 4 + 5 Phase 5 + 5 Phase 6)
