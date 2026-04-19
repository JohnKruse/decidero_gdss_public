# Decidero Settings Guide

This document is the authoritative reference for runtime configuration via the **Settings page** (`/settings`).

---

## Overview

Decidero has two tiers of configuration:

| Tier | Where | Who | When applied |
|---|---|---|---|
| **Infrastructure** | `config.yaml` Section A | Sysadmin / DevOps | On server restart |
| **Operational** | Settings page (stored in DB) | Admin / Facilitator | Immediately, no restart |

The **Settings page** is accessible from the **⚙ SETTINGS** button on the right side of the Quick Actions panel on the Dashboard.  It is available to users with the **Facilitator**, **Admin**, or **Super-Admin** role.

### Lookup priority (highest to lowest)

```
Database override (Settings UI)  →  config.yaml value  →  hardcoded default
```

Once an Admin saves a value in the Settings UI, it is stored encrypted in the `app_settings` database table and takes priority over whatever is written in `config.yaml`.  To revert a value back to its `config.yaml` default, use the **Reset to Default** button in the UI (or manually delete the row from the `app_settings` table).

---

## Roles & Permissions

| Section | Facilitator | Admin / Super-Admin |
|---|---|---|
| AI Config | View only 🔒 | Full read/write |
| Meeting Defaults | View only 🔒 | Full read/write |
| Brainstorming | Full read/write | Full read/write |
| Security | View only 🔒 | Full read/write |

Facilitators can see all current values but cannot modify Admin-only sections.  Admin-only fields are visually grayed out with a 🔒 indicator.

---

## Tab Reference

### Tab 1 — AI Configuration

Configures the AI model powering the **AI Meeting Designer** (`/meeting/design`).

| Field | Description | Default |
|---|---|---|
| **Provider** | AI API provider | *(empty — disabled)* |
| **API Key** | Provider API key — stored encrypted in DB | *(empty)* |
| **Model** | Exact model identifier | *(empty)* |
| **Custom Endpoint URL** | Only for `openai_compatible` providers | *(empty)* |
| **Max Tokens** | Maximum tokens per AI response | `2048` |
| **Temperature** | Randomness (0.0 = deterministic, 1.0 = creative) | `0.7` |

#### Provider setup

**Anthropic (Claude)**
- Provider: `anthropic`
- API Key: from [console.anthropic.com](https://console.anthropic.com)
- Model examples: `claude-opus-4-5`, `claude-sonnet-4-5`, `claude-haiku-4-5`
- Endpoint URL: leave blank (uses default `https://api.anthropic.com`)

**OpenAI (GPT)**
- Provider: `openai`
- API Key: from [platform.openai.com](https://platform.openai.com)
- Model examples: `gpt-4o`, `gpt-4o-mini`
- Endpoint URL: leave blank (uses default `https://api.openai.com/v1`)

**Azure OpenAI**
- Provider: `openai_compatible`
- API Key: your Azure API key
- Endpoint URL: `https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions?api-version=2024-02-01`
- Model: your deployment name

**OpenRouter**
- Provider: `openrouter` (or `openai_compatible` with custom endpoint)
- API Key: from [openrouter.ai](https://openrouter.ai)
- Endpoint URL: `https://openrouter.ai/api/v1`
- Model: e.g. `meta-llama/llama-3.3-70b-instruct`

**Ollama (local)**
- Provider: `openai_compatible`
- API Key: any non-empty string (e.g. `ollama`)
- Endpoint URL: `http://localhost:11434/v1`
- Model: e.g. `llama3.2`

#### Test Connection button

**Test Connection** makes a minimal live API call (a single `"Hi"` message with `max_tokens: 8`) to verify that the credentials are valid and the endpoint is reachable.  It does **not** save anything — you must still click **Save AI Settings** after a successful test.

Test result indicators:
- ✓ Green badge + latency in ms → connection verified
- ✗ Red badge + error message:
  - `"Invalid API key — authentication failed."` → check your API key
  - `"Model not found"` → check the model identifier for this provider
  - `"Connection timed out"` → check the endpoint URL and network
  - `"Network error"` → firewall or DNS issue

#### API key security

API keys entered via the Settings UI are:
- Encrypted using Fernet symmetric encryption before being stored in the database
- Never returned to the browser — the GET response only shows a masked preview (e.g. `sk-ant●●●●●●●●`)
- Never logged (the audit middleware redacts keys)
- Never visible in the URL

The encryption key is stored in `data/.settings_key` (auto-generated on first use, unique per deployment).

API keys should not be committed to `config.yaml` or prompt template files.

---

### Tab 2 — Meeting Defaults

Controls default values for new meetings and the user management system.

| Field | Description | Default |
|---|---|---|
| **Max Participants per Meeting** | Hard cap on attendees per meeting | `100` |
| **Session Duration (minutes)** | How long a login session stays active | `2880` (48 h) |
| **Recording Enabled by Default** | New meetings default to recording on | `true` |
| **Activity Participant Exclusivity** | When on: participant can only be in one activity at a time | `false` |
| **Allow Guest (Unauthenticated) Join** | Enables the `/meeting/join` flow for people without accounts | `false` |
| **Default User Password** | Temporary password assigned to new accounts | `TempPass123!` |

> ⚠ **Guest join** opens meeting access to anyone with the URL.  Only enable this if your use case requires it.

> ⚠ **Default user password** is stored encrypted.  Users are prompted to change it on first login.  Choose a strong default.

---

### Tab 3 — Brainstorming

Sets the default behaviour for new brainstorming activities.  These defaults can be overridden per-activity when creating or editing a meeting.

| Field | Description | Default |
|---|---|---|
| **Idea Character Limit** | Max characters per idea (50–5000) | `500` |
| **Max Ideas per User** | Max ideas each participant can submit | `50` |
| **Default: Maintain Anonymity** | Ideas are submitted without showing the author | `false` |
| **Default: Allow Sub-Comments** | Participants can comment on each other's ideas | `false` |
| **Default: Auto-Jump to New Ideas** | Auto-scroll to newly submitted ideas in real time | `true` |

Facilitators have **full read/write access** to this tab.

---

### Tab 4 — Security

Controls brute-force protection for the login endpoint.

| Field | Description | Default |
|---|---|---|
| **Rate Limiting Enabled** | Master toggle for login rate limiting | `true` |
| **Rate Window (seconds)** | Time window for counting failures | `60` |
| **Lockout Duration (seconds)** | How long account/IP is locked after threshold | `60` |
| **Max Failures per Username** | Failures per username before lockout | `8` |
| **Max Failures per IP** | Failures per IP address before lockout | `40` |

> Note: Environment variables take **highest priority** over these UI settings:
> - `DECIDERO_LOGIN_RATE_LIMIT_ENABLED`
> - `DECIDERO_LOGIN_RATE_LIMIT_WINDOW_SECONDS`
> - `DECIDERO_LOGIN_RATE_LIMIT_MAX_FAILURES_PER_USERNAME`
> - `DECIDERO_LOGIN_RATE_LIMIT_MAX_FAILURES_PER_IP`
> - `DECIDERO_LOGIN_RATE_LIMIT_LOCKOUT_SECONDS`

---

## The ⚡ Override Dot

A small **gold dot** (●) appears next to any field label that has an active database override — i.e., an Admin has explicitly saved a value for it in the Settings UI.  If no dot is shown, the field is using its `config.yaml` value or hardcoded default.

---

## Infrastructure Settings (config.yaml only)

The following settings are **not** exposed in the Settings UI.  They require editing `config.yaml` and restarting the server.

| Setting | Section | Description |
|---|---|---|
| `database_url` | A | SQLite (or other) database path |
| `data_directory` | A | Directory for data files |
| `backup_interval_seconds` | A | How often data is backed up |
| `autosave_seconds` | A | Activity auto-save interval |
| `sqlite.*` | A | SQLite journal mode, busy timeout, write retries |
| `database_pool.*` | A | Connection pool sizing |
| `auth.secure_cookies` | A | Secure flag on auth cookies (also `DECIDERO_SECURE_COOKIES`) |
| `meeting_refresh.*` | A | Background polling cadence |
| `ui_refresh.*` | A | Dashboard polling cadence |
| `frontend_reliability.*` | A | JS retry/backoff behaviour |
| `ai.provider_defaults.*` | B | Non-secret provider base URLs / API versions |
| `ai.http.timeouts.*` | B | AI HTTP timeout profiles (provider + test connection) |
| `ai.prompts.meeting_designer.*` | B | Prompt template source (file/inline) and path |

Environment variables with higher priority than `config.yaml`:
- `DECIDERO_SECURE_COOKIES` — overrides `auth.secure_cookies`
- `JWT_SECRET_KEY` — token signing secret (env var only, never in config)
- `DECIDERO_ENCRYPTION_KEY` — data encryption key (env var only)

---

## Database: app_settings table

Settings saved via the UI are stored in the `app_settings` table:

```
key         TEXT PRIMARY KEY   — dot-notation key (e.g. "ai.api_key")
value       TEXT               — JSON-encoded; sensitive values prefixed "enc:" and Fernet-encrypted
updated_at  DATETIME           — timestamp of last change
updated_by  TEXT               — user_id of the Admin/Facilitator who saved it
```

To inspect current overrides (SQLite):
```sql
SELECT key, updated_by, updated_at FROM app_settings;
```

To reset a single setting to its `config.yaml` default:
```sql
DELETE FROM app_settings WHERE key = 'ai.api_key';
```

Or use the **Reset to Default** button (🔄) in the Settings UI.

---

## Encryption key (data/.settings_key)

The Fernet encryption key for sensitive settings (API keys, default passwords) is stored in `data/.settings_key`.

- Auto-generated on first use if the file does not exist
- Unique per deployment — **back this file up** alongside your database
- If the file is lost, encrypted settings in the DB become unreadable.  You will need to re-enter API keys via the Settings UI

In a containerised deployment, mount `data/` as a persistent volume so the key file survives container restarts.

---

## For Developers

### Adding a new setting to the Settings page

1. **Add the DB key** — choose a dot-notation key (e.g. `"myfeature.some_option"`)
2. **Register it in `app/routers/settings.py`** — add to `_ADMIN_ONLY_WRITE_KEYS` or `_FACILITATOR_WRITE_KEYS`
3. **Add the getter** — update `app/config/loader.py`: add a `_db_get("myfeature.some_option")` overlay in the relevant getter
4. **Mark sensitive if needed** — add to `SENSITIVE_KEYS` in `app/config/settings_store.py` if the value should be encrypted
5. **Add the UI** — add the field to the appropriate tab in `app/templates/settings.html`
6. **Document it** — add a row to the relevant table in this file

### Calling getter functions in routers/services

All existing getters continue to work unchanged.  The DB overlay is transparent:

```python
from app.config.loader import get_meeting_designer_settings, get_brainstorming_limits

settings = get_meeting_designer_settings()   # DB > config.yaml > default
limits   = get_brainstorming_limits()        # same layered lookup
```

For prompt templates:

```python
from app.config.loader import get_meeting_designer_prompt_templates

templates = get_meeting_designer_prompt_templates()
system_prompt = templates["system_prefix"]
```

Plugins should always use the loader getters rather than reading `config.yaml` directly, so that Settings UI overrides take effect.
