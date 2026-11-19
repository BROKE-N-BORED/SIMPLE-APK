"""First-Time Setup window: get the build tools ready, guided.

One function, one window (U1). The window shows a short checklist of
what is ready and what is missing, in plain words, then one button
does the whole setup: download the build tools (resumable, U24),
unpack them, accept the licenses, install the platform. Progress and
cancel throughout (U26). Java is a separate guided step when it is
missing, installed through the system package manager.
"""
from __future__ import annotations

import logging
import os
import threading

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import environment as env_core
from ..core.errors import format_bytes
from .helpers import StatusLine, make_top_level
from .workers import EnvCheckWorker, JavaInstallWorker, SetupWorker

log = logging.getLogger("apk_builder")

WINDOW_WIDTH = 640
WINDOW_HEIGHT = 520


class SetupWindow(QWidget):
    """Guides the first-time setup. Emits setup_changed whenever the
    environment state changes, so the main window can re-check."""

    setup_changed = Signal()

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        make_top_level(self)
        self._settings_manager = settings_manager
        self._env_status = None
        self._thread: QThread | None = None
        self._worker = None
        self._check_thread: QThread | None = None
        self._check_worker: EnvCheckWorker | None = None
        self._java_thread: QThread | None = None
        self._java_worker: JavaInstallWorker | None = None
        self._download_total = -1

        self.setWindowTitle("First-Time Setup")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        layout = QVBoxLayout(self)
        title = QLabel("Get the build tools ready")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "The first build needs two things on this PC: Java, and the "
            "Android build tools. This window sets them up once. After "
            "that, builds just work.")
        intro.setWordWrap(True)
        intro.setObjectName("body")
        layout.addWidget(intro)

        self.java_label = QLabel("Java: checking...")
        layout.addWidget(self.java_label)
        self.java_note = QLabel("")
        self.java_note.setObjectName("small")
        self.java_note.setWordWrap(True)
        layout.addWidget(self.java_note)
        self.java_button = QPushButton("Install Java")
        self.java_button.setVisible(False)
        self.java_button.clicked.connect(self._install_java)
        layout.addWidget(self.java_button)

        self.sdk_label = QLabel("Build tools: checking...")
        layout.addWidget(self.sdk_label)
        self.sdk_note = QLabel("")
        self.sdk_note.setObjectName("small")
        self.sdk_note.setWordWrap(True)
        layout.addWidget(self.sdk_note)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("small")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        buttons = QHBoxLayout()
        self.setup_button = QPushButton("Set up the build tools")
        self.setup_button.setObjectName("primary")
        self.setup_button.clicked.connect(self._start_setup)
        buttons.addWidget(self.setup_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel_setup)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.status = StatusLine()
        layout.addWidget(self.status)
        layout.addStretch(1)

        self.refresh()

    # -- state ---------------------------------------------------------
    def refresh(self) -> None:
        """Re-check Java and the SDK in a worker thread."""
        if self._check_thread is not None and self._check_thread.isRunning():
            return
        sdk_override = self._settings_manager.current.sdk_folder or None
        self._check_thread = QThread(self)
        worker = EnvCheckWorker(sdk_override)
        # Stored, not local: a worker kept only in a local is garbage
        # collected before run() executes, and the check then never
        # finishes (proven in the GUI tests).
        self._check_worker = worker
        worker.moveToThread(self._check_thread)
        self._check_thread.started.connect(worker.run)
        worker.finished.connect(self._on_env_checked)
        worker.finished.connect(self._check_thread.quit)
        self._check_thread.start()

    def _on_env_checked(self, status) -> None:
        self._env_status = status
        if status.java_ok:
            self.java_label.setText(
                f"Java: ready (version {status.java_version}).")
            self.java_note.setText("The build tools can use this Java.")
            self.java_button.setVisible(False)
        elif status.java_path is None:
            self.java_label.setText("Java: not installed.")
            self.java_note.setText(
                "Java runs the build. Installing it asks for your "
                "password once, through the system prompt.")
            self.java_button.setVisible(True)
        else:
            self.java_label.setText(
                f"Java: version {status.java_version} is too old.")
            self.java_note.setText(
                "The build tools need Java 17 or newer. Installing it "
                "asks for your password once, through the system prompt.")
            self.java_button.setVisible(True)
        if status.sdk_ok:
            self.sdk_label.setText("Build tools: ready.")
            self.sdk_note.setText(
                f"Found at {status.sdk_dir}. Nothing left to set up.")
            self.setup_button.setVisible(False)
        else:
            self.sdk_label.setText("Build tools: not ready yet.")
            # The Java lines have their own section above; the SDK note
            # names only the SDK pieces, so nothing repeats.
            sdk_missing = [m for m in status.missing
                           if not m.startswith("Java")]
            self.sdk_note.setText(
                " ".join(sdk_missing) if sdk_missing
                else "Something is missing.")
            self.setup_button.setVisible(True)
            self.setup_button.setEnabled(status.java_ok)
        if status.ready:
            self.status.set_status("Everything is ready. You can build.", "good")
        else:
            self.status.set_status(
                "Some pieces are still missing. Follow the steps above.", "idle")
        self.setup_changed.emit()

    # -- java ----------------------------------------------------------
    def _install_java(self) -> None:
        self.java_button.setEnabled(False)
        self.status.set_status(
            "Installing Java. The system may ask for your password.", "working")
        self._java_thread = QThread(self)
        worker = JavaInstallWorker()
        self._java_worker = worker
        worker.moveToThread(self._java_thread)
        self._java_thread.started.connect(worker.run)
        worker.finished.connect(self._on_java_installed)
        worker.finished.connect(self._java_thread.quit)
        self._java_thread.start()

    def _on_java_installed(self, ok: bool) -> None:
        if ok:
            self.status.set_status("Java is installed.", "good")
        else:
            self.status.set_status(
                "Java could not be installed. Try again, or install "
                "openjdk-17-jdk with the system package manager.", "bad")
        self.java_button.setEnabled(True)
        self.refresh()

    # -- sdk setup -----------------------------------------------------
    def _start_setup(self) -> None:
        if self._env_status is None or not self._env_status.java_ok:
            self.status.set_status(
                "Java is needed first. Install Java, then set up the "
                "build tools.", "bad")
            return
        sdk_dir = self._settings_manager.current.sdk_folder \
            or env_core.default_sdk_dir()
        download_dir = os.path.join(
            os.path.dirname(sdk_dir), ".simple-apk-downloads")
        self.setup_button.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.progress.setVisible(True)
        self.progress_label.setVisible(True)
        self.progress.setRange(0, 0)  # indeterminate until size is known
        self.status.set_status("Setting up the build tools.", "working")
        self._thread = QThread(self)
        self._worker = SetupWorker(sdk_dir, download_dir)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.phase.connect(self._on_phase)
        self._worker.download_progress.connect(self._on_download_progress)
        self._worker.finished.connect(self._on_setup_finished)
        self._worker.failed.connect(self._on_setup_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _cancel_setup(self) -> None:
        if self._worker is not None:
            self._worker.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status.set_status("Cancelling. The download will resume next time.",
                               "working")

    def _on_phase(self, text: str) -> None:
        self.status.set_status(text + ".", "working")
        if text.startswith("Downloading"):
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 0)
            self.progress_label.setText(text + ".")

    def _on_download_progress(self, done: int, total: int) -> None:
        self._download_total = total
        if total and total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.progress_label.setText(
                f"Downloaded {format_bytes(done)} of {format_bytes(total)}.")
        else:
            self.progress.setRange(0, 0)
            self.progress_label.setText(
                f"Downloaded {format_bytes(done)}.")

    def _on_setup_finished(self, sdk_dir: str) -> None:
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        self.cancel_button.setVisible(False)
        self.setup_button.setEnabled(True)
        self.status.set_status("The build tools are ready.", "good")
        log.info("Setup finished: SDK at %s", sdk_dir)
        self.refresh()

    def _on_setup_failed(self, reason: str) -> None:
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        self.cancel_button.setVisible(False)
        self.setup_button.setEnabled(True)
        self.status.set_status(reason, "bad")

    def shutdown(self) -> bool:
        """Stop every worker thread. Called before the window is
        destroyed (its own close, or the app quitting): a QThread
        destroyed while still running aborts the process, so no close
        path may skip this. quit() is called directly: the
        finished-to-quit connection is queued, and a queued quit()
        cannot be delivered while this thread blocks in wait().
        Returns True when every thread stopped. Every worker here is
        cancellable, so the waits below finish promptly."""
        if self._worker is not None:
            self._worker.cancel_event.set()
        if self._java_worker is not None:
            self._java_worker.cancel_event.set()
        stopped = True
        for thread in (self._thread, self._check_thread, self._java_thread):
            if thread is not None:
                thread.quit()
                if not thread.wait(15000):
                    stopped = False
        return stopped

    def closeEvent(self, event) -> None:  # noqa: N802
        # Closing mid-setup cancels it; the download resumes next time.
        # A thread that has not stopped yet defers the close instead of
        # being destroyed mid-run.
        if not self.shutdown():
            self.hide()
            event.ignore()
            QTimer.singleShot(500, self.close)
            return
        event.accept()
