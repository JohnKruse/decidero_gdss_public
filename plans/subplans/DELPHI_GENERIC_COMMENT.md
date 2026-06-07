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

## "Reskin" means configure, not fork

There is exactly **one** brainstorming activity. Stage B does **not** copy it,
create a `brainstorming_delphi` variant, or add `if delphi:` branches. The only
code added to the activity is **generic, reusable configuration capability** — new
flags it honors and the ability to render from its incoming data. That one-time
investment is what lets Delphi (and any future method) get a bespoke *feel* through
**config + data alone**:
- Generic capability added once to the activity: `allow_new_ideas`,
  `seed_from_input`, comment-scope `all|eligible`, and rendering per-item stats /
  eligibility / order from its input bundle.
- Pure config + data for Delphi: `delphi.json` sets the flags and labels; the
  ranking bundle supplies order + group stats; the in-round decision supplies the
  eligible subset. No Delphi code in the activity.

If a needed behavior can't be expressed as a generic flag the activity honors,
that's a signal to add a generic knob to the activity/orchestrator contract — not
to special-case the method.

## Design tenets

- **No new activities, no forks, no Delphi-specific branches in activity code.**
  Brainstorming gains *generic, config-driven* behaviors (comment-only,
  seed-from-input, commentable subset) that any method can use — not `if delphi`
  logic.
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

### Stage B — Generic comment surface on brainstorming — DONE

Implemented as configuration of the single brainstorming activity (no fork):
- **B1** generic flags + API enforcement: `allow_new_ideas=false` (reject new
  top-level ideas) and `comment_scope="selected"` (sub-comments only on items
  flagged `commentable`). Defaults preserve today's behavior.
- **B2** `brainstorming.open_activity` with `seed_from_input=true` seeds the input
  bundle's ranked ideas as ordered top-level `Idea` rows, annotated for display
  (group median/IQR/agreement band/rank) and flagged `commentable` for the
  facilitator's chosen disputed subset. Scoring + the in-round count lookup live in
  `delphi_feedback_policy` (a configured strategy); the activity is generic +
  idempotent. The aggregator receives the bundle's vote metadata so group stats are
  derived even when the raw items lack them.
- **B3** the brainstorming panel orders by group rank, shows the agreement band +
  group median/spread, subdues non-eligible items (no Comment button), relabels
  Reply → Comment, and hides the new-idea form when `allow_new_ideas=false`.
- **B4** `delphi.json` comment step is now `tool_type: brainstorming` with
  `seed_from_input/allow_new_ideas/comment_scope/feedback_policy` config.

### Stage B (original) — Generic comment surface on brainstorming

**Eligibility-location decision (keeps brainstorming generic):** brainstorming
itself contains *no* Delphi scoring. Its generic contract is "seed items from the
input bundle in the given order; allow comments only on items whose metadata says
`commentable`." The least-converged scoring + the facilitator's count are applied
*once*, when the in-round decision resolves: the resume persists
`eligible_stable_keys` (top-N from the report's `feedback_selection.items`) on the
decision bundle, and the comment step's seeding stamps `commentable` onto exactly
those seeded items. The Delphi math stays in `delphi_feedback_policy`; brainstorming
reads booleans. (Same compromise the current `outlier_justification` apply-on-open
uses, but moved behind a generic flag so no method logic lives in the activity.)

Original sketch:
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

### Stage C — Cross-round display from generic output — DONE
- The next round's rank-order summary reads prior comments from the brainstorming
  comment bundle (marked `comment_surface`): sub-comments grouped by the seeded item
  they reply to, keyed by stable option key, peer-anonymous with the viewer's own
  comment privately flagged (`mine` from the sub-comment's `user_id`). The legacy
  `outlier_justification` reader remains as a fallback. See
  `RankOrderVotingManager._comments_from_brainstorming`.

### Stage D — Retire the bespoke path — DONE (keep-deprecated)
Decision: **keep `outlier_justification` in the tree, marked deprecated** (lower
risk; revisit deletion when writing the paper's methods section).
- `delphi.json` no longer references it (swapped in B4); the live comment step is
  the generic brainstorming surface.
- Deprecation notes added to the plugin, manager, router, and `OutlierRationale`
  model. The rank-manager keeps a fallback reader for the legacy bundle shape.
- Figures regenerated from `delphi.json` (`scripts/export_orchestration_diagram.py`)
  and the figures README + `DELPHI_VALIDATION.md` updated to the generic comment
  surface; paper outline §F.1 noted as superseded.

**This plan is complete.** The Delphi comment flow is `rank → in-round decision →
comment (generic brainstorming) → rerank`, with cross-round anonymized comment
display, all on generic activities + Layer-2 config.

## Open question for you
Stage D disposition of `outlier_justification`: **retire from `delphi.json` but keep
the code (deprecated)**, or **remove the activity entirely**? Keeping it is lower
risk; removing it makes the "no custom activities" claim cleaner.
