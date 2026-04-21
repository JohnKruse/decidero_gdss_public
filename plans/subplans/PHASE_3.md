# PHASE 3 — Interface and API Coherence

**Parent plan:** [plans/01_MASTER_PLAN.md](plans/01_MASTER_PLAN.md)

**Phase objective:** Align server-rendered meeting UI gates, frontend capability state, and API-facing capability semantics with the unified backend authorization model so visible controls and enforced permissions cannot diverge.

## Phase Canary

**Toaster Sombrero**

Use this exact two-word canary in Phase 3 notes, commit messages, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — Inventory and Normalize Per-Meeting UI Gates
Review the Phase 3 surfaces identified in discovery and isolate every meeting-scoped UI control that is still gated by global role or stale page-load assumptions rather than the unified backend capability model. This includes meeting page controls, dashboard meeting affordances, capability-bearing template attributes, and JavaScript state derived from `data-user-role` or analogous system-role-only inputs.

Conclude this step by:
- Implementing the core logic as the normalized list of per-meeting UI and API-facing gates that must shift to backend-derived capability.
- Creating or updating the relevant pytest file, preferring edits to existing frontend, page, and meeting/API pytest modules over creating a new pytest file unless no existing suite can reasonably hold the coverage.
- Updating docstrings and documentation so the Phase 3 `Toaster Sombrero` scope clearly distinguishes per-meeting authority from global-role-only UI.

### Step 2 — Rebase Meeting Templates and Frontend State on Backend Capability
Update the meeting-facing templates and JavaScript initialization path so meeting-scoped controls are driven by a backend-derived capability record rather than raw system role. This includes in-meeting settings access, roster access, activity controls, view-mode derivation, and any frontend state that currently treats a global facilitator role as sufficient meeting authority.

Conclude this step by:
- Implementing the core logic by rebasing meeting templates and frontend state on the backend-derived meeting capability semantics.
- Creating or updating the relevant pytest file, favoring surgical edits to existing suites such as `app/tests/test_frontend_smoke.py`, `app/tests/test_pages.py`, and `app/tests/test_api_meetings.py` instead of creating a new test file.
- Updating docstrings and documentation so template logic, frontend behavior notes, and test descriptions describe the capability-driven model rather than system-role gating for meeting controls.

### Step 3 — Align Dashboard and API-Facing Capability Semantics
Ensure any dashboard meeting affordance, meeting summary contract, or API-facing capability field exposed to the frontend reflects the same per-meeting authorization result the backend enforces. The goal is one coherent capability story across SSR output, fetched meeting data, and frontend rendering decisions, even if some compatibility fields remain temporarily present until Phase 5.

Conclude this step by:
- Implementing the core logic by aligning dashboard/API capability semantics with the unified backend meeting-capability model.
- Creating or updating the relevant pytest file, preferring targeted edits to existing suites such as `app/tests/test_meeting_manager.py`, `app/tests/test_api_meetings.py`, `app/tests/test_api_participants.py`, and `app/tests/test_frontend_smoke.py` instead of adding new pytest modules.
- Updating docstrings and documentation so any capability field consumed by the frontend is documented as a derived interface contract from the unified backend model.

### Step 4 — Lock UI and Backend Symmetry Through Regression Coverage
Convert the originally reported incoherence into durable regression coverage that proves the interface and the backend stay synchronized after role changes and roster changes. This phase must specifically prevent cases where controls are hidden but backend access still succeeds, or controls are shown but the backend denies the action.

Conclude this step by:
- Implementing the core logic as regression coverage and supporting interface/API adjustments that enforce UI/backend symmetry for meeting-scoped authority.
- Creating or updating the relevant pytest file, favoring edits to existing frontend/API/page suites such as `app/tests/test_frontend_smoke.py`, `app/tests/test_pages.py`, and `app/tests/test_api_meetings.py` over creating a new test file.
- Updating docstrings and documentation so the symmetry guarantees and the user-visible bug scenarios are explicitly captured in the repository narrative.

### Step 5 — Lock the Phase 3 Verification Boundary
Define the exact mixed frontend/API validation command for this phase and ensure it represents the full interface-coherence surface. Phase 3 is complete only when meeting-scoped UI gates, frontend state, and API capability semantics are all consistent with backend authorization and the selected suites pass without exceptions.

Conclude this step by:
- Implementing the core logic as the final Phase 3 verification checklist and completion notes in this file.
- Creating or updating the relevant pytest file so the interface/API coherence coverage required for Phase 3 is included in the exit command below without unnecessary pytest file proliferation.
- Updating docstrings and documentation so the verification command, intended coherence model, and Phase 3 canary remain aligned.

## Phase 3 Interface Scope Map

The following surfaces must be coherent by the end of this phase:

| Surface | Required Phase 3 outcome |
|---|---|
| `app/templates/meeting.html` meeting-scoped controls | No meeting-scoped control is gated only by global role |
| Meeting page JS capability state | Derived from backend meeting capability, not just `data-user-role` |
| Dashboard meeting affordances | Reflect per-meeting backend authority semantics |
| API-facing capability flags consumed by frontend | Match backend enforcement behavior |
| Page-level meeting UI and backend endpoints | Visible controls and actual authorization outcomes remain in sync |

## Phase 3 Non-Goals

This phase does **not** complete the following:

- Physical removal of `MeetingFacilitator`, `meeting_facilitators`, or ORM relationships, which belongs to Phase 4.
- Export/import contract cleanup and removal of legacy compatibility fields, which belongs to Phase 5.
- WebSocket auth cleanup or unrelated UI redesign outside the role/permission coherence path.

## Phase Exit Criteria

Phase 3 clears only when the following command passes 100%:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_frontend_smoke.py app/tests/test_pages.py app/tests/test_api_meetings.py app/tests/test_meeting_manager.py app/tests/test_api_participants.py app/tests/test_auth.py -v
```

Passing this command means:
- meeting-scoped UI controls are driven by the same authority semantics the backend enforces,
- the selected existing pytest modules have been updated instead of unnecessarily duplicated,
- dashboard/API capability fields consumed by the frontend are coherent with backend authorization,
- and documentation/docstrings describe one capability-driven interface model for meeting authority.

---

*End of Phase 3 execution file. This phase makes the interface and API coherent with backend authorization; it does not yet remove the persistent facilitator schema or complete compatibility cleanup.*
