# PHASE 6 — End-to-End Validation and Merge Readiness

**Parent plan:** [plans/01_MASTER_PLAN.md](plans/01_MASTER_PLAN.md)

**Phase objective:** Prove that the collapsed role/permission model is stable across the full application surface, that the original incoherence is no longer reproducible, and that the branch is ready to merge without unresolved dependency on the removed facilitator model.

## Phase Canary

**Lobster Teacup**

Use this exact two-word canary in Phase 6 notes, commit messages, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — Establish the Final Validation Baseline
Assemble the full verification surface for this project state: automated tests, grep-based residue checks for removed facilitator-model tokens, and the concrete user-facing bug scenarios that must no longer reproduce. The output of this step is the final validation checklist that Phase 6 will close against, not new feature work.

Conclude this step by:
- Implementing the core logic as the final end-to-end validation checklist and residue-check list for Phase 6.
- Creating or updating the relevant pytest file, preferring edits to existing broad-surface pytest modules over creating a new pytest file unless an existing suite cannot reasonably house the final regression coverage.
- Updating docstrings and documentation so the Phase 6 `Lobster Teacup` finish line is explicit and auditable.

### Step 2 — Lock the Original Failure Modes as Final Regression Proof
Verify, and where necessary encode in existing test coverage, the three core behavioral outcomes from the original discovery: demoting a facilitator to participant removes meeting-scoped powers, removing and re-adding a participant does not resurrect stale facilitator powers, and UI/backend capability alignment remains intact after role or roster changes. These are the mandatory no-regression proofs for ship readiness.

Conclude this step by:
- Implementing the core logic as the final regression proof for the original failure modes.
- Creating or updating the relevant pytest file, favoring edits to existing suites such as `app/tests/test_api_meetings.py`, `app/tests/test_meeting_manager.py`, `app/tests/test_frontend_smoke.py`, `app/tests/test_pages.py`, and related already-relevant tests instead of creating a new test file.
- Updating docstrings and documentation so the repository clearly records these scenarios as fixed and protected.

### Step 3 — Verify Full-Surface Consistency and Residue Removal
Run the final consistency pass across the codebase and contracts to ensure the removed facilitator model does not still appear in active code, active contracts, or stale test expectations except where intentionally isolated for backward compatibility. This step also confirms that all phase canaries, contract decisions, and cleanup boundaries remain internally coherent in the written project record.

Conclude this step by:
- Implementing the core logic as the final residue-removal and consistency verification pass.
- Creating or updating the relevant pytest file, preferring edits to existing suites that still need final cleanup coverage instead of creating a new pytest file.
- Updating docstrings and documentation so no active narrative conflicts with the shipped collapsed model or its explicitly isolated compatibility exceptions.

### Step 4 — Prepare Merge-Readiness Artifacts
Produce the final branch-readiness record: verification status, test pass baseline, summary of user-visible fixes, summary of compatibility boundaries, and any grep/stat checks that prove the removed model is actually gone from the active code path. This step is about making the diff reviewable and the final state easy to audit.

Conclude this step by:
- Implementing the core logic as the final merge-readiness notes and completion artifacts for the branch.
- Creating or updating the relevant pytest file, using existing broad-surface suites if any final assertion or marker adjustments are still needed rather than creating a new test file.
- Updating docstrings and documentation so the merge record, validation narrative, and Phase 6 canary are aligned.

### Step 5 — Lock the Final Exit Boundary
Define the exact final terminal command that must pass 100% to clear the entire effort and treat this phase as complete only when the full-suite result, residue checks, and merge-readiness artifacts all support shipment of the collapsed model.

Conclude this step by:
- Implementing the core logic as the final Phase 6 exit checklist and completion criteria in this file.
- Creating or updating the relevant pytest file so any remaining end-to-end regression coverage is included in the exit command below without unnecessary pytest file proliferation.
- Updating docstrings and documentation so the final command, expected success state, and Phase 6 canary remain aligned.

## Phase 6 Final Readiness Scope Map

The following surfaces must be proven ready by the end of this phase:

| Surface | Required Phase 6 outcome |
|---|---|
| Full automated test suite | Passes with zero failures |
| Original user-reported bug scenarios | No longer reproducible |
| Active codebase references to removed facilitator model | Absent, except intentionally isolated backward-compatibility handling if retained |
| Documentation and test narratives | Reflect the collapsed model consistently |
| Branch reviewability | Verification evidence and change narrative are sufficient for merge |

## Phase 6 Non-Goals

This phase does **not** introduce new feature scope. If a new authorization behavior question appears here, it is a scope regression and must be spun out rather than folded into final validation.

## Phase Exit Criteria

Phase 6 clears only when the following command passes 100%:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/ -v
```

Passing this command means:
- the entire automated application surface is green,
- the selected existing pytest modules have absorbed the necessary final regression coverage instead of unnecessary new-test sprawl,
- the collapsed role/permission model is stable across backend, frontend, persistence, and compatibility surfaces,
- and the branch is in a technically merge-ready state pending normal review.

---

*End of Phase 6 execution file. This phase is the final validation and ship-readiness gate for the role/permission collapse effort.*
