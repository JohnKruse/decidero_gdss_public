# 01 — MASTER PLAN: Role & Permission Collapse

**Depends on:** [plans/00_DISCOVERY.md](plans/00_DISCOVERY.md)

**Target state:** System-wide roles only (`super_admin`, `admin`, `facilitator`, `participant`) plus meeting roster membership. No per-meeting facilitator role remains anywhere in the runtime model, database model, API contract, or UI gate.

## Global Canary

**Wobble Biscuit**

Use this exact two-word canary in planning notes, implementation logs, and validation artifacts tied to this effort.

## Strategic Phases

### Phase 1 — Behavioral Contract Alignment
Define and lock the intended authorization model at the product-contract level so the codebase has one authoritative interpretation of who can view, facilitate, edit, manage roster, control activity, and delete within a meeting under the collapsed model.

**Success Gate**
- The repository contains one explicit canonical authorization contract for meeting capabilities derived only from `User.role`, `Meeting.owner_id`, and meeting roster membership.
- The contract explicitly resolves the asymmetries surfaced in discovery, including delete-meeting semantics, roster-management authority, meeting-control authority, and dashboard capability semantics.
- No contract text or test naming still treats `MeetingFacilitator`, `facilitator_links`, or `is_owner` on a facilitator row as part of the intended steady state.
- The planned phase count remains 7 or fewer; current scope is fully representable within this master plan without adding additional top-level phases.

### Phase 2 — Authorization Surface Unification
Collapse the backend’s fragmented meeting-authorization logic into one coherent capability model so every meeting-scoped decision is derived from the same durable facts and no backend enforcement path depends on per-meeting facilitator rows.

**Success Gate**
- Every meeting-scoped backend gate identified in discovery derives authorization from one canonical capability model.
- No backend enforcement decision in `app/routers/` or meeting-scoped logic in `app/data/` depends on `facilitator_links` or `MeetingFacilitator`.
- Meeting-scoped capability outcomes are consistent across meetings, users, activities, transfer/export paths, and user-directory meeting context.
- The only remaining meeting authority inputs are global role, ownership, and roster membership.

### Phase 3 — Interface and API Coherence
Align all server-rendered meeting UI gates, frontend capability state, and API response semantics with the unified backend model so the visible interface and the enforced permissions cannot diverge.

**Success Gate**
- No per-meeting control in templates or frontend state is gated purely by system role when the backend treats it as meeting-scoped authority.
- Meeting page controls, dashboard meeting affordances, and any capability flags exposed to JavaScript reflect the same authorization result the backend enforces.
- A user who lacks meeting-scoped authority sees no facilitator-only meeting controls and receives backend denial for the same actions.
- A user who has meeting-scoped authority sees the corresponding controls and can successfully use the matching endpoints.

### Phase 4 — Data Model Collapse
Remove the per-meeting facilitator concept from the persistent model and runtime object graph so the schema itself matches the target authorization design.

**Success Gate**
- `MeetingFacilitator`, `meeting_facilitators` storage, and related ORM relationships are absent from the active application schema and model layer.
- `Meeting.owner_id` remains the sole persisted owner concept; no parallel persisted ownership flag survives.
- No active code path creates, updates, deletes, or reads per-meeting facilitator assignments.
- The application can boot, create meetings, manage rosters, and execute meeting workflows without any facilitator-assignment table or startup shim.

### Phase 5 — Compatibility and Contract Cleanup
Normalize all outward-facing contracts that previously exposed or depended on facilitator assignments so exports, imports, serialized meeting payloads, and tests reflect the collapsed model without leaving legacy semantics in the active contract.

**Success Gate**
- Active API responses no longer expose `facilitator_links`, facilitator assignment arrays, or equivalent per-meeting facilitator artifacts as live contract elements.
- Exported meeting data no longer writes facilitator assignment structures tied to the old model.
- Any required legacy import compatibility is explicitly one-way and isolated to compatibility handling, not reused as active authorization logic.
- The test suite no longer encodes the old auto-grant or stale-facilitator behavior as intended behavior.

### Phase 6 — End-to-End Validation and Merge Readiness
Prove that the collapsed model is stable across the full application surface and that the originally observed incoherence is gone in practice, not just in code structure.

**Success Gate**
- Automated validation for the role/meeting authorization surface passes with zero failures.
- The original failure modes from discovery are no longer reproducible:
  - demoting a user from facilitator to participant removes meeting-scoped facilitator powers,
  - removing and re-adding a participant does not restore stale facilitator powers,
  - UI affordances and backend authorization remain in sync after role and roster changes.
- No non-test references to `MeetingFacilitator`, `meeting_facilitators`, `facilitator_links`, or facilitator auto-assignment helpers remain in the active codebase, except intentionally isolated backward-compatibility handling if retained.
- The branch is in a technically shippable state with a coherent diff, passing verification, and no unresolved dependency on the removed model.

## Phase Count Check

This plan contains **6 strategic phases**. Scope remains under the 7-phase ceiling, so no halt is required.

## Scope Boundary

This master plan covers only the role/permission collapse described in discovery. The following discovery items remain out of scope unless separately authorized:

- WebSocket authentication and authorization gaps.
- Activity-roster dual-source-of-truth cleanup unrelated to facilitator-role collapse.
- Cross-tool participant-lock consistency outside the core role-collapse path.
- Unrelated enum-string cleanup that does not affect the authorization model.

---

*End of MASTER PLAN. This document is intentionally macroscopic. Tactical sequencing belongs in phase-entry execution plans, not here.*
