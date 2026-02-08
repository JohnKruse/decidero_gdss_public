# GitHub Task Migration Seed (from Task Master)

Source: pending TM tasks in `decidero_gdss_public` as of 2026-02-08.

Suggested labels:
- `type:feature`
- `area:backend`
- `area:frontend`
- `priority:high`
- `priority:medium`
- `status:todo`

## TM 53: Meetings: Export Metadata, Naming, and Import Preview
Priority: `high`

Improve meeting export/import usability with human-readable metadata, better file naming, and a pre-import preview step; keep archived meetings in DB status without purge/remap flows.

### Subtasks
- [ ] Add human-readable export metadata summary
- [ ] Improve exported bundle filename semantics
- [ ] Add import preview endpoint/flow
- [ ] Require explicit confirmation before import
- [ ] Document archival posture and defer purge/remap

### Acceptance
- [ ] Implemented
- [ ] Tests added/updated
- [ ] Docs updated (if applicable)

## TM 56: Activities: Facilitator Forced Shared View with Anchor Sync
Priority: `medium`

Enable facilitators to force participants to a synchronized activity/view state, then add anchor-based in-activity sync points (starting with Brainstorming) for practical visual alignment.

### Subtasks
- [ ] Phase 1: Add forced activity/view shared-state contract
- [ ] Phase 1: Facilitator UI controls for force/release
- [ ] Phase 1: Participant auto-follow behavior
- [ ] Phase 2: Brainstorming anchor-based visual sync
- [ ] Compatibility and fallback handling

### Acceptance
- [ ] Implemented
- [ ] Tests added/updated
- [ ] Docs updated (if applicable)

## TM 81: Open-Source Release Hardening And Cleanup
Priority: `high`

Prepare a clean, public-ready release of Decidero by removing legacy cruft, tightening security/deployment defaults, validating onboarding, and publishing with maintainable project hygiene.

Status note:
- [x] `81.1` Secret And Repository Hygiene Sweep
- [x] `81.2` Dependency And Legacy-Cruft Cleanup

### Remaining Subtasks
- [ ] Auth And Session Hardening Pass (`81.3`)
- [ ] Authorization And Input Validation Review (`81.4`)
- [ ] Deployment Modes And Operator UX Finalization (`81.5`)
- [ ] Session Health And Disconnect UX (`81.6`)
- [ ] CI Security And Release Guardrails (`81.7`)
- [ ] Public Docs And Onboarding Polish (`81.8`)
- [ ] Fresh-History Public Release Plan (`81.9`)

### Acceptance
- [ ] Implemented
- [ ] Tests added/updated
- [ ] Docs updated (if applicable)

## TM 82: New Activity: Rank Order Voting (Borda) with transfer/manual seeding, live facilitator progress, and agreement stats
Priority: `high`

Add a new meeting activity type for rank-order voting where participants reorder idea tiles and submit a full preference ranking; aggregate rankings with Borda count and present both consensus order and agreement statistics.

### Subtasks
- [ ] Scaffold rank_order_voting plugin and registry wiring
- [ ] Agenda builder config UX for manual idea entry and toggles
- [ ] Add SQLAlchemy model for ranking submissions and data-flag plumbing
- [ ] Implement option normalization and stable option IDs for rank-order voting
- [ ] Implement Borda scoring and agreement metrics math
- [ ] Add submission lifecycle: submit/resubmit, reset, results gating, and progress counts
- [ ] Complete RankOrderVotingPlugin seeding, stale-state reset, and output bundle generation
- [ ] Add rank-order voting API schemas and endpoints with RBAC and websocket broadcasts
- [ ] Define and implement presence-based active participant counting for progress
- [ ] Extend transfer commit pipeline to seed rank-order voting with provenance-preserving idea items
- [ ] Add meeting runtime template for rank-order voting panel and results modal
- [ ] Add CSS styling for draggable rank list and agreement metrics results
- [ ] Implement meeting.js rank-order voting UX (drag reorder, submit/resubmit, reset, results, progress)
- [ ] Add documentation and comprehensive pytest coverage for rank-order voting

### Acceptance
- [ ] Implemented
- [ ] Tests added/updated
- [ ] Docs updated (if applicable)
