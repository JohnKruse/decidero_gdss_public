# PHASE 4 [COMPLETE] — Data Model Collapse

**Parent plan:** [plans/01_MASTER_PLAN.md](plans/01_MASTER_PLAN.md)

**Phase objective:** Remove the per-meeting facilitator concept from the persistent data model and runtime object graph so the schema itself matches the collapsed authorization design already enforced by earlier phases.

## Phase Canary

**Noodle Catapult**

Use this exact two-word canary in Phase 4 notes, commit messages, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 [DONE] — Identify and Isolate Persistent Facilitator Artifacts
Map the remaining schema, ORM, startup, and runtime references that still treat per-meeting facilitator assignment as a persisted model concern. This includes `MeetingFacilitator`, `meeting_facilitators` storage, ORM relationships on `Meeting` and `User`, any startup shim that creates or expects the table, and any helper whose sole purpose is managing facilitator assignments as stored rows.

Conclude this step by:
- Implementing the core logic as the complete removal map for persistent facilitator artifacts targeted in this phase.
- Creating or updating the relevant pytest file, preferring edits to existing model/meeting/API pytest modules over creating a new pytest file unless an existing suite cannot reasonably carry the coverage.
- Updating docstrings and documentation so the Phase 4 `Noodle Catapult` scope clearly states which persistent facilitator constructs are being eliminated now versus which outward-facing compatibility concerns are deferred to Phase 5.

Step 1 inventory for `Noodle Catapult`:

| File / surface | Persistent facilitator artifact isolated in Step 1 | Removal phase target |
|---|---|---|
| `app/models/meeting.py` | `MeetingFacilitator`, `meeting_facilitators_table`, `Meeting.facilitator_links`, `Meeting.facilitators` | Step 2 |
| `app/models/user.py` | `MeetingFacilitator` import bridge, `meeting_facilitators_table`, `User.facilitator_links`, `User.facilitated_meetings` | Step 2 |
| `app/models/__init__.py` | Re-export of `MeetingFacilitator` as an active model symbol | Step 2 |
| `app/main.py` | Startup shim calling `meeting_facilitators_table.create(..., checkfirst=True)` | Step 3 |
| `app/data/meeting_manager.py` | Meeting creation/update helpers that create, mutate, eager-load, or sort facilitator assignment rows, including `_ensure_facilitator_assignment` and `_collect_facilitator_assignments` | Step 3 |
| `app/utils/identifiers.py` | `generate_facilitator_id` and its sequence helpers keyed to `MeetingFacilitator` rows | Step 3 |
| `app/routers/brainstorming.py`, `app/routers/categorization.py`, `app/routers/transfer.py`, `app/routers/voting.py` | Router imports and eager-load paths that still depend on `MeetingFacilitator` / `facilitator_links` | Step 3 |
| `app/routers/meetings.py` | Export/import compatibility bundle still reading `meeting.facilitator_links`; request payloads still accept facilitator-oriented compatibility fields | Step 4 / Phase 5 |
| `app/services/meeting_authorization.py` and `app/schemas/meeting.py` | Backend-derived compatibility outputs (`facilitators`, `facilitator_ids`, `facilitator_user_ids`) still emitted for outward-facing contract stability | Phase 5 |
| Existing pytest modules | Legacy assertions that inspect `facilitator_links`, facilitator IDs, or auto-assignment behavior as persisted-row facts | Step 4 |

### Step 2 [DONE] — Collapse the ORM and Schema Model
Remove `MeetingFacilitator`, the `meeting_facilitators` storage model, related ORM relationships, and any persisted ownership duplication that survives outside `Meeting.owner_id`. After this step, the active data model must express meeting authority only through global role, owner linkage, and roster membership, with no live facilitator-assignment entity left in the application schema.

Conclude this step by:
- Implementing the core logic by collapsing the ORM/schema model to eliminate persisted per-meeting facilitator assignment.
- Creating or updating the relevant pytest file, favoring surgical edits to existing suites such as `app/tests/test_meeting_manager.py`, `app/tests/test_api_meetings.py`, `app/tests/test_api_participants.py`, and `app/tests/test_auth.py` instead of creating a new test file.
- Updating docstrings and documentation so model descriptions, relationship descriptions, and test narratives no longer present facilitator assignments as a live persisted concept.

Step 2 collapse notes for `Noodle Catapult`:

- `MeetingFacilitator` and `meeting_facilitators_table` have been removed from the active SQLAlchemy model registry.
- `Meeting.facilitator_links`, `Meeting.facilitators`, `User.facilitator_links`, and `User.facilitated_meetings` have been removed from the active ORM mappings.
- Owner authority now persists only as `Meeting.owner_id`; roster-scoped facilitator authority is derived from `User.role == "facilitator"` plus meeting participant membership.
- Meeting-manager regression coverage now asserts the absence of the removed ORM model/table and verifies owner/co-facilitator behavior through canonical capabilities instead of persisted facilitator rows.

### Step 3 [DONE] — Remove Runtime and Boot Dependencies on the Old Model
Delete or rewrite runtime helpers, initialization shims, and meeting-management paths that still create, mutate, or expect facilitator-assignment rows to exist. The application must be able to boot, create meetings, manage rosters, and execute meeting workflows without any facilitator-assignment table or startup workaround present.

Conclude this step by:
- Implementing the core logic by removing runtime and startup dependencies on the old facilitator persistence model.
- Creating or updating the relevant pytest file, preferring edits to existing meeting/API/router suites such as `app/tests/test_meeting_manager.py`, `app/tests/test_api_meetings.py`, `app/tests/test_api_participants.py`, `app/tests/test_brainstorming_api.py`, `app/tests/test_voting_api.py`, `app/tests/test_rank_order_voting_api.py`, `app/tests/test_categorization_api.py`, and `app/tests/test_transfer_api.py` instead of adding new pytest modules.
- Updating docstrings and documentation so runtime behavior and startup expectations describe the collapsed model accurately.

Step 3 runtime notes for `Noodle Catapult`:

- Removed the no-op facilitator-assignment helpers from `MeetingManager`; participant and roster mutations no longer call a facilitator-row synchronization path.
- Removed the obsolete `generate_facilitator_id` compatibility helper from `app/utils/identifiers.py`; active runtime code no longer generates row-backed facilitator identifiers.
- Removed the stale `facilitated_meetings` dashboard context placeholder from `app/routers/pages.py`.
- Added regression coverage that scans the active runtime/boot files for the old helper and startup symbols.

### Step 4 [DONE] — Prune Dead Code and Legacy Test Assumptions
Remove helper code, relationship plumbing, and test assumptions whose only purpose was to support persisted facilitator assignments or auto-grant behavior. By the end of this step, old facilitator-model code should be absent from the active application path, and tests should assert the collapsed steady state rather than carrying transitional assumptions forward.

Conclude this step by:
- Implementing the core logic by pruning dead facilitator-model code and resolving Phase 1 rewrite/delete items that are unblocked by schema removal.
- Creating or updating the relevant pytest file, favoring edits to the already-relevant suites instead of creating a new test file for cleanup work.
- Updating docstrings and documentation so no active description of the model or tests still relies on per-meeting facilitator persistence semantics.

Step 4 cleanup notes for `Noodle Catapult`:

- Removed the legacy JSON data-access fallback that treated `facilitator_user_ids` as a meeting membership source.
- Removed schema coercion for deleted `facilitator_links` / `facilitator_id` relationship objects; surviving facilitator-shaped response fields now accept only dict-shaped compatibility payloads until Phase 5 removes the external contract.
- Converted the Step 1 inventory regression into a steady-state documentation regression and added a guard against active code reading removed facilitator persistence fields.
- Updated test narratives that still described the old row-backed model as the comparison point.

### Step 5 [DONE] — Lock the Phase 4 Verification Boundary
Define the exact validation command for the schema/runtime collapse and treat this phase as complete only when the application functions without the facilitator-assignment model, the targeted suites pass, and the removed model is absent from active code paths within the scope of this phase.

Conclude this step by:
- Implementing the core logic as the final Phase 4 verification checklist and completion notes in this file.
- Creating or updating the relevant pytest file so the data-model-collapse coverage required for Phase 4 is included in the exit command below without unnecessary pytest file proliferation.
- Updating docstrings and documentation so the verification command, collapse boundary, and Phase 4 canary remain aligned.

Step 5 verification notes for `Noodle Catapult`:

- The final Phase 4 verification boundary is the command in the Phase Exit Criteria section below.
- Phase 4 is complete when that command finishes at `[100%]` with all runnable tests passing and only the expected guest-join feature skips.
- The active schema, boot path, runtime helper path, and tests no longer depend on persisted per-meeting facilitator assignment rows.
- Remaining facilitator-shaped response names are intentionally Phase 5 compatibility work and are not active persistence-model dependencies.

## Phase 4 Collapse Scope Map

The following persistent-model surfaces must be collapsed during this phase:

| Surface | Required Phase 4 outcome |
|---|---|
| `MeetingFacilitator` model | Removed from active application schema |
| `meeting_facilitators` table/storage definition | Removed from active application schema/runtime expectations |
| `Meeting.facilitator_links` / `Meeting.facilitators` relationships | Removed |
| `User.facilitator_links` relationship | Removed |
| Facilitator-assignment startup shim | Removed |
| Facilitator-assignment-specific helpers | Removed or rewritten so they no longer depend on persisted facilitator rows |

## Phase 4 Non-Goals

This phase does **not** complete the following:

- Export/import compatibility handling and outward-facing contract cleanup, which belongs to Phase 5.
- Additional UI/interface alignment work beyond what earlier phases already established.
- WebSocket auth cleanup or unrelated authorization redesign outside the facilitator-model removal path.

## Technical Deviations Log

- Step 1 (`Noodle Catapult`): The isolation pass intentionally keeps outward-facing compatibility fields such as `facilitator_ids`, `facilitator_user_ids`, export/import facilitator payloads, and derived facilitator summaries in place for now. Those surfaces are documented as deferred so Step 2 and Step 3 can remove the persistent model first without mixing schema collapse with API contract cleanup that belongs to Phase 5.
- Step 2 (`Noodle Catapult`): Removing the SQLAlchemy model required eliminating import-time eager-load references and the startup table-creation shim in the same step; otherwise the application could not import after the model registry stopped exposing `MeetingFacilitator`. Follow-on runtime helper cleanup was completed in Step 3.
- Step 3 (`Noodle Catapult`): The active runtime cleanup intentionally leaves facilitator-named response schemas and derived compatibility output classes in place because those are outward-facing API contract cleanup work for Phase 5, not runtime dependencies on the removed persistence model.
- Step 4 (`Noodle Catapult`): Facilitator-shaped API response names and create/import compatibility inputs remain by design for Phase 5. This step prunes only active code and tests that still depended on the removed persisted facilitator model or relationship objects.
- Step 5 (`Noodle Catapult`): The final verification run includes two expected guest-join skips because guest access remains feature-flagged; they are not Phase 4 schema/runtime collapse failures.

## Phase Exit Criteria

Phase 4 clears only when the following command passes 100%:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_auth.py app/tests/test_meeting_manager.py app/tests/test_api_meetings.py app/tests/test_api_participants.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_rank_order_voting_api.py app/tests/test_categorization_api.py app/tests/test_transfer_api.py app/tests/test_pages.py app/tests/test_frontend_smoke.py -v
```

Passing this command means:
- the active schema and runtime model no longer rely on persisted per-meeting facilitator assignments,
- the selected existing pytest modules have been updated instead of unnecessarily duplicated,
- meeting workflows still function after removal of the facilitator-assignment model,
- and documentation/docstrings describe the collapsed persistent model accurately.

---

*End of Phase 4 execution file. This phase removes the persistent facilitator model and its runtime dependencies; outward-facing compatibility cleanup remains Phase 5 work.*
