# User Testing Guide - Copper Compass

This guide runs the first Decidero pilot sessions after the orchestration-engine master plan. It is practical session guidance, not a publication-grade empirical protocol.

The current Phase 7 product assumption is that meeting creation will be organized around four distinct paths:

- **Start from Template** creates a clean meeting from reusable structure.
- **Design with AI** generates a custom agenda from conversation.
- **Design Yourself** starts from a blank manual creator.
- **Import Meeting** loads an existing meeting archive for review, recovery, or reuse of prior data.

The dashboard should expose those choices without training: **Create Meeting** opens the creation choices, while **Import Meeting** remains its own button.

The reusable template storage contract is documented in [MEETING_TEMPLATE_CONTRACT.md](MEETING_TEMPLATE_CONTRACT.md). For pilot observers, the important boundary is that **Start from Template** creates a clean meeting structure; **Import Meeting** restores prior meeting data/history.

## Purpose

Use the pilot to answer four operational questions:

1. Can a facilitator understand the difference between template, AI, manual, and import paths without explanation?
2. Can a facilitator create and run a meeting without developer help?
3. Can participants join, contribute, and understand the active activity?
4. Do realtime updates, permissions, templates, and transfers behave correctly under observed use?
5. What blocker or high-severity issues must be fixed before broader testing?

## Preflight

Before each session:

- Record the git commit SHA being tested.
- Record whether the app is local, LAN-hosted, or server-hosted.
- Confirm the agreed regression command passed for that build.
- Create one facilitator/admin account and three to five participant accounts.
- Decide whether guest join is enabled.
- Create a blank issue log using the evidence template below.
- Confirm screen recording or screenshot consent if identifiable information will be captured.
- Prepare a fallback communication channel for join failures.

## Recommended Regression Command

For the first pilot, use the same Phase 6 exit command unless there is a deliberate reason to narrow it:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_orchestration_engine.py app/tests/test_agenda_validator.py app/tests/test_bundle_transforms.py app/tests/test_convergence_predicates.py app/tests/test_reliability_rehearsal.py app/tests/test_activity_plugins.py app/tests/test_meeting_state.py app/tests/test_meeting_manager.py app/tests/test_api_meetings.py app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_frontend_smoke.py app/tests/test_pages.py app/tests/test_brainstorming_api.py app/tests/test_voting_api.py app/tests/test_rank_order_voting_api.py app/tests/test_categorization_api.py app/tests/test_ai_provider_config.py -v
```

## Roles

- Facilitator/admin: creates the meeting, configures activities, starts and stops activities, reviews outputs.
- Participants: join the meeting and complete activity tasks.
- Observer: watches without coaching unless the session is blocked.

The observer should record what users do, what they say, where they hesitate, and what error state or UI state appears.

## Session Script

### Opening

Read or paraphrase:

"We are testing the software, not you. Please say what you are looking for and what you expect to happen. I will avoid helping unless you are blocked, because confusion is useful evidence."

### Workflow A - Create a Meeting

Facilitator goal:

"Create a meeting for this group. Choose the creation path that seems right, add participants, and share the join path."

Observer prompts only if needed:

- "What are you looking for now?"
- "What did you expect that button or page to do?"
- "What would you tell participants to do next?"

Success signals:

- Facilitator can explain, in their own words, when they would use Start from Template, Design with AI, Design Yourself, and Import Meeting.
- Meeting is created.
- Participants can join.
- Activities are configured without invalid placeholder data.
- Facilitator understands role and roster controls.

### Workflow B - Start from Template

Use this workflow once the Phase 7 template path is implemented. Until then, record the missing path as a product gap rather than forcing a workaround.

Facilitator goal:

"Start from a prebuilt meeting template, adjust only the details needed for today's group, and create the meeting."

Observe:

- Whether the facilitator finds Start from Template from the dashboard.
- Whether the Meeting Templates page makes built-in and custom templates understandable.
- Whether card details are enough without a separate preview page.
- Whether the facilitator understands that a template is a clean reusable design, not an old meeting with data.
- Whether required fields and template-specific parameters are clear.
- Whether the resulting meeting contains the expected agenda and no stale runtime data.

### Workflow C - Run a Live Meeting

Group goal:

"Run through the meeting activities and produce a prioritized set of outputs."

Observe:

- Whether participants can identify the active activity.
- Whether ideas, votes, rankings, and categories submit successfully.
- Whether users understand when results are visible.
- Whether agenda changes appear without refresh.
- Whether accidental refresh or reconnect causes data loss or confusion.

### Workflow D - Transfer Output

Facilitator goal:

"Move useful output from one completed activity into a later compatible activity."

Observe:

- Whether eligible transfer targets are clear.
- Whether preview and commit behavior is understandable.
- Whether provenance and item content remain intact.
- Whether locked or ineligible targets explain why they are unavailable.

### Workflow E - Save as Template

Use this workflow once Phase 7 save-as-template is implemented.

Facilitator goal:

"This meeting structure worked well. Save the reusable structure so you can run a similar meeting next week."

Observe:

- Whether the facilitator finds Save as Template from the meeting page or settings.
- Whether they understand which data will and will not be saved.
- Whether the saved template appears in Meeting Templates.
- Whether starting from the saved template creates a clean meeting without ideas, votes, rankings, categories, runtime state, or participant responses.

### Workflow F - Delphi Readiness

Use only if the Delphi path is exposed in the current product surface.

Facilitator goal:

"Start or inspect the Classical Delphi template and explain how round-to-round feedback works."

If Delphi is not exposed through the UI as a template, record that as a product gap. Do not force a backend-only demonstration in a user pilot.

## Evidence Template

| Field | Value |
| --- | --- |
| Session ID |  |
| Date/time |  |
| Commit SHA |  |
| Environment | Local, LAN, or hosted |
| Workflow | Setup, A, B, C, D, E, or F |
| Role | Admin, facilitator, participant, observer |
| Browser/device |  |
| Severity | Blocker, high, medium, low, note |
| Type | Bug, usability, documentation, performance, setup |
| Expected |  |
| Actual |  |
| Evidence | Screenshot, log, meeting ID, traceback, or reproduction notes |
| Decision | Fix now, defer, needs reproduction, or not a defect |
| Owner |  |

## Severity

- Blocker: prevents joining, creating, facilitating, submitting, saving, or recovering from the primary workflow.
- High: primary workflow completes only with observer intervention or produces misleading results.
- Medium: workflow completes, but users hesitate, misunderstand, or take a fragile path.
- Low: cosmetic, copy, layout, or minor polish issue that does not change task success.
- Note: observation that may inform later design but is not yet actionable.

## Triage Rules

After the session:

- Fix blockers before running another broad session.
- Fix high-severity issues before inviting a wider group.
- Do not mix speculative redesign work into the blocker pass.
- Preserve exact user language for confusing labels or instructions.
- Add regression tests for fixed bugs when the behavior is testable.
- Record deferrals with a clear reason.

## Pilot Report Outline

Use this outline after each session:

1. Session summary
2. Build and environment
3. Participants and roles
4. Workflows attempted
5. Workflows completed without observer help
6. Blockers
7. High-severity issues
8. Usability friction
9. Documentation gaps
10. Deferred findings
11. Recommended next action

## Exit Checklist

Before considering the first pilot-hardening pass complete:

- At least one observed session is documented.
- Every blocker and high-severity issue has a decision.
- Accepted blocker and high-severity fixes have regression coverage where feasible.
- The agreed regression command passes at `[100%]`.
- The pilot report distinguishes product bugs from usability friction and future research questions.
