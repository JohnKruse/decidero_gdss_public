# Hand-off to Codex — 2026-06-07

Written for a cold pick-up. Branch: **`codex/outlier-justification-api`**. Working
tree clean, all committed. Canary in play: **Plainspoken Marmot** (Phase 9).

## TL;DR — what just shipped

The Delphi controlled-feedback loop now runs entirely on **generic, configured
activities** — the worked proof of the paper claim "orchestration + configurable
activities obviate custom activities." Flow:

```
rank_order_voting  →  in-round facilitator-decision (how many ideas to open?)
                   →  brainstorming (comment surface)  →  rerank  →  round gate
```

Nothing in the comment path is bespoke. The old `outlier_justification` activity is
**deprecated but kept** (your call earlier was "keep, deprecated").

Full plan + design rationale: `plans/subplans/DELPHI_GENERIC_COMMENT.md` (COMPLETE).
Validation notes: `docs/DELPHI_VALIDATION.md`. Figures regenerated from the JSON.

## Verify

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/ -q          # 765 passed, 2 skipped
node --check app/static/js/meeting.js
```
End-to-end Delphi (real HTTP advance/control flow):
`app/tests/test_pages.py::test_adaptive_delphi_feedback_end_to_end`.

## How the pieces fit (so you don't re-derive it)

- **In-round decision (engine).** `FacilitatorDecisionStep` placed inside the
  iterate subcycle in `orchestrations/delphi.json` (between rank and comment),
  options `["open_comments","skip_comments"]`, report
  `delphi_round_agreement` with `config.feedback_selection: true`.
  `OrchestrationEngineStrategy._materialize_facilitator_decision` now inherits the
  round_index and computes the report (incl. `feedback_selection`) from the same
  round's just-closed ranking. `_compute_gate_report` only attaches
  `feedback_selection` when the report opts in, so the **boundary gate stays plain
  continue/conclude**. `resolve_prior_activity` skips facilitator-decision steps so
  the comment step still consumes the ranking as its input bundle.
- **Comment surface = generic brainstorming, configured (NOT forked).** Config:
  `seed_from_input`, `allow_new_ideas=false`, `comment_scope="selected"`,
  `feedback_policy`. `brainstorming_plugin.open_activity` seeds the ranked ideas as
  `Idea` rows in group-vote order with metadata
  `{seeded, stable_key, group_rank, group_median, group_iqr, agreement_band,
  commentable}`. The disputed subset = the facilitator's in-round count
  (`delphi_feedback_policy.selected_comment_count_for_round` +
  `build_delphi_feedback_selection`). The Delphi scoring lives in
  `delphi_feedback_policy` (a configured strategy), **never in the activity**.
  Enforcement is in `app/routers/brainstorming.py::submit_idea`
  (reject new top-level when `allow_new_ideas=false`; sub-comment only on
  `commentable` parents when `comment_scope="selected"`).
- **Cross-round display.** `RankOrderVotingManager._comments_from_brainstorming`
  reads the prior round's brainstorming bundle (metadata `comment_surface: true`),
  groups sub-comments by the seeded parent's `stable_key`, returns `{text, mine}`
  (mine from the sub-comment `user_id`). Legacy `outlier_justification` reader kept
  as a fallback. Rank summary also returns `delphi_round` ({round_number,
  max_rounds}) and richer `prior_round_feedback` (median, iqr, dispersion,
  your_prior_rank).
- **Frontend.** `app/static/js/meeting.js`: brainstorming panel orders by
  `group_rank`, shows agreement band + "Group median rank · spread", subdues
  non-commentable rows, relabels Reply→Comment, hides the new-idea form when
  `allow_new_ideas=false`. The facilitator-decision count selector renders for any
  decision whose report carries `feedback_selection` (report div moved out of the
  gate-only sub-panel in `meeting.html`).

## Guardrails (hold these)

- **One activity, configured — never fork.** No `brainstorming_delphi`, no
  `if delphi:` in activity code. If a behavior can't be a generic flag, add a
  generic knob to the activity/orchestrator contract instead.
- Method logic stays in Layer-2 (`delphi.json`) + Layer-3 strategies
  (`delphi_feedback_policy`, predicate/transform/summarizer/recommender registries).
- Cross-round comments stay peer-anonymous; `mine` is computed per-viewer, never
  persisted as identity in a bundle.

## Open / next (nothing blocking)

1. **Live drive-through** of "Classical Delphi test 10" — confirm the comment
   surface (seeded vote order, only disputed ideas commentable / others subdued,
   the in-round count prompt, Round N of M + spread/your-rank). Logic is covered by
   automated tests; this is eyeball confirmation since the issues were first caught
   in-app.
2. **outlier_justification deletion** — deferred. Currently deprecated-in-place
   (plugin/manager/router/`OutlierRationale` model + the JS justification panel all
   still exist). Decide whether to delete when writing the paper's methods section;
   if so, also drop the rank-manager legacy fallback reader.
3. **Zero-comment skip** is a soft skip today (empty queue / `skip_comments` →
   everyone sees nothing, facilitator advances). A true engine auto-advance past an
   empty comment step is future engine work.
4. Phase 9 has other pending steps (PHASE_9.md): Step 2 control-point card UI,
   Step 3 show-it-back views, Step 4 pattern-block canvas, Step 5 AI co-author.

## Files most worth reading first

- `orchestrations/delphi.json` (the method as data)
- `app/plugins/builtin/brainstorming_plugin.py` (`_seed_from_input`)
- `app/services/delphi_feedback_policy.py`
- `app/services/agenda_strategy.py` (`_materialize_facilitator_decision`,
  `_compute_gate_report`, `round_progress_for`, `resolve_prior_activity`)
- `app/services/rank_order_voting_manager.py` (`build_summary`,
  `_comments_from_brainstorming`, `_own_prior_ranks`)
