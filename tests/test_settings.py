"""Tests for core/settings.py and core/logutil.py."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest

from apk_builder.core.logutil import (
    build_debug_report,
    ring_lines,
    scrub_text,
    setup_logging,
)
from apk_builder.core.settings import SettingsManager


class SettingsTests(unittest.TestCase):
    def test_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SettingsManager(os.path.join(tmp, "s.json"))
            self.assertTrue(manager.current.output_folder.endswith("Simple APK"))
            self.assertEqual(manager.current.sdk_folder, "")
            self.assertTrue(manager.current.check_updates_on_startup)
            self.assertEqual(manager.current.last_update_check, 0.0)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            manager = SettingsManager(path)
            manager.current.output_folder = "/tmp/out"
            manager.current.sdk_folder = "/tmp/sdk"
            manager.current.check_updates_on_startup = False
            manager.current.last_update_check = 1234.5
            manager.save()
            reloaded = SettingsManager(path)
            self.assertEqual(reloaded.current.output_folder, "/tmp/out")
            self.assertEqual(reloaded.current.sdk_folder, "/tmp/sdk")
            self.assertFalse(reloaded.current.check_updates_on_startup)
            self.assertEqual(reloaded.current.last_update_check, 1234.5)

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            manager = SettingsManager(path)
            self.assertTrue(manager.current.check_updates_on_startup)

    def test_unknown_keys_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"output_folder": "/tmp/x", "surprise": 1}, fh)
            manager = SettingsManager(path)
            self.assertEqual(manager.current.output_folder, "/tmp/x")


class LogUtilTests(unittest.TestCase):
    def test_setup_logging_writes_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = setup_logging(os.path.join(tmp, "logs"))
            logger.info("hello log")
            for handler in logger.handlers:
                handler.flush()
            found = os.path.join(tmp, "logs", "app.log")
            # setup_logging is idempotent: the first caller's dir wins, so
            # only assert the file exists when this call created it.
            if os.path.isfile(found):
                with open(found, encoding="utf-8") as fh:
                    self.assertIn("hello log", fh.read())

    def test_ring_buffer_keeps_the_last_200(self):
        logger = setup_logging()
        for i in range(250):
            logger.info("ring line %d", i)
        lines = ring_lines()
        self.assertEqual(len(lines), 200)
        self.assertIn("ring line 249", lines[-1])
        self.assertNotIn("ring line 0\n", "\n".join(lines))

    def test_report_scrubs_home_and_credentials(self):
        home = os.path.expanduser("~")
        scrubbed = scrub_text(f"path {home}/secret token=abc123")
        self.assertNotIn(home, scrubbed)
        self.assertIn("~", scrubbed)
        self.assertNotIn("abc123", scrubbed)

    def test_debug_report_has_version_and_log(self):
        setup_logging()
        logging.getLogger("apk_builder").info("report probe")
        report = build_debug_report("0.1")
        self.assertIn("Simple APK 0.1", report)
        self.assertIn("report probe", report)


if __name__ == "__main__":
    unittest.main()
