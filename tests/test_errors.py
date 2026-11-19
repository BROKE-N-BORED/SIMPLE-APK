"""Tests for core/errors.py: plain-words messages (U29)."""
from __future__ import annotations

import unittest
import zipfile

from apk_builder.core.errors import ProjectError, describe


class DescribeTests(unittest.TestCase):
    def test_known_errors_pass_through(self):
        self.assertEqual(
            describe(ProjectError("That pick has no build file.")),
            "That pick has no build file.")

    def test_bad_zip_is_plain(self):
        message = describe(zipfile.BadZipFile("File is not a zip file"))
        self.assertIn("not a zip file", message)

    def test_unknown_error_never_leaks_raw_text(self):
        # Regression guard (2026-11-18): a raw "I/O operation on closed
        # file" reached the setup window's status line. The fallback
        # must stay plain and point at the log instead.
        message = describe(ValueError("I/O operation on closed file."))
        self.assertNotIn("closed file", message)
        self.assertTrue(message.startswith("Something went wrong."))
        self.assertIn("Open Logs", message)


if __name__ == "__main__":
    unittest.main()
