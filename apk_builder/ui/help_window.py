"""How to Use window: the built-in index (U22).

An index on the left, the entry on the right. Plain words, no jargon,
nothing selected until the user picks an entry (U6). Every entry says
what to do and what happens next.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .helpers import make_top_level

WINDOW_WIDTH = 760
WINDOW_HEIGHT = 520

ENTRIES: list[tuple[str, str]] = [
    ("Start here",
     "Simple APK turns Android app source into an installable app "
     "file, called an APK.\n\n"
     "There are three steps, top to bottom on the main window:\n\n"
     "1. Pick your app: choose a zip file or a folder with the app source.\n"
     "2. Build it: press Build and wait. The first build takes a few minutes.\n"
     "3. Done: your APK is in the output folder. Open Folder shows it.\n\n"
     "That is the whole app. Everything else lives in the menus."),
    ("Pick your app",
     "Press Pick a zip file or Pick a folder.\n\n"
     "A zip file is unpacked into a work folder first. The original zip "
     "is never changed. A folder is used as it is, and the build writes "
     "its outputs into it, which is how Android builds normally work.\n\n"
     "The app checks the pick right away. A real Android project has a "
     "settings file and an app build file. If something is missing, the "
     "window says so in plain words and the Build button stays off.\n\n"
     "If the zip holds files that could not be read, they are listed "
     "under step 1 with the reason. Nothing is ever skipped quietly."),
    ("Build it",
     "Press Build. The build runs in the background, so the app stays "
     "usable while it works. The status line says what is happening, "
     "and the Build Log window shows the build's own words as they come.\n\n"
     "Press Cancel to stop a build. A cancelled build leaves nothing "
     "half made.\n\n"
     "The first build on a PC downloads the build engine, so it takes "
     "longer than later builds. Later builds reuse it."),
    ("Your finished app",
     "When the build finishes, the APK is copied to the output folder "
     "(Simple APK in your home folder, unless you changed it in "
     "Settings). Step 3 shows its name and size, and its app name and "
     "version when they can be read.\n\n"
     "Open Folder opens the output folder so you can copy the APK to "
     "your phone or share it.\n\n"
     "If a file with the same name is already there, the new one gets a "
     "number added to its name. Old files are never overwritten."),
    ("First-time setup",
     "The first build needs Java and the Android build tools on this "
     "PC. Open Windows, then First-Time Setup.\n\n"
     "The window shows what is ready and what is missing. Install Java "
     "first when it asks: it uses the system package manager and asks "
     "for your password once.\n\n"
     "Then press Set up the build tools. It downloads the tools (about "
     "150 MB), unpacks them, accepts the licenses, and installs the "
     "platform. If the download is interrupted, it picks up where it "
     "left off next time.\n\n"
     "You only do this once. After that, builds just work."),
    ("The build log",
     "Open Windows, then Build Log to watch a build's own words as they "
     "come. You do not need to read it.\n\n"
     "If a build fails, the last lines of the log say why. Copy log "
     "copies the whole log so you can share it when asking for help."),
    ("If a build fails",
     "First, read the message on the main window: it says what happened "
     "in plain words.\n\n"
     "Common causes:\n\n"
     "The project is missing its build starter. Ask whoever made the "
     "project to include the wrapper files.\n\n"
     "The build tools are not set up yet. Open First-Time Setup.\n\n"
     "The internet dropped during the first build. Try again: the "
     "downloaded pieces are kept.\n\n"
     "The project itself has an error. The Build Log shows the build's "
     "own error lines at the end."),
    ("Updates",
     "The app checks for a newer version when it starts, at most once a "
     "day. Up to date means nothing happens.\n\n"
     "When a newer version is out, the app asks once. Saying yes "
     "downloads it, checks it against its checksum, and installs it. "
     "Afterwards it asks whether to restart now or later.\n\n"
     "You can also check by hand: Help, then Check for Updates. Turn "
     "the startup check off in Settings if you prefer."),
    ("Where files live",
     "Finished APKs: the output folder (Simple APK in your home "
     "folder, unless you changed it in Settings).\n\n"
     "Unpacked zips: the work folder inside the app's data folder. "
     "File, then Clear Work Files removes them. Your original zips and "
     "folders are never touched.\n\n"
     "Settings: the settings file in your config folder. Logs: the "
     "logs folder in your data folder. Both are reachable from "
     "Settings."),
]


class HelpWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        make_top_level(self)
        self.setWindowTitle("How to Use")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.index = QListWidget()
        for title, _body in ENTRIES:
            self.index.addItem(title)
        self.index.setFixedWidth(180)
        self.index.currentRowChanged.connect(self._show_entry)
        row.addWidget(self.index)
        self.body = QTextEdit()
        self.body.setReadOnly(True)
        self.body.setText(
            "Pick an entry on the left to read how that part works.")
        row.addWidget(self.body, 1)
        layout.addLayout(row, 1)

    def _show_entry(self, row: int) -> None:
        if 0 <= row < len(ENTRIES):
            title, body = ENTRIES[row]
            self.body.setPlainText(title + "\n\n" + body)
            self.body.verticalScrollBar().setValue(0)

    def show_entry(self, title: str) -> None:
        """Open the window on one entry by title."""
        for index, (entry_title, _body) in enumerate(ENTRIES):
            if entry_title == title:
                self.index.setCurrentRow(index)
                break
