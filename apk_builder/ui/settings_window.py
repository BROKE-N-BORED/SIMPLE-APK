"""Settings window: only the settings a user would ever change.

One function, one window (U1). Every field explains itself in plain
words directly underneath it (U20). Things the backend works out for
itself (Gradle memory, worker count, auto-detected paths) do not
appear here at all (U36).
"""
from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.logutil import build_debug_report, default_logs_dir
from .helpers import open_folder, show_info

log = logging.getLogger("apk_builder")

WINDOW_WIDTH = 620
WINDOW_HEIGHT = 520


class SettingsWindow(QWidget):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self._settings_manager = settings_manager
        self.setWindowTitle("Settings")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        layout = QVBoxLayout(self)
        title = QLabel("Settings")
        title.setObjectName("title")
        layout.addWidget(title)

        layout.addWidget(QLabel("Where finished apps go"))
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setText(settings_manager.current.output_folder)
        row.addWidget(self.output_edit, 1)
        browse_output = QPushButton("Browse")
        browse_output.clicked.connect(self._browse_output)
        row.addWidget(browse_output)
        layout.addLayout(row)
        note = QLabel(
            "Finished APK files are copied here after a build. The "
            "folder is made for you if it does not exist yet.")
        note.setObjectName("small")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addWidget(QLabel("Android build tools folder"))
        sdk_row = QHBoxLayout()
        self.sdk_edit = QLineEdit()
        self.sdk_edit.setText(settings_manager.current.sdk_folder)
        self.sdk_edit.setPlaceholderText("Find it automatically")
        sdk_row.addWidget(self.sdk_edit, 1)
        browse_sdk = QPushButton("Browse")
        browse_sdk.clicked.connect(self._browse_sdk)
        sdk_row.addWidget(browse_sdk)
        auto_sdk = QPushButton("Auto")
        auto_sdk.clicked.connect(lambda: self.sdk_edit.setText(""))
        sdk_row.addWidget(auto_sdk)
        layout.addLayout(sdk_row)
        sdk_note = QLabel(
            "Leave this empty and the app finds the build tools on its "
            "own. Only set it when the tools live somewhere unusual.")
        sdk_note.setObjectName("small")
        sdk_note.setWordWrap(True)
        layout.addWidget(sdk_note)

        self.updates_check = QCheckBox("Check for updates when the app starts")
        self.updates_check.setChecked(
            settings_manager.current.check_updates_on_startup)
        layout.addWidget(self.updates_check)
        updates_note = QLabel(
            "Checked at most once a day. Up to date means nothing "
            "happens. A newer version asks once, and only downloads "
            "when you say yes.")
        updates_note.setObjectName("small")
        updates_note.setWordWrap(True)
        layout.addWidget(updates_note)

        tools = QHBoxLayout()
        logs_button = QPushButton("Open Logs")
        logs_button.clicked.connect(self._open_logs)
        tools.addWidget(logs_button)
        report_button = QPushButton("Copy Debug Report")
        report_button.clicked.connect(self._copy_report)
        tools.addWidget(report_button)
        tools.addStretch(1)
        layout.addLayout(tools)
        tools_note = QLabel(
            "The debug report holds the version and the recent log, with "
            "personal paths removed. Copy it when reporting a problem.")
        tools_note.setObjectName("small")
        tools_note.setWordWrap(True)
        layout.addWidget(tools_note)

        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Save")
        save_button.setObjectName("primary")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose where finished apps go",
            self.output_edit.text() or os.path.expanduser("~"))
        if folder:
            self.output_edit.setText(folder)

    def _browse_sdk(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the Android build tools folder",
            self.sdk_edit.text() or os.path.expanduser("~"))
        if folder:
            self.sdk_edit.setText(folder)

    def _open_logs(self) -> None:
        folder = default_logs_dir()
        os.makedirs(folder, exist_ok=True)
        if not open_folder(folder):
            show_info(self, "Logs", f"The logs live at:\n{folder}")

    def _copy_report(self) -> None:
        report = build_debug_report(__version__)
        QApplication.clipboard().setText(report)
        show_info(self, "Debug Report", "The debug report is copied.")

    def _save(self) -> None:
        settings = self._settings_manager.current
        settings.output_folder = self.output_edit.text().strip() \
            or settings.output_folder
        settings.sdk_folder = self.sdk_edit.text().strip()
        settings.check_updates_on_startup = self.updates_check.isChecked()
        self._settings_manager.save()
        log.info("Settings saved")
        self.close()
