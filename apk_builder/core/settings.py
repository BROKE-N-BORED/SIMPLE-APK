"""User settings for Simple APK.

Only settings a user would ever change for a real reason live here
(U36). Everything the backend works out for itself (Gradle memory,
worker count, Java and SDK paths when they are found automatically)
stays out of sight (U35).

- settings JSON: ~/.config/simple-apk/settings.json
- atomic save: write tmp file, then os.replace

A missing or corrupt file falls back to defaults (with a warning in the
log). `last_update_check` is bookkeeping, not a setting: it is stored
in the same file but never shown in the Settings window.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field

logger = logging.getLogger("apk_builder")


def config_dir() -> str:
    """~/.config/simple-apk (honours XDG_CONFIG_HOME)."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(config_home, "simple-apk")


def data_dir() -> str:
    """~/.local/share/simple-apk (honours XDG_DATA_HOME)."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(data_home, "simple-apk")


def work_dir() -> str:
    """Where picked zips are unpacked for building."""
    return os.path.join(data_dir(), "work")


def default_settings_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def default_output_folder() -> str:
    """~/Simple APK, where finished APKs are put."""
    return os.path.join(os.path.expanduser("~"), "Simple APK")


@dataclass
class Settings:
    output_folder: str = field(default_factory=default_output_folder)
    sdk_folder: str = ""  # Empty means find the SDK automatically.
    check_updates_on_startup: bool = True
    last_update_check: float = 0.0  # epoch seconds; bookkeeping, not shown
    window_geometry: dict | None = None  # {"x", "y", "w", "h"}

    def __post_init__(self) -> None:
        self.output_folder = (
            os.path.expanduser(self.output_folder or "")
            or default_output_folder()
        )
        self.sdk_folder = os.path.expanduser(self.sdk_folder or "")
        if self.window_geometry is not None and not isinstance(
            self.window_geometry, dict
        ):
            self.window_geometry = None


class SettingsManager:
    """Loads settings once, saves atomically on demand."""

    def __init__(self, path: str | None = None):
        self._path = path or default_settings_path()
        self.current: Settings = self._load()

    @property
    def path(self) -> str:
        return self._path

    def _load(self) -> Settings:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    known = {
                        key: value
                        for key, value in data.items()
                        if key in Settings.__dataclass_fields__
                    }
                    return Settings(**known)
        except Exception as exc:
            logger.warning(
                "Settings file could not be read; using defaults | %s: %s",
                type(exc).__name__,
                exc,
            )
        return Settings()

    def save(self) -> None:
        """Atomic save (tmp + os.replace). Failures only log a warning."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp_path = self._path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(asdict(self.current), handle, indent=2)
                handle.write("\n")
            os.replace(tmp_path, self._path)
        except Exception as exc:
            logger.warning(
                "Settings could not be saved | %s: %s", type(exc).__name__, exc
            )
