# PHASE 5 — Compatibility and Contract Cleanup

**Parent plan:** [plans/01_MASTER_PLAN.md](plans/01_MASTER_PLAN.md)

**Phase objective:** Normalize outward-facing contracts so active APIs, exports, imports, serialized meeting payloads, and tests reflect the collapsed authorization model without leaving legacy facilitator semantics in the live contract.

## Phase Canary

**Pickle Trombone**

Use this exact two-word canary in Phase 5 notes, commit messages, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 [DONE] — Inventory the Remaining External Contract Surface
Identify every outward-facing contract element that can still leak the old facilitator model after Phase 4, including meeting payload fields, dashboard summaries, export bundle contents, transfer/import schemas, and any test assertions that still validate legacy facilitator artifacts as if they were part of the intended active API. The output of this step is a complete cleanup ledger for all remaining public-facing contract debt.

Conclude this step by:
- Implementing the core logic as the complete Phase 5 ledger of remaining API/export/import/test contract elements tied to the old facilitator model.
- Creating or updating the relevant pytest file, preferring edits to existing API/transfer/meeting pytest modules over creating a new pytest file unless an existing suite cannot reasonably carry the contract-cleanup coverage.
- Updating docstrings and documentation so the Phase 5 `Pickle Trombone` scope clearly distinguishes active contract cleanup from narrowly-isolated backward-compatibility handling.

Step 1 external contract ledger for `Pickle Trombone`:

| Surface | Current external contract debt | Cleanup target |
|---|---|---|
| `app/schemas/meeting.py` | `MeetingFacilitatorSummary`, `facilitator_ids`, `facilitator_user_ids`, `facilitators`, `facilitator_names`, and `is_owner` still shape active meeting/dashboard responses around facilitator terminology. | Step 2 removes active response fields or renames them to collapsed owner/authority terminology. |
| `app/services/meeting_authorization.py` | `MeetingFacilitatorOutput`, `MeetingFacilitatorOutputs`, and `derive_meeting_facilitator_outputs` still produce facilitator-shaped response metadata even though the data is capability-derived. | Step 2 replaces derived facilitator metadata with collapsed owner/authority presentation metadata. |
| `app/data/meeting_manager.py` | Dashboard payloads still emit `facilitator_names` and `facilitators`. `create_meeting`, `add_meeting`, and `update_meeting` still accept facilitator-oriented compatibility inputs. | Step 2 removes active dashboard response fields; Step 4 resolves create/update contract naming that remains after import compatibility is isolated. |
| `app/routers/meetings.py` | `MeetingCreateRequest.co_facilitator_ids`, update `facilitator_ids`, restricted-field language, export `facilitators`, and import reader mapping of legacy `facilitators` into `additional_facilitator_ids` remain visible. | Step 2 removes active API response/update semantics; Step 3 isolates legacy import/export handling so new exports stop writing old structures. |
| `app/static/js/dashboard.js` and `app/static/js/meeting.js` | Frontend display logic still reads `facilitators`, `facilitator_names`, `facilitator.is_owner`, and `meeting.facilitator`. | Step 2 updates consumers to owner/authority fields once backend responses expose the cleaned contract. |
| `app/templates/create_meeting.html` | Create-meeting payload still sends `co_facilitator_ids: []` as an active request shape. | Step 4 removes stale create-contract payload language unless Step 2 replaces it earlier. |
| `app/tests/test_api_meetings.py`, `app/tests/test_meeting_manager.py`, `app/tests/test_api_user_directory.py`, `app/tests/test_pages.py`, and frontend smoke tests | Existing assertions still require facilitator-shaped response fields and names as intended behavior. | Steps 2-4 rewrite tests to assert owner/capability/participant contract fields and retain only isolated legacy import-reader tests. |
| Export fixture `EXPORT_ZIP_BASE64` in `app/tests/test_api_meetings.py` | Legacy import fixture still includes facilitator-bearing serialized data. | Step 3 keeps this only as a one-way legacy import fixture and verifies new exports do not write facilitator structures. |

### Step 2 [DONE] — Remove Legacy Facilitator Semantics from Active API Responses
Clean the live API surface so active responses no longer expose `facilitator_links`, facilitator-assignment arrays, `is_owner`-style facilitator-row semantics, or equivalent remnants of the old model. Any capability or meeting-authority fields that remain must describe the collapsed model directly and be consumed as such by dependent code and tests.

Conclude this step by:
- Implementing the core logic by removing old facilitator semantics from active API response contracts.
- Creating or updating the relevant pytest file, favoring surgical edits to existing suites such as `app/tests/test_api_meetings.py`, `app/tests/test_api_participants.py`, `app/tests/test_meeting_manager.py`, and related API-facing tests instead of creating a new test file.
- Updating docstrings and documentation so active API contracts and test descriptions describe only the collapsed authority model.

Step 2 active response cleanup for `Pickle Trombone`:

| Surface | Step 2 result |
|---|---|
| `app/services/meeting_authorization.py` | Replaced facilitator-shaped presentation helpers with `derive_meeting_authority_outputs`, `MeetingAuthorityOutput`, and `MeetingAuthorityOutputs`. These derive owner and meeting-authority metadata from the collapsed capability model without emitting facilitator assignment rows. |
| `app/schemas/meeting.py` | Replaced active `MeetingResponse` and dashboard list fields `facilitator_user_ids`, `facilitators`, `facilitator_names`, and `facilitator` with `authority_user_ids`, `meeting_authorities`, `authority_names`, and `owner`. |
| `app/data/meeting_manager.py` | Dashboard payload construction now emits owner and meeting-authority fields instead of facilitator-shaped summary arrays. |
| `app/static/js/dashboard.js` and `app/static/js/meeting.js` | Frontend consumers now read `owner`, `meeting_authorities`, and `authority_names`; the meeting overview label now says `Authority`. |
| `app/tests/test_api_meetings.py` and `app/tests/test_meeting_manager.py` | Active API/dashboard assertions now verify the authority fields and explicitly reject the removed facilitator-shaped response keys. |

### Step 3 [DONE] — Isolate Legacy Import/Export Compatibility
Rewrite export and transfer-facing contracts so newly produced artifacts no longer encode the old facilitator model while preserving only the minimum one-way compatibility needed to read older serialized meeting data. Legacy compatibility must be explicitly isolated to compatibility handling and must not re-enter the active authorization path or active API contract.

Conclude this step by:
- Implementing the core logic by separating active export/import contracts from narrowly-scoped legacy compatibility handling.
- Creating or updating the relevant pytest file, preferring edits to existing suites such as `app/tests/test_transfer_api.py`, `app/tests/test_transfer_transforms.py`, `app/tests/test_transfer_metadata.py`, `app/tests/test_transfer_comment_format_parity.py`, and other already-relevant transfer/export tests instead of adding new pytest modules.
- Updating docstrings and documentation so export/import expectations clearly state what the system now writes, what legacy data it can still read, and that compatibility handling is one-way.

Step 3 import/export compatibility isolation for `Pickle Trombone`:

| Surface | Step 3 result |
|---|---|
| `app/routers/meetings.py` export writer | New meeting export bundles now write `owner` metadata and no longer write the legacy top-level `facilitators` structure. |
| `app/routers/meetings.py` import reader | Legacy top-level `facilitators` entries are accepted only through `_read_legacy_import_facilitators` and are intentionally ignored for imported roster and authority construction. |
| `app/tests/test_api_meetings.py` | Export coverage now rejects new `facilitators` output, and legacy import coverage verifies facilitator-only legacy entries do not grant participant membership or active authority. |

### Step 4 [DONE] — Purge Legacy Test Assumptions and Contract Language
Resolve the remaining Phase 1 rewrite/delete ledger items that encoded stale auto-grant behavior, facilitator-row persistence, or old payload shapes as intended behavior. By the end of this step, the test suite and its naming/docstrings must reinforce only the collapsed model and its intentionally isolated compatibility exceptions.

Conclude this step by:
- Implementing the core logic by purging stale contract assumptions from tests and any supporting code comments or references.
- Creating or updating the relevant pytest file, favoring edits to the existing affected suites instead of creating a new test file for cleanup work.
- Updating docstrings and documentation so no active test or repository narrative still treats the old facilitator contract as intended behavior.

Step 4 contract-language cleanup for `Pickle Trombone`:

| Surface | Step 4 result |
|---|---|
| `app/templates/create_meeting.html` | Removed the stale `co_facilitator_ids: []` create payload field so the create form no longer writes facilitator-shaped request language as an active contract. |
| `app/templates/meeting.html` | Participant-management guidance now describes roster membership versus meeting management authority without referring to meeting facilitators as an active concept. |
| `app/tests/test_api_meetings.py` | Updated control and roster-regression docstrings plus setup payloads so the tests describe meeting authority rather than legacy facilitator contract language. |
| `app/tests/test_meeting_manager.py` | Updated stale test meeting copy so ownership transfer coverage talks about owner authority rather than facilitator semantics. |

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

## Technical Deviations Log

- Step 1 (`Pickle Trombone`): This step intentionally documents the external contract debt without removing it. Active response and export/import changes begin in Step 2 and Step 3 so the cleanup remains reviewable and the legacy import exception is isolated rather than mixed into the inventory pass.
- Step 2 (`Pickle Trombone`): Active API and dashboard response contracts now use owner/authority presentation names. The `MeetingUpdate.facilitator_ids`, create/import `additional_facilitator_ids`/`co_facilitator_ids`, and export/import `facilitators` compatibility surfaces remain intentionally untouched for Step 3 and Step 4 so request-shape and transfer cleanup stay isolated from response cleanup.
- Step 3 (`Pickle Trombone`): Legacy `facilitators` data is still tolerated when reading older bundles, but it is no longer translated into `additional_facilitator_ids` or any active authority path. Create/update request names remain deferred to Step 4 because this step is limited to export/import compatibility.
- Step 4 (`Pickle Trombone`): Request-shape cleanup in this step removes the create-page `co_facilitator_ids` payload, but the backend compatibility fields `MeetingUpdate.facilitator_ids`, `MeetingCreatePayload.co_facilitator_ids`, and `MeetingCreate.additional_facilitator_ids` remain temporarily accepted so existing tests and compatibility readers can be cleaned incrementally without conflating this step with API removal work.

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
