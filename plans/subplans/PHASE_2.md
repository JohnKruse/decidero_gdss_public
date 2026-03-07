# Phase 2 [COMPLETE] — Dynamic Prompt Construction

> Global Canary: `BRASS-PELICAN-7`
> Phase Canary: `SILVER-FALCON-9`
> Source: `plans/01_MASTER_PLAN.md`, Phase 2
> Prerequisite: Phase 1 (`COPPER-HERON-3`) — Validation Engine must be complete
> Target file: `app/services/meeting_designer_prompt.py`
> Target test file: `app/tests/test_meeting_designer_prompts.py`

---

## Context

The current `GENERATE_AGENDA_PROMPT` is a static string constant with hardcoded tool_type names (`brainstorming|voting|rank_order_voting|categorization`), hardcoded per-type config hints, and hardcoded duration ranges. If a plugin is added or removed, this prompt goes stale silently. The system prompt (`build_system_prompt()`) already solves this problem correctly — it builds its activity section dynamically from the enriched catalog at call time. Phase 2 applies the same pattern to the generation and outline prompts.

This phase creates two new prompt-builder functions and a new parser, all catalog-driven. No changes to the generation endpoint, retry logic, or frontend. The existing `build_system_prompt()`, `_format_activity_block()`, `_format_config_options()`, and `parse_agenda_json()` are untouched.

---

## Atomic Steps

### Step 1 [DONE] — Catalog-driven fragment helpers

Build the reusable text fragments that replace every hardcoded value in the current `GENERATE_AGENDA_PROMPT`. Each helper reads from a catalog list (the same shape returned by `get_enriched_activity_catalog()`) and returns a formatted string.

**Implement** (in `meeting_designer_prompt.py`):

- `_build_tool_type_enum(catalog: List[Dict]) -> str`
  Returns a pipe-separated string of valid tool_types, e.g. `"brainstorming|voting|rank_order_voting|categorization"`. Built from `catalog[*]["tool_type"]`. No hardcoded names.

- `_build_config_overrides_block(catalog: List[Dict]) -> str`
  Returns a multi-line comment block describing the valid `config_overrides` keys per tool_type. For each activity in the catalog, iterate its `default_config` keys (applying the same skip-set logic from `_format_config_options()`), and emit a comment line like `// brainstorming: "allow_anonymous" (bool), "allow_subcomments" (bool)`. Tool_type names come from catalog, not literals.

- `_build_duration_guidance(catalog: List[Dict]) -> str`
  Returns a single guidance line listing duration ranges per tool_type, e.g. `"brainstorming: 5–30 min, voting: 3–15 min, ..."`. Ranges come from each activity's `typical_duration_minutes` dict (`min`/`max` keys).

All three are private functions. They accept the catalog list as a parameter (no internal catalog fetch — the caller passes it in). They must contain zero hardcoded tool_type strings.

**Test** (in `app/tests/test_meeting_designer_prompts.py`):

- `test_tool_type_enum_from_catalog` — pass a 2-item synthetic catalog → output contains both tool_types separated by `|`, no extras
- `test_tool_type_enum_ordering` — output order matches catalog order
- `test_config_overrides_block_contains_all_types` — pass full 4-plugin catalog → output contains one comment line per tool_type
- `test_config_overrides_block_skips_internal_keys` — voting entry with `options`, `vote_type` in default_config → neither appears in output; `max_votes` does appear
- `test_duration_guidance_all_types` — pass full catalog → output contains a range string for each tool_type
- `test_duration_guidance_missing_range` — activity with empty `typical_duration_minutes` → output shows "varies" for that type

**Docs:**
- Docstring on each helper: one line explaining purpose, note that it accepts the catalog list (not fetched internally) for testability and single-fetch efficiency

**Technical deviations:**
- Existing repository test file is `app/tests/test_meeting_designer_prompt.py` (singular), so Step 1 tests were added there instead of the planned `test_meeting_designer_prompts.py`.
- Local runner does not expose `pytest` on PATH; verification was executed with `venv/bin/python -m pytest` for equivalent coverage.

---

### Step 2 [DONE] — `build_generation_prompt()` replacing `GENERATE_AGENDA_PROMPT`

Create a function that produces the same conceptual prompt as the current constant, but assembled entirely from catalog data. Also accept an optional `outline` parameter so Phase 3 can pass in a validated outline to constrain the full generation.

**Implement:**

- `build_generation_prompt(outline: Optional[List[Dict]] = None) -> str`
  - Calls `get_enriched_activity_catalog()` once internally (same pattern as `build_system_prompt()`)
  - Uses `_build_tool_type_enum()`, `_build_config_overrides_block()`, `_build_duration_guidance()` to assemble the JSON schema example and guidance section
  - The JSON schema template uses `{tool_type_enum}`, `{config_overrides_block}`, `{duration_guidance}` placeholders filled from helpers
  - Retains the structural rules from the original prompt: "Output ONLY a valid JSON object", calibration advice for `max_votes`, anonymous mode guidance, bucket name guidance — but without naming specific tool_types in these rules. Instead, phrase them generically: "For voting activities, calibrate max_votes to roughly 20–30% of the option count", "For activities that support anonymity, enable it when power asymmetry is detected"
  - When `outline` is provided (a list of activity dicts from the outline stage): prepend a section that locks in the sequence — "The following activity outline has been approved. Generate the full agenda following this exact sequence, tool_types, and titles. Add instructions and config_overrides for each." followed by the outline as a formatted numbered list
  - When `outline` is `None`: prompt works standalone (equivalent to today's behavior, just dynamic)

- Remove the `GENERATE_AGENDA_PROMPT` constant entirely

**Test:**

- `test_build_generation_prompt_contains_all_tool_types` — output contains every tool_type from the live registry, none hardcoded
- `test_build_generation_prompt_no_hardcoded_tool_types` — scan the returned string for the 4 known tool_type names; confirm they only appear in catalog-derived sections (not in static prose). Specifically: the function's source code (via `inspect.getsource`) must not contain any of `"brainstorming"`, `"voting"`, `"rank_order_voting"`, `"categorization"` as string literals
- `test_build_generation_prompt_includes_json_schema` — output contains `"tool_type"`, `"title"`, `"instructions"`, `"config_overrides"`, `"duration_minutes"` as schema field names
- `test_build_generation_prompt_without_outline` — call with no args → output does NOT contain "activity outline has been approved"
- `test_build_generation_prompt_with_outline` — call with a 3-item outline list → output contains "activity outline has been approved" and all 3 titles from the outline, in order
- `test_generate_prompt_output_only_instruction` — output contains "Output ONLY" (the critical instruction to suppress prose)

**Docs:**
- Docstring explaining the dual-mode behavior (with and without outline), the catalog-driven approach, and that this replaces the former `GENERATE_AGENDA_PROMPT` constant

**Technical deviations:**
- The codebase already used `get_generation_prompt()` from config templates rather than an in-module `GENERATE_AGENDA_PROMPT` constant; Step 2 was implemented by introducing `build_generation_prompt(outline=None)` and making `get_generation_prompt()` a backward-compatible wrapper over it.
- Existing repository test file is `app/tests/test_meeting_designer_prompt.py` (singular), so Step 2 tests were added there instead of the planned `test_meeting_designer_prompts.py`.
- Verification executed via `venv/bin/python -m pytest` because `pytest` is not on PATH in this environment.

---

### Step 3 [DONE] — Update `build_generation_messages()` to use the new function

Wire `build_generation_messages()` to call `build_generation_prompt()` instead of referencing the deleted constant. Add the `outline` parameter passthrough.

**Implement:**

- Update `build_generation_messages()` signature to accept `outline: Optional[List[Dict]] = None`
- Body changes from:
  ```python
  return list(conversation_history) + [
      {"role": "user", "content": GENERATE_AGENDA_PROMPT}
  ]
  ```
  to:
  ```python
  return list(conversation_history) + [
      {"role": "user", "content": build_generation_prompt(outline=outline)}
  ]
  ```
- This is the smallest possible change. No other logic changes. The function signature stays backward-compatible (outline defaults to None).

**Test:**

- `test_build_generation_messages_appends_prompt` — pass conversation history of 2 messages → returned list has 3 messages, last one has role="user"
- `test_build_generation_messages_preserves_history` — input history is not mutated (list copy, not in-place)
- `test_build_generation_messages_without_outline` — call without outline → last message content matches `build_generation_prompt()` output
- `test_build_generation_messages_with_outline` — call with outline → last message content matches `build_generation_prompt(outline=...)` output
- `test_build_generation_messages_backward_compatible` — call with only `conversation_history` (no outline kwarg) → works without error

**Docs:**
- Update existing docstring to document the new `outline` parameter: "When provided, the generation prompt locks in the outline's activity sequence and asks the AI to elaborate with instructions and config_overrides."

**Technical deviations:**
- Existing repository test file is `app/tests/test_meeting_designer_prompt.py` (singular), so Step 3 tests were added there instead of the planned `test_meeting_designer_prompts.py`.
- Verification executed via `venv/bin/python -m pytest` because `pytest` is not on PATH in this environment.

---

### Step 4 [DONE] — Outline prompt and message builder

Create the outline-stage prompt and its message builder. The outline prompt asks the AI for a lightweight activity sequence plan — tool_type, title, duration, collaboration_pattern, and rationale per activity — with no instructions or config_overrides.

**Implement:**

- `build_outline_prompt() -> str`
  - Calls `get_enriched_activity_catalog()` internally
  - Uses `_build_tool_type_enum()` and `_build_duration_guidance()` from Step 1
  - Prompt structure:
    - Opening: "Based on our conversation, generate a meeting activity outline now."
    - JSON schema (simpler than full generation):
      ```
      {
        "meeting_summary": "...",
        "outline": [
          {
            "tool_type": "<tool_type_enum>",
            "title": "Concise action-oriented title",
            "duration_minutes": 15,
            "collaboration_pattern": "Generate|Reduce|Clarify|Organize|Evaluate|Build Consensus",
            "rationale": "Why this activity at this point in the sequence"
          }
        ]
      }
      ```
    - Duration guidance from `_build_duration_guidance()`
    - Instruction: "Output ONLY the JSON object. Do not include instructions or config_overrides — those will be added in a subsequent step."
  - Zero hardcoded tool_type strings

- `build_outline_messages(conversation_history: List[Dict[str, str]]) -> List[Dict[str, str]]`
  - Same pattern as `build_generation_messages()`: appends outline prompt as final user message
  - Returns `list(conversation_history) + [{"role": "user", "content": build_outline_prompt()}]`

**Test:**

- `test_build_outline_prompt_contains_tool_types` — output contains every tool_type from the live registry
- `test_build_outline_prompt_no_hardcoded_tool_types` — `inspect.getsource(build_outline_prompt)` contains no tool_type string literals
- `test_build_outline_prompt_excludes_config_schema` — output does NOT contain `"config_overrides"` or `"instructions"` as JSON schema fields (those are full-generation only)
- `test_build_outline_prompt_includes_outline_key` — output contains `"outline"` as the array key (not `"agenda"`)
- `test_build_outline_prompt_output_only` — output contains "Output ONLY"
- `test_build_outline_messages_appends_prompt` — pass 2-message history → returned list has 3, last is role="user"
- `test_build_outline_messages_preserves_history` — input history not mutated

**Docs:**
- Docstring on `build_outline_prompt()`: explains this is Stage 1 of the two-stage pipeline, produces a lightweight plan validated before full generation
- Docstring on `build_outline_messages()`: mirrors `build_generation_messages()` pattern

**Technical deviations:**
- Existing repository test file is `app/tests/test_meeting_designer_prompt.py` (singular), so Step 4 tests were added there instead of the planned `test_meeting_designer_prompts.py`.
- Verification executed via `venv/bin/python -m pytest` because `pytest` is not on PATH in this environment.

---

### Step 5 [DONE] — Outline JSON parser

Create `parse_outline_json()` to extract and validate the outline structure from raw AI output. Follows the same defensive parsing strategy as `parse_agenda_json()` (markdown fence stripping, brace extraction) but validates the outline-specific schema.

**Implement:**

- `parse_outline_json(raw_text: str) -> Dict[str, Any]`
  - Reuse the same markdown-fence and brace-extraction logic from `parse_agenda_json()`. Extract this shared logic into a private helper `_extract_json_object(raw_text: str) -> str` used by both parsers (DRY refactor)
  - After JSON parsing, validate:
    - `outline` key must exist and be a list (raise `ValueError` if not)
  - Return the parsed dict
  - Raise `ValueError` with descriptive message on any failure

- Refactor `parse_agenda_json()` to call `_extract_json_object()` internally (behavior unchanged, just DRY)

**Test:**

- `test_parse_outline_json_clean` — raw text is pure JSON `{"meeting_summary": "...", "outline": [...]}` → parses correctly
- `test_parse_outline_json_markdown_fenced` — raw text wrapped in ` ```json ... ``` ` → parses correctly
- `test_parse_outline_json_with_preamble` — raw text has prose before the JSON object → extracts and parses correctly
- `test_parse_outline_json_missing_outline_key` — JSON without `outline` key → raises `ValueError`
- `test_parse_outline_json_outline_not_list` — `{"outline": "wrong"}` → raises `ValueError`
- `test_parse_outline_json_invalid_json` — raw text is not JSON at all → raises `ValueError`
- `test_parse_agenda_json_still_works` — existing `parse_agenda_json()` behavior unchanged after DRY refactor (regression guard). Test with fenced, unfenced, and prose-preamble inputs
- `test_extract_json_object_shared` — both parsers produce identical output when given the same raw wrapper around different JSON payloads

**Docs:**
- Docstring on `parse_outline_json()`: explains outline schema, error conditions, relationship to `parse_agenda_json()`
- Docstring on `_extract_json_object()`: explains the shared extraction strategy (fence regex, brace fallback)

**Technical deviations:**
- Existing repository test file is `app/tests/test_meeting_designer_prompt.py` (singular), so Step 5 tests were added there instead of the planned `test_meeting_designer_prompts.py`.
- Verification executed via `venv/bin/python -m pytest` because `pytest` is not on PATH in this environment.

---

### Step 6 [DONE] — Integration tests and zero-hardcoded-tool_type audit

Verify the full prompt module works end-to-end with realistic inputs, confirm no function in the module contains hardcoded tool_type strings (except the untouched `_PROMPT_SUFFIX` standard sequences), and verify existing chat behavior is unaffected.

**Implement:**

- Create test helpers in the test file:
  - `_synthetic_catalog(n=4)` — returns a list of `n` fake enriched catalog entries with unique tool_types (e.g. `"alpha"`, `"beta"`, `"gamma"`, `"delta"`), each with `default_config`, `typical_duration_minutes`, and `collaboration_patterns` populated. This proves the prompts work with arbitrary plugins, not just the 4 builtins.

**Test:**

- `test_hypothetical_5th_plugin_appears_in_generation_prompt` — register a mock 5th plugin in the catalog, call `build_generation_prompt()` → the new tool_type appears in the prompt
- `test_hypothetical_5th_plugin_appears_in_outline_prompt` — same for `build_outline_prompt()`
- `test_no_hardcoded_tool_types_in_new_functions` — use `inspect.getsource()` on `build_generation_prompt`, `build_outline_prompt`, `_build_tool_type_enum`, `_build_config_overrides_block`, `_build_duration_guidance`. Assert none contain the strings `"brainstorming"`, `"voting"`, `"rank_order_voting"`, or `"categorization"` as literals
- `test_build_system_prompt_unchanged` — call `build_system_prompt()` and verify it still contains `_PROMPT_PREFIX` content (PURPOSE, RULES, IDENTITY) and `_PROMPT_SUFFIX` content (STANDARD SEQUENCES, MOTION). This is a regression guard — Phase 2 must not alter chat behavior.
- `test_full_round_trip_outline_then_generation` — build outline messages from a sample conversation → simulate an outline response → parse with `parse_outline_json()` → pass outline into `build_generation_messages(history, outline=parsed_outline["outline"])` → verify the last message contains the outline titles and the full JSON schema
- `test_generation_prompt_with_synthetic_catalog` — monkeypatch `get_enriched_activity_catalog` to return `_synthetic_catalog(5)` → call `build_generation_prompt()` → verify all 5 synthetic tool_types appear, zero real tool_types appear

**Docs:**
- Update module-level docstring on `meeting_designer_prompt.py` to document the new public API surface: `build_generation_prompt()`, `build_outline_prompt()`, `build_outline_messages()`, `parse_outline_json()` alongside the existing functions
- Ensure every new public function has a complete docstring with Args, Returns, and Raises sections

**Technical deviations:**
- Existing repository test file is `app/tests/test_meeting_designer_prompt.py` (singular), so Step 6 tests were added there instead of the planned `test_meeting_designer_prompts.py`.
- Regression guard for system prompt continuity was implemented against stable rendered prompt anchors (`PURPOSE`, `RULES`, `IDENTITY`, `STANDARD SEQUENCES`, `MOTION`) because this codebase uses template-driven system prompt assembly rather than literal `_PROMPT_PREFIX`/`_PROMPT_SUFFIX` constants.
- Verification executed via `venv/bin/python -m pytest` because `pytest` is not on PATH in this environment.

---

## Phase Exit Criteria

```bash
pytest app/tests/test_meeting_designer_prompts.py -v
```

**All tests must pass at 100%.** No skips, no xfails. Additionally, verify no regressions in Phase 1:

```bash
pytest app/tests/test_agenda_validator.py app/tests/test_meeting_designer_prompts.py -v
```

Both test files must pass before Phase 3 begins.
