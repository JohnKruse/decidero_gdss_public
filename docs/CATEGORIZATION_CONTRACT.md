# Categorization Contract (V1)

This document defines the versioned contract for the `categorization` activity.
It is the compatibility baseline for Task Master `#84`.

## Scope

- Standard in/out bundle compatibility with existing plugin pipeline
- Transfer metadata + provenance retention compatibility
- Forward-compatible schema evolution rules
- Validation fixtures for facilitator-live and parallel-ballot flows

## Canonical References

- `docs/ACTIVITY_CONTRACT_GUIDE.md`
- `docs/PLUGIN_DEV_GUIDE.md`
- `docs/TRANSFER_METADATA.md`
- `docs/CATEGORIZATION_ACTIVITY_SPEC.md`
- `app/schemas/categorization_contract.py`
- `app/tests/fixtures/categorization_contract_fixtures.py`

## Versioning

- `schema_version = 1` for config, runtime state, and output payloads.
- Additive fields are allowed.
- Removing required fields or changing required field meanings is breaking.

## Config Schema (V1)

Required:
- `schema_version: 1`
- `mode: FACILITATOR_LIVE` (canonical runtime mode)

Compatibility acceptance:
- `mode: PARALLEL_BALLOT` is accepted for backward compatibility in config payloads.
- Current runtime behavior normalizes legacy `PARALLEL_BALLOT` to `FACILITATOR_LIVE`.
- Legacy parallel endpoints remain deprecated and return `410 Gone`.

Core fields:
- `items: [string | item-object]`
- `buckets: [string | bucket-object]`
- `single_assignment_only: bool`
- `allow_unsorted_submission: bool`
- `agreement_threshold: float [0,1]`
- `minimum_ballots: int >= 0`
- `tie_policy: TIE_UNRESOLVED | TIE_BREAK_FACILITATOR | TIE_BREAK_BY_RULE`
- `missing_vote_handling: ignore | unsorted`
- `private_until_reveal: bool`

## Runtime State Schema (V1)

Required:
- `schema_version: 1`
- `meeting_id`
- `activity_id`
- `mode` (`FACILITATOR_LIVE`)

Core fields:
- `locked: bool`
- `buckets: []`
- `assignments: { item_id -> category_id|null }`
- `ballots: { user_id -> { item_id -> category_id|null } }`
- `agreement_metrics: { item_id -> metric-block }`

## Output Schema (V1)

Required:
- `schema_version: 1`
- `meeting_id`
- `activity_id`
- `categories: [{category_id,title,description?,item_ids[]}]`
- `finalization_metadata`

`finalization_metadata` requires:
- `mode`
- `finalized_at`

Optional:
- `facilitator_id`
- `agreement_threshold`
- `minimum_ballots`
- `ballot_count`
- `tallies`
- `ballots`

## Transfer Compatibility Rules

- Preserve `metadata` and `source` from incoming transfer items.
- Respect transfer metadata policy: metadata is retained independent of content toggles.
- Comments-in-parentheses format must match transfer path behavior:
  `Idea text (Comments: c1; c2; c3)`.

## Compatibility Policy

Allowed without version bump:
- adding optional fields
- adding optional metadata blocks

Requires version bump:
- removing required fields
- changing required field semantics
- changing required enum values incompatibly

## Validation And Fixtures

- Contract validators: `app/schemas/categorization_contract.py`
- Fixtures:
  - `app/tests/fixtures/categorization_contract_fixtures.py`
- Tests:
  - `app/tests/test_categorization_contract.py`
  - `app/tests/test_transfer_comment_format_parity.py`
