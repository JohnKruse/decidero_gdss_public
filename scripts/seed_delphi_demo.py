"""Seed a screen-capture-ready Classical Delphi meeting.

The script creates one small, anonymous-by-presentation Delphi panel in the
repository's ``decidero.db``.  The opening brainstorm and the first ranking are
written as activity output bundles, so the meeting is left immediately before
the in-round facilitator decision that displays the ranking statistics and the
least-converged-item selector.

The public ``inject_ranking_ballots`` helper is also useful during a walkthrough:
pass it a live rank activity id and a list of per-participant rank mappings to
populate a later round.  A mapping may use the item's stable key (preferred) or
an option id; a list is interpreted as item keys in rank order.  The helper is
idempotent for an activity and stores the ballots in the same output-bundle
metadata shape used by the test suite.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

# Make direct execution independent of the caller's import path.  The requested
# command already supplies PYTHONPATH=., but this keeps the helper importable too.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

import app.models  # noqa: F401 - register every model before create_all/queries
from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.ideas_manager import IdeasManager
from app.data.meeting_manager import MeetingManager
from app.data.meeting_template_manager import (
    MeetingTemplateManager,
    seed_builtin_meeting_templates,
)
from app.data.user_manager import UserManager
from app.database import Base, SessionLocal, engine, ensure_sqlite_schema
from app.models.activity_bundle import ActivityBundle
from app.models.categorization import (
    CategorizationAssignment,
    CategorizationAuditEvent,
    CategorizationBallot,
    CategorizationBucket,
    CategorizationFinalAssignment,
    CategorizationItem,
)
from app.models.idea import Idea
from app.models.idempotency import BrainstormingIdempotencyKey
from app.models.meeting import Agenda, AgendaActivity, Meeting, ToolConfig, participants_table
from app.models.outlier_rationale import OutlierRationale
from app.models.rank_order_voting import RankOrderVote
from app.models.user import User, UserRole
from app.models.voting import VotingVote
from app.schemas.meeting import MeetingCreate, PublicityType
from app.services.agenda_strategy import get_agenda_strategy
from app.utils.security import get_password_hash


DEMO_TITLE = "Classical Delphi \u2014 Demo"
DEMO_DESCRIPTION = (
    "Decision question: Which factors should guide prioritization of the 2027 "
    "product roadmap for a sustainable, customer-centered release plan?"
)
DEMO_ORGANIZATION = "Decidero Delphi Demo Panel"
DEMO_PARTICIPANT_PASSWORD = "password123"

DEMO_PARTICIPANTS = (
    ("demo_p1", "Maya", "Chen"),
    ("demo_p2", "Jonas", "Weber"),
    ("demo_p3", "Priya", "Nair"),
    ("demo_p4", "Lucas", "Moretti"),
    ("demo_p5", "Sofia", "Alvarez"),
    ("demo_p6", "Ethan", "Brooks"),
)

DEMO_ITEMS = (
    {
        "key": "customer-outcome-impact",
        "content": "Expected customer outcome impact",
    },
    {
        "key": "delivery-feasibility",
        "content": "Delivery feasibility and time to value",
    },
    {
        "key": "strategic-differentiation",
        "content": "Strategic differentiation in the 2027 market",
    },
    {
        "key": "platform-health",
        "content": "Platform health and technical sustainability",
    },
    {
        "key": "evidence-of-demand",
        "content": "Strength of evidence for customer demand",
    },
)

# Each row is a complete permutation of ranks 1..5.  The first item is
# intentionally polarized, while delivery feasibility is converged at rank 2.
DEMO_BALLOT_PATTERN = (
    {
        "customer-outcome-impact": 1,
        "delivery-feasibility": 2,
        "strategic-differentiation": 3,
        "platform-health": 4,
        "evidence-of-demand": 5,
    },
    {
        "customer-outcome-impact": 1,
        "delivery-feasibility": 2,
        "strategic-differentiation": 3,
        "platform-health": 4,
        "evidence-of-demand": 5,
    },
    {
        "customer-outcome-impact": 5,
        "delivery-feasibility": 2,
        "strategic-differentiation": 1,
        "platform-health": 3,
        "evidence-of-demand": 4,
    },
    {
        "customer-outcome-impact": 5,
        "delivery-feasibility": 2,
        "strategic-differentiation": 1,
        "platform-health": 3,
        "evidence-of-demand": 4,
    },
    {
        "customer-outcome-impact": 3,
        "delivery-feasibility": 2,
        "strategic-differentiation": 4,
        "platform-health": 1,
        "evidence-of-demand": 5,
    },
    {
        "customer-outcome-impact": 3,
        "delivery-feasibility": 2,
        "strategic-differentiation": 4,
        "platform-health": 1,
        "evidence-of-demand": 5,
    },
)


def _slug(value: Any) -> str:
    """Make a stable, human-readable fallback key for a bundle item."""

    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return text.strip("-") or "item"


def _iteration_metadata(activity: AgendaActivity) -> tuple[str | None, int]:
    orchestration = dict((activity.config or {}).get("_orchestration") or {})
    logical_step_id = orchestration.get("logical_step_id")
    try:
        round_index = int(orchestration.get("round_index", 0) or 0)
    except (TypeError, ValueError):
        round_index = 0
    return (str(logical_step_id) if logical_step_id else None, max(0, round_index))


def _latest_bundle(
    db: Session,
    meeting_id: str,
    activity_id: str,
    kind: str,
) -> ActivityBundle | None:
    return (
        db.query(ActivityBundle)
        .filter(
            ActivityBundle.meeting_id == meeting_id,
            ActivityBundle.activity_id == activity_id,
            ActivityBundle.kind == kind,
        )
        .order_by(ActivityBundle.round_index.desc(), ActivityBundle.id.desc())
        .first()
    )


def _item_key(item: Mapping[str, Any], index: int) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    stable_key = metadata.get("stable_key")
    if stable_key:
        return str(stable_key).strip()

    rank_meta = metadata.get("rank_order_voting")
    if isinstance(rank_meta, Mapping) and rank_meta.get("option_id"):
        return str(rank_meta["option_id"]).rsplit(":", 1)[-1]

    item_id = item.get("id")
    if item_id:
        return str(item_id)
    return _slug(item.get("content") or f"item-{index + 1}")


def _activity_items(db: Session, meeting: Meeting, activity: AgendaActivity) -> list[dict[str, Any]]:
    """Resolve the options for a rank activity from its input or prior output."""

    config_ideas = (activity.config or {}).get("ideas")
    if isinstance(config_ideas, list) and config_ideas:
        return [dict(item) for item in config_ideas if isinstance(item, Mapping)]

    input_bundle = _latest_bundle(db, meeting.meeting_id, activity.activity_id, "input")
    if input_bundle is not None and isinstance(input_bundle.items, list) and input_bundle.items:
        return [dict(item) for item in input_bundle.items if isinstance(item, Mapping)]

    agenda = sorted(meeting.agenda_activities or [], key=lambda row: row.order_index)
    try:
        position = next(index for index, row in enumerate(agenda) if row.activity_id == activity.activity_id)
    except StopIteration:
        position = len(agenda)

    for previous in reversed(agenda[:position]):
        output = _latest_bundle(db, meeting.meeting_id, previous.activity_id, "output")
        if output is not None and isinstance(output.items, list) and output.items:
            return [dict(item) for item in output.items if isinstance(item, Mapping)]
    return []


def _normalise_pattern_for_roster(
    pattern: Sequence[Any] | Mapping[str, Any], roster: list[User]
) -> list[Any]:
    if isinstance(pattern, Mapping):
        if all(str(user.login).lower() in pattern or str(user.user_id) in pattern for user in roster):
            return [
                pattern.get(str(user.login).lower(), pattern.get(str(user.user_id)))
                for user in roster
            ]
        # A mapping with no user keys is accepted as a one-user pattern only when
        # the roster itself has one member; otherwise ambiguity would be silent.
        if len(roster) == 1:
            return [pattern]
        raise ValueError("A mapping pattern must be keyed by each roster login or user_id")

    values = list(pattern)
    if len(values) != len(roster):
        raise ValueError(f"Expected {len(roster)} ballot rows, received {len(values)}")
    return values


def inject_ranking_ballots(
    db: Session,
    meeting_id: str,
    activity_id: str,
    pattern: Sequence[Any] | Mapping[str, Any],
) -> ActivityBundle:
    """Finalize one rank activity with anonymous cohort ballots.

    ``pattern`` is ordered like the meeting roster (sorted by login), unless it
    is a mapping keyed by those logins/user ids.  Each row is either a mapping
    from stable item keys to integer ranks, or a list/tuple of item keys in
    preferred-to-least-preferred order.  The six-row ``DEMO_BALLOT_PATTERN``
    constant is a ready-made pattern for the staged meeting.

    If the activity already has an output bundle, that bundle is returned rather
    than adding a duplicate.  This makes the helper safe to call from a live
    walkthrough or a re-run of the seed script.
    """

    activity = (
        db.query(AgendaActivity)
        .filter(
            AgendaActivity.meeting_id == meeting_id,
            AgendaActivity.activity_id == activity_id,
        )
        .one_or_none()
    )
    if activity is None:
        raise ValueError(f"Rank activity not found: {meeting_id}/{activity_id}")
    if activity.tool_type != "rank_order_voting":
        raise ValueError(f"Activity {activity_id} is not rank_order_voting")

    existing = _latest_bundle(db, meeting_id, activity_id, "output")
    if existing is not None:
        return existing

    meeting = (
        db.query(Meeting)
        .options(joinedload(Meeting.participants), joinedload(Meeting.agenda_activities))
        .filter(Meeting.meeting_id == meeting_id)
        .one()
    )
    roster = sorted(
        list(meeting.participants or []),
        key=lambda user: (str(user.login or "").lower(), str(user.user_id)),
    )
    if not roster:
        raise ValueError("The meeting has no participant roster")

    source_items = _activity_items(db, meeting, activity)
    if not source_items:
        raise ValueError(f"No rankable items found for activity {activity_id}")

    item_by_key: dict[str, dict[str, Any]] = {}
    item_by_option_id: dict[str, str] = {}
    item_keys: list[str] = []
    for index, raw_item in enumerate(source_items):
        key = _item_key(raw_item, index)
        if not key or key in item_by_key:
            raise ValueError(f"Rank activity has duplicate/blank item key: {key!r}")
        item = dict(raw_item)
        item_by_key[key] = item
        item_keys.append(key)
        rank_meta = item.get("metadata", {}).get("rank_order_voting", {})
        if isinstance(rank_meta, Mapping) and rank_meta.get("option_id"):
            item_by_option_id[str(rank_meta["option_id"])] = key

    ballot_rows = _normalise_pattern_for_roster(pattern, roster)
    resolved_ballots: list[dict[str, int]] = []
    expected_ranks = set(range(1, len(item_keys) + 1))
    for row_index, raw_ballot in enumerate(ballot_rows, start=1):
        if isinstance(raw_ballot, Mapping):
            rank_map: dict[str, int] = {}
            for raw_key, raw_rank in raw_ballot.items():
                key_text = str(raw_key).strip()
                key = key_text if key_text in item_by_key else item_by_option_id.get(key_text)
                if key is None and ":" in key_text:
                    suffix = key_text.rsplit(":", 1)[-1]
                    key = suffix if suffix in item_by_key else None
                if key is None:
                    raise ValueError(f"Unknown item key {raw_key!r} in ballot {row_index}")
                try:
                    rank_map[key] = int(raw_rank)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid rank {raw_rank!r} in ballot {row_index}") from exc
        elif isinstance(raw_ballot, Sequence) and not isinstance(raw_ballot, (str, bytes)):
            rank_map = {}
            for rank, raw_key in enumerate(raw_ballot, start=1):
                key_text = str(raw_key).strip()
                key = key_text if key_text in item_by_key else item_by_option_id.get(key_text)
                if key is None and ":" in key_text:
                    suffix = key_text.rsplit(":", 1)[-1]
                    key = suffix if suffix in item_by_key else None
                if key is None:
                    raise ValueError(f"Unknown item key {raw_key!r} in ballot {row_index}")
                rank_map[key] = rank
        else:
            raise ValueError(f"Ballot {row_index} must be a mapping or rank-order list")

        if set(rank_map) != set(item_keys) or set(rank_map.values()) != expected_ranks:
            raise ValueError(
                f"Ballot {row_index} must rank every item exactly once using 1..{len(item_keys)}"
            )
        resolved_ballots.append(rank_map)

    option_ids = {key: f"{activity_id}:{key}" for key in item_keys}
    averages = {
        key: sum(ballot[key] for ballot in resolved_ballots) / len(resolved_ballots)
        for key in item_keys
    }
    display_order = sorted(item_keys, key=lambda key: (averages[key], key))
    output_items: list[dict[str, Any]] = []
    for group_rank, key in enumerate(display_order, start=1):
        payload = deepcopy(item_by_key[key])
        metadata = dict(payload.get("metadata") or {})
        metadata["stable_key"] = key
        rank_metadata = dict(metadata.get("rank_order_voting") or {})
        rank_metadata.update({"option_id": option_ids[key], "rank": group_rank})
        metadata["rank_order_voting"] = rank_metadata
        payload["metadata"] = metadata
        source = dict(payload.get("source") or {})
        source.update({"meeting_id": meeting_id, "activity_id": activity_id})
        payload["source"] = source
        payload["activity_id"] = activity_id
        output_items.append(payload)

    votes = [
        {
            "user_id": user.user_id,
            "option_id": option_ids[key],
            "rank_position": ballot[key],
        }
        for user, ballot in zip(roster, resolved_ballots)
        for key in item_keys
    ]
    logical_step_id, round_index = _iteration_metadata(activity)
    return ActivityBundleManager(db).finalize_output_bundle(
        meeting_id,
        activity_id,
        output_items,
        metadata={
            "source": "rank_order_voting",
            "seeded": True,
            "votes": votes,
        },
        logical_step_id=logical_step_id,
        round_index=round_index,
    )


def _ensure_admin(db: Session) -> User:
    manager = UserManager()
    manager.set_db(db)
    admin = manager.get_user_by_login("admin")
    if admin is not None:
        role = str(getattr(admin.role, "value", admin.role)).lower()
        if role not in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value, UserRole.FACILITATOR.value}:
            raise RuntimeError("The existing admin login is not a facilitator-capable account")
        return admin

    return manager.add_user(
        first_name="Admin",
        last_name="User",
        email="admin@decidero.local",
        hashed_password=get_password_hash(DEMO_PARTICIPANT_PASSWORD),
        role=UserRole.ADMIN.value,
        login="admin",
        organization="Decidero Admin",
    )


def _ensure_participants(db: Session) -> list[User]:
    manager = UserManager()
    manager.set_db(db)
    participants: list[User] = []
    for login, first_name, last_name in DEMO_PARTICIPANTS:
        user = manager.get_user_by_login(login)
        if user is None:
            email = f"{login}@decidero.local"
            by_email = manager.get_user_by_email(email)
            if by_email is not None:
                raise RuntimeError(
                    f"Email {email} already belongs to a different login; refusing to duplicate it"
                )
            user = manager.add_user(
                first_name=first_name,
                last_name=last_name,
                email=email,
                hashed_password=get_password_hash(DEMO_PARTICIPANT_PASSWORD),
                role=UserRole.PARTICIPANT.value,
                login=login,
                organization=DEMO_ORGANIZATION,
            )
        else:
            role = str(getattr(user.role, "value", user.role)).lower()
            if role != UserRole.PARTICIPANT.value:
                user.role = UserRole.PARTICIPANT.value
                db.add(user)
                db.commit()
                db.refresh(user)
        participants.append(user)
    if len(participants) != len(DEMO_PARTICIPANTS):
        raise RuntimeError("The demo participant roster could not be created")
    return participants


def _ensure_brainstorm_ideas(db: Session, meeting: Meeting) -> int:
    """Populate the Round 1 brainstorming activity with anonymous idea rows.

    The opening brainstorm is seeded as an output bundle for the engine, but the
    brainstorming *view* renders live Idea rows.  Without these the "Generate
    Items" step shows an empty list on camera.  Idempotent: if the activity
    already has ideas, nothing is added.  Rows are anonymous, matching how a real
    Delphi generation round records ideas (user_id null, name "Anonymous").
    """

    brainstorm = next(
        (
            activity
            for activity in sorted(
                meeting.agenda_activities or [], key=lambda row: row.order_index
            )
            if activity.tool_type == "brainstorming"
            and not (activity.config or {}).get("seed_from_input")
        ),
        None,
    )
    if brainstorm is None:
        return 0

    ideas_manager = IdeasManager()
    existing = ideas_manager.get_ideas_for_activity(
        db, meeting.meeting_id, brainstorm.activity_id
    )
    if existing:
        return len(existing)

    created = 0
    for item in DEMO_ITEMS:
        idea = ideas_manager.add_idea(
            db,
            meeting.meeting_id,
            None,
            {"content": item["content"], "metadata": {"stable_key": item["key"]}},
            activity_id=brainstorm.activity_id,
            force_anonymous_name=True,
            commit=False,
        )
        if idea is not None:
            created += 1
    db.commit()
    return created


def _reset_demo_records(db: Session) -> None:
    """Remove prior demo meetings and demo_p* users, including non-FK bundles."""

    demo_meeting_ids = [
        meeting_id
        for (meeting_id,) in db.query(Meeting.meeting_id)
        .filter(Meeting.title == DEMO_TITLE)
        .all()
    ]
    if demo_meeting_ids:
        db.execute(participants_table.delete().where(participants_table.c.meeting_id.in_(demo_meeting_ids)))
        for model in (
            ActivityBundle,
            BrainstormingIdempotencyKey,
            CategorizationAssignment,
            CategorizationAuditEvent,
            CategorizationBallot,
            CategorizationBucket,
            CategorizationFinalAssignment,
            CategorizationItem,
            Idea,
            OutlierRationale,
            RankOrderVote,
            VotingVote,
            AgendaActivity,
            Agenda,
            ToolConfig,
        ):
            db.query(model).filter(model.meeting_id.in_(demo_meeting_ids)).delete(
                synchronize_session=False
            )
        db.query(Meeting).filter(Meeting.meeting_id.in_(demo_meeting_ids)).delete(
            synchronize_session=False
        )

    demo_users = (
        db.query(User)
        .filter(func.lower(User.login).like("demo_p%"))
        .all()
    )
    demo_user_ids = [user.user_id for user in demo_users]
    if demo_user_ids:
        db.execute(participants_table.delete().where(participants_table.c.user_id.in_(demo_user_ids)))
        for model in (
            BrainstormingIdempotencyKey,
            CategorizationBallot,
            OutlierRationale,
            RankOrderVote,
            VotingVote,
        ):
            db.query(model).filter(model.user_id.in_(demo_user_ids)).delete(
                synchronize_session=False
            )
        db.query(CategorizationBucket).filter(CategorizationBucket.created_by.in_(demo_user_ids)).update(
            {CategorizationBucket.created_by: None}, synchronize_session=False
        )
        db.query(CategorizationAssignment).filter(CategorizationAssignment.assigned_by.in_(demo_user_ids)).update(
            {CategorizationAssignment.assigned_by: None}, synchronize_session=False
        )
        db.query(CategorizationFinalAssignment).filter(
            CategorizationFinalAssignment.resolved_by.in_(demo_user_ids)
        ).update({CategorizationFinalAssignment.resolved_by: None}, synchronize_session=False)
        db.query(CategorizationAuditEvent).filter(
            CategorizationAuditEvent.actor_user_id.in_(demo_user_ids)
        ).update({CategorizationAuditEvent.actor_user_id: None}, synchronize_session=False)
        db.query(Idea).filter(Idea.user_id.in_(demo_user_ids)).update(
            {Idea.user_id: None}, synchronize_session=False
        )
        db.query(User).filter(User.user_id.in_(demo_user_ids)).delete(synchronize_session=False)

    db.commit()


def _find_rank_activity(meeting: Meeting, round_index: int = 0) -> AgendaActivity | None:
    for activity in sorted(meeting.agenda_activities or [], key=lambda row: row.order_index):
        if activity.tool_type != "rank_order_voting":
            continue
        _, activity_round = _iteration_metadata(activity)
        if activity_round == round_index:
            return activity
    return None


def seed_demo(db: Session, *, reset: bool = False) -> tuple[Meeting, AgendaActivity]:
    """Create or reuse the fully staged demo and return meeting/rank activity."""

    if reset:
        _reset_demo_records(db)

    admin = _ensure_admin(db)
    participants = _ensure_participants(db)
    [template] = seed_builtin_meeting_templates(db)
    meeting = (
        db.query(Meeting)
        .options(joinedload(Meeting.participants), joinedload(Meeting.agenda_activities))
        .filter(Meeting.title == DEMO_TITLE)
        .order_by(Meeting.created_at.desc(), Meeting.meeting_id.desc())
        .first()
    )

    if meeting is None:
        meeting = MeetingTemplateManager(db).create_meeting_from_template(
            template_id=template.template_id,
            facilitator_id=admin.user_id,
            meeting_data=MeetingCreate(
                title=DEMO_TITLE,
                description=DEMO_DESCRIPTION,
                duration_minutes=90,
                publicity=PublicityType.PRIVATE,
                owner_id=admin.user_id,
                participant_ids=[user.user_id for user in participants],
            ),
        )
        meeting.status = "active"
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        brainstorm = sorted(meeting.agenda_activities, key=lambda row: row.order_index)[0]
        ActivityBundleManager(db).finalize_output_bundle(
            meeting.meeting_id,
            brainstorm.activity_id,
            [
                {
                    "content": item["content"],
                    "metadata": {"stable_key": item["key"]},
                    "source": {
                        "meeting_id": meeting.meeting_id,
                        "activity_id": brainstorm.activity_id,
                    },
                }
                for item in DEMO_ITEMS
            ],
            metadata={
                "source": "brainstorming",
                "seeded": True,
                "decision_question": DEMO_DESCRIPTION.removeprefix("Decision question: ").strip(),
            },
        )

    # Reconcile the roster only for this deliberately named demo meeting.  This
    # makes a partially-created first run recoverable without touching other data.
    meeting.participants = list(participants)
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    _ensure_brainstorm_ideas(db, meeting)

    rank_activity = _find_rank_activity(meeting, round_index=0)
    if rank_activity is None:
        strategy = get_agenda_strategy(meeting)
        rank_activity = strategy.create_activity(
            meeting,
            payload=None,
            manager=MeetingManager(db),
        )
        db.refresh(meeting)

    if _latest_bundle(db, meeting.meeting_id, rank_activity.activity_id, "output") is None:
        inject_ranking_ballots(
            db,
            meeting.meeting_id,
            rank_activity.activity_id,
            DEMO_BALLOT_PATTERN,
        )

    # Keep the operator-facing meeting active, but do not resurrect a demo that
    # an operator has already completed when a safe default re-run is requested.
    if meeting.status not in {"completed", "archived"}:
        meeting.status = "active"
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
    return meeting, rank_activity


def _print_seed_summary(db: Session, meeting: Meeting, rank_activity: AgendaActivity) -> None:
    brainstorm = next(
        (
            activity
            for activity in meeting.agenda_activities
            if activity.tool_type == "brainstorming"
            and not (activity.config or {}).get("seed_from_input")
        ),
        None,
    )
    idea_count = 0
    if brainstorm is not None:
        opening = _latest_bundle(db, meeting.meeting_id, brainstorm.activity_id, "output")
        idea_count = len(opening.items or []) if opening is not None else 0
    ranking = _latest_bundle(db, meeting.meeting_id, rank_activity.activity_id, "output")
    votes = len((ranking.bundle_metadata or {}).get("votes") or []) if ranking else 0
    print(f"Demo meeting: {meeting.meeting_id} | {meeting.title}")
    print(f"Status: {meeting.status} | participants: {len(meeting.participants)}")
    print(f"Round 1 ideas: {idea_count} | Round 1 ballots: {votes}")
    print(f"Next advance: in-round statistical feedback for {rank_activity.activity_id}")


def _inject_round_from_cli(db: Session, activity_id: str) -> None:
    activity = (
        db.query(AgendaActivity)
        .options(joinedload(AgendaActivity.meeting))
        .filter(AgendaActivity.activity_id == activity_id)
        .one_or_none()
    )
    if activity is None:
        raise RuntimeError(f"Activity not found: {activity_id}")
    meeting = activity.meeting
    if meeting is None:
        raise RuntimeError(f"Meeting not found for activity: {activity_id}")
    bundle = inject_ranking_ballots(db, meeting.meeting_id, activity_id, DEMO_BALLOT_PATTERN)
    print(
        f"Injected/reused {len((bundle.bundle_metadata or {}).get('votes') or [])} ballots "
        f"for {meeting.meeting_id}/{activity_id} (round {bundle.round_index})."
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="remove the prior demo meeting and demo_p* users before recreating them",
    )
    parser.add_argument(
        "--inject-round",
        metavar="ACTIVITY_ID",
        help="inject the reusable demo pattern into an existing rank activity",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Match the application's startup behavior when the script is run without a
    # server.  Existing databases are unchanged by create_all/ensure_sqlite_schema.
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_schema(engine)
    db = SessionLocal()
    try:
        if args.inject_round:
            _inject_round_from_cli(db, args.inject_round)
            return 0
        meeting, rank_activity = seed_demo(db, reset=args.reset)
        _print_seed_summary(db, meeting, rank_activity)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
