# Delphi Validation - Oracular Quokka

This document records the Phase 6 synthetic validation for
`orchestrations/delphi.json`. The executable witness is
`app/tests/test_orchestration_engine.py::test_phase6_delphi_synthetic_cohort_end_to_end`.

## Evaluation Mode

This is an analytical synthetic validation of the packaged-method path. It
demonstrates that a reusable Delphi orchestration document can be represented,
loaded, executed, broadcast, and evaluated over the existing plugin substrate.
It is not a field study, not an empirical claim about real participant groups,
and not a claim that every live facilitator improvisation pattern has been
modeled. Empirical evaluation with real groups and product tuning for ad hoc
activities inserted into a running orchestration remain future work.

## Synthetic Cohort Fixture

The deterministic fixture lives at `app/tests/fixtures/delphi_synthetic.py`.
It carries the Oracular Quokka canary and defines five participants ranking
five items:

1. Reduce handoff latency
2. Improve meeting preparation
3. Standardize decision records
4. Automate follow-up tracking
5. Expose confidence intervals

The fixture exercises three IQR regimes:

| Regime | Fixture constant | Median IQR | Predicate result |
| --- | --- | ---: | --- |
| High-IQR opening round | `HIGH_IQR_OPENING_ROUND` | 2.0 | Does not fire because history has only one completed round |
| Contracted intermediate round | `CONTRACTED_INTERMEDIATE_ROUND` | 0.0 | Does not fire against round 1 because the median-IQR change is 2.0, above the document threshold |
| Terminal stable round | `TERMINAL_STABLE_ROUND` | 0.0 | Fires because the median-IQR change from the prior round is 0.0 |

The same fixture also exposes `NON_STABILIZING_ROUNDS`; the test loads the
Delphi document with an impossible predicate threshold of `-1.0` to prove the
document's `max_rounds` ceiling terminates execution after four rank-order
rounds when convergence is unavailable.

## Round Statistics

### Round 1 Feedback

The round-2 rank-order input bundle contains the transformed round-1 output
from `DelphiStatisticalAggregationTransform`.

| Item | Ranks | Median | IQR | Dispersion | Outliers |
| --- | --- | ---: | ---: | ---: | --- |
| Reduce handoff latency | 1, 1, 1, 1, 5 | 1.0 | 0.0 | 1.600 | p5 |
| Improve meeting preparation | 2, 5, 5, 3, 4 | 4.0 | 2.0 | 1.166 | none |
| Standardize decision records | 3, 3, 2, 5, 3 | 3.0 | 0.0 | 0.980 | p3, p4 |
| Automate follow-up tracking | 4, 4, 3, 2, 2 | 3.0 | 2.0 | 0.894 | none |
| Expose confidence intervals | 5, 2, 4, 4, 1 | 4.0 | 2.0 | 1.470 | none |

The test asserts the participant outlier contract concretely for "Reduce
handoff latency": the last synthetic participant is flagged in
`outlier_flags` and appears in the `outliers` list.

### Round 2 Feedback

The round-3 rank-order input bundle contains the transformed round-2 output.

| Item | Ranks | Median | IQR | Dispersion | Outliers |
| --- | --- | ---: | ---: | ---: | --- |
| Reduce handoff latency | 1, 1, 2, 1, 1 | 1.0 | 0.0 | 0.400 | p3 |
| Improve meeting preparation | 2, 2, 1, 3, 2 | 2.0 | 0.0 | 0.632 | p3, p4 |
| Standardize decision records | 3, 3, 3, 2, 4 | 3.0 | 0.0 | 0.632 | p4, p5 |
| Automate follow-up tracking | 4, 4, 4, 4, 3 | 4.0 | 0.0 | 0.400 | p5 |
| Expose confidence intervals | 5, 5, 5, 5, 5 | 5.0 | 0.0 | 0.000 | none |

### Round 3 Feedback

The terminal round repeats the contracted ranking fixture, so the transformed
round-3 median IQR remains 0.0. `IQRStabilityPredicate` therefore fires because
the change from the prior transformed round is 0.0.

## Adaptive Controlled-Feedback Policy

The Delphi orchestration also carries the default policy for the next adaptive
feedback pass on its comment/justification activity. This is declarative Layer-2
data, not engine logic:

- `comment_selection.strategy = adaptive_least_converged`
- default comment suggestion = 25% of ideas when disagreement is high
- facilitator-selectable cap = 50% of ideas
- `allow_skip = true`, so selecting zero ideas can skip comments and proceed to
  reranking
- agreement bands start from IQR (`green_max = 1.0`, `yellow_max = 2.0`)

### The in-round decision point

The "how many least-converged ideas to open for comment?" choice is an **in-round
facilitator-decision** step, placed in the round subcycle between the ranking and
the comment step (`rank → decide count → comment → rerank`). It reuses the generic
`facilitator-decision` step the engine already pauses on mid-sequence — no
Delphi-specific control. Its report (`delphi_round_agreement` with
`config.feedback_selection: true`) is computed from the same round's just-completed
ranking, so the facilitator sees the agreement bands and the count selector before
the comment step opens. Options are `open_comments` / `skip_comments` (skip = zero,
a soft pass straight to reranking). The boundary round-gate remains a plain
continue/conclude decision and no longer carries the count selector.

### Applying the facilitator's count (selected-idea comment mode)

The facilitator chooses how many least-converged ideas to open at the in-round
decision (`selected_comment_count`, persisted on the facilitator-decision bundle).
The same round's comment activity applies that decision when it opens:
it reads the same round's recorded count, scores the just-completed ranking by
disagreement (`build_delphi_feedback_selection`), switches into
`comment_scope = selected_items`, and seeds the top-N most-disputed ideas as
`selected_comment_items` — the same queue for every participant. A count of `0`
(or `skip_comments`) opens an empty queue (everyone sees "nothing to comment"), a
soft skip straight to reranking. With no recorded decision the activity keeps its
default outlier-only mode.

### Tuning the comment workload at fork time

The adaptive comment workload is a fork-and-tune knob. `apply_tuning` accepts
`comment_default_fraction` (the suggested share of least-converged ideas) and
`comment_max_fraction` (the facilitator-selectable cap), validates them in meeting
terms (each between 0% and 100%, and the suggested share never above the cap), and
writes them onto every feedback-policy comment step. The fork API and template
manager expose the same two knobs, the resulting inline document carries the tuned
fractions, and the plain-language method summary describes the workload ("the
most-disputed ideas are opened for comment — about N% suggested, up to M%"). The
default Classical Delphi template still ships 25% suggested / 50% cap.

### End-to-end verification

`app/tests/test_pages.py::test_adaptive_delphi_feedback_end_to_end` drives the
whole adaptive pass through the real HTTP advance/control flow: Round 1 ranks with
disagreement; the facilitator chooses `selected_comment_count = 1` at the gate;
starting the next round's comment step applies that decision (selected_items mode
opens the single most-disputed idea to every participant); a participant comments
through the justification API; and the Round 2 rank summary reports
`delphi_round = {round_number: 2, max_rounds: 4}`. This confirms the adaptive
least-converged controlled-feedback pass works in place of the participant-outlier
MVP.

The policy records the testing-driven design revision: select ideas by
disagreement band, not participants by outlier status.

**The comment step is a generic activity, not a bespoke one.** The shipped Delphi
method's comment step is the **brainstorming** activity configured as a comment
surface (`seed_from_input`, `allow_new_ideas=false`, `comment_scope=selected`,
plus this `feedback_policy`). Brainstorming seeds the ranked ideas from its input
bundle in group-vote order, opens the facilitator-chosen disputed subset for
comment (others subdued), and collects comments as sub-comments. This is the
paper's "orchestration obviates custom activities" claim in practice: one generic
activity, parameterized — no method-specific code. The earlier bespoke
`outlier_justification` activity is **deprecated** and no longer referenced by
`orchestrations/delphi.json`. See `DELPHI_GENERIC_COMMENT.md`, relocated to the
HICSS research repo under `dev_record/source/plans/subplans/` (see
[../plans/RELOCATED.md](../plans/RELOCATED.md)).

### Cross-round comment display (peer-anonymous, own-comment aware)

When a Round 2+ ranking opens, each item carries the prior round's collected
comments via `prior_round_rationales`. The output bundle stays unattributed
(comment text only — no user ids or per-person flags). The rank-order summary
annotates each comment per-viewer as `{text, mine}`: `mine` is `True` only for
the comment the requesting viewer privately authored, derived live from that
user's own `OutlierRationale` rows and never persisted into the bundle. Peers
therefore see one another's comments without authorship, while each participant
can still spot their own. The meeting UI renders the viewer's own comment with a
"Your comment" badge.

Each Round 2+ item also carries `prior_round_feedback` with the group's
`median`, `iqr`, and `dispersion`, plus `your_prior_rank` — the viewer's own rank
for that item last round (from their `RankOrderVote` rows on the prior round's
rank activity, matched across rounds by stable option key). The panel shows
"Group median rank M · spread S" alongside the agreement color band (so the
facilitator sees the numbers behind the band, not just the color) and "You ranked
it N" so each participant can compare their position against the group. The
current round's live Borda/avg tally is suppressed until at least one ranking is
submitted, since before that it is all zeros.

## Predicate Decisions

`IQRStabilityPredicate` requires at least two transformed rounds before it can
fire. After round 1 the history is insufficient. After round 2, the median IQR
has contracted from 2.0 to 0.0; that change is larger than the Delphi
document's `0.15` threshold, so the predicate does not fire. After round 3,
the median IQR remains 0.0; the change is 0.0 and the predicate fires.

The max-rounds branch is intentionally separate from the stable-cohort branch.
The test uses the same document shape and synthetic rankings with an impossible
threshold to isolate the hard ceiling: the engine materializes rounds 0, 1, 2,
and 3 and then exits because `max_rounds` is four.

## DP9 Confirmation

DP9 held for the central Delphi evaluation case. The Step 2 test asserts that
the Phase 6 canary does not appear in these files:

- `app/plugins/base.py`
- `app/plugins/builtin/brainstorming_plugin.py`
- `app/plugins/builtin/rank_order_voting_plugin.py`

That assertion is evidence that Delphi was instantiated through the
orchestration document, bundle transforms, predicates, and existing plugin
lifecycle hooks rather than by modifying the base plugin class or built-in
plugin lifecycle methods for this phase.

## Breaking Points Attested

The run indirectly attests to several previously resolved breaking points:

- BP-1, linear previous-activity assumptions: the Delphi loop depends on
  round-to-round prior-bundle resolution through the orchestration strategy.
- BP-3, iteration discrimination: multiple rounds of the same logical
  rank-order step persist distinct input and output bundles.
- BP-7, server-side reliability substrate: the transform and retry substrate
  remains covered by the Phase 3 smoke witness that Step 2 builds on.
- BP-5 and BP-10, realtime and frontend coherence: the Step 2 run checks that
  engine materializations broadcast through the Phase 5 `agenda_update` and
  `meeting_state` envelopes.

This document cites those executable witnesses rather than re-deriving their
phase-specific proofs.

## Generalization Decision

Oracular Quokka: Estimate-Talk-Estimate (ETE), Nominal Group Technique (NGT),
and additional packaged collaboration-engineering methods are formally
deferred to post-master-plan work for this submission cycle.

The decision is based on engineering scope rather than on a limitation in the
orchestration grammar. A useful ETE witness would require a second authored
fixture, method-specific bundle expectations, and a separate discussion-step
interpretation, but it would primarily exercise the same Phase 3 transforms,
Phase 4 `iterate` walker, Phase 5 broadcast envelope, and Phase 6 DP9 boundary
already covered by the Delphi run. NGT would add a different facilitation
shape and stronger UI expectations, which would be product work outside this
paper package's packaged-method path.

For the conference submission, the engine's generalization claim therefore
rests on Delphi alone: a named, literature-grounded method is represented as a
declarative orchestration, executed through existing plugins, evaluated across
multiple rounds, and validated without modifying the plugin substrate. The
deferred methods remain appropriate next reference orchestrations once there is
time to author fixtures that would add new evidence instead of duplicating the
Delphi proof.

## Boundary

The validation demonstrates that the packaged Delphi method can be expressed as
a declarative orchestration and executed over existing plugins. It does not
demonstrate a field deployment, facilitator improvisation semantics, arbitrary
hybrid insertion into active orchestration history, or the generalization of
every collaboration-engineering method. ETE, NGT, and additional packaged
methods are future work after the paper package.
