# PHASE 7 — User Testing and Pilot Hardening

**Parent plan:** Post-master-plan continuation after [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Prior validation:** [plans/subplans/PHASE_6.md](PHASE_6.md)
**Reference evaluation:** [docs/DELPHI_VALIDATION.md](../../docs/DELPHI_VALIDATION.md)

**Phase objective:** Move from analytical and synthetic validation into observed use by realistic facilitators and participants. Phase 7 does not expand the orchestration engine architecture. It verifies whether users can set up, facilitate, participate in, and recover from ordinary meeting workflows without developer guidance, and it turns the observed defects and friction into a prioritized hardening backlog.

**Scope posture:** This phase is a pilot-hardening phase, not a field study claim for publication. Evidence collected here may inform a later empirical study, but Phase 7's immediate purpose is operational readiness: find bugs, confusing flows, missing instructions, permission mismatches, and facilitator workflow gaps before wider use.

## Phase Canary

**Copper Compass**

Use this exact two-word canary in Phase 7 notes, testing scripts, issue labels, pilot reports, and commits tied to this phase.

## Pilot Setup

### Roles

Run each pilot with at minimum:

- One facilitator or admin who creates and runs the meeting.
- Three to five participants who join and contribute.
- One observer who does not guide users unless the session is blocked.

If staffing is limited, the facilitator and observer may be the same person, but record that as a limitation because it weakens observation quality.

### Environment

Before inviting users:

- Start from a clean git commit and record its SHA in the session notes.
- Confirm the app starts from the documented local or hosted setup path.
- Confirm the Phase 6 exit command or an agreed pilot regression command passes.
- Create test accounts for each participant role.
- Decide whether guest join is enabled for the pilot.
- Prepare a fallback communication channel in case users cannot join the meeting.
- Prepare a simple issue log with severity, role, browser, workflow, expected behavior, actual behavior, evidence, and follow-up owner.

### Session Rules

During the session:

- Give users goals, not click-by-click instructions.
- Do not explain the UI unless the session is blocked.
- Record exact terms users misunderstand.
- Capture screenshots or logs for every defect.
- Separate product bugs from usability friction and study-setup confusion.
- Keep each workflow time-boxed so one failure does not consume the whole pilot.

## Workflow Script

### Workflow A — Meeting Creation and Roster

Goal for the facilitator: create a new meeting, add participants, configure at least three activities, and share the join path.

Observe whether the facilitator can:

- Find the create-meeting flow.
- Understand participant and facilitator roles.
- Add, remove, and re-add participants.
- Configure activities without invalid placeholder data.
- Save the meeting and recover from validation errors.
- Explain what participants should do next.

### Workflow B — Live Linear Meeting

Goal for the facilitator and participants: run a normal meeting using brainstorming, voting, rank-order voting, and categorization.

Observe whether users can:

- Join the meeting without help.
- Tell which activity is active.
- Submit brainstorming ideas.
- Vote or rank options successfully.
- Understand when results are visible.
- Categorize or review categorized items.
- Recover from refreshes, reconnects, and accidental navigation.
- See facilitator-driven agenda changes in real time.

### Workflow C — Transfer and Reuse

Goal for the facilitator: move useful output from one activity into a later compatible activity.

Observe whether the facilitator can:

- Identify transfer-eligible activities.
- Preview transferred content.
- Commit a transfer without losing provenance or item metadata.
- Understand why a transfer target is unavailable when it is locked or already contains data.

### Workflow D — Delphi Demonstration Readiness

Goal for the facilitator: inspect or run the packaged Delphi path if it is exposed in the current UI. If it is not exposed, record that as a product gap rather than forcing a backend-only demonstration.

Observe whether the facilitator can:

- Find the Delphi entry point.
- Understand how Delphi differs from a normal linear agenda.
- Explain round-to-round feedback to participants.
- Interpret convergence or max-round termination.
- Export or summarize the resulting decision record.

## Evidence Template

Use one row per observation:

| Field | Required content |
| --- | --- |
| Session ID | Date plus short label, for example `2026-06-01-pilot-a` |
| Commit SHA | Exact git commit tested |
| Workflow | A, B, C, D, or setup |
| Role | Admin, facilitator, participant, observer |
| Browser/device | Browser version and device type |
| Severity | Blocker, high, medium, low, note |
| Type | Bug, usability, documentation, performance, setup |
| Expected | What the user or system should have done |
| Actual | What happened |
| Evidence | Screenshot, log line, traceback, meeting ID, or reproduction notes |
| Decision | Fix now, defer, needs reproduction, or not a defect |

## Severity Taxonomy

- Blocker: prevents joining, creating, facilitating, submitting, saving, or recovering from the primary workflow.
- High: primary workflow completes only with observer intervention or produces misleading results.
- Medium: workflow completes, but users hesitate, misunderstand, or take a fragile path.
- Low: cosmetic, copy, layout, or minor polish issue that does not change task success.
- Note: observation that may inform future design but is not yet actionable.

## Atomic Steps

### Step 1 — Draft and Dry-Run the Pilot Protocol

Create the concrete pilot packet from this guide: participant invitation text, facilitator script, observer checklist, session-note template, consent/privacy note if recordings or screenshots will include user-identifying data, and a preflight checklist for local or hosted deployment. Dry-run the packet internally with one facilitator account and one participant account before involving external users.

Conclude this step by:

- Creating or updating the pilot packet in `docs/USER_TESTING_GUIDE.md` or an equivalent docs location.
- Recording the chosen pilot command set, including app startup and regression verification.
- Recording any deviations from this Phase 7 guide.

### Step 2 — Run the First Facilitated Pilot

Run one observed session with realistic users. Use Workflows A through C as the minimum path; include Workflow D only if the Delphi path is exposed through the current product surface. Do not fix issues during the session unless the session is blocked.

Conclude this step by:

- Recording the session notes and evidence.
- Filing each actionable defect or friction item into a prioritized backlog.
- Recording which workflows completed without observer intervention.

### Step 3 — Triage and Fix Pilot Blockers

Fix only blocker and high-severity findings from the first pilot unless a medium issue is trivial and adjacent to a blocker fix. Preserve the difference between observed defects and speculative improvements.

Conclude this step by:

- Updating code or documentation for accepted fixes.
- Adding regression coverage for every fixed bug where feasible.
- Recording deferred findings with explicit rationale.

### Step 4 — Run a Confirmation Pilot

Run a second session or focused retest against the fixed build. The goal is to confirm that blocker/high issues from Step 2 are resolved and no primary workflow regressed.

Conclude this step by:

- Recording confirmation evidence.
- Updating the pilot report with remaining risks.
- Deciding whether the product is ready for broader user testing or needs another hardening loop.

## Phase Exit Criteria

Phase 7 clears only when:

- At least one realistic pilot session has been observed and documented.
- Every blocker and high-severity finding has either been fixed, reproduced into a tracked follow-up, or explicitly deferred with rationale.
- The agreed regression command reaches `[100%]` on the final pilot build.
- Documentation reflects how a new tester should run the pilot without developer-only context.
- The final pilot report distinguishes bugs, usability friction, documentation gaps, and future research questions.

## Scope Boundary

This phase does not cover:

- A publication-grade empirical study.
- Statistical claims about group decision quality.
- Large-scale load testing beyond the pilot group.
- New orchestration grammar features.
- New reference methods beyond documenting whether users need them.
- Major visual redesign unless pilot blockers prove the current UI prevents task completion.
