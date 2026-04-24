# Phase 6 Validation Checklist

Use this document as the auditable Phase 6 Step 1 baseline for the role/permission collapse effort.

## Canary

`Lobster Teacup`

Use this exact canary in Phase 6 notes, commit messages, test docstrings, and merge-readiness artifacts tied to this final validation phase.

## Final Certification Command

Phase 6 is not complete until this command passes 100%:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/ -v
```

## Discovery Regression Baseline

The original incoherence reported in discovery must remain fixed across the following already-existing broad-surface checks:

- `app/tests/test_api_meetings.py::test_demoted_facilitator_loses_control_across_meetings_and_page_controls`
- `app/tests/test_api_meetings.py::test_removed_facilitator_loses_control_until_readded`
- `app/tests/test_frontend_smoke.py::test_meeting_roster_button_present`

These checks together cover:

- demoting a facilitator to participant removes meeting-scoped authority,
- removing and re-adding a participant does not resurrect stale authority while off-roster,
- and visible meeting controls remain aligned with backend-derived per-meeting capabilities.

## Final Regression Proof

Phase 6 Step 2 locks the original failure modes under the `Lobster Teacup` canary by treating the following outcomes as mandatory regression proof:

- demotion authority revocation: a user demoted from facilitator to participant keeps meeting view access only as a rostered participant, loses meeting-management dashboard capability flags, loses visible management controls, and receives backend denial for meeting control actions across affected meetings,
- remove-and-readd stale-authority prevention: removing a facilitator-role user from a roster removes meeting visibility and backend control access, and re-adding that user restores authority only because current system role plus current roster membership now satisfy the collapsed model,
- UI/backend capability symmetry: meeting roster/settings controls are rendered from the same backend-derived per-meeting capability record that backs API authorization and dashboard capability fields.

The active proof points are:

- `app/tests/test_api_meetings.py::test_demoted_facilitator_loses_control_across_meetings_and_page_controls`
- `app/tests/test_api_meetings.py::test_removed_facilitator_loses_control_until_readded`
- `app/tests/test_frontend_smoke.py::test_meeting_roster_button_present`

## Residue Check List

Before closing Phase 6, verify that the following removed-model markers are absent from active code paths:

- `MeetingFacilitator`
- `meeting_facilitators`
- `facilitator_links`
- `_ensure_facilitator_assignment`
- `_collect_facilitator_assignments`
- `_should_auto_facilitate`

Compatibility handling and historical references may remain only when they are clearly isolated to legacy import support, tests that assert cleanup boundaries, or plan records documenting completed work.

## Ship-Readiness Record

Phase 6 `Lobster Teacup` is auditable only if all of the following stay aligned:

- this checklist,
- `plans/subplans/PHASE_6.md`,
- `plans/01_MASTER_PLAN.md`,
- the full-suite pytest result,
- and the final merge-readiness notes produced later in Phase 6.
