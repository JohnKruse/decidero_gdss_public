# Phase 3 — Outline Track Awareness [COMPLETE]

**Phase Canary**: Amber Compass

**Parent**: `plans/01_MASTER_PLAN.md` (Cobalt Fennel)

**Objective**: Make Stage 1 (outline generation) produce multi-activity track sequences informed by the conversation context. Add optional `track_hint` metadata to the outline JSON schema so Stage 1 can explicitly label which track each activity belongs to and what pattern it follows. Update the Stage 1 → Stage 2 handoff so Stage 2 receives track groupings rather than a flat numbered list, eliminating the need for Stage 2 to re-infer track structure.

---

## Files Modified

| File | Functions/Sections |
|------|-------------------|
| `app/services/meeting_designer_prompt.py` | `build_outline_prompt()` (lines 332–377), `build_generation_prompt()` outline rendering (lines 225–240) |
| `app/services/agenda_validator.py` | `validate_outline()` (lines 370–392) |
| `app/tests/test_generation_pipeline.py` | New test functions (6 tests) |

---

## Step 1: Extend the outline JSON schema with optional track metadata [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, modify `build_outline_prompt()` to extend the outline JSON schema with two new optional structures:

1. A top-level `tracks` array (present only when the conversation discussed breakout groups):
```json
"tracks": [
  {"track_id": "track_a", "label": "Descriptive track name", "goal": "What this track must produce"}
]
```

2. An optional `track_id` field on each outline activity item (null for plenary activities):
```json
{
  "tool_type": "brainstorming",
  "title": "Generate Budget Ideas",
  "duration_minutes": 20,
  "collaboration_pattern": "Generate",
  "rationale": "...",
  "track_id": "track_a"
}
```

Update the schema example in the prompt string (lines 357–367) to show both the `tracks` array and the `track_id` field. Add a comment in the prompt clarifying: "Include the tracks array and track_id fields only when the conversation discussed breakout groups or parallel tracks. For simple or multi_phase meetings, omit tracks and set track_id to null."

**Test**: Add `test_outline_prompt_includes_track_schema()` to `app/tests/test_generation_pipeline.py`. Call `build_outline_prompt()` and assert the returned string contains `"track_id"`, `"tracks"`, and `"goal"`. Assert it also contains the guidance string `"only when the conversation discussed breakout"`.

**Docstring**: Update `build_outline_prompt()` docstring to: `"Build the Stage 1 outline prompt for the two-stage generation pipeline. Produces a lightweight sequence plan (tool_type, title, duration, collaboration pattern, rationale) with optional track grouping metadata (tracks array, per-activity track_id) for multi-track meetings. Validated before full agenda generation."`

**Technical deviations**: To satisfy the thread-level verification gate ("pytest passes 100%"), full-suite regression exposed pre-existing stale expectations in prompt tests (`app/tests/test_meeting_designer_prompt.py`) and pipeline-call wiring assertions (`app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request`). Updated those tests to align with current architecture (pattern-library wording and route-level delegation to `_run_generation_pipeline`) without changing runtime behavior for this step.

---

## Step 2: Replace formulaic multi-track outline rules with pattern-library guidance [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, replace the `Multi-track outline rules` block (lines 370–374) in `build_outline_prompt()`. Remove the prescriptive `"diverge → organize/reduce → converge arc"` recipe. Replace with:

- (a) Hard constraint: each track MUST have 2+ activities in the outline — a single activity per track is never acceptable.
- (b) Instruction to select a pattern from the Collaboration Pattern Library that matches the track's goal, time budget, and deliverable type.
- (c) The compact pattern selection guide (same 5 named patterns from Phase 1):
  - **Quick Convergence** (brainstorming → voting): short time, simple shortlist.
  - **Organized Convergence** (brainstorming → categorization → voting): ideas need thematic structure.
  - **Rigorous Ranking** (brainstorming → categorization → rank_order_voting): fully ordered priority list.
  - **Two-Pass Funnel** (brainstorming → voting → brainstorming → rank_order_voting): time for deeper deliberation.
  - **Nested Decomposition** (brainstorming → voting → brainstorming → voting): narrow scope before ideation.
- (d) Guidance that different tracks may use different patterns if their goals differ.
- (e) Instruction to set the `rationale` field on each activity to explain why that pattern was chosen for that track.

**Test**: Add `test_outline_prompt_pattern_library_guidance()` to `app/tests/test_generation_pipeline.py`. Call `build_outline_prompt()` and assert the returned string contains `"Quick Convergence"` and `"Collaboration Pattern Library"`. Assert it does NOT contain `"diverge → organize/reduce → converge arc"`.

**Docstring**: Already updated in Step 1. No additional changes needed.

**Technical deviations**: Existing test `test_build_outline_prompt_pattern_library()` already covered part of this behavior. Added the explicitly named `test_outline_prompt_pattern_library_guidance()` per Step 2 requirements while retaining the earlier regression test.

---

## Step 3: Update outline validation to enforce multi-track activity counts [DONE]

**Implement**: In `app/services/agenda_validator.py`, enhance `validate_outline()` to add a post-validation check for multi-track outlines. After the existing `_validate_activity_payload()` call, if the result is valid AND the outline contains a `tracks` array with 1+ entries:

1. Collect all `track_id` values from the `tracks` array.
2. For each declared track, count how many outline activities reference that `track_id`.
3. If any track has fewer than 2 activities, add an error: `"Track '{track_id}' ({label}) has {n} activity but must have at least 2."`.
4. If any outline activity references a `track_id` not declared in the `tracks` array, add a warning: `"Activity '{title}' references undeclared track_id '{track_id}'."`.

If the `tracks` array is absent or empty, skip these checks entirely (backward-compatible for simple/multi_phase meetings).

**Test**: Add `test_validate_outline_multi_track_enforcement()` to `app/tests/test_generation_pipeline.py`. Test three cases:
- (a) Valid: 2 tracks, each with 2+ activities → passes validation.
- (b) Invalid: 1 track has only 1 activity → validation fails with the expected error message.
- (c) Warning: activity references a `track_id` not in the `tracks` array → validation passes but includes a warning.
- (d) No tracks array → validation passes (backward-compatible).

**Docstring**: Update `validate_outline()` docstring to: `"Validate Stage 1 outline output against the live activity catalog. Validates tool_types, titles, and durations. When a tracks array is present, enforces that each declared track has at least 2 activities and flags undeclared track_id references."`

**Technical deviations**: None. Implemented as specified, including exact error/warning message templates and backward-compatible no-tracks behavior.

---

## Step 4: Update Stage 1 → Stage 2 handoff to pass track groupings [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, modify the outline rendering block in `build_generation_prompt()` (lines 225–240). When the validated outline includes a `tracks` array, render the outline grouped by track instead of as a flat numbered list:

Current flat rendering:
```
1. Generate Budget Ideas [brainstorming]
2. Group Budget Ideas [categorization]
3. Vote Budget Priorities [voting]
```

New track-grouped rendering:
```
Plenary activities:
1. Opening Discussion [brainstorming]

Track "Budget Review" (track_a):
2. Generate Budget Ideas [brainstorming]
3. Group Budget Ideas [categorization]
4. Vote Budget Priorities [voting]

Track "Technology Assessment" (track_b):
5. Generate Tech Options [brainstorming]
6. Evaluate Tech Options [voting]
```

Add logic to:
1. Check if the outline contains a `tracks` list.
2. If yes, separate activities into plenary (null/missing `track_id`) and per-track groups.
3. Render plenary activities first, then each track group under a header.
4. If no `tracks` list exists, fall back to the existing flat rendering.

Update the `outline_prefix` text to: `"The following activity outline has been approved. Generate the full agenda following this exact sequence, tool_types, titles, and track groupings. Add instructions and config_overrides for each."` (adding "and track groupings").

**Test**: Add `test_generation_prompt_renders_track_grouped_outline()` to `app/tests/test_generation_pipeline.py`. Call `build_generation_prompt()` with an outline containing a `tracks` array and activities with `track_id` values. Assert the rendered prompt contains `'Track "Budget Review"'` and proper grouping. Also test with an outline without `tracks` to confirm flat rendering still works.

**Docstring**: Update the `build_generation_prompt()` docstring to note: `"When the outline includes track metadata (tracks array, per-activity track_id), the outline is rendered grouped by track to preserve multi-track structure for Stage 2 elaboration."`

**Technical deviations**: Implemented `build_generation_prompt()` and `build_generation_messages()` to accept either the legacy outline list or a full Stage 1 outline payload dict (`outline` + optional `tracks`) for backward compatibility. Added safe rendering for undeclared `track_id` buckets instead of dropping those activities.

---

## Step 5: Add conversation-context awareness to outline prompt [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, add guidance to `build_outline_prompt()` that instructs the AI to reason about track patterns based on the conversation context. Add a new section after the pattern selection guide:

```
Track-aware reasoning:
- Read the conversation for mentions of breakout groups, parallel tracks, sub-teams, or topic-specific working groups.
- If breakout tracks were discussed, populate the tracks array with one entry per track, using the labels and goals from the conversation.
- For each track, select a pattern from the Collaboration Pattern Library that fits the track's stated goal and time budget.
- Set each activity's track_id to match its parent track.
- If no breakout tracks were discussed, omit the tracks array and set all track_id values to null.
- The rationale field should explain the pattern choice for that track (e.g., "Quick Convergence chosen because this track has only 15 minutes to produce a shortlist").
```

**Test**: Add `test_outline_prompt_track_reasoning_guidance()` to `app/tests/test_generation_pipeline.py`. Call `build_outline_prompt()` and assert the returned string contains `"Track-aware reasoning"`, `"breakout"`, and `"rationale"`.

**Docstring**: Already updated in Step 1. No additional changes needed.

**Technical deviations**: None. Implemented the track-aware reasoning block in `build_outline_prompt()` and added the exact named test.

---

## Step 6: Regression — Verify all existing tests still pass [DONE]

**Implement**: No code changes. Run the full existing test suite to confirm nothing was broken by Steps 1–5. The outline schema extension is additive (optional `tracks` array, optional `track_id`), so existing tests that build outlines without track metadata must continue to pass. The validator change only activates when a `tracks` array is present, preserving backward compatibility.

**Test**: Execute:
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
venv/bin/python -m pytest app/tests/test_config_loader.py -q -k meeting_designer
```
All must pass.

**Docstring**: No changes needed.

**Technical deviations**: Ran both prescribed Step 6 commands and additionally ran full-suite `venv/bin/python -m pytest -q` to satisfy the thread-level verification requirement.

---

## Phase Exit Criteria

**New tests** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q -k "track_schema or track_grouped or track_enforcement or track_reasoning or outline_prompt_pattern_library_guidance" --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 6 passed
1. `test_outline_prompt_includes_track_schema`
2. `test_outline_prompt_pattern_library_guidance`
3. `test_validate_outline_multi_track_enforcement`
4. `test_generation_prompt_renders_track_grouped_outline`
5. `test_outline_prompt_track_reasoning_guidance`
6. Regression (all existing tests pass)

**Full regression** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py app/tests/test_config_loader.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 110+ passed (94 existing + 5 Phase 1 + 5 Phase 2 + 6 Phase 3)
