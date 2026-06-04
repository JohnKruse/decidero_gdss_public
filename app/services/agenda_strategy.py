"""Smug Otter agenda-strategy seam and deterministic default binding.

The seam keeps agenda interpretation behind a strategy object. Two reference
implementations are defined here:

- `LinearAgendaStrategy` (Phase 2): canonical reference for order-index agenda
  behavior; admits mid-meeting creation through `MeetingManager.add_agenda_activity`.
- `OrchestrationEngineStrategy` (Phase 4 — Insolent Metronome): interprets a
  loaded `OrchestrationDocument` via a step-pointer state machine. Each call to
  `create_activity` materializes the next document step as an `AgendaActivity`;
  `resolve_prior_activity` uses the engine's plan order rather than order-index
  adjacency to name the donor bundle.

Convergent Yak: prior-bundle resolution now flows through explicit donor
requests rather than making the activity pipeline infer meaning from order
adjacency. Both strategies respect the `PriorActivityReference`/`PriorActivityResolution`
hook signature introduced in Phase 3.

Loquacious Pelican: realtime broadcast side effects stay outside this
synchronous strategy interface. Engine callers broadcast mutations through
`app.services.orchestration_realtime` after `create_activity` or
`resume_with_facilitator_decision` returns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, object_session

from app.models.activity_bundle import ActivityBundle
from app.models.meeting import AgendaActivity, Meeting


@dataclass(frozen=True)
class PriorActivityReference:
    """Convergent Yak request for the donor bundle feeding a consumer activity."""

    consumer_activity_id: str
    donor_activity_id: Optional[str] = None
    logical_step_id: Optional[str] = None
    round_index: Optional[int] = None
    handle: Optional[str] = None

    @classmethod
    def for_consumer(cls, activity: AgendaActivity) -> "PriorActivityReference":
        return cls(consumer_activity_id=activity.activity_id)


@dataclass(frozen=True)
class PriorActivityResolution:
    """Convergent Yak resolved donor plus optional iteration discriminator."""

    activity: AgendaActivity
    logical_step_id: Optional[str] = None
    round_index: Optional[int] = None
    handle: Optional[str] = None


class AgendaStrategy(ABC):
    """Smug Otter interface for interpreting a meeting agenda."""

    name = "abstract"

    @abstractmethod
    def resolve_prior_activity(
        self,
        meeting: Meeting,
        reference: PriorActivityReference,
    ) -> Optional[PriorActivityResolution]:
        """Resolve the donor activity and iteration for an input-bundle request."""

    @abstractmethod
    def list_agenda(self, meeting: Meeting) -> List[AgendaActivity]:
        """Return agenda activities in this strategy's canonical order."""

    @abstractmethod
    def is_complete(self, meeting: Meeting) -> bool:
        """Return whether the strategy considers the meeting agenda complete."""

    @abstractmethod
    def on_activity_close(self, meeting: Meeting, activity: AgendaActivity) -> None:
        """Record an activity close event for strategies that need it."""

    @abstractmethod
    def create_activity(
        self,
        meeting: Meeting,
        payload: Any,
        manager: Any,
    ) -> AgendaActivity:
        """Admit mid-meeting activity creation through the owning manager."""


class LinearAgendaStrategy(AgendaStrategy):
    """Smug Otter reference implementation for current order-index agendas.

    Convergent Yak: explicit donor references pass through unchanged; otherwise
    this strategy preserves the Phase 2 previous-by-order-index behavior.
    """

    name = "linear"

    def resolve_prior_activity(
        self,
        meeting: Meeting,
        reference: PriorActivityReference,
    ) -> Optional[PriorActivityResolution]:
        agenda = self.list_agenda(meeting)
        if reference.donor_activity_id:
            for item in agenda:
                if item.activity_id == reference.donor_activity_id:
                    return PriorActivityResolution(
                        activity=item,
                        logical_step_id=reference.logical_step_id,
                        round_index=reference.round_index,
                        handle=reference.handle,
                    )
            return None

        previous = None
        for item in agenda:
            if item.activity_id == reference.consumer_activity_id:
                if previous is None:
                    return None
                return PriorActivityResolution(
                    activity=previous,
                    logical_step_id=reference.logical_step_id,
                    round_index=reference.round_index,
                    handle=reference.handle,
                )
            previous = item
        return None

    def list_agenda(self, meeting: Meeting) -> List[AgendaActivity]:
        return sorted(
            list(getattr(meeting, "agenda_activities", []) or []),
            key=lambda item: item.order_index,
        )

    def is_complete(self, meeting: Meeting) -> bool:
        agenda = self.list_agenda(meeting)
        if not agenda:
            return True
        db = object_session(meeting)
        if db is None:
            return False
        latest = (
            db.query(ActivityBundle.id)
            .filter(
                ActivityBundle.meeting_id == meeting.meeting_id,
                ActivityBundle.activity_id == agenda[-1].activity_id,
                ActivityBundle.kind == "output",
            )
            .first()
        )
        return latest is not None

    def on_activity_close(self, meeting: Meeting, activity: AgendaActivity) -> None:
        return None

    def create_activity(
        self,
        meeting: Meeting,
        payload: Any,
        manager: Any,
    ) -> AgendaActivity:
        return manager.add_agenda_activity(meeting.meeting_id, payload)


def get_agenda_strategy(meeting: Meeting) -> AgendaStrategy:
    """Smug Otter deterministic binding for a meeting's agenda strategy.

    Linear agendas remain the default. Meetings with persisted orchestration
    metadata are rebound to an `OrchestrationEngineStrategy` from the packaged
    document path.
    """
    strategy_name = str(getattr(meeting, "agenda_strategy", "") or "linear").lower()
    orchestration_path = getattr(meeting, "orchestration_path", None)
    if strategy_name == "orchestration" and orchestration_path:
        path_str = str(orchestration_path)
        if path_str.startswith("template://"):
            document = _load_inline_template_document(path_str, object_session(meeting))
        else:
            document = _load_persisted_orchestration_document(path_str)
        if document is not None:
            strategy = OrchestrationEngineStrategy(document)
            # Deliberate Heron: the strategy is rebuilt per request, so restore
            # the iteration map and any paused decision from persisted rows.
            strategy.rehydrate_from_db(meeting, object_session(meeting))
            return strategy
    return LinearAgendaStrategy()


def _load_inline_template_document(
    orchestration_path: str, db: Optional[Session]
) -> Optional[Any]:
    """Plainspoken Marmot: resolve a ``template://<id>`` path to its inline document.

    Forked/tuned templates store the orchestration document inline in the template
    payload rather than as a repo file, so the meeting references it by template id.
    """
    from app.models.meeting_template import MeetingTemplate
    from app.services.orchestration_loader import (
        OrchestrationValidationError,
        load_orchestration_data,
    )

    if db is None:
        return None
    template_id = orchestration_path[len("template://"):]
    template = (
        db.query(MeetingTemplate)
        .filter(MeetingTemplate.template_id == template_id)
        .first()
    )
    if template is None:
        return None
    payload = template.template_payload if isinstance(template.template_payload, dict) else {}
    orchestration = payload.get("orchestration") if isinstance(payload, dict) else None
    document = orchestration.get("document") if isinstance(orchestration, dict) else None
    if not isinstance(document, dict):
        return None
    try:
        return load_orchestration_data(document)
    except (OrchestrationValidationError, ValueError):
        return None


def _load_persisted_orchestration_document(orchestration_path: str) -> Optional[Any]:
    """Load a persisted orchestration path if it resolves inside the repo."""
    from app.services.orchestration_loader import (
        OrchestrationValidationError,
        load_orchestration_path,
    )

    project_root = Path(__file__).resolve().parents[2]
    candidate = Path(orchestration_path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(project_root.resolve())
    except ValueError:
        return None
    try:
        return load_orchestration_path(resolved)
    except (OSError, OrchestrationValidationError, ValueError):
        return None


def _round_output_logical_step_id(step: Any, path: str) -> str:
    """Logical_step_id of the activity that produces the round's convergence output.

    In a feedback loop this is the activity declaring `transform_input` (it both
    consumes the prior round's feedback and produces the result the transform /
    predicate read); when several do, the last; when none do, the last leaf.
    This lets a round subcycle place non-converging steps (e.g. a post-ranking
    justification) *after* the ranking without the predicate reading the wrong
    output.
    """
    from app.services.orchestration_loader import ActivityStep

    leaves: List[Tuple[str, Optional[str]]] = []

    def _walk(node: Any, node_path: str) -> None:
        children = getattr(node, "steps", None)
        if not children:
            transform_input = (
                getattr(node, "transform_input", None)
                if isinstance(node, ActivityStep)
                else None
            )
            leaves.append((f"engine:{node_path}", transform_input))
            return
        for index, child in enumerate(children):
            child_path = f"{node_path}.{index}" if node_path else str(index)
            _walk(child, child_path)

    _walk(step, path)
    if not leaves:
        return f"engine:{path}" if path else "engine:0"
    for lsid, transform_input in reversed(leaves):
        if transform_input:
            return lsid
    return leaves[-1][0]


@dataclass
class _SequenceFrame:
    """Insolent Metronome walker frame: a sequence step in progress.

    `iterate_frame` is the nearest enclosing iterate, if any. When a sequence is
    nested inside an iterate (a round subcycle), activities emitted from this
    frame must inherit that iterate's round context (round_index + frame) so
    feedback injection, iteration metadata, and round-output collection keep
    working. It is None for top-level sequences.
    """

    steps: List[Any]
    path: str
    pointer: int = 0
    iterate_frame: Optional["_IterateFrame"] = None


@dataclass
class _GateContext:
    """Deliberate Heron: a paused iterate round-gate awaiting a facilitator choice."""

    gate_logical_step_id: str
    round_index: int
    recommendation: str  # "continue" or "conclude"
    recommendation_source: str  # "convergence" or "ai"
    round_number: int
    max_rounds: int
    converged: bool


@dataclass
class _IterateFrame:
    """Insolent Metronome walker frame: an iterate step in progress.

    Tracks the iteration counter and the bundle history fed to the convergence
    predicate. `round_activity_ids` collects the activities minted in the
    current round so the engine can locate the round's output bundle when the
    round ends.
    """

    step: Any  # IterateStep
    path: str
    pointer: int = 0
    round_index: int = 0
    bundle_history: List[Dict[str, Any]] = field(default_factory=list)
    round_activity_ids: List[str] = field(default_factory=list)


class _PlanWalker:
    """Insolent Metronome state machine that emits plan entries leaf-by-leaf.

    The walker keeps a frame stack and emits one `(logical_step_id, ActivityStep,
    round_index, iterate_frame)` tuple per call to `advance()`. When the walker
    must evaluate a convergence predicate to decide whether to start another
    round, it asks the caller to supply a database session; absent one, it sets
    `needs_db=True` and returns `None` so the caller can defer eager-walking.
    """

    def __init__(self, top_steps: List[Any]) -> None:
        self._stack: List[Any] = [_SequenceFrame(steps=list(top_steps), path="")]
        self.needs_db: bool = False
        # Deliberate Heron: set when the walker pauses at an iterate round-gate.
        self.needs_gate: Optional[_GateContext] = None
        # Deliberate Heron: bundle lookups must be scoped to this meeting, since
        # logical_step_ids are shared across meetings built from the same document.
        self.meeting_id: Optional[str] = None

    @property
    def exhausted(self) -> bool:
        return not self._stack

    def advance(
        self, db: Optional[Session]
    ) -> Optional[Tuple[str, Any, int, Optional[_IterateFrame]]]:
        from app.services.orchestration_loader import (
            ActivityStep,
            ConditionalStep,
            FacilitatorDecisionStep,
            AIDecisionStep,
            IterateStep,
            SequenceStep,
        )
        from app.services.bundle_transforms import get_bundle_transform_registry
        from app.services.convergence_predicates import get_convergence_predicate_registry

        self.needs_db = False
        self.needs_gate = None
        while self._stack:
            frame = self._stack[-1]
            if isinstance(frame, _SequenceFrame):
                if frame.pointer >= len(frame.steps):
                    self._stack.pop()
                    continue
                cur = frame.steps[frame.pointer]
                child_path = (
                    f"{frame.path}.{frame.pointer}" if frame.path else str(frame.pointer)
                )
                frame.pointer += 1
                # When this sequence is nested inside an iterate, propagate that
                # round context to emitted activities and deeper sequences.
                ctx = frame.iterate_frame
                ctx_round = ctx.round_index if ctx is not None else 0
                if isinstance(cur, ActivityStep):
                    return (f"engine:{child_path}", cur, ctx_round, ctx)
                if isinstance(cur, SequenceStep):
                    self._stack.append(
                        _SequenceFrame(steps=list(cur.steps), path=child_path, iterate_frame=ctx)
                    )
                    continue
                if isinstance(cur, IterateStep):
                    # Insolent Metronome: dispatch into the iterate state machine.
                    self._stack.append(_IterateFrame(step=cur, path=child_path))
                    continue
                if isinstance(cur, ConditionalStep):
                    continue  # reserved / deferred — skip silently
                if isinstance(cur, FacilitatorDecisionStep):
                    # Insolent Metronome: facilitator-decision pause dispatch.
                    return (f"engine:{child_path}", cur, ctx_round, ctx)
                if isinstance(cur, AIDecisionStep):
                    # Insolent Metronome: ai-decision dispatch (Phase 4 Step 5).
                    return (f"engine:{child_path}", cur, ctx_round, ctx)
                continue
            elif isinstance(frame, _IterateFrame):
                if frame.pointer >= len(frame.step.steps):
                    if db is None:
                        self.needs_db = True
                        return None
                    next_round = frame.round_index + 1
                    at_cap = next_round >= frame.step.max_rounds
                    gate = getattr(frame.step, "round_gate", None)

                    already_recorded = len(frame.bundle_history) > frame.round_index
                    round_output = (
                        None
                        if already_recorded
                        else self._collect_round_output(frame, db, self.meeting_id)
                    )

                    # Deliberate Heron: a gated boundary below the cap must wait for
                    # the round to actually close before presenting the continue/
                    # conclude decision. Stop extending rather than appending an
                    # empty round and evaluating the recommendation on stale data.
                    if (
                        gate
                        and not at_cap
                        and not already_recorded
                        and not (round_output or {}).get("items")
                    ):
                        return None

                    # Idempotent per-round append: re-entering the same boundary
                    # (e.g. while paused on a round-gate) must not double-count
                    # this round into the convergence history.
                    if not already_recorded:
                        transform_spec = frame.step.bundle_transform or {}
                        transform = get_bundle_transform_registry().get_transform(
                            transform_spec.get("name", "")
                        )
                        transformed = (
                            transform.transform(round_output or {}, transform_spec.get("config") or {})
                            if transform is not None
                            else (round_output or {})
                        )
                        frame.bundle_history.append(transformed)
                    pred_spec = frame.step.convergence_predicate or {}
                    predicate = get_convergence_predicate_registry().get_predicate(
                        pred_spec.get("name", "")
                    )
                    fired = (
                        bool(predicate.evaluate(frame.bundle_history, pred_spec.get("config") or {}))
                        if predicate is not None
                        else False
                    )

                    # Deliberate Heron: facilitator round-gate. Below the cap the
                    # walker pauses for a continue/conclude decision instead of
                    # auto-deciding; the predicate verdict is the recommendation.
                    if gate and not at_cap:
                        gate_lsid = (
                            f"engine:{frame.path}#gate" if frame.path else "engine:#gate"
                        )
                        decision = self._lookup_gate_decision(
                            db, gate_lsid, frame.round_index, self.meeting_id
                        )
                        if decision == "conclude":
                            self._stack.pop()
                            continue
                        if decision == "continue":
                            frame.round_index = next_round
                            frame.pointer = 0
                            frame.round_activity_ids = []
                            continue
                        self.needs_gate = _GateContext(
                            gate_logical_step_id=gate_lsid,
                            round_index=frame.round_index,
                            recommendation=("conclude" if fired else "continue"),
                            recommendation_source=str(gate.get("recommendation", "convergence")),
                            round_number=frame.round_index + 1,
                            max_rounds=frame.step.max_rounds,
                            converged=fired,
                        )
                        return None

                    # No gate, or the cap is a hard backstop that forces conclude.
                    if fired or at_cap:
                        self._stack.pop()
                        continue
                    frame.round_index = next_round
                    frame.pointer = 0
                    frame.round_activity_ids = []
                    continue
                cur = frame.step.steps[frame.pointer]
                child_path = (
                    f"{frame.path}.{frame.pointer}" if frame.path else str(frame.pointer)
                )  # stable across rounds
                frame.pointer += 1
                if isinstance(cur, ActivityStep):
                    return (f"engine:{child_path}", cur, frame.round_index, frame)
                if isinstance(cur, SequenceStep):
                    # One level of recursion: a round subcycle. Push a sequence
                    # frame carrying this iterate's round context so its leaf
                    # activities inherit round_index + frame. The round boundary
                    # fires once this drains and the iterate pointer is past it.
                    self._stack.append(
                        _SequenceFrame(steps=list(cur.steps), path=child_path, iterate_frame=frame)
                    )
                    continue
                raise NotImplementedError(
                    "Nested iterate inside iterate is not yet supported; a round "
                    "subcycle may be a sequence of activities."
                )
        return None

    @staticmethod
    def _lookup_gate_decision(
        db: Session,
        gate_logical_step_id: str,
        round_index: int,
        meeting_id: Optional[str],
    ) -> Optional[str]:
        """Deliberate Heron: read a persisted round-gate choice, if any.

        Gate decisions are persisted as facilitator-decision output bundles tagged
        with the gate's logical_step_id and round_index, so a per-request strategy
        re-derives the facilitator's continue/conclude steer for each boundary.
        Scoped to `meeting_id` because logical_step_ids are shared across meetings
        built from the same document.
        """
        query = db.query(ActivityBundle).filter(
            ActivityBundle.logical_step_id == gate_logical_step_id,
            ActivityBundle.round_index == round_index,
            ActivityBundle.kind == "output",
        )
        if meeting_id is not None:
            query = query.filter(ActivityBundle.meeting_id == meeting_id)
        bundle = query.order_by(ActivityBundle.id.desc()).first()
        if bundle is None:
            return None
        chosen = dict(bundle.bundle_metadata or {}).get("chosen")
        return chosen if chosen in ("continue", "conclude") else None

    @staticmethod
    def _collect_round_output(
        frame: _IterateFrame, db: Session, meeting_id: Optional[str] = None
    ) -> Dict[str, Any]:
        # The round's convergence output comes from the round-output activity (the
        # ranking in a feedback loop), not necessarily the last step minted — a
        # subcycle may end with a non-converging step such as a justification.
        target_lsid = _round_output_logical_step_id(frame.step, frame.path)
        query = db.query(ActivityBundle).filter(
            ActivityBundle.logical_step_id == target_lsid,
            ActivityBundle.round_index == frame.round_index,
            ActivityBundle.kind == "output",
        )
        if meeting_id is not None:
            query = query.filter(ActivityBundle.meeting_id == meeting_id)
        bundle = query.order_by(ActivityBundle.id.desc()).first()

        # Legacy in-process fallback: a flow that did not tag logical_step_id.
        # Scan the round's minted activities (newest first) for one with items.
        if bundle is None and frame.round_activity_ids:
            for activity_id in reversed(frame.round_activity_ids):
                candidate = (
                    db.query(ActivityBundle)
                    .filter(
                        ActivityBundle.activity_id == activity_id,
                        ActivityBundle.kind == "output",
                    )
                    .order_by(ActivityBundle.round_index.desc(), ActivityBundle.id.desc())
                    .first()
                )
                if candidate is not None and (candidate.items or []):
                    bundle = candidate
                    break
        if bundle is None:
            return {"items": [], "metadata": {}}
        return {
            "items": list(bundle.items or []),
            "metadata": dict(bundle.bundle_metadata or {}),
        }


class OrchestrationEngineStrategy(AgendaStrategy):
    """Insolent Metronome step-pointer state machine for orchestration documents.

    Interprets a loaded `OrchestrationDocument` by walking the document AST
    leaf-by-leaf through a `_PlanWalker`. `create_activity` materializes the
    next plan entry as an `AgendaActivity` row; `resolve_prior_activity` uses
    plan order rather than order-index adjacency to name the donor bundle and
    surfaces the iteration counter (logical_step_id and round_index) on the
    resolution per the Phase 3 hook signature.

    Phase 4 Step 3 adds the `iterate` step kind. Each iteration runs the child
    steps once, applies the named `BundleTransform` to the round output, and
    evaluates the named `ConvergencePredicate` against the accumulated bundle
    history (resolved against Phase 3's registries at
    `app/services/bundle_transforms.py` and
    `app/services/convergence_predicates.py`). The `max_rounds` bound is a hard
    ceiling enforced regardless of predicate state.

    `FacilitatorDecisionStep` and `AIDecisionStep` are delivered in Phase 4
    Steps 4-5.
    """

    name = "orchestration"

    FACILITATOR_DECISION_TOOL_TYPE = "facilitator_decision"
    AI_DECISION_TOOL_TYPE = "ai_decision"

    DEFAULT_AI_DECISION_RETRY_POLICY: Dict[str, Any] = {
        "max_retries": 2,
        "base_delay_ms": 0,
        "max_delay_ms": 0,
        "jitter_ratio": 0.0,
    }

    def __init__(
        self,
        document: "OrchestrationDocument",  # noqa: F821
        *,
        ai_caller: Optional[Any] = None,
        ai_settings: Optional[Dict[str, Any]] = None,
        ai_retry_policy: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._document = document
        # (logical_step_id, step, round_index, iterate_frame_or_None) — step may
        # be an ActivityStep, FacilitatorDecisionStep, or AIDecisionStep.
        self._plan: List[Tuple[str, Any, int, Optional[_IterateFrame]]] = []
        # activity_id -> (logical_step_id, round_index)
        self._activity_iteration: Dict[str, Tuple[str, int]] = {}
        # Pending facilitator decision: dict with activity_id/step/logical_step_id
        # while paused, or None when the engine is free to advance.
        self._pending_decision: Optional[Dict[str, Any]] = None
        # AI-decision injection points. The default `ai_caller` lazily delegates
        # to `app/services/ai_provider.py::chat_complete` via asyncio.run so
        # tests can supply a synchronous stub without touching the network.
        self._ai_caller = ai_caller if ai_caller is not None else _default_ai_caller
        self._ai_settings: Dict[str, Any] = dict(ai_settings or {})
        self._ai_retry_policy: Dict[str, Any] = dict(
            ai_retry_policy or self.DEFAULT_AI_DECISION_RETRY_POLICY
        )
        self._walker = _PlanWalker(document.steps)
        # Eager prefetch: walk until walker requires DB or document is exhausted.
        self._extend_plan(db=None)

    def _extend_plan(self, db: Optional[Session]) -> None:
        while True:
            entry = self._walker.advance(db)
            if entry is None:
                return
            self._plan.append(entry)

    def _materialize_count(self, meeting: Meeting, db: Session) -> int:
        """Count plan-aligned AgendaActivity rows already minted for this meeting.

        Round-gate decision activities are materialized out-of-band (they are not
        plan entries), so they are excluded here to keep `step_index` aligned with
        the plan list.
        """
        rows = (
            db.query(AgendaActivity.config)
            .filter(AgendaActivity.meeting_id == meeting.meeting_id)
            .all()
        )
        count = 0
        for (config,) in rows:
            orchestration = (config or {}).get("_orchestration") or {}
            if orchestration.get("gate"):
                continue
            count += 1
        return count

    def _next_order_index(self, meeting: Meeting, db: Session) -> int:
        """Next agenda position across *all* rows (including out-of-band gates).

        `step_index` is the plan-aligned count and excludes gate decisions, so it
        cannot be used for `order_index` (which has a unique (meeting, order_index)
        constraint). This counts every materialized row instead.
        """
        count = (
            db.query(func.count(AgendaActivity.activity_id))
            .filter(AgendaActivity.meeting_id == meeting.meeting_id)
            .scalar()
        ) or 0
        return int(count) + 1

    def _completed_count(self, meeting: Meeting, db: Session) -> int:
        """Count plan steps whose activity has an output bundle (closed)."""
        count = (
            db.query(func.count(func.distinct(ActivityBundle.activity_id)))
            .filter(
                ActivityBundle.meeting_id == meeting.meeting_id,
                ActivityBundle.kind == "output",
            )
            .scalar()
        ) or 0
        return int(count)

    def rehydrate_from_db(self, meeting: Meeting, db: Optional[Session]) -> None:
        """Deliberate Heron: rebuild per-run in-memory state from persisted rows.

        A fresh `OrchestrationEngineStrategy` is constructed on every request
        (see `get_agenda_strategy`), so the in-memory `_activity_iteration` map
        and `_pending_decision` reset to empty. Production advancement (Phase 8)
        reconstructs the strategy per request, so without this rebuild the
        engine forgets which prior activity belongs to which iterate round and
        `previous_round_feedback` injection silently produces empty input
        bundles. This reconstructs that state from persisted rows:

        - `_activity_iteration` from activities whose config carries the
          `_orchestration` iteration discriminator, so the feedback path can
          locate the prior round's activity and bundle.
        - `_pending_decision` from the last materialized facilitator-decision
          activity that has no output bundle yet (the engine paused there).

        Idempotent and merge-only: safe to call on an already-populated
        strategy, so the in-process test flows that accumulate state are
        unaffected.
        """
        if db is None:
            return
        activities = (
            db.query(AgendaActivity)
            .filter(AgendaActivity.meeting_id == meeting.meeting_id)
            .order_by(AgendaActivity.order_index.asc())
            .all()
        )
        for activity in activities:
            config = dict(activity.config or {})
            orchestration = config.get("_orchestration")
            if isinstance(orchestration, dict) and orchestration.get("logical_step_id"):
                self._activity_iteration.setdefault(
                    activity.activity_id,
                    (
                        str(orchestration["logical_step_id"]),
                        int(orchestration.get("round_index", 0) or 0),
                    ),
                )
        if self._pending_decision is None:
            for activity in reversed(activities):
                if activity.tool_type != self.FACILITATOR_DECISION_TOOL_TYPE:
                    continue
                has_output = (
                    db.query(ActivityBundle)
                    .filter(
                        ActivityBundle.activity_id == activity.activity_id,
                        ActivityBundle.kind == "output",
                    )
                    .first()
                    is not None
                )
                if has_output:
                    break  # the latest decision is resolved; engine is not paused
                config = dict(activity.config or {})
                orchestration = config.get("_orchestration") or {}
                self._pending_decision = {
                    "activity_id": activity.activity_id,
                    "logical_step_id": orchestration.get("logical_step_id")
                    or config.get("logical_step_id"),
                    "round_index": int(orchestration.get("round_index", 0) or 0),
                    "prompt": config.get("prompt") or activity.title,
                    "options": list(config.get("options") or []),
                    "context_bundle_keys": list(config.get("context_bundle_keys") or []),
                    "gate": bool(orchestration.get("gate", False)),
                    "recommendation": config.get("recommendation"),
                    "evidence": config.get("evidence"),
                }
                break

    def resolve_prior_activity(
        self,
        meeting: Meeting,
        reference: PriorActivityReference,
    ) -> Optional[PriorActivityResolution]:
        agenda = self.list_agenda(meeting)
        if reference.donor_activity_id:
            for item in agenda:
                if item.activity_id == reference.donor_activity_id:
                    iteration = self._activity_iteration.get(item.activity_id)
                    return PriorActivityResolution(
                        activity=item,
                        logical_step_id=reference.logical_step_id
                        or (iteration[0] if iteration else None),
                        round_index=reference.round_index
                        if reference.round_index is not None
                        else (iteration[1] if iteration else None),
                        handle=reference.handle,
                    )
            return None

        # No explicit donor: resolve by plan order (previous activity feeds this one)
        previous: Optional[AgendaActivity] = None
        for item in agenda:
            if item.activity_id == reference.consumer_activity_id:
                if previous is None:
                    return None
                iteration = self._activity_iteration.get(previous.activity_id)
                return PriorActivityResolution(
                    activity=previous,
                    logical_step_id=iteration[0] if iteration else None,
                    round_index=iteration[1] if iteration else None,
                    handle=reference.handle,
                )
            previous = item
        return None

    def list_agenda(self, meeting: Meeting) -> List[AgendaActivity]:
        return sorted(
            list(getattr(meeting, "agenda_activities", []) or []),
            key=lambda item: item.order_index,
        )

    def is_complete(self, meeting: Meeting) -> bool:
        db = object_session(meeting)
        if db is not None:
            self._walker.meeting_id = meeting.meeting_id
            self._extend_plan(db)
        if self._walker.exhausted and not self._plan:
            return True
        if db is None:
            return False
        return self._walker.exhausted and self._completed_count(meeting, db) >= len(
            self._plan
        )

    def iteration_metadata_for(self, activity_id: str) -> Tuple[Optional[str], int]:
        """Return the (logical_step_id, round_index) recorded for an activity.

        Callers that finalize an activity's output bundle through
        `ActivityBundleManager` pass these values to honour the Phase 3
        iteration storage model. Returns (None, 0) for unknown activity ids.
        """
        return self._activity_iteration.get(activity_id, (None, 0))

    def on_activity_close(self, meeting: Meeting, activity: AgendaActivity) -> None:
        return None

    def create_activity(
        self,
        meeting: Meeting,
        payload: Any,
        manager: Any,
    ) -> AgendaActivity:
        """Materialize the next engine step as an AgendaActivity row.

        `payload` and `manager` are unused; configuration comes from the bound
        `OrchestrationDocument`. Calls `plugin.validate_config` per DP6.
        """
        from app.plugins.registry import get_activity_registry
        from app.services.activity_catalog import get_activity_definition
        from app.utils.identifiers import generate_activity_id, generate_tool_config_id
        from app.services.orchestration_loader import (
            ActivityStep,
            AIDecisionStep,
            FacilitatorDecisionStep,
        )

        db = object_session(meeting)
        if db is None:
            raise ValueError("Meeting is not attached to a database session.")

        if self._pending_decision is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Orchestration engine is paused on a facilitator-decision step; "
                    "call resume_with_facilitator_decision() to advance."
                ),
            )

        self._walker.meeting_id = meeting.meeting_id
        step_index = self._materialize_count(meeting, db)
        # Drive walker forward only after all currently-planned entries have
        # been materialized. Advancing earlier can evaluate an iterate frame
        # before the current round's activity id has been recorded.
        if step_index >= len(self._plan):
            self._extend_plan(db)
        # Deliberate Heron: the walker paused at an iterate round-gate; materialize
        # the continue/conclude decision rather than a plan activity.
        if step_index >= len(self._plan) and self._walker.needs_gate is not None:
            return self._materialize_gate_decision(
                meeting, db, step_index, self._walker.needs_gate
            )
        if step_index >= len(self._plan):
            raise HTTPException(
                status_code=400,
                detail="Orchestration plan is complete; no further activities to create.",
            )

        logical_step_id, step, round_index, iterate_frame = self._plan[step_index]

        if isinstance(step, FacilitatorDecisionStep):
            return self._materialize_facilitator_decision(
                meeting, db, step_index, logical_step_id, step
            )

        if isinstance(step, AIDecisionStep):
            return self._materialize_ai_decision(
                meeting, db, step_index, logical_step_id, round_index, step
            )

        if not isinstance(step, ActivityStep):
            raise NotImplementedError(
                f"Step at position {step_index} is not an activity step."
            )

        definition = get_activity_definition(step.tool_type)
        if definition is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool type '{step.tool_type}' in orchestration document.",
            )

        # Merge activity catalog defaults with document step config (DP6)
        config: Dict[str, Any] = dict(definition.get("default_config", {}))
        config.update(dict(step.config or {}))
        if iterate_frame is not None:
            config["_orchestration"] = {
                "logical_step_id": logical_step_id,
                "round_index": round_index,
            }
        plugin = get_activity_registry().get_plugin(step.tool_type)
        validated_config = plugin.validate_config(config) if plugin else config

        activity_id = generate_activity_id(db, meeting.meeting_id, step.tool_type)
        tool_config_id = generate_tool_config_id(activity_id, meeting.meeting_id)

        activity = AgendaActivity(
            activity_id=activity_id,
            meeting_id=meeting.meeting_id,
            tool_type=step.tool_type,
            title=step.title,
            order_index=self._next_order_index(meeting, db),
            tool_config_id=tool_config_id,
            config=validated_config,
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)

        if iterate_frame is not None:
            self._activity_iteration[activity.activity_id] = (logical_step_id, round_index)
            iterate_frame.round_activity_ids.append(activity.activity_id)
            if round_index > 0 and step.transform_input and iterate_frame.bundle_history:
                from app.data.activity_bundle_manager import ActivityBundleManager
                from app.services.bundle_transforms import get_bundle_transform_registry

                transformed_input = dict(iterate_frame.bundle_history[-1] or {})
                previous_activity_id = next(
                    (
                        candidate_id
                        for candidate_id, (candidate_step_id, candidate_round)
                        in self._activity_iteration.items()
                        if (
                            candidate_step_id == logical_step_id
                            and candidate_round == round_index - 1
                        )
                    ),
                    None,
                )
                previous_output = None
                if previous_activity_id is not None:
                    previous_output = (
                        db.query(ActivityBundle)
                        .filter(
                            ActivityBundle.meeting_id == meeting.meeting_id,
                            ActivityBundle.activity_id == previous_activity_id,
                            ActivityBundle.kind == "output",
                        )
                        .order_by(
                            ActivityBundle.round_index.desc(),
                            ActivityBundle.id.desc(),
                        )
                        .first()
                    )
                if previous_output is not None:
                    transform_spec = iterate_frame.step.bundle_transform or {}
                    transform = get_bundle_transform_registry().get_transform(
                        transform_spec.get("name", "")
                    )
                    round_output = {
                        "items": list(previous_output.items or []),
                        "metadata": dict(previous_output.bundle_metadata or {}),
                    }
                    transformed_input = (
                        transform.transform(
                            round_output,
                            transform_spec.get("config") or {},
                        )
                        if transform is not None
                        else round_output
                    )
                    iterate_frame.bundle_history[-1] = transformed_input
                input_metadata = dict(transformed_input.get("metadata") or {})
                input_metadata["transform_input"] = step.transform_input
                ActivityBundleManager(db).create_bundle(
                    meeting.meeting_id,
                    activity.activity_id,
                    "input",
                    list(transformed_input.get("items") or []),
                    metadata=input_metadata,
                    logical_step_id=logical_step_id,
                    round_index=round_index,
                )
        return activity

    def _materialize_facilitator_decision(
        self,
        meeting: Meeting,
        db: Session,
        step_index: int,
        logical_step_id: str,
        step: Any,
    ) -> AgendaActivity:
        """Insolent Metronome: mint the placeholder row and enter pause state.

        Materializes an `AgendaActivity` carrying the decision prompt/options as
        configuration so callers can render the pause to a facilitator. The
        engine then refuses to advance until `resume_with_facilitator_decision`
        is called with one of the configured option names.
        """
        from app.utils.identifiers import generate_activity_id, generate_tool_config_id

        tool_type = self.FACILITATOR_DECISION_TOOL_TYPE
        activity_id = generate_activity_id(db, meeting.meeting_id, tool_type)
        tool_config_id = generate_tool_config_id(activity_id, meeting.meeting_id)

        config: Dict[str, Any] = {
            "prompt": step.prompt,
            "options": list(step.options),
            "context_bundle_keys": list(step.context_bundle_keys or []),
            # Deliberate Heron: persist the step pointer so a per-request strategy
            # can rehydrate the pause state from this row alone.
            "_orchestration": {"logical_step_id": logical_step_id, "round_index": 0},
        }

        activity = AgendaActivity(
            activity_id=activity_id,
            meeting_id=meeting.meeting_id,
            tool_type=tool_type,
            title=step.prompt,
            order_index=self._next_order_index(meeting, db),
            tool_config_id=tool_config_id,
            config=config,
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)

        self._pending_decision = {
            "activity_id": activity.activity_id,
            "logical_step_id": logical_step_id,
            "prompt": step.prompt,
            "options": list(step.options),
            "context_bundle_keys": list(step.context_bundle_keys or []),
        }
        return activity

    def _materialize_gate_decision(
        self,
        meeting: Meeting,
        db: Session,
        step_index: int,
        gate: _GateContext,
    ) -> AgendaActivity:
        """Deliberate Heron: mint the iterate round-gate decision and pause.

        Reuses the facilitator-decision tool type and pause contract, but the
        options are the loop-control verbs (`continue`/`conclude`) and the config
        carries the convergence recommendation and round evidence so the gate UI
        can render it. The decision is tagged `gate` in `_orchestration` so it is
        excluded from the plan-aligned activity count and so `resume_*` writes a
        gate-keyed output bundle the walker can read back.
        """
        from app.utils.identifiers import generate_activity_id, generate_tool_config_id

        tool_type = self.FACILITATOR_DECISION_TOOL_TYPE
        activity_id = generate_activity_id(db, meeting.meeting_id, tool_type)
        tool_config_id = generate_tool_config_id(activity_id, meeting.meeting_id)

        prompt = (
            f"Round {gate.round_number} of up to {gate.max_rounds} complete. "
            "Run another round or conclude the method?"
        )
        options = ["continue", "conclude"]
        evidence = {
            "round_number": gate.round_number,
            "max_rounds": gate.max_rounds,
            "converged": gate.converged,
            "recommendation_source": gate.recommendation_source,
        }
        config: Dict[str, Any] = {
            "prompt": prompt,
            "options": options,
            "context_bundle_keys": [],
            "recommendation": gate.recommendation,
            "evidence": evidence,
            "_orchestration": {
                "logical_step_id": gate.gate_logical_step_id,
                "round_index": gate.round_index,
                "gate": True,
            },
        }

        activity = AgendaActivity(
            activity_id=activity_id,
            meeting_id=meeting.meeting_id,
            tool_type=tool_type,
            title=prompt,
            order_index=self._next_order_index(meeting, db),
            tool_config_id=tool_config_id,
            config=config,
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)

        self._pending_decision = {
            "activity_id": activity.activity_id,
            "logical_step_id": gate.gate_logical_step_id,
            "round_index": gate.round_index,
            "prompt": prompt,
            "options": options,
            "context_bundle_keys": [],
            "gate": True,
            "recommendation": gate.recommendation,
            "evidence": evidence,
        }
        return activity

    def _materialize_ai_decision(
        self,
        meeting: Meeting,
        db: Session,
        step_index: int,
        logical_step_id: str,
        round_index: int,
        step: Any,
    ) -> AgendaActivity:
        """Insolent Metronome: ai-decision dispatch with Phase 3 reliability retry.

        Renders the step's `prompt_template` with the named context bundles,
        calls the injected `ai_caller`, parses the response as JSON, and
        validates it against the declared `output_schema`. Schema-validation
        failures are treated as retryable results so Phase 3's
        `app/services/reliable_writes.py::run_with_retry` retries the call
        under an idempotency key derived from the engine's step pointer
        (`logical_step_id`) plus `round_index`. The validated payload is
        written to the bundle stream as a typed item that satisfies Phase 1's
        `bundle_payload.schema.json`.

        When `review_required` is True the bundle's metadata records it; the
        immediately-following `facilitator-decision` step (mandated by the
        Step 1 loader) is responsible for gating downstream advancement via
        its own pause/resume cycle.
        """
        import json as _json
        from app.data.activity_bundle_manager import ActivityBundleManager
        from app.services.reliable_writes import run_with_retry
        from app.utils.identifiers import generate_activity_id, generate_tool_config_id

        tool_type = self.AI_DECISION_TOOL_TYPE
        activity_id = generate_activity_id(db, meeting.meeting_id, tool_type)
        tool_config_id = generate_tool_config_id(activity_id, meeting.meeting_id)

        activity = AgendaActivity(
            activity_id=activity_id,
            meeting_id=meeting.meeting_id,
            tool_type=tool_type,
            title="AI Decision",
            order_index=self._next_order_index(meeting, db),
            tool_config_id=tool_config_id,
            config={
                "prompt_template": step.prompt_template,
                "output_schema": step.output_schema,
                "review_required": bool(step.review_required),
                "context_bundle_keys": list(step.context_bundle_keys or []),
            },
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)

        rendered_prompt = _render_ai_decision_prompt(
            step.prompt_template,
            self._resolve_ai_context_bundles(meeting, db, step.context_bundle_keys or []),
        )

        idempotency_key = f"{logical_step_id}:round{round_index}"

        def _task(_attempt: int, _idem_key: str) -> Dict[str, Any]:
            raw = self._ai_caller(rendered_prompt, dict(self._ai_settings))
            try:
                parsed = _json.loads(raw) if isinstance(raw, str) else raw
            except _json.JSONDecodeError as exc:
                return {
                    "_validation_failed": True,
                    "errors": [f"JSON parse error: {exc}"],
                    "raw": raw,
                }
            valid, errors = _validate_output_schema(parsed, step.output_schema or {})
            if not valid:
                return {"_validation_failed": True, "errors": errors, "parsed": parsed}
            return {"_validated": True, "parsed": parsed}

        def _should_retry_result(result: Any) -> bool:
            return isinstance(result, dict) and result.get("_validation_failed", False)

        try:
            result = run_with_retry(
                task=_task,
                policy=dict(self._ai_retry_policy),
                idempotency_key=idempotency_key,
                should_retry_result=_should_retry_result,
                sleep_func=lambda _seconds: None,
            )
        except Exception as exc:  # AI provider blew up — surface a structured failure
            raise HTTPException(
                status_code=502,
                detail=(
                    f"AI provider raised in ai-decision step '{logical_step_id}': {exc}"
                ),
            ) from exc

        if isinstance(result, dict) and result.get("_validation_failed"):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"ai-decision step '{logical_step_id}' exhausted retries; "
                    f"response failed output_schema validation: "
                    f"{result.get('errors')}"
                ),
            )

        validated = result["parsed"] if isinstance(result, dict) else result

        bundle_manager = ActivityBundleManager(db)
        content_text = (
            validated if isinstance(validated, str) else _json.dumps(validated)
        )
        bundle_manager.finalize_output_bundle(
            meeting.meeting_id,
            activity.activity_id,
            items=[{
                "content": content_text,
                "metadata": {
                    "ai_decision": {
                        "validated_output": validated,
                        "review_required": bool(step.review_required),
                        "logical_step_id": logical_step_id,
                        "round_index": round_index,
                        "idempotency_key": idempotency_key,
                    }
                },
                "source": {
                    "meeting_id": meeting.meeting_id,
                    "activity_id": activity.activity_id,
                    "tool_type": tool_type,
                },
                "activity_id": activity.activity_id,
            }],
            metadata={
                "source": "ai_decision",
                "review_required": bool(step.review_required),
                "logical_step_id": logical_step_id,
                "idempotency_key": idempotency_key,
            },
        )

        return activity

    @staticmethod
    def _resolve_ai_context_bundles(
        meeting: Meeting, db: Session, keys: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Resolve `context_bundle_keys` against the meeting's bundle stream.

        Each key is treated as a `logical_step_id` lookup against the latest
        `output` bundle carrying that id; if no matching bundle exists, the
        key is interpreted as an `activity_id` and the latest output bundle
        for that activity is used. Unresolved keys are silently omitted from
        the rendered prompt context.
        """
        resolved: Dict[str, Dict[str, Any]] = {}
        for key in keys:
            bundle = (
                db.query(ActivityBundle)
                .filter(
                    ActivityBundle.meeting_id == meeting.meeting_id,
                    ActivityBundle.kind == "output",
                    ActivityBundle.logical_step_id == key,
                )
                .order_by(ActivityBundle.round_index.desc(), ActivityBundle.id.desc())
                .first()
            )
            if bundle is None:
                bundle = (
                    db.query(ActivityBundle)
                    .filter(
                        ActivityBundle.meeting_id == meeting.meeting_id,
                        ActivityBundle.kind == "output",
                        ActivityBundle.activity_id == key,
                    )
                    .order_by(ActivityBundle.round_index.desc(), ActivityBundle.id.desc())
                    .first()
                )
            if bundle is not None:
                resolved[key] = {
                    "items": list(bundle.items or []),
                    "metadata": dict(bundle.bundle_metadata or {}),
                }
        return resolved

    def pending_decision(self) -> Optional[Dict[str, Any]]:
        """Return the pending facilitator-decision descriptor or None.

        While the engine is paused on a facilitator-decision step, this returns
        a dict carrying the pause `activity_id`, the rendered `prompt`, the
        configured `options`, and `context_bundle_keys`. Returns None when the
        engine is free to advance.
        """
        if self._pending_decision is None:
            return None
        return dict(self._pending_decision)

    def is_paused(self) -> bool:
        return self._pending_decision is not None

    def resume_with_facilitator_decision(
        self,
        meeting: Meeting,
        chosen_option: str,
        *,
        db: Optional[Session] = None,
        actor_user_id: Optional[str] = None,
    ) -> ActivityBundle:
        """Insolent Metronome: resume the engine with the facilitator's choice.

        Validates the chosen option against the step's configured options,
        writes an output bundle containing the choice as a single typed item
        (with provenance that satisfies `bundle_payload.schema.json`), and
        clears the pause state so subsequent `create_activity` calls can
        advance the plan.

        The executable contract for this entry point is the test module
        `app/tests/test_orchestration_engine.py` — see the
        `test_facilitator_decision_*` cases for invariants, failure modes, and
        the captured-bundle provenance contract.
        """
        from app.data.activity_bundle_manager import ActivityBundleManager

        if self._pending_decision is None:
            raise HTTPException(
                status_code=400,
                detail="No facilitator-decision is pending on this engine.",
            )

        pending = self._pending_decision
        options: List[str] = list(pending["options"])
        if not options:
            raise HTTPException(
                status_code=400,
                detail="Facilitator-decision step has no remaining options; engine cannot advance.",
            )
        if chosen_option not in options:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Facilitator choice '{chosen_option}' is not one of the configured "
                    f"options: {options}."
                ),
            )

        session = db if db is not None else object_session(meeting)
        if session is None:
            raise ValueError("Meeting is not attached to a database session.")

        activity_id = pending["activity_id"]
        logical_step_id = pending["logical_step_id"]
        round_index = int(pending.get("round_index", 0) or 0)

        bundle_manager = ActivityBundleManager(session)
        bundle = bundle_manager.finalize_output_bundle(
            meeting.meeting_id,
            activity_id,
            items=[{
                "content": chosen_option,
                "metadata": {
                    "facilitator_decision": {
                        "prompt": pending["prompt"],
                        "options": options,
                        "chosen": chosen_option,
                        "actor_user_id": actor_user_id,
                        "logical_step_id": logical_step_id,
                    }
                },
                "source": {
                    "meeting_id": meeting.meeting_id,
                    "activity_id": activity_id,
                    "tool_type": self.FACILITATOR_DECISION_TOOL_TYPE,
                },
                "activity_id": activity_id,
                "user_id": actor_user_id,
            }],
            metadata={
                "source": "facilitator_decision",
                "logical_step_id": logical_step_id,
                "options": options,
                "chosen": chosen_option,
            },
            # Deliberate Heron: tag with the step pointer so a per-request walker
            # can read a round-gate steer back by (logical_step_id, round_index).
            logical_step_id=logical_step_id,
            round_index=round_index,
        )

        self._pending_decision = None
        return bundle

    @property
    def document(self) -> "OrchestrationDocument":  # noqa: F821
        return self._document

    @property
    def plan(self) -> List[Tuple[str, Any]]:
        """Backward-compatible (logical_step_id, step) tuples for the known plan.

        For iterate-bearing documents this grows as rounds are committed.
        """
        return [(logical_step_id, step) for (logical_step_id, step, _r, _f) in self._plan]


# ---------------------------------------------------------------------------
# Insolent Metronome: ai-decision helper utilities
# ---------------------------------------------------------------------------


def _default_ai_caller(prompt: str, settings: Dict[str, Any]) -> str:
    """Default sync wrapper around `app/services/ai_provider.py::chat_complete`.

    Tests inject a synchronous stub so the engine never reaches the network.
    """
    import asyncio
    from app.services.ai_provider import chat_complete

    messages = [{"role": "user", "content": prompt}]
    system_prompt = settings.get("system_prompt", "") if isinstance(settings, dict) else ""
    return asyncio.run(chat_complete(settings, messages, system_prompt))


def _render_ai_decision_prompt(
    template: str, context_bundles: Dict[str, Dict[str, Any]]
) -> str:
    """Substitute `{key}` placeholders with JSON-encoded context bundles."""
    import json as _json

    rendered = template
    for key, bundle in context_bundles.items():
        placeholder = "{" + key + "}"
        if placeholder in rendered:
            rendered = rendered.replace(placeholder, _json.dumps(bundle))
    return rendered


_JSON_SCHEMA_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _validate_output_schema(data: Any, schema: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Minimal JSON-Schema-style validator for ai-decision output_schema.

    Supports the subset the engine and its tests rely on: top-level `type`
    checks, `required` field presence, recursive `properties` validation, and
    `items` validation for arrays. Numeric types are validated against `int`
    or `float` and explicitly reject `bool` for `integer`/`number`. Returns
    `(valid, errors)` so the caller can include a structured failure detail.
    """
    errors: List[str] = []
    if not isinstance(schema, dict) or not schema:
        return True, errors
    expected = schema.get("type")
    if expected:
        if expected == "integer":
            if isinstance(data, bool) or not isinstance(data, int):
                errors.append(f"expected integer, got {type(data).__name__}")
                return False, errors
        elif expected == "number":
            if isinstance(data, bool) or not isinstance(data, (int, float)):
                errors.append(f"expected number, got {type(data).__name__}")
                return False, errors
        else:
            py_type = _JSON_SCHEMA_TYPE_MAP.get(expected)
            if py_type is not None and not isinstance(data, py_type):
                errors.append(f"expected {expected}, got {type(data).__name__}")
                return False, errors
    if expected == "object" and isinstance(data, dict):
        for required_field in schema.get("required") or []:
            if required_field not in data:
                errors.append(f"missing required field '{required_field}'")
        for field_name, sub_schema in (schema.get("properties") or {}).items():
            if field_name in data and isinstance(sub_schema, dict):
                ok, sub_errors = _validate_output_schema(data[field_name], sub_schema)
                if not ok:
                    errors.extend(f"{field_name}.{e}" for e in sub_errors)
    if expected == "array" and isinstance(data, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(data):
                ok, sub_errors = _validate_output_schema(item, item_schema)
                if not ok:
                    errors.extend(f"[{idx}].{e}" for e in sub_errors)
    return not errors, errors
