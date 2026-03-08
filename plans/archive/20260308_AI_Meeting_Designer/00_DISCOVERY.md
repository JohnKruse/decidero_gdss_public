# Technical Audit: Flexible Within-Track Workflow Patterns

**Goal**: Make the AI Meeting Designer's breakout track workflows context-aware and composable rather than formulaic. The AI should reason about which collaboration pattern fits each track's goal, time constraints, and deliverable type — drawing from a library of ThinkLet-grounded sequences rather than following a rigid recipe.

**Audit date**: 2026-03-08

---

## 1. Module Dependency Map

```
POST /api/meeting-designer/generate-agenda
  │
  └─ app/routers/meeting_designer.py
       ├─ _run_generation_pipeline()           ← two-stage orchestrator
       │    ├─ Stage 1: build_outline_messages() + validate_outline()
       │    └─ Stage 2: build_generation_messages() + validate_agenda()
       │
       ├─ app/services/meeting_designer_prompt.py    ← prompt assembly
       │    ├─ build_system_prompt()                 ← chat-phase prompt (YAML templates + live catalog)
       │    ├─ build_generation_system_prompt()       ← generation-mode system prompt (hardcoded)
       │    ├─ build_outline_prompt()                 ← Stage 1 user prompt (Python-built)
       │    ├─ build_generation_prompt(outline=...)   ← Stage 2 user prompt (Python-built)
       │    ├─ parse_outline_json() / parse_agenda_json()
       │    └─ _normalise_agenda()
       │         └─ app/config/loader.py
       │              └─ get_meeting_designer_prompt_templates()
       │                   └─ app/config/prompts/meeting_designer.yaml
       │
       ├─ app/services/agenda_validator.py           ← schema + catalog validation
       │    └─ app/services/activity_catalog.py
       │         └─ app/plugins/registry.py
       │              └─ app/plugins/builtin/*.py    ← 4 plugins with ThinkLet metadata
       │
       ├─ app/services/ai_provider.py                ← multi-provider HTTP client
       └─ app/models/meeting_designer_log.py         ← audit storage
```

### Key dependency: Dual prompt paths

The YAML `generate_agenda` template and the Python `build_generation_prompt()` function contain **overlapping but independent** generation instructions. The Python function is what actually runs. The YAML template is loaded but not consumed by the generation pipeline. Both must stay in sync manually.

---

## 2. Data Flow: Two-Stage Generation Pipeline

### Stage 1 — Outline

```
Conversation history
  + build_outline_prompt()  ← flat activity list, no phase/track awareness
  → AI produces: {"meeting_summary": "...", "outline": [{tool_type, title, duration, pattern, rationale}, ...]}
  → parse_outline_json()    ← extract JSON, validate structure
  → validate_outline()      ← check tool_type exists, duration in range (warnings only)
  → Retry up to 3x with correction prompts on failure
```

**Critical constraint**: The outline is a **flat list** with no `phase_id` or `track_id` fields. If it produces 1 activity per track, Stage 2 is locked to that.

### Stage 2 — Full Agenda

```
Conversation history
  + build_generation_prompt(outline=validated_outline)
    ← "following this exact sequence, tool_types, and titles"
  → AI produces: {meeting_summary, session_name, complexity, phases[], agenda[], ...}
  → parse_agenda_json()     ← extract JSON, strip comments, json_repair fallback
  → _normalise_agenda()     ← fill defaults for complexity/phases/track fields
  → validate_agenda()       ← check tool_type, title, instructions, config keys
  → Retry up to 2x with correction prompts on failure
```

**Critical constraint**: Stage 2 prompt says "following this **exact** sequence, tool_types, and titles" from the outline. The AI cannot add activities that weren't in the outline.

### Downstream consumption

```
Generated agenda JSON
  ├─ Frontend (meeting_designer.html)
  │    ├─ Renders phases/tracks in CSS grid layout
  │    ├─ splitAgendasByTrack() → creates separate meetings per track
  │    └─ Phase/track info used for display only; discarded on meeting creation
  │
  ├─ Meeting creation (meetings.py)
  │    ├─ Maps agenda items → AgendaActivity rows (order_index = sequential)
  │    └─ phase_id and track_id are NOT stored in DB columns
  │
  ├─ Report script (scripts/meeting_designer_report.py)
  │    └─ Groups activities by phase_id/track_id for hierarchical rendering
  │
  └─ Audit log (meeting_designer_logs table)
       └─ Stores full parsed_output JSON blob
```

---

## 3. Current Activity Inventory

| Plugin | tool_type | Patterns | ThinkLets | Duration | Group Size |
|--------|-----------|----------|-----------|----------|------------|
| Brainstorming | `brainstorming` | Generate, Clarify | FreeBrainstorm, LeafHopper | 5-30 min | 2-100 |
| Categorization | `categorization` | Reduce, Organize | BucketWalk, FastFocus | 5-25 min | 2-50 |
| Dot Voting | `voting` | Evaluate, Build Consensus | StrawPoll, FastFocus | 3-15 min | 2-100 |
| Rank Order | `rank_order_voting` | Evaluate | Borda Vote | 5-20 min | 2-50 |

### Composable sequences from these 4 activities

**2-activity (quick convergence)**:
- brainstorming → voting (Simple Consensus)
- brainstorming → rank_order_voting

**3-activity (organized convergence)**:
- brainstorming → categorization → voting (Classic)
- brainstorming → categorization → rank_order_voting (Deep Evaluation)
- brainstorming (with sub-comments) → categorization → voting (Clarify-first)

**4-activity (deep funnel)**:
- brainstorming → categorization → voting → rank_order_voting
- brainstorming → voting (straw poll) → brainstorming (refine) → rank_order_voting (Dual-Pass)
- brainstorming (topics) → voting (select) → brainstorming (within topic) → voting (select deliverables) (Nested Decomposition)

**Already defined in system_suffix**: Standard Sequences, Extended Sequences — but framed as full-session patterns only, never explicitly offered for within-track use.

### Unused metadata

These manifest fields are populated but **not injected into any prompt**:
- `when_not_to_use` — would help AI avoid inappropriate activity choices
- `input_requirements` — would help AI reason about sequencing dependencies
- `output_characteristics` — would help AI understand what feeds into what

---

## 4. Prompt Surface Area

### Chat phase (`system_prefix` + activity blocks + `system_suffix`)

| Section | Content | File location |
|---------|---------|---------------|
| System prefix | Identity, rules, 6-pattern model | YAML lines 1-38 |
| Activity blocks | Per-plugin: patterns, ThinkLets, when_to_use, bias, duration, config | Python-built from catalog |
| Standard Sequences | 6 named patterns for simple sessions | YAML lines 42-48 |
| Extended Sequences | 4 named patterns for multi-phase sessions | YAML lines 50-55 |
| Multi-Track Patterns | Decomposition + Iterative Refinement | YAML lines 57-69 |
| Breakout Track Guidelines | Track sizing, naming, structure | YAML lines 71-78 |
| Reconvergence Rules | Hard requirements for multi-track | YAML lines 80-86 |
| MOTION flow | 6-phase conversation structure | YAML lines 88-147 |

### Generation phase (`build_generation_prompt()`)

| Section | Content | Source |
|---------|---------|--------|
| Outline lock-in | "follow this exact sequence" | Python lines 225-240 |
| Complexity rules | simple/multi_phase/multi_track | Python lines 282-286 |
| Config overrides ref | Per-tool config keys | Python-built from catalog |
| Activity calibration | Duration, votes, anonymity, buckets | Python lines 289-293 |
| Within-track rules | **Currently formulaic** | Python lines 294-303 |
| Reconvergence rules | Phase sequencing requirements | Python lines 304-308 |

### Outline phase (`build_outline_prompt()`)

| Section | Content | Source |
|---------|---------|--------|
| Schema template | Flat activity list | Python lines 345-359 |
| Duration guidance | Per-tool ranges | Python-built from catalog |
| Multi-track rules | **Currently formulaic** | Python lines 361-365 |

---

## 5. Validation Gap Analysis

### What IS validated (agenda_validator.py)

- `tool_type` exists and matches registered plugin (error)
- `title` is non-empty string (error)
- `instructions` is non-empty string (error, full agenda only)
- `duration_minutes` is positive number, within typical range (warning)
- `collaboration_pattern` matches activity's allowed patterns (warning)
- `config_overrides` keys exist in activity's default_config (warning)

### What is NOT validated

| Gap | Risk | Impact |
|-----|------|--------|
| Activities per track | AI generates 1-activity tracks | Breakouts produce divergent chaos with no deliverable |
| Phase/track referential integrity | Agenda items reference non-existent phase_id/track_id | Frontend can't render tracks; activities become orphans |
| Reconvergence phase presence | Parallel phases not followed by plenary | Meeting ends on breakouts with no integration |
| Collaboration pattern progression | Evaluate activity before any Generate | Illogical sequence; participants vote on nothing |
| Outline-to-agenda consistency | Stage 2 adds/removes activities vs. outline | Activity count mismatch; phases/tracks misaligned |
| Config override value types | `max_votes: "invalid"` passes | Runtime error when activity starts |

---

## 6. Test Coverage Map

**File**: `app/tests/test_generation_pipeline.py` — 92 passing tests

### Covered

- GenerationPipelineError exception fields and defaults
- Correction prompt construction (parse failure, validation failure)
- Retry loop orchestration (outline 3x, agenda 2x)
- Valid/invalid outline and agenda JSON generation helpers
- Max token scaling formula
- Config loader templates (2 tests in test_config_loader.py)

### Not covered

- Phase/track structure validation
- Within-track activity count or sequence rules
- Reconvergence pattern enforcement
- Outline lock-in verification (Stage 2 respects Stage 1)
- Prompt content assertions (no tests verify specific prompt text)
- Multi-track agenda end-to-end with real validation

---

## 7. Breaking Points for Within-Track Pattern Changes

### P0 — Will break if not addressed

| # | Risk | Location | Why it matters |
|---|------|----------|----------------|
| 1 | **Outline is flat — no track awareness** | `build_outline_prompt()` | If outline produces 1 activity/track, Stage 2 is locked to it. Must produce multi-activity tracks. |
| 2 | **Stage 2 locked to "exact sequence"** | `build_generation_prompt()` line 237 | AI cannot add within-track activities not in outline. Outline must be track-aware. |
| 3 | **No validation of activities per track** | `agenda_validator.py` | Single-activity tracks pass validation silently. |

### P1 — Should address for reliability

| # | Risk | Location | Why it matters |
|---|------|----------|----------------|
| 4 | Phase/track integrity not validated | `agenda_validator.py` | Dangling phase_id/track_id values break frontend rendering |
| 5 | Reconvergence not validated | `agenda_validator.py` | Parallel phases can end the agenda without plenary |
| 6 | `when_not_to_use` and `input_requirements` not in prompts | `_format_activity_block()` | AI lacks guidance on sequencing constraints |

### P2 — Nice to have

| # | Risk | Location | Why it matters |
|---|------|----------|----------------|
| 7 | Dual prompt paths (YAML vs Python) | `meeting_designer_prompt.py` + YAML | Manual sync burden; YAML generate_agenda is unused |
| 8 | Phase/track info lost on meeting creation | Frontend `splitAgendasByTrack()` | Track metadata not persisted in AgendaActivity table |

---

## 8. Architectural Observations

### The sequences already exist — they just aren't offered for within-track use

The `system_suffix` already defines Standard Sequences (Simple Consensus, Classic, Deep Evaluation, etc.) and Extended Sequences (Full Funnel, Dual-Pass, etc.). These are framed as "full session" patterns. The AI never considers them as within-track workflow options because:

1. They're in a separate section from the Breakout Track Guidelines
2. The generation prompt's within-track rules prescribe a fixed recipe instead of referencing the sequence library
3. The conversation flow (Phase 5 — Design Discussion) doesn't guide the AI to discuss track workflow options with the facilitator

### The activity metadata supports reasoning but isn't surfaced

Each plugin's `input_requirements` and `output_characteristics` describe what it needs and produces — exactly the information needed to reason about valid sequencing. But `_format_activity_block()` doesn't include these fields. Adding them would let the AI understand the data flow between activities (e.g., "categorization requires items from a prior activity" → can't be first in a track).

### The outline stage is the bottleneck

Because the outline is flat and Stage 2 is locked to it, the outline stage determines track structure. If the outline prompt doesn't give the AI enough guidance about within-track patterns, the entire downstream pipeline inherits that structural deficiency. The fix must start at the outline stage.
