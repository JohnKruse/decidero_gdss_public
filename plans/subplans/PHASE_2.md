# Phase 2 — Backend Commit Branch [COMPLETE]

**Parent:** `plans/01_MASTER_PLAN.md`
**Depends on:** `plans/subplans/PHASE_1.md` (Phase 1 complete — schema, eligibility, 501 placeholder in place)
**Global Canary:** `Turquoise Wombat`
**Phase Canary:** `Crimson Narwhal`

---

## Overview

Replace the Phase 1 `501 NOT_IMPLEMENTED` placeholder in `commit_transfer()` with a complete existing-activity commit path. When `target_activity.activity_id` is provided, the function resolves the target from the agenda, validates eligibility, maps transferred items into the target's config (same mapping logic as the create path), writes config directly to the ORM, initializes state, creates an input bundle, and broadcasts.

The create path (`activity_id` absent) remains completely unchanged.

---

## Step 1: [DONE] Extract Shared Config-Mapping Logic Into a Helper

**File:** `app/routers/transfer.py`

**Implement:**
The current `commit_transfer()` has inline config-mapping blocks for voting (lines 473-506), categorization (lines 507-540), rank_order_voting (lines 541-579), and brainstorming idea-seeding (lines 659-728). Both the create and existing-activity paths need the same mapping logic. To avoid duplication:

- Extract a pure function `_map_transfer_config(target_tool: str, config: dict, ideas: list, comments_by_parent: dict, include_comments: bool, inherited_config_from_donor: bool) -> dict` that performs the voting/categorization/rank_order_voting config mapping currently at lines 473-579. It takes the mutable `config` dict, applies the tool-type-specific mapping, and returns it. Move the mapping `if` blocks into this function verbatim.
- Extract a function `_seed_brainstorming_ideas(db: Session, meeting_id: str, activity_id: str, ideas: list, comments_by_parent: dict) -> None` from lines 659-728. This function deletes existing ideas for the target activity, inserts `Idea` rows for each idea and comment, and commits. Used by both paths.
- Both helpers are module-private (underscore prefix), placed after the existing helpers near line 200.
- The existing create path calls these helpers where the inline code was. Behavior is byte-for-byte identical.

**Test:** Run the full existing transfer test suite. Every test must pass with zero changes to assertions. This is a pure refactor — no behavioral change.
```
pytest app/tests/test_transfer_api.py -v
```

**Docs:** Add docstrings to both extracted functions:
- `_map_transfer_config`: "Apply tool-type-specific mapping of transferred ideas into the target config dict. Mutates and returns config."
- `_seed_brainstorming_ideas`: "Delete any existing ideas for the activity and insert transferred ideas and comments as Idea rows."

**Technical Deviations Logged:**
- Environment path variance: `pytest` was not available on PATH in this shell, so verification was executed with `venv/bin/pytest app/tests/test_transfer_api.py -v` instead of the bare `pytest ...` command.

---

## Step 2: [DONE] Implement Existing-Activity Config Write

**File:** `app/routers/transfer.py` — inside `commit_transfer()`, replace the Phase 1 `501 NOT_IMPLEMENTED` block.

**Implement:**
Replace the `raise HTTPException(status_code=501, ...)` block (the `Velvet Penguin` placeholder from Phase 1) with:

```python
if target.activity_id:
    existing_target = _resolve_activity(meeting, target.activity_id)
    await _assert_transfer_eligible(
        existing_target, payload.donor_activity_id, meeting_id, meeting_manager
    )
    target_tool = (existing_target.tool_type or "").strip().lower()
    # Crimson Narwhal: existing-activity commit path

    # Build config starting from the existing activity's current config.
    # Transfer items REPLACE content fields (options, items, ideas)
    # while preserving non-content config keys (max_votes, mode, etc.).
    config = dict(existing_target.config or {})
    # Force the content fields to be re-mapped from transferred items
    # by removing them so _map_transfer_config treats them as missing.
    for content_key in ("options", "items", "ideas"):
        config.pop(content_key, None)
    config = _map_transfer_config(
        target_tool, config, ideas, comments_by_parent,
        payload.include_comments, inherited_config_from_donor=False,
    )

    # Write config directly to ORM — bypass update_agenda_activity
    # to avoid its incremental-merge and lock semantics.
    existing_target.config = config
    db.add(existing_target)
    db.flush()
    ...  # Steps 3-5 continue from here
```

Key design decisions:
- **Preserve non-content config** (e.g., `max_votes`, `mode`, `allow_retract`, `randomize_order`). Only the content fields (`options`, `items`, `ideas`) are stripped and re-mapped.
- **Direct ORM write** instead of `meeting_manager.update_agenda_activity()` — avoids the incremental key-merge and lock checks that are inappropriate for a virgin-activity config replacement.
- `inherited_config_from_donor` is always `False` for existing-activity targets (the target has its own config).

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_transfer_commit_into_existing_voting_replaces_options` — Create a meeting with a brainstorming donor (with ideas, stopped) and a virgin voting activity pre-configured with `config: {"options": ["Placeholder A"], "max_votes": 5}`. Commit with `target_activity: {"activity_id": "<voting_id>"}`. Assert 200. Assert the target activity's `config.options` now contains the transferred idea content (not `["Placeholder A"]`). Assert `config.max_votes` is still `5` (preserved).

**Docs:** Add inline comment: `# Crimson Narwhal: existing-activity commit path — replaces content config, preserves settings`.

**Technical Deviations Logged:**
- Verification command was run as `venv/bin/pytest app/tests/test_transfer_api.py -v` to match the project virtualenv executable path in this shell.

---

## Step 3: [DONE] State Initialization for Existing Targets

**File:** `app/routers/transfer.py` — continuing the existing-activity branch from Step 2.

**Implement:**
After config write (Step 2), add state initialization identical to the create path (lines 590-607), but targeting `existing_target.activity_id`:

```python
    if target_tool == "voting":
        VotingManager(meeting_manager.db).reset_activity_state(
            meeting_id, existing_target.activity_id, clear_bundles=True
        )
    if target_tool == "categorization":
        cat_manager = CategorizationManager(meeting_manager.db)
        cat_manager.reset_activity_state(
            meeting_id, existing_target.activity_id, clear_bundles=True
        )
        cat_manager.seed_activity(
            meeting_id=meeting_id,
            activity=existing_target,
            actor_user_id=current_user.user_id,
        )
    if target_tool == "rank_order_voting":
        RankOrderVotingManager(meeting_manager.db).reset_activity_state(
            meeting_id, existing_target.activity_id, clear_bundles=True
        )
    if target_tool == "brainstorming":
        _seed_brainstorming_ideas(
            db, meeting_id, existing_target.activity_id,
            ideas, comments_by_parent,
        )
```

The `clear_bundles=True` on reset is safe because virgin activities have no user-generated bundles (the eligibility check already confirmed no data). The input bundle created in Step 4 will be the only bundle.

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_transfer_commit_into_existing_categorization_seeds_state` — Create a brainstorming donor (with ideas) and a virgin categorization activity with `config: {"items": ["Old card"], "buckets": [{"title": "Bucket 1"}], "mode": "FACILITATOR_LIVE"}`. Commit transfer into the categorization target. Assert 200. Assert `config.items` contains the transferred ideas (not `["Old card"]`). Assert `config.buckets` is still present. Query `CategorizationItem` table for the target activity — assert items exist and match the transferred content.

- `test_transfer_commit_into_existing_brainstorming_seeds_ideas` — Create a brainstorming donor (with two ideas and a comment) and a virgin brainstorming target. Commit transfer. Assert 200. Query `Idea` table for the target activity — assert idea rows exist matching the transferred content, including the comment with correct `parent_id`.

**Docs:** Add inline comment: `# State init for existing target — identical to create path, safe because target is virgin`.

**Technical Deviations Logged:**
- Verification used `venv/bin/pytest app/tests/test_transfer_api.py -v` due to shell PATH not exposing `pytest` directly.

---

## Step 4: [DONE] Input Bundle, Metadata, Broadcast & Response

**File:** `app/routers/transfer.py` — completing the existing-activity branch.

**Implement:**
After state init (Step 3), add the bundle creation, metadata, broadcast, and response — mirroring the create path but with `existing_target` in place of `created`:

```python
    # -- Bundle + metadata (same as create path) --
    bundle_metadata = dict(payload.metadata or {})
    round_index = _resolve_round_index(metadata=bundle_metadata, donor=donor)
    bundle_metadata = ensure_transfer_metadata(
        base=bundle_metadata,
        meeting_id=meeting_id,
        source_activity_id=payload.donor_activity_id,
        source_tool_type=donor.tool_type,
        round_index=round_index,
        tool_type="transfer",
        tool_details={
            "include_comments": payload.include_comments,
            "idea_count": len(ideas),
            "comment_count": sum(len(e) for e in comments_by_parent.values()),
        },
    )
    append_transfer_history(
        metadata=bundle_metadata,
        tool_type="transfer_commit",
        activity_id=payload.donor_activity_id,
        details={
            "target_tool_type": target_tool,
            "target_activity_id": existing_target.activity_id,
            "target_mode": "existing",
            "include_comments": payload.include_comments,
            "idea_count": len(ideas),
            "comment_count": sum(len(e) for e in comments_by_parent.values()),
        },
        created_at=bundle_metadata.get("created_at"),
    )
    bundle_metadata.update({
        "source_activity_id": payload.donor_activity_id,
        "include_comments": payload.include_comments,
        "comments_by_parent": comments_by_parent,
    })
    bundle_metadata = ensure_transfer_metadata(
        base=bundle_metadata,
        meeting_id=meeting_id,
        source_activity_id=payload.donor_activity_id,
        source_tool_type=donor.tool_type,
        round_index=round_index,
        tool_type=target_tool,
        tool_details={
            "activity_id": existing_target.activity_id,
            "title": existing_target.title,
        },
    )
    bundle_manager = ActivityBundleManager(db)
    input_bundle = bundle_manager.create_bundle(
        meeting_id, existing_target.activity_id, "input", ideas, bundle_metadata
    )

    # -- Broadcast + state patch --
    await _broadcast_agenda_update(meeting_id, current_user.user_id, meeting_manager)
    await meeting_state_manager.apply_patch(
        meeting_id,
        {
            "currentActivity": existing_target.activity_id,
            "agendaItemId": existing_target.activity_id,
            "currentTool": existing_target.tool_type,
            "status": "stopped",
        },
    )

    # -- Response --
    agenda_items = meeting_manager.list_agenda(meeting_id)
    return {
        "target_activity": AgendaActivityResponse.model_validate(existing_target).model_dump(),
        "new_activity": None,  # backward compat — no new activity was created
        "agenda": [
            AgendaActivityResponse.model_validate(item).model_dump()
            for item in agenda_items
        ],
        "input_bundle_id": input_bundle.bundle_id,
    }
```

Notable differences from create path:
- `new_activity` is `None` (no activity was created).
- `target_activity` contains the existing activity's data (post-config-update).
- Transfer metadata history includes `"target_mode": "existing"` and `"target_activity_id"`.

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_transfer_commit_into_existing_response_shape` — Perform a transfer-into-existing-voting commit. Assert response contains `target_activity` with the existing activity's `activity_id`, `new_activity` is `None`, `agenda` is a list, `input_bundle_id` is a string. Assert the agenda list length did NOT increase (no new activity created).

- `test_transfer_commit_into_existing_creates_input_bundle` — After a transfer-into-existing commit, query `ActivityBundle` for the target activity with `kind="input"`. Assert exactly one bundle exists and its `items` match the transferred ideas. Assert `bundle_metadata` contains `"target_mode": "existing"` in the transfer history.

**Docs:** Add inline comment above the response: `# target_activity is the canonical key; new_activity is None for existing-target transfers`.

**Technical Deviations Logged:**
- Verification used `venv/bin/pytest app/tests/test_transfer_api.py -v` due to shell PATH not exposing `pytest` directly.

---

## Step 5: [DONE] Transfer Into Existing Rank Order Voting

**File:** `app/routers/transfer.py` — already handled by `_map_transfer_config` (Step 1) and state init (Step 3), but needs a targeted integration test.

**Implement:**
No additional code changes. The rank_order_voting path in `_map_transfer_config` strips `config.ideas` (Step 2) and remaps from transferred items. State init calls `RankOrderVotingManager.reset_activity_state()`. This step is test-only.

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_transfer_commit_into_existing_rank_order_voting_populates_ideas` — Create a brainstorming donor (with ideas) and a virgin rank_order_voting activity with `config: {"ideas": [{"id": 1, "content": "Placeholder"}], "randomize_order": true, "allow_reset": false}`. Commit transfer. Assert 200. Assert `config.ideas` contains entries with `content` matching the transferred ideas. Assert `config.randomize_order` is still `true` and `config.allow_reset` is still `false` (preserved settings). Assert `new_activity` is `None`.

**Docs:** No additional docs. The `_map_transfer_config` docstring (Step 1) already covers all four tool types.

**Technical Deviations Logged:**
- Verification used `venv/bin/pytest app/tests/test_transfer_api.py -v` due to shell PATH not exposing `pytest` directly.

---

## Step 6: [DONE] Sequential Transfer (Replace-on-Retransfer) & AI-Prepopulated Config

**File:** `app/routers/transfer.py` — no code changes needed; this step validates edge cases.

**Implement:**
The existing-activity path (Steps 2-4) already handles retransfer correctly:
- Content config keys are stripped and re-mapped on every commit.
- State reset clears prior bundles and state.
- For brainstorming, `_seed_brainstorming_ideas` deletes all existing ideas before inserting new ones.

No additional code. This step is test-only.

**Test:** Add to `app/tests/test_transfer_api.py`:
- `test_transfer_commit_into_existing_twice_replaces_first` — Create a brainstorming donor with ideas "Alpha" and "Beta", and a virgin voting target. Commit transfer (Alpha, Beta arrive as options). Then create a second brainstorming donor with ideas "Gamma" and "Delta" on the same meeting. Commit a second transfer into the same voting target (still virgin — never started). Assert 200. Assert `config.options` is `["Gamma", "Delta"]`, NOT `["Alpha", "Beta"]`. Assert only one input bundle exists for the target (the second commit's `clear_bundles=True` during state reset removes the first).

- `test_transfer_commit_into_existing_replaces_ai_prepopulated_config` — Create a voting activity with `config: {"options": ["AI Option 1", "AI Option 2", "AI Option 3"], "max_votes": 2}` (simulating AI designer output). Create a brainstorming donor with one idea "Human Idea". Commit transfer into the voting target. Assert `config.options` is `["Human Idea"]`. Assert `config.max_votes` is still `2`.

**Docs:** No additional docs.

**Technical Deviations Logged:**
- Although Step 6 was scoped as test-only, implementation needed a small eligibility refinement in `app/routers/transfer.py`: `_assert_transfer_eligible` now checks for participant-generated data (ideas, votes, categorization activity) directly, so bundle-only prior transfers do not block retransfer.
- Verification used `venv/bin/pytest app/tests/test_transfer_api.py -v` due to shell PATH not exposing `pytest` directly.

---

## Step 7: [DONE] Phase Canary Verification & Regression Sweep

**No new code.** Verification gate.

**Implement:**
- Remove the `Velvet Penguin` placeholder comment from `transfer.py` (it was replaced by real code in Step 2).
- Grep the codebase for `Crimson Narwhal` — should appear only in the inline comment added in Step 2.
- Grep for `Velvet Penguin` — should no longer appear in any source file (only in plan docs).
- Grep for `Turquoise Wombat` — should not appear in source code.

**Test:** Run the full transfer + meeting test suite:
```
pytest app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_transfer_comment_format_parity.py -v
```
All pre-existing tests must pass. All new Phase 2 tests must pass.

**Docs:** Confirm all docstrings and inline comments from Steps 1-6 are present.

**Technical Deviations Logged:**
- Canary verification was executed across `app`, `docs`, and `scripts` paths (instead of a global repo grep) to avoid plan-file matches by design.
- Verification used `venv/bin/pytest app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_transfer_comment_format_parity.py -v` due to shell PATH not exposing `pytest` directly.

---

## Phase Exit Criteria

The following command must pass at 100%:

```bash
pytest app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_transfer_comment_format_parity.py -v
```

**Specific assertions:**
- `_map_transfer_config` and `_seed_brainstorming_ideas` extraction causes zero regressions (Step 1)
- `test_transfer_commit_into_existing_voting_replaces_options` passes — config.options replaced, max_votes preserved (Step 2)
- `test_transfer_commit_into_existing_categorization_seeds_state` passes — items replaced, CategorizationItem rows created (Step 3)
- `test_transfer_commit_into_existing_brainstorming_seeds_ideas` passes — Idea rows created with correct parent_id (Step 3)
- `test_transfer_commit_into_existing_response_shape` passes — target_activity present, new_activity is None, agenda unchanged length (Step 4)
- `test_transfer_commit_into_existing_creates_input_bundle` passes — bundle exists with correct metadata (Step 4)
- `test_transfer_commit_into_existing_rank_order_voting_populates_ideas` passes — ideas mapped, settings preserved (Step 5)
- `test_transfer_commit_into_existing_twice_replaces_first` passes — second transfer overwrites first (Step 6)
- `test_transfer_commit_into_existing_replaces_ai_prepopulated_config` passes — AI config replaced by human content (Step 6)
- All pre-existing transfer tests pass unchanged (Step 7)
- `Crimson Narwhal` canary appears only in the expected inline comment
- `Velvet Penguin` no longer appears in source files
