# 01_MASTER_PLAN: AI Meeting Designer — Generation Pipeline Redesign

> Derived from: `plans/00_DISCOVERY.md`
> Branch: `settings-page-dev`
> Date: 2026-03-07

---

## Global Canary

```
BRASS-PELICAN-7
```

All phase plans, commits, and test artifacts for this project must reference this codeword. If a phase plan does not contain `BRASS-PELICAN-7`, it is orphaned and must not be executed.

---

## Strategic Phases

### Phase 1 — Validation Engine

Build a programmatic validation layer that can judge AI-generated agenda output against the live activity catalog. Until the system can express what "valid" means in code, no downstream work (multi-stage, retry) has a foundation.

**Addresses:** C1 (hallucinated tool_type), C3 (empty/nonsensical activities), M1 (config surface gap), discovery sections 5 and 7.

**Scope boundary:** Validation module only. No changes to the generation pipeline, prompts, or frontend. The validator is a pure function: JSON in, verdict out.

#### Success Gate

- [ ] A function exists that accepts raw AI agenda JSON and returns a structured result: list of per-activity errors/warnings, overall pass/fail
- [ ] Validation checks tool_type against the live plugin registry (not a hardcoded list)
- [ ] Validation checks required field presence: `tool_type`, `title`, `instructions` (non-empty)
- [ ] Validation checks config_overrides keys against the plugin's `default_config` (unknown keys flagged)
- [ ] Validation checks `duration_minutes` against `typical_duration_minutes` from catalog (out-of-range flagged as warning, not error)
- [ ] Validation checks `collaboration_pattern` against the plugin's declared `collaboration_patterns`
- [ ] Unit tests pass with synthetic valid and invalid agenda payloads covering each check
- [ ] Validator imports only from `activity_catalog.py` and standard library — no coupling to router, prompt, or provider layers

---

### Phase 2 — Dynamic Prompt Construction

Replace hardcoded content in `GENERATE_AGENDA_PROMPT` with catalog-driven generation. Build the outline prompt as a new artifact. Both prompts must be impossible to desync from the plugin registry.

**Addresses:** H4 (static GENERATE_AGENDA_PROMPT), discovery section 6 (all hardcoded assumptions in prompt), section 7 (config schema gap).

**Scope boundary:** `meeting_designer_prompt.py` only. No changes to the generation endpoint, retry logic, or frontend. Existing `build_system_prompt()` pattern is the template — extend, don't replace.

#### Success Gate

- [ ] `GENERATE_AGENDA_PROMPT` is replaced by a function `build_generation_prompt()` that reads tool_types, config keys, and duration ranges from the enriched catalog at call time
- [ ] A new `build_outline_prompt()` function exists that asks the AI for a lightweight sequence plan (tool_type, title, duration, rationale per activity — no instructions or config)
- [ ] Neither prompt function contains any hardcoded tool_type string (`brainstorming`, `voting`, etc.)
- [ ] Adding a hypothetical 5th plugin to the registry automatically appears in both prompts without code changes
- [ ] `build_generation_messages()` and a new `build_outline_messages()` work correctly with conversation history
- [ ] Existing `parse_agenda_json()` still parses the full-JSON stage output (contract unchanged)
- [ ] A new `parse_outline_json()` function exists for the outline stage output
- [ ] All existing chat behavior is unaffected (system prompt, conversation flow unchanged)

---

### Phase 3 — Two-Stage Generation Pipeline

Replace the single `chat_complete()` call in `generate_agenda()` with a two-stage pipeline: outline generation → outline validation → full JSON generation → full JSON validation. The validation engine from Phase 1 and prompts from Phase 2 are composed here.

**Addresses:** C1, C2, C3 (all critical risks), H1 (single-shot brittleness), discovery section 4 (current pipeline).

**Scope boundary:** `meeting_designer.py` endpoint restructure. Uses Phase 1 validator and Phase 2 prompts. No retry logic yet (that is Phase 4). No frontend changes.

#### Success Gate

- [ ] `generate_agenda()` makes two sequential `chat_complete()` calls: outline, then full JSON
- [ ] Outline output is validated by Phase 1 validator before proceeding to full JSON generation
- [ ] Full JSON output is validated by Phase 1 validator before returning to the client
- [ ] If outline validation fails, the endpoint returns a 502 with specific error details (not a generic message)
- [ ] If full JSON validation fails, the endpoint returns a 502 with specific error details
- [ ] The validated outline is injected into the full-JSON prompt so the AI has a locked-in structure to elaborate
- [ ] Response shape to the frontend is unchanged: `{success, meeting_summary, design_rationale, agenda}`
- [ ] End-to-end: a facilitator can converse with the designer, click Generate, and receive a validated agenda that creates a meeting without errors

---

### Phase 4 — Retry with Error Feedback

Add automatic retry at each pipeline stage. When validation fails, the specific errors are fed back to the AI as a correction prompt and the stage is re-attempted. Configurable attempt limits.

**Addresses:** H1 (no retry mechanism), discovery section 9 (error handling & recovery).

**Scope boundary:** Retry logic inside `generate_agenda()`. No frontend changes beyond what the existing error display already handles. No new endpoints.

#### Success Gate

- [ ] Outline stage: up to 2 retries (3 total attempts) with validation errors appended as a user message before each retry
- [ ] Full JSON stage: 1 retry (2 total attempts) with validation errors appended
- [ ] Retry prompt includes the specific validation errors (e.g., "tool_type 'discussion' is not registered; available types are: brainstorming, voting, rank_order_voting, categorization")
- [ ] If all retries are exhausted, the endpoint returns a 502 with the final validation errors
- [ ] Retry count and error details are logged at INFO level for each attempt
- [ ] No retry on non-recoverable errors (AI not configured, network failure, auth error) — only on validation failures
- [ ] Total wall-clock time for a full retry sequence stays under the 90s read timeout

---

### Phase 5 — Integration and Hardening

Connect the new pipeline to the frontend. Ensure the end-to-end flow works across all supported providers. Handle edge cases surfaced by the discovery audit.

**Addresses:** H2 (sessionStorage failure), C2 (token exhaustion), remaining moderate risks, discovery section 13 (potential additions).

**Scope boundary:** Frontend updates to `meeting_designer.html`, logging improvements, edge case fixes. No new architectural changes.

#### Success Gate

- [ ] Frontend displays a progress indicator during multi-stage generation (not a blank wait)
- [ ] Frontend shows validation-specific error messages when generation fails (not just "please try again")
- [ ] sessionStorage handoff failure displays an explicit error message instead of silently failing
- [ ] Generation works end-to-end with at least 2 different AI providers (e.g., Anthropic + OpenAI)
- [ ] A 6-activity meeting agenda can be generated, validated, and created as a meeting without errors
- [ ] Structured logging captures: stage entered, stage result (pass/fail), retry count, wall-clock time per stage
- [ ] No regressions: existing chat flow, settings page AI config, and manual meeting creation all still work

---

## Phase Count Check

**5 phases.** Under the 7-phase ceiling. Scope is bounded.
