"""Qt GUI smoke tests for Simple APK, driven the way the user will
use it: pick the real NEO zip through the same code path the file
dialog feeds, watch the real states change, and look at screenshots.

Runs offscreen (QT_QPA_PLATFORM=offscreen). Screenshots land in
verify/ at the project root. Needs PySide6; skipped cleanly without it.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import zipfile

try:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from PySide6.QtCore import Qt
    HAS_QT = True
except ImportError:
    HAS_QT = False

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

NEO_ZIP = os.path.expanduser("~/workspace/NEO-source-v0.1.zip")
VERIFY_DIR = os.path.join(PROJECT_DIR, "verify")

_app = None


def setUpModule():
    global _app
    if not HAS_QT:
        raise unittest.SkipTest("PySide6 is not available")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.makedirs(VERIFY_DIR, exist_ok=True)
    _app = QApplication.instance() or QApplication(sys.argv)
    # Apply the real stylesheet, exactly as main() does: the screenshots
    # must show what the user actually sees, not the unstyled default.
    from apk_builder.ui.theme import stylesheet

    _app.setStyleSheet(stylesheet())


def tearDownModule():
    # Clean Qt teardown: destroying widgets after the QApplication is
    # gone segfaults at interpreter shutdown, so the app is quit here
    # while its objects are still alive.
    if _app is not None:
        _app.processEvents()
        _app.quit()


def _pump(seconds: float = 0.5) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.02)


def _wait_until(predicate, timeout: float = 30.0, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for: {what}")


@unittest.skipUnless(HAS_QT, "PySide6 is not available")
class GuiSmokeTests(unittest.TestCase):
    def setUp(self):
        from apk_builder.core.settings import SettingsManager
        from apk_builder.ui.main_window import MainWindow

        self._tmp = tempfile.TemporaryDirectory()
        self.settings = SettingsManager(
            os.path.join(self._tmp.name, "settings.json"))
        self.settings.current.output_folder = os.path.join(
            self._tmp.name, "out")
        self.window = MainWindow(self.settings)
        self.window._work_root = os.path.join(self._tmp.name, "work")
        self.window.resize(1100, 680)
        self.window.show()
        _pump(0.5)
        self.addCleanup(self._close_window)

    def _close_window(self):
        if self.window is not None:
            self.window.close()
            # Delete now, while the QApplication is alive: leaving the
            # window for interpreter shutdown segfaults (Qt objects
            # destroyed after the app is gone).
            self.window.deleteLater()
            self.window = None
            _pump(0.3)
        self._tmp.cleanup()

    def _shot(self, name: str) -> str:
        _pump(0.3)
        path = os.path.join(VERIFY_DIR, name)
        pixmap = self.window.grab()
        self.assertFalse(pixmap.isNull(), f"screenshot {name} is empty")
        self.assertTrue(pixmap.save(path), f"could not save {path}")
        return path

    def test_main_window_starts_empty_and_build_is_off(self):
        # U6: nothing selected by default; the Build button starts off.
        self.assertEqual(self.window.source_label.text(),
                         "Nothing picked yet.")
        self.assertFalse(self.window.build_button.isEnabled())
        self.assertEqual(self.window.windowTitle(), "Simple APK")
        shot = self._shot("main-empty.png")
        self.assertTrue(os.path.getsize(shot) > 1000)

    @unittest.skipUnless(os.path.isfile(NEO_ZIP), "NEO test zip not present")
    def test_pick_neo_zip_detects_a_buildable_project(self):
        self.window.pick_source(NEO_ZIP)
        _wait_until(lambda: not self.window._busy, what="prepare to finish")
        project = self.window._project
        self.assertIsNotNone(project)
        self.assertTrue(project.is_android_project)
        self.assertTrue(project.can_build)
        self.assertIn("NEO-source-v0.1.zip",
                      self.window.source_label.text())
        self.assertFalse(self.window.issues_label.isVisible())
        self._shot("main-picked-neo.png")

    @unittest.skipUnless(os.path.isfile(NEO_ZIP), "NEO test zip not present")
    def test_build_button_enables_when_project_and_tools_are_ready(self):
        from apk_builder.core.environment import EnvironmentStatus

        self.window.pick_source(NEO_ZIP)
        _wait_until(lambda: not self.window._busy, what="prepare to finish")
        ready = EnvironmentStatus(
            java_path="/usr/bin/java", java_version=17,
            sdk_dir="/tmp/fake-sdk", has_cmdline_tools=True,
            has_platform_tools=True, has_platform=True,
            has_build_tools=True)
        self.window._env_status = ready
        self.window._update_build_state()
        self.assertTrue(self.window.build_button.isEnabled())
        self.assertEqual("Ready.",
                         self.window.build_note_label.text())
        self._shot("main-ready-to-build.png")

    def test_full_build_flow_with_fake_gradlew(self):
        """The whole journey through the real UI: pick a project folder,
        press Build, watch step 3 show the finished APK. The project's
        gradlew is a stand-in script (no real Gradle runs in this
        sandbox, by rule), but every line of the app's own flow is the
        real one: pick, detect, build worker, copy, finish moment."""
        from apk_builder.core.environment import EnvironmentStatus

        project = os.path.join(self._tmp.name, "fakeproj")
        os.makedirs(os.path.join(project, "app"))
        with open(os.path.join(project, "settings.gradle"), "w") as fh:
            fh.write("")
        with open(os.path.join(project, "app", "build.gradle"), "w") as fh:
            fh.write("")
        gradlew = os.path.join(project, "gradlew")
        with open(gradlew, "w") as fh:
            fh.write(
                "#!/bin/sh\n"
                "echo 'Starting fake build'\n"
                "echo ':app:assembleDebug'\n"
                "mkdir -p app/build/outputs/apk/debug\n"
                "printf 'fake apk' > "
                "app/build/outputs/apk/debug/app-debug.apk\n"
                "echo 'BUILD SUCCESSFUL'\n")
        os.chmod(gradlew, 0o755)

        ready = EnvironmentStatus(
            java_path="/usr/bin/java", java_version=17,
            sdk_dir="/tmp/fake-sdk", has_cmdline_tools=True,
            has_platform_tools=True, has_platform=True,
            has_build_tools=True)
        self.window._env_status = ready

        self.window.pick_source(project)
        _wait_until(lambda: not self.window._busy, what="prepare to finish")
        self.assertTrue(self.window.build_button.isEnabled())

        self.window._start_build()
        _wait_until(lambda: not self.window._busy, what="build to finish")
        _pump(0.5)  # let the 200 ms finish fade complete
        self.assertTrue(self.window.open_folder_button.isEnabled())
        self.assertIn("Your app is ready", self.window.done_label.text())
        self.assertIn("app-debug.apk", self.window.done_label.text())
        out_dir = self.settings.current.output_folder
        self.assertTrue(os.path.isfile(
            os.path.join(out_dir, "app-debug.apk")))
        self.assertEqual(self.window.done_check.text(), "\u2713")
        self._shot("main-done.png")

    def test_bad_zip_shows_a_plain_error(self):
        bad = os.path.join(self._tmp.name, "bad.zip")
        with open(bad, "wb") as fh:
            fh.write(b"not a zip at all")
        self.window.pick_source(bad)
        _wait_until(lambda: not self.window._busy, what="prepare to finish")
        self.assertIsNone(self.window._project)
        self.assertTrue(self.window.issues_label.isVisible())
        self.assertIn("not a zip", self.window.issues_label.text())
        self.assertFalse(self.window.build_button.isEnabled())

    def test_non_android_folder_shows_plain_issues(self):
        folder = os.path.join(self._tmp.name, "notes")
        os.makedirs(folder)
        with open(os.path.join(folder, "notes.txt"), "w") as fh:
            fh.write("hello")
        self.window.pick_source(folder)
        _wait_until(lambda: not self.window._busy, what="prepare to finish")
        self.assertIsNotNone(self.window._project)
        self.assertFalse(self.window._project.can_build)
        self.assertTrue(self.window.issues_label.isVisible())
        self.assertFalse(self.window.build_button.isEnabled())

    def test_missing_wrapper_blocks_with_plain_words(self):
        folder = os.path.join(self._tmp.name, "proj")
        os.makedirs(os.path.join(folder, "app"))
        with open(os.path.join(folder, "settings.gradle"), "w") as fh:
            fh.write("")
        with open(os.path.join(folder, "app", "build.gradle"), "w") as fh:
            fh.write("")
        self.window.pick_source(folder)
        _wait_until(lambda: not self.window._busy, what="prepare to finish")
        self.assertFalse(self.window._project.can_build)
        self.assertIn("wrapper", self.window.issues_label.text())

    def test_child_windows_open(self):
        from apk_builder.ui.help_window import HelpWindow
        from apk_builder.ui.log_window import LogWindow
        from apk_builder.ui.settings_window import SettingsWindow
        from apk_builder.ui.setup_window import SetupWindow

        opened = []
        self.addCleanup(
            lambda: [w.close() for w in opened] or _pump(0.2))

        log_window = LogWindow()
        opened.append(log_window)
        log_window.append_line("Starting fake build")
        log_window.append_line(":app:assembleDebug")
        log_window.append_line("BUILD SUCCESSFUL")
        log_window.show()
        _pump(0.3)
        self.assertTrue(log_window.grab().save(
            os.path.join(VERIFY_DIR, "log-window.png")))
        log_window.close()

        setup_window = SetupWindow(self.settings)
        opened.append(setup_window)
        setup_window.show()
        _wait_until(lambda: setup_window._env_status is not None,
                    what="setup env check")
        _pump(0.3)
        self.assertTrue(setup_window.grab().save(
            os.path.join(VERIFY_DIR, "setup-window.png")))
        setup_window.close()

        settings_window = SettingsWindow(self.settings)
        opened.append(settings_window)
        settings_window.show()
        _pump(0.3)
        self.assertTrue(settings_window.grab().save(
            os.path.join(VERIFY_DIR, "settings-window.png")))
        settings_window.close()

        help_window = HelpWindow()
        opened.append(help_window)
        help_window.show()
        help_window.show_entry("Start here")
        _pump(0.3)
        self.assertTrue(help_window.grab().save(
            os.path.join(VERIFY_DIR, "help-window.png")))
        help_window.close()

    def test_child_windows_are_real_windows(self):
        """Each secondary window is a real top-level window with a
        painted background. Without the Window flag a QWidget shown
        from the main window embeds inside it, and without
        WA_StyledBackground its background never paints, so the main
        window shows through (seen on a real PC, 2026-11-18:
        First-Time Setup painted over the main window)."""
        from PySide6.QtCore import Qt

        from apk_builder.ui.help_window import HelpWindow
        from apk_builder.ui.log_window import LogWindow
        from apk_builder.ui.settings_window import SettingsWindow
        from apk_builder.ui.setup_window import SetupWindow

        windows = [
            LogWindow(self.window),
            SetupWindow(self.settings, self.window),
            SettingsWindow(self.settings, self.window),
            HelpWindow(self.window),
        ]
        try:
            for window in windows:
                self.assertTrue(window.isWindow(), type(window).__name__)
                self.assertTrue(
                    window.testAttribute(
                        Qt.WidgetAttribute.WA_StyledBackground),
                    type(window).__name__)
        finally:
            for window in windows:
                window.close()
            _pump(0.2)

    def test_no_em_dash_or_ampersand_in_visible_text(self):
        """U33 and U11 guards: walk every visible string the main window
        and the help index can show and refuse em-dashes and bare &."""
        from apk_builder.ui.help_window import ENTRIES

        texts: list[str] = []
        for widget in self.window.findChildren(QLabel):
            texts.append(widget.text())
        for widget in self.window.findChildren(QPushButton):
            texts.append(widget.text())
        for action in self.window.menuBar().actions():
            texts.append(action.text())
            if action.menu() is not None:
                for sub in action.menu().actions():
                    texts.append(sub.text())
        texts.append(self.window.windowTitle())
        for title, body in ENTRIES:
            texts.append(title)
            texts.append(body)
        problems = [t for t in texts if "\u2014" in t or "&" in t]
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
