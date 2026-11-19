"""Entry point wiring for Simple APK.

Logging (U12), settings, single instance (U27: re-clicking the icon
focuses the running app through a local socket), global exception
handler with a friendly dialog, one silent update check per launch
after the window shows, shutdown save.
"""
from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from .core.errors import describe as describe_error
from .core.logutil import setup_logging
from .core.settings import SettingsManager
from .core.updates import REPO
from .ui.main_window import MainWindow
from .ui.theme import stylesheet

log = logging.getLogger("apk_builder")

APP_NAME = "Simple APK"
ORG_NAME = "Broke n Bored"
SINGLE_INSTANCE_KEY = "simple-apk-single-instance"


def _install_exception_handler(app: QApplication) -> None:
    """Friendly dialog for unexpected errors; the user's files are
    never at risk (a build writes only into the project and the
    output folder)."""

    def handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.error(
            "Unexpected error:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        try:
            QMessageBox.warning(
                None,
                APP_NAME,
                "Something unexpected went wrong, but your files are safe.\n\n"
                + describe_error(exc_value)
                + "\n\nTechnical details were saved to the log "
                  "(Settings: Open Logs).",
            )
        except Exception:
            pass

    sys.excepthook = handle


def _focus_running_instance() -> bool:
    """True when another copy is already running (and was asked to
    come forward)."""
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if not socket.waitForConnected(1000):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


class _SingleInstanceServer(QLocalServer):
    """Listens for a second launch and brings the window forward."""

    def __init__(self, window: MainWindow):
        super().__init__(window)
        self._window = window
        self.newConnection.connect(self._on_connection)
        # A stale socket from a crashed run must not block a fresh start.
        QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
        self.listen(SINGLE_INSTANCE_KEY)

    def _on_connection(self) -> None:
        client = self.nextPendingConnection()
        if client is not None:
            client.disconnectFromServer()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()


def main(argv=None) -> int:
    setup_logging()
    log.info("Application startup")
    if not REPO:
        log.info("Update repo is not set up yet; update checks are skipped.")

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setStyleSheet(stylesheet())
    _install_exception_handler(app)

    if _focus_running_instance():
        log.info("Another copy is already running; asked it to come forward.")
        return 0

    settings_manager = SettingsManager()
    window = MainWindow(settings_manager)
    server = _SingleInstanceServer(window)
    window.show()
    log.info("Main window shown")
    # One quiet update check per launch, after the window is up (gated
    # on the setting and the 24-hour interval; see
    # MainWindow.start_silent_update_check).
    QTimer.singleShot(1000, window.start_silent_update_check)

    try:
        return app.exec()
    finally:
        log.info("Application exit")
        try:
            server.close()
        except Exception as exc:
            log.warning("Error closing the single-instance server: %s", exc)
        try:
            settings_manager.save()
        except Exception as exc:
            log.warning("Error saving settings: %s", exc)


if __name__ == "__main__":
    sys.exit(main())
