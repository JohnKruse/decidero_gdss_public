import logging
import logging.config
import os
from pathlib import Path
from typing import Iterable


def _prune_backups(log_dir: Path, base_name: str, backup_count: int) -> None:
    if backup_count < 1:
        return
    candidates: Iterable[Path] = sorted(
        log_dir.glob(f"{base_name}.*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale in list(candidates)[backup_count:]:
        try:
            stale.unlink()
        except OSError:
            continue


def setup_logging():
    """
    Configures logging for the application.
    Logs are written to 'logs/app.log' and 'logs/error.log'.
    """
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    max_bytes = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "3"))
    _prune_backups(log_dir, "app.log", backup_count)
    _prune_backups(log_dir, "error.log", backup_count)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
            "json": {
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": "INFO",
            },
            "file_app": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": "logs/app.log",
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "level": "INFO",
                "encoding": "utf8",
            },
            "file_error": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": "logs/error.log",
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "level": "ERROR",
                "encoding": "utf8",
            },
        },
        "loggers": {
            "": {  # Root logger
                "handlers": ["console", "file_app", "file_error"],
                "level": "INFO",
                "propagate": True,
            },
            "uvicorn": {
                "handlers": ["console", "file_app"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console", "file_app"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console", "file_error"],
                "level": "INFO",
                "propagate": False,
            },
            "auth_module": {
                "handlers": ["console", "file_app"],
                "level": "INFO",
                "propagate": False,
            },
            "audit": {
                "handlers": ["console", "file_app"],
                "level": "INFO",
                "propagate": False,
            },
            "fastapi": {
                "handlers": ["console", "file_app"],
                "level": "INFO",
                "propagate": False,
            },
            "app": {  # Application logger
                "handlers": ["console", "file_app", "file_error"],
                "level": "DEBUG",
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(logging_config)
    logging.info("Logging configured successfully.")
