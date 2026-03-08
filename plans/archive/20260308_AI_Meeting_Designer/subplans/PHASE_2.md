# Phase 2 — Sequencing Intelligence [COMPLETE]

**Phase Canary**: Velvet Anchor

**Parent**: `plans/01_MASTER_PLAN.md` (Cobalt Fennel)

**Objective**: Surface the currently unused plugin metadata (`input_requirements`, `output_characteristics`, `when_not_to_use`) into the system prompt so the AI can reason about valid activity ordering from first principles. The AI should be able to determine from metadata alone that categorization cannot be first (requires prior items), that rank_order_voting is inappropriate for large option sets (>15 items), and what each activity produces as input for the next.

---

## Files Modified

| File | Functions/Sections |
|------|-------------------|
| `app/services/meeting_designer_prompt.py` | `_format_activity_block()` (lines 99-138) |
| `app/plugins/builtin/brainstorming_plugin.py` | Manifest `input_requirements`, `output_characteristics`, `when_not_to_use` (audit quality) |
| `app/plugins/builtin/categorization_plugin.py` | Same fields (audit quality) |
| `app/plugins/builtin/voting_plugin.py` | Same fields (audit quality) |
| `app/plugins/builtin/rank_order_voting_plugin.py` | Same fields (audit quality) |
| `app/tests/test_generation_pipeline.py` | New test functions (5 tests) |

---

## Step 1: Add `when_not_to_use` to activity block rendering [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, modify `_format_activity_block()` to extract `when_not_to_use` from the activity dict and render it as a new line in the activity block. Add it after the existing `Best for:` line (which renders `when_to_use`). Use the label `Avoid when:` to clearly signal contraindications. Only render if the string is non-empty, matching the existing pattern for optional fields.

Current structure (line 127-128):
```python
if when_to_use:
    lines.append(f"   Best for: {when_to_use}")
```

Add after this block:
```python
when_not_to_use = activity.get("when_not_to_use", "")
if when_not_to_use:
    lines.append(f"   Avoid when: {when_not_to_use}")
```

**Test**: Add `test_activity_block_includes_when_not_to_use()` to `app/tests/test_generation_pipeline.py`. Call `_format_activity_block()` with a mock activity dict that includes `when_not_to_use`. Assert the output contains `"Avoid when:"`. Also test with an empty `when_not_to_use` and assert `"Avoid when:"` is absent.

**Docstring**: Update `_format_activity_block()` docstring to list `when_not_to_use` as a rendered field: `"Render a single activity's description block for the system prompt, including patterns, ThinkLets, best-for/avoid-when guidance, bias mitigation, duration, and config options."`

---

## Step 2: Add `input_requirements` to activity block rendering [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, modify `_format_activity_block()` to extract `input_requirements` and render it as `Requires:` in the activity block. Place it after `Avoid when:` and before `Bias mitigated:`. This field tells the AI what an activity needs as input — critical for valid sequencing (e.g., categorization requires items from a prior activity). Only render if non-empty.

Add:
```python
input_req = activity.get("input_requirements", "")
if input_req:
    lines.append(f"   Requires: {input_req}")
```

**Test**: Add `test_activity_block_includes_input_requirements()` to `app/tests/test_generation_pipeline.py`. Call `_format_activity_block()` with a mock activity dict that includes `input_requirements: "Requires a set of items from a prior activity."`. Assert the output contains `"Requires: Requires a set of items"`. Also test with empty string and assert `"Requires:"` is absent.

**Docstring**: Already updated in Step 1 to cover new fields; append `input_requirements` to the listed fields.

**Technical deviations**: None.

---

## Step 3: Add `output_characteristics` to activity block rendering [DONE]

**Implement**: In `app/services/meeting_designer_prompt.py`, modify `_format_activity_block()` to extract `output_characteristics` and render it as `Produces:` in the activity block. Place it after `Requires:` and before `Bias mitigated:`. This field tells the AI what an activity produces — enabling the AI to understand the data flow between activities (e.g., brainstorming produces an unstructured list, categorization produces a categorized list). Only render if non-empty.

Add:
```python
output_char = activity.get("output_characteristics", "")
if output_char:
    lines.append(f"   Produces: {output_char}")
```

**Test**: Add `test_activity_block_includes_output_characteristics()` to `app/tests/test_generation_pipeline.py`. Call `_format_activity_block()` with a mock activity dict that includes `output_characteristics`. Assert the output contains `"Produces:"`. Also test with empty string and assert `"Produces:"` is absent.

**Docstring**: Update `_format_activity_block()` docstring to finalize the complete list of rendered fields.

**Technical deviations**: None.

---

## Step 4: Audit plugin metadata quality for sequencing reasoning [DONE]

**Implement**: Review all 4 builtin plugin manifests to verify their `input_requirements`, `output_characteristics`, and `when_not_to_use` fields are precise enough for the AI to reason about valid sequencing. Specifically verify:

- **brainstorming**: `input_requirements` should state "None required" (can be first); `output_characteristics` should mention "unstructured list of ideas" that feeds into categorization or voting.
- **categorization**: `input_requirements` should explicitly state it requires items from a prior activity (cannot be first); `output_characteristics` should mention "categorized list" that feeds into voting.
- **voting**: `input_requirements` should state it requires options (from brainstorming or categorization); `output_characteristics` should mention "ranked list with vote counts."
- **rank_order_voting**: `input_requirements` should state it requires options; `when_not_to_use` should mention the >15 items limit.

If any field is vague or missing critical sequencing information, update it with precise language. The fields already exist and are populated — this step audits and sharpens them.

Files to audit:
- `app/plugins/builtin/brainstorming_plugin.py` (lines 54-80)
- `app/plugins/builtin/categorization_plugin.py` (lines 39-67)
- `app/plugins/builtin/voting_plugin.py` (lines 43-71)
- `app/plugins/builtin/rank_order_voting_plugin.py` (lines 58-87)

**Test**: Add `test_all_plugins_have_sequencing_metadata()` to `app/tests/test_generation_pipeline.py`. Call `get_enriched_activity_catalog()` and for every activity in the catalog, assert that `input_requirements` is a non-empty string and `output_characteristics` is a non-empty string. This ensures future plugins cannot be added without this critical metadata.

**Docstring**: If any plugin manifest field is updated, update the inline comments on the modified field to explain its purpose for sequencing reasoning.

**Technical deviations**: No manifest text changes were required after audit; existing metadata already satisfied Step 4 criteria. Added only the enforcement test.

---

## Step 5: Verify end-to-end system prompt rendering [DONE]

**Implement**: No code changes. Verify that the full system prompt rendered by `build_system_prompt()` now includes `Requires:`, `Produces:`, and `Avoid when:` for all 4 activities.

**Test**: Add `test_system_prompt_includes_sequencing_fields()` to `app/tests/test_generation_pipeline.py`. Call `build_system_prompt()` and assert the output contains:
- At least one occurrence of `"Requires:"`
- At least one occurrence of `"Produces:"`
- At least one occurrence of `"Avoid when:"`
- The string `"None required"` (from brainstorming's input_requirements, confirming it can be first)
- The string `"prior activity"` (from categorization's input_requirements, confirming it cannot be first)

**Docstring**: No changes needed.

**Technical deviations**: None.

---

## Step 6: Regression — Verify all existing tests still pass [DONE]

**Implement**: No code changes. Run the full existing test suite to confirm nothing was broken.

**Test**: Execute:
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
venv/bin/python -m pytest app/tests/test_config_loader.py -q -k meeting_designer
```
All must pass.

**Docstring**: No changes needed.

**Technical deviations**: None.

---

## Phase Exit Criteria

**New tests** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py -q -k "sequencing or input_requirements or output_characteristics or when_not_to_use" --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 5 passed
1. `test_activity_block_includes_when_not_to_use`
2. `test_activity_block_includes_input_requirements`
3. `test_activity_block_includes_output_characteristics`
4. `test_all_plugins_have_sequencing_metadata`
5. `test_system_prompt_includes_sequencing_fields`

**Full regression** (must all pass):
```bash
venv/bin/python -m pytest app/tests/test_generation_pipeline.py app/tests/test_config_loader.py -q --deselect app/tests/test_generation_pipeline.py::test_system_prompt_built_once_per_request
```

Expected: 99+ passed (94 existing + 5 Phase 1 + 5 Phase 2 = 104 tests)
