# Delphi Comment Step on a Generic Activity (paper-thesis alignment)

**Canary:** Plainspoken Marmot
**Parent:** [PHASE_9.md](PHASE_9.md) Step 3A · supersedes the bespoke
`outlier_justification` comment surface.

## Why

The HICSS thesis is that **orchestration (Layer-2 data) obviates custom
activities** — a small set of generic activities, reconfigured by the
orchestration document, should field complex methods. The current Delphi comment
step uses `outlier_justification`, a *bespoke* activity built for one method.
That undercuts the very claim Delphi is meant to demonstrate.

This plan moves the Delphi comment step onto **generic activities only**:
- the comment surface becomes **brainstorming** (a generic "collect items +
  comment on them" activity), configured via the orchestration document;
- the "how many disputed ideas to open?" choice becomes an **in-round
  facilitator-decision** step (the generic control point), placed between rank and
  comment so the flow is `rank → decide count → comment on selected → rerank`.

No method-specific activity code. Method logic stays in `delphi.json` + the input
bundles the engine already passes between steps.

## Design tenets

- **No new activities, no Delphi-specific branches in activity code.** Brainstorming
  gains *generic, config-driven* behaviors (comment-only, seed-from-input,
  commentable subset) that any method can use — not `if delphi` logic.
- **Display data rides on the input bundle.** Each idea's group rank / median / IQR
  / agreement band comes from the prior `rank_order_voting` output (already
  delivered to the next step as an input bundle). The activity renders what its
  input carries; it does not compute Delphi stats.
- **Eligibility is data.** The in-round decision selects the top-N least-converged
  ideas; the comment step opens those for comment and subdues the rest.

## Data model fit (brainstorming `Idea` rows)

- Seeded ideas → top-level `Idea` rows (one per ranked idea), in group vote order,
  with `idea_metadata = {group_rank, group_median, group_iqr, agreement_band,
  eligible: bool, stable_key}`.
- A participant comment → a **sub-comment** `Idea` row (`parent_id` = the seeded
  idea), which brainstorming already supports via `allow_subcomments`.
- New top-level ideas are disabled in this mode; sub-comments are accepted only on
  `eligible` parents.

This reuses the existing `Idea` / sub-comment plumbing and the existing
brainstorming output bundle (the next round's cross-round display reads sub-comments
the same way it reads rationales today).

## Stages (each ends green + committed)

### Stage A — In-round facilitator decision point (engine + orchestration) — DONE
- `delphi.json`: a `facilitator-decision` step now sits in the round subcycle
  **between** `rank_order_voting` and the comment step, options
  `["open_comments", "skip_comments"]`, carrying a `delphi_round_agreement` report
  with `config.feedback_selection: true`. The boundary round-gate stays
  continue/conclude.
- Engine: `_materialize_facilitator_decision` now inherits the iterate
  `round_index` and, when the step declares a report inside an iterate, computes it
  (including `feedback_selection`) from the **same round's** just-completed rank
  output via the walker's `_collect_round_output` / `_compute_gate_report`.
- `_compute_gate_report` only attaches `feedback_selection` when the report opts in
  (`config.feedback_selection: true`), so the selector lands on the in-round
  decision and not the boundary gate.
- The count-selector UI now renders for any decision whose report carries
  `feedback_selection` (the report div moved out of the gate-only sub-panel).
- `resolve_prior_activity` skips facilitator-decision steps when finding a
  consumer's donor, so the comment step after `rank → in-round decision` still
  consumes the ranking output.
- The comment step (`outlier_justification` for now) reads the **same-round**
  decision (`_selected_comment_count_for_round`); `skip_comments` → 0.
- Verified by `test_pages.py::test_adaptive_delphi_feedback_end_to_end` (in-round
  flow) + engine/diagram/schema tests. Full regression green.

### Stage B — Generic comment surface on brainstorming
- Add generic brainstorming config flags (defaults preserve today's behavior):
  `allow_new_ideas` (default `true`), `seed_from_input` (default `false`),
  `comment_target` (`"all"` default | `"eligible_only"`).
- `brainstorming.open_activity`: when `seed_from_input`, seed the input bundle's
  ideas as ordered top-level `Idea` rows with the metadata above; mark `eligible`
  from the in-round decision's selected set; enable sub-comments; disable new ideas.
- `submit_idea`: enforce `allow_new_ideas: false` (reject top-level) and
  `comment_target: eligible_only` (sub-comment only on eligible parents).
- Frontend brainstorming panel: in this mode render ideas in seeded order with the
  agreement badge + "Group median rank M · spread S · You ranked it N", a comment
  box on eligible ideas, subdued styling + no box on the rest, and the private
  "Your comment" flag.
- `delphi.json`: swap the comment step `tool_type` from `outlier_justification` to
  `brainstorming` with the new config.

### Stage C — Cross-round display from generic output
- The next round's rank-order summary reads prior comments from the brainstorming
  sub-comment output bundle (same shape it reads rationales from today), keeping
  peer-anonymity + the per-viewer `mine` flag.

### Stage D — Retire the bespoke path + tests/docs/e2e
- `delphi.json` no longer references `outlier_justification`; leave the activity in
  the tree marked deprecated (or remove if nothing else uses it) — decided with you.
- Update/replace the justification tests with brainstorming-comment-mode tests;
  refresh the end-to-end Delphi regression; update `DELPHI_VALIDATION.md`, the
  paper outline, and this plan.

## Open question for you
Stage D disposition of `outlier_justification`: **retire from `delphi.json` but keep
the code (deprecated)**, or **remove the activity entirely**? Keeping it is lower
risk; removing it makes the "no custom activities" claim cleaner.
