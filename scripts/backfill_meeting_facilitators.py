#!/usr/bin/env python3
"""Backfill facilitator roster entries for meetings using the new identifier scheme.

The modern schema stores facilitator assignments in the `meeting_facilitators`
table keyed by human-readable `facilitator_id` values. Older databases may only
have the legacy `meeting.facilitator_id` foreign key or an unmapped
`meeting.facilitators` relationship. This script makes sure every meeting has an
explicit facilitator roster entry for each facilitator, promoting the owner to
`is_owner=True` and generating the new `FAC-...` identifiers when missing.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

# Ensure the project package is importable when the script is executed directly.
if __name__ == "__main__" and __package__ is None:
    sys.path.append(".")

from app.database import SessionLocal, engine  # noqa: E402
from app.models.meeting import Meeting, MeetingFacilitator, meeting_facilitators_table  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.identifiers import generate_facilitator_id  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("meeting_facilitators_backfill")


@contextmanager
def managed_session() -> Session:
    """Yield a DB session that automatically rolls back on failure."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_join_table() -> None:
    """Create the meeting_facilitators table if it does not already exist."""
    inspector = inspect(engine)
    if inspector.has_table(meeting_facilitators_table.name):
        logger.info("Join table '%s' already present.", meeting_facilitators_table.name)
        return

    logger.info("Creating join table '%s'.", meeting_facilitators_table.name)
    meeting_facilitators_table.create(bind=engine, checkfirst=True)
    logger.info("Join table '%s' created successfully.", meeting_facilitators_table.name)


def _ensure_assignment(
    session: Session,
    meeting: Meeting,
    user: User,
    is_owner: bool,
    existing_assignments: dict[str, MeetingFacilitator],
) -> bool:
    """Create or update the facilitator roster entry for the provided user."""
    assignment = existing_assignments.get(user.user_id)
    if assignment:
        if assignment.is_owner != is_owner:
            assignment.is_owner = is_owner
            logger.debug(
                "Updated facilitator assignment %s for meeting %s (is_owner=%s).",
                assignment.facilitator_id,
                meeting.meeting_id,
                is_owner,
            )
            return True
        return False

    roster_id = generate_facilitator_id(session, user.first_name, user.last_name)
    new_assignment = MeetingFacilitator(
        facilitator_id=roster_id,
        meeting_id=meeting.meeting_id,
        user_id=user.user_id,
        is_owner=is_owner,
    )
    new_assignment.user = user
    meeting.facilitator_links.append(new_assignment)
    existing_assignments[user.user_id] = new_assignment
    logger.debug(
        "Created facilitator assignment %s for meeting %s (owner=%s).",
        roster_id,
        meeting.meeting_id,
        is_owner,
    )
    return True


def backfill_facilitator_roster(session: Session) -> None:
    """Ensure every facilitator (owner and co-facilitators) has a roster entry."""
    meetings = (
        session.query(Meeting)
        .options(
            joinedload(Meeting.owner),
            joinedload(Meeting.facilitator_links).joinedload(MeetingFacilitator.user),
            joinedload(Meeting.facilitators),
        )
        .all()
    )
    logger.info("Backfilling facilitator roster for %d meeting(s).", len(meetings))

    created_or_updated = 0
    skipped = 0

    for meeting in meetings:
        if not meeting.meeting_id:
            logger.warning("Meeting without meeting_id encountered; skipping legacy row.")
            skipped += 1
            continue

        owner_id = getattr(meeting, "owner_id", None)
        if not owner_id:
            logger.warning("Meeting %s has no owner_id; skipping.", meeting.meeting_id)
            skipped += 1
            continue

        owner: User | None = getattr(meeting, "owner", None)
        if owner is None:
            owner = session.get(User, owner_id)
        if owner is None:
            logger.warning(
                "Owner with user_id=%s not found for meeting %s; skipping.",
                owner_id,
                meeting.meeting_id,
            )
            skipped += 1
            continue

        assignments_by_user = {
            link.user_id: link for link in meeting.facilitator_links if link.user_id
        }

        if _ensure_assignment(session, meeting, owner, True, assignments_by_user):
            created_or_updated += 1

        for facilitator in meeting.facilitators or ():
            if facilitator.user_id == owner.user_id:
                continue
            if _ensure_assignment(session, meeting, facilitator, False, assignments_by_user):
                created_or_updated += 1

    if created_or_updated:
        session.flush()

    logger.info(
        "Backfill completed. %d facilitator assignment(s) created or updated; %d meeting(s) skipped.",
        created_or_updated,
        skipped,
    )


def main() -> None:
    logger.info("Starting meeting facilitator backfill.")
    ensure_join_table()

    try:
        with managed_session() as session:
            backfill_facilitator_roster(session)
    except SQLAlchemyError as exc:
        logger.error("Backfill failed due to database error: %s", exc)
        raise SystemExit(1) from exc

    logger.info("Meeting facilitator backfill finished successfully.")


if __name__ == "__main__":
    main()
