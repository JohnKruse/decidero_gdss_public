# Phase 4 — Retry with Error Feedback

> Global Canary: `BRASS-PELICAN-7`
> Phase Canary: `BRONZE-MERLIN-2`
> Source: `plans/01_MASTER_PLAN.md`, Phase 4
> Prerequisites: Phase 1 (`COPPER-HERON-3`), Phase 2 (`SILVER-FALCON-9`), Phase 3 (`IRON-OSPREY-4`)
> Primary target file: `app/routers/meeting_designer.py`
> Target test file: `app/tests/test_generation_pipeline.py` (extended)

---

## Context

After Phase 3, `_run_generation_pipeline()` makes two sequential `chat_complete()` calls (outline, then full JSON). Each stage parses and validates the AI output. On any failure — unparseable JSON, hallucinated tool_type, missing title — the pipeline raises `GenerationPipelineError` immediately and the user sees a 502.

This is still single-shot at each stage. The AI frequently fixes its own mistakes when told exactly what went wrong. Phase 4 adds retry loops: when a stage fails, the specific errors are appended to the message list as a correction prompt and the stage is re-attempted. The AI sees its own bad output and a clear description of what's wrong, then generates a corrected version.

Retry budget (from the design discussion):
- **Outline stage**: up to 3 total attempts (2 retries)
- **Full JSON stage**: up to 2 total attempts (1 retry)

Non-recoverable errors (`AIProviderError`, `AIProviderNotConfiguredError`) are never retried — they propagate immediately. Retry applies only to parse failures and validation failures, which are problems the AI can self-correct.

---

## Interfaces consumed (from Phases 1–3)

```python
# Phase 1 — app/services/agenda_validator.py
validate_agenda(agenda_data: Dict) -> AgendaValidationResult
validate_outline(outline_data: Dict) -> AgendaValidationResult
AgendaValidationResult: { valid: bool, errors: List[AgendaFieldError], warnings: List[AgendaFieldError] }
AgendaFieldError: { activity_index: int, field: str, message: str, level: "error"|"warning" }

# Phase 2 — app/services/meeting_designer_prompt.py
build_outline_messages(conversation_history: List[Dict]) -> List[Dict]
build_generation_messages(conversation_history: List[Dict], outline: Optional[List[Dict]]) -> List[Dict]
parse_outline_json(raw_text: str) -> Dict   # raises ValueError
parse_agenda_json(raw_text: str) -> Dict    # raises ValueError

# Phase 3 — app/routers/meeting_designer.py
GenerationPipelineError: { stage, detail, validation_errors, raw_output }
_format_validation_errors(result: AgendaValidationResult, stage: str) -> GenerationPipelineError
_run_generation_pipeline(settings, history, system_prompt) -> Dict  # async
```

---

## Atomic Steps

### Step 1 — Correction prompt builder

Build the function that converts a failed attempt into a "try again" user message. The correction prompt must tell the AI exactly what went wrong (parse error or specific validation errors) and restate the output-format requirement so the AI doesn't drift.

**Implement** (in `app/routers/meeting_designer.py`):

- `_build_correction_prompt(stage: str, parse_failed: bool, parse_snippet: str, validation_errors: Optional[List[AgendaFieldError]]) -> str`
  - When `parse_failed is True`:
    - Opening: `"Your previous response was not valid JSON."`
    - Include first 300 chars of the raw output as context: `"Here is the beginning of what you returned:\n{parse_snippet}"`
    - Instruction: `"Please output ONLY a valid JSON object with no preamble, no markdown fences, and no explanation outside the JSON."`
  - When `parse_failed is False` (validation errors):
    - Opening: `"Your previous response had {N} validation error(s):"`
    - Numbered list of each error: `"  {i}. Activity {activity_index}: {field} — {message}"`
    - Instruction: `"Please fix these issues and regenerate. Output ONLY the corrected JSON object."`
  - In both cases, append a schema reminder based on `stage`:
    - If `stage == "outline"`: `"The JSON must have a top-level \"outline\" array with objects containing: tool_type, title, duration_minutes, collaboration_pattern, rationale."`
    - If `stage == "full_json"`: `"The JSON must have a top-level \"agenda\" array with objects containing: tool_type, title, instructions, duration_minutes, collaboration_pattern, rationale, config_overrides."`
  - Zero hardcoded tool_type names — the error messages from the validator already include the list of valid types when a tool_type check fails

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_correction_prompt_parse_failure_outline` — call with `parse_failed=True`, `stage="outline"` → output contains `"not valid JSON"`, the parse snippet, `"outline"` schema reminder
- `test_correction_prompt_parse_failure_full_json` — call with `parse_failed=True`, `stage="full_json"` → output contains `"agenda"` schema reminder (not `"outline"`)
- `test_correction_prompt_validation_errors` — call with `parse_failed=False` and 2 `AgendaFieldError` items → output contains `"2 validation error(s)"`, both error messages, activity indices
- `test_correction_prompt_no_hardcoded_tool_types` — `inspect.getsource(_build_correction_prompt)` contains none of `"brainstorming"`, `"voting"`, `"rank_order_voting"`, `"categorization"`
- `test_correction_prompt_includes_raw_snippet` — call with a 500-char `parse_snippet` → only first 300 chars appear in the output (truncation)

**Docs:**
- Docstring: "Builds a user-message correction prompt for a failed pipeline stage. Includes the specific error details and a schema reminder so the AI can self-correct. Used by the retry loop to append error feedback before re-attempting generation."

---

### Step 2 — Retry constants and `GenerationPipelineError` enhancement

Define the attempt limits as module-level constants and extend `GenerationPipelineError` to carry retry metadata, so the endpoint handler and logs can report how many attempts were made and the error trail from each attempt.

**Implement** (in `app/routers/meeting_designer.py`):

- Module-level constants:
  ```python
  _OUTLINE_MAX_ATTEMPTS = 3   # 1 initial + 2 retries
  _AGENDA_MAX_ATTEMPTS = 2    # 1 initial + 1 retry
  ```

- Extend `GenerationPipelineError.__init__` to accept two additional optional parameters:
  - `attempts_made: int = 1` — how many attempts were executed before giving up
  - `error_trail: Optional[List[List[str]]] = None` — list of error-message lists, one inner list per failed attempt (enables debugging across retries)
  - Store both as instance attributes

- Update `_format_validation_errors()` to accept an optional `attempts_made` and `error_trail` parameter and pass them through to the `GenerationPipelineError` it creates. Update the `detail` string to include the attempt count: `"Stage '{stage}' failed validation after {attempts_made} attempt(s) with {N} error(s): {joined_errors}"`

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_pipeline_error_carries_attempts_made` — instantiate with `attempts_made=3` → `exc.attempts_made == 3`
- `test_pipeline_error_carries_error_trail` — instantiate with `error_trail=[[...], [...]]` → `len(exc.error_trail) == 2`
- `test_pipeline_error_defaults` — instantiate without retry kwargs → `attempts_made == 1`, `error_trail is None`
- `test_format_validation_errors_includes_attempt_count` — call `_format_validation_errors` with `attempts_made=3` → detail string contains `"3 attempt(s)"`
- `test_retry_constants_values` — `_OUTLINE_MAX_ATTEMPTS == 3`, `_AGENDA_MAX_ATTEMPTS == 2` (guards against accidental changes)

**Docs:**
- Inline comment on constants: `"# Configurable: increase if the model frequently needs more correction rounds"`
- Update `GenerationPipelineError` docstring to document `attempts_made` and `error_trail`
- Update `_format_validation_errors` docstring to document the new optional parameters

---

### Step 3 — Generic stage runner with retry loop

Build the async helper that encapsulates the parse → validate → correct → retry cycle. This is the core retry engine — both stages call it with their own parser, validator, and attempt limit.

**Implement** (in `app/routers/meeting_designer.py`):

- ```python
  async def _run_stage_with_retry(
      stage: str,
      messages: List[Dict[str, str]],
      parser_fn: Callable[[str], Dict[str, Any]],
      validator_fn: Callable[[Dict[str, Any]], AgendaValidationResult],
      max_attempts: int,
      settings: Dict,
      system_prompt: str,
  ) -> Dict[str, Any]:
  ```
  - `messages` is a mutable list — the function appends correction messages in-place for retries (caller builds the initial list, this function extends it as needed)
  - Loop logic for each attempt `i` in `range(max_attempts)`:
    1. `raw = await chat_complete(settings, messages, system_prompt)`
    2. Try `parsed = parser_fn(raw)` — catch `ValueError`:
       - If attempts remain: build correction prompt (`parse_failed=True`), append `{"role": "assistant", "content": raw}` then `{"role": "user", "content": correction}` to `messages`, `continue`
       - If last attempt: raise `GenerationPipelineError(stage=stage, detail="...", raw_output=raw[:500], attempts_made=i+1, error_trail=accumulated_errors)`
    3. `result = validator_fn(parsed)`
    4. If `result.valid`: return `parsed`
    5. If attempts remain: build correction prompt (`parse_failed=False`, `validation_errors=result.errors`), append assistant + correction messages, accumulate errors, `continue`
    6. If last attempt: raise `GenerationPipelineError` via `_format_validation_errors(result, stage, attempts_made=i+1, error_trail=accumulated_errors)`
  - `accumulated_errors` is a `List[List[str]]` — each inner list contains the error messages from one failed attempt
  - `AIProviderError` and `AIProviderNotConfiguredError` are NOT caught — they propagate immediately (no retry on infrastructure failures)

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_stage_runner_succeeds_first_attempt` — mock `chat_complete` returns valid JSON on first call → returns parsed data, no retry
- `test_stage_runner_succeeds_after_retry` — first call returns invalid JSON, second call returns valid JSON → returns parsed data on attempt 2
- `test_stage_runner_parse_error_then_recovery` — first call returns prose ("Here is your outline:..."), second call returns clean JSON → succeeds, correction prompt was appended
- `test_stage_runner_validation_error_then_recovery` — first call has hallucinated tool_type, second call has valid tool_type → succeeds
- `test_stage_runner_exhausts_all_attempts` — all calls return invalid data → raises `GenerationPipelineError` with `attempts_made == max_attempts` and non-empty `error_trail`
- `test_stage_runner_appends_correction_messages` — after a failed attempt, inspect `messages` list → contains assistant message (AI's bad output) and user message (correction prompt) appended
- `test_stage_runner_does_not_catch_provider_error` — mock raises `AIProviderError` → propagates as-is, not wrapped in `GenerationPipelineError`
- `test_stage_runner_error_trail_accumulates` — 3 attempts with max_attempts=3, all fail → `error_trail` has 3 inner lists

**Docs:**
- Docstring: "Executes a pipeline stage (parse → validate) with automatic retry on failure. When parsing or validation fails, the AI's bad output and a correction prompt are appended to the message list, and the stage is re-attempted. Non-recoverable errors (AIProviderError) propagate immediately. Returns the parsed and validated data dict, or raises GenerationPipelineError after all attempts are exhausted."
- Args documentation for each parameter

---

### Step 4 — Wire `_run_generation_pipeline()` to use the retry-aware stage runner

Replace the direct parse-and-validate calls in `_run_generation_pipeline()` with calls to `_run_stage_with_retry()`. The pipeline function's public signature and return type are unchanged — the retry is invisible to the caller.

**Implement** (in `app/routers/meeting_designer.py`):

- **Stage 1 replacement:**
  - Before (Phase 3): inline `chat_complete → parse_outline_json → validate_outline`, raise on failure
  - After (Phase 4):
    ```python
    outline_messages = build_outline_messages(history)
    outline_data = await _run_stage_with_retry(
        stage="outline",
        messages=outline_messages,
        parser_fn=parse_outline_json,
        validator_fn=validate_outline,
        max_attempts=_OUTLINE_MAX_ATTEMPTS,
        settings=settings,
        system_prompt=system_prompt,
    )
    validated_outline = outline_data["outline"]
    ```

- **Stage 2 replacement:**
  - Before (Phase 3): inline `chat_complete → parse_agenda_json → validate_agenda`, raise on failure
  - After (Phase 4):
    ```python
    generation_messages = build_generation_messages(history, outline=validated_outline)
    agenda_data = await _run_stage_with_retry(
        stage="full_json",
        messages=generation_messages,
        parser_fn=parse_agenda_json,
        validator_fn=validate_agenda,
        max_attempts=_AGENDA_MAX_ATTEMPTS,
        settings=settings,
        system_prompt=system_prompt,
    )
    ```

- Return statement unchanged — still returns `{success, meeting_summary, design_rationale, agenda}` from `agenda_data`
- Remove the inline parse/validate/raise code that Phase 3 added (now handled inside the stage runner)
- The direct `chat_complete` calls in the pipeline body are removed — all calls now go through the stage runner

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_pipeline_outline_retry_then_success` — mock `chat_complete` side_effect: [invalid outline, valid outline, valid agenda] → pipeline returns success, `chat_complete` called 3 times
- `test_pipeline_agenda_retry_then_success` — mock side_effect: [valid outline, invalid agenda, valid agenda] → pipeline returns success, `chat_complete` called 3 times
- `test_pipeline_both_stages_retry` — mock side_effect: [invalid outline, valid outline, invalid agenda, valid agenda] → pipeline returns success, `chat_complete` called 4 times
- `test_pipeline_outline_exhausted` — mock returns 3 consecutive invalid outlines → raises `GenerationPipelineError(stage="outline", attempts_made=3)`
- `test_pipeline_agenda_exhausted` — mock side_effect: [valid outline, 2 invalid agendas] → raises `GenerationPipelineError(stage="full_json", attempts_made=2)`
- `test_pipeline_response_shape_unchanged` — successful pipeline with retry → response still has exactly `{success, meeting_summary, design_rationale, agenda}`
- `test_pipeline_provider_error_no_retry` — mock raises `AIProviderError` on first call → propagates immediately, `chat_complete` called only once (no retry)

**Docs:**
- Update `_run_generation_pipeline` docstring: "Orchestrates the two-stage agenda generation pipeline with automatic retry. Stage 1 generates and validates an activity outline (up to {_OUTLINE_MAX_ATTEMPTS} attempts). Stage 2 generates and validates the full agenda JSON using the validated outline (up to {_AGENDA_MAX_ATTEMPTS} attempts). On validation failure, specific errors are fed back to the AI as a correction prompt before re-attempting. Raises GenerationPipelineError after all retries are exhausted. AIProviderError propagates uncaught."

---

### Step 5 — Logging and timing observability

Add structured logging so that retry behavior is visible in production logs. Each attempt should be logged at INFO level. Warnings from successful attempts should be logged at DEBUG level. Total pipeline wall-clock time should be logged. This is essential for tuning retry limits and prompt quality.

**Implement** (in `app/routers/meeting_designer.py`):

- In `_run_stage_with_retry()`, add logging at key points:
  - Before each attempt: `logger.info("Stage '%s' attempt %d/%d", stage, i+1, max_attempts)`
  - On parse failure (with attempts remaining): `logger.info("Stage '%s' attempt %d/%d: parse error — retrying", stage, i+1, max_attempts)`
  - On validation failure (with attempts remaining): `logger.info("Stage '%s' attempt %d/%d: %d validation error(s) — retrying", stage, i+1, max_attempts, len(result.errors))`
  - On successful validation after retry: `logger.info("Stage '%s' recovered on attempt %d/%d", stage, i+1, max_attempts)`
  - On successful validation first try: `logger.info("Stage '%s' passed on first attempt", stage)`
  - Warnings from successful validation: `logger.debug("Stage '%s' warnings: %s", stage, [w.message for w in result.warnings])`

- In `_run_generation_pipeline()`, add timing:
  - Record `start_time = time.monotonic()` at pipeline entry
  - After Stage 1 completes: `logger.info("Outline stage completed in %.1fs (%d activities)", elapsed, len(validated_outline))`
  - After Stage 2 completes: `logger.info("Full generation completed in %.1fs total (%d activities)", total_elapsed, len(agenda))`

- Add `import time` to the module imports

- In `generate_agenda()` endpoint handler, when catching `GenerationPipelineError`:
  - Log `exc.attempts_made` and `exc.stage`: `logger.error("Pipeline stage '%s' failed after %d attempt(s): %s", exc.stage, exc.attempts_made, exc.detail)`

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_logging_first_attempt_success` — successful first attempt → log output contains `"passed on first attempt"` (use `caplog` fixture)
- `test_logging_retry_recovery` — success on second attempt → log output contains `"retrying"` and `"recovered on attempt 2"`
- `test_logging_exhausted_attempts` — all attempts fail, catch the exception → endpoint log contains `"failed after 3 attempt(s)"` (for outline) or `"failed after 2 attempt(s)"` (for full_json)
- `test_logging_pipeline_timing` — successful pipeline → log output contains two timing entries with `"completed in"` (one per stage)
- `test_logging_warnings_at_debug` — successful validation with warnings → `"warnings"` appears at DEBUG level in caplog

**Docs:**
- Add a comment block above the logging statements: `"# Logging: INFO for attempt lifecycle, DEBUG for warnings and correction prompts"`

---

### Step 6 — End-to-end retry integration tests and regression guards

Verify the complete retry pipeline with realistic multi-activity agendas, confirm retry behavior matches the design spec, and ensure no regressions to the endpoint contract, chat endpoint, or status endpoint.

**Implement:**

- Create test helpers in `test_generation_pipeline.py`:
  - `_mock_chat_complete_sequence(*responses)` — returns an `AsyncMock` whose `side_effect` yields the given raw strings in order. Each string is returned on successive calls to `chat_complete`.
  - `_invalid_outline_json(error="hallucinated_type")` — returns a raw JSON string with a known validation error (e.g., `tool_type: "roundtable"` for hallucinated type, empty title for missing field)
  - `_invalid_agenda_json(error="empty_instructions")` — returns a raw JSON string with a known validation error in the full agenda format

**Test:**

- `test_e2e_outline_self_corrects_hallucinated_type` — mock sequence: outline with `tool_type: "workshop"` → corrected outline with valid types → valid agenda → pipeline returns success with correct tool_types
- `test_e2e_agenda_self_corrects_empty_instructions` — mock sequence: valid outline → agenda with empty instructions → corrected agenda with instructions → success
- `test_e2e_parse_error_then_valid_json` — mock sequence: `"Sure! Here's your outline: {..."` (prose-wrapped) → clean JSON outline → valid agenda → success
- `test_e2e_all_retries_exhausted_returns_502` — mock sequence: 3 invalid outlines → endpoint returns 502, response body `detail` contains `"3 attempt(s)"` and the specific validation errors
- `test_e2e_provider_error_returns_502_no_retry` — mock `chat_complete` raises `AIProviderError` → 502 response, `chat_complete` called once (no retry attempted)
- `test_e2e_5_activity_pipeline_with_retry` — mock sequence: valid outline (5 activities) → invalid 5-activity agenda (one bad config key) → corrected 5-activity agenda → success, all 5 activities present
- `test_response_contract_unchanged_after_retry` — successful pipeline after retry → response keys are exactly `{success, meeting_summary, design_rationale, agenda}` — no retry metadata leaked to the frontend
- `test_chat_endpoint_unaffected_by_retry` — POST to `/api/meeting-designer/chat` → still works as SSE streaming, no retry logic involved
- `test_status_endpoint_unaffected_by_retry` — GET `/api/meeting-designer/status` → unchanged

**Docs:**
- Update `test_generation_pipeline.py` module docstring to reference `BRONZE-MERLIN-2` alongside `IRON-OSPREY-4`
- Ensure all new test functions have a one-line docstring explaining the retry scenario they verify

---

## Phase Exit Criteria

```bash
pytest app/tests/test_agenda_validator.py app/tests/test_meeting_designer_prompts.py app/tests/test_generation_pipeline.py -v
```

**All tests across all three files must pass at 100%.** No skips, no xfails. Phase 1, Phase 2, and Phase 3 tests must remain green — no regressions.
