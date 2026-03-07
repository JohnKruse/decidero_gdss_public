# Phase 3 [COMPLETE] — Two-Stage Generation Pipeline

> Global Canary: `BRASS-PELICAN-7`
> Phase Canary: `IRON-OSPREY-4`
> Source: `plans/01_MASTER_PLAN.md`, Phase 3
> Prerequisites: Phase 1 (`COPPER-HERON-3`), Phase 2 (`SILVER-FALCON-9`)
> Primary target file: `app/routers/meeting_designer.py`
> Secondary target: `app/services/agenda_validator.py` (outline validator addition)
> Target test file: `app/tests/test_generation_pipeline.py`

---

## Context

The current `generate_agenda()` endpoint makes a single `chat_complete()` call, parses the JSON, checks three fields, and returns. Phase 1 gave us a validation engine (`validate_agenda`) and Phase 2 gave us dynamic prompts (`build_outline_messages`, `build_generation_messages` with outline injection, `parse_outline_json`). Phase 3 composes them into a two-stage pipeline:

```
Stage 1: outline_messages → chat_complete → parse_outline_json → validate_outline
                                                                       │
                                                               fail → 502
                                                               pass ↓
Stage 2: generation_messages(outline) → chat_complete → parse_agenda_json → validate_agenda
                                                                                  │
                                                                          fail → 502
                                                                          pass → return
```

No retry logic (Phase 4). No frontend changes (Phase 5). The response shape to the frontend is unchanged: `{success, meeting_summary, design_rationale, agenda}`.

---

## Interfaces consumed (from Phase 1 and Phase 2)

```python
# Phase 1 — app/services/agenda_validator.py
validate_agenda(agenda_data: Dict[str, Any]) -> AgendaValidationResult
AgendaValidationResult: { valid: bool, errors: List[AgendaFieldError], warnings: List[AgendaFieldError] }
AgendaFieldError: { activity_index: int, field: str, message: str, level: "error"|"warning" }

# Phase 2 — app/services/meeting_designer_prompt.py
build_system_prompt() -> str
build_outline_messages(conversation_history: List[Dict]) -> List[Dict]
build_generation_messages(conversation_history: List[Dict], outline: Optional[List[Dict]] = None) -> List[Dict]
parse_outline_json(raw_text: str) -> Dict[str, Any]        # raises ValueError
parse_agenda_json(raw_text: str) -> Dict[str, Any]          # raises ValueError

# Existing — app/services/ai_provider.py
chat_complete(settings: Dict, messages: List[Dict], system_prompt: str) -> str  # async
AIProviderError, AIProviderNotConfiguredError
```

---

## Atomic Steps

### Step 1 [DONE] — `validate_outline()` in the validator module

The Phase 1 validator (`validate_agenda`) expects an `agenda` key and requires `instructions` as a non-empty field. Outlines use an `outline` key and deliberately omit `instructions` and `config_overrides`. Add a sibling function `validate_outline()` to `agenda_validator.py` that reuses the same catalog lookup and tool_type/duration/pattern checks but with the correct schema expectations.

**Implement** (in `app/services/agenda_validator.py`):

- `validate_outline(outline_data: Dict[str, Any]) -> AgendaValidationResult`
  - Envelope checks:
    - `outline` key must exist and be a non-empty list → error if missing/empty
    - `meeting_summary` must be a non-empty string → warning if missing
    - No `design_rationale` check (outlines don't have it)
  - Per-activity checks (iterate `outline_data["outline"]`):
    - `tool_type`: required, must be in live catalog → error (same as `validate_agenda`)
    - `title`: required, non-empty string → error (same)
    - `duration_minutes`: should be a positive number → warning if missing (same)
    - `collaboration_pattern`: should match plugin's declared patterns → warning (same)
    - `rationale`: should be non-empty → warning if missing
    - **No check for `instructions`** (not present in outlines)
    - **No check for `config_overrides`** (not present in outlines)
  - Returns `AgendaValidationResult` with same error/warning semantics as `validate_agenda`
  - Share the internal catalog-lookup and tool_type-checking logic with `validate_agenda()` if possible (extract a private helper) — but do not break the Phase 1 public API

**Test** (in `app/tests/test_agenda_validator.py` — extend the Phase 1 test file):

- `test_valid_outline_passes` — outline with 3 valid activities (tool_type, title, duration, pattern, rationale) → `valid is True`
- `test_outline_missing_outline_key` — input `{}` → `valid is False`
- `test_outline_empty_list` — input `{"outline": []}` → `valid is False`
- `test_outline_hallucinated_tool_type` — one activity with `tool_type: "roundtable"` → `valid is False`, error message lists valid types
- `test_outline_missing_title` — activity with no `title` → `valid is False`
- `test_outline_does_not_check_instructions` — activity with no `instructions` key → `valid is True` (no error, no warning for this field)
- `test_outline_does_not_check_config_overrides` — activity with no `config_overrides` → `valid is True`
- `test_outline_duration_out_of_range_warns` — brainstorming with `duration_minutes: 999` → `valid is True` with warning

**Docs:**
- Docstring on `validate_outline()`: "Validates an AI-generated outline (Stage 1 output) against the live activity catalog. Same validation logic as validate_agenda() but does not require instructions or config_overrides fields. Returns AgendaValidationResult."

**Technical deviations:**
- Implemented shared internal validation path via `_validate_activity_payload(...)` and `_build_catalog_lookup()` so `validate_agenda()` and `validate_outline()` reuse identical tool_type/duration/collaboration-pattern logic while toggling `instructions`/`config_overrides` requirements by mode.
- Existing repository test file is `app/tests/test_agenda_validator.py` (not `test_generation_pipeline.py` yet), so Step 1 tests were added there as directed by this step’s test section.
- Verification executed via `venv/bin/python -m pytest` because `pytest` is not on PATH in this environment.

---

### Step 2 [DONE] — Pipeline error class and validation-to-HTTP formatter

Define a structured error type for pipeline stage failures and a helper that converts `AgendaValidationResult` errors into a human-readable string suitable for both HTTP error details and future retry prompts (Phase 4).

**Implement** (in `app/routers/meeting_designer.py`):

- `class GenerationPipelineError(Exception)`
  - Attributes: `stage: str` (e.g. `"outline"`, `"full_json"`), `detail: str` (human-readable summary), `validation_errors: List[str]` (individual error messages), `raw_output: str` (first 500 chars of the AI's raw response, for logging)

- `_format_validation_errors(result: AgendaValidationResult, stage: str) -> GenerationPipelineError`
  - Extracts all errors from `result.errors` and formats each as: `"Activity {idx}: {field} — {message}"`
  - Builds a detail string: `"Stage '{stage}' failed validation with {N} error(s): {joined_errors}"`
  - Returns a `GenerationPipelineError` instance

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_pipeline_error_has_stage_and_detail` — instantiate `GenerationPipelineError` with stage="outline" → accessible via `.stage`, `.detail`
- `test_format_validation_errors_single_error` — create `AgendaValidationResult` with 1 error → formatted detail includes activity index and field name
- `test_format_validation_errors_multiple_errors` — result with 3 errors → detail includes all 3, count is correct
- `test_format_validation_errors_ignores_warnings` — result with 2 errors and 3 warnings → only errors appear in formatted output

**Docs:**
- Docstring on `GenerationPipelineError`: "Raised when a pipeline stage produces output that fails validation. Carries stage name, formatted error detail, individual error messages, and truncated raw output for logging."
- Docstring on `_format_validation_errors`: "Converts an AgendaValidationResult into a GenerationPipelineError with human-readable error messages."

**Technical deviations:**
- `_format_validation_errors()` formats entries as `"Activity {idx}: {field} - {message}"` using an ASCII hyphen to match repository style in validator messages; behavior is equivalent to the spec’s em dash separator.
- `GenerationPipelineError.raw_output` truncation to 500 chars is enforced in the exception constructor, so the guarantee holds for all call sites rather than depending on each caller to slice manually.

---

### Step 3 [DONE] — `_run_generation_pipeline()` — Stage 1 (outline)

Extract the generation logic from `generate_agenda()` into a standalone async function. Implement Stage 1: generate the outline, parse it, validate it, and return the validated outline or raise `GenerationPipelineError`.

**Implement** (in `app/routers/meeting_designer.py`):

- `async def _run_generation_pipeline(settings: Dict, history: List[Dict], system_prompt: str) -> Dict[str, Any]`
  - **Stage 1 — Outline:**
    1. `outline_messages = build_outline_messages(history)`
    2. `raw_outline = await chat_complete(settings, outline_messages, system_prompt)`
    3. `outline_data = parse_outline_json(raw_outline)` — if `ValueError`, raise `GenerationPipelineError(stage="outline", detail="...", raw_output=raw_outline[:500])`
    4. `outline_result = validate_outline(outline_data)` — if `not outline_result.valid`, raise via `_format_validation_errors(outline_result, "outline")` with `raw_output=raw_outline[:500]`
    5. Store `validated_outline = outline_data["outline"]` for Stage 2
  - Stage 2 is a stub for now: `return {"outline": validated_outline}` (completed in Step 4)

- `AIProviderError` and `AIProviderNotConfiguredError` are NOT caught here — they propagate up to the endpoint handler (same as today). The pipeline only catches parse/validation errors.

**Test** (in `app/tests/test_generation_pipeline.py`):

- All pipeline tests use `unittest.mock.AsyncMock` to mock `chat_complete`. The mock is patched at `app.routers.meeting_designer.chat_complete`.
- `test_stage1_valid_outline` — mock returns valid outline JSON → `_run_generation_pipeline` returns without error, result contains `"outline"` key
- `test_stage1_unparseable_json` — mock returns `"not json at all"` → raises `GenerationPipelineError` with `stage="outline"`
- `test_stage1_invalid_tool_type` — mock returns outline with `tool_type: "brainstorming_deluxe"` → raises `GenerationPipelineError`, detail mentions the invalid tool_type
- `test_stage1_missing_title` — mock returns outline with empty title → raises `GenerationPipelineError`
- `test_stage1_calls_chat_complete_once` — verify `chat_complete` was called exactly once (Stage 2 not yet implemented)

**Docs:**
- Docstring on `_run_generation_pipeline`: "Orchestrates the two-stage agenda generation pipeline. Stage 1 generates and validates an activity outline. Stage 2 generates and validates the full agenda JSON using the validated outline. Raises GenerationPipelineError on validation failure. AIProviderError propagates uncaught."

**Technical deviations:**
- At Step 3 completion, `_run_generation_pipeline()` returned `{"outline": validated_outline}` as an intentional Stage 2 stub; this was completed in Step 4.
- Parse-failure detail includes the original parser exception text (`Stage 'outline' produced invalid JSON: ...`) to improve diagnostics in current tests/logs.

---

### Step 4 [DONE] — `_run_generation_pipeline()` — Stage 2 (full JSON)

Complete the pipeline function by adding Stage 2: inject the validated outline into the generation prompt, call `chat_complete` a second time, parse, validate, and return the final agenda.

**Implement** (in `_run_generation_pipeline`, continuing from Step 3):

- **Stage 2 — Full JSON:**
  1. `generation_messages = build_generation_messages(history, outline=validated_outline)`
  2. `raw_agenda = await chat_complete(settings, generation_messages, system_prompt)`
  3. `agenda_data = parse_agenda_json(raw_agenda)` — if `ValueError`, raise `GenerationPipelineError(stage="full_json", ...)`
  4. `agenda_result = validate_agenda(agenda_data)` — if `not agenda_result.valid`, raise via `_format_validation_errors(agenda_result, "full_json")` with `raw_output=raw_agenda[:500]`
  5. Return the final response dict:
     ```python
     {
         "success": True,
         "meeting_summary": agenda_data.get("meeting_summary", ""),
         "design_rationale": agenda_data.get("design_rationale", ""),
         "agenda": agenda_data.get("agenda", []),
     }
     ```

- Log at INFO level: `"Outline stage passed (%d activities). Proceeding to full generation."` and `"Full generation stage passed. Returning %d validated activities."`
- Log warnings from both stages at DEBUG level (they don't block generation but are useful for prompt tuning)

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_stage2_valid_full_agenda` — mock `chat_complete` to return valid outline on first call, valid full agenda on second call → pipeline returns `{success: True, meeting_summary, design_rationale, agenda}` with correct values
- `test_stage2_unparseable_json` — first call returns valid outline, second returns garbage → raises `GenerationPipelineError(stage="full_json")`
- `test_stage2_hallucinated_tool_type` — first call valid, second call has `tool_type: "fishbowl"` → raises `GenerationPipelineError(stage="full_json")`, detail mentions "fishbowl"
- `test_stage2_empty_instructions` — first call valid, second call has activity with empty instructions → raises `GenerationPipelineError(stage="full_json")`
- `test_pipeline_calls_chat_complete_twice` — verify `chat_complete` was called exactly 2 times total (once for outline, once for full JSON)
- `test_pipeline_passes_outline_to_generation_messages` — capture the second `chat_complete` call's `messages` arg → the last message (generation prompt) contains the outline activity titles
- `test_response_shape_matches_original` — pipeline result has exactly the keys `success`, `meeting_summary`, `design_rationale`, `agenda` — no extras, no missing

**Docs:**
- Update `_run_generation_pipeline` docstring to describe both stages, including the outline-injection into Stage 2

**Technical deviations:**
- Stage parse-failure details include parser exception text for both outline and full JSON stages (`Stage '...' produced invalid JSON: ...`) to preserve diagnostic context.
- Existing Stage 3 test `test_stage1_calls_chat_complete_once` now validates two calls because Stage 2 is implemented in this step (name preserved for continuity with prior step history).

---

### Step 5 [DONE] — Rewire `generate_agenda()` endpoint

Replace the current single-call logic in `generate_agenda()` with a call to `_run_generation_pipeline()`. Map pipeline errors and provider errors to the correct HTTP responses. The response shape is unchanged.

**Implement** (in `app/routers/meeting_designer.py`):

- Update imports at module top: add `validate_agenda`, `validate_outline` from `agenda_validator`, add `build_outline_messages`, `parse_outline_json` from `meeting_designer_prompt`
- Rewrite `generate_agenda()` body:
  ```python
  _require_facilitator(user_manager, current_user)
  settings = get_meeting_designer_settings()
  history = [{"role": m.role, "content": m.content} for m in request.messages]
  system_prompt = build_system_prompt()

  try:
      return await _run_generation_pipeline(settings, history, system_prompt)
  except AIProviderNotConfiguredError as exc:
      raise HTTPException(status_code=503, detail="...") from exc
  except AIProviderError as exc:
      logger.error("AI provider error during generation: %s", exc)
      raise HTTPException(status_code=502, detail=f"AI provider error: {exc}") from exc
  except GenerationPipelineError as exc:
      logger.error("Pipeline stage '%s' failed: %s | Raw: %s", exc.stage, exc.detail, exc.raw_output)
      raise HTTPException(status_code=502, detail=exc.detail) from exc
  ```
- Remove the old inline parsing/validation logic (the `parse_agenda_json(raw)` call, the `"agenda" not in agenda_data` check, etc.) — all of that now lives in the pipeline function
- The old `try/except ValueError` for parse failures and the manual structure check are both replaced by the pipeline's `GenerationPipelineError`

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_endpoint_returns_200_on_valid_pipeline` — mock `chat_complete` for both stages, use `TestClient` to POST to `/api/meeting-designer/generate-agenda` → 200, body has `success: True`
- `test_endpoint_returns_502_on_outline_failure` — mock returns invalid outline → 502, response detail mentions "outline"
- `test_endpoint_returns_502_on_full_json_failure` — mock returns valid outline then invalid agenda → 502, response detail mentions "full_json"
- `test_endpoint_returns_503_when_not_configured` — mock `get_meeting_designer_settings` to return `enabled: False` → 503
- `test_endpoint_returns_502_on_provider_error` — mock `chat_complete` to raise `AIProviderError` → 502
- `test_chat_endpoint_unchanged` — POST to `/api/meeting-designer/chat` still works as before (SSE streaming, no pipeline involvement)

**Docs:**
- Update `generate_agenda()` docstring: "Generates a structured meeting agenda using a two-stage pipeline. Stage 1 produces and validates an activity outline. Stage 2 generates the full agenda JSON constrained by the validated outline. Returns the same response shape as the original single-stage implementation."

**Technical deviations:**
- `test_endpoint_returns_503_when_not_configured` simulates the not-configured path by making `_run_generation_pipeline()` raise `AIProviderNotConfiguredError`; this validates endpoint mapping behavior without coupling the test to provider internals.
- Endpoint audit logging now stores the conversation `history` and final `result` payload for generate-agenda requests; Stage-level raw outputs remain captured on `GenerationPipelineError` via `exc.raw_output`.

---

### Step 6 [DONE] — End-to-end integration tests and regression guards

Verify the complete pipeline with realistic multi-activity agendas, confirm the response contract is identical to the pre-Phase 3 contract, and ensure no regressions to chat or status endpoints.

**Implement:**

- Create test fixtures in `test_generation_pipeline.py`:
  - `_valid_outline_json(n=3)` — returns a raw JSON string representing a valid n-activity outline (uses real tool_types from the live registry)
  - `_valid_agenda_json(n=3)` — returns a raw JSON string representing a valid n-activity full agenda matching the outline's sequence
  - `_mock_chat_complete_two_stage(outline_json, agenda_json)` — returns an `AsyncMock` whose `side_effect` returns `outline_json` on the first call and `agenda_json` on the second

**Test:**

- `test_e2e_5_activity_pipeline` — mock both stages with a 5-activity classic sequence (brainstorming → categorization → voting → rank_order_voting → voting) → pipeline returns valid result with 5 activities, all tool_types match the outline
- `test_e2e_1_activity_pipeline` — minimal case: 1-activity outline and agenda → works correctly
- `test_response_contract_unchanged` — compare the JSON response keys and types against the original contract: `success` (bool), `meeting_summary` (str), `design_rationale` (str), `agenda` (list of dicts with `tool_type`, `title`, `instructions`, `duration_minutes`, `collaboration_pattern`, `rationale`, `config_overrides`)
- `test_status_endpoint_unaffected` — GET `/api/meeting-designer/status` → still returns `StatusResponse` (no pipeline involvement)
- `test_pipeline_error_detail_is_actionable` — trigger a validation failure, inspect the 502 response detail → confirm it names the specific stage, activity index, and field that failed (not a generic "please try again")
- `test_system_prompt_built_once_per_request` — monkeypatch `build_system_prompt` to count calls → verify it's called exactly once per `generate_agenda()` invocation (same prompt instance passed to both `chat_complete` calls)

**Docs:**
- Add module docstring to `test_generation_pipeline.py` referencing `BRASS-PELICAN-7` and `IRON-OSPREY-4`
- Ensure all test functions have a one-line docstring explaining what they verify

**Technical deviations:**
- `_valid_outline_json(n)` and `_valid_agenda_json(n)` use a deterministic in-test tool sequence (brainstorming/categorization/voting/rank_order_voting/voting) rather than querying the live catalog at runtime, keeping E2E tests stable and deterministic.
- One-line docstrings were added for new Step 6 tests and retained prior test coverage; existing earlier tests in `test_generation_pipeline.py` predated this step and were left unchanged to avoid non-functional churn.
- Phase-wide verification was run with `venv/bin/python -m pytest -q` (full suite) and passed (`392 passed, 2 skipped`); repository baseline includes skipped tests unrelated to this phase.

---

## Phase Exit Criteria

```bash
pytest app/tests/test_agenda_validator.py app/tests/test_meeting_designer_prompts.py app/tests/test_generation_pipeline.py -v
```

**All tests across all three files must pass at 100%.** No skips, no xfails. Phase 1 and Phase 2 tests must remain green — no regressions.
