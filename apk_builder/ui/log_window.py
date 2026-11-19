"""Build Log window: the build's own words, as they happen.

One function, one window (U1). The main window stays calm and quiet
while the log lives here for anyone who wants to watch. The log shows
real lines and real elapsed time (U37), never a fake progress bar.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import format_seconds
from .helpers import make_top_level
from .theme import FONT_LOG

WINDOW_WIDTH = 760
WINDOW_HEIGHT = 480


class LogWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        make_top_level(self)
        self.setWindowTitle("Build Log")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self._started_at: float | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "This is what the build says while it works. You do not need "
            "to read it. If a build fails, the last lines here say why.")
        intro.setWordWrap(True)
        intro.setObjectName("body")
        layout.addWidget(intro)

        self.elapsed_label = QLabel("No build running.")
        self.elapsed_label.setObjectName("small")
        layout.addWidget(self.elapsed_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(FONT_LOG)
        self.log_view.setFont(font)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view, 1)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy log")
        self.copy_button.clicked.connect(self._copy_log)
        buttons.addWidget(self.copy_button)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.log_view.clear)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def append_line(self, text: str) -> None:
        """Add one build line, keeping the view pinned to the end."""
        self.log_view.appendPlainText(text)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def build_started(self) -> None:
        self._started_at = time.monotonic()
        self.elapsed_label.setText("Build running: 0s")
        self._timer.start()

    def build_finished(self, message: str) -> None:
        self._timer.stop()
        if self._started_at is not None:
            elapsed = format_seconds(time.monotonic() - self._started_at)
            self.elapsed_label.setText(f"Build finished in {elapsed}. {message}")
        else:
            self.elapsed_label.setText(message)
        self._started_at = None

    def _tick(self) -> None:
        if self._started_at is not None:
            elapsed = format_seconds(time.monotonic() - self._started_at)
            self.elapsed_label.setText(f"Build running: {elapsed}")

    def _copy_log(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.elapsed_label.setText("Log copied.")

    def closeEvent(self, event) -> None:  # noqa: N802
        # Closing the log never stops a build; the window just hides.
        event.accept()
