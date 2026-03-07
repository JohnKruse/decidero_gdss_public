# Phase 5 [COMPLETE] — Integration and Hardening

> Global Canary: `BRASS-PELICAN-7`
> Phase Canary: `STEEL-KINGFISHER-5`
> Source: `plans/01_MASTER_PLAN.md`, Phase 5
> Prerequisites: Phase 1 (`COPPER-HERON-3`), Phase 2 (`SILVER-FALCON-9`), Phase 3 (`IRON-OSPREY-4`), Phase 4 (`BRONZE-MERLIN-2`)
> Primary target files: `app/templates/meeting_designer.html`, `app/templates/create_meeting.html`, `app/routers/meeting_designer.py`
> Target test file: `app/tests/test_generation_pipeline.py` (extended)

---

## Context

Phases 1–4 built the backend pipeline: validation engine, dynamic prompts, two-stage generation, and retry with error feedback. The `generate_agenda()` endpoint now produces validated, retry-hardened agenda JSON. But the frontend is still wired for the old single-shot world:

- The loading spinner says "Generating agenda…" with no sense of multi-stage progress
- Error messages show raw backend detail strings that are too technical for facilitators
- `create_meeting.html` silently swallows sessionStorage parse failures (H2 from discovery)
- The default `max_tokens=2048` can truncate large agendas (C2 from discovery)
- No pipeline metadata reaches the frontend (retry counts, timing)

Phase 5 closes these gaps. **No new architectural changes** — just frontend polish, edge case fixes, and end-to-end verification.

### Scope boundary

- `meeting_designer.html`: progress messaging, error display
- `create_meeting.html`: sessionStorage hardening
- `meeting_designer.py`: pipeline metadata in response, max_tokens scaling
- No new endpoints. No new modules. No changes to the pipeline's internal flow.

---

## Interfaces consumed (from Phases 1–4)

```python
# Phase 3–4 — app/routers/meeting_designer.py
_run_generation_pipeline(settings, history, system_prompt) -> Dict  # async
# Returns: {success, meeting_summary, session_name, evaluation_criteria,
#           design_rationale, complexity, phases, agenda}
GenerationPipelineError: { stage, detail, validation_errors, raw_output,
                           attempts_made, error_trail }

# Phase 4 — retry constants
_OUTLINE_MAX_ATTEMPTS = 3
_AGENDA_MAX_ATTEMPTS = 2

# Existing — app/services/ai_provider.py
chat_complete(settings: Dict, messages, system_prompt) -> str
# settings dict includes: provider, model, api_key, max_tokens, temperature, ...

# Existing — app/config/loader.py
get_meeting_designer_settings() -> Dict
# Returns: {enabled, provider, model, api_key, max_tokens, temperature, ...}
# max_tokens default: 2048
```

### Frontend current state

```
meeting_designer.html:
  - Generate button click → POST /api/meeting-designer/generate-agenda
  - Spinner: <div id="mdAgendaLoading"> with "Generating agenda…"
  - Error handler: appendSystemMessage(`Failed to generate agenda: ${err.detail || resp.statusText}`)
  - sessionStorage write: try/catch with appendSystemMessage on failure (already handled)

create_meeting.html:
  - sessionStorage read: try/catch with SILENT catch (no error shown)
  - config_overrides → config rename at line 1705
  - Success banner: green "AI Meeting Designer agenda loaded — N activities pre-filled"
```

---

## Atomic Steps

### Step 1 [DONE] — Pipeline response metadata

Add a `_pipeline_meta` dict to the `generate_agenda()` response. The frontend can optionally display this (timing, retry info). This is additive — the existing contract (`success`, `meeting_summary`, etc.) is unchanged; the underscore-prefixed key signals it's informational.

**Implement** (in `app/routers/meeting_designer.py`):

- Modify `_run_generation_pipeline()` to track and return pipeline metadata alongside the agenda data:
  - `outline_attempts: int` — how many attempts Stage 1 took (1 = first try)
  - `agenda_attempts: int` — how many attempts Stage 2 took
  - `total_seconds: float` — wall-clock time for the full pipeline (from `time.monotonic()` delta, rounded to 1 decimal)
  - `outline_activity_count: int` — number of activities in the validated outline

- To capture attempt counts, modify `_run_stage_with_retry()` to return a tuple `(parsed_data, attempts_used)` instead of just `parsed_data`. The `attempts_used` is `i + 1` where `i` is the loop index at which validation succeeded. This is a small internal API change within the pipeline — callers unpack the tuple.

- In `_run_generation_pipeline()`, unpack the stage runner results and build the metadata:
  ```python
  outline_data, outline_attempts = await _run_stage_with_retry(...)
  # ... Stage 2 ...
  agenda_data, agenda_attempts = await _run_stage_with_retry(...)

  total_seconds = round(time.monotonic() - start_time, 1)
  ```

- Add `_pipeline_meta` to the returned dict:
  ```python
  return {
      "success": True,
      "meeting_summary": ...,
      "session_name": ...,
      "evaluation_criteria": ...,
      "design_rationale": ...,
      "complexity": ...,
      "phases": ...,
      "agenda": ...,
      "_pipeline_meta": {
          "outline_attempts": outline_attempts,
          "agenda_attempts": agenda_attempts,
          "outline_activity_count": len(validated_outline),
          "total_seconds": total_seconds,
      },
  }
  ```

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_stage_runner_returns_attempt_count` — mock succeeds on first attempt → returns `(parsed_data, 1)`
- `test_stage_runner_returns_attempt_count_after_retry` — mock succeeds on second attempt → returns `(parsed_data, 2)`
- `test_pipeline_meta_present_in_response` — successful pipeline → response contains `_pipeline_meta` key with all 4 subkeys
- `test_pipeline_meta_attempt_counts_correct` — pipeline with 1 outline retry → `_pipeline_meta.outline_attempts == 2`, `_pipeline_meta.agenda_attempts == 1`
- `test_pipeline_meta_total_seconds_is_number` — `_pipeline_meta.total_seconds` is a float ≥ 0
- `test_pipeline_meta_outline_activity_count` — 4-activity outline → `_pipeline_meta.outline_activity_count == 4`
- `test_original_response_keys_unchanged` — response still has all original keys (`success`, `meeting_summary`, `session_name`, `evaluation_criteria`, `design_rationale`, `complexity`, `phases`, `agenda`)

**Docs:**
- Docstring update on `_run_stage_with_retry`: note the return type change to `Tuple[Dict, int]`
- Docstring update on `_run_generation_pipeline`: document `_pipeline_meta` in the return dict
- Inline comment on `_pipeline_meta`: `"# Informational metadata for frontend display; not part of the agenda contract"`

**Technical deviations (Step 1):**
- Added the full enriched response keys (`session_name`, `evaluation_criteria`, `complexity`, `phases`) in `_run_generation_pipeline()` alongside `_pipeline_meta` because the live frontend already consumes these fields and Step 1 requires preserving the existing contract while adding metadata.
- Verification command `venv/bin/python -m pytest -q` completed with `440 passed, 2 skipped`; the two skips are existing repository baseline skips (not introduced by Step 1 changes).

---

### Step 2 [DONE] — Dynamic max_tokens scaling for Stage 2

After Stage 1 produces a validated outline, estimate the token budget needed for Stage 2 and scale `max_tokens` upward if the default is too small. This addresses discovery risk C2 (truncated JSON from token exhaustion on large agendas).

**Implement** (in `app/routers/meeting_designer.py`):

- Add a helper function:
  ```python
  def _estimate_stage2_max_tokens(activity_count: int, base_max_tokens: int) -> int:
  ```
  - Each activity in the full JSON needs roughly 250–350 tokens (tool_type, title, instructions, duration, collaboration_pattern, rationale, config_overrides, phase_id, track_id)
  - Envelope overhead (meeting_summary, session_name, evaluation_criteria, design_rationale, complexity, phases array): ~400 tokens
  - Safety multiplier: 1.5x to account for verbose instructions and complex config
  - Formula: `estimated = int((activity_count * 300 + 400) * 1.5)`
  - Return: `max(base_max_tokens, estimated)` — never shrink below the configured default
  - Floor: always return at least `base_max_tokens` (respect user config)
  - Ceiling: cap at `16384` to avoid runaway token usage on pathological outlines

- In `_run_generation_pipeline()`, after Stage 1 produces the validated outline:
  ```python
  scaled_max_tokens = _estimate_stage2_max_tokens(
      len(validated_outline),
      settings.get("max_tokens", 2048),
  )
  stage2_settings = {**settings, "max_tokens": scaled_max_tokens}
  ```
  - Pass `stage2_settings` (not the original `settings`) to Stage 2's `_run_stage_with_retry()` call
  - Log the scaling: `logger.info("Stage 2 max_tokens: %d (base: %d, activities: %d)", scaled_max_tokens, settings.get("max_tokens", 2048), len(validated_outline))`

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_estimate_tokens_small_agenda` — 2 activities, base=2048 → returns 2048 (base is sufficient)
- `test_estimate_tokens_large_agenda` — 8 activities, base=2048 → returns value > 2048 (scaling kicks in)
- `test_estimate_tokens_never_shrinks` — 1 activity, base=4096 → returns 4096 (base preserved)
- `test_estimate_tokens_ceiling` — 100 activities, base=2048 → returns 16384 (cap enforced)
- `test_pipeline_passes_scaled_tokens_to_stage2` — monkeypatch `_estimate_stage2_max_tokens`, verify that the Stage 2 `chat_complete` call receives settings with the scaled `max_tokens` value (inspect mock call args)
- `test_pipeline_stage1_uses_original_tokens` — verify Stage 1 `chat_complete` call uses the original `max_tokens` from settings (outline is always small, no scaling needed)

**Docs:**
- Docstring on `_estimate_stage2_max_tokens`: "Estimates the minimum max_tokens needed for Stage 2 full JSON generation based on the validated outline's activity count. Returns the larger of the base max_tokens and the estimate, capped at 16384. Formula: (activity_count × 300 + 400) × 1.5."
- Inline comment: `"# Scaling addresses discovery risk C2 — token exhaustion on large agendas"`

**Technical deviations (Step 2):**
- Implemented the docstring formula using ASCII `x` (`(activity_count x 300 + 400) x 1.5`) instead of the multiplication symbol to keep source ASCII-only.
- `base_max_tokens` is normalized via `int(settings.get("max_tokens", 2048) or 2048)` before scaling to avoid `None`/falsey config values causing type errors in max/estimate comparison.
- Verification command `venv/bin/python -m pytest -q` completed with `446 passed, 2 skipped`; the two skips remain baseline repository skips unrelated to Step 2.

---

### Step 3 [DONE] — Frontend multi-stage progress messaging

Update `meeting_designer.html` to show stage-aware progress text during generation. Since the endpoint is a single POST → JSON response (not SSE), real-time stage tracking isn't possible without an architectural change. Instead, cycle the spinner text on a timer to give the facilitator a sense of progress. After completion, optionally display pipeline metadata.

**Implement** (in `app/templates/meeting_designer.html`):

- Update the spinner HTML (`#mdAgendaLoading`):
  - Change the static `<span>Generating agenda…</span>` to `<span id="mdAgendaStatus">Analyzing conversation…</span>`

- In the generate button click handler, add a progress text cycler:
  ```javascript
  const statusEl = document.getElementById('mdAgendaStatus');
  const stages = [
      'Analyzing conversation…',
      'Generating activity outline…',
      'Validating outline…',
      'Building full agenda…',
      'Validating activities…',
  ];
  let stageIdx = 0;
  const progressInterval = setInterval(() => {
      stageIdx = Math.min(stageIdx + 1, stages.length - 1);
      statusEl.textContent = stages[stageIdx];
  }, 6000);  // advance every 6 seconds
  ```
  - Clear the interval when the response arrives (success or error):
    ```javascript
    clearInterval(progressInterval);
    ```

- After successful generation, if `_pipeline_meta` is present in the response:
  - Show a subtle info line under the agenda summary:
    ```javascript
    if (data._pipeline_meta) {
        const meta = data._pipeline_meta;
        const retries = (meta.outline_attempts - 1) + (meta.agenda_attempts - 1);
        const info = retries > 0
            ? `Generated in ${meta.total_seconds}s (${retries} correction${retries > 1 ? 's' : ''} needed)`
            : `Generated in ${meta.total_seconds}s`;
        // Append as a small muted text element below the summary
    }
    ```

**Test** (frontend changes — verified via manual testing, documented in this step):

- Manual verification checklist:
  - [ ] Spinner text starts at "Analyzing conversation…" when Generate clicked
  - [ ] Text cycles through stages every ~6 seconds
  - [ ] Text stops cycling when response arrives
  - [ ] On success, pipeline meta info line appears below summary (if retries occurred)
  - [ ] On error, text cycling stops and error message displays
  - [ ] Spinner text resets to first stage if Generate is clicked again

- Backend test (in `app/tests/test_generation_pipeline.py`):
  - `test_pipeline_meta_in_endpoint_response` — POST to `/api/meeting-designer/generate-agenda` with mocked pipeline → 200 response body contains `_pipeline_meta`

**Docs:**
- Add an inline comment in the JS: `// Progress text cycles on a timer since the endpoint is a single POST, not SSE`
- Comment explaining the 6-second interval choice: `// ~6s per stage ≈ 30s total cycle, aligns with typical generation time`

**Technical deviations (Step 3):**
- Added a dedicated `.md-agenda-meta` style in `app/static/css/meeting_designer.css` to ensure the pipeline metadata line is visually subtle under the summary, rather than relying on inline style attributes.
- Manual browser validation checklist is documented but not executed in this terminal-only pass; automated verification was performed via backend tests and full pytest.
- Verification command `venv/bin/python -m pytest -q` completed with `447 passed, 2 skipped`; the two skips remain baseline repository skips unrelated to Step 3.

---

### Step 4 [DONE] — Frontend structured error display for generation failures

Update `meeting_designer.html` to parse the 502 detail string from the pipeline and display a user-friendly error panel instead of a raw system message. The pipeline error detail from Phase 4 is machine-readable (stage name + error list), so the frontend can format it.

**Implement** (in `app/templates/meeting_designer.html`):

- Replace the current error handler in the generate button click handler:
  ```javascript
  // BEFORE (existing):
  if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      appendSystemMessage(`Failed to generate agenda: ${err.detail || resp.statusText}`);
      ...
  }

  // AFTER:
  if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const detail = err.detail || resp.statusText;
      if (resp.status === 502 && detail.includes('attempt(s)')) {
          // Pipeline validation failure — show structured error
          _showGenerationError(detail);
      } else {
          appendSystemMessage(`Failed to generate agenda: ${detail}`);
      }
      ...
  }
  ```

- Add a `_showGenerationError(detail)` function:
  - Parse the detail string to extract: stage name, attempt count, individual error messages
  - Display an error panel in the agenda panel area (where the spinner was) with:
    - A clear heading: "Agenda generation failed" (not the raw detail)
    - Which stage failed: "The AI could not produce a valid [outline / agenda]"
    - How many attempts: "after 3 attempts"
    - The specific issues as a bullet list (e.g., "Activity 0: tool_type 'workshop' is not registered")
    - A "Try Again" button that re-triggers the generate flow
  - Style: error-themed (red/orange border, warning icon) but not alarming

- Ensure the "Try Again" button clears the error panel and re-calls the generate flow (same as clicking the Generate button)

**Test** (frontend changes — verified via manual testing, documented in this step):

- Manual verification checklist:
  - [ ] 502 with pipeline validation detail → structured error panel appears (not a system message)
  - [ ] Error panel shows stage name, attempt count, and individual errors as bullets
  - [ ] "Try Again" button works and triggers a fresh generation attempt
  - [ ] 502 without pipeline detail (e.g., provider error) → falls back to system message
  - [ ] 503 (not configured) → still shows system message as before
  - [ ] Error panel is cleared when a new generation attempt starts

- Backend test (in `app/tests/test_generation_pipeline.py`):
  - `test_502_detail_contains_stage_and_attempts` — trigger pipeline failure via endpoint → 502 response detail contains the stage name and attempt count (confirms the detail format the frontend parses)
  - `test_502_detail_contains_individual_errors` — trigger validation failure → detail contains specific field errors (e.g., "tool_type", "instructions")

**Docs:**
- Inline JS comment: `// Parses Phase 4 pipeline error detail format: "Stage '{stage}' failed validation after {N} attempt(s) with {M} error(s): ..."`

**Technical deviations (Step 4):**
- Implemented the "Try Again" behavior by refactoring the generate click handler into a reusable `handleGenerateAgenda()` function and wiring both the main Generate button and panel retry button to it.
- Added dedicated error-panel styles in `app/static/css/meeting_designer.css` to keep the warning appearance consistent and avoid large inline style blocks in JS-generated HTML.
- Manual frontend checklist is documented but not executed in this terminal-only pass; automated verification covered backend detail format tests plus full pytest.
- Verification command `venv/bin/python -m pytest -q` completed with `449 passed, 2 skipped`; the two skips remain baseline repository skips unrelated to Step 4.

---

### Step 5 [DONE] — sessionStorage handoff hardening

Fix the silent catch in `create_meeting.html` that swallows sessionStorage parse failures (discovery risk H2). Replace it with an explicit error message so the facilitator knows something went wrong and can return to the designer.

**Implement** (in `app/templates/create_meeting.html`):

- Replace the silent catch block:
  ```javascript
  // BEFORE:
  } catch (e) {
      // Non-critical; ignore storage/parse errors silently
      sessionStorage.removeItem('md_agenda');
  }

  // AFTER:
  } catch (e) {
      sessionStorage.removeItem('md_agenda');
      const errBanner = document.createElement('div');
      errBanner.id = 'mdHandoffError';
      errBanner.style.cssText = [
          'background:#fff3e0', 'color:#e65100', 'padding:0.65rem 1.25rem',
          'border-radius:8px', 'font-size:0.85rem', 'font-weight:600',
          'margin-bottom:1rem', 'display:flex', 'align-items:center', 'gap:0.5rem',
      ].join(';');
      errBanner.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm-.75 4a.75.75 0 011.5 0v3.5a.75.75 0 01-1.5 0V5zm.75 6.5a.75.75 0 110-1.5.75.75 0 010 1.5z"/>
          </svg>
          Could not load the AI-designed agenda. The data may have been cleared by your browser.
          <a href="/meeting-designer" style="color:#e65100;text-decoration:underline;margin-left:0.5rem;">
            Return to Meeting Designer
          </a>
          <button onclick="this.parentElement.remove()" style="margin-left:auto;background:none;border:none;color:#e65100;cursor:pointer;font-size:1rem;">×</button>
      `;
      const form = document.getElementById('createMeetingForm');
      if (form) form.prepend(errBanner);
  }
  ```
  - Orange warning style (not red error — it's recoverable)
  - Link back to `/meeting-designer` so the facilitator can regenerate
  - Dismissible with × button (same pattern as the success banner)

- Add a size guard before the sessionStorage write in `meeting_designer.html`:
  ```javascript
  // Before sessionStorage.setItem:
  const payload = JSON.stringify(state.agendaData);
  if (payload.length > 4 * 1024 * 1024) {
      appendSystemMessage('Agenda is too large to transfer. Try reducing the number of activities.');
      return;
  }
  sessionStorage.setItem('md_agenda', payload);
  ```
  - sessionStorage has a ~5MB limit per origin. A 4MB guard gives headroom.

**Test** (frontend changes — verified via manual testing, documented in this step):

- Manual verification checklist:
  - [ ] Corrupt/missing sessionStorage → orange warning banner appears on create_meeting page
  - [ ] Banner includes "Return to Meeting Designer" link
  - [ ] Banner is dismissible with × button
  - [ ] Normal flow still works: designer → create → green success banner
  - [ ] Oversized agenda (>4MB) shows error on designer page, does not navigate

- Backend test (in `app/tests/test_generation_pipeline.py`):
  - `test_generate_agenda_response_is_json_serializable` — successful pipeline response → entire response dict is JSON-serializable (verifies sessionStorage compatibility)

**Docs:**
- Inline JS comment on the catch block: `// H2 fix: explicit error replaces silent swallow (discovery risk H2)`
- Inline JS comment on the size guard: `// Guard against sessionStorage quota (~5MB per origin)`

**Technical deviations (Step 5):**
- Error banner injection targets `#createMeetingForm` first and falls back to the first `<form>` element to remain compatible with current template structure and avoid silent failures if IDs change.
- The oversized-payload guard is applied to the single-meeting handoff path (`sessionStorage.setItem('md_agenda', payload)`); multi-track creation flow is unchanged because it does not use this handoff key.
- Manual frontend checklist is documented but not executed in this terminal-only pass; automated verification covered new JSON-serializable response test plus full pytest.
- Verification command `venv/bin/python -m pytest -q` completed with `450 passed, 2 skipped`; the two skips remain baseline repository skips unrelated to Step 5.

---

### Step 6 [DONE] — End-to-end integration tests and regression guards

Verify the complete pipeline with realistic multi-activity agendas, confirm pipeline metadata and max_tokens scaling work together, and ensure no regressions to chat, status, logs, or manual meeting creation paths.

**Implement:**

- Create test helpers in `test_generation_pipeline.py`:
  - `_valid_6_activity_outline_json()` — returns raw JSON string for a 6-activity outline using real tool_types from the live registry (brainstorming → categorization → voting → brainstorming → rank_order_voting → voting)
  - `_valid_6_activity_agenda_json()` — returns a matching 6-activity full agenda with session_name, evaluation_criteria, complexity, phases, and all per-activity fields

**Test** (in `app/tests/test_generation_pipeline.py`):

- `test_e2e_6_activity_agenda_succeeds` — mock both stages with 6-activity fixture → pipeline returns success, all 6 activities present, all tool_types valid, `_pipeline_meta` present
- `test_e2e_6_activity_with_retry_and_metadata` — mock outline fails once then succeeds, agenda succeeds → `_pipeline_meta.outline_attempts == 2`, `_pipeline_meta.agenda_attempts == 1`
- `test_e2e_max_tokens_scaled_for_large_agenda` — 6-activity outline → verify `chat_complete` Stage 2 call received settings with `max_tokens` > 2048
- `test_e2e_max_tokens_not_scaled_for_small_agenda` — 2-activity outline with base max_tokens=4096 → Stage 2 receives max_tokens=4096 (no shrink)
- `test_e2e_pipeline_meta_not_leaked_to_audit_log` — verify `_persist_meeting_designer_log` is called with `parsed_output` that contains the agenda data (the meta is for the response only, not the audit log)
- `test_chat_endpoint_unaffected` — POST to `/api/meeting-designer/chat` → still SSE, no pipeline involvement
- `test_status_endpoint_unaffected` — GET `/api/meeting-designer/status` → still returns `StatusResponse`
- `test_logs_endpoint_unaffected` — GET `/api/meeting-designer/logs` → still returns audit records
- `test_response_contract_backward_compatible` — successful pipeline response has all keys from the original contract (`success`, `meeting_summary`, `session_name`, `evaluation_criteria`, `design_rationale`, `complexity`, `phases`, `agenda`) plus `_pipeline_meta` — no keys removed, no keys renamed

**Docs:**
- Update `test_generation_pipeline.py` module docstring to reference `STEEL-KINGFISHER-5` alongside `IRON-OSPREY-4` and `BRONZE-MERLIN-2`
- Ensure all new test functions have a one-line docstring
- Add a comment block at the top of the Phase 5 test section: `"# Phase 5 (STEEL-KINGFISHER-5): Integration, hardening, and end-to-end verification"`

**Technical deviations (Step 6):**
- Added the requested 6-activity helpers/tests and backward-compatibility coverage while keeping existing earlier-phase regression tests in place (no removals), resulting in broader overlap than the minimum Step 6 list.
- Implemented a small backend hardening change in `generate_agenda()` so `_pipeline_meta` remains response-only and is excluded from persisted `parsed_output` audit logs, matching Step 6 intent for metadata scoping.
- Manual verification checklist is documented but not executed in this terminal-only pass; automated verification covered the expanded pipeline/regression suite plus full pytest.
- Verification command `venv/bin/python -m pytest -q` completed with `456 passed, 2 skipped`; the two skips remain baseline repository skips unrelated to Step 6.

---

## Phase Exit Criteria

### Automated gate

```bash
pytest app/tests/test_agenda_validator.py app/tests/test_meeting_designer_prompts.py app/tests/test_generation_pipeline.py -v
```

**All tests across all three files must pass at 100%.** No skips, no xfails. Phase 1–4 tests must remain green — no regressions.

### Manual verification gate

The following must be verified by a facilitator-role user in a running instance:

- [ ] Generate a 6-activity agenda end-to-end: conversation → generate → review → create meeting → meeting loads with all 6 activities
- [ ] Progress text cycles during generation (not stuck on "Generating agenda…")
- [ ] Pipeline metadata info line appears after successful generation
- [ ] Trigger a generation failure → structured error panel appears with stage name, attempt count, and specific errors
- [ ] "Try Again" button in error panel works
- [ ] Corrupt sessionStorage before navigating to create_meeting → orange warning banner appears with "Return to Meeting Designer" link
- [ ] Normal designer → create flow shows green success banner (no regression)
- [ ] Chat endpoint still works (send messages, receive streaming responses)
- [ ] Settings page AI configuration still works
- [ ] Manual meeting creation (without designer) still works
