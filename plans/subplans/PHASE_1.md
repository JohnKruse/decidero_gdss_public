# PHASE 1 — Behavioral Contract Alignment

**Parent plan:** [plans/01_MASTER_PLAN.md](plans/01_MASTER_PLAN.md)

**Phase objective:** Define and lock the intended meeting-authorization contract so later implementation phases operate against one explicit behavioral target derived only from system role, meeting ownership, and roster membership.

## Phase Canary

**Muffin Tractor**

Use this exact two-word canary in Phase 1 notes, commit messages, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 [DONE] — Extract the Current Authorization Contract Surface
Read [plans/00_DISCOVERY.md](plans/00_DISCOVERY.md) and inventory every meeting-scoped capability that must be normalized in this effort: view access, facilitation, config edits, roster management, activity control, delete semantics, dashboard capability flags, and meeting-context user-directory behavior. Convert that inventory into a concise Phase 1 contract matrix that names the authority inputs and the expected outcomes for each user posture.

Conclude this step by:
- Implementing the core logic as the first draft of the Phase 1 authorization contract matrix inside this file.
- Creating or updating the relevant pytest file, preferring edits to existing meeting/auth/frontend pytest modules over adding a new one unless no existing file can reasonably hold the contract coverage.
- Updating docstrings and documentation to reference the `Muffin Tractor` Phase 1 contract language consistently.

### Step 2 — Resolve the Ambiguities Surfaced by Discovery
Use the discovery open questions and inconsistency matrix to make explicit product-contract decisions for the collapsed model, especially around delete-meeting authority, roster-management authority, activity-control authority, dashboard `is_facilitator` semantics, and the expected relationship between UI affordances and backend enforcement. The output of this step is a single written source of truth, not code restructuring.

Conclude this step by:
- Implementing the core logic as finalized contract decisions in the Phase 1 matrix and accompanying notes.
- Creating or updating the relevant pytest file so existing tests or new assertions encode those exact decisions in the smallest viable set of edited pytest modules.
- Updating docstrings and documentation so test names, test docstrings, and planning text no longer describe per-meeting facilitator rows as part of the intended steady state.

### Step 3 — Encode the Target Behavior in Focused Failing Tests
Translate the Phase 1 contract into focused authorization tests that describe the desired steady state before structural refactors begin. These tests must cover the known incoherence cases from discovery: facilitator-to-participant demotion, remove-and-readd residue, global role change propagation across meetings, and UI/backend symmetry for meeting-scoped controls.

Conclude this step by:
- Implementing the core logic as explicit contract assertions embodied in the chosen pytest modules.
- Creating or updating the relevant pytest file, favoring surgical edits to existing files such as `app/tests/test_api_meetings.py`, `app/tests/test_meeting_manager.py`, `app/tests/test_frontend_smoke.py`, `app/tests/test_auth.py`, or other already-relevant suites instead of creating a new test file.
- Updating docstrings and documentation so every new or revised contract test clearly states the intended collapsed-model behavior and carries the `Muffin Tractor` phase marker where appropriate.

### Step 4 — Classify Legacy Tests Against the New Contract
Review the existing tests identified in discovery that currently pin auto-grant behavior or facilitator-row assumptions. For each affected test, classify it as `keep`, `rewrite`, or `delete`, with one-line rationale tied to the Phase 1 contract. This creates the controlled migration map for later phases without performing the later-phase rewrites yet.

Conclude this step by:
- Implementing the core logic as a maintained Phase 1 rewrite ledger embedded in this file or a clearly-linked Phase 1 section of the planning docs.
- Creating or updating the relevant pytest file by applying only the minimal marker, docstring, or expectation changes needed to distinguish legacy behavior from the new intended contract.
- Updating docstrings and documentation so legacy-test status is explicit and future phases can tell which assertions are temporary holdovers versus target-state requirements.

### Step 5 — Establish the Phase 1 Verification Boundary
Define the exact validation command for this phase and ensure Phase 1 is considered complete only when the contract artifacts are present, the target-behavior tests exist, and the intended failing-versus-passing status is understood and documented. This step closes the phase by making later execution auditable.

Conclude this step by:
- Implementing the core logic as the final verification section and completion checklist in this file.
- Creating or updating the relevant pytest file so the Phase 1 contract coverage is included in the command below and no unnecessary new pytest file has been introduced.
- Updating docstrings and documentation so the exit command, expected outcomes, and Phase 1 canary are all aligned.

## Phase 1 Contract Matrix

This matrix is the canonical behavioral target for Phase 1 planning and test encoding.

| User posture | Can view meeting | Can facilitate / manage roster / control activity / edit meeting-scoped config | Can delete meeting | Dashboard meeting capability should indicate facilitator authority |
|---|---|---|---|---|
| `super_admin` | Yes | Yes | Yes | Yes |
| `admin` | Yes | Yes | Yes | Yes |
| Meeting owner | Yes | Yes | Yes | Yes |
| `facilitator` who is on the roster | Yes | Yes | No, unless also owner/admin | Yes |
| `facilitator` not on the roster and not owner/admin | No meeting-scoped access | No | No | No for that meeting |
| `participant` on the roster | Yes | No | No | No |
| User not on the roster and not owner/admin | No | No | No | No |

## Technical Deviations Log

- Step 1 keeps the contract inventory in planning documentation plus targeted existing pytest modules instead of introducing a new dedicated contract test file. The broader failing-state coverage for role-change residue, remove-and-readd residue, and full UI/backend symmetry is deferred to later Phase 1 steps.

## Legacy Test Classification Ledger

The following tests from discovery require explicit disposition during later phases:

| Existing test anchor | Current premise | Phase 1 disposition |
|---|---|---|
| `app/tests/test_meeting_manager.py::test_activity_participant_scope_management` | Facilitator users auto-acquire facilitator meeting power | Rewrite |
| `app/tests/test_meeting_manager.py::test_bulk_update_participants_adds_and_removes_users` | Bulk add auto-grants facilitator status | Rewrite |
| `app/tests/test_api_meetings.py::test_cofacilitator_update_permissions` | Co-facilitator row is a live authorization concept | Rewrite |
| `app/tests/test_api_meetings.py::test_facilitator_controls_start_stop_tool` | Facilitator authority may derive from per-meeting facilitator assignment | Rewrite |
| `app/tests/test_api_participants.py` roster CRUD coverage | Facilitator-only management likely assumes old facilitator derivation | Review and rewrite where needed |
| `app/tests/test_frontend_smoke.py::test_meeting_roster_button_present` | Meeting Roster button gated by system role template branch | Rewrite |

## Phase Exit Criteria

Phase 1 clears only when the following command passes 100%:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_meeting_manager.py app/tests/test_api_meetings.py app/tests/test_frontend_smoke.py app/tests/test_auth.py -v
```

Passing this command means:
- the Phase 1 contract-bearing tests are present and green,
- the selected existing pytest modules have been updated rather than unnecessarily duplicated,
- docstrings and planning documentation reflect the collapsed-model contract,
- and the repository has one explicit authorization contract for later implementation phases to execute against.

---

*End of Phase 1 execution file. This phase defines the contract and its test expression; it does not yet perform the structural authorization collapse.*
