"""Shared UI helpers for Simple APK: the status light, folder opening,
and small plain-words dialogs. No em-dashes in visible text (U33), no
bare "&" in visible labels (U11)."""
from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QWidget,
)

from ..core.errors import format_bytes  # noqa: F401  (re-exported)
from .theme import ACCENT, ERROR, MUTE, SUCCESS


class StatusDot(QWidget):
    """A small coloured light (U16: always show what it is doing). The
    colour is never the only signal: the status line next to it always
    says the same thing in words (colour is never meaning alone)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = MUTE
        self.setFixedSize(14, 14)

    def set_state(self, state: str) -> None:
        """idle, working, good, or bad."""
        self._color = {
            "idle": MUTE,
            "working": ACCENT,
            "good": SUCCESS,
            "bad": ERROR,
        }.get(state, MUTE)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(self._color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 12, 12)


class StatusLine(QWidget):
    """Status light plus status text, one row, used at the bottom of
    the main window and the setup window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.dot = StatusDot()
        self.label = QLabel("Ready.")
        self.label.setWordWrap(True)
        layout.addWidget(self.dot)
        layout.addWidget(self.label, 1)

    def set_status(self, text: str, state: str = "idle") -> None:
        self.dot.set_state(state)
        self.label.setText(text)


def open_folder(path: str) -> bool:
    """Open a folder in the file manager. True when it launched."""
    if not os.path.isdir(path):
        return False
    try:
        subprocess.Popen(["xdg-open", path],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def confirm_destructive(parent, title: str, text: str) -> bool:
    """A destructive-action confirm that defaults to No (U23, U31).
    Returns True only when the user picks Yes."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning)
    yes = box.addButton("Yes", QMessageBox.ButtonRole.YesRole)
    no = box.addButton("No", QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(no)
    box.setEscapeButton(no)
    box.exec()
    return box.clickedButton() is yes


def show_info(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def show_warning(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)
