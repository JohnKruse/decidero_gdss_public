# Phase 1 — Pattern Library Unification [COMPLETE]

**Phase Canary**: Quartz Bramble

**Parent**: `plans/01_MASTER_PLAN.md` (Cobalt Fennel)

**Objective**: Reframe the existing Standard and Extended Sequences as a single composable Collaboration Pattern Library available at any scope (full session, phase, or within-track). Replace all formulaic "Activity 1 → Activity 2 → Activity 3" prescriptions with pattern selection guidance that gives the AI selection criteria based on time, deliverable type, and problem complexity.

---

## Files Modified

| File | Functions/Sections |
|------|-------------------|
| `app/config/prompts/meeting_designer.yaml` | `system_suffix` (lines 40-86), `generate_agenda` (lines 205-221) |
| `app/services/meeting_designer_prompt.py` | `build_generation_prompt()` (lines 289-303), `build_outline_prompt()` (lines 370-374) |
| `app/tests/test_generation_pipeline.py` | New test functions (5 tests) |

---

## Step 1: Restructure YAML system_suffix — Unify sequences into a Collaboration Pattern Library [DONE]

**Implement**: In `app/config/prompts/meeting_designer.yaml`, merge the three separate sections — `STANDARD SEQUENCES` (lines 42-48), `EXTENDED SEQUENCES` (lines 50-55), and the formulaic breakout track guidelines (lines 76-77) — into a single section titled `COLLABORATION PATTERN LIBRARY`. Reorganize the patterns by complexity/depth rather than by session type. Add a preamble stating these patterns are composable building blocks available at any scope: full session, individual phase, or within a breakout track. Each pattern keeps its existing name and sequence but gains a one-line selection criterion describing when it fits (time budget, deliverable type, problem complexity). The `MULTI-TRACK PATTERNS` section (lines 57-69) remains separate since it describes macro-level session architecture, not composable activity sequences.

**Test**: Add `test_system_prompt_contains_pattern_library()` to `app/tests/test_generation_pipeline.py`. Assert that `build_system_prompt()` output contains the string `"COLLABORATION PATTERN LIBRARY"` and does NOT contain the old section headers `"STANDARD SEQUENCES"` or `"EXTENDED SEQUENCES"` as separate sections. Assert the output contains at least 3 named patterns (Simple Consensus, Classic, Deep Evaluation).

**Docstring**: Add a YAML comment at the top of the unified section: `# Collaboration Pattern Library — composable building blocks for any scope`.

---

## Step 2: Replace YAML system_suffix breakout track guidelines with pattern-aware rules [DONE]

**Implement**: In `app/config/prompts/meeting_designer.yaml`, replace the `BREAKOUT TRACK DESIGN GUIDELINES` (lines 71-78). Remove the formulaic lines: `"Each track should follow a diverge → organize → converge arc"` and `"Each track MUST have a multi-activity sequence (2–3 activities minimum)"`. Replace with:
- (a) Hard constraint: a single-activity track is never acceptable.
- (b) Instruction to select a pattern from the Collaboration Pattern Library that fits each track's time budget, deliverable type, and problem scope.
- (c) Guidance that different tracks may use different patterns if their deliverables differ.
- (d) Guidance to mirror patterns across tracks when outputs need to be comparable.

Keep all other bullet points (track sizing at 8-15 people, descriptive naming, participant assignment) unchanged.

**Test**: Add `test_system_prompt_no_formulaic_track_rules()` to `app/tests/test_generation_pipeline.py`. Assert that `build_system_prompt()` output does NOT contain the strings `"diverge → organize → converge arc"`, `"Activity 1 (Generate)"`, or `"Activity 2 (Organize"`. Assert it DOES contain `"Collaboration Pattern Library"` and `"single-activity"` (the retained hard constraint).

**Docstring**: No Python function modified; the YAML section heading serves as documentation.

---

## Step 3: Replace within-track rules in YAML generate_agenda section [DONE]

**Implement**: In `app/config/prompts/meeting_designer.yaml`, replace the `Within-track workflow rules` block (lines 212-221) in the `generate_agenda` template. Remove the fixed recipe (Activity 1/2/3 and recommended sequences list). Replace with:
- (a) Hard constraint: each breakout track MUST have 2+ activities, never a single activity.
- (b) Instruction to select a pattern from the Collaboration Pattern Library based on the track's time budget, deliverable type, and problem complexity.
- (c) A compact selection guide listing 5 patterns with their one-line selection criterion:
  - **Quick Convergence** (brainstorming → voting): short time, simple shortlist deliverable.
  - **Organized Convergence** (brainstorming → categorization → voting): ideas need thematic structure before evaluation.
  - **Rigorous Ranking** (brainstorming → categorization → rank_order_voting): fully ordered priority list needed.
  - **Two-Pass Funnel** (brainstorming → voting → brainstorming → rank_order_voting): time allows deeper deliberation and refinement.
  - **Nested Decomposition** (brainstorming → voting → brainstorming → voting): problem space too broad for direct ideation, narrow scope first.
- (d) Note that different tracks may use different patterns if their goals differ.

**Test**: Add `test_yaml_generate_agenda_pattern_library()` to `app/tests/test_generation_pipeline.py`. Load the YAML template via `get_meeting_designer_prompt_templates()` and assert `generate_agenda` contains `"Quick Convergence"` and `"Nested Decomposition"` and does NOT contain `"Activity 1 (Generate)"`.

**Docstring**: No Python function modified; update YAML section heading to `Within-track pattern selection (mandatory for multi_track breakout phases)`.

---

## Step 4: Replace within-track rules in Python build_generation_prompt() [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, replace lines 294-303 (the `Within-track workflow rules` block in `build_generation_prompt()`). Remove the fixed recipe. Replace with the same pattern selection guide from Step 3:
- Hard constraint (2+ activities per track, never single-activity).
- Compact pattern selection guide with 5 named patterns and selection criteria.
- Note about pattern flexibility across tracks.

This mirrors the YAML `generate_agenda` content so both prompt paths stay in sync.

**Test**: Add `test_build_generation_prompt_pattern_library()` to `app/tests/test_generation_pipeline.py`. Call `build_generation_prompt()` and assert the returned string contains `"Quick Convergence"` and `"Nested Decomposition"` and does NOT contain `"Activity 1 (Generate)"` or `"diverge → organize/reduce → converge arc"`.

**Docstring**: Update the `build_generation_prompt()` docstring to note that within-track workflow guidance references the Collaboration Pattern Library with per-pattern selection criteria, rather than prescribing a fixed activity sequence.

---

## Step 5: Replace multi-track rules in Python build_outline_prompt() [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, replace lines 370-374 (the `Multi-track outline rules` block in `build_outline_prompt()`). Remove the formulaic `"diverge → organize/reduce → converge arc (e.g., brainstorming → categorization → voting)"`. Replace with:
- (a) Hard constraint: each track MUST have 2+ activities in the outline.
- (b) Instruction to choose a pattern from the Collaboration Pattern Library that fits the track's goal discussed in the conversation.
- (c) List all activities for all tracks sequentially in the outline.
- (d) A single brainstorming per track is never sufficient for a breakout that must produce a specific deliverable.

**Test**: Add `test_build_outline_prompt_pattern_library()` to `app/tests/test_generation_pipeline.py`. Call `build_outline_prompt()` and assert the returned string contains `"Collaboration Pattern Library"` and does NOT contain `"diverge → organize/reduce → converge arc"`.

**Docstring**: Update the `build_outline_prompt()` docstring to reference the Collaboration Pattern Library for multi-track guidance.

---

## Step 6: Regression — Verify all existing tests still pass [DONE]

**Implement**: No code changes. Run the full existing test suite to confirm nothing was broken by Steps 1-5.

**Test**: Execute:
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
venv/bin/python -m pytest app/tests/test_config_loader.py -q -k meeting_designer
```
All must pass (92 pipeline + 2 config = 94 tests).

**Docstring**: No changes needed.

---

## Phase Exit Criteria

**New tests** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q -k "pattern_library or formulaic_track" --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 5 passed
1. `test_system_prompt_contains_pattern_library`
2. `test_system_prompt_no_formulaic_track_rules`
3. `test_yaml_generate_agenda_pattern_library`
4. `test_build_generation_prompt_pattern_library`
5. `test_build_outline_prompt_pattern_library`

**Full regression** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py app/tests/test_config_loader.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 99 passed (94 existing + 5 new)
