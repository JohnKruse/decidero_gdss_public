# Phase 1 [COMPLETE] — Validation Engine

> Global Canary: `BRASS-PELICAN-7`
> Phase Canary: `COPPER-HERON-3`
> Source: `plans/01_MASTER_PLAN.md`, Phase 1
> Target file: `app/services/agenda_validator.py`
> Target test file: `app/tests/test_agenda_validator.py`

---

## Context

The AI Meeting Designer currently validates generated agenda JSON with three checks: is it parseable JSON, does it have an `agenda` key, and is that key a list. No per-activity validation exists at the generation endpoint. Hallucinated tool_types, empty fields, invalid config keys, and out-of-range durations all pass through silently — only to crash downstream when the facilitator tries to create the meeting.

This phase builds a standalone validation module that can judge AI-generated agenda output against the live activity catalog. It is a **pure function with no side effects**: dict in, verdict out. It imports only from `activity_catalog.py` and the standard library.

---

## Atomic Steps

### Step 1 [DONE] — Result data structures and module skeleton

Define the return types for the validator. The validator must communicate per-activity errors and warnings separately, with an overall pass/fail verdict.

**Implement:**
- Create `app/services/agenda_validator.py`
- Define `AgendaFieldError` (dataclass): `activity_index: int`, `field: str`, `message: str`, `level: Literal["error", "warning"]`
- Define `AgendaValidationResult` (dataclass): `valid: bool`, `errors: List[AgendaFieldError]`, `warnings: List[AgendaFieldError]`
  - `valid` is `True` only when `errors` is empty (warnings do not fail validation)
- Define the public function stub `validate_agenda(agenda_data: Dict[str, Any]) -> AgendaValidationResult` that returns a passing result for now
- Add module docstring referencing `BRASS-PELICAN-7` and `COPPER-HERON-3`

**Test:**
- Create `app/tests/test_agenda_validator.py`
- Add module docstring referencing `COPPER-HERON-3`
- `test_result_dataclasses_exist` — import and instantiate `AgendaFieldError` and `AgendaValidationResult`, verify field access
- `test_empty_agenda_passes` — call `validate_agenda({"agenda": []})` and assert `result.valid is True` with no errors or warnings
- `test_validate_agenda_is_importable` — verify the function can be imported from `app.services.agenda_validator`

**Docs:**
- Docstring on `validate_agenda` explaining: accepts the raw dict returned by `parse_agenda_json()`, returns `AgendaValidationResult`, pure function with no DB or network calls

**Technical deviations:**
- No functional deviation from Step 1 scope.
- Added full `Args`/`Returns`/`Raises` docstring sections in `validate_agenda` to align with Step 7 documentation standards early.

---

### Step 2 [DONE] — Top-level structure validation

Validate the envelope: `agenda` key must exist and be a non-empty list, `meeting_summary` and `design_rationale` must be non-empty strings.

**Implement:**
- In `validate_agenda()`, before iterating activities:
  - If `agenda` key is missing or not a list → append error (index=-1, field="agenda", message describing the issue)
  - If `agenda` is an empty list → append error (index=-1, field="agenda", message="Agenda contains no activities")
  - If `meeting_summary` is missing or empty string → append warning (index=-1, field="meeting_summary")
  - If `design_rationale` is missing or empty string → append warning (index=-1, field="design_rationale")
- If `agenda` is missing or not a list, return early (no point validating activities)

**Test:**
- `test_missing_agenda_key` — input `{}` → `valid is False`, one error referencing "agenda"
- `test_agenda_not_a_list` — input `{"agenda": "oops"}` → `valid is False`
- `test_empty_agenda_list` — input `{"agenda": []}` → `valid is False`
- `test_missing_meeting_summary_warns` — input with valid agenda but no `meeting_summary` → `valid is True`, one warning
- `test_missing_design_rationale_warns` — input with valid agenda but no `design_rationale` → `valid is True`, one warning

**Docs:**
- Update `validate_agenda` docstring to describe envelope checks

**Technical deviations:**
- Preserved Step 1 behavior where `agenda: []` was previously considered valid only by replacing it with the Step 2 requirement (`Agenda contains no activities` error), and updated the prior test accordingly.
- Full-suite verification run has zero failures but includes existing unrelated skips in the baseline suite (`293 passed, 2 skipped`), so strict no-skip "100%" remains unmet at repository level.

---

### Step 3 [DONE] — tool_type validation against live catalog

Check each activity's `tool_type` against the plugin registry via `get_enriched_activity_catalog()`. This is the core check that eliminates hallucinated activity types.

**Implement:**
- At the start of `validate_agenda()`, call `get_enriched_activity_catalog()` once and build a lookup dict keyed by normalized `tool_type`
- For each activity in the agenda list:
  - If `tool_type` is missing, empty, or not a string → append error
  - Normalize `tool_type` (strip + lowercase) and check against lookup dict → if not found, append error with message listing all valid tool_types
- Store the resolved catalog entry for each valid activity for use in subsequent checks (steps 4-6)

**Test:**
- `test_valid_tool_type_passes` — activity with `tool_type: "brainstorming"` → no error for that field
- `test_hallucinated_tool_type_fails` — activity with `tool_type: "discussion"` → error, message includes available types
- `test_missing_tool_type_fails` — activity with no `tool_type` key → error
- `test_tool_type_case_insensitive` — activity with `tool_type: "BRAINSTORMING"` → no error (normalized)
- `test_multiple_activities_mixed_validity` — 3 activities, one invalid tool_type → `valid is False`, exactly 1 error, the other 2 are clean

**Docs:**
- Inline comment explaining why catalog is queried at call time (stays in sync with live registry, no hardcoded list)

**Technical deviations:**
- Added a defensive `activity` type guard (`if not isinstance(activity, dict): continue`) before reading `tool_type`; this is forward-compatible with later steps and avoids runtime errors on malformed list entries.
- Full-suite verification remains green with existing repository baseline skips (`298 passed, 2 skipped`), so strict no-skip "100%" is still not met at repository level.

---

### Step 4 [DONE] — Required field presence validation

Check that each activity has non-empty `title` and `instructions` fields.

**Implement:**
- For each activity in the agenda:
  - If `title` is missing, not a string, or empty after stripping → append error
  - If `instructions` is missing, not a string, or empty after stripping → append error
  - If `duration_minutes` is missing or not a positive number → append warning (not an error — the frontend drops this field anyway, but it indicates the AI didn't follow the prompt)
  - If `rationale` is missing or empty → append warning

**Test:**
- `test_complete_activity_passes` — activity with all required fields populated → no errors
- `test_missing_title_fails` — activity with `title: ""` → error
- `test_missing_instructions_fails` — activity with no `instructions` key → error
- `test_missing_duration_warns` — activity with no `duration_minutes` → warning, not error
- `test_missing_rationale_warns` — activity with no `rationale` → warning, not error
- `test_whitespace_only_title_fails` — activity with `title: "   "` → error (stripped to empty)

**Docs:**
- Docstring section explaining the error vs warning distinction: errors block generation, warnings are informational

**Technical deviations:**
- To preserve actionable output for retries, validation continues checking `title`/`instructions`/`duration_minutes`/`rationale` even when `tool_type` is invalid; this yields multi-error feedback in one pass rather than short-circuiting after the first tool_type error.
- Full-suite verification remains free of failures but includes existing baseline skips (`304 passed, 2 skipped`), so strict no-skip "100%" remains unmet at repository level.

---

### Step 5 [DONE] — config_overrides key validation

Check that any keys in `config_overrides` are recognized by the target plugin's `default_config`. Unknown keys indicate the AI is hallucinating config options.

**Implement:**
- For each activity with a valid (resolved) tool_type:
  - If `config_overrides` is present and not a dict → append error
  - If `config_overrides` is a dict, compare its keys against the plugin's `default_config` keys (from the catalog entry resolved in Step 3)
  - For each key in `config_overrides` that is NOT in `default_config` → append warning (not error — unknown keys are harmless since config merge ignores them, but they indicate prompt drift)
- Skip this check entirely for activities with invalid tool_type (already flagged in Step 3)

**Test:**
- `test_valid_config_overrides_pass` — brainstorming activity with `config_overrides: {"allow_anonymous": true}` → no warnings
- `test_unknown_config_key_warns` — brainstorming activity with `config_overrides: {"enable_reactions": true}` → warning mentioning "enable_reactions"
- `test_config_overrides_not_a_dict_fails` — activity with `config_overrides: "oops"` → error
- `test_missing_config_overrides_ok` — activity with no `config_overrides` key → no error, no warning (it's optional)
- `test_config_validation_skipped_for_invalid_tool_type` — activity with invalid tool_type and config_overrides → only the tool_type error appears, no config warnings

**Docs:**
- Inline comment explaining why unknown keys are warnings not errors (config merge via `dict.update()` silently ignores them downstream)

**Technical deviations:**
- Config-key warnings are emitted per unknown key (one warning each) to preserve precise retry feedback instead of collapsing multiple unknown keys into a single aggregated warning.
- Full-suite verification remains free of failures but includes existing baseline skips (`309 passed, 2 skipped`), so strict no-skip "100%" remains unmet at repository level.

---

### Step 6 [DONE] — Duration range and collaboration_pattern validation

Check `duration_minutes` against the plugin's `typical_duration_minutes` range and `collaboration_pattern` against the plugin's `collaboration_patterns` list.

**Implement:**
- For each activity with a valid tool_type:
  - If `duration_minutes` is present and numeric:
    - Get `typical_duration_minutes` from catalog entry (`{"min": X, "max": Y}`)
    - If duration is outside the range → append warning (not error — the AI may have good reasons to deviate, but it signals potential issues)
  - If `collaboration_pattern` is present and non-empty:
    - Get `collaboration_patterns` list from catalog entry
    - If the value is not in the list → append warning with message listing valid patterns for this tool_type

**Test:**
- `test_duration_in_range_no_warning` — brainstorming with `duration_minutes: 15` (within 5-30) → no warning
- `test_duration_out_of_range_warns` — brainstorming with `duration_minutes: 120` → warning
- `test_duration_zero_warns` — activity with `duration_minutes: 0` → warning (already caught by Step 4 as missing, but also flagged here)
- `test_valid_collaboration_pattern_passes` — brainstorming with `collaboration_pattern: "Generate"` → no warning
- `test_invalid_collaboration_pattern_warns` — brainstorming with `collaboration_pattern: "Synthesize"` → warning listing valid patterns
- `test_range_check_skipped_for_invalid_tool_type` — activity with invalid tool_type → no duration/pattern warnings (tool_type error is sufficient)

**Docs:**
- Docstring on any helper functions explaining the warning-not-error rationale for range checks (AI may intentionally deviate for pedagogical reasons)

**Technical deviations:**
- Range checks emit an additional `duration_minutes` warning when numeric values are both invalid for Step 4 semantics and outside the plugin range (for example `0`), preserving both signals for retry prompts.
- `collaboration_pattern` validation runs only when the catalog provides at least one declared pattern; empty/missing pattern lists do not trigger warnings.
- Full-suite verification remains free of failures but includes existing baseline skips (`315 passed, 2 skipped`), so strict no-skip "100%" remains unmet at repository level.

---

### Step 7 [DONE] — Integration test with realistic payloads and import isolation check

Build end-to-end tests with realistic multi-activity agendas (both valid and invalid) and verify the module's import graph.

**Implement:**
- Create a convenience helper `_make_activity(**overrides)` in the test file that returns a complete valid activity dict with sensible defaults, overridable per-field. This reduces boilerplate in all prior test functions (refactor as needed).
- Add a `_make_agenda(activities, **envelope_overrides)` helper that wraps activities in the full envelope with `meeting_summary`, `design_rationale`, and `agenda` keys.

**Test:**
- `test_realistic_valid_5_activity_agenda` — Classic sequence (brainstorming → categorization → voting → rank_order_voting → voting) with all fields populated → `valid is True`, zero errors, acceptable warnings only
- `test_realistic_invalid_agenda_multiple_errors` — 4 activities with a mix of issues: one hallucinated tool_type, one empty title, one unknown config key, one out-of-range duration → `valid is False`, verify exact error count and that error messages are specific and actionable
- `test_single_activity_agenda_valid` — minimal valid agenda with 1 brainstorming activity → passes
- `test_validator_import_isolation` — inspect `agenda_validator.__module__` imports: assert no imports from `app.routers`, `app.services.ai_provider`, `app.services.meeting_designer_prompt`, `app.templates`, `app.data`, or `app.models`. Only `app.services.activity_catalog` and stdlib/typing are allowed.
- `test_error_messages_include_context` — verify that error messages include the activity index and field name so they're useful in retry prompts (e.g., "Activity 2: tool_type 'discussion' is not registered")

**Docs:**
- Update module docstring on `agenda_validator.py` with a usage example showing expected input and output
- Ensure all public functions have complete docstrings with Args, Returns, and Raises sections

**Technical deviations:**
- Added `_activity_message()` helper and standardized message formatting to include activity index and field context directly in message strings (in addition to structured `activity_index`/`field` fields), so retry prompts can use messages without extra formatting logic.
- Import-isolation test validates source-level import statements rather than runtime module graph traversal to keep the check deterministic and fast.
- Full-suite verification remains free of failures but includes existing baseline skips (`320 passed, 2 skipped`), so strict no-skip "100%" remains unmet at repository level.

---

## Phase Exit Criteria

```bash
pytest app/tests/test_agenda_validator.py -v
```

**All tests must pass at 100%.** No skips, no xfails. The validator module must be fully functional and decoupled before Phase 2 begins.
