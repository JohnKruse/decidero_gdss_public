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
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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

    Currently always returns `LinearAgendaStrategy`. Callers that drive an
    orchestration document bind `OrchestrationEngineStrategy` directly rather
    than routing through this function.
    """
    return LinearAgendaStrategy()


@dataclass
class _SequenceFrame:
    """Insolent Metronome walker frame: a sequence step in progress."""

    steps: List[Any]
    path: str
    pointer: int = 0


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
                if isinstance(cur, ActivityStep):
                    return (f"engine:{child_path}", cur, 0, None)
                if isinstance(cur, SequenceStep):
                    self._stack.append(_SequenceFrame(steps=list(cur.steps), path=child_path))
                    continue
                if isinstance(cur, IterateStep):
                    # Insolent Metronome: dispatch into the iterate state machine.
                    self._stack.append(_IterateFrame(step=cur, path=child_path))
                    continue
                if isinstance(cur, ConditionalStep):
                    continue  # reserved / deferred — skip silently
                if isinstance(cur, FacilitatorDecisionStep):
                    # Insolent Metronome: facilitator-decision pause dispatch.
                    return (f"engine:{child_path}", cur, 0, None)
                if isinstance(cur, AIDecisionStep):
                    raise NotImplementedError(
                        f"'{cur.type}' step kind is not yet implemented"
                    )
                continue
            elif isinstance(frame, _IterateFrame):
                if frame.pointer >= len(frame.step.steps):
                    if db is None:
                        self.needs_db = True
                        return None
                    round_output = self._collect_round_output(frame, db)
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
                    next_round = frame.round_index + 1
                    if fired or next_round >= frame.step.max_rounds:
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
                raise NotImplementedError(
                    "Nested control flow inside iterate is not supported in Phase 4."
                )
        return None

    @staticmethod
    def _collect_round_output(frame: _IterateFrame, db: Session) -> Dict[str, Any]:
        if not frame.round_activity_ids:
            return {"items": [], "metadata": {}}
        last_activity_id = frame.round_activity_ids[-1]
        bundle = (
            db.query(ActivityBundle)
            .filter(
                ActivityBundle.activity_id == last_activity_id,
                ActivityBundle.kind == "output",
            )
            .order_by(ActivityBundle.round_index.desc(), ActivityBundle.id.desc())
            .first()
        )
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

    def __init__(self, document: "OrchestrationDocument") -> None:  # noqa: F821
        self._document = document
        # (logical_step_id, step, round_index, iterate_frame_or_None) — step may
        # be an ActivityStep or FacilitatorDecisionStep.
        self._plan: List[Tuple[str, Any, int, Optional[_IterateFrame]]] = []
        # activity_id -> (logical_step_id, round_index)
        self._activity_iteration: Dict[str, Tuple[str, int]] = {}
        # Pending facilitator decision: dict with activity_id/step/logical_step_id
        # while paused, or None when the engine is free to advance.
        self._pending_decision: Optional[Dict[str, Any]] = None
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
        """Count AgendaActivity rows already minted for this meeting."""
        count = (
            db.query(func.count(AgendaActivity.activity_id))
            .filter(AgendaActivity.meeting_id == meeting.meeting_id)
            .scalar()
        ) or 0
        return int(count)

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
        from app.services.orchestration_loader import ActivityStep, FacilitatorDecisionStep

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

        step_index = self._materialize_count(meeting, db)
        # Drive walker forward (may evaluate iterate predicates now that we have db)
        self._extend_plan(db)
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
        plugin = get_activity_registry().get_plugin(step.tool_type)
        validated_config = plugin.validate_config(config) if plugin else config

        activity_id = generate_activity_id(db, meeting.meeting_id, step.tool_type)
        tool_config_id = generate_tool_config_id(activity_id, meeting.meeting_id)

        activity = AgendaActivity(
            activity_id=activity_id,
            meeting_id=meeting.meeting_id,
            tool_type=step.tool_type,
            title=step.title,
            order_index=step_index + 1,
            tool_config_id=tool_config_id,
            config=validated_config,
        )
        db.add(activity)
        db.commit()
        db.refresh(activity)

        if iterate_frame is not None:
            self._activity_iteration[activity.activity_id] = (logical_step_id, round_index)
            iterate_frame.round_activity_ids.append(activity.activity_id)
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
        }

        activity = AgendaActivity(
            activity_id=activity_id,
            meeting_id=meeting.meeting_id,
            tool_type=tool_type,
            title=step.prompt,
            order_index=step_index + 1,
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
