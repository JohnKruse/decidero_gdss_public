# AI Config Externalization Plan

## Objective

Remove hardcoded AI prompt text and AI provider defaults from Python modules, and make them configurable through the existing config system (`app/config/config.yaml` + DB override pattern where appropriate) without breaking current behavior.

Primary goals:
- Move prompt templates out of `app/services/meeting_designer_prompt.py`.
- Make URLs, model-related defaults, temperature/token defaults, and HTTP timeout values config-driven.
- Preserve secure handling of secrets (API keys stay DB-encrypted via Settings UI flow).
- Add test coverage and documentation so this is maintainable.

Security invariant:
- API keys must never be added to `config.yaml` (or any prompt/config file). Keys are entered only through Settings UI and stored encrypted in `app_settings` via `app/config/settings_store.py`.

---

## Current State Summary

### Hardcoded prompt content
- `app/services/meeting_designer_prompt.py`
  - `_PROMPT_PREFIX` and `_PROMPT_SUFFIX` contain large, static system-prompt text.
  - `GENERATE_AGENDA_PROMPT` contains static generation instructions and JSON schema text.

### Hardcoded AI provider constants
- `app/services/ai_provider.py`
  - `_DEFAULT_ANTHROPIC_BASE`
  - `_DEFAULT_OPENAI_BASE`
  - `_ANTHROPIC_API_VERSION`
  - `_HTTP_TIMEOUT` (connect/read/write/pool)

### Loader constants already present but still hardcoded in code
- `app/config/loader.py`
  - `_OPENROUTER_ENDPOINT`
  - `_GOOGLE_OPENAI_COMPAT_ENDPOINT`

### Existing configurable AI settings
- `app/config/config.yaml` → `meeting_designer_model`
  - `provider`, `api_key`, `endpoint_url`, `model`, `max_tokens`, `temperature`
- DB overrides via Settings UI for provider/model/key/endpoint and numeric AI settings.

---

## Target Design

## 1) Add an explicit `ai` config section in `config.yaml`

Introduce an `ai` section for non-secret runtime behavior and prompt locations/content:

```yaml
ai:
  provider_defaults:
    anthropic:
      endpoint_url: "https://api.anthropic.com"
      api_version: "2023-06-01"
    openai:
      endpoint_url: "https://api.openai.com/v1"
    openrouter:
      endpoint_url: "https://openrouter.ai/api/v1"
    google:
      endpoint_url: "https://generativelanguage.googleapis.com/v1beta/openai"

  http:
    timeout_seconds:
      connect: 10
      read: 90
      write: 30
      pool: 5

  prompts:
    meeting_designer:
      source: "inline"   # inline | file
      system_prefix: ""
      system_suffix: ""
      generate_agenda: ""
      file_path: "app/config/prompts/meeting_designer.yaml"  # used when source=file
```

Notes:
- Keep API keys in DB/settings store only (encrypted).
- Keep current `meeting_designer_model` section for backward compatibility, but route new defaults through `ai`.

Explicitly out of scope:
- Adding `ai.*.api_key` values to YAML defaults.
- Reading API keys from prompt files or any non-encrypted config source.

## 2) Add a prompt config file for maintainability

Create `app/config/prompts/meeting_designer.yaml` containing:
- `system_prefix`
- `system_suffix`
- `generate_agenda`

Reason:
- Avoid giant multiline strings in Python.
- Easier prompt iteration and diffs.

## 3) Add loader getters for AI runtime config

In `app/config/loader.py`, add typed getters:
- `get_ai_prompt_templates()`
- `get_ai_provider_defaults()`
- `get_ai_http_settings()`

Behavior:
- Read from YAML.
- Validate/coerce values with safe fallbacks.
- Never raise on malformed config; log + fallback.

## 4) Refactor prompt builder to use config, not module constants

In `app/services/meeting_designer_prompt.py`:
- Replace `_PROMPT_PREFIX`, `_PROMPT_SUFFIX`, `GENERATE_AGENDA_PROMPT` constants with loader-backed values.
- Build prompt from loaded templates + dynamic activity catalog.
- Keep existing `build_system_prompt()`, `build_generation_messages()`, and `parse_agenda_json()` APIs stable.

## 5) Refactor AI provider runtime to use config

In `app/services/ai_provider.py`:
- Replace hardcoded base URLs and API version with values from `get_ai_provider_defaults()`.
- Replace `_HTTP_TIMEOUT` constant with loader-driven timeout object from `get_ai_http_settings()`.
- Preserve provider behavior (`max_completion_tokens` for native OpenAI).

## 6) Align settings/test endpoints with same defaults

In `app/routers/settings.py`:
- Use shared loader-provided defaults for provider test endpoints where possible.
- Eliminate duplicate default URL constants so the app uses one source of truth.

---

## Compatibility and Migration Strategy

## Backward compatibility rules
- If new `ai.*` keys are missing, behavior remains identical to current hardcoded defaults.
- Existing `meeting_designer_model` keys continue to work unchanged.
- Existing DB settings keys remain unchanged (`ai.active_provider`, `ai.<provider>.*`, etc.).

## Migration order
1. Add new config keys + loader getters with fallback to current defaults.
2. Switch prompt service and AI provider to consume getters.
3. Add optional prompt file loading.
4. Update docs and tests.

No DB migration required for this refactor.

Secret handling compatibility requirement:
- Existing encrypted key flow remains unchanged:
  - Save: `settings_store.save_setting` / `save_settings_bulk` with key in `SENSITIVE_KEYS`
  - Read: `get_meeting_designer_settings()` via DB overrides
  - UI: Settings page remains the only supported key-entry path

---

## Implementation Work Breakdown

## Phase A: Config schema and loader
- Update `app/config/config.yaml` with documented `ai` section.
- Add prompt file scaffold at `app/config/prompts/meeting_designer.yaml`.
- Implement loader getters + coercion helpers for:
  - provider endpoint defaults
  - anthropic API version
  - timeout values
  - prompt sources/content/file path

## Phase B: Prompt extraction
- Move current prompt text from Python constants into YAML prompt file.
- Update prompt service to read templates from loader.
- Preserve dynamic activity block insertion.

## Phase C: Provider/runtime extraction
- Replace hardcoded defaults in `ai_provider.py`.
- Inject timeout config into `httpx.AsyncClient`.
- Ensure endpoint resolution remains correct for:
  - OpenAI native
  - OpenAI-compatible
  - Azure-style full path
  - OpenRouter and Google shortcuts

## Phase D: Settings endpoint alignment
- Ensure `/api/settings/test-ai` uses shared default endpoint config.
- Remove duplicated default endpoint constants where practical.

## Phase E: Tests + docs
- Add/adjust tests (below).
- Update docs (`docs/SETTINGS_GUIDE.md`, setup/admin docs, and index links if needed).

---

## Pytest Plan

## New/updated unit tests

### `app/tests/test_config_loader.py`
- Add tests for `get_ai_provider_defaults()`:
  - defaults when missing
  - coercion/invalid values fallback
- Add tests for `get_ai_http_settings()`:
  - default timeout structure
  - coercion for invalid/negative values
- Add tests for `get_ai_prompt_templates()`:
  - inline source path
  - file source path
  - missing file fallback
  - malformed YAML fallback

### `app/tests/test_meeting_designer_prompt.py`
- Replace direct constant assertions (`GENERATE_AGENDA_PROMPT`) with behavior assertions from loader-backed templates.
- Add test that custom prompt file content is reflected in built messages.
- Keep parse/normalization tests unchanged unless behavior changes.

### New test file: `app/tests/test_ai_provider_config.py`
- Verify provider defaults are sourced from loader, not hardcoded constants.
- Verify timeout values from loader are applied in client creation path.
- Verify endpoint resolution still handles full `chat/completions` URL and base URL forms.

### `app/tests/test_settings_api.py` (or existing settings test file)
- Add/adjust tests to confirm test-AI endpoint uses shared defaults.

## Suggested focused test runs
- `pytest app/tests/test_config_loader.py -q`
- `pytest app/tests/test_meeting_designer_prompt.py -q`
- `pytest app/tests/test_ai_provider_config.py -q`
- `pytest app/tests/test_settings_api.py -q`

Then full suite:
- `pytest -q`

---

## Documentation Plan

Update the following docs:
- `docs/SETTINGS_GUIDE.md`
  - Clarify which AI settings are DB-managed vs config-managed.
  - Document new `ai` config section.
  - Document prompt file override mechanism.
- `docs/LOCAL_SETUP_GUIDE.md`
  - Add prompt customization instructions.
  - Add examples for provider default endpoint overrides.
- `docs/ADMIN_HOSTING_GUIDE.md`
  - Add operational guidance on prompt/version management.
- `README.md` (brief section)
  - Link to settings/config docs and mention prompt externalization.

Include a short “safe editing” note:
- API keys remain in encrypted DB settings.
- Prompt/template files may contain business logic guidance but should not contain secrets.

---

## Acceptance Criteria

- No large prompt text constants remain in Python service modules.
- AI provider default URLs/API version/timeouts are read from config loaders.
- Current behavior remains unchanged when new config keys are absent.
- All targeted tests pass, and full `pytest -q` passes.
- Documentation clearly explains configuration ownership and override precedence.

---

## Risks and Mitigations

- Risk: Prompt regressions from file formatting changes.
  - Mitigation: Snapshot-style prompt smoke tests + strict parse tests remain.
- Risk: Misconfigured timeout/endpoints causing runtime failures.
  - Mitigation: coercion + defaults + settings endpoint validation path.
- Risk: Split-brain defaults between modules.
  - Mitigation: enforce loader as single source of truth; remove duplicated constants.

---

## Optional Follow-ups (post-refactor)

- Add a lightweight prompt version field (e.g., `ai.prompts.meeting_designer.version`) for auditability.
- Add an admin UI read-only preview of effective prompt templates.
- Add startup health log that prints effective provider/timeouts (without secrets).
