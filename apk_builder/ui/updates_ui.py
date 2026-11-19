"""Update UI for Simple APK: check worker, apply worker, dialogs.

Follows the Android Photo Transfer port shape: QObject workers on
QThreads, results back over signals. The pull flow downloads to a temp
dir, applies by atomic swap, then asks "Restart now to complete the
update?": Yes closes the window and relaunches via the installed
launcher, No leaves the update to complete on next launch.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .. import __version__
from ..core import updates
from ..core.errors import format_bytes
from ..core.updates import UpdateCancelled, UpdateError

log = logging.getLogger("apk_builder")


class UpdateCheckWorker(QObject):
    """One update check, off the UI thread."""

    finished = Signal(dict)

    def run(self) -> None:
        self.finished.emit(updates.check_for_update(__version__))


class UpdateApplyWorker(QObject):
    """Download (verified) then apply an update."""

    progress_changed = Signal(int, int)  # downloaded, total (-1 unknown)
    phase_changed = Signal(str)
    finished = Signal(str)  # version
    failed = Signal(str)  # plain-words reason
    cancelled = Signal()

    def __init__(self, info: dict, dest_dir: str):
        super().__init__()
        self._info = info
        self._dest_dir = dest_dir
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            self.phase_changed.emit("Downloading")
            downloaded = updates.download_update(
                self._info, self._dest_dir,
                progress_cb=lambda done, total: self.progress_changed.emit(
                    done, total if total is not None else -1),
                cancel=self.cancel_event.is_set)
            if self.cancel_event.is_set():
                self.cancelled.emit()
                return
            self.phase_changed.emit("Installing")
            updates.apply_update(downloaded["zip_path"],
                                 downloaded["version"])
            self.finished.emit(downloaded["version"])
        except UpdateCancelled:
            self.cancelled.emit()
        except UpdateError as exc:
            log.warning("Update failed: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - any failure is a message
            log.warning("Update failed unexpectedly: %s: %s",
                        type(exc).__name__, exc)
            self.failed.emit(f"Something went wrong: {exc}")


class UpdateDialog(QDialog):
    """A newer version is out. Installed: Update / Later. Source run:
    Open the release page / Close. update_requested is True only when
    Update was tapped."""

    def __init__(self, info: dict, installed: bool, parent=None):
        super().__init__(parent)
        self.update_requested = False
        self._page_url = info.get("page_url") or ""
        self.setWindowTitle("Update available")
        self.setModal(True)
        layout = QVBoxLayout(self)
        latest = info.get("version") or info.get("latest") or "?"
        body = QLabel(
            f"Simple APK {latest} is out. You have {__version__}.")
        body.setWordWrap(True)
        layout.addWidget(body)
        note = QLabel(
            "Updating downloads the new version, checks it, and "
            "installs it. Your settings and logs stay put.")
        note.setWordWrap(True)
        note.setObjectName("small")
        layout.addWidget(note)
        buttons = QHBoxLayout()
        if installed:
            update_button = QPushButton("Update")
            update_button.setObjectName("primary")
            update_button.clicked.connect(self._on_update)
            buttons.addWidget(update_button)
            later_button = QPushButton("Later")
            later_button.clicked.connect(self.reject)
            buttons.addWidget(later_button)
        else:
            page_button = QPushButton("Open the release page")
            page_button.clicked.connect(self._on_open_page)
            buttons.addWidget(page_button)
            close_button = QPushButton("Close")
            close_button.clicked.connect(self.reject)
            buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _on_update(self) -> None:
        self.update_requested = True
        self.accept()

    def _on_open_page(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        if self._page_url:
            QDesktopServices.openUrl(QUrl(self._page_url))
        self.reject()


class UpdateProgressDialog(QDialog):
    """Download and install progress. Cancel works during the download;
    it is disabled once Installing starts (the swap runs to completion)."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Updating")
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        self.phase_label = QLabel("Downloading.")
        layout.addWidget(self.phase_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.bytes_label = QLabel("")
        self.bytes_label.setObjectName("small")
        layout.addWidget(self.bytes_label)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_button)

    def set_phase(self, phase: str) -> None:
        self.phase_label.setText(phase + ".")
        if phase == "Installing":
            self.cancel_button.setEnabled(False)
            self.progress.setRange(0, 0)
            self.bytes_label.setText("")

    def set_progress(self, done: int, total: int) -> None:
        if total and total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.bytes_label.setText(
                f"{format_bytes(done)} of {format_bytes(total)}.")
        else:
            self.progress.setRange(0, 0)
            self.bytes_label.setText(f"{format_bytes(done)}.")

    def _on_cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_requested.emit()
