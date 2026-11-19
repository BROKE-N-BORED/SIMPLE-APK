"""Logging setup for Simple APK (U12 debug log layer).

Ports the BNB S61 + T21 shape: rotating timestamped file logs under the
XDG logs dir, a last-200 ring buffer kept in memory, traceback capture
through the standard logging calls, and a scrubbed debug report the user
can copy from the Help menu. Logging must never crash or slow the app,
so setup failures fall back to a plain stderr handler and are swallowed.
"""
from __future__ import annotations

import collections
import logging
import os
import re
import traceback
from logging.handlers import RotatingFileHandler

LOGGER_NAME = "apk_builder"
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 2  # app.log + app.log.1 + app.log.2
RING_SIZE = 200

_ring: collections.deque = collections.deque(maxlen=RING_SIZE)


class _RingHandler(logging.Handler):
    """Keeps the last 200 formatted log lines in memory."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _ring.append(self.format(record))
        except Exception:
            pass


def ring_lines() -> list[str]:
    """A copy of the last-200 ring buffer, oldest first."""
    return list(_ring)


def default_logs_dir() -> str:
    """~/.local/share/simple-apk/logs (honours XDG_DATA_HOME)."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(data_home, "simple-apk", "logs")


def setup_logging(logs_dir: str | None = None) -> logging.Logger:
    """Configure the "apk_builder" logger; returns it.

    Idempotent: calling it again returns the same logger without adding
    duplicate handlers. Never raises.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler: logging.Handler
    try:
        folder = logs_dir or default_logs_dir()
        os.makedirs(folder, exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(folder, "app.log"),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except Exception:
        # A full or read-only disk must not take the app down.
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    ring = _RingHandler()
    ring.setFormatter(formatter)
    logger.addHandler(ring)
    return logger


def log_exception(
    logger: logging.Logger, message: str, exc: Exception | None = None
) -> None:
    """Log a warning with the exception type and message attached."""
    if exc is None:
        logger.warning(message)
    else:
        logger.warning("%s | %s: %s", message, type(exc).__name__, exc)


def log_traceback(logger: logging.Logger, message: str) -> None:
    """Log the current exception with its full traceback."""
    logger.error("%s\n%s", message, traceback.format_exc())


_HOME_RE = re.compile(re.escape(os.path.expanduser("~")))
_TOKEN_RE = re.compile(r"(?i)(token|secret|password|key)\s*[:=]\s*\S+")


def scrub_text(text: str) -> str:
    """Scrub a report string: home dir becomes ~, anything that looks
    like a credential value is replaced. No secrets ever leave in a
    debug report."""
    scrubbed = _HOME_RE.sub("~", text)
    scrubbed = _TOKEN_RE.sub(r"\1: [removed]", scrubbed)
    return scrubbed


def build_debug_report(version: str) -> str:
    """The scrubbed debug report: version, platform, and the last-200
    ring buffer. Safe to paste anywhere."""
    import platform
    import sys

    lines = [
        f"Simple APK {version} debug report",
        f"Python {sys.version.split()[0]} on {platform.system()} "
        f"{platform.release()} ({platform.machine()})",
        "",
        "Recent log (newest last):",
    ]
    lines.extend(ring_lines() or ["(no log lines yet)"])
    return scrub_text("\n".join(lines) + "\n")
