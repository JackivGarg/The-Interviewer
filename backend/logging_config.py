"""
Centralized logging configuration for The Interviewer backend.

Sets up:
  - Console handler (colored, human-readable) for terminal
  - File handler (rotating, detailed) saved to backend/logs/
  - Module-specific log levels

Import this at the TOP of main.py before anything else:
    from backend.logging_config import setup_logging
    setup_logging()
"""

import os
import logging
import logging.handlers
from datetime import datetime

# Log directory — backend/logs/
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logging(level: str = "DEBUG"):
    """
    Configure root logger with console + rotating file handlers.
    Call this ONCE at startup, before any other imports that use logging.
    """
    root_logger = logging.getLogger()

    # Prevent duplicate handler attachment on reload
    if root_logger.handlers:
        return

    root_logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    # ── Console handler ──────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-7s │ %(name)-30s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    console.setFormatter(console_fmt)
    root_logger.addHandler(console)

    # ── File handler (rotating, 5MB per file, keep 5 backups) ────────────
    log_file = os.path.join(LOG_DIR, "interviewer.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-7s │ %(name)-35s │ %(funcName)-25s │ L%(lineno)-4d │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # ── Quiet down noisy third-party loggers ─────────────────────────────
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # ── Startup banner ───────────────────────────────────────────────────
    banner_logger = logging.getLogger("interviewer.startup")
    banner_logger.info("=" * 70)
    banner_logger.info("  THE INTERVIEWER — Backend Starting")
    banner_logger.info(f"  Log file: {log_file}")
    banner_logger.info(f"  Log level: {level.upper()}")
    banner_logger.info(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    banner_logger.info("=" * 70)
