"""Plain-language error messages for Simple APK.

Technical detail goes to the log; this is what the user sees. No
em-dashes in user-visible strings (U33), no bare "&" in visible labels
(U11). Every message says what happened and what to do next (U29).
"""
from __future__ import annotations

import errno
import zipfile


class BuildError(Exception):
    """A build step failed. The message is already plain language."""


class ProjectError(Exception):
    """The picked zip or folder is not a usable Android project."""


class EnvironmentError(Exception):
    """The build tools are missing or unusable."""


class SetupCancelled(Exception):
    """The user cancelled a download or setup step."""


def format_bytes(count: int) -> str:
    """Human-readable byte count."""
    if count < 1024:
        return f"{count} B"
    value = float(count)
    units = ("KB", "MB", "GB", "TB")
    unit = -1
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    if value >= 100:
        return f"{value:.0f} {units[unit]}"
    return f"{value:.1f} {units[unit]}"


def format_seconds(seconds: float) -> str:
    """Human-readable elapsed time: 45s, 1m 23s, 12m 04s."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    return f"{minutes}m {secs:02d}s"


def is_disk_full(exc: Exception) -> bool:
    """True when the exception means a drive ran out of space."""
    return isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT)


def describe(exc: Exception) -> str:
    """Translate an exception into a message a normal person can act on."""
    if isinstance(exc, (BuildError, ProjectError, EnvironmentError,
                        SetupCancelled)):
        # Already plain language; pass them through.
        return str(exc)
    if isinstance(exc, zipfile.BadZipFile):
        return ("That file is not a zip file, or the zip file is damaged. "
                "Pick a different file.")
    if isinstance(exc, PermissionError):
        return ("The app was not allowed to read or write there. "
                "Pick a different file or folder.")
    if isinstance(exc, FileNotFoundError):
        return ("That file or folder is no longer there. "
                "Pick it again.")
    if is_disk_full(exc):
        return ("The drive is full. Free up some space and try again.")
    if isinstance(exc, TimeoutError):
        return ("That took too long and timed out. Check the internet "
                "connection and try again.")
    # Never leak the raw exception text (U29): it is jargon to a user.
    # A raw "I/O operation on closed file" reached a status line on
    # 2026-11-18. The workers log the technical detail before calling
    # this, so nothing is lost.
    return ("Something went wrong. Try again. If it keeps happening, "
            "the details are in the log (Settings, Open Logs).")
