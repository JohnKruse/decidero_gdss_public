# PHASE 5 — Compatibility and Contract Cleanup

**Parent plan:** [plans/01_MASTER_PLAN.md](plans/01_MASTER_PLAN.md)

**Phase objective:** Normalize outward-facing contracts so active APIs, exports, imports, serialized meeting payloads, and tests reflect the collapsed authorization model without leaving legacy facilitator semantics in the live contract.

## Phase Canary

**Pickle Trombone**

Use this exact two-word canary in Phase 5 notes, commit messages, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — Inventory the Remaining External Contract Surface
Identify every outward-facing contract element that can still leak the old facilitator model after Phase 4, including meeting payload fields, dashboard summaries, export bundle contents, transfer/import schemas, and any test assertions that still validate legacy facilitator artifacts as if they were part of the intended active API. The output of this step is a complete cleanup ledger for all remaining public-facing contract debt.

Conclude this step by:
- Implementing the core logic as the complete Phase 5 ledger of remaining API/export/import/test contract elements tied to the old facilitator model.
- Creating or updating the relevant pytest file, preferring edits to existing API/transfer/meeting pytest modules over creating a new pytest file unless an existing suite cannot reasonably carry the contract-cleanup coverage.
- Updating docstrings and documentation so the Phase 5 `Pickle Trombone` scope clearly distinguishes active contract cleanup from narrowly-isolated backward-compatibility handling.

### Step 2 — Remove Legacy Facilitator Semantics from Active API Responses
Clean the live API surface so active responses no longer expose `facilitator_links`, facilitator-assignment arrays, `is_owner`-style facilitator-row semantics, or equivalent remnants of the old model. Any capability or meeting-authority fields that remain must describe the collapsed model directly and be consumed as such by dependent code and tests.

Conclude this step by:
- Implementing the core logic by removing old facilitator semantics from active API response contracts.
- Creating or updating the relevant pytest file, favoring surgical edits to existing suites such as `app/tests/test_api_meetings.py`, `app/tests/test_api_participants.py`, `app/tests/test_meeting_manager.py`, and related API-facing tests instead of creating a new test file.
- Updating docstrings and documentation so active API contracts and test descriptions describe only the collapsed authority model.

### Step 3 — Isolate Legacy Import/Export Compatibility
Rewrite export and transfer-facing contracts so newly produced artifacts no longer encode the old facilitator model while preserving only the minimum one-way compatibility needed to read older serialized meeting data. Legacy compatibility must be explicitly isolated to compatibility handling and must not re-enter the active authorization path or active API contract.

Conclude this step by:
- Implementing the core logic by separating active export/import contracts from narrowly-scoped legacy compatibility handling.
- Creating or updating the relevant pytest file, preferring edits to existing suites such as `app/tests/test_transfer_api.py`, `app/tests/test_transfer_transforms.py`, `app/tests/test_transfer_metadata.py`, `app/tests/test_transfer_comment_format_parity.py`, and other already-relevant transfer/export tests instead of adding new pytest modules.
- Updating docstrings and documentation so export/import expectations clearly state what the system now writes, what legacy data it can still read, and that compatibility handling is one-way.

### Step 4 — Purge Legacy Test Assumptions and Contract Language
Resolve the remaining Phase 1 rewrite/delete ledger items that encoded stale auto-grant behavior, facilitator-row persistence, or old payload shapes as intended behavior. By the end of this step, the test suite and its naming/docstrings must reinforce only the collapsed model and its intentionally isolated compatibility exceptions.

Conclude this step by:
- Implementing the core logic by purging stale contract assumptions from tests and any supporting code comments or references.
- Creating or updating the relevant pytest file, favoring edits to the existing affected suites instead of creating a new test file for cleanup work.
- Updating docstrings and documentation so no active test or repository narrative still treats the old facilitator contract as intended behavior.

### Step 5 — Lock the Phase 5 Verification Boundary
Define the exact validation command for outward-facing contract cleanup and treat this phase as complete only when active contracts are free of old facilitator semantics, legacy import compatibility is isolated, and the selected suites pass with the collapsed model represented consistently across APIs, exports, imports, and tests.

Conclude this step by:
- Implementing the core logic as the final Phase 5 verification checklist and completion notes in this file.
- Creating or updating the relevant pytest file so the contract-cleanup coverage required for Phase 5 is included in the exit command below without unnecessary pytest file proliferation.
- Updating docstrings and documentation so the verification command, compatibility boundary, and Phase 5 canary remain aligned.

## Phase 5 Contract Cleanup Scope Map

The following outward-facing surfaces must be normalized during this phase:

| Surface | Required Phase 5 outcome |
|---|---|
| Active meeting/dash/API payloads | No live facilitator-assignment contract artifacts remain |
| Export bundle output | No new export writes old facilitator structures |
| Legacy import/transfer readers | Old facilitator-bearing artifacts can be read only through isolated one-way compatibility handling |
| Test suite contract language | No old facilitator semantics are asserted as intended active behavior |
| Repository documentation for contracts | Describes collapsed model plus explicit compatibility exception only |

## Phase 5 Non-Goals

This phase does **not** complete the following:

- Broad end-to-end merge-readiness verification across the entire application surface, which belongs to Phase 6.
- New authorization model design work; Phase 5 cleans contracts, it does not redefine authority rules.
- WebSocket auth cleanup or unrelated transfer-system redesign outside the facilitator-contract cleanup path.

## Phase Exit Criteria

Phase 5 clears only when the following command passes 100%:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_api_meetings.py app/tests/test_api_participants.py app/tests/test_meeting_manager.py app/tests/test_transfer_api.py app/tests/test_transfer_transforms.py app/tests/test_transfer_metadata.py app/tests/test_transfer_comment_format_parity.py app/tests/test_frontend_smoke.py app/tests/test_pages.py -v
```

Passing this command means:
- active API and export contracts no longer expose the old facilitator model,
- any retained legacy compatibility is isolated to one-way import/reader handling,
- the selected existing pytest modules have been updated instead of unnecessarily duplicated,
- and documentation/docstrings describe the cleaned contract surface accurately.

---

*End of Phase 5 execution file. This phase cleans active contracts and isolates legacy compatibility; Phase 6 remains responsible for full end-to-end validation and ship readiness.*
