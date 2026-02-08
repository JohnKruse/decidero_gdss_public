"""One-off migration helper to convert integer user IDs to string user_id values.

This script rebuilds the impacted tables (`users`, `meetings`, `participants`,
`meeting_facilitators`, `ideas`) inside the target SQLite database so that the
schema matches the new SQLAlchemy models that rely on string based identifiers.

Usage:
    python scripts/migrate_user_ids.py --database ./decidero.db

The script is intentionally idempotent; if it detects the new `user_id` column
already exists it will abort without making further changes.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models.idea import Idea
from app.models.meeting import Meeting, MeetingFacilitator, participants_table
from app.models.user import User
from app.utils.identifiers import build_user_id_prefix, generate_meeting_id, generate_facilitator_id
from app.data.user_manager import get_initials, generate_svg, get_color


logger = logging.getLogger("migration")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


TABLES_TO_REBUILD: Tuple[str, ...] = (
    "users",
    "meetings",
    "participants",
    "meeting_facilitators",
    "ideas",
)


def _column_names(session: Session, table_name: str) -> Iterable[str]:
    rows = session.execute(text(f"PRAGMA table_info({table_name})")).mappings()
    return [row["name"] for row in rows]


def _ensure_ready(engine: Engine) -> None:
    with engine.connect() as conn:
        existing_tables = {row["name"] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        missing = set(TABLES_TO_REBUILD).difference(existing_tables)
        if missing:
            raise RuntimeError(
                "Cannot run migration because the following tables are missing in the target database: "
                + ", ".join(sorted(missing))
            )


def _already_migrated(session: Session) -> bool:
    columns = set(_column_names(session, "users"))
    return "user_id" in columns


def _rename_tables(session: Session) -> None:
    for table in TABLES_TO_REBUILD:
        session.execute(text(f"ALTER TABLE {table} RENAME TO {table}__legacy"))


def _create_new_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)


def _normalize_timestamp(value: Optional[object]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _build_user_mapping(session: Session) -> Dict[int, str]:
    legacy_rows = session.execute(
        text(
            "SELECT id, first_name, last_name, email, login, hashed_password, "
            "is_active, role, password_changed, profile_svg, about_me "
            "FROM users__legacy ORDER BY id"
        )
    ).mappings()

    prefix_counters: Dict[str, int] = defaultdict(int)
    mapping: Dict[int, str] = {}

    insert_stmt = text(
        """
        INSERT INTO users (
            user_id,
            legacy_user_id,
            email,
            first_name,
            last_name,
            login,
            hashed_password,
            is_active,
            role,
            password_changed,
            profile_svg,
            about_me
        )
        VALUES (
            :user_id,
            :legacy_user_id,
            :email,
            :first_name,
            :last_name,
            :login,
            :hashed_password,
            :is_active,
            :role,
            :password_changed,
            :profile_svg,
            :about_me
        )
        """
    )

    for row in legacy_rows:
        legacy_id = row["id"]
        prefix = build_user_id_prefix(row["first_name"], row["last_name"])
        prefix_counters[prefix] += 1
        user_id = f"{prefix}-{prefix_counters[prefix]:03d}"
        mapping[legacy_id] = user_id

        initials = get_initials(row["first_name"], row["last_name"])
        svg = row["profile_svg"] or generate_svg(initials, get_color(user_id))

        session.execute(
            insert_stmt,
            {
                "user_id": user_id,
                "legacy_user_id": legacy_id,
                "email": row["email"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "login": row["login"],
                "hashed_password": row["hashed_password"],
                "is_active": row["is_active"],
                "role": row["role"],
                "password_changed": row["password_changed"],
                "profile_svg": svg,
                "about_me": row["about_me"],
            },
        )

    logger.info("Assigned new user_id values for %d user(s).", len(mapping))
    return mapping


def _copy_meetings(session: Session, mapping: Dict[int, str]) -> Tuple[Dict[int, str], Dict[str, str]]:
    legacy_rows = session.execute(
        text(
            "SELECT id, title, description, created_at, started_at, end_time, updated_at, status, is_public, facilitator_id "
            "FROM meetings__legacy ORDER BY id"
        )
    )
    insert_stmt = text(
        """
        INSERT INTO meetings (
            meeting_id,
            legacy_meeting_id,
            title,
            description,
            created_at,
            started_at,
            end_time,
            updated_at,
            status,
            is_public,
            owner_id
        )
        VALUES (
            :meeting_id,
            :legacy_meeting_id,
            :title,
            :description,
            :created_at,
            :started_at,
            :end_time,
            :updated_at,
            :status,
            :is_public,
            :owner_id
        )
        """
    )

    meeting_mapping: Dict[int, str] = {}
    owner_lookup: Dict[str, str] = {}
    migrated = 0

    for row in legacy_rows.mappings():
        owner_id = mapping.get(row["facilitator_id"])
        if not owner_id:
            logger.warning(
                "Skipping legacy meeting %s because facilitator_id %s was not migrated.",
                row["id"],
                row["facilitator_id"],
            )
            continue

        created_at = _normalize_timestamp(row.get("created_at"))
        started_at = _normalize_timestamp(row.get("started_at"))
        end_time = _normalize_timestamp(row.get("end_time"))
        updated_at = _normalize_timestamp(row.get("updated_at"))

        meeting_id = generate_meeting_id(session, created_at or started_at or datetime.now(timezone.utc))

        session.execute(
            insert_stmt,
            {
                "meeting_id": meeting_id,
                "legacy_meeting_id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "created_at": created_at,
                "started_at": started_at,
                "end_time": end_time,
                "updated_at": updated_at,
                "status": row.get("status"),
                "is_public": row.get("is_public"),
                "owner_id": owner_id,
            },
        )

        meeting_mapping[row["id"]] = meeting_id
        owner_lookup[meeting_id] = owner_id
        migrated += 1

    logger.info("Migrated %d meeting record(s).", migrated)
    return meeting_mapping, owner_lookup


def _copy_participants(
    session: Session,
    user_mapping: Dict[int, str],
    meeting_mapping: Dict[int, str],
) -> None:
    legacy_rows = session.execute(
        text("SELECT user_id, meeting_id, joined_at FROM participants__legacy")
    )
    payload = []
    for row in legacy_rows.mappings():
        user_id = user_mapping.get(row["user_id"])
        meeting_id = meeting_mapping.get(row["meeting_id"])
        if not user_id or not meeting_id:
            continue
        payload.append(
            {
                "user_id": user_id,
                "meeting_id": meeting_id,
                "joined_at": row.get("joined_at"),
            }
        )
    if payload:
        session.execute(participants_table.insert(), payload)
    logger.info("Migrated %d participant assignment(s).", len(payload))


def _copy_meeting_facilitators(
    session: Session,
    user_mapping: Dict[int, str],
    meeting_mapping: Dict[int, str],
    owner_lookup: Dict[str, str],
) -> None:
    legacy_rows = session.execute(
        text("SELECT meeting_id, user_id FROM meeting_facilitators__legacy")
    )
    assignments = set()
    created = 0

    for row in legacy_rows.mappings():
        meeting_id = meeting_mapping.get(row["meeting_id"])
        user_id = user_mapping.get(row["user_id"])
        if not meeting_id or not user_id:
            continue
        key = (meeting_id, user_id)
        if key in assignments:
            continue
        user = session.get(User, user_id)
        if user is None:
            logger.warning(
                "Skipping facilitator link for legacy meeting %s; user %s not found.",
                row["meeting_id"],
                row["user_id"],
            )
            continue
        facilitator = MeetingFacilitator(
            facilitator_id=generate_facilitator_id(session, user.first_name, user.last_name),
            meeting_id=meeting_id,
            user_id=user_id,
            is_owner=owner_lookup.get(meeting_id) == user_id,
        )
        facilitator.user = user
        session.add(facilitator)
        assignments.add(key)
        created += 1

    for meeting_id, owner_id in owner_lookup.items():
        key = (meeting_id, owner_id)
        if key in assignments:
            continue
        owner = session.get(User, owner_id)
        if owner is None:
            continue
        facilitator = MeetingFacilitator(
            facilitator_id=generate_facilitator_id(
                session, owner.first_name, owner.last_name
            ),
            meeting_id=meeting_id,
            user_id=owner_id,
            is_owner=True,
        )
        facilitator.user = owner
        session.add(facilitator)
        assignments.add(key)
        created += 1

    if created:
        session.flush()
    logger.info("Migrated %d facilitator assignment(s).", created)


def _copy_ideas(
    session: Session,
    mapping: Dict[int, str],
    meeting_mapping: Dict[int, str],
) -> None:
    legacy_rows = session.execute(
        text(
            "SELECT id, content, timestamp, updated_at, meeting_id, user_id "
            "FROM ideas__legacy"
        )
    )
    insert_stmt = text(
        """
        INSERT INTO ideas (
            id,
            content,
            timestamp,
            updated_at,
            meeting_id,
            user_id
        )
        VALUES (
            :id,
            :content,
            :timestamp,
            :updated_at,
            :meeting_id,
            :user_id
        )
        """
    )

    migrated = 0
    for row in legacy_rows.mappings():
        user_id = mapping.get(row["user_id"])
        meeting_id = meeting_mapping.get(row["meeting_id"])
        if not user_id or not meeting_id:
            continue
        session.execute(
            insert_stmt,
            {
                "id": row["id"],
                "content": row["content"],
                "timestamp": row.get("timestamp"),
                "updated_at": row.get("updated_at"),
                "meeting_id": meeting_id,
                "user_id": user_id,
            },
        )
        migrated += 1

    logger.info("Migrated %d idea record(s).", migrated)


def _reset_sequences(session: Session) -> None:
    tables_with_auto_ids = ("ideas",)
    for table in tables_with_auto_ids:
        max_id_result = session.execute(text(f"SELECT MAX(id) AS max_id FROM {table}"))
        max_id = max_id_result.scalar()
        if max_id is not None:
            session.execute(
                text("UPDATE sqlite_sequence SET seq = :seq WHERE name = :name"),
                {"seq": max_id, "name": table},
            )


def _cleanup(session: Session) -> None:
    for table in TABLES_TO_REBUILD:
        session.execute(text(f"DROP TABLE IF EXISTS {table}__legacy"))


def migrate(database_path: Path) -> None:
    engine = create_engine(f"sqlite:///{database_path}")
    _ensure_ready(engine)

    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        if _already_migrated(session):
            logger.info("Database already contains user_id column; skipping migration.")
            return

    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
    try:
        with SessionLocal() as session:
            _rename_tables(session)
            session.commit()

        Base.metadata.create_all(bind=engine)

        with SessionLocal() as session:
            user_mapping = _build_user_mapping(session)
            meeting_mapping, owner_lookup = _copy_meetings(session, user_mapping)
            _copy_participants(session, user_mapping, meeting_mapping)
            _copy_meeting_facilitators(session, user_mapping, meeting_mapping, owner_lookup)
            _copy_ideas(session, user_mapping, meeting_mapping)
            _reset_sequences(session)
            _cleanup(session)
            session.commit()
    finally:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))

    logger.info("Migration completed successfully for %s", database_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate integer user IDs to string user_id values.")
    parser.add_argument(
        "--database",
        default="./decidero.db",
        type=Path,
        help="Path to the SQLite database file (default: ./decidero.db)",
    )
    args = parser.parse_args()

    if not args.database.exists():
        parser.error(f"Database file '{args.database}' does not exist.")

    try:
        migrate(args.database)
    except (SQLAlchemyError, RuntimeError) as exc:
        logger.error("Migration failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
