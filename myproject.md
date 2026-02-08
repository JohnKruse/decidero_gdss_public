# Decidero GDSS Project

## Objectives

- Develop a Group Decision Support System (GDSS) to facilitate collaborative decision-making.
- Implement user authentication and authorization.
- Provide tools for brainstorming, idea organization, and voting.
- Ensure a responsive and user-friendly interface.

## Architecture

- FastAPI backend.
- Frontend (likely using HTML, CSS, and JavaScript).
- SQLite database.

## Key Components

- User authentication and authorization (`app/routers/auth.py`, `app/models/user.py`, `app/schemas/user.py`).
- Meeting management (`app/routers/meetings.py`, `app/schemas/meeting.py`).
- Brainstorming tool (`app/tools/brainstorming_tool.py`, `app/routers/brainstorming.py`).
- User interface (`app/static`, `app/templates`).
- Data Access Layer: `app/dal/user_dal.py`
- Models: `app/models/user.py`
- Schemas: `app/schemas/schemas.py`, `app/schemas/user.py`, `app/schemas/meeting.py`
- Tests: `app/tests`
- Requirements: `requirements.in`, `requirements.txt`
- Documentation: `requirements_docs/Decidero_GDSS_Requirements_Document_v1.6.md`

## Lessons Learned

- Importance of clear communication and collaboration within the team.
- Thorough testing is crucial for identifying and resolving issues early on.
- Proper database connection management is essential to avoid locking errors.
- Authentication middleware needs careful configuration to ensure correct redirection.

## To-Do List

- [ ] Implement user registration and login functionality.
- [ ] Design and implement the brainstorming tool.
- [ ] Develop the idea organization and voting mechanisms.
- [ ] Create a responsive user interface.
- [ ] Implement user roles and permissions.
- [x] Make `login`/`username` the canonical user identifier (JWT `sub`, auth dependencies, middleware, tests).
- [x] Enforce required, unique usernames and treat email as optional metadata.
- [ ] Add data structures and hooks to associate external OAuth identities with local users.
- [ ] **Investigate and resolve the SQLite database locking issue.**
- [ ] **Investigate and fix the authentication middleware redirection failure.**

- [ ] Address `pytest` errors from `pytest.txt`.

## API Updates

- `GET /api/meetings` now returns a `MeetingDashboardResponse` payload with scoped meetings, quick-action links, and aggregated notification/status counts. Query parameters `role_scope`, `status`, and `sort` let the frontend drive participant/facilitator views while staying aligned with the v1.6 dashboard checklist.
- Meeting creation and update flows accept optional `additional_facilitator_ids`, keep the `meeting_facilitators` join table synced automatically, and expose `facilitator_names` plus co-facilitator metadata in API responses.

## UI Updates

- The adaptive dashboard fetches `/api/meetings` on load, rendering facilitator and participant cards with status pills, quick-access buttons, and notification counts to satisfy the v1.6 “My Meetings” and “Notifications/Alerts” requirements.
- Dashboard tables now render the complete facilitator roster for each meeting, improving visibility into co-facilitator coverage and supporting name-based sorting.

## Manual Verification

- Login as a facilitator and confirm the dashboard lists both facilitated and participant meetings, with status filters and quick actions functioning.
- Toggle the status filter chips (All/Upcoming/In Progress/Completed) to ensure the meeting list updates without errors.
- Trigger a meeting with unread notifications and verify the Notifications panel reflects invitation/reminder counters and total badge.
- Create a meeting with one or more additional facilitators and confirm that roster changes appear in API responses and on the dashboard; update an existing meeting’s primary facilitator to ensure the join table remains consistent.
- For a quick participant UI review, create two meetings (one in the future, one marked completed) and assign a participant account. Use the “JOIN MEETING” quick action on the dashboard or visit `/meeting/join` to exercise the join flow and populate the participant activity summary.

## Completed Tasks

- 6/7/2025: Identity: Enforced username-first authentication (required unique usernames, optional emails) and updated UI/tests.
- 6/7/2025: UI: Simplified meeting creation/join experience and aligned styling with dashboard theme.
- 6/6/2025: Backend: Implement Meeting Creation API (Facilitator) — Implemented the POST `/api/meetings` endpoint in `app/routers/meetings.py`, including facilitator role check and database interaction via MeetingManager.
- 10/17/2025: Data/API/UI: Added `meeting_facilitators` backfill script, wired multi-facilitator creation/update flows, expanded dashboard payloads, and surfaced facilitator rosters in the frontend.
- 6/8/2025: Backend: Implement Meeting List/View API — Added user-scoped meeting list responses with notification heuristics and dashboard filters in `GET /api/meetings`.
- 6/8/2025: Frontend: Wired the participant dashboard to the meeting list API with status filters, quick actions, and notification summaries aligned to the v1.6 checklist.
## Instructions

1.  Set up the development environment.
2.  Create the database schema.
3.  Implement the user authentication system using FastAPI and JWT.
4.  Develop the core GDSS functionalities.
5.  Write unit tests for all components.
6.  Deploy the application to a production environment.
