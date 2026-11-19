"""Worker objects for Simple APK (U30: long work runs in worker
threads; the UI never blocks. U26: long operations show progress and
offer cancel).

Each worker is a QObject moved onto a QThread; results come back over
signals. Cancellation is a threading.Event the core functions check.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal

from ..core import build as build_core
from ..core import environment as env_core
from ..core import project as project_core
from ..core.errors import describe as describe_error

log = logging.getLogger("apk_builder")


class PrepareWorker(QObject):
    """Unpack (when the pick is a zip) and detect the project."""

    progress = Signal(int, int)  # done, total entries
    finished = Signal(object)  # PrepareResult
    failed = Signal(str)  # plain-words reason

    def __init__(self, path: str, work_root: str):
        super().__init__()
        self._path = path
        self._work_root = work_root
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            result = project_core.prepare_source(
                self._path, self._work_root,
                on_progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=self.cancel_event.is_set)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - any failure is a message
            log.warning("Prepare failed: %s: %s", type(exc).__name__, exc)
            self.failed.emit(describe_error(exc))


class BuildWorker(QObject):
    """Run the Gradle build, streaming its lines."""

    line = Signal(str)
    finished = Signal(object)  # BuildResult

    def __init__(self, project_root: str, env_status):
        super().__init__()
        self._project_root = project_root
        self._env_status = env_status
        self.cancel_event = threading.Event()

    def run(self) -> None:
        result = build_core.run_build(
            self._project_root, self._env_status,
            on_line=self.line.emit,
            should_cancel=self.cancel_event.is_set)
        self.finished.emit(result)


class EnvCheckWorker(QObject):
    """Check Java and the SDK without blocking the window."""

    finished = Signal(object)  # EnvironmentStatus

    def __init__(self, sdk_override: str | None = None):
        super().__init__()
        self._sdk_override = sdk_override

    def run(self) -> None:
        self.finished.emit(env_core.check_environment(self._sdk_override))


class SetupWorker(QObject):
    """Run the guided SDK setup: download, unpack, licenses, packages."""

    phase = Signal(str)
    download_progress = Signal(int, int)  # downloaded bytes, total or -1
    finished = Signal(str)  # sdk dir
    failed = Signal(str)  # plain-words reason

    def __init__(self, sdk_dir: str, download_dir: str):
        super().__init__()
        self._sdk_dir = sdk_dir
        self._download_dir = download_dir
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            sdk_dir = env_core.install_sdk(
                self._sdk_dir, self._download_dir,
                progress_cb=lambda done, total: self.download_progress.emit(
                    done, total if total is not None else -1),
                phase_cb=self.phase.emit,
                cancel=self.cancel_event.is_set)
            self.finished.emit(sdk_dir)
        except Exception as exc:  # noqa: BLE001 - any failure is a message
            log.warning("Setup failed: %s: %s", type(exc).__name__, exc)
            self.failed.emit(describe_error(exc))


class JavaInstallWorker(QObject):
    """Install Java through the system package manager (asks for the
    user's password with the system prompt)."""

    finished = Signal(bool)  # True when Java 17+ is usable now

    def __init__(self):
        super().__init__()
        self.cancel_event = threading.Event()

    def run(self) -> None:
        self.finished.emit(
            env_core.install_java_pkexec(cancel=self.cancel_event.is_set))
