# 00_DISCOVERY: AI Meeting Designer — Technical Audit

> Scope: Full repository scan of the AI Meeting Designer pipeline.
> Purpose: Map all module dependencies, data flows, and breaking points prior to redesigning the generation stage.
> Branch: `settings-page-dev` (4ba5a2e)
> Date: 2026-03-07

---

## 1. Module Inventory

### Core Pipeline (request order)

| # | File | Role |
|---|------|------|
| 1 | `app/templates/meeting_designer.html` | Frontend: chat UI, SSE listener, agenda review panel, sessionStorage handoff |
| 2 | `app/routers/meeting_designer.py` | HTTP API: `/status` (GET), `/chat` (POST SSE), `/generate-agenda` (POST) |
| 3 | `app/services/meeting_designer_prompt.py` | Prompt construction: `build_system_prompt()`, `GENERATE_AGENDA_PROMPT`, `build_generation_messages()`, `parse_agenda_json()` |
| 4 | `app/services/ai_provider.py` | Multi-provider LLM client: `chat_stream()`, `chat_complete()` |
| 5 | `app/services/activity_catalog.py` | Plugin registry facade: `get_enriched_activity_catalog()`, `get_activity_definition()` |
| 6 | `app/plugins/registry.py` | Singleton `ActivityRegistry` — lazy-loads builtins + drop-ins |
| 7 | `app/plugins/loader.py` | Discovery: `load_builtin_plugins()`, `load_dropin_plugins()` |
| 8 | `app/plugins/base.py` | `ActivityPlugin` ABC + `ActivityPluginManifest` frozen dataclass |
| 9 | `app/config/loader.py` | `get_meeting_designer_settings()` — 3-tier resolution (DB > YAML > hardcoded) |
| 10 | `app/config/settings_store.py` | DB-backed settings with Fernet encryption for API keys |

### Downstream Consumers (meeting creation path)

| # | File | Role |
|---|------|------|
| 11 | `app/templates/create_meeting.html` | Deserializes `sessionStorage['md_agenda']`, maps `config_overrides` -> `config`, builds form |
| 12 | `app/routers/meetings.py` | `POST /api/meetings` — accepts `MeetingCreatePayload` with `agenda: List[AgendaActivityCreate]` |
| 13 | `app/schemas/meeting.py` | Pydantic: `AgendaActivityBase`, `AgendaActivityCreate` — field validation + `tool_type` normalization |
| 14 | `app/data/meeting_manager.py` | `_append_activity()` — plugin lookup, config merge, placeholder validation, voting limits |
| 15 | `app/models/meeting.py` | SQLAlchemy: `Meeting`, `AgendaActivity` ORM models |
| 16 | `app/utils/identifiers.py` | `generate_activity_id()`, `generate_tool_config_id()` |

### Builtin Plugins

| Plugin file | `tool_type` | Patterns |
|-------------|-------------|----------|
| `app/plugins/builtin/brainstorming_plugin.py` | `brainstorming` | Generate, Clarify |
| `app/plugins/builtin/voting_plugin.py` | `voting` | Evaluate, Build Consensus |
| `app/plugins/builtin/rank_order_voting_plugin.py` | `rank_order_voting` | Evaluate |
| `app/plugins/builtin/categorization_plugin.py` | `categorization` | Reduce, Organize |

---

## 2. Dependency Graph

```
meeting_designer.html
  ├── GET  /api/meeting-designer/status
  ├── POST /api/meeting-designer/chat (SSE)
  │     └── meeting_designer.py:chat()
  │           ├── _require_facilitator()     → user_manager → DB
  │           ├── get_meeting_designer_settings() → loader.py → settings_store.py → DB
  │           ├── build_system_prompt()      → meeting_designer_prompt.py
  │           │     └── get_enriched_activity_catalog() → activity_catalog.py
  │           │           └── get_activity_registry()  → registry.py
  │           │                 └── load_builtin_plugins() + load_dropin_plugins()
  │           └── chat_stream()              → ai_provider.py → LLM API
  │
  ├── POST /api/meeting-designer/generate-agenda
  │     └── meeting_designer.py:generate_agenda()
  │           ├── get_meeting_designer_settings()
  │           ├── build_generation_messages() → appends GENERATE_AGENDA_PROMPT to history
  │           ├── chat_complete()            → ai_provider.py → LLM API (non-streaming)
  │           ├── parse_agenda_json()        → regex + json.loads
  │           └── minimal structure check    → "agenda" key exists and is a list
  │
  └── sessionStorage['md_agenda'] → /meeting/create?from=designer
        └── create_meeting.html
              ├── maps config_overrides → config
              ├── discards: duration_minutes, collaboration_pattern, rationale
              └── POST /api/meetings
                    └── meetings.py → MeetingManager.create_meeting()
                          └── _append_activity() per item
                                ├── get_activity_definition() → plugin registry lookup
                                ├── config merge (defaults + overrides)
                                ├── placeholder validation
                                ├── voting limit enforcement
                                └── DB flush
```

---

## 3. Data Flow — Field Lifecycle

Tracks each field from AI output through to database write:

| Field | AI generates | Frontend keeps | Sent to API | Stored in DB | Notes |
|-------|:---:|:---:|:---:|:---:|-------|
| `tool_type` | Y | Y | Y | Y | Normalized to lowercase at Pydantic layer |
| `title` | Y | Y | Y | Y | Falls back to plugin label if empty |
| `instructions` | Y | Y | Y | Y | Nullable, max 2000 chars |
| `config_overrides` | Y | Y (as `config`) | Y (as `config`) | Y (merged with defaults) | **Key rename** happens in JS (line 1705) |
| `duration_minutes` | Y | **DROPPED** | N | N | Not persisted anywhere |
| `collaboration_pattern` | Y | **DROPPED** | N | N | Educational metadata, discarded |
| `rationale` | Y | **DROPPED** | N | N | Design reasoning, discarded |
| `meeting_summary` | Y | Shown as banner | N | N | Displayed then forgotten |
| `design_rationale` | Y | Shown in panel | N | N | Displayed then forgotten |
| `order_index` | N | Auto-assigned | Y | Y | Sequential 1..N |
| `activity_id` | N | N | N | Y | Generated from meeting_id + stem + seq |
| `tool_config_id` | N | N | N | Y | Generated from activity_id |

---

## 4. Generation Pipeline — Current State

```
┌─────────────┐     ┌──────────────────┐     ┌───────────────┐     ┌────────────┐
│ Conversation │ ──> │ GENERATE_AGENDA_ │ ──> │ chat_complete  │ ──> │ parse_     │
│ History      │     │ PROMPT appended  │     │ (single call)  │     │ agenda_json│
│ (in-memory)  │     │ as user msg      │     │ non-streaming  │     │            │
└─────────────┘     └──────────────────┘     └───────────────┘     └─────┬──────┘
                                                                          │
                                                            ┌─────────────v──────────────┐
                                                            │ Validation (current):       │
                                                            │  - JSON parseable?          │
                                                            │  - "agenda" key exists?     │
                                                            │  - "agenda" is a list?      │
                                                            │  - That's it.               │
                                                            └────────────────────────────┘
```

**Single call. No retry. No schema validation. No tool_type verification. No config checking.**

---

## 5. What Is Validated — and Where

### Layer 1: `generate_agenda()` endpoint (meeting_designer.py:157-232)

| Check | What happens on failure |
|-------|------------------------|
| JSON parseable | 502 — "invalid agenda format" |
| `agenda` key exists and is list | 502 — "missing or invalid structure" |

**Not checked:** tool_type validity, field completeness, config structure, duration values, collaboration_pattern values.

### Layer 2: Pydantic schema (schemas/meeting.py)

| Check | What happens on failure |
|-------|------------------------|
| `tool_type` non-empty, max 50 chars, lowercased | 422 validation error |
| `title` non-empty, max 200 chars | 422 validation error |
| `instructions` max 2000 chars | 422 validation error |
| `config` is a dict or null | 422 type error |

### Layer 3: `_append_activity()` (meeting_manager.py:107-145)

| Check | What happens on failure |
|-------|------------------------|
| `tool_type` registered in plugin registry | 400 — "Unknown tool type" |
| Config values not `[object Object]` placeholder | 422 — serialization error |
| Voting: `max_votes_per_option <= max_votes` | **Silent correction** (no error) |

### Gap: No validation between Layer 1 and Layer 2

The generated agenda JSON goes from `generate_agenda()` → frontend → `POST /api/meetings` with **zero server-side validation** of individual activities at the generation endpoint. If the AI produces a bad activity, the user sees it in the review panel and then hits an error when trying to create the meeting.

---

## 6. Hardcoded Assumptions

### In `GENERATE_AGENDA_PROMPT` (meeting_designer_prompt.py:184-215)

The generation prompt has **static, hardcoded** content that will go stale if plugins change:

| Line | Hardcoded value | Should be dynamic |
|------|----------------|-------------------|
| 193 | `"brainstorming\|voting\|rank_order_voting\|categorization"` | Should come from catalog |
| 199-205 | Per-type config_overrides comments (brainstorming: allow_anonymous, etc.) | Should come from catalog default_config |
| 211 | Duration ranges per type (brainstorming: 10-25 min, etc.) | Should come from `typical_duration_minutes` |
| 212 | `max_votes` calibration guidance | Should come from voting plugin metadata |

### In `_format_config_options()` (meeting_designer_prompt.py:95-105)

| Line | Hardcoded value | Issue |
|------|----------------|-------|
| 98 | `skip = {"options", "ideas", "items", "buckets", "mode", "vote_type"}` | Assumes these are always "internal" — new plugins may need different skip sets |

### In `_validate_activity_config_placeholders()` (meeting_manager.py:177-206)

| Line | Hardcoded value | Issue |
|------|----------------|-------|
| 184 | `voting → ["options"]` | Hardcoded watched keys per tool_type |
| 186 | `rank_order_voting → ["ideas"]` | Should be declared in plugin manifest |
| 188 | `categorization → ["items", "buckets"]` | Same |

### In `_append_activity()` (meeting_manager.py:130-131)

| Line | Hardcoded value | Issue |
|------|----------------|-------|
| 130 | `if payload.tool_type == "voting":` | Tool-specific validation not delegated to plugin |

---

## 7. Config Schema Gap: What AI Knows vs What Plugins Accept

The generation prompt tells the AI about a **subset** of each plugin's config keys. Several valid config keys are invisible to the AI:

| Plugin | AI is told about | Actually configurable | Invisible to AI |
|--------|-----------------|----------------------|-----------------|
| brainstorming | `allow_anonymous`, `allow_subcomments` | + `auto_jump_new_ideas` | `auto_jump_new_ideas` |
| voting | `max_votes`, `show_results_immediately` | + `max_votes_per_option`, `allow_retract`, `randomize_participant_order` | 3 keys hidden |
| rank_order_voting | `randomize_order` | + `show_results_immediately`, `allow_reset` | 2 keys hidden |
| categorization | `buckets` | + `single_assignment_only` | `single_assignment_only` |

These hidden keys get their default values via config merge, which is correct behavior. But if the generation prompt were built dynamically from the catalog, the AI could make smarter design decisions with the full config surface.

---

## 8. State Management

### Client-Side

- **Conversation**: `state.messages[]` in JS — lost on page refresh, not persisted to server
- **Generated agenda**: `state.agendaData` in JS — transferred via `sessionStorage['md_agenda']`, consumed and deleted on create_meeting page load
- **No server-side session**: Every `/chat` request sends the full history; no session key

### Server-Side

- **Stateless**: No conversation storage. No audit trail. No undo.
- **Config**: Re-read from DB + YAML on every request (no cache, changes instant)
- **Plugin registry**: Loaded once (lazy), singleton, never reloaded without restart

---

## 9. Error Handling & Recovery

### Current recovery mechanisms

| Failure | Current behavior | Recovery |
|---------|-----------------|----------|
| AI not configured | 503 | User sees "not configured" message |
| LLM API error (timeout, rate limit, 5xx) | 502 | User clicks "Generate Agenda" again |
| Invalid JSON from LLM | 502 | User clicks "Generate Agenda" again |
| Missing `agenda` key | 502 | User clicks "Generate Agenda" again |
| Invalid `tool_type` (hallucinated) | Passes generation, fails at meeting creation (400) | User must manually fix or regenerate |
| Empty agenda array | Passes all checks, shows empty panel | User must regenerate |
| Truncated JSON (max_tokens exceeded) | `parse_agenda_json()` fails with JSONDecodeError → 502 | User retries; no guidance to increase max_tokens |
| sessionStorage handoff failure | Silent catch, no error shown | User sees empty form, no explanation |

### What doesn't exist

- No automatic retry with backoff
- No retry with error feedback to the model
- No partial recovery (salvage valid activities from invalid batch)
- No token budget estimation before calling LLM
- No streaming of generation (can't show progress)
- No conversation persistence (crash = start over)

---

## 10. AI Provider Layer

### Supported providers

| Provider | Endpoint | System prompt handling |
|----------|----------|----------------------|
| `anthropic` | `api.anthropic.com/v1/messages` | Separate `system` parameter |
| `openai` | `api.openai.com/v1/chat/completions` | Prepended as `{"role":"system"}` message |
| `google` | `generativelanguage.googleapis.com/v1beta/openai` | Same as openai (compat wrapper) |
| `openrouter` | `openrouter.ai/api/v1` | Same as openai |
| `openai_compatible` | Custom URL | Same as openai |

### Timeouts (hardcoded in ai_provider.py:25)

```
connect: 10s, read: 90s, write: 30s, pool: 5s
```

### Token budget

- `max_tokens` default: **2048** (configurable via settings)
- System prompt size: ~2500-3500 tokens depending on plugin count
- No pre-flight check: if conversation + system prompt + generation prompt > model context, the call will fail or truncate

---

## 11. Breaking Points — Risk Assessment

### CRITICAL (causes crashes or invalid meetings)

| # | Risk | Location | Trigger |
|---|------|----------|---------|
| C1 | **Hallucinated tool_type** passes generation validation, fails at meeting creation | `generate_agenda()` has no tool_type check | Complex meetings where AI invents activity names |
| C2 | **Truncated JSON** from token exhaustion | `max_tokens=2048` default may be too small for 5+ activity agendas | Long conversations + complex meetings |
| C3 | **Empty/nonsensical activities** pass all checks | No field completeness validation at generation time | AI generates structurally valid but semantically empty entries |

### HIGH (causes poor UX or data loss)

| # | Risk | Location | Trigger |
|---|------|----------|---------|
| H1 | **No retry mechanism** — single shot, one chance | `generate_agenda()` | Any transient LLM failure requires manual retry |
| H2 | **Silent sessionStorage failure** loses agenda | `create_meeting.html:1727-1729` | Storage quota, private browsing, race condition |
| H3 | **Conversation loss on refresh** | Client-side only, no persistence | Accidental refresh, browser crash |
| H4 | **GENERATE_AGENDA_PROMPT is static** — tool_types and config hints are hardcoded | `meeting_designer_prompt.py:193-205` | Adding/removing a plugin makes prompt stale |

### MODERATE (suboptimal but not broken)

| # | Risk | Location | Trigger |
|---|------|----------|---------|
| M1 | **AI can't see full config surface** — several keys hidden | `_format_config_options()` skip set | AI makes suboptimal config decisions |
| M2 | **duration_minutes discarded** — no duration tracking | `create_meeting.html:1701-1706` | Facilitator loses AI's time guidance |
| M3 | **design_rationale discarded** — no audit trail | Same | No record of why agenda was structured this way |
| M4 | **Voting limits silently corrected** | `_enforce_voting_limits()` | User unaware of backend adjustment |

---

## 12. Relevant Constants & Magic Numbers

| Value | Location | Purpose |
|-------|----------|---------|
| `2048` | `loader.py:491` | Default max_tokens |
| `0.7` | `loader.py:496` | Default temperature |
| `4000` | `meeting_designer.py:66` | Max chars per user message |
| `90` (seconds) | `ai_provider.py:25` | Read timeout for LLM calls |
| `500` | `meeting_designer.py:214` | Chars of raw output logged on parse failure |

---

## 13. Summary: What Must Change for Multi-Stage Generation

For the planned **outline → validate → full JSON → validate** pipeline, these are the touch points:

### Must modify

1. **`meeting_designer_prompt.py`** — add outline prompt, make `GENERATE_AGENDA_PROMPT` dynamic (inject tool_types and config from catalog), add retry-with-feedback prompt template
2. **`meeting_designer.py`** — restructure `generate_agenda()` into multi-stage pipeline with validation between stages, add retry logic
3. **`activity_catalog.py`** — may need a new function that returns a compact validation schema (valid tool_types, required fields, config key types) for use by the validation layer

### Must add

4. **Validation module** (new) — programmatic validation of AI output against the live catalog: tool_type existence, required field presence, config key validity, duration range checks
5. **Retry logic** — retry with error feedback at each stage, configurable attempt limits

### Should not need to change

6. `ai_provider.py` — `chat_complete()` already supports the needed interface
7. `create_meeting.html` — consumes the same final JSON shape
8. `meeting_manager.py` — downstream validation unchanged
9. Plugin manifests — no changes needed, just consumed differently

### Potential additions for robustness

10. Token budget estimation before generation call
11. Dynamic `max_tokens` scaling based on outline activity count
12. Structured logging of generation attempts for debugging
