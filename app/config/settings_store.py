"""
Runtime settings store backed by the ``app_settings`` database table.

The lookup chain for every setting is:
    DB override  →  config.yaml value  →  hardcoded default

Sensitive values (keys in ``_SENSITIVE_KEYS``) are Fernet-encrypted before
they are written to the database.  A per-deployment symmetric key is stored
in ``data/.settings_key``; it is auto-generated on first use.

Public API
----------
get_setting(key)                   → Optional[Any]   (single key, DB-only)
get_all_settings()                 → Dict[str, Any]  (all DB rows, decrypted)
save_setting(key, value, user_id)  → None            (upsert single key)
save_settings_bulk(updates, uid)   → None            (upsert many, one txn)
delete_setting(key)                → None            (remove DB override)

All values are JSON-encoded internally.  Callers always work with native
Python types (str, int, float, bool, …).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Encryption ──────────────────────────────────────────────────────────────

#: Keys whose values are encrypted in DB storage.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {"ai.api_key", "meetings.default_user_password"}
)

_ENC_PREFIX = "enc:"
_KEY_FILE = Path("data/.settings_key")
_fernet_lock = threading.Lock()
_fernet_instance = None  # type: ignore[assignment]  # lazy


def _get_fernet():
    """Return (or lazily create) the per-deployment Fernet instance."""
    global _fernet_instance  # noqa: PLW0603
    with _fernet_lock:
        if _fernet_instance is not None:
            return _fernet_instance
        try:
            from cryptography.fernet import Fernet  # local import keeps top-level lean

            if _KEY_FILE.exists():
                key = _KEY_FILE.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
                _KEY_FILE.write_bytes(key)
                logger.info("Generated new settings encryption key at %s", _KEY_FILE)
            _fernet_instance = Fernet(key)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Could not initialise settings encryption: %s — sensitive values "
                "will be stored unencrypted as a fallback.",
                exc,
            )
            _fernet_instance = None
    return _fernet_instance


def _encrypt(plaintext: str) -> str:
    f = _get_fernet()
    if f is None:
        return plaintext  # fallback: store plain (logged above)
    return _ENC_PREFIX + f.encrypt(plaintext.encode()).decode()


def _decrypt(stored: str) -> str:
    if not stored.startswith(_ENC_PREFIX):
        return stored
    f = _get_fernet()
    if f is None:
        logger.warning("Cannot decrypt setting — encryption not initialised.")
        return ""
    try:
        return f.decrypt(stored[len(_ENC_PREFIX):].encode()).decode()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to decrypt setting value: %s", exc)
        return ""


# ── Database session (lazy import to avoid circular: database→loader→store) ──

def _get_session():
    from app.database import SessionLocal  # noqa: PLC0415

    return SessionLocal()


def _get_model():
    from app.models.app_setting import AppSetting  # noqa: PLC0415

    return AppSetting


# ── Public read API ──────────────────────────────────────────────────────────

def get_setting(key: str) -> Optional[Any]:
    """Return the decoded DB value for *key*, or ``None`` if not overridden."""
    db = _get_session()
    try:
        AppSetting = _get_model()
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row is None:
            return None
        raw = row.value
        if key in SENSITIVE_KEYS:
            raw = _decrypt(raw)
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("settings_store.get_setting(%r) failed: %s", key, exc)
        return None
    finally:
        db.close()


def get_all_settings() -> Dict[str, Any]:
    """Return **all** DB settings as ``{key: decoded_value}``.

    Sensitive values are decrypted before being returned.
    """
    db = _get_session()
    try:
        AppSetting = _get_model()
        rows = db.query(AppSetting).all()
        result: Dict[str, Any] = {}
        for row in rows:
            raw = row.value
            if row.key in SENSITIVE_KEYS:
                raw = _decrypt(raw)
            try:
                result[row.key] = json.loads(raw)
            except json.JSONDecodeError:
                result[row.key] = raw
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("settings_store.get_all_settings() failed: %s", exc)
        return {}
    finally:
        db.close()


def has_setting(key: str) -> bool:
    """Return True if *key* has a DB override."""
    db = _get_session()
    try:
        AppSetting = _get_model()
        return db.query(AppSetting).filter(AppSetting.key == key).count() > 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        db.close()


# ── Public write API ─────────────────────────────────────────────────────────

def save_setting(key: str, value: Any, user_id: str) -> None:
    """Upsert a single setting.  Sensitive keys are encrypted before storage."""
    db = _get_session()
    try:
        AppSetting = _get_model()
        encoded = json.dumps(value)
        if key in SENSITIVE_KEYS:
            encoded = _encrypt(encoded)
        now = datetime.now(timezone.utc)
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row is None:
            row = AppSetting(key=key, value=encoded, updated_by=user_id, updated_at=now)
            db.add(row)
        else:
            row.value = encoded
            row.updated_by = user_id
            row.updated_at = now
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("settings_store.save_setting(%r) failed: %s", key, exc)
        raise
    finally:
        db.close()


def save_settings_bulk(updates: Dict[str, Any], user_id: str) -> None:
    """Upsert multiple settings in a single DB transaction."""
    if not updates:
        return
    db = _get_session()
    try:
        AppSetting = _get_model()
        now = datetime.now(timezone.utc)
        for key, value in updates.items():
            encoded = json.dumps(value)
            if key in SENSITIVE_KEYS:
                encoded = _encrypt(encoded)
            row = db.query(AppSetting).filter(AppSetting.key == key).first()
            if row is None:
                row = AppSetting(key=key, value=encoded, updated_by=user_id, updated_at=now)
                db.add(row)
            else:
                row.value = encoded
                row.updated_by = user_id
                row.updated_at = now
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("settings_store.save_settings_bulk() failed: %s", exc)
        raise
    finally:
        db.close()


def delete_setting(key: str) -> None:
    """Remove a DB override, causing the setting to revert to its config.yaml / hardcoded default."""
    db = _get_session()
    try:
        AppSetting = _get_model()
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            db.delete(row)
            db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("settings_store.delete_setting(%r) failed: %s", key, exc)
        raise
    finally:
        db.close()


def delete_settings_bulk(keys: list[str]) -> None:
    """Remove multiple DB overrides in a single transaction."""
    if not keys:
        return
    db = _get_session()
    try:
        AppSetting = _get_model()
        db.query(AppSetting).filter(AppSetting.key.in_(keys)).delete(
            synchronize_session="fetch"
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("settings_store.delete_settings_bulk() failed: %s", exc)
        raise
    finally:
        db.close()
