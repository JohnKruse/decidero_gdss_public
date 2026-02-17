import logging
import sqlite3
import threading
import time
from pathlib import Path
import hashlib
import json

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker
import uuid

from app.config.loader import load_config

_DEFAULT_DATABASE_URL = "sqlite:///./decidero.db"
_DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 30000
_DEFAULT_SQLITE_JOURNAL_MODE = "WAL"
_DEFAULT_SQLITE_SYNCHRONOUS = "NORMAL"
_DEFAULT_SQLITE_WRITE_RETRIES = 5
_DEFAULT_SQLITE_RETRY_BACKOFF_MS = 200
_DEFAULT_POOL_SIZE = 20
_DEFAULT_MAX_OVERFLOW = 40
_DEFAULT_POOL_TIMEOUT_SECONDS = 15
_DEFAULT_POOL_RECYCLE_SECONDS = 1800

def _get_database_url() -> str:
    config = load_config()
    url = config.get("database_url")
    return str(url) if url else _DEFAULT_DATABASE_URL


def _get_sqlite_settings() -> dict:
    config = load_config()
    sqlite_config = config.get("sqlite") or {}

    def _coerce_positive_int(value, fallback):
        try:
            candidate = int(value)
            return candidate if candidate > 0 else fallback
        except Exception:  # noqa: BLE001
            return fallback

    journal_mode = sqlite_config.get("journal_mode") or _DEFAULT_SQLITE_JOURNAL_MODE
    synchronous = sqlite_config.get("synchronous") or _DEFAULT_SQLITE_SYNCHRONOUS
    busy_timeout_ms = _coerce_positive_int(
        sqlite_config.get("busy_timeout_ms"), _DEFAULT_SQLITE_BUSY_TIMEOUT_MS
    )
    write_retries = _coerce_positive_int(
        sqlite_config.get("write_retries"), _DEFAULT_SQLITE_WRITE_RETRIES
    )
    retry_backoff_ms = _coerce_positive_int(
        sqlite_config.get("retry_backoff_ms"), _DEFAULT_SQLITE_RETRY_BACKOFF_MS
    )
    return {
        "journal_mode": str(journal_mode),
        "synchronous": str(synchronous),
        "busy_timeout_ms": busy_timeout_ms,
        "write_retries": write_retries,
        "retry_backoff_ms": retry_backoff_ms,
    }


def _get_pool_settings() -> dict:
    config = load_config()
    pool_config = config.get("database_pool") or {}

    def _coerce_positive_int(value, fallback):
        try:
            candidate = int(value)
            return candidate if candidate > 0 else fallback
        except Exception:  # noqa: BLE001
            return fallback

    return {
        "pool_size": _coerce_positive_int(
            pool_config.get("pool_size"), _DEFAULT_POOL_SIZE
        ),
        "max_overflow": _coerce_positive_int(
            pool_config.get("max_overflow"), _DEFAULT_MAX_OVERFLOW
        ),
        "pool_timeout": _coerce_positive_int(
            pool_config.get("pool_timeout_seconds"), _DEFAULT_POOL_TIMEOUT_SECONDS
        ),
        "pool_recycle": _coerce_positive_int(
            pool_config.get("pool_recycle_seconds"), _DEFAULT_POOL_RECYCLE_SECONDS
        ),
    }


def _ensure_sqlite_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return
    db_url = make_url(database_url)
    if not db_url.database or db_url.database == ":memory:":
        return
    db_path = Path(db_url.database)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


DATABASE_URL = _get_database_url()

# Get a logger instance
logger = logging.getLogger("database")

_ensure_sqlite_directory(DATABASE_URL)

connect_args = {}
_sqlite_settings = None
if DATABASE_URL.startswith("sqlite"):
    _sqlite_settings = _get_sqlite_settings()
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = max(1, _sqlite_settings["busy_timeout_ms"] / 1000)

_pool_settings = _get_pool_settings()
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_size=_pool_settings["pool_size"],
    max_overflow=_pool_settings["max_overflow"],
    pool_timeout=_pool_settings["pool_timeout"],
    pool_recycle=_pool_settings["pool_recycle"],
    pool_pre_ping=True,
    pool_use_lifo=True,
)


if DATABASE_URL.startswith("sqlite"):
    _SQLITE_WRITE_LOCK = threading.RLock()

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        if not isinstance(dbapi_connection, sqlite3.Connection):
            return
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA journal_mode={_sqlite_settings['journal_mode']}")
        cursor.execute(f"PRAGMA synchronous={_sqlite_settings['synchronous']}")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={_sqlite_settings['busy_timeout_ms']}")
        cursor.close()

    def _is_sqlite_locked_error(exc: OperationalError) -> bool:
        message = str(exc).lower()
        return "database is locked" in message or "database table is locked" in message


    class QueuedSession(Session):
        def commit(self) -> None:
            retries = max(1, _sqlite_settings["write_retries"])
            backoff = max(1, _sqlite_settings["retry_backoff_ms"]) / 1000
            with _SQLITE_WRITE_LOCK:
                for attempt in range(1, retries + 1):
                    try:
                        return super().commit()
                    except OperationalError as exc:
                        if not _is_sqlite_locked_error(exc):
                            raise
                        super().rollback()
                        if attempt >= retries:
                            raise
                        time.sleep(backoff * attempt)

        def flush(self, objects=None) -> None:
            with _SQLITE_WRITE_LOCK:
                return super().flush(objects)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=QueuedSession if DATABASE_URL.startswith("sqlite") else Session,
)

Base = declarative_base()


def _color_from_seed(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    r = 40 + (digest[0] % 176)
    g = 40 + (digest[1] % 176)
    b = 40 + (digest[2] % 176)
    return f"#{r:02X}{g:02X}{b:02X}"


def _unique_avatar_color(seed: str, used: set[str]) -> str:
    candidate = _color_from_seed(seed)
    if candidate not in used:
        return candidate
    attempt = 1
    while True:
        candidate = _color_from_seed(f"{seed}:{attempt}")
        if candidate not in used:
            return candidate
        attempt += 1


def _load_avatar_keys() -> list[str]:
    manifest_path = Path(__file__).resolve().parent / "static" / "avatars" / "fluent" / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    avatars = payload.get("avatars")
    if not isinstance(avatars, list):
        return []
    keys: list[str] = []
    for entry in avatars:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if isinstance(key, str) and key.strip():
            keys.append(key.strip())
    return keys


def _avatar_key_from_seed(user_id: str, avatar_seed: int, keys: list[str]) -> str | None:
    if not keys:
        return None
    digest = hashlib.sha256(f"{user_id}:{int(avatar_seed or 0)}".encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(keys)
    return keys[idx]


def ensure_sqlite_schema(engine_to_check) -> None:
    if not str(engine_to_check.url).startswith("sqlite"):
        return
    with engine_to_check.connect() as connection:
        try:
            result = connection.execute(text("PRAGMA table_info(ideas)"))
        except Exception:
            return
        columns = {row[1] for row in result.fetchall()}
        if "idea_metadata" not in columns and columns:
            connection.execute(
                text("ALTER TABLE ideas ADD COLUMN idea_metadata JSON NOT NULL DEFAULT '{}'")  # noqa: S608
            )
            connection.commit()
        try:
            user_columns_result = connection.execute(text("PRAGMA table_info(users)"))
            user_columns = {row[1] for row in user_columns_result.fetchall()}
            if "avatar_color" not in user_columns and user_columns:
                connection.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN avatar_color VARCHAR(7)"
                    )  # noqa: S608
                )
                connection.commit()
            if "avatar_key" not in user_columns and user_columns:
                connection.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN avatar_key VARCHAR(128)"
                    )  # noqa: S608
                )
                connection.commit()
            if "avatar_seed" not in user_columns and user_columns:
                connection.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN avatar_seed INTEGER NOT NULL DEFAULT 0"
                    )  # noqa: S608
                )
                connection.commit()

            users_result = connection.execute(
                text("SELECT user_id, avatar_color, avatar_key, avatar_seed FROM users")
            )
            rows = users_result.fetchall()
            used = {
                str(row[1]).strip().upper()
                for row in rows
                if row[1] and str(row[1]).strip()
            }
            avatar_keys = _load_avatar_keys()
            avatar_key_set = set(avatar_keys)
            for row in rows:
                user_id = row[0]
                existing_color = row[1]
                existing_avatar_key = row[2]
                avatar_seed = row[3]
                if not user_id or existing_color:
                    pass
                else:
                    color = _unique_avatar_color(str(user_id), used)
                    used.add(color)
                    connection.execute(
                        text(
                            "UPDATE users SET avatar_color = :avatar_color WHERE user_id = :user_id"
                        ),
                        {"avatar_color": color, "user_id": user_id},
                    )

                safe_seed = int(avatar_seed or 0)
                if avatar_seed is None:
                    connection.execute(
                        text(
                            "UPDATE users SET avatar_seed = :avatar_seed WHERE user_id = :user_id"
                        ),
                        {"avatar_seed": safe_seed, "user_id": user_id},
                    )

                valid_existing_key = (
                    isinstance(existing_avatar_key, str)
                    and existing_avatar_key.strip()
                    and existing_avatar_key in avatar_key_set
                )
                if not valid_existing_key:
                    resolved_key = _avatar_key_from_seed(str(user_id), safe_seed, avatar_keys)
                    connection.execute(
                        text(
                            "UPDATE users SET avatar_key = :avatar_key WHERE user_id = :user_id"
                        ),
                        {"avatar_key": resolved_key, "user_id": user_id},
                    )
            connection.commit()
        except Exception:
            # Ignore users-table migration issues to avoid blocking startup.
            pass


def get_db():
    req_id = uuid.uuid4()
    logger.debug(f"[DB_SESSION_START][{req_id}] Creating database session.")
    db = SessionLocal()
    try:
        logger.debug(f"[DB_SESSION_YIELD][{req_id}] Yielding database session.")
        yield db
    finally:
        logger.debug(f"[DB_SESSION_END][{req_id}] Closing database session.")
        db.close()
