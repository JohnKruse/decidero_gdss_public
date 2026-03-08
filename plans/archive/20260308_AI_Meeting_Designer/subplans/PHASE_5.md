# Phase 5 — Conversation Design Guidance [COMPLETE]

**Phase Canary**: Copper Sagebrush

**Parent**: `plans/01_MASTER_PLAN.md` (Cobalt Fennel)

**Objective**: Update the MOTION Phase 5 (Design Discussion) in the system prompt to guide the AI in discussing within-track workflow options with the facilitator — presenting trade-offs between collaboration patterns rather than silently picking one. The AI should propose specific within-track workflow patterns during design discussion, explain time/depth trade-offs, and confirm the facilitator's preference before proceeding to generation. This phase is independent of Phases 2–4 and touches only the YAML prompt surface.

---

## Files Modified

| File | Functions/Sections |
|------|-------------------|
| `app/config/prompts/meeting_designer.yaml` | `system_suffix`: MOTION Phase 5 — DESIGN DISCUSSION block (line 134) |
| `app/services/meeting_designer_prompt.py` | `build_system_prompt()` — no logic changes, but docstring update to reflect new prompt content |
| `app/tests/test_generation_pipeline.py` | New test functions (5 tests) |

---

## Step 1: Add pattern trade-off examples to MOTION Phase 5 prompt [DONE]

**Implement**: In `app/config/prompts/meeting_designer.yaml`, expand the `Phase 5 — DESIGN DISCUSSION` block (line 134). After the existing bullet about walking the facilitator through the proposed activity flow, add a new section titled `Within-track workflow discussion`. This section must instruct the AI to:

1. For each breakout track identified in the conversation, propose at least two candidate collaboration patterns from the Collaboration Pattern Library (established in Phase 1).
2. Present each candidate as a concrete workflow with estimated total time. Use this format as the exemplar in the prompt:
   - `"Option A — Quick Convergence (brainstorm → vote, ~20 min): fast, but ideas won't be organized into themes."`
   - `"Option B — Organized Convergence (brainstorm → categorize → vote, ~35 min): takes longer, but you'll get a structured deliverable with themed groups."`
   - `"Option C — Rigorous Ranking (brainstorm → categorize → rank-order vote, ~45 min): gives a fully ordered priority list, best when the group needs a clear 1-2-3 ranking."`
3. Instruct the AI to explain what the facilitator gains and gives up with each option — the trade-off must be explicit, not implied.

This step focuses exclusively on embedding the exemplar trade-off language. Do not modify any other MOTION phase.

**Test**: Add `test_system_prompt_contains_pattern_tradeoff_examples()` to `app/tests/test_generation_pipeline.py`. Call `build_system_prompt()` and assert:
- The returned string contains `"Quick Convergence"`.
- The returned string contains `"Organized Convergence"`.
- The returned string contains `"Rigorous Ranking"`.
- The returned string contains `"Within-track workflow discussion"` (section header).

**Docstring**: No code function changes in this step — the YAML is the prompt template. No docstring updates needed.

**Technical deviations**: Executed full-suite `venv/bin/python -m pytest -q` for thread-level verification in addition to the step's named test; no behavior deviations from Step 1 requirements.

---

## Step 2: Add facilitator confirmation gate to Phase 5 [DONE]

**Implement**: In `app/config/prompts/meeting_designer.yaml`, within the expanded `Phase 5 — DESIGN DISCUSSION` block, add a `Facilitator confirmation` sub-section immediately after the within-track workflow discussion. This sub-section must instruct the AI to:

1. After presenting the pattern options for each track, explicitly ask the facilitator which pattern they prefer for that track. Example phrasing: `"Which workflow fits best for this track — the quick option or the more structured one? Or would you like something different?"`
2. Record the facilitator's choice and reference it when summarizing design decisions in Phase 6 (Agenda Generation).
3. If the facilitator is uncertain or defers, recommend the pattern that best matches the track's time budget and deliverable type — but still confirm before proceeding.
4. Never silently choose a pattern. The facilitator must acknowledge the choice before the AI moves to generation.

This step adds the explicit confirmation gate that prevents the AI from auto-selecting patterns without facilitator input.

**Test**: Add `test_system_prompt_contains_facilitator_confirmation_gate()` to `app/tests/test_generation_pipeline.py`. Call `build_system_prompt()` and assert:
- The returned string contains `"Facilitator confirmation"` (sub-section header).
- The returned string contains `"Which workflow"` (the confirmation question exemplar).
- The returned string contains `"Never silently choose a pattern"` (the hard constraint).

**Docstring**: No code function changes in this step. No docstring updates needed.

**Technical deviations**: Executed full-suite `venv/bin/python -m pytest -q` for thread-level verification in addition to the step's named test; no behavior deviations from Step 2 requirements.

---

## Step 3: Add time-budget reasoning guidance to Phase 5 [DONE]

**Implement**: In `app/config/prompts/meeting_designer.yaml`, within the `Phase 5 — DESIGN DISCUSSION` block, add a `Time-budget reasoning` sub-section after the facilitator confirmation gate. This sub-section must instruct the AI to:

1. Calculate the available time per track by dividing the total parallel-phase duration by 1 (since tracks run simultaneously, each track gets the full parallel-phase timeslot).
2. Eliminate pattern options that exceed the track's time budget. Example: `"If a track has only 20 minutes, do not propose patterns requiring 35+ minutes. Present only patterns that fit the available time."`.
3. When presenting options, annotate each with its estimated total duration and flag whether it is a tight fit, comfortable fit, or over-budget for the track's timeslot.
4. If only one pattern fits the time budget, explain why the others were excluded: `"The other patterns require more time than this track's 20-minute slot allows."`.

This step ensures the AI's pattern proposals are grounded in practical time constraints rather than abstract preferences.

**Test**: Add `test_system_prompt_contains_time_budget_reasoning()` to `app/tests/test_generation_pipeline.py`. Call `build_system_prompt()` and assert:
- The returned string contains `"Time-budget reasoning"` (sub-section header).
- The returned string contains `"exceed the track"` or `"over-budget"` (time constraint language).
- The returned string contains `"estimated total duration"` (duration annotation instruction).

**Docstring**: No code function changes in this step. No docstring updates needed.

**Technical deviations**: Executed full-suite `venv/bin/python -m pytest -q` for thread-level verification in addition to the step's named test; no behavior deviations from Step 3 requirements.

---

## Step 4: Add per-track differentiation guidance to Phase 5 [DONE]

**Implement**: In `app/config/prompts/meeting_designer.yaml`, within the `Phase 5 — DESIGN DISCUSSION` block, add a `Per-track differentiation` sub-section after the time-budget reasoning. This sub-section must instruct the AI to:

1. Recognize that different tracks may have different goals and therefore warrant different workflow patterns. Example: `"A track focused on generating creative ideas might use Quick Convergence, while a track focused on prioritizing existing options might use Rigorous Ranking."`.
2. Discuss each track's workflow independently — do not assume all tracks use the same pattern.
3. Explicitly highlight when two tracks have similar goals and suggest the same pattern for both, explaining why: `"Both tracks are doing the same type of work, so the same pattern makes sense here."`.
4. When the facilitator has stated a track-specific deliverable (from the earlier Phase 5 questions about what each track should produce), use that deliverable to recommend a matching pattern. Map deliverable types to patterns:
   - Shortlist / top-N → Quick Convergence or Organized Convergence
   - Ranked priority list → Rigorous Ranking
   - Refined proposal → Two-Pass Funnel
   - Categorized inventory → Organized Convergence

**Test**: Add `test_system_prompt_contains_per_track_differentiation()` to `app/tests/test_generation_pipeline.py`. Call `build_system_prompt()` and assert:
- The returned string contains `"Per-track differentiation"` (sub-section header).
- The returned string contains `"different tracks may have different goals"`.
- The returned string contains `"Shortlist"` and `"Ranked priority list"` (deliverable-to-pattern mapping).

**Docstring**: No code function changes in this step. No docstring updates needed.

**Technical deviations**: Executed full-suite `venv/bin/python -m pytest -q` for thread-level verification in addition to the step's named test; no behavior deviations from Step 4 requirements.

---

## Step 5: Update build_system_prompt() docstring and run regression [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, update the `build_system_prompt()` docstring to reflect the expanded Phase 5 content. The updated docstring should read: `"Build the Meeting Designer system prompt with the live activity catalog. The STRUCTURE section is generated at call time from the plugin registry, so it stays in sync with the Activity Library automatically. The MOTION section guides a six-phase conversation: goal framing, format shaping, scope calibration, criteria discovery, design discussion (with within-track workflow pattern trade-offs and facilitator confirmation), and generation handoff."`.

Run the full regression suite to confirm the YAML changes did not break any existing tests. The changes are purely additive prompt text — no logic, schema, or validation changes — so all existing tests must continue to pass.

**Test**: Execute:
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
venv/bin/python -m pytest app/tests/test_config_loader.py -q -k meeting_designer
```
All must pass.

Also add `test_build_system_prompt_docstring_reflects_design_discussion()` to `app/tests/test_generation_pipeline.py`. Import `build_system_prompt` and use `inspect.getdoc()` to assert the docstring contains `"within-track workflow pattern trade-offs"`.

**Docstring**: This step IS the docstring update (described above).

**Technical deviations**: The initial docstring assertion failed due to wrapped whitespace in `inspect.getdoc()` output; normalized whitespace in the test before asserting the required phrase. Executed both prescribed Step 5 regression commands and full-suite `venv/bin/python -m pytest -q` for thread-level verification.

---

## Phase Exit Criteria

**New tests** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q -k "pattern_tradeoff or facilitator_confirmation_gate or time_budget_reasoning or per_track_differentiation or design_discussion" --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 5 passed
1. `test_system_prompt_contains_pattern_tradeoff_examples`
2. `test_system_prompt_contains_facilitator_confirmation_gate`
3. `test_system_prompt_contains_time_budget_reasoning`
4. `test_system_prompt_contains_per_track_differentiation`
5. `test_build_system_prompt_docstring_reflects_design_discussion`

**Full regression** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py app/tests/test_config_loader.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 122+ passed (94 existing + 5 Phase 1 + 5 Phase 2 + 6 Phase 3 + 7 Phase 4 + 5 Phase 5)
