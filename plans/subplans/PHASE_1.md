# PHASE 1 — Contract Hardening

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Discovery reference:** [plans/00_DISCOVERY.md](../00_DISCOVERY.md)
**Elaboration reference:** [plans/02_ORCHESTRATION_ENGINE.md](../02_ORCHESTRATION_ENGINE.md)

**Phase objective:** Tighten and formalize the existing activity-plugin contract so the orchestration layer that follows in later phases composes over a specification, not over informal conventions. Phase 1 ships value independent of any engine work: it produces a defendable specification, closes the idempotency test gap, validates plugin manifests and bundle payloads at startup, audits ThinkLet claims against canonical sources, and elevates the reliability-policy contract surface from implementation detail to named architectural principle.

## Phase Canary

**Tangerine Larynx**

Use this exact two-word canary in Phase 1 notes, commit messages, schema header comments, test docstrings, and validation artifacts tied to this phase.

## Atomic Steps

### Step 1 — Author the JSON Schemas and Wire Startup Validation
Author three JSON Schema documents that formalize the previously-implicit data contracts: the activity-plugin manifest (covering every field declared on `ActivityPluginManifest` at [app/plugins/base.py:17-36](../../app/plugins/base.py), including all ThinkLet metadata), the activity-bundle payload (covering the `items` shape and the required `metadata` and `source` provenance fields per [app/models/activity_bundle.py:6-17](../../app/models/activity_bundle.py)), and the transfer-metadata payload (formalizing what [docs/TRANSFER_METADATA.md](../../docs/TRANSFER_METADATA.md) presently describes only in prose). The bundle-payload schema must permit the iteration-discriminator extension that Phase 3 will introduce, even though Phase 1 does not consume it yet. Each schema must carry a `Tangerine Larynx` Phase 1 canary line in its top-level description so downstream tooling can identify schemas authored under this effort. A loader at application boot must validate every built-in plugin manifest against the manifest schema and refuse to start if any plugin's declaration violates the contract; the bundle-payload schema must be invokable as a library function for use by tests and (later) by the engine.

Conclude this step by:
- Implementing the core logic as `docs/schemas/activity_manifest.schema.json`, `docs/schemas/bundle_payload.schema.json`, and `docs/schemas/transfer_metadata.schema.json`, plus the startup validator that wires the manifest schema into plugin registration.
- Creating or updating the relevant pytest file, preferring surgical edits to `app/tests/test_activity_plugins.py` (for manifest and bundle-payload assertions) and `app/tests/test_transfer_metadata.py` (for transfer-metadata schema conformance) over introducing a new test module unless coverage cannot reasonably be housed there.
- Updating docstrings and documentation so that `app/plugins/base.py`, `app/plugins/registry.py`, `app/models/activity_bundle.py`, and `docs/TRANSFER_METADATA.md` each cross-reference the authoritative schema file and identify Phase 1 by its `Tangerine Larynx` canary.

### Step 2 — Split the Contract Document and Name the Design Principles
Reshape the current [docs/ACTIVITY_CONTRACT_GUIDE.md](../../docs/ACTIVITY_CONTRACT_GUIDE.md) into two artifacts: a normative `docs/ACTIVITY_CONTRACT_SPEC.md` that carries the formal invariants, the numbered design principles DP1 through DP6 (with DP4 — reliability policy as manifest contract surface — promoted to first-class principle and explicitly defended in prose), the JSON Schemas authored in Step 1 referenced by path, and a populated DP-to-test mapping table; and a slimmed `docs/ACTIVITY_CONTRACT_GUIDE.md` that retains only implementer-facing how-to material and cross-references the spec for anything normative. The DP-to-test mapping table must list, for each of DP1 through DP6, the specific test module and test function that enforces it; rows for principles whose enforcement is added later in this phase (DP3 in Step 3, DP6 disposition in Step 3) may be marked with the test path they will resolve to once those steps complete. The reliability-policy section must explain why the manifest-declared, server-normalized, client-applied design is novel relative to the GDSS literature and why it is a candidate for reuse by future server-driven step kinds.

Conclude this step by:
- Implementing the core logic as the two finalized markdown documents (`docs/ACTIVITY_CONTRACT_SPEC.md` and the trimmed `docs/ACTIVITY_CONTRACT_GUIDE.md`), with cross-references threaded in both directions and the `Tangerine Larynx` canary appearing in the SPEC header.
- Creating or updating the relevant pytest file by editing existing modules (`app/tests/test_activity_plugins.py`, `app/tests/test_transfer_metadata.py`, `app/tests/test_categorization_contract.py`) so that each test referenced in the DP-to-test mapping table carries a docstring identifying which DP it enforces; no new pytest module should be introduced for documentation-only work.
- Updating docstrings and documentation so that `docs/INDEX.md`, `app/plugins/base.py` module docstring, and `docs/PLUGIN_DEV_GUIDE.md` direct readers to the SPEC for normative material and to the GUIDE for how-to.

### Step 3 — Close the DP3 Idempotency Gap and Resolve DP6 Disposition
Add direct test coverage for the DP3 invariant (idempotent `open_activity` under restart) across every built-in plugin — brainstorming, voting, rank-order voting, and categorization. For each plugin the test must construct a meeting and an activity row, invoke `open_activity(context, input_bundle)` twice with the same input bundle, and assert that no plugin-owned state row is duplicated (no extra ideas, no duplicated voting options, no extra ballot/voter rows, no parallel categorization buckets) and that the second invocation produces the same observable activity configuration as the first. The discovery audit confirmed this coverage is currently absent ([plans/00_DISCOVERY.md §12.2](../00_DISCOVERY.md)).

In the same step, resolve the DP6 disposition: either (a) wire `validate_config()` into the framework so it is invoked automatically at activity creation/update time and at engine-driven instantiation, with a corresponding test that confirms a deliberately-malformed config is rejected before reaching the plugin's lifecycle methods; or (b) explicitly document `validate_config()` as a plugin-controlled extension point that the framework will not invoke, with a test that asserts the documented contract (the base implementation is a passthrough and the framework does not call it). The choice between (a) and (b) is recorded in the SPEC authored in Step 2 alongside its rationale; the DP-to-test mapping table is updated to point at the resolving test.

Conclude this step by:
- Implementing the core logic as the new idempotency assertions for each built-in plugin and the chosen DP6 disposition (framework-invocation wiring or documented passthrough contract), all carrying `Tangerine Larynx` in their docstrings.
- Creating or updating the relevant pytest file by extending `app/tests/test_activity_plugins.py` with the DP3 coverage and the DP6-disposition assertion; new test modules must not be introduced for this work since the target module already houses plugin-lifecycle coverage.
- Updating docstrings and documentation so that the SPEC, the plugin ABC (`app/plugins/base.py`), and any plugin-level docstring that describes lifecycle semantics record the DP3 guarantee and the DP6 disposition consistently.

### Step 4 — ThinkLet Faithfulness Audit and FastFocus Resolution
For each built-in plugin, locate the canonical ThinkLet description in the Briggs, de Vreede, Nunamaker, and Kolfschoten literature and produce `docs/THINKLET_AUDIT.md`: a per-plugin section that names every declared tag in the plugin's manifest, quotes or paraphrases the canonical specification, and records the audit verdict (faithful as-is, faithful with documented caveat, or unjustified). Where the implementation diverges from the canonical specification, the divergence is either tightened in the plugin's behavior (if the divergence is incidental and can be corrected without altering the plugin's public contract per the Phase 1 scope) or the unjustified tag is removed from the manifest. The double-claim of `FastFocus` across VotingPlugin and CategorizationPlugin (flagged in [plans/00_DISCOVERY.md §13.5](../00_DISCOVERY.md)) must be explicitly resolved in this document: either both claims survive with an explanation of how the same ThinkLet legitimately serves two patterns (Evaluate vs. Reduce), or one of the two tags is removed from its manifest. Any manifest mutation performed in this step is the only manifest mutation Phase 1 authorizes, and the SPEC's DP-to-test mapping table is updated so the audit document is the cited evidence for DP5.

Conclude this step by:
- Implementing the core logic as `docs/THINKLET_AUDIT.md` (carrying `Tangerine Larynx` in its header), plus any manifest tightening or tag removal the audit requires within the built-in plugins.
- Creating or updating the relevant pytest file by extending `app/tests/test_activity_plugins.py` with assertions that the manifest tags declared by each built-in plugin match the post-audit declarations recorded in `docs/THINKLET_AUDIT.md`, so the audit document and the manifest cannot silently drift apart; no new pytest module is needed.
- Updating docstrings and documentation so that each built-in plugin's module docstring references the audit document and so that the SPEC's DP5 row in the DP-to-test mapping table cites both the audit document and the new conformance test.

## Phase Exit Criteria

Phase 1 clears only when the following command reaches `[100%]` and finishes without failures:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_activity_plugins.py app/tests/test_transfer_metadata.py app/tests/test_categorization_contract.py app/tests/test_transfer_transforms.py app/tests/test_transfer_api.py -v
```

Passing this command means:

- All three JSON Schemas (`activity_manifest`, `bundle_payload`, `transfer_metadata`) exist and every built-in plugin manifest and every transfer-metadata payload exercised by the suite conforms to them.
- The startup validator authored in Step 1 is wired into plugin registration and is exercised by the test suite via the registry's normal initialization path.
- Every built-in plugin has a DP3 idempotency test that passes, and the DP6 disposition (framework-invoked validation or documented passthrough) has a corresponding test that passes.
- The SPEC's DP-to-test mapping table cites real test functions, and a conformance test asserts that each built-in plugin's manifest matches the post-audit declarations in `docs/THINKLET_AUDIT.md`.
- No test that previously passed regresses, and no test docstring or fixture name introduced under Phase 1 omits the `Tangerine Larynx` canary where the step requirements call for it.

## Scope Boundary

This phase covers only the contract-hardening work that strengthens the existing activity-plugin substrate. The following items are explicitly deferred to later phases of [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md):

- Any introduction of `AgendaStrategy`, `LinearAgendaStrategy`, or refactor of router/service consumers of `meeting.agenda_activities` (Phase 2).
- Any change to `_find_previous_activity()` semantics, `ActivityBundle` storage to admit iteration discriminators, `BundleTransform` or `ConvergencePredicate` interfaces, and any server-side reliability execution analogue (Phase 3).
- Authoring of the orchestration-document schema or any step-kind implementation (Phase 4).
- Engine-driven agenda broadcast changes or facilitator-decision UI work (Phase 5).
- Authoring of `orchestrations/delphi.json`, the Delphi end-to-end test, or `docs/DELPHI_VALIDATION.md` (Phase 6).
