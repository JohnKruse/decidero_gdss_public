# Master Plan: Flexible Within-Track Workflow Patterns

**Canary**: Cobalt Fennel

**Objective**: Replace the formulaic "brainstorming → categorization → voting" within-track prescription with a context-aware pattern selection system where the AI reasons about which collaboration sequence fits each track's goal, time budget, and deliverable type — drawing from the existing Standard and Extended Sequence library.

**Prerequisite**: `plans/00_DISCOVERY.md` (technical audit completed 2026-03-08)

---

## Phase 1 — Pattern Library Unification

Reframe the existing Standard and Extended Sequences as a single composable pattern library available at any scope (full session, phase, or within-track). Remove the artificial boundary between "session-level sequences" and "track-level rules."

**Scope**:
- `app/config/prompts/meeting_designer.yaml` (system_suffix: sequences + breakout guidelines + generate_agenda within-track rules)
- `app/services/meeting_designer_prompt.py` (build_generation_prompt, build_outline_prompt)

**Success gate**: The generation prompt and outline prompt reference the unified pattern library with per-pattern selection criteria (time, deliverable type, problem complexity). No fixed "Activity 1 → Activity 2 → Activity 3" recipe remains in any prompt surface. The hard constraint that tracks must have 2+ activities is preserved.

---

## Phase 2 — Sequencing Intelligence

Surface the currently unused plugin metadata (`input_requirements`, `output_characteristics`, `when_not_to_use`) into the prompts so the AI can reason about valid activity ordering rather than memorizing recipes.

**Scope**:
- `app/services/meeting_designer_prompt.py` (`_format_activity_block`)
- `app/plugins/builtin/*.py` (audit metadata quality — are the descriptions sufficient for sequencing reasoning?)

**Success gate**: Each activity block in the system prompt includes input/output characteristics and contraindications. The AI can determine from metadata alone that categorization cannot be first (requires prior items) and that rank_order_voting is inappropriate for large option sets (>15 items).

---

## Phase 3 — Outline Track Awareness

Make Stage 1 produce multi-activity track sequences informed by the conversation context. The outline must reflect within-track workflow choices so Stage 2 can elaborate them.

**Scope**:
- `app/services/meeting_designer_prompt.py` (build_outline_prompt)
- Possibly the outline JSON schema (consider adding lightweight track hints)

**Success gate**: Given a conversation that discusses 4 breakout tracks, Stage 1 produces an outline with 2-3 activities per track (not 1). The outline reflects a pattern choice appropriate to the track's stated goal, and Stage 2 can elaborate it without needing to add or remove activities.

---

## Phase 4 — Structural Validation

Add validator checks that enforce the structural invariants currently expressed only as prompt instructions. Catch single-activity tracks, dangling phase/track references, and missing reconvergence phases at validation time rather than relying on prompt compliance.

**Scope**:
- `app/services/agenda_validator.py` (validate_agenda)
- `app/tests/test_generation_pipeline.py` (new validation test cases)

**Success gate**: `validate_agenda()` returns errors (not warnings) for: (a) any parallel-phase track with fewer than 2 activities, (b) agenda items referencing undefined phase_id or track_id values, (c) a parallel phase not followed by a plenary phase. Existing tests pass; new tests cover each rule.

---

## Phase 5 — Conversation Design Guidance

Update the MOTION Phase 5 (Design Discussion) to guide the AI in discussing within-track workflow options with the facilitator — presenting trade-offs between pattern choices rather than silently picking one.

**Scope**:
- `app/config/prompts/meeting_designer.yaml` (system_suffix: MOTION Phase 5)

**Success gate**: The chat-phase prompt instructs the AI to propose within-track workflow patterns during design discussion, explain trade-offs (e.g., "a quick brainstorm → vote takes 20 minutes but won't organize ideas; a full brainstorm → categorize → rank takes 40 minutes but gives you a structured deliverable"), and confirm the facilitator's preference before proceeding to generation.

---

## Phase 6 — Integration Verification

End-to-end validation with real multi-track generation scenarios. Confirm the full pipeline (conversation → outline → generation → validation → frontend rendering) produces structurally sound multi-track agendas with context-appropriate within-track workflows.

**Scope**:
- Manual smoke test with Colorado River scenario (or similar multi-track case)
- Report script verification (`scripts/meeting_designer_report.py`)
- Frontend rendering spot-check

**Success gate**: A multi-track generation run produces breakout tracks with 2-3 activities each, using patterns appropriate to the conversation context. The report script renders the hierarchical tree correctly. No single-activity tracks appear. The validator catches intentionally malformed test cases.

---

## Phase dependency graph

```
Phase 1 (Pattern Library)
  └─ Phase 2 (Sequencing Intelligence)
       └─ Phase 3 (Outline Track Awareness)
             └─ Phase 4 (Structural Validation)
                   └─ Phase 6 (Integration Verification)

Phase 5 (Conversation Guidance) — independent, can run in parallel with Phases 2-4
```

Phases 1-3 are the core prompt changes. Phase 4 adds enforcement. Phase 5 is the conversation-side improvement. Phase 6 validates everything end-to-end.
