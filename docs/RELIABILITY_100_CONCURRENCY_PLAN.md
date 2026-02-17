# Reliability Plan: SQLite 100-Concurrent Target

This document defines the measurable reliability baseline for Decidero on SQLite
for short, bursty workshop traffic.

## Scope

- Target deployment profile: single-node, SQLite-backed, realtime enabled.
- Capacity objective: approximately 100 concurrent attendees.
- Burst pattern: synchronized user actions (register/login/submit) for 1-2 minutes.
- Out of scope for this milestone: Postgres migration and multi-node scaling.

## User-Centered Reliability Goals

1. Avoid mass lockouts during short bursts.
2. Keep brainstorming submissions reliable with bounded automatic retry.
3. Prevent duplicate idea creation when retries happen.
4. Degrade as temporary slowdown (recoverable) instead of unrecoverable failure.

## Definitions

- `concurrent attendee`: authenticated browser session actively polling and/or
  connected to meeting realtime channels.
- `hard failure`: action fails after all retries and requires manual user retry.
- `transient failure`: temporary backend or network issue expected to recover
  within seconds (e.g., HTTP 503, timeout, temporary disconnect).
- `lockout event`: valid user is incorrectly treated as unauthorized for longer
  than the recovery window.

## Acceptance Criteria (Go/No-Go)

The 100-concurrent target is considered met only if all criteria pass.

1. Availability:
- During burst rehearsal, successful completion for critical flows is >= 98%.
- Critical flows: login, registration, brainstorming submit, meeting state fetch.

2. Recovery:
- For transient failures, client automatic retry recovers >= 95% of affected
  write actions without user intervention.
- Max recovery window from burst onset to stable behavior: <= 30 seconds.

3. Lockout control:
- Zero prolonged lockout events.
- Temporary auth/backend failures must be surfaced as retryable overload
  behavior (`503` path), not false credential invalidation (`401`) for valid users.

4. Data correctness:
- Zero duplicate idea writes for replayed retry requests with same idempotency key.
- Zero lost writes for requests acknowledged as success.

5. UX:
- Final user-facing failure message appears only after bounded retry exhaustion.
- No silent infinite retries.

## Burst Traffic Profiles

Each profile is run independently and as part of a mixed full rehearsal.

1. Registration wave:
- 60 users attempt registration in 60 seconds.
- 20 users continue normal dashboard/meeting reads concurrently.

2. Login wave:
- 80 users attempt login in 45 seconds.
- 20 users remain active in meeting pages.

3. Brainstorming submission wave:
- 100 connected users submit an idea within a 90-second window.
- At least 30 users perform near-simultaneous submits in first 15 seconds.

4. Mixed facilitator + participant wave:
- Facilitator performs activity controls while 80-100 users refresh state and
  submit ideas in clumps.

## Required Test Coverage (Pytest + Rehearsal)

1. Unit tests:
- Retry policy decision matrix (retryable status classes, max retries, backoff bounds).
- Idempotency key replay and mismatch semantics.

2. Integration tests:
- Brainstorming create endpoint with idempotency under repeated/replayed requests.
- Auth middleware behavior under simulated DB/pool temporary failures.

3. Regression tests:
- Realtime connection churn does not trigger mutation-iteration crashes.
- Transient overload behavior does not regress into false-401 lockouts.

4. Rehearsal tests:
- Scripted burst profile runs with metrics collection and pass/fail summary.

## Metrics To Capture Per Rehearsal

- Total request count by endpoint/action.
- Success count and success percentage.
- Transient failure count and retry recovery percentage.
- Hard failure count and percentage.
- P50/P95/P99 latency for critical endpoints.
- Time-to-recovery from burst onset.
- Duplicate write count (must be zero).

## Documentation Deliverables

1. Operator runbook update:
- Expected overload behavior, recovery steps, and pre-session checks.

2. Developer contract update:
- Reliability policy fields for activity modules (retry, idempotency flags).

3. Session host guidance:
- What participants should experience during temporary overload and when to retry.

## Brainstorming Idempotency Contract (Current)

- Write endpoint: `POST /api/meetings/{meeting_id}/brainstorming/ideas`
- Client header: `X-Idempotency-Key: <opaque-client-key>`
- Recommended client behavior:
  1. Generate one key per user submit action.
  2. Reuse that same key across retries for that action.
  3. Do not reuse the key for a different payload.
- Server behavior:
  1. Same key + same payload in the same user/meeting/activity scope replays the
     original success response.
  2. Same key + different payload returns conflict (`409`).

## Auth/Registration Overload UX Policy (Current)

- Login (`/api/auth/token`):
  - Browser performs bounded automatic retry for transient overload statuses
    (`429`, `503`) with short backoff.
  - After retry exhaustion, user sees a clear temporary-busy message.
- Registration (`/api/auth/register`):
  - No silent automatic retry yet (to avoid duplicate-account edge cases without
    registration idempotency support).
  - User receives explicit temporary-busy guidance and can safely retry manually.

## Exit Gate

Do not declare milestone complete until:

1. Reliability pytest suite is green.
2. 100-concurrent burst rehearsal passes criteria above.
3. Hosting + runbook docs are updated and linked from docs index.
