# 00 — DISCOVERY: Role & Permission Terrain Audit

**Scope:** Map the existing identity/authorization surface across backend data, backend enforcement, and frontend gating. Identify dependencies, data flows, and breaking points relevant to the target state *"system-wide roles only (super_admin / admin / facilitator / participant) + meeting roster membership — no per-meeting role concept."*

This document is a **terrain map, not a plan.** It does not prescribe changes. Every claim is anchored to a file:line reference so later planning work can trust the picture.

Branch at time of audit: `fix/role-problems`. HEAD: `e26d1be`.

---

## 1. Glossary — the four concepts currently in play

| Concept | Where it lives | Cardinality | Owner of truth |
|---|---|---|---|
| **System role** | `User.role` column (string; enum `UserRole` in [app/models/user.py:11](app/models/user.py:11)) | One per user | User admin flow |
| **Meeting ownership** | `Meeting.owner_id` FK → `User` ([app/models/meeting.py:48](app/models/meeting.py:48)) | One per meeting | Meeting creation |
| **Meeting facilitator roster** | `meeting_facilitators` table → `MeetingFacilitator` model ([app/models/meeting.py:98](app/models/meeting.py:98)) with `is_owner` flag | N per meeting | Auto-grant + explicit add |
| **Meeting participant roster** | `participants` association table ([app/models/meeting.py:19](app/models/meeting.py:19)) | N per meeting | Roster UI / bulk update |

The **first concept is global**; the remaining three are **per-meeting**. The collapse target removes the "meeting facilitator roster" concept entirely — facilitator capability would be derived from system role + participant-roster membership (plus the owner).

---

## 2. Module dependency map (auth terrain)

```
                 ┌────────────────────────────┐
                 │  app/models/user.py        │
                 │  UserRole enum             │
                 │  User.role                 │
                 └─────────────┬──────────────┘
                               │
        ┌──────────────────────┼─────────────────────┐
        │                      │                     │
┌───────▼─────────┐  ┌─────────▼──────────┐  ┌───────▼────────────┐
│ app/auth/auth.py│  │ app/models/meeting │  │ app/data/          │
│  JWT + session  │  │  .py               │  │  user_manager.py   │
│  check_permission│ │  Meeting.owner_id  │  │  update_user_role  │
│  Permission enum│  │  MeetingFacilitator│  │  (never syncs      │
│  request.state. │  │  participants_table│  │   facilitator_links)│
│  user cache     │  └────────┬───────────┘  └────────────────────┘
└────────┬────────┘           │
         │                    │
         │    ┌───────────────▼────────────────────┐
         │    │ app/data/meeting_manager.py        │
         │    │  _should_auto_facilitate (system   │
         │    │    role gate for auto-grant)       │
         │    │  _ensure_facilitator_assignment    │
         │    │    (only adds, never revokes)      │
         │    │  add_participant / remove_         │
         │    │    participant / bulk_update_      │
         │    │    participants                    │
         │    │  _cascade_activity_participant_    │
         │    │    cleanup (participants only;     │
         │    │    does not touch facilitator_     │
         │    │    links)                          │
         │    │  get_dashboard_meetings (derives   │
         │    │    is_facilitator from facilitator_│
         │    │    links)                          │
         │    └────────────┬───────────────────────┘
         │                 │
         └────────┬────────┴────────┬────────────────────┐
                  │                 │                    │
        ┌─────────▼──────────┐  ┌──▼───────────────┐  ┌─▼──────────────────┐
        │ app/routers/       │  │ app/routers/     │  │ app/routers/       │
        │   meetings.py      │  │   users.py,      │  │   brainstorming.py,│
        │ _assert_meeting_   │  │   settings.py,   │  │   voting.py,       │
        │   access (the      │  │   pages.py       │  │   rank_order_      │
        │   canonical gate)  │  │                  │  │   voting.py,       │
        │   reads facilitator│  │                  │  │   categorization.py│
        │   _links           │  │                  │  │   transfer.py      │
        └─────────┬──────────┘  └──────────────────┘  └────────────────────┘
                  │
        ┌─────────▼──────────────────┐
        │ app/templates/*.html       │
        │  (render-time gating:      │
        │   current_user.role,       │
        │   is_admin booleans,       │
        │   data-user-role attr)     │
        └─────────┬──────────────────┘
                  │
        ┌─────────▼──────────────────┐
        │ app/static/js/             │
        │   meeting.js, dashboard.js │
        │   (read data-user-role     │
        │    once at page load →     │
        │    state.isFacilitator,    │
        │    state.capabilities)     │
        └────────────────────────────┘
```

**Key property:** every arrow pointing into `MeetingFacilitator` / `facilitator_links` is a dependency that must be relocated or removed under the target model. There are ~97 non-test references to `facilitator_links` across 15 files.

---

## 3. Identity model — data at rest

### 3.1 `User` ([app/models/user.py:18](app/models/user.py:18))
- PK: `user_id` (string, 20)
- Unique: `email`, `login`, `legacy_user_id`
- Role: `role` column, `default=PARTICIPANT`, nullable=False ([app/models/user.py:31](app/models/user.py:31))
- Signup defaults `PARTICIPANT` via [app/data/user_manager.py:218](app/data/user_manager.py:218). `register_user` hardcodes the string `"PARTICIPANT"` ([app/data/user_manager.py:984](app/data/user_manager.py:984)).
- First admin bootstrap in `ensure_admin_exists` grants `SUPER_ADMIN` if no admin exists, else `ADMIN` ([app/data/user_manager.py:911](app/data/user_manager.py:911)).
- Relationships: `owned_meetings`, `facilitator_links`, `meetings` (m2m via `participants_table`).

### 3.2 `Meeting` ([app/models/meeting.py:33](app/models/meeting.py:33))
- PK: `meeting_id`
- `owner_id`: FK `users.user_id`, nullable=False ([app/models/meeting.py:48](app/models/meeting.py:48))
- `facilitator_links`: one-to-many → `MeetingFacilitator`, `cascade="all, delete-orphan"`
- `facilitators`: secondary viewonly convenience relation through `meeting_facilitators_table`
- `participants`: m2m via `participants_table`

### 3.3 `MeetingFacilitator` ([app/models/meeting.py:98](app/models/meeting.py:98))
- PK: `facilitator_id`
- FK `meeting_id` ON DELETE CASCADE
- FK `user_id` ON DELETE CASCADE
- `is_owner` boolean (distinguishes meeting owner from co-facilitators)
- `created_at` timestamp
- **Unique constraints:**
  - `uq_meeting_facilitators_facilitator_id` on `facilitator_id` alone (redundant — PK already unique)
  - `uq_meeting_facilitators_user` on `(meeting_id, user_id)` — prevents duplicate facilitator rows for one user in one meeting

### 3.4 `participants_table` ([app/models/meeting.py:19](app/models/meeting.py:19))
- Composite PK `(user_id, meeting_id)`
- `joined_at` timestamp
- CASCADE on meeting delete
- No extra columns — pure m2m membership

### 3.5 Migrations
- **No Alembic / migration framework in the repo.** Schema is created at app startup via SQLAlchemy `create_all` plus an explicit `meeting_facilitators_table.create(..., checkfirst=True)` shim in [app/main.py:101](app/main.py:101). Schema evolution cannot be traced through migration files.

---

## 4. Write paths — how these tables get mutated

| Writer | File:Line | Writes | Trigger |
|---|---|---|---|
| `add_participant` | [app/data/meeting_manager.py:1232](app/data/meeting_manager.py:1232) | `participants` + (via helper) `facilitator_links` | Roster add |
| `remove_participant` | [app/data/meeting_manager.py:1253](app/data/meeting_manager.py:1253) | `participants` — **does NOT touch `facilitator_links`** | Roster remove |
| `bulk_update_participants` | [app/data/meeting_manager.py:1280](app/data/meeting_manager.py:1280) | `participants` + (adds only) `facilitator_links` | Bulk roster op |
| `_should_auto_facilitate` | [app/data/meeting_manager.py:1183](app/data/meeting_manager.py:1183) | Pure predicate: `user.role ∈ {FACILITATOR, ADMIN, SUPER_ADMIN}` | Gate for the helper below |
| `_ensure_facilitator_assignment` | [app/data/meeting_manager.py:1190](app/data/meeting_manager.py:1190) | `facilitator_links` — **add-or-update only, never removes** | Called from `add_participant`, `bulk_update_participants`, `create_meeting`, `add_meeting` |
| `_cascade_activity_participant_cleanup` | [app/data/meeting_manager.py:1358](app/data/meeting_manager.py:1358) | `agenda_activities.config['participant_ids']` (JSON) | Called from participant removals; **does not clean facilitator_links** |
| `create_meeting` | [app/data/meeting_manager.py:900](app/data/meeting_manager.py:900) | `meetings`, `meeting_facilitators` (owner + co-facilitators), `participants` | New meeting |
| `add_meeting` | [app/data/meeting_manager.py:1042](app/data/meeting_manager.py:1042) | Same as above, older API | New meeting |
| `UserManager.update_user_role` | [app/data/user_manager.py:564](app/data/user_manager.py:564) | `users.role` — **does NOT cascade to any `facilitator_links`** | Admin role-change flow |
| `UserManager.add_user` / `register_user` | [app/data/user_manager.py:212](app/data/user_manager.py:212), [:966](app/data/user_manager.py:966) | `users`; default `PARTICIPANT` | Signup/admin |

**The three documented staleness-generating writer gaps:**
1. `remove_participant` removes from `participants` but leaves the `MeetingFacilitator` row intact.
2. `_ensure_facilitator_assignment` never removes a facilitator row; re-adding a previously-facilitated user short-circuits at the "already exists" check.
3. `update_user_role` demoting a FACILITATOR to PARTICIPANT leaves every pre-existing `facilitator_links` row for that user intact.

---

## 5. Read paths — every place `facilitator_links` is consulted

### 5.1 Canonical gate

- `_assert_meeting_access` ([app/routers/meetings.py:203](app/routers/meetings.py:203))
  - Computes `is_facilitator = any(link.user_id == user.user_id for link in meeting.facilitator_links)`
  - Admits if `is_admin OR is_owner OR is_facilitator OR (is_participant AND not require_facilitator)`
  - Used by ~15 endpoints (full list in §6)

### 5.2 Other readers

| Reader | File:Line | Purpose |
|---|---|---|
| `get_dashboard_meetings` | [app/data/meeting_manager.py:1467](app/data/meeting_manager.py:1467) | Query filter + `is_facilitator` computation ([app/data/meeting_manager.py:1636](app/data/meeting_manager.py:1636)) |
| `_collect_facilitator_assignments` | [app/data/meeting_manager.py:1773](app/data/meeting_manager.py:1773) | Ordered facilitator list (owner first) |
| `_user_can_manage_meeting` / user directory | [app/routers/users.py:728](app/routers/users.py:728), [:814](app/routers/users.py:814) | Flags each user with `is_facilitator` for frontend display |
| Brainstorming `_ensure_user_access` | [app/routers/brainstorming.py:85](app/routers/brainstorming.py:85) | Gate on ideas/comments |
| Voting `_ensure_user_access` | [app/routers/voting.py:44](app/routers/voting.py:44) | Gate on votes |
| Rank-order voting `_ensure_user_access` | [app/routers/rank_order_voting.py:48](app/routers/rank_order_voting.py:48) | Gate on rank-votes |
| Categorization `_access` | [app/routers/categorization.py:70](app/routers/categorization.py:70) | Gate + returns `(is_participant, is_facilitator)` tuple |
| Transfer `_assert_transfer_access` | [app/routers/transfer.py:48](app/routers/transfer.py:48) | Gate on export/import |
| Meeting start/stop control | [app/routers/meetings.py:1935](app/routers/meetings.py:1935) | Inline facilitator check for activity control |
| Meeting update (PUT) | [app/routers/meetings.py:1860](app/routers/meetings.py:1860) | Inline facilitator check + owner-only fields |
| Meeting delete | [app/routers/meetings.py:2355](app/routers/meetings.py:2355) | **Owner-only** — co-facilitators rejected |
| Export bundle | [app/routers/meetings.py:273](app/routers/meetings.py:273) | Serializes facilitator_links into export JSON |
| Settings page `is_admin` | [app/routers/pages.py:353](app/routers/pages.py:353) | Per-meeting settings page gate |

### 5.3 Identity caching

- **JWT** carries only `sub = login` ([app/auth/auth.py:147](app/auth/auth.py:147)). No role claim, no per-meeting state.
- **Request-scoped cache** of `UserSchema` at `request.state.user` ([app/auth/auth.py:350](app/auth/auth.py:350)). Per-request only; next request refetches.
- **No per-meeting caching** — facilitator status is recomputed per request.

---

## 6. Backend enforcement surface (capability ↔ gate)

| Capability | Current gate | Source of truth |
|---|---|---|
| View meeting | `_assert_meeting_access(require_facilitator=False)` | facilitator_links ∪ owner ∪ participants ∪ admin |
| Create meeting | `check_permission(CREATE_MEETING)` | System role (facilitator+) |
| Update meeting config / properties | `is_admin ∨ is_owner ∨ is_facilitator` | facilitator_links |
| **Delete meeting** | `is_admin ∨ is_owner` **only** | owner_id — **co-facilitators cannot delete** |
| Archive / restore | `_assert_meeting_access(require_facilitator=True)` | facilitator_links |
| Agenda CRUD + reorder | `_assert_meeting_access(require_facilitator=True)` | facilitator_links |
| Start / stop activity / change tool | Inline `is_admin ∨ is_owner ∨ is_facilitator` | facilitator_links |
| List / add / remove participants | `_assert_meeting_access(require_facilitator=True)` | facilitator_links |
| Activity roster set | `_assert_meeting_access(require_facilitator=True)` | facilitator_links |
| Submit brainstorming idea | `_ensure_user_access` | facilitator_links ∪ activity.config participant_ids |
| Cast vote / rank-vote | `_ensure_user_access` | facilitator_links ∪ activity.config participant_ids |
| Categorization operations | `_access` + `_enforce_participant_lock` | facilitator_links + activity lock state |
| Export / import meeting | `_assert_meeting_access(require_facilitator=True)` / `CREATE_MEETING` | Mixed |
| Manage users | `check_permission(MANAGE_USERS)` | System role (admin+) |
| Change user role | `check_permission(MANAGE_ROLES)` | System role (admin+); SUPER_ADMIN immutable |
| User directory (meeting context) | `_user_can_manage_meeting` | facilitator_links + participants |
| User directory (system context) | `requester.role ∈ {ADMIN, FACILITATOR}` | System role |
| Settings read | `_require_facilitator_or_admin` | System role |
| Settings write (admin keys) | Admin-only whitelist | System role |
| Settings write (`brainstorming.*`) | Facilitator-allowed | System role |
| Page routes `/dashboard`, `/settings`, `/meeting/design`, `/activity-library`, `/meeting/create`, `/meeting/{id}/settings`, `/admin/users` | `current_user.role ∈ {…}` checks in [app/routers/pages.py](app/routers/pages.py) | System role |

**Permission inheritance** in [app/auth/auth.py:432-452](app/auth/auth.py:432):
- PARTICIPANT: `VIEW_MEETING`
- FACILITATOR: + `CREATE_MEETING, UPDATE_MEETING, DELETE_MEETING`
- ADMIN: + `MANAGE_USERS, MANAGE_ROLES`
- SUPER_ADMIN: all

### 6.1 WebSocket endpoints — unauthenticated

- `WS /meetings/{meeting_id}` ([app/routers/realtime.py:37](app/routers/realtime.py:37))
- Brainstorming WS ([app/routers/brainstorming.py:50](app/routers/brainstorming.py:50))
- Categorization `_broadcast_refresh` ([app/routers/categorization.py:152](app/routers/categorization.py:152))

All three **broadcast to every connected client in a meeting with no role filtering and no validation of the self-reported `userId` query param**. Orthogonal to the current bug but worth flagging as a breaking-point during any auth rework.

---

## 7. Frontend gating surface

### 7.1 Templates branching on role

| File:Line | Condition | Gates |
|---|---|---|
| [app/templates/_base.html:19](app/templates/_base.html:19) | `data-user-role="{{ current_user.role … }}"` | Global role attribute read by JS |
| [app/templates/meeting.html:14](app/templates/meeting.html:14) | `data-user-role=…` | Seeds `context.userRole` in meeting.js |
| [app/templates/meeting.html:15](app/templates/meeting.html:15) | `data-view-mode=facilitator/participant` (system-role branch) | Drives `state.isFacilitator` |
| [app/templates/meeting.html:59](app/templates/meeting.html:59) | `{% if current_user.role in ['admin','super_admin','facilitator'] %}` | Activity-log link |
| [app/templates/meeting.html:96-101](app/templates/meeting.html:96) | Same condition | **Meeting Settings + Meeting Roster buttons** (the user-visible bug) |
| [app/templates/dashboard.html:8](app/templates/dashboard.html:8), [:12](app/templates/dashboard.html:12) | Same condition | Quick Actions panel |
| [app/templates/dashboard.html:59](app/templates/dashboard.html:59) | `role in ['admin','super_admin']` | MANAGE USERS |
| [app/templates/dashboard.html:74](app/templates/dashboard.html:74) | Same admin condition | Restart/Shutdown |
| [app/templates/dashboard.html:110](app/templates/dashboard.html:110) | Same admin condition | Loads `admin_system.js` |
| [app/templates/dashboard/_panel_admin.html:5](app/templates/dashboard/_panel_admin.html:5) | `data-requires-role="admin"` | Admin panel |
| [app/templates/dashboard/_panel_facilitator.html:5](app/templates/dashboard/_panel_facilitator.html:5) | `data-requires-role="facilitator"` | Facilitated meetings panel |
| [app/templates/dashboard/_panel_participant.html:5](app/templates/dashboard/_panel_participant.html:5) | `data-requires-role="participant"` | All-meetings panel |
| [app/templates/settings.html:30](app/templates/settings.html:30), [:36](app/templates/settings.html:36), [:46](app/templates/settings.html:46), [:56-61](app/templates/settings.html:56) | `{% if not is_admin %}` | AI / defaults / security tabs + banner |

### 7.2 JS consumers

- [app/static/js/meeting.js:19](app/static/js/meeting.js:19): `context.userRole = dataset.userRole` (once, page-load)
- [app/static/js/meeting.js:46](app/static/js/meeting.js:46): `isAdminUser` computed from system role
- [app/static/js/meeting.js:1334](app/static/js/meeting.js:1334): `if (!state.isFacilitator) return` — blocks participant-directory load
- [app/static/js/meeting.js:1195](app/static/js/meeting.js:1195): reads API-derived `item.is_facilitator` for display pill only (not a gate)
- [app/static/js/dashboard.js:31](app/static/js/dashboard.js:31): collects all `[data-requires-role]` elements
- [app/static/js/dashboard.js:129-148](app/static/js/dashboard.js:129): `determineRoleScope` + `buildCapabilities` — builds capability set from system role **once** at page load
- [app/static/js/dashboard.js:150-169](app/static/js/dashboard.js:150): `updatePanelVisibility` reads the capability set
- [app/static/js/dashboard.js:704](app/static/js/dashboard.js:704): uses API-derived `meeting.is_facilitator` to route into tables (refreshed on dashboard poll)

### 7.3 Page-load caching hotspots (staleness)

1. `meeting.html:14-15` → `data-user-role` + `data-view-mode` — **never re-read** after load.
2. `meeting.js:19` → `context.userRole`, `state.isFacilitator` — derived once.
3. `dashboard.html:19` → `data-user-role` on `layout-container` — consumed by `dashboard.js` once.
4. All `{% if current_user.role … %}` blocks in templates — render-time only; no SSR re-render on role change.

---

## 8. Inconsistency & breaking-point matrix

| # | Inconsistency | Symptom seen by user | Evidence |
|---|---|---|---|
| 1 | `remove_participant` doesn't clear `facilitator_links` | Remove & re-add a facilitator on the roster → row survives → stale facilitator powers | [app/data/meeting_manager.py:1253](app/data/meeting_manager.py:1253) |
| 2 | `_ensure_facilitator_assignment` is add-only | Cannot "downgrade" a meeting-level facilitator to participant through the roster UI | [app/data/meeting_manager.py:1200](app/data/meeting_manager.py:1200) |
| 3 | `update_user_role` doesn't touch facilitator_links | Demoting a system facilitator leaves them with stale per-meeting facilitator powers across every meeting they've touched | [app/data/user_manager.py:564](app/data/user_manager.py:564) |
| 4 | Template Settings/Roster buttons gate on system role, but backend gates on `facilitator_links` | User demoted to participant at system level *still holds* stale facilitator_links → backend admits their actions; but buttons hidden → asymmetric UI/capability split. Exactly matches the reported symptoms. | [app/templates/meeting.html:96](app/templates/meeting.html:96) vs [app/routers/meetings.py:203](app/routers/meetings.py:203) |
| 5 | Delete-meeting gates on `owner_id` only; every other facilitator capability admits co-facilitators | A co-facilitator can do everything but delete | [app/routers/meetings.py:2355](app/routers/meetings.py:2355) |
| 6 | User-directory gate differs between meeting-context and system-context | Same UI flows through two different authorization rules | [app/routers/users.py:700-860](app/routers/users.py:700) |
| 7 | Activity roster has two sources of truth: `activity.config['participant_ids']` vs live `meeting_state_manager` | Activity visibility can disagree with config | [app/routers/brainstorming.py:151-176](app/routers/brainstorming.py:151) |
| 8 | Categorization has a participant-lock mechanism; brainstorming/voting do not | Participant-blocking behavior inconsistent across activity types | [app/routers/categorization.py:199](app/routers/categorization.py:199) |
| 9 | WebSocket endpoints do not authenticate or authorize; `userId` is self-reported | Any client can connect to any meeting and receive all broadcasts | [app/routers/realtime.py:46](app/routers/realtime.py:46) |
| 10 | Redundant `UniqueConstraint` on `meeting_facilitators.facilitator_id` (PK already unique) | Cosmetic; noise for any schema cleanup | [app/models/meeting.py:102](app/models/meeting.py:102) |
| 11 | `register_user` hardcodes the string `"PARTICIPANT"` instead of `UserRole.PARTICIPANT.value` | Fragile if enum values shift | [app/data/user_manager.py:984](app/data/user_manager.py:984) |
| 12 | Dashboard response exposes full `facilitator_links` + `participants` arrays plus derived `is_facilitator` / `can_edit` / `can_delete` / `can_archive` | Contract coupling: any collapse of `facilitator_links` requires adjusting the response shape + frontend consumers | [app/data/meeting_manager.py:1636](app/data/meeting_manager.py:1636), [app/static/js/dashboard.js:704](app/static/js/dashboard.js:704) |

---

## 9. Test coverage terrain

### 9.1 Tests that pin current behavior (non-exhaustive; names with one-line purpose)

| Test file | Function | Pins |
|---|---|---|
| [app/tests/test_meeting_manager.py](app/tests/test_meeting_manager.py) | `test_activity_participant_scope_management` | Assumes auto-grant of facilitator_links for FACILITATOR users |
| [app/tests/test_meeting_manager.py](app/tests/test_meeting_manager.py) | `test_bulk_update_participants_adds_and_removes_users` | Assumes bulk add triggers facilitator auto-grant |
| [app/tests/test_meeting_manager.py](app/tests/test_meeting_manager.py) | `test_remove_meeting_participant_pops_empty_custom` | Cascade cleanup of activity config on participant removal |
| [app/tests/test_api_meetings.py](app/tests/test_api_meetings.py) | `test_cofacilitator_update_permissions` | Co-facilitators may update config but not owner/facilitators |
| [app/tests/test_api_meetings.py](app/tests/test_api_meetings.py) | `test_facilitator_controls_start_stop_tool` | Start/stop gated to facilitators |
| [app/tests/test_auth.py](app/tests/test_auth.py) | (multiple) | Permission-inheritance ladder |
| [app/tests/test_activity_rosters.py](app/tests/test_activity_rosters.py) | (multiple) | Custom activity roster scoping |
| [app/tests/test_categorization_api.py](app/tests/test_categorization_api.py) | `test_participant_cannot_assign_categories` (and siblings) | Facilitator-only categorization ops |
| [app/tests/test_brainstorming_api.py](app/tests/test_brainstorming_api.py) | `test_participant_in_custom_roster` (and siblings) | Activity participant_ids gating |
| [app/tests/test_api_participants.py](app/tests/test_api_participants.py) | roster CRUD tests | Facilitator-only roster management |
| [app/tests/test_api_batch_users.py](app/tests/test_api_batch_users.py) | batch creation | Admin-only |
| [app/tests/test_pages.py](app/tests/test_pages.py) | `test_settings_page_requires_facilitator` | Settings UI gated to facilitator+ |
| [app/tests/test_frontend_smoke.py](app/tests/test_frontend_smoke.py) | `test_meeting_roster_button_present` | Meeting Roster button present and gated by `{% if current_user.role in [...] %}` |
| [app/tests/test_frontend_smoke.py](app/tests/test_frontend_smoke.py) | `test_meeting_settings_button_label` | Meeting Settings button labeled "Meeting Settings" |

Baseline: `PYTHONPATH=. ./venv/bin/pytest app/tests/ -v` → **526 passed, 2 skipped** as of HEAD (recorded in commit `4f3dac3`).

### 9.2 Missing coverage

- No test for `_ensure_facilitator_assignment` as a unit.
- No test for stale `facilitator_links` after `remove_participant`.
- No test for `update_user_role` cascade (or lack thereof) to `facilitator_links`.
- No WebSocket authorization tests.

---

## 10. Files most likely to be touched by the collapse

**Schema / models**
- [app/models/meeting.py](app/models/meeting.py) — remove `MeetingFacilitator`, `meeting_facilitators_table`, `facilitator_links`, `facilitators` relations; `is_owner` concept collapses to `owner_id` alone
- [app/models/user.py](app/models/user.py) — remove `facilitator_links` relationship

**Data layer**
- [app/data/meeting_manager.py](app/data/meeting_manager.py) — remove `_should_auto_facilitate`, `_ensure_facilitator_assignment`, `_collect_facilitator_assignments`; rewrite `create_meeting`, `add_meeting`, `add_participant`, `bulk_update_participants`, `get_dashboard_meetings`; adjust dashboard response shape
- [app/data/user_manager.py](app/data/user_manager.py) — `update_user_role` no longer needs cascade (nothing to cascade to)
- [app/main.py:101](app/main.py:101) — drop `meeting_facilitators_table.create(...)` shim

**Backend enforcement**
- [app/routers/meetings.py](app/routers/meetings.py) — rewrite `_assert_meeting_access`; remove `facilitator_links` iteration everywhere
- [app/routers/users.py](app/routers/users.py), [app/routers/brainstorming.py](app/routers/brainstorming.py), [app/routers/voting.py](app/routers/voting.py), [app/routers/rank_order_voting.py](app/routers/rank_order_voting.py), [app/routers/categorization.py](app/routers/categorization.py), [app/routers/transfer.py](app/routers/transfer.py) — each has a `_ensure_user_access` / `_access` / etc. reading `facilitator_links`
- [app/routers/pages.py](app/routers/pages.py) — page role gates (minor)
- [app/routers/realtime.py](app/routers/realtime.py) — orthogonal (auth gap), may surface during rework
- [app/auth/auth.py](app/auth/auth.py) — permission inheritance (probably unchanged; the collapse doesn't touch the system-role ladder)

**Frontend**
- [app/templates/meeting.html:14-15, 59, 96-101](app/templates/meeting.html) — the visible-bug hotspot
- [app/templates/_base.html](app/templates/_base.html), [app/templates/dashboard.html](app/templates/dashboard.html), [app/templates/dashboard/_panel_*.html](app/templates/dashboard), [app/templates/settings.html](app/templates/settings.html)
- [app/static/js/meeting.js](app/static/js/meeting.js), [app/static/js/dashboard.js](app/static/js/dashboard.js)

**Export / serialization**
- [app/routers/meetings.py:273](app/routers/meetings.py:273) `_build_meeting_export_bundle` writes `facilitators[].is_owner` into export JSON → **backward compatibility consideration** for existing exported files

**Tests**
- All test files in §9.1 need updates or deletions (auto-grant assumptions disappear).

---

## 11. Open questions the terrain surfaces (not to be answered here)

1. **Delete-meeting asymmetry** — does collapse preserve "only the owner can delete" or fold it into "any system facilitator on the roster can delete"?
2. **Co-facilitator concept at meeting creation** — the create-meeting form today takes `additional_facilitator_ids`. If per-meeting facilitator role disappears, that field becomes a no-op; is the create UI changing too?
3. **Exported data backward compatibility** — does existing exported JSON with `facilitators[]` sections still need to import cleanly?
4. **WebSocket auth gap** — orthogonal to this task, but touching auth layer will make the gap more obvious. In scope or separate issue?
5. **`is_owner` flag** — currently stored on `MeetingFacilitator`. On collapse, owner-ness is purely `Meeting.owner_id`. Semantics align, but any code branching on the flag needs to switch to the FK compare.

---

## 12. Verification baseline

- Test suite baseline at audit time: `526 passed, 2 skipped, 0 failed` (from commit `4f3dac3` message).
- `facilitator_links` reference count across non-test code: ~97 occurrences across 15 files.
- Branch: `fix/role-problems`. Working tree: `plans/` files deleted (uncommitted) as part of a wipe; this discovery file is the first re-population.

---

*End of DISCOVERY. No code suggestions in this file by design. Planning, scoping, and sequencing belong to later documents.*
