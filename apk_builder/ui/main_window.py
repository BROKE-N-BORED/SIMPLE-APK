"""Main window: three big steps, nothing else.

1. Pick your app (a zip file or a folder).
2. Build it.
3. Done: the APK, with an Open Folder button.

Progressive disclosure (012): the main window shows only the three
steps. The log, setup, settings, and help each live in their own
window behind the menu bar (U1). Calm technology (003): one status
light plus one status line; the app never pops up to say it worked.
Delight (008): the finish moment only, a check that fades in over
200 ms when the APK is ready.

No em-dashes in visible text (U33), no bare "&" in visible labels
(U11), nothing selected by default (U6).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time

from PySide6.QtCore import (
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core import build as build_core
from ..core import project as project_core
from ..core import updates
from ..core.errors import describe as describe_error, format_bytes, format_seconds
from ..core.logutil import build_debug_report
from ..core.settings import work_dir
from .helpers import StatusLine, confirm_destructive, open_folder, show_info
from .help_window import HelpWindow
from .log_window import LogWindow
from .settings_window import SettingsWindow
from .setup_window import SetupWindow
from .theme import ACCENT
from .updates_ui import (
    UpdateApplyWorker,
    UpdateCheckWorker,
    UpdateDialog,
    UpdateProgressDialog,
)
from .workers import BuildWorker, EnvCheckWorker, PrepareWorker

log = logging.getLogger("apk_builder")

WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 680
MIN_WIDTH = 900
MIN_HEIGHT = 560
UPDATE_CHECK_INTERVAL_S = 24 * 60 * 60  # at most once a day


class MainWindow(QMainWindow):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self._settings_manager = settings_manager
        self._project = None  # ProjectInfo
        self._prepare_result = None
        self._env_status = None
        self._busy = False  # preparing or building
        self._build_started_at: float | None = None
        self._last_apks: list = []
        self._work_root = work_dir()

        # Worker threads.
        self._prepare_thread: QThread | None = None
        self._prepare_worker: PrepareWorker | None = None
        self._build_thread: QThread | None = None
        self._build_worker: BuildWorker | None = None
        self._env_thread: QThread | None = None
        self._env_worker: EnvCheckWorker | None = None

        # Update state. Only one check runs at a time (silent or manual).
        self._silent_check_started = False
        self._update_check_thread: QThread | None = None
        self._update_check_manual = False
        self._update_apply_thread: QThread | None = None
        self._update_apply_worker: UpdateApplyWorker | None = None
        self._update_progress_dialog: UpdateProgressDialog | None = None
        self._update_temp_dir: str | None = None

        # Child windows (one each, reused).
        self._log_window: LogWindow | None = None
        self._setup_window: SetupWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._help_window: HelpWindow | None = None

        self.setWindowTitle("Simple APK")
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self._restore_geometry()

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        header = QLabel("Simple APK")
        header.setObjectName("title")
        layout.addWidget(header)
        subtitle = QLabel("Turn app source into an app you can install.")
        subtitle.setObjectName("body")
        layout.addWidget(subtitle)

        self._step1_card, self._step1_body = self._build_step_card(
            "1", "Pick your app",
            "Choose a zip file or a folder with the app source.")
        layout.addWidget(self._step1_card)
        self._step2_card, self._step2_body = self._build_step_card(
            "2", "Build it",
            "Press Build and wait. The first build takes a few minutes.")
        layout.addWidget(self._step2_card)
        self._step3_card, self._step3_body = self._build_step_card(
            "3", "Done",
            "Your finished app shows up here.")
        layout.addWidget(self._step3_card)
        layout.addStretch(1)

        self.status_line = StatusLine()
        layout.addWidget(self.status_line)

        self._fill_step1()
        self._fill_step2()
        self._fill_step3()
        self._build_menu()
        self._set_active_step(1)
        self._refresh_env()

    # -- layout helpers --------------------------------------------------
    def _build_step_card(self, number: str, title: str, plain: str):
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        outer = QHBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(16)
        badge = QLabel(number)
        badge.setStyleSheet(
            f"color: {ACCENT}; font-size: 28px; font-weight: 700;")
        badge.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(badge)
        body = QVBoxLayout()
        body.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("stepTitle")
        body.addWidget(title_label)
        plain_label = QLabel(plain)
        plain_label.setObjectName("body")
        plain_label.setWordWrap(True)
        body.addWidget(plain_label)
        outer.addLayout(body, 1)
        return card, body

    def _set_card_active(self, card: QFrame, active: bool) -> None:
        card.setObjectName("cardActive" if active else "card")
        card.style().unpolish(card)
        card.style().polish(card)

    def _set_active_step(self, step: int) -> None:
        self._set_card_active(self._step1_card, step == 1)
        self._set_card_active(self._step2_card, step == 2)
        self._set_card_active(self._step3_card, step == 3)

    def _fill_step1(self) -> None:
        self.source_label = QLabel("Nothing picked yet.")
        self.source_label.setObjectName("body")
        self.source_label.setWordWrap(True)
        self._step1_body.addWidget(self.source_label)
        row = QHBoxLayout()
        self.pick_zip_button = QPushButton("Pick a zip file")
        self.pick_zip_button.clicked.connect(self._pick_zip)
        row.addWidget(self.pick_zip_button)
        self.pick_folder_button = QPushButton("Pick a folder")
        self.pick_folder_button.clicked.connect(self._pick_folder)
        row.addWidget(self.pick_folder_button)
        row.addStretch(1)
        self._step1_body.addLayout(row)
        self.issues_label = QLabel("")
        self.issues_label.setObjectName("error")
        self.issues_label.setWordWrap(True)
        self.issues_label.setVisible(False)
        self._step1_body.addWidget(self.issues_label)
        self.skipped_label = QLabel("")
        self.skipped_label.setObjectName("small")
        self.skipped_label.setWordWrap(True)
        self.skipped_label.setVisible(False)
        self._step1_body.addWidget(self.skipped_label)

    def _fill_step2(self) -> None:
        self.build_note_label = QLabel("Pick an app first.")
        self.build_note_label.setObjectName("body")
        self.build_note_label.setWordWrap(True)
        self._step2_body.addWidget(self.build_note_label)
        row = QHBoxLayout()
        self.build_button = QPushButton("Build")
        self.build_button.setObjectName("primary")
        self.build_button.setEnabled(False)
        self.build_button.clicked.connect(self._start_build)
        row.addWidget(self.build_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel_build)
        row.addWidget(self.cancel_button)
        self.setup_button = QPushButton("Open First-Time Setup")
        self.setup_button.setVisible(False)
        self.setup_button.clicked.connect(self._show_setup)
        row.addWidget(self.setup_button)
        self.log_button = QPushButton("Open Build Log")
        self.log_button.clicked.connect(self._show_log)
        row.addWidget(self.log_button)
        row.addStretch(1)
        self._step2_body.addLayout(row)
        self.build_progress = QProgressBar()
        self.build_progress.setVisible(False)
        self._step2_body.addWidget(self.build_progress)
        self.elapsed_label = QLabel("")
        self.elapsed_label.setObjectName("small")
        self.elapsed_label.setVisible(False)
        self._step2_body.addWidget(self.elapsed_label)

    def _fill_step3(self) -> None:
        row = QHBoxLayout()
        self.done_check = QLabel("")
        self.done_check.setStyleSheet(
            "color: #7fb069; font-size: 28px; font-weight: 700;")
        self._check_effect = QGraphicsOpacityEffect(self.done_check)
        self._check_effect.setOpacity(0.0)
        self.done_check.setGraphicsEffect(self._check_effect)
        row.addWidget(self.done_check)
        self.done_label = QLabel("Nothing built yet.")
        self.done_label.setObjectName("body")
        self.done_label.setWordWrap(True)
        row.addWidget(self.done_label, 1)
        self._step3_body.addLayout(row)
        buttons = QHBoxLayout()
        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        buttons.addWidget(self.open_folder_button)
        buttons.addStretch(1)
        self._step3_body.addLayout(buttons)

    # -- menu ------------------------------------------------------------
    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        pick_zip = QAction("Pick a Zip File", self)
        pick_zip.triggered.connect(self._pick_zip)
        file_menu.addAction(pick_zip)
        pick_folder = QAction("Pick a Folder", self)
        pick_folder.triggered.connect(self._pick_folder)
        file_menu.addAction(pick_folder)
        file_menu.addSeparator()
        open_output = QAction("Open Output Folder", self)
        open_output.triggered.connect(self._open_output_folder)
        file_menu.addAction(open_output)
        clear_work = QAction("Clear Work Files", self)
        clear_work.triggered.connect(self._clear_work_files)
        file_menu.addAction(clear_work)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        windows_menu = menu_bar.addMenu("Windows")
        log_action = QAction("Build Log", self)
        log_action.triggered.connect(self._show_log)
        windows_menu.addAction(log_action)
        setup_action = QAction("First-Time Setup", self)
        setup_action.triggered.connect(self._show_setup)
        windows_menu.addAction(setup_action)
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self._show_settings)
        windows_menu.addAction(settings_action)

        help_menu = menu_bar.addMenu("Help")
        howto = QAction("How to Use", self)
        howto.triggered.connect(self._show_help)
        help_menu.addAction(howto)
        check_updates = QAction("Check for Updates", self)
        check_updates.triggered.connect(lambda: self._check_updates(manual=True))
        help_menu.addAction(check_updates)
        self._updates_toggle = QAction("Check for updates on startup", self)
        self._updates_toggle.setCheckable(True)
        self._updates_toggle.triggered.connect(self._toggle_updates_setting)
        help_menu.addAction(self._updates_toggle)
        help_menu.aboutToShow.connect(self._refresh_updates_toggle)
        help_menu.addSeparator()
        report = QAction("Copy Debug Report", self)
        report.triggered.connect(self._copy_debug_report)
        help_menu.addAction(report)
        about = QAction("About Simple APK", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    def _refresh_updates_toggle(self) -> None:
        self._updates_toggle.setChecked(
            self._settings_manager.current.check_updates_on_startup)

    def _toggle_updates_setting(self) -> None:
        settings = self._settings_manager.current
        settings.check_updates_on_startup = self._updates_toggle.isChecked()
        self._settings_manager.save()

    def _copy_debug_report(self) -> None:
        QApplication.clipboard().setText(build_debug_report(__version__))
        show_info(self, "Debug Report", "The debug report is copied.")

    def _show_about(self) -> None:
        show_info(
            self, "About Simple APK",
            f"Simple APK {__version__}\n\n"
            "Turn Android app source into an installable app file.\n"
            "Pick a zip or a folder, press Build, get an APK.")

    # -- geometry (U5) ---------------------------------------------------
    def _restore_geometry(self) -> None:
        from PySide6.QtCore import QSettings

        settings = QSettings("Broke n Bored", "Simple APK")
        geometry = settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                frame = self.frameGeometry()
                if not available.intersects(frame):
                    self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
                    self.move(available.center() - self.rect().center())
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                self.move(available.center() - self.rect().center())

    def _save_geometry(self) -> None:
        from PySide6.QtCore import QSettings

        settings = QSettings("Broke n Bored", "Simple APK")
        settings.setValue("window/geometry", self.saveGeometry())

    # -- environment -----------------------------------------------------
    def _refresh_env(self) -> None:
        if self._env_thread is not None and self._env_thread.isRunning():
            return
        sdk_override = self._settings_manager.current.sdk_folder or None
        self._env_thread = QThread(self)
        worker = EnvCheckWorker(sdk_override)
        # The worker MUST stay referenced: a worker kept only in a local
        # is garbage collected before run() executes, and the check then
        # never finishes (proven in the GUI tests: the setup env check
        # timed out at 30 s while the thread idled).
        self._env_worker = worker
        worker.moveToThread(self._env_thread)
        self._env_thread.started.connect(worker.run)
        worker.finished.connect(self._on_env_checked)
        worker.finished.connect(self._env_thread.quit)
        self._env_thread.start()

    def _on_env_checked(self, status) -> None:
        self._env_status = status
        if not status.ready:
            self.setup_button.setVisible(True)
        else:
            self.setup_button.setVisible(False)
        self._update_build_state()
        if self._project is None:
            if status.ready:
                self.status_line.set_status(
                    "Ready. Pick a zip file or a folder to start.", "idle")
            else:
                self.status_line.set_status(
                    "The build tools are not ready yet. Open First-Time "
                    "Setup to get them ready.", "idle")

    # -- picking ---------------------------------------------------------
    def _pick_zip(self) -> None:
        if self._busy:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a zip file with the app source",
            os.path.expanduser("~"), "Zip files (*.zip)")
        if path:
            self.pick_source(path)

    def _pick_folder(self) -> None:
        if self._busy:
            return
        path = QFileDialog.getExistingDirectory(
            self, "Pick a folder with the app source",
            os.path.expanduser("~"))
        if path:
            self.pick_source(path)

    def pick_source(self, path: str) -> None:
        """Pick a zip or folder. This is the one entry point the file
        dialogs and the tests share, so the tested path is the real path."""
        if self._busy:
            return
        self._busy = True
        self._project = None
        self._prepare_result = None
        self._last_apks = []
        self._set_active_step(1)
        self.source_label.setText(f"Reading {os.path.basename(path)}.")
        self.issues_label.setVisible(False)
        self.skipped_label.setVisible(False)
        self.open_folder_button.setEnabled(False)
        self.done_label.setText("Nothing built yet.")
        self.done_check.setText("")
        self._check_effect.setOpacity(0.0)
        self._update_build_state()
        self.status_line.set_status("Reading your pick.", "working")
        self._prepare_thread = QThread(self)
        self._prepare_worker = PrepareWorker(path, self._work_root)
        self._prepare_worker.moveToThread(self._prepare_thread)
        self._prepare_thread.started.connect(self._prepare_worker.run)
        self._prepare_worker.finished.connect(self._on_prepare_finished)
        self._prepare_worker.failed.connect(self._on_prepare_failed)
        self._prepare_worker.finished.connect(self._prepare_thread.quit)
        self._prepare_worker.failed.connect(self._prepare_thread.quit)
        self._prepare_thread.start()

    def _on_prepare_finished(self, result) -> None:
        self._busy = False
        self._prepare_result = result
        self._project = result.project
        project = result.project
        self.source_label.setText(f"Picked: {project.source_label}")
        if project.skipped:
            shown = project.skipped[:5]
            lines = [f"{entry.name}: {entry.reason}" for entry in shown]
            if len(project.skipped) > 5:
                lines.append(
                    f"And {len(project.skipped) - 5} more. The full list "
                    "is in the log.")
            self.skipped_label.setText(
                "Some files could not be read:\n" + "\n".join(lines))
            self.skipped_label.setVisible(True)
        if project.can_build:
            self.issues_label.setVisible(False)
            self._set_active_step(2)
            self.status_line.set_status(
                "That looks like an Android app. Press Build when ready.",
                "good")
        else:
            blocker = project.build_blocker or " ".join(project.issues)
            self.issues_label.setText(blocker)
            self.issues_label.setVisible(True)
            self.status_line.set_status(
                "That pick cannot build yet. See the note under step 1.",
                "bad")
        self._update_build_state()

    def _on_prepare_failed(self, reason: str) -> None:
        self._busy = False
        self.source_label.setText("Nothing picked yet.")
        self.issues_label.setText(reason)
        self.issues_label.setVisible(True)
        self.status_line.set_status(reason, "bad")
        self._update_build_state()

    # -- build state -----------------------------------------------------
    def _update_build_state(self) -> None:
        env_ready = bool(self._env_status and self._env_status.ready)
        project_ready = bool(self._project and self._project.can_build)
        self.build_button.setEnabled(
            project_ready and env_ready and not self._busy)
        self.pick_zip_button.setEnabled(not self._busy)
        self.pick_folder_button.setEnabled(not self._busy)
        # The setup shortcut is only offered while the tools are not
        # ready; it hides the moment they are, from every path that
        # refreshes this state.
        if self._env_status is not None:
            self.setup_button.setVisible(not env_ready)
        if self._busy:
            return
        if not project_ready and self._project is not None:
            self.build_note_label.setText(
                "This pick cannot build. See the note under step 1.")
        elif not project_ready:
            self.build_note_label.setText("Pick an app first.")
        elif not env_ready:
            self.build_note_label.setText(
                "The build tools are not ready yet. Open First-Time "
                "Setup to get them ready, then come back and press Build.")
        else:
            self.build_note_label.setText("Ready.")

    # -- build -----------------------------------------------------------
    def _start_build(self) -> None:
        if self._project is None or not self._project.can_build:
            return
        if self._env_status is None or not self._env_status.ready:
            self._show_setup()
            return
        self._busy = True
        self._last_apks = []
        self._set_active_step(2)
        self._update_build_state()
        self.build_progress.setVisible(True)
        self.build_progress.setRange(0, 0)
        self.elapsed_label.setVisible(True)
        self.cancel_button.setVisible(True)
        self._build_started_at = time.monotonic()
        self.elapsed_label.setText("Build running: 0s")
        self._elapsed_timer.start()
        self.status_line.set_status("Building. This takes a few minutes.",
                                    "working")
        log_window = self._log_window_for_build()
        log_window.build_started()
        log_window.append_line(
            f"Building {self._project.source_label}.")
        self._build_thread = QThread(self)
        self._build_worker = BuildWorker(self._project.root, self._env_status)
        self._build_worker.moveToThread(self._build_thread)
        self._build_thread.started.connect(self._build_worker.run)
        self._build_worker.line.connect(self._on_build_line)
        self._build_worker.finished.connect(self._on_build_finished)
        self._build_worker.finished.connect(self._build_thread.quit)
        self._build_thread.start()

    def _log_window_for_build(self) -> LogWindow:
        if self._log_window is None:
            self._log_window = LogWindow(self)
        return self._log_window

    def _on_build_line(self, text: str) -> None:
        if self._log_window is not None:
            self._log_window.append_line(text)

    def _tick_elapsed(self) -> None:
        if self._build_started_at is not None:
            elapsed = format_seconds(time.monotonic() - self._build_started_at)
            self.elapsed_label.setText(f"Build running: {elapsed}")

    def _cancel_build(self) -> None:
        if self._build_worker is not None:
            self._build_worker.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status_line.set_status("Cancelling the build.", "working")

    def _on_build_finished(self, result) -> None:
        self._busy = False
        self._elapsed_timer.stop()
        self.build_progress.setVisible(False)
        self.elapsed_label.setVisible(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.setEnabled(True)
        if self._log_window is not None:
            self._log_window.build_finished(result.message)
        if result.cancelled:
            self.status_line.set_status(
                "The build was cancelled. Nothing was made.", "idle")
            self._update_build_state()
            return
        if not result.success:
            self.status_line.set_status(result.message, "bad")
            self._update_build_state()
            return
        if not result.apks:
            self.status_line.set_status(result.message, "bad")
            self._update_build_state()
            return
        out_dir = self._settings_manager.current.output_folder
        try:
            aapt2 = build_core.find_aapt2(
                self._env_status.sdk_dir if self._env_status else None)
            copied = build_core.copy_apks(
                [info.path for info in result.apks], out_dir, aapt2)
        except OSError as exc:
            log.warning("Could not copy APKs: %s", exc)
            self.status_line.set_status(describe_error(exc), "bad")
            self._update_build_state()
            return
        self._last_apks = copied
        first = copied[0]
        detail = f"{first.name} ({format_bytes(first.size)})"
        if first.version_name:
            detail += f", version {first.version_name}"
        if len(copied) > 1:
            detail += f" and {len(copied) - 1} more"
        self.done_label.setText(
            f"Your app is ready.\n{detail}\nSaved to {out_dir}.")
        self.open_folder_button.setEnabled(True)
        self._set_active_step(3)
        self.status_line.set_status("Your app is ready.", "good")
        self._play_finish_moment()
        self._update_build_state()

    def _play_finish_moment(self) -> None:
        """The quiet finish moment (008): a check fades in over 200 ms.
        Opacity only, no layout motion, cheap on his PC."""
        self.done_check.setText("\u2713")
        animation = QPropertyAnimation(
            self._check_effect, b"opacity", self)
        animation.setDuration(200)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # -- output folder and work files ------------------------------------
    def _open_output_folder(self) -> None:
        out_dir = self._settings_manager.current.output_folder
        os.makedirs(out_dir, exist_ok=True)
        if not open_folder(out_dir):
            show_info(self, "Output Folder",
                      f"Your finished apps live at:\n{out_dir}")

    def _clear_work_files(self) -> None:
        if self._busy:
            show_info(self, "Clear Work Files",
                      "Wait for the current job to finish first.")
            return
        if not confirm_destructive(
                self, "Clear Work Files",
                "This removes the unpacked copies of zips you picked. "
                "Your original zips and folders are not touched.\n\n"
                "Clear them?"):
            return
        removed = project_core.clear_work_folders(self._work_root)
        if removed:
            self.status_line.set_status(
                f"Cleared {removed} work folder(s).", "good")
        else:
            self.status_line.set_status(
                "There were no work files to clear.", "idle")

    # -- child windows ---------------------------------------------------
    def _show_log(self) -> None:
        if self._log_window is None:
            self._log_window = LogWindow(self)
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    def _show_setup(self) -> None:
        if self._setup_window is None:
            self._setup_window = SetupWindow(self._settings_manager, self)
            self._setup_window.setup_changed.connect(self._refresh_env)
        self._setup_window.refresh()
        self._setup_window.show()
        self._setup_window.raise_()
        self._setup_window.activateWindow()

    def _show_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                self._settings_manager, self)
        else:
            # Rebuild so it always shows the saved settings.
            self._settings_window.close()
            self._settings_window = SettingsWindow(
                self._settings_manager, self)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _show_help(self) -> None:
        if self._help_window is None:
            self._help_window = HelpWindow(self)
        self._help_window.show()
        self._help_window.raise_()
        self._help_window.activateWindow()

    # -- updates ---------------------------------------------------------
    def start_silent_update_check(self) -> None:
        """One quiet check per launch, at most once every 24 hours.
        Up to date shows nothing; a failure shows a status line at
        most, never a modal. Skipped entirely when the repo is not set
        up yet (updates.check_for_update reports unknown)."""
        if self._silent_check_started:
            return
        self._silent_check_started = True
        if not self._settings_manager.current.check_updates_on_startup:
            return
        last = self._settings_manager.current.last_update_check or 0.0
        if time.time() - last < UPDATE_CHECK_INTERVAL_S:
            return
        self._check_updates(manual=False)

    def _check_updates(self, manual: bool) -> None:
        if self._update_check_thread is not None \
                and self._update_check_thread.isRunning():
            if manual:
                show_info(self, "Check for Updates",
                          "Already checking for updates.")
            return
        self._update_check_manual = manual
        self._update_check_thread = QThread(self)
        worker = UpdateCheckWorker()
        # Stored, not local: a worker kept only in a local is garbage
        # collected before run() executes (see _refresh_env).
        self._update_check_worker = worker
        worker.moveToThread(self._update_check_thread)
        self._update_check_thread.started.connect(worker.run)
        worker.finished.connect(self._on_update_checked)
        worker.finished.connect(self._update_check_thread.quit)
        self._update_check_thread.start()

    def _on_update_checked(self, result: dict) -> None:
        settings = self._settings_manager.current
        settings.last_update_check = time.time()
        self._settings_manager.save()
        state = result.get("state")
        if state == "newer":
            dialog = UpdateDialog(result, updates.is_installed(), self)
            dialog.exec()
            if dialog.update_requested:
                self._start_apply(result)
            return
        if not self._update_check_manual:
            # Silent check: up to date or unknown stays quiet.
            if state == "unknown":
                log.info("Silent update check: %s", result.get("reason"))
            return
        if state == "current":
            show_info(self, "Check for Updates",
                      f"You have the newest version ({__version__}).")
        else:
            show_info(self, "Check for Updates",
                      result.get("reason")
                      or "The update check could not run.")

    def _start_apply(self, info: dict) -> None:
        self._update_temp_dir = tempfile.mkdtemp(prefix="simple-apk-update-")
        self._update_progress_dialog = UpdateProgressDialog(self)
        self._update_progress_dialog.cancel_requested.connect(
            self._cancel_apply)
        self._update_apply_thread = QThread(self)
        self._update_apply_worker = UpdateApplyWorker(
            info, self._update_temp_dir)
        self._update_apply_worker.moveToThread(self._update_apply_thread)
        self._update_apply_thread.started.connect(
            self._update_apply_worker.run)
        self._update_apply_worker.progress_changed.connect(
            self._update_progress_dialog.set_progress)
        self._update_apply_worker.phase_changed.connect(
            self._update_progress_dialog.set_phase)
        self._update_apply_worker.finished.connect(self._on_apply_finished)
        self._update_apply_worker.failed.connect(self._on_apply_failed)
        self._update_apply_worker.cancelled.connect(self._on_apply_cancelled)
        self._update_apply_worker.finished.connect(
            self._update_apply_thread.quit)
        self._update_apply_worker.failed.connect(
            self._update_apply_thread.quit)
        self._update_apply_worker.cancelled.connect(
            self._update_apply_thread.quit)
        self._update_apply_thread.start()
        self._update_progress_dialog.exec()

    def _cancel_apply(self) -> None:
        if self._update_apply_worker is not None:
            self._update_apply_worker.cancel_event.set()

    def _close_apply_dialog(self) -> None:
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.accept()
            self._update_progress_dialog = None
        if self._update_temp_dir is not None:
            shutil.rmtree(self._update_temp_dir, ignore_errors=True)
            self._update_temp_dir = None

    def _on_apply_finished(self, version: str) -> None:
        self._close_apply_dialog()
        answer = QMessageBox.question(
            self, "Update installed",
            f"Simple APK {version} is installed.\n\n"
            "Restart now to complete the update?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer == QMessageBox.StandardButton.Yes:
            self._restart_app()

    def _on_apply_failed(self, reason: str) -> None:
        self._close_apply_dialog()
        QMessageBox.warning(self, "Update", reason)

    def _on_apply_cancelled(self) -> None:
        self._close_apply_dialog()
        self.status_line.set_status("The update was cancelled.", "idle")

    def _restart_app(self) -> None:
        launcher = updates.launcher_path()
        try:
            subprocess.Popen([launcher], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as exc:
            log.warning("Restart launch failed: %s", exc)
            show_info(self, "Update",
                      "The update is installed. Start the app again "
                      "from the menu to use the new version.")
            return
        QApplication.instance().quit()

    # -- close -----------------------------------------------------------
    def _stop_thread(self, thread, timeout_ms=15000) -> bool:
        """Ask a worker thread to stop and wait for it. quit() is called
        directly: the finished-to-quit connection is queued, and a queued
        quit() cannot be delivered while this thread blocks in wait(),
        so relying on it deadlocks the close (proven in the GUI tests:
        every wait timed out at 15 s)."""
        if thread is None:
            return True
        thread.quit()
        return thread.wait(timeout_ms)

    def _retry_close(self) -> None:
        """Second try at closing, after the deferred close hid the
        window while a worker finished. The workers are all bounded or
        cancellable, so this converges."""
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._build_thread is not None and self._build_thread.isRunning():
            if not confirm_destructive(
                    self, "A build is running",
                    "A build is still running. Closing now stops it.\n\n"
                    "Close anyway?"):
                event.ignore()
                return
            self._cancel_build()
        if self._prepare_worker is not None:
            self._prepare_worker.cancel_event.set()
        if self._update_apply_worker is not None:
            self._update_apply_worker.cancel_event.set()
        setup_stopped = True
        if self._setup_window is not None:
            setup_stopped = self._setup_window.shutdown()
        stopped = setup_stopped
        stopped = self._stop_thread(
            self._build_thread, timeout_ms=25000) and stopped
        stopped = self._stop_thread(self._prepare_thread) and stopped
        stopped = self._stop_thread(self._env_thread) and stopped
        stopped = self._stop_thread(self._update_check_thread) and stopped
        stopped = self._stop_thread(
            self._update_apply_thread, timeout_ms=25000) and stopped
        if not stopped:
            # A QThread destroyed while still running aborts the
            # process, so the close is deferred, never forced: hide the
            # window now and try again once the worker has stopped.
            self.hide()
            event.ignore()
            QTimer.singleShot(500, self._retry_close)
            return
        self._save_geometry()
        self._settings_manager.save()
        event.accept()
