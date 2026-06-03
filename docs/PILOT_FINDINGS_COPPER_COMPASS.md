# Pilot Findings — Copper Compass

First internal dry-run of the Phase 7 template path, recorded against the
[USER_TESTING_GUIDE](USER_TESTING_GUIDE.md) Pilot Report Outline. This satisfies
the Phase 7 Step 6 requirement to record pilot findings against the template flow
and the paper claims.

## 1. Session summary

A facilitator-operated dry-run that launched the built-in **Classical Delphi**
template (Workflow B) and ran it live with two participant logins submitting ideas
(Workflow C). The launch path worked through participant selection and the first
activity, then surfaced three blocking defects and two research-level gaps before a
full Delphi cycle could complete. The first major finding (no runtime advancement
past round 1) is the origin of Phase 8.

## 2. Build and environment

- Environment: Local.
- Branch: `codex/orchestration-template-bridge`.
- Relevant commits produced in response: `c9514db` (migration), `05f2fa2`
  (participant picker), and the Phase 8/9 plans (`e3012a5`).
- Database: pre-existing local `decidero.db` (carried the schema drift below).

## 3. Participants and roles

- One facilitator/operator (maintainer).
- Two participant logins used to submit Round 1 ideas.
- No naive first-time users in this pass (see Documentation gaps / Recommended next
  action).

## 4. Workflows attempted

- Workflow B — Start from Template (Classical Delphi).
- Workflow C — Run a Live Meeting (Round 1 brainstorming, then attempted advance).

## 5. Workflows completed without observer help

- Dashboard → `Start from Template` → Classical Delphi guided start → participant
  selection → meeting creation → Round 1 brainstorming with live idea submission.
- The four-choice creation IA (`Start from Template`, `Design with AI`,
  `Design Yourself`, `Import Meeting`) was navigated without assistance by the
  operator, but operator familiarity confounds this — naive comprehension was not
  tested.

## 6. Blockers

| # | Finding | Severity | Decision |
| --- | --- | --- | --- |
| B1 | Live Delphi meeting page raised `sqlite3.OperationalError: no such column: activity_bundles.logical_step_id`. The `ActivityBundle` model added `logical_step_id`/`round_index` without a SQLite migration, so any pre-existing DB failed every bundle read. | Blocker | **Fixed now** — migration added to `ensure_sqlite_schema` and applied to the live DB (`c9514db`). Regression-relevant tests pass. |
| B2 | After stopping the Round 1 brainstorming activity, the orchestration-backed meeting could not advance to the rank-order voting round. `OrchestrationEngineStrategy.create_activity` is only invoked once at creation; no endpoint or UI control advances the engine. The facilitator was stuck with no next step. | Blocker | **Deferred to Phase 8** (Deliberate Heron) — runtime advancement wiring + engine state rehydration. Cannot be a quick fix; it is the body of Phase 8. |
| B3 | The orchestration template start page shipped a hand-rolled free-text "Names, logins, or emails" box submitting a `participant_contacts` field the backend never consumed, so template-created meetings silently received zero participants. | Blocker | **Fixed now** — reuse the shared directory picker and submit real `participant_ids` (`05f2fa2`). |

## 7. High-severity issues

| # | Finding | Severity | Decision |
| --- | --- | --- | --- |
| H1 | Facilitator/AI decisions are recorded but do not steer flow: the `conditional` primitive was deferred in Phase 4, so a `facilitator-decision` choice is captured into the bundle stream and the engine advances linearly regardless. Delphi's "do another cycle?" decision is therefore silent automation (IQR predicate + `max_rounds`) with no facilitator control point — counter to the paper's facilitation-support claim (UF8). | High (research) | **Deferred to Phase 8 Step 3** (narrow loop-control decision) and **Phase 9** (authoring). |

## 8. Usability friction

- The guided orchestration start page sets the expectation that future rounds
  appear at runtime gates, but with B2 unresolved there is no gate to reach, so the
  promise currently reads as a dead end to the facilitator. Resolving B2 (Phase 8)
  is the precondition for evaluating this copy honestly.

## 9. Documentation gaps

- Naive-user comprehension of the four-choice creation IA (templates vs AI design
  vs manual vs import) was **not** formally tested in this pass because the operator
  was the maintainer. The dashboard vocabulary claim remains unverified by fresh
  users.
- Authoring control points currently requires hand-editing Layer-2 orchestration
  JSON — not feasible for non-technical facilitators. Captured as the motivation for
  **Phase 9** (Plainspoken Marmot).

## 10. Deferred findings

- B2 → Phase 8 (runtime advancement + cycle gate).
- H1 → Phase 8 Step 3 + Phase 9.
- Non-technical authoring of control points → Phase 9.
- Naive-user dashboard comprehension → next pilot session with first-time users.

## 11. Recommended next action

1. Build **Phase 8, Step 1** (engine state rehydration) — the precondition for all
   runtime advancement.
2. Run a second Copper Compass session with **first-time users** to test dashboard
   vocabulary comprehension once the Delphi loop runs end-to-end.

## Findings against the paper claims

- **Templates make reusable methods understandable:** Partially supported. The
  template landing and guided start communicated Classical Delphi as a packaged
  method, and the operator launched it without help. Not yet demonstrable
  end-to-end because the method cannot complete its cycles (B2).
- **AI/facilitator decision support lowers the facilitation burden:** Not yet
  demonstrable. The decision machinery exists but does not steer flow (H1); the
  facilitation-support claim becomes testable only after Phase 8 Steps 2–4.
- **Ordinary agenda templates remain distinct from orchestration-backed methods:**
  Supported. Ordinary templates run through the standard creator; the Classical
  Delphi template bound to the packaged orchestration and used the guided start page
  rather than a hand-authored agenda, consistent with the Phase 7 design.
