# 00 — DISCOVERY: Orchestration Engine Terrain Audit

**Scope:** Map module dependencies, data flows, and coupling assumptions across the codebase that bear on the orchestration-engine extension described in [plans/02_ORCHESTRATION_ENGINE.md](02_ORCHESTRATION_ENGINE.md). Identify breaking points and load-bearing assumptions. This is a **terrain map, not a plan** — every claim is anchored to a file:line reference and no remediation is prescribed.

Branch at time of audit: `HICSS-orchestrator-dev`. HEAD: `62bba57`.

The prior role/permission discovery has been moved to [plans/archive/00_DISCOVERY_role_permissions.md](archive/00_DISCOVERY_role_permissions.md).

---

## 1. Glossary — concepts the engine will compose over

| Concept | Where it lives | Cardinality | Owner of truth |
|---|---|---|---|
| **Meeting** | `Meeting` model ([app/models/meeting.py:48](../app/models/meeting.py)) | One row per meeting | Meeting creation / facilitator |
| **AgendaActivity** | `AgendaActivity` model ([app/models/meeting.py:121-156](../app/models/meeting.py)) | N per meeting, totally ordered by `order_index` | Meeting setup + mid-meeting POST |
| **ActivityPlugin** | `ActivityPlugin` ABC ([app/plugins/base.py:38-81](../app/plugins/base.py)) | One per `tool_type` (singleton in registry) | `app/plugins/builtin/` + dropin dir |
| **ActivityPluginManifest** | dataclass ([app/plugins/base.py:17-36](../app/plugins/base.py)) | One per plugin instance | Plugin declaration |
| **ActivityBundle** | `ActivityBundle` model ([app/models/activity_bundle.py:6-17](../app/models/activity_bundle.py)) | N per activity, keyed by `kind ∈ {input, draft, output}` | `ActivityBundleManager` via `ActivityContext` |
| **MeetingState** | `MeetingState` dataclass ([app/services/meeting_state.py:29-40](../app/services/meeting_state.py)) | One per active meeting (in-memory, transient) | `meeting_state_manager`, mutated by WebSocket `state_update` |
| **TransferSource** | `TransferSourceResult` ([app/services/transfer_source.py](../app/services/transfer_source.py)) | Computed per donor activity on demand | Plugin override or default extraction |
| **ReliabilityPolicy** | manifest field ([app/plugins/base.py:23](../app/plugins/base.py)) normalized by [app/services/activity_catalog.py:62-80](../app/services/activity_catalog.py) | Per `(plugin, action)` pair | Plugin declaration; client consumes |

The orchestration engine adds **AgendaStrategy**, **OrchestrationDocument**, **BundleTransform**, and **ConvergencePredicate** as new concepts above this layer. The audit below identifies where those new concepts will collide with assumptions baked into the existing concepts.

---

## 2. Module dependency map (engine-relevant terrain)

```
┌────────────────────────────────────────────────────────────────┐
│  Routers (HTTP surface)                                         │
│  ─ app/routers/meetings.py     (agenda CRUD + reorder)          │
│  ─ app/routers/realtime.py     (WebSocket; broadcasts agenda)   │
│  ─ app/routers/transfer.py     (donor→recipient bundle moves)   │
│  ─ app/routers/{brainstorming, voting, rank_order_voting,       │
│       categorization}.py       (per-plugin action endpoints)    │
└─────────────────────────┬──────────────────────────────────────┘
                          │
            ┌─────────────┼────────────────────────────┐
            │             │                            │
┌───────────▼────┐  ┌─────▼──────────────┐  ┌──────────▼─────────┐
│ meeting_state  │  │ activity_pipeline  │  │ transfer_source    │
│ .py            │  │ .py                │  │ .py                │
│ in-mem state   │  │ ensure_input_      │  │ build_transfer_    │
│ singleton      │  │ bundle             │  │ items              │
│ currentActivity│  │ _find_previous_    │  │ default + plugin   │
│ activeActivities│ │ activity (order_   │  │ override path      │
│ (Dict by id)   │  │ index linear scan) │  │                    │
└───────┬────────┘  └────────┬───────────┘  └──────────┬─────────┘
        │                    │                         │
        └────────┬───────────┴──────────────┬──────────┘
                 │                          │
        ┌────────▼─────────┐       ┌────────▼──────────┐
        │ data/            │       │ plugins/          │
        │ meeting_manager  │       │ registry.py       │
        │ .py              │       │ loader.py         │
        │ add/update/      │       │ context.py        │
        │ resequence agenda│       │ base.py (ABC)     │
        └────────┬─────────┘       └────────┬──────────┘
                 │                          │
        ┌────────▼─────────┐       ┌────────▼──────────┐
        │ models/          │       │ plugins/builtin/  │
        │ meeting.py       │       │ {brainstorming,   │
        │ activity_bundle  │       │  voting,          │
        │ .py              │       │  categorization,  │
        │                  │       │  rank_order_      │
        │                  │       │  voting}_plugin.py│
        └──────────────────┘       └───────────────────┘
                                            │
                          ┌─────────────────┴─────────────────┐
                          │ Adjacent services consulted by    │
                          │ plugin lifecycle / transfer:      │
                          │ ─ activity_catalog.py             │
                          │ ─ ai_provider.py                  │
                          │ ─ agenda_validator.py             │
                          │ ─ transfer_transforms.py          │
                          │ ─ categorization_manager.py       │
                          │ ─ voting_manager.py               │
                          │ ─ rank_order_voting_manager.py    │
                          └───────────────────────────────────┘
```

The engine will need to interpose **between routers and `activity_pipeline` / `meeting_manager`**, and to add new services (`agenda_strategy.py`, `bundle_transforms.py`, `convergence_predicates.py`) without altering the `plugins/` subtree.

---

## 3. Agenda model and `order_index` total ordering

### 3.1 The relationship is sorted at the ORM level

[app/models/meeting.py:72-77](../app/models/meeting.py):

```python
agenda_activities = relationship(
    "AgendaActivity",
    order_by="AgendaActivity.order_index",
    cascade="all, delete-orphan",
    back_populates="meeting",
)
```

[app/models/meeting.py:79-81](../app/models/meeting.py) exposes `Meeting.agenda` as `list(self.agenda_activities or [])` — a plain list assumed by all callers to be in linear traversal order.

### 3.2 Uniqueness constraints

[app/models/meeting.py:123-126](../app/models/meeting.py) declares:

- `UniqueConstraint("meeting_id", "order_index", name="uq_agenda_activity_order")`
- `UniqueConstraint("meeting_id", "activity_id", name="uq_agenda_activity_id")`

Two consequences: (a) every activity row has a position in a *total* order, no concept of "tied" or "branch" position exists at the schema layer; (b) inserting a new row mid-sequence requires either a free slot or a resequence to avoid the unique-constraint collision.

### 3.3 Sites that walk `agenda_activities` or assume `order_index`

| Site | What it does | Linearity assumption |
|---|---|---|
| [app/routers/meetings.py:970](../app/routers/meetings.py) | `sorted(meeting.agenda_activities, key=lambda i: i.order_index)` for GET response | Strong — returns total-ordered list to client |
| [app/routers/meetings.py:298](../app/routers/meetings.py) | Iterates `agenda_activities` to build export bundle | Strong — sequential iteration |
| [app/routers/realtime.py:52-54](../app/routers/realtime.py) | Sorts by `order_index` for WebSocket broadcast | Strong — clients see a single ordered list |
| [app/routers/transfer.py:56-64](../app/routers/transfer.py) | `_resolve_activity()` linear scan of `agenda_activities` | Implicit — assumes resolution by membership only |
| [app/services/activity_pipeline.py:59-68](../app/services/activity_pipeline.py) | `_find_previous_activity()` walks list, returns the row whose `order_index` is immediately less | **Hard linear-order dependency** |
| [app/data/meeting_manager.py:349-353](../app/data/meeting_manager.py) | `list_agenda()` returns `sorted(...)` | Strong — public list API |
| [app/data/meeting_manager.py:265-291](../app/data/meeting_manager.py) | `_resequence_agenda()` two-pass renumbering (placeholder indices `max+1000+idx`, then `1..N`) | Strong — assumes a global sequence the meeting can be reduced to |

**Breaking point.** `_find_previous_activity()` is the single most load-bearing linear assumption. An `iterate` step kind that runs the same activity twice, or a `conditional` step that selects between two predecessors, has no defensible "previous by `order_index`" answer.

### 3.4 Where AgendaActivity rows are created

- **Meeting creation:** [app/data/meeting_manager.py:910-1010](../app/data/meeting_manager.py) `create_meeting()` → `_apply_agenda_items()` at [app/data/meeting_manager.py:293-340](../app/data/meeting_manager.py), which **clears `meeting.agenda_activities` then re-creates** (line 298).
- **Mid-meeting append:** [app/data/meeting_manager.py:528-565](../app/data/meeting_manager.py) `add_agenda_activity()` appends then calls `_resequence_agenda()`. Exposed via `POST /api/meetings/{meeting_id}/agenda` at [app/routers/meetings.py:976-1008](../app/routers/meetings.py).
- **Update:** `PUT /api/meetings/{meeting_id}/agenda/{activity_id}` at [app/routers/meetings.py:1011-1045](../app/routers/meetings.py). Note: `tool_type` is **forbidden to change** ([app/data/meeting_manager.py:588-592](../app/data/meeting_manager.py)).
- **Reorder:** `PUT /api/meetings/{meeting_id}/agenda-reorder` at [app/routers/meetings.py:1080-1113](../app/routers/meetings.py).

The schema is mechanically friendly to mid-meeting insertion. The two-pass resequence in `_resequence_agenda()` is the mechanism that lets inserts coexist with the `order_index` unique constraint.

### 3.5 Activity ID minting

Activity IDs are minted by `_next_activity_identifier()` called from [app/data/meeting_manager.py:122-126](../app/data/meeting_manager.py), using a per-meeting per-`tool_type` sequence cache. The prefix derivation lives at `derive_activity_prefix` in [app/services/activity_catalog.py:150](../app/services/activity_catalog.py). Observed pattern in test fixtures: `M-SEED-BRAIN-0001`, `M-SEED-VOTE-0002` ([app/tests/test_activity_plugins.py:32,41](../app/tests/test_activity_plugins.py)).

### 3.6 No agenda-complete predicate

There is no `is_agenda_complete()`, no terminal-step marker, no derived "done" state. `Meeting.status` ([app/models/meeting.py:44](../app/models/meeting.py)) is facilitator-set and orthogonal to agenda progress. The engine must supply its own completion semantics (`ConvergencePredicate`).

---

## 4. Meeting state machine — what "current activity" means today

### 4.1 In-memory, singleton, client-driven

[app/services/meeting_state.py:29-40](../app/services/meeting_state.py):

```python
@dataclass
class MeetingState:
    meeting_id: str
    current_activity: Optional[str] = None
    current_tool: Optional[str] = None
    agenda_item_id: Optional[str] = None
    status: Optional[str] = None
    ...
```

`current_activity` is a single activity_id string. The state lives only in `meeting_state_manager` (the in-memory manager at [app/services/meeting_state.py:64-236](../app/services/meeting_state.py)); it is not persisted. State transitions happen via `apply_patch()` ([app/services/meeting_state.py:140-228](../app/services/meeting_state.py)) invoked from `state_update` WebSocket messages at [app/routers/realtime.py:165-172](../app/routers/realtime.py).

### 4.2 There is no server-side "advance" function

The server never autonomously selects a next activity. The facilitator's client decides, sends a patch, the server stores it, the server broadcasts. The `AgendaStrategy` interface proposed in plan §2.1 has **no existing analogue** to refactor — it is greenfield.

### 4.3 `activeActivities` is already a dict, but singular by convention

`_resolve_active_activity_state()` at [app/routers/meetings.py:620-657](../app/routers/meetings.py) reads `snapshot.get("activeActivities")` (a dict keyed by activity_id) and `snapshot.get("currentActivity")` (a scalar). The schema permits multiple active entries, but every caller assumes exactly one is "current."

**Breaking point.** Parallel branches, paused-pending-decision states, and facilitator-decision/ai-decision pauses all need a richer notion of "what is the engine doing right now" than a single string.

---

## 5. Activity plugin contract — what the engine must NOT change

### 5.1 The ABC

[app/plugins/base.py:38-81](../app/plugins/base.py):

```python
class ActivityPlugin(ABC):
    manifest: ActivityPluginManifest

    @abstractmethod
    def open_activity(self, context, input_bundle=None) -> None: ...

    @abstractmethod
    def close_activity(self, context) -> Optional[Dict[str, Any]]: ...

    def validate_config(self, config) -> Dict[str, Any]: ...
    def snapshot_activity(self, context) -> Optional[Dict[str, Any]]: ...
    def get_transfer_source(self, context, include_comments=True) \
        -> Optional[TransferSourceResult]: ...
    def get_transfer_count(self, context) -> Optional[int]: ...
```

The signatures are stable and the contract is small. DP9 ("method-specific concerns do not belong in activity plugins") requires that the engine compose existing plugins unmodified — these signatures are the surface that constraint binds on.

### 5.2 Manifest fields

[app/plugins/base.py:17-36](../app/plugins/base.py) — `ActivityPluginManifest` is a frozen dataclass with the following fields:

- Identity: `tool_type`, `label`, `description`
- Behavior: `default_config`, `reliability_policy`, `autosave_seconds`
- ThinkLet metadata: `collaboration_patterns`, `use_cases`, `when_to_use`, `when_not_to_use`, `group_size_range`, `typical_duration_minutes`, `bias_mitigation`, `thinklets`, `input_requirements`, `output_characteristics`

### 5.3 Registry and discovery

- [app/plugins/registry.py:11-48](../app/plugins/registry.py) — `ActivityRegistry` keyed by lowercase `tool_type`; `register()`, `get_plugin()`, `load()`.
- [app/plugins/loader.py:39-65](../app/plugins/loader.py) — `load_builtin_plugins()` (hardcoded import list at lines 55-60) + `load_dropin_plugins()` scanning `$DECIDERO_PLUGIN_DIR` or `<project>/plugins`.
- [app/plugins/context.py:14-58](../app/plugins/context.py) — `ActivityContext` carries `db`, `meeting`, `activity`, optional `user`/`logger`, plus bundle helpers `load_input_bundle`, `load_draft_bundle`, `save_draft_bundle`, `finalize_output_bundle`.

### 5.4 `validate_config()` is not invoked by the framework

The base implementation at [app/plugins/base.py:49-51](../app/plugins/base.py) is a passthrough. Grep finds no call site outside plugin internals. This is the gap that DP6 in the orchestration plan calls out: the engine will need to either invoke it explicitly during step instantiation, or document the convention.

### 5.5 `tool_type` is immutable on update

[app/data/meeting_manager.py:588-592](../app/data/meeting_manager.py) rejects `tool_type` mutation in `update_agenda_activity()`. The engine cannot morph a step's plugin choice in-flight; it must create a new activity row.

---

## 6. Bundle pipeline — input / draft / output flow

### 6.1 The bundle row

[app/models/activity_bundle.py:6-17](../app/models/activity_bundle.py):

```python
class ActivityBundle(Base):
    __tablename__ = "activity_bundles"
    bundle_id   = Column(String(36), unique=True, ...)
    meeting_id  = Column(String(20), ..., index=True)
    activity_id = Column(String(32), ..., index=True)
    kind        = Column(String(16), ..., index=True)  # "input" | "draft" | "output"
    items       = Column(JSON, default=list)
    bundle_metadata = Column(JSON, default=dict)
    created_at, updated_at
```

Notes:

- `activity_id` is a **string reference, not a foreign key**. Bundles outlive activity replacements.
- `kind` values (`"input"`, `"draft"`, `"output"`) are hardcoded strings; no enum.
- **No iteration / round / phase field.** Two iterations of the same activity row would collide on `(activity_id, kind)`.

**Breaking point.** A naive `iterate` implementation that re-opens the same activity row across rounds will overwrite or shadow prior bundles. Either each iteration needs its own `AgendaActivity` row (with a derived id), or `ActivityBundle` gains an iteration discriminator.

### 6.2 `ensure_input_bundle()` and the "previous activity" assumption

[app/services/activity_pipeline.py:12-69](../app/services/activity_pipeline.py): `ensure_input_bundle()` first looks for an existing `input` bundle newer than the activity; if absent, it calls `_find_previous_activity()` and pulls that activity's `output` bundle, calling `create_input_bundle_from_output()` to materialize the chain.

`_find_previous_activity()` at lines 59-68 is the linear-scan dependency already noted in §3.3.

### 6.3 Provenance preservation is plugin-implemented

Item-level fields (`id`, `content`, `submitted_name`, `parent_id`, `created_at`, `updated_at`, `user_id`, `user_color`, `user_avatar_*`, `metadata`, `source`) are preserved across transfer **by individual plugin code**, not by a framework guarantee:

- [app/plugins/builtin/brainstorming_plugin.py:140-150](../app/plugins/builtin/brainstorming_plugin.py) — `serialize_transfer_idea()`
- [app/plugins/builtin/voting_plugin.py:108-129](../app/plugins/builtin/voting_plugin.py) — `_sanitize_option_entry()`
- [app/services/transfer_source.py:118-149](../app/services/transfer_source.py) — default extraction; [199-221](../app/services/transfer_source.py) — `_normalize_bundle_item()` source-dict reconstruction
- [app/services/transfer_transforms.py](../app/services/transfer_transforms.py) — applies split/append transforms during transfer commit

This is what `test_transfer_metadata.py` ([app/tests/test_transfer_metadata.py](../app/tests/test_transfer_metadata.py)) currently pins.

**Breaking point.** New step kinds (`facilitator-decision`, `ai-decision`) will emit bundle items that don't fit the existing extraction paths. Their items will need their own provenance-preserving normalization or the metadata will silently drop.

---

## 7. Reliability policy infrastructure (DP4 surface area)

### 7.1 Declaration

Plugin manifest field `reliability_policy: Dict[str, Any]` at [app/plugins/base.py:23](../app/plugins/base.py). Example from BrainstormingPlugin at [app/plugins/builtin/brainstorming_plugin.py:29-37](../app/plugins/builtin/brainstorming_plugin.py):

```python
reliability_policy={
    "submit_idea": {
        "retryable_statuses": [429, 502, 503, 504],
        "max_retries": 3,
        "base_delay_ms": 400,
        "max_delay_ms": 2500,
        "jitter_ratio": 0.25,
        "idempotency_header": "X-Idempotency-Key",
    }
},
```

### 7.2 Server-side normalization

[app/services/activity_catalog.py:62-80](../app/services/activity_catalog.py) — `normalise_reliability_policy()`:

- Validates retry counts, delay bounds, jitter ratio (0.0–1.0).
- Falls back to `_DEFAULT_WRITE_POLICY` at [app/services/activity_catalog.py:8-15](../app/services/activity_catalog.py).
- Returns a dict the client consumes via the activity catalog API.

### 7.3 Client-side application

`runReliableWriteAction` at [app/static/js/reliable_actions.js](../app/static/js/reliable_actions.js). Used by plugin frontends (brainstorming.js, voting.js, etc.). Implements exponential backoff with jitter, sends idempotency header.

### 7.4 No server-side retry analogue exists

There is **no server-side equivalent** of `runReliableWriteAction`. The orchestration plan's `ai-decision` step (which proposes reusing this pattern for malformed LLM responses) will find normalization + manifest declarations, but no server-side execution path — that infrastructure must be authored.

---

## 8. AI provider surface

### 8.1 Providers and clients

[app/services/ai_provider.py](../app/services/ai_provider.py) supports Anthropic (Messages), OpenAI Chat Completions, Google Gemini (OpenAI-compatible), OpenRouter, and custom OpenAI-compatible endpoints. Core entry points:

- `_anthropic_stream()` (lines 78-123) — async generator
- `_anthropic_complete()` (lines 126-156) — buffered completion
- Equivalent OpenAI-family functions
- `AIProviderError` (lines 38-39)

### 8.2 Existing "call LLM, parse, validate" pattern

[app/services/meeting_designer_prompt.py](../app/services/meeting_designer_prompt.py) (763 lines) is the existing customer for `ai_provider.py`. It generates and validates meeting agendas. Its output funnels into [app/services/agenda_validator.py:584-703](../app/services/agenda_validator.py), which exposes `validate_agenda()` and `validate_outline()` returning structured `AgendaValidationResult` ([app/services/agenda_validator.py:41-47](../app/services/agenda_validator.py)) with errors and warnings.

`ai-decision` step semantics overlap meaningfully with this pattern — the validator framework is structurally reusable, though it is currently agenda-specific.

---

## 9. Routers and transport — coupling to a linear agenda

### 9.1 Agenda CRUD ([app/routers/meetings.py](../app/routers/meetings.py))

| Route | Lines | Coupling note |
|---|---|---|
| `GET  /api/meetings/{id}/agenda` | 950-973 | Returns `order_index`-sorted list, augmented with `transfer_count`, `has_data`, `has_votes`, `transfer_target_eligible`, `locked_config_keys` |
| `POST /api/meetings/{id}/agenda` | 976-1008 | Appends at end |
| `PUT  /api/meetings/{id}/agenda/{aid}` | 1011-1045 | Updates config; rejects `tool_type` change |
| `DELETE /api/meetings/{id}/agenda/{aid}` | 1048-1077 | Removes row; `order_index` gaps persist unless explicit reorder |
| `PUT  /api/meetings/{id}/agenda-reorder` | 1080-1113 | Accepts a totally-ordered list of `activity_ids` |

### 9.2 Realtime ([app/routers/realtime.py](../app/routers/realtime.py))

- Lines 52-55 — formatted agenda sent on connect; sorted by `order_index`.
- Lines 165-172 — `state_update` handler patches `MeetingState`; this is the only mutation path for `currentActivity`.
- Lines 37-243 — meeting socket envelope and dispatch.

**Breaking point.** Any backend-initiated agenda mutation by the engine must produce an `agenda_update` broadcast or clients will diverge from server state.

### 9.3 Transfer ([app/routers/transfer.py](../app/routers/transfer.py))

`_resolve_activity()` at lines 56-64 linearly scans `meeting.agenda_activities` to resolve a donor/recipient — relies on membership only, not on adjacency, so it survives non-linear topologies as long as both endpoints exist in the relationship.

### 9.4 Per-plugin action routers

Each builtin plugin has a router file ([brainstorming.py](../app/routers/brainstorming.py), [voting.py](../app/routers/voting.py), [rank_order_voting.py](../app/routers/rank_order_voting.py), [categorization.py](../app/routers/categorization.py)) that exposes the plugin's runtime endpoints. These touch plugin runtime state directly (Idea, VotingVote, RankOrderBallot, Categorization* tables) and do not consult `MeetingState.currentActivity`. They will be unaffected by engine introduction.

---

## 10. Schemas (Pydantic) — API contract surface

[app/schemas/meeting.py](../app/schemas/meeting.py):

- `MeetingStatus` enum (lines 13-18): SCHEDULED / IN_PROGRESS / PAUSED / COMPLETED / ARCHIVED
- `AgendaActivityCreate` (lines 141-142): `tool_type`, `title`, `instructions`, `config`, `order_index`
- `AgendaActivityUpdate` (lines 145-169): partial update; `order_index` mutable; `tool_type` mutation blocked at the manager layer (see §5.5)
- `AgendaActivityResponse` (lines 172-190): server-augmented (`transfer_count`, `transfer_source`, `transfer_reason`, `has_data`, `has_votes`, `has_submitted_ballots`, `transfer_target_eligible`, `locked_config_keys`); `model_config: from_attributes=True`
- `AgendaReorderPayload` (lines 193-204): `activity_ids: List[str]`
- `ActivityParticipantUpdatePayload` (lines 117-144): roster update with `mode='all' | 'custom'` (empty custom → `'all'`)

These schemas are the wire contract. The engine will need a parallel orchestration-document schema (`docs/schemas/orchestration.schema.json` per plan §3.1) that does not collide with these.

---

## 11. Agenda validator — what it does and doesn't enforce

[app/services/agenda_validator.py](../app/services/agenda_validator.py):

- `validate_agenda()` (lines 584-611) — full validation: tool types, titles, instructions, duration, phases, tracks, reconvergence
- `validate_outline()` (lines 614-703) — lighter Stage-1 outline validation
- `AgendaFieldError` (lines 31-38) and `AgendaValidationResult` (lines 41-47)
- Structural invariants at lines 310-329: dangling `phase_id` references; dangling `track_id` references; ≥ 2 activities per parallel-phase track; parallel phases must end in plenary reconvergence

The validator already understands a notion of `phases` and `tracks` beyond a flat list. This is more structure than the current linear-agenda runtime uses — it exists to validate AI-generated agendas. The engine's orchestration documents are not currently in its grammar; a separate validator (or extension) will be needed.

---

## 12. Test footprint — what is pinned, what is not

### 12.1 Existing relevant tests

| Test file | What it pins |
|---|---|
| [app/tests/test_activity_plugins.py](../app/tests/test_activity_plugins.py) | Plugin lifecycle: `open_activity` → close; bundle roundtrip (lines 91-106); `activity_pipeline` input-from-prior-output (lines 109-123); stale input replacement (~line 288+); voting seeds from input (126-144); voting preserves provenance in output (147-196); voting clears stale votes/bundles (199-264) |
| [app/tests/test_transfer_metadata.py](../app/tests/test_transfer_metadata.py) | Provenance fields survive transfer (DP2) |
| [app/tests/test_transfer_transforms.py](../app/tests/test_transfer_transforms.py) | Split/append behaviors of transfer transforms |
| [app/tests/test_categorization_contract.py](../app/tests/test_categorization_contract.py) | Categorization plugin contract |
| [app/tests/test_meeting_state.py](../app/tests/test_meeting_state.py) | `MeetingState` patch application |
| [app/tests/test_meeting_manager.py](../app/tests/test_meeting_manager.py) | Agenda CRUD + resequence + reorder |
| [app/tests/test_api_meetings.py](../app/tests/test_api_meetings.py) | Agenda HTTP surface and active-activity resolution |
| [app/tests/test_agenda_validator.py](../app/tests/test_agenda_validator.py) | Agenda validator structural invariants |

### 12.2 Confirmed coverage gaps

- **DP3 (idempotency of `open_activity`):** no test calls `open_activity()` twice on the same activity row with the same input bundle and asserts no state duplication. Plan §1.3 names this gap explicitly.
- **Bundle iteration semantics:** no test exercises a second `output` bundle for the same `activity_id`. The implicit assumption is that each activity_id has at most one output.
- **Non-linear "previous activity":** every `_find_previous_activity()` test exercises the linear case.

---

## 13. ThinkLet metadata currently declared (faithfulness audit input)

A factual extraction. Faithfulness against the canonical Briggs/de Vreede/Kolfschoten descriptions is **not** evaluated here — that is plan Task 1.5.

### 13.1 BrainstormingPlugin ([app/plugins/builtin/brainstorming_plugin.py:16-82](../app/plugins/builtin/brainstorming_plugin.py))

- `tool_type`: `"brainstorming"` · `label`: `"Brainstorming"`
- `collaboration_patterns`: `["Generate", "Clarify"]`
- `thinklets`: `["FreeBrainstorm (anonymous, parallel — maximises idea volume)", "LeafHopper (sub-comments for inline Clarify without interruption)"]`
- `group_size_range`: `{min: 2, max: 100}` · `typical_duration_minutes`: `{min: 5, max: 30}`
- `bias_mitigation`: anonymous-mode anti-anchoring; simultaneous electronic submission; in-context sub-comments
- 5 `use_cases`; full `when_to_use` / `when_not_to_use` prose declared

### 13.2 VotingPlugin ([app/plugins/builtin/voting_plugin.py:14-74](../app/plugins/builtin/voting_plugin.py))

- `tool_type`: `"voting"` · `label`: `"Dot Voting"`
- `collaboration_patterns`: `["Evaluate", "Build Consensus"]`
- `thinklets`: `["StrawPoll (temperature check — quick single-round vote to gauge sentiment)", "FastFocus (multi-vote prioritisation — distribute vote budget across options)"]`
- `group_size_range`: `{min: 2, max: 100}` · `typical_duration_minutes`: `{min: 3, max: 15}`
- `bias_mitigation`: randomized option order; hidden-results mode; multi-vote allocation
- 5 `use_cases`; full `when_to_use` / `when_not_to_use` prose declared

### 13.3 CategorizationPlugin ([app/plugins/builtin/categorization_plugin.py:13-70](../app/plugins/builtin/categorization_plugin.py))

- `tool_type`: `"categorization"` · `label`: `"Bucketing - Facilitator"`
- `collaboration_patterns`: `["Reduce", "Organize"]`
- `thinklets`: `["BucketWalk (thematic grouping — organise items into named topic buckets)", "FastFocus (keep/discard Reduce — narrow a long list to a workable shortlist)"]`
- `group_size_range`: `{min: 2, max: 50}` · `typical_duration_minutes`: `{min: 5, max: 25}`
- `bias_mitigation`: facilitator-led criterion consistency; pre-defined buckets prevent suppression; categorization before voting prevents premature convergence
- 5 `use_cases`; full `when_to_use` / `when_not_to_use` prose declared

### 13.4 RankOrderVotingPlugin ([app/plugins/builtin/rank_order_voting_plugin.py:15-91](../app/plugins/builtin/rank_order_voting_plugin.py))

- `tool_type`: `"rank_order_voting"`
- `collaboration_patterns`: `["Evaluate"]`
- `thinklets`: `["Borda Vote (rigorous rank aggregation — Borda-count scoring across all rankings)"]`
- `group_size_range`: `{min: 2, max: 50}` · `typical_duration_minutes`: `{min: 5, max: 20}`
- `bias_mitigation`: Borda balanced weighting; randomized presentation; rank-variance disagreement signal; complete-ordering anti-strategic
- 5 `use_cases`; full `when_to_use` / `when_not_to_use` prose declared

### 13.5 Observation

`FastFocus` appears in **two** plugins (VotingPlugin and CategorizationPlugin) with different parentheticals. The audit in plan Task 1.5 will need to decide whether the canonical ThinkLet is the same construct used in two registers, or whether one of the two tags is overloaded.

---

## 14. Frontend caching of agenda + current activity

- [app/static/js/meeting.js:244-248, 435-436, 564](../app/static/js/meeting.js) — `state.agenda` array and `state.agendaMap` Map populated on connection; `currentActivity` resolved from `state.latestState`.
- `renderAgenda(data.agenda)` is the client's redraw entry (referenced ~line 3778 of meeting.js per the scan).
- Cache is invalidated by WebSocket `agenda_update` messages broadcast from the meeting state machine ([app/routers/realtime.py](../app/routers/realtime.py)).

**Breaking point.** Engine-initiated agenda mutations (creating an activity row for a new iteration round, advancing past a facilitator decision) must broadcast `agenda_update`, or the frontend will silently desync until the next reconnect.

---

## 15. Database migrations

No Alembic directory exists at the project root or under `app/` (verified by `find`). Schema is currently managed by SQLAlchemy `Base.metadata.create_all` against a SQLite file (`decidero.db`). Adding new tables for orchestration documents or new columns to existing tables (iteration discriminators, phase ids) is mechanically possible but is not gated by a versioned-migration tool — any schema additions become breaking changes to deployed instances.

---

## 16. Consolidated breaking-point inventory

| # | Location | Assumption that breaks | Engine artifact that triggers it |
|---|---|---|---|
| BP-1 | [app/services/activity_pipeline.py:59-68](../app/services/activity_pipeline.py) | "Previous activity = row with the next-lower `order_index`" | `iterate`, `conditional`, any non-linear graph |
| BP-2 | [app/services/meeting_state.py:29-40](../app/services/meeting_state.py) | One `current_activity` string, set externally by the client | `facilitator-decision` and `ai-decision` pauses; engine-driven progression |
| BP-3 | [app/models/activity_bundle.py:6-17](../app/models/activity_bundle.py) | One `(activity_id, kind)` bundle per row, no round discriminator | `iterate` re-running the same step |
| BP-4 | [app/plugins/base.py:49-51](../app/plugins/base.py) | `validate_config()` is convention, not contract — never invoked by framework | Engine instantiating activities from JSON config |
| BP-5 | [app/routers/realtime.py:52-55, 165-172](../app/routers/realtime.py) | Agenda broadcast assumes a stable linear list; mutations only via client patches | Engine-initiated agenda mutations |
| BP-6 | [app/services/transfer_source.py](../app/services/transfer_source.py) + per-plugin serializers | Provenance preservation is per-plugin custom code, not a framework guarantee | New step kinds emitting items that no existing serializer covers |
| BP-7 | (absent) | No server-side reliability/retry analogue to `runReliableWriteAction` | `ai-decision` retries on schema-invalid LLM output |
| BP-8 | [app/data/meeting_manager.py:588-592](../app/data/meeting_manager.py) | `tool_type` is immutable on existing rows | Engine cannot rebind a step; must create new rows |
| BP-9 | [app/services/agenda_validator.py](../app/services/agenda_validator.py) | Validator's grammar is meeting-designer agendas, not orchestration documents | Engine validating loaded JSON orchestrations |
| BP-10 | [app/static/js/meeting.js](../app/static/js/meeting.js) | Frontend caches agenda at connect; refreshes only on `agenda_update` | Engine mutating agenda without broadcast → client desync |
| BP-11 | (absent) | No Alembic / migration framework | New tables for orchestration documents or bundle iteration columns |
| BP-12 | [app/tests/test_activity_plugins.py](../app/tests/test_activity_plugins.py) (gap) | No idempotency test for `open_activity()` | Iterative engine relying on idempotent plugin behavior without test coverage |

---

## 17. Stable surfaces (intentionally low-risk)

These are surfaces the engine can build *on* without expecting friction:

- The plugin ABC and manifest ([app/plugins/base.py](../app/plugins/base.py)) — frozen, well-tested.
- The plugin registry and loader ([app/plugins/registry.py](../app/plugins/registry.py), [app/plugins/loader.py](../app/plugins/loader.py)) — dropin discovery works.
- `ActivityContext` ([app/plugins/context.py](../app/plugins/context.py)) — sufficient for engine-driven plugin invocation.
- `ActivityBundle` storage and the `ActivityBundleManager` helpers — usable for any new step kind that emits an `items + metadata` payload.
- `AIProvider` ([app/services/ai_provider.py](../app/services/ai_provider.py)) — multi-provider, completion + streaming, ready to reuse for `ai-decision`.
- Reliability-policy manifest declaration and normalization ([app/services/activity_catalog.py:62-80](../app/services/activity_catalog.py)) — the declarative half of DP4 already works; only the server-side execution half (BP-7) is missing.
- The two-pass resequence in [app/data/meeting_manager.py:265-291](../app/data/meeting_manager.py) — robust enough to handle engine-driven inserts.

---

*End of audit.*
