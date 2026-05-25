# ThinkLet Faithfulness Audit

Tangerine Larynx Phase 1 audit of built-in activity manifest ThinkLet claims.

## Sources Consulted

- Briggs, de Vreede, Nunamaker, and Tobey, "ThinkLets: Achieving predictable, repeatable patterns of group interaction with Group Support Systems (GSS)", HICSS 2001, DOI `10.1109/HICSS.2001.926238`.
- Briggs and de Vreede, "ThinkLets: Building Blocks for Concerted Collaboration", GroupSystems reference material, 2001.
- de Vreede, Kolfschoten, and Briggs collaboration-engineering pattern references that classify ThinkLets under Generate, Reduce/Clarify, Organize, Evaluate, and Build Consensus.
- Publicly indexed secondary summaries that identify FreeBrainstorm, LeafHopper, FastFocus, BucketWalk, and StrawPoll in collaboration-engineering processes.

## Audit Method

Each retained manifest tag below is listed as `Manifest tag`. The conformance
test in `app/tests/test_activity_plugins.py` treats these lines as the
post-audit declaration set and fails if a built-in manifest silently drifts.

Verdicts:

- `faithful as-is`: implementation directly matches the named ThinkLet's core collaboration pattern.
- `faithful with documented caveat`: implementation captures the relevant pattern but has a narrower or platform-specific execution.
- `removed`: the tag was removed because the audit could not defend it as a canonical ThinkLet claim for this plugin.

## BrainstormingPlugin

Tool type: `brainstorming`

- Manifest tag: `FreeBrainstorm (anonymous, parallel — maximises idea volume)`
- Manifest tag: `LeafHopper (sub-comments for inline Clarify without interruption)`

Canonical basis:

- FreeBrainstorm is a Generate-pattern ThinkLet for broad, parallel idea generation around a prompt, with participants drawing inspiration from each other's contributions.
- LeafHopper is a Generate-pattern ThinkLet where participants contribute detail to topics they know or care about. In Decidero, sub-comments let participants add clarifying detail to existing ideas without interrupting the main idea-generation flow.

Verdict: faithful with documented caveat.

The brainstorming plugin faithfully supports FreeBrainstorm through parallel idea capture, anonymous submission options, and a shared idea stream. The LeafHopper claim is narrower: Decidero implements topic-hopping/detail contribution as sub-comments on ideas rather than a separate facilitator-scripted topic rotation. The retained claim is justified as a Clarify-adjacent implementation of the same contribution pattern.

## VotingPlugin

Tool type: `voting`

- Manifest tag: `StrawPoll (temperature check — quick single-round vote to gauge sentiment)`

Canonical basis:

- StrawPoll is an Evaluate-pattern ThinkLet used to obtain a quick group assessment of concepts, often after a reduction step has produced a candidate list.
- FastFocus is a Reduce/Clarify-pattern ThinkLet for extracting a clean, non-redundant list of key issues from divergent comments and agreeing on wording.

Verdict: faithful with documented caveat; FastFocus removed.

The voting plugin supports a StrawPoll-like quick evaluation over a fixed option set. The implementation is dot voting rather than a full criterion-by-criterion ThinkLet script, so the claim is retained with that platform caveat. The previous FastFocus tag was removed because multi-vote prioritization does not perform FastFocus's canonical extraction and wording-cleanup work.

## RankOrderVotingPlugin

Tool type: `rank_order_voting`

No retained Manifest tag entries.

Canonical basis:

- Borda count is a preferential voting rule in which participants rank options and scores are aggregated from those ranks.
- The audit did not locate sufficient evidence that `Borda Vote` is a canonical named ThinkLet in the Briggs, de Vreede, Nunamaker, and Kolfschoten pattern language.

Verdict: removed.

The rank-order voting plugin remains a valid Evaluate-pattern activity, but its former `Borda Vote` manifest entry was removed because the evidence supports Borda as the scoring method, not as a canonical ThinkLet tag. The implementation documentation may continue to describe Borda-style aggregation outside the ThinkLet manifest field.

## CategorizationPlugin

Tool type: `categorization`

- Manifest tag: `BucketWalk (thematic grouping — organise items into named topic buckets)`
- Manifest tag: `FastFocus (keep/discard Reduce — narrow a long list to a workable shortlist)`

Canonical basis:

- BucketWalk is used around bucket/category work: the group reviews category contents so items are appropriately placed and understood.
- FastFocus extracts a clean list of key issues from divergent comments and clarifies wording. It is commonly followed by evaluation steps such as StrawPoll when prioritization is needed.

Verdict: faithful with documented caveat.

The categorization plugin faithfully supports the bucket-oriented organization surface needed for BucketWalk, though the current implementation is facilitator-led rather than a fully scripted group walk through every bucket. The retained FastFocus claim is limited to Reduce-mode configurations such as keep/discard/maybe buckets that narrow a long idea list. The audit resolves the previous double-claim by removing FastFocus from VotingPlugin and retaining it only here as the Reduce-oriented claim.

## FastFocus Double-Claim Resolution

The previous manifest set claimed FastFocus for both VotingPlugin and
CategorizationPlugin. This audit resolves the conflict by removing FastFocus
from VotingPlugin. Voting evaluates or prioritizes an already-formed option
set; it does not extract and clean the option list from divergent material.
Categorization can support the Reduce side of FastFocus when configured with
keep/discard-style buckets, so it retains the tag with the caveat above.
