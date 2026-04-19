# Phase 1 [COMPLETE] — Purge Dummy Data Origins

**Phase canary:** `Turbulent Ketchup`

**Parent:** `plans/01_MASTER_PLAN.md` (Project canary: `Velvet Prosciutto`)

**Objective:** Eliminate every source of placeholder/dummy content that gets baked into fresh activities at creation time, so that `_assert_transfer_eligible()` no longer false-rejects pristine transfer targets.

---

## Step 1 [DONE]: Strip the voting plugin manifest placeholder

The voting plugin's `default_config` ships `"options": ["Edit vote option here"]`. This string has no functional purpose — `VotingManager._extract_options()` and the frontend's `renderVotingSummary()` both handle `[]` gracefully (see Discovery sections 3.1 and 4.2). Replace it with an empty list.

**Files:**

| File | Location | Current | Target |
|------|----------|---------|--------|
| `app/plugins/builtin/voting_plugin.py` | Line 20, `default_config` | `"options": ["Edit vote option here"]` | `"options": []` |

**Implementation:**
- Change the single line in the manifest's `default_config` dict.
- Update the module docstring or inline comment to note that empty options are valid and render the facilitator "Edit options" CTA in the UI.

**Test:**
- In `app/tests/test_meeting_manager.py`, add a test `test_voting_default_config_has_empty_options` that creates a voting activity with **no** caller-provided config, retrieves it, and asserts `config["options"] == []`.
- Existing test `test_add_voting_config_rejects_object_placeholder_lines` (line 676) must still pass unchanged — it tests `[object Object]` rejection, not placeholder content.

**Docs:**
- Add a one-line comment above the `default_config` dict: `# options intentionally empty; UI shows "Edit options" CTA for facilitators`.

---

## Step 2 [DONE]: Strip the rank-order voting frontend placeholder

The backend plugin manifest already has `"ideas": []`, but the **frontend** carries a stale placeholder:

| File | Location | Current | Target |
|------|----------|---------|--------|
| `app/static/js/meeting.js` | Line 153 | `ideas: ["Edit ranked idea here"]` | `ideas: []` |
| `app/templates/create_meeting.html` | Line 216 | `ideas: ['Edit ranked idea here']` | `ideas: []` |

These are the client-side tool catalogs used by the transfer panel and the meeting creation form. They must match the backend manifest.

**Implementation:**
- Replace both instances with empty arrays.
- Note: `create_meeting.html` also has `options: ['Edit vote option here']` at line 208 — change it to `options: []` in lockstep with Step 1.

**Test:**
- No new pytest needed. The existing `test_frontend_smoke.py` validates HTML/JS integrity. Run it to confirm no syntax errors were introduced.
- Optionally verify in `test_meeting_manager.py` that a rank-order activity created with no caller config gets `config["ideas"] == []` (analog to the Step 1 test).

**Docs:**
- Add a JS comment in both files above the default_config block: `// options/ideas intentionally empty — backend is the source of truth for defaults`.

---

## Step 3 [DONE]: Add placeholder detection for voting in `_map_transfer_config()`

Categorization already detects placeholder strings (`"edit item here"`, `"one idea per line."`) at `transfer.py:438-442` and treats them as "items missing." Voting has **no** equivalent guard — if a voting activity is created with `["Edit vote option here"]` and later becomes a transfer target, the stale placeholder would survive as a real option.

With Step 1 deployed, new activities won't carry the placeholder. But existing activities in the wild may still have it. Add a parallel guard for voting.

**Files:**

| File | Location | Change |
|------|----------|--------|
| `app/routers/transfer.py` | Inside `_map_transfer_config()`, voting branch (around line 401) | After `use_transferred_options = inherited_config_from_donor or not config.get("options")`, add a fallthrough that also sets `use_transferred_options = True` if the existing options normalize to `["edit vote option here"]` |

**Implementation:**
- Mirror the categorization pattern: normalize the existing options to lowercase-stripped strings and compare against `["edit vote option here"]`.
- Also add `["edit ranked idea here"]` to the rank-order voting branch at line 465 for the same reason.

**Test:**
- In `app/tests/test_transfer_api.py`, add a test `test_transfer_commit_replaces_voting_placeholder_options` that:
  1. Creates a meeting with a donor brainstorming activity and a target voting activity whose config is `{"options": ["Edit vote option here"], "max_votes": 3}`.
  2. Seeds a real idea into the donor.
  3. Commits transfer into the target.
  4. Asserts the target's config now has `options == ["<the real idea>"]`, not `["Edit vote option here", "<the real idea>"]`.

**Docs:**
- Update the `_map_transfer_config()` docstring to note that placeholder strings are treated as empty for all tool types.

---

## Step 4 [DONE]: Audit `_validate_activity_config_placeholders()` for empty-array safety

`meeting_manager.py:177-206` validates that config arrays don't contain `[object Object]` strings. It iterates the array values with `any(...)`. If the array is `[]`, the `any(...)` call returns `False` immediately — this is safe. But we need to confirm it doesn't implicitly reject empty arrays or raise on `None`.

**Files:**

| File | Location | Change |
|------|----------|--------|
| `app/data/meeting_manager.py` | `_contains_object_placeholder()` (line 166) and `_validate_activity_config_placeholders()` (line 177) | Read and confirm behavior. Add explicit guard if `value` is `None`. |

**Implementation:**
- Read `_contains_object_placeholder()`. If `value` is `None` or not a list, confirm it returns `False` without raising.
- If it does raise, add `if not value: return False` at the top.
- This is an audit step — if no code change is needed, document why in a comment.

**Test:**
- In `app/tests/test_meeting_manager.py`, add a test `test_activity_config_accepts_empty_options_list` that creates a voting activity with `config={"options": []}` and asserts it succeeds (no 422 error).
- Add a companion `test_activity_config_accepts_none_options` that creates a voting activity with `config={"options": None}` and asserts it succeeds or produces a clean validation error (not an unhandled exception).

**Docs:**
- Add a comment in `_contains_object_placeholder()` noting that empty/None values are intentionally accepted.

---

## Step 5 [DONE]: Locate and remove any branch-local dummy Idea seeding

The discovery's exhaustive search found **no** mainline code that auto-creates `Idea` rows in fresh activities. But the user reported that activities were "seeded with a dummy idea." This means the seeding is either:
- A branch-specific change on the current branch (`codex/meeting-designer-green`)
- A manual workaround applied during development
- Injected via the meeting designer AI's agenda generation

**Files:**
- Run `git diff main -- '*.py'` to identify all changes on the current branch that touch `Idea(` or `add_idea`.
- Search the meeting designer router (`app/routers/meeting_designer.py`) and its AI prompt templates for any instructions that tell the LLM to include "ideas" or "seed" content in brainstorming activities.
- Search `app/templates/create_meeting.html` for any JS that auto-populates idea content during activity creation.

**Implementation:**
- If branch-specific Idea seeding is found: remove it.
- If the meeting designer AI generates activities with pre-populated ideas in config: modify the prompt or post-processing to strip idea content from brainstorming activities (brainstorming `open_activity()` ignores config entirely, so config-level ideas would be vestigial).
- If no seeding code is found: document the conclusion in a code comment in `transfer.py` near `_assert_transfer_eligible()` noting that fresh activities have zero Idea rows by design.

**Test:**
- In `app/tests/test_transfer_api.py`, add a test `test_fresh_activity_has_no_idea_rows` that:
  1. Creates a meeting with one brainstorming activity (no ideas submitted).
  2. Queries `db.query(Idea).filter(activity_id=...).count()` and asserts it equals 0.
  3. Creates a voting, categorization, and rank-order activity similarly and asserts zero Idea rows for each.

**Docs:**
- Add a comment in `_assert_transfer_eligible()` above the `Idea` query: `# Fresh activities must have zero Idea rows. See plans/00_DISCOVERY.md Section 10.`

---

## Step 6 [DONE]: Verify the categorization placeholder list is complete

`_map_transfer_config()` at `transfer.py:438-442` detects two placeholder strings for categorization: `["edit item here"]` and `["one idea per line."]`. The `create_meeting.html` template at line 449 uses `'One idea per line.'` as a textarea placeholder and at line 445 as hint text. Verify no other UI-generated placeholders can leak into config.

**Files:**

| File | Location | Check |
|------|----------|-------|
| `app/templates/create_meeting.html` | Lines 440-490 | Confirm categorization textarea placeholders and hint text |
| `app/static/js/meeting.js` | Transfer panel / activity config rendering | Confirm no other default strings |
| `app/routers/transfer.py` | Lines 438-442 | Confirm the detection list is exhaustive |

**Implementation:**
- Cross-reference every placeholder/hint string in `create_meeting.html` against the detection list in `_map_transfer_config()`.
- If any additional strings are found (e.g., `"One bucket/category per line."` for buckets), add them to the detection list.
- Ensure detection is case-insensitive and whitespace-trimmed (it already normalizes via `.strip().lower()`).

**Test:**
- In `app/tests/test_transfer_api.py`, add `test_transfer_categorization_replaces_placeholder_items` that:
  1. Creates a target categorization activity with `config={"items": ["One idea per line."], "buckets": []}`.
  2. Transfers real ideas into it.
  3. Asserts the target's config items contain only the transferred ideas, not the placeholder string.
- Existing test `test_transfer_commit_to_categorization_populates_items` should still pass.

**Docs:**
- Add a comment above the placeholder list in `_map_transfer_config()`: `# Placeholder strings from create_meeting.html UI hints. Keep in sync with template.`

---

## Step 7 [DONE]: Run Phase 1 validation suite

Execute all tests touched or created in Steps 1-6 to confirm nothing regressed and all new assertions hold.

**Implementation:**
- No new code. This is the gate-check step.

**Test:**
- Run the full validation command (see Phase Exit Criteria below).
- If any test fails, triage and fix before exiting this phase.

**Docs:**
- Once green, add a brief log entry at the bottom of this file recording the pass timestamp and any notes.

---

## Phase Exit Criteria

The following command must pass 100% to clear Phase 1:

```bash
pytest app/tests/test_transfer_api.py app/tests/test_meeting_manager.py app/tests/test_activity_plugins.py app/tests/test_voting_api.py app/tests/test_frontend_smoke.py -v --tb=short 2>&1 | tail -40
```

**Specific assertions that must hold:**
1. `test_voting_default_config_has_empty_options` — PASS
2. `test_activity_config_accepts_empty_options_list` — PASS
3. `test_transfer_commit_replaces_voting_placeholder_options` — PASS
4. `test_fresh_activity_has_no_idea_rows` — PASS
5. `test_transfer_categorization_replaces_placeholder_items` — PASS
6. `test_transfer_eligible_rejects_activity_with_data` — PASS (existing, must not regress)
7. `test_add_voting_config_rejects_object_placeholder_lines` — PASS (existing, must not regress)
8. All other existing tests in the listed files — PASS

---

## Technical Deviations Log

- 2026-03-08: Step 1 executed as specified with no technical deviations.
- 2026-03-08: Step 2 executed as specified with no technical deviations.
- 2026-03-08: Step 3 executed as specified with no technical deviations.
- 2026-03-09: Step 4 executed as specified with no technical deviations.
- 2026-03-09: Step 5 executed as specified with no technical deviations.
- 2026-03-09: Step 6 executed as specified with no technical deviations.
- 2026-03-09: Step 7 executed as specified with no technical deviations.
- 2026-03-09 16:54 Europe/Rome: Phase 1 validation suite passed (`106 passed`).
