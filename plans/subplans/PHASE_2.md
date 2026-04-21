# PHASE 2 — Authorization Surface Unification

**Parent plan:** [plans/01_MASTER_PLAN.md](plans/01_MASTER_PLAN.md)

**Phase objective:** Collapse the backend’s fragmented meeting-authorization logic into one canonical capability model so every meeting-scoped enforcement path derives from the same durable facts: system role, meeting ownership, and roster membership.

## Phase Canary

**Gravy Parachute**

Use this exact two-word canary in Phase 2 notes, commit messages, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — Define the Canonical Backend Capability Model
Translate the Phase 1 contract into one backend capability model that explicitly represents the meeting-scoped decisions the application makes: view access, facilitation authority, meeting-config authority, roster-management authority, activity-control authority, activity-roster authority, delete authority, and any backend-facing “is facilitator” derivative needed for current contracts. The model must depend only on `User.role`, `Meeting.owner_id`, and roster membership, even if legacy storage still exists during this phase.

Conclude this step by:
- Implementing the core logic as the canonical backend capability model in one authoritative location.
- Creating or updating the relevant pytest file, preferring edits to existing backend/auth pytest modules over introducing a new pytest file unless an existing module cannot reasonably house the capability-model coverage.
- Updating docstrings and documentation so the model’s inputs, outputs, and Phase 2 `Gravy Parachute` intent are unambiguous.

### Step 2 — Rewire the Core Meeting Access Gates
Replace the main meeting-access and meeting-management decision points with the canonical capability model. This includes the canonical meeting access helper, meeting update and activity-control checks, participant-management gates, archive/restore semantics, and any backend path that currently branches directly on facilitator rows or ad hoc owner/facilitator combinations.

Conclude this step by:
- Implementing the core logic by routing the core meeting gates through the canonical capability model.
- Creating or updating the relevant pytest file, favoring surgical updates to existing suites such as `app/tests/test_api_meetings.py`, `app/tests/test_api_participants.py`, `app/tests/test_meeting_manager.py`, and `app/tests/test_auth.py` instead of creating a new test file.
- Updating docstrings and documentation so gate semantics now describe the unified backend authority model rather than legacy facilitator-row behavior.

### Step 3 — Rewire Activity and Cross-Router Authorization
Apply the same capability model to the meeting-scoped activity routers and adjacent backend surfaces identified in discovery, including brainstorming, voting, rank-order voting, categorization, transfer/import-export access, and meeting-context user-directory decisions. The target is behavioral consistency across all router families, not just the main meetings router.

Conclude this step by:
- Implementing the core logic by replacing per-router ad hoc facilitator checks with the canonical capability model wherever the phase scope requires.
- Creating or updating the relevant pytest file, preferring edits to existing router-specific suites such as `app/tests/test_brainstorming_api.py`, `app/tests/test_voting_api.py`, `app/tests/test_rank_order_voting_api.py`, `app/tests/test_categorization_api.py`, `app/tests/test_transfer_api.py`, and related backend tests instead of adding new pytest modules.
- Updating docstrings and documentation so router-level authorization descriptions match the same meeting authority language used in the canonical model.

### Step 4 — Normalize Backend-Derived Capability Outputs
Unify the backend-produced capability signals that other layers consume, especially dashboard meeting capability fields, meeting-context user flags, and any serialized “is facilitator” derivative that remains temporarily necessary before the Phase 3 interface cleanup. At the end of this step, any retained derived flag must be computed from the canonical capability model rather than legacy facilitator rows.

Conclude this step by:
- Implementing the core logic by deriving backend-facing capability outputs exclusively from the canonical model.
- Creating or updating the relevant pytest file, favoring targeted edits to existing meeting-manager, meetings API, and related backend suites over creating a new pytest file.
- Updating docstrings and documentation so any surviving derived capability fields are explicitly documented as outputs of the unified model, not separate sources of truth.

### Step 5 — Lock the Backend Verification Boundary
Define and verify the exact backend-oriented command that certifies this phase. Phase 2 is complete only when the canonical capability model is the sole meeting-scoped backend authority source, all selected backend suites pass, and no router/data enforcement path within scope still depends on per-meeting facilitator rows for authorization.

Conclude this step by:
- Implementing the core logic as the final Phase 2 verification checklist and completion notes in this file.
- Creating or updating the relevant pytest file so the backend authorization coverage needed for Phase 2 is included in the exit command below without unnecessary pytest file proliferation.
- Updating docstrings and documentation so the verification command, intended authority model, and Phase 2 canary remain aligned.

## Phase 2 Backend Scope Map

The following backend surfaces must be brought under the canonical capability model during this phase:

| Surface | Required Phase 2 outcome |
|---|---|
| Main meeting access gate | Canonical capability model decides view/facilitation authority |
| Meeting update / archive / restore / control endpoints | No ad hoc facilitator-row checks remain in enforcement logic |
| Participant and activity-roster management | Authority derives from canonical model |
| Brainstorming / voting / rank-order voting / categorization | Meeting-scoped authority decisions are consistent with the canonical model |
| Transfer / export / meeting-context user-directory behavior | Authorization uses the same canonical model |
| Dashboard `is_facilitator` and similar backend-derived flags | Derived from canonical model only |

## Phase 2 Non-Goals

This phase does **not** complete the following:

- Frontend template and JavaScript gate cleanup, which belongs to Phase 3.
- Physical removal of `MeetingFacilitator`, `meeting_facilitators`, or ORM relationships, which belongs to Phase 4.
- Export/import contract cleanup and legacy serialization cleanup, which belongs to Phase 5.

## Phase Exit Criteria

Phase 2 clears only when the following command passes 100%:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_auth.py app/tests/test_meeting_manager.py app/tests/test_api_meetings.py app/tests/test_api_participants.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_rank_order_voting_api.py app/tests/test_categorization_api.py app/tests/test_transfer_api.py -v
```

Passing this command means:
- the canonical backend capability model is implemented and in active use,
- the selected existing pytest modules have been updated instead of unnecessarily duplicated,
- backend authorization is consistent across the meeting and activity router surface in scope for this phase,
- and documentation/docstrings describe one unified backend authority model.

---

*End of Phase 2 execution file. This phase unifies backend authorization logic; it does not yet remove the persistent facilitator schema or clean up frontend gating.*
