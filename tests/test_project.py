"""Tests for core/project.py: safe unzip and project detection."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile

from apk_builder.core.errors import ProjectError
from apk_builder.core.project import (
    clear_work_folders,
    detect_project,
    find_project_root,
    prepare_source,
    safe_extract_zip,
)

NEO_ZIP = os.path.expanduser("~/workspace/NEO-source-v0.1.zip")


def _write(path: str, content: str = "") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _make_project(root: str, with_gradlew: bool = True,
                  with_wrapper_jar: bool = True) -> str:
    _write(os.path.join(root, "settings.gradle.kts"), "")
    _write(os.path.join(root, "app", "build.gradle.kts"), "")
    if with_gradlew:
        _write(os.path.join(root, "gradlew"), "#!/bin/sh\n")
    if with_wrapper_jar:
        jar = os.path.join(root, "gradle", "wrapper",
                           "gradle-wrapper.jar")
        os.makedirs(os.path.dirname(jar), exist_ok=True)
        with open(jar, "wb") as fh:
            fh.write(b"fake jar")
    return root


class SafeExtractTests(unittest.TestCase):
    def test_extracts_files_and_counts_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "a.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("one.txt", "hello")
                zf.writestr("sub/two.txt", "world")
            dest = os.path.join(tmp, "out")
            result = safe_extract_zip(zip_path, dest)
            self.assertEqual(result.files, 2)
            self.assertEqual(result.skipped, [])
            with open(os.path.join(dest, "sub", "two.txt")) as fh:
                self.assertEqual(fh.read(), "world")

    def test_zip_slip_entries_are_listed_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "evil.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("../evil.txt", "escape")
                zf.writestr("/abs.txt", "absolute")
                zf.writestr("ok.txt", "fine")
            dest = os.path.join(tmp, "out")
            result = safe_extract_zip(zip_path, dest)
            self.assertEqual(result.files, 1)
            self.assertEqual(len(result.skipped), 2)
            self.assertFalse(os.path.exists(os.path.join(tmp, "evil.txt")))
            self.assertFalse(os.path.exists(os.path.join(dest, "evil.txt")))
            for entry in result.skipped:
                self.assertTrue(entry.reason)

    def test_bad_zip_is_a_plain_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.zip")
            with open(bad, "wb") as fh:
                fh.write(b"this is not a zip at all")
            with self.assertRaises(ProjectError):
                safe_extract_zip(bad, os.path.join(tmp, "out"))

    def test_cancel_stops_the_unpack(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "a.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                for i in range(20):
                    zf.writestr(f"f{i}.txt", "x")
            with self.assertRaises(ProjectError):
                safe_extract_zip(zip_path, os.path.join(tmp, "out"),
                                 should_cancel=lambda: True)


class ProjectRootTests(unittest.TestCase):
    def test_single_top_level_folder_is_unwrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            inner = _make_project(os.path.join(tmp, "inner"))
            self.assertEqual(find_project_root(tmp), inner)

    def test_root_project_stays_put(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            self.assertEqual(find_project_root(tmp), tmp)


class DetectTests(unittest.TestCase):
    def test_complete_project_detects(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp)
            info = detect_project(tmp, "test")
            self.assertTrue(info.is_android_project)
            self.assertTrue(info.has_gradlew)
            self.assertTrue(info.has_wrapper_jar)
            self.assertTrue(info.can_build)
            self.assertIsNone(info.build_blocker)

    def test_non_android_folder_lists_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "notes.txt"), "hello")
            info = detect_project(tmp, "notes")
            self.assertFalse(info.is_android_project)
            self.assertFalse(info.can_build)
            self.assertTrue(info.issues)
            self.assertIn("settings", info.build_blocker)

    def test_missing_wrapper_blocks_with_plain_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp, with_gradlew=False, with_wrapper_jar=False)
            info = detect_project(tmp, "test")
            self.assertTrue(info.is_android_project)
            self.assertFalse(info.can_build)
            self.assertIn("wrapper", info.build_blocker)

    def test_wrapper_jar_alone_can_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_project(tmp, with_gradlew=False, with_wrapper_jar=True)
            info = detect_project(tmp, "test")
            self.assertTrue(info.can_build)


class PrepareTests(unittest.TestCase):
    def test_prepare_folder_uses_it_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = _make_project(os.path.join(tmp, "proj"))
            result = prepare_source(project_dir, os.path.join(tmp, "work"))
            self.assertTrue(result.project.can_build)
            self.assertIsNone(result.work_dir)

    def test_prepare_zip_unpacks_and_detects(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _make_project(os.path.join(tmp, "src"))
            zip_path = os.path.join(tmp, "proj.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                for root, _dirs, files in os.walk(src):
                    for name in files:
                        path = os.path.join(root, name)
                        zf.write(path, os.path.relpath(path, src))
            result = prepare_source(zip_path, os.path.join(tmp, "work"))
            self.assertTrue(result.project.can_build)
            self.assertIsNotNone(result.work_dir)
            self.assertTrue(os.path.isdir(result.work_dir))

    def test_prepare_unknown_path_is_a_plain_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProjectError):
                prepare_source(os.path.join(tmp, "nope"),
                               os.path.join(tmp, "work"))

    def test_clear_work_folders_removes_only_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, "work")
            os.makedirs(os.path.join(work, "a-1"))
            os.makedirs(os.path.join(work, "b-2"))
            self.assertEqual(clear_work_folders(work), 2)
            self.assertEqual(os.listdir(work), [])


@unittest.skipUnless(os.path.isfile(NEO_ZIP), "NEO test zip not present")
class NeoZipTests(unittest.TestCase):
    def test_neo_zip_detects_as_a_buildable_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = prepare_source(NEO_ZIP, os.path.join(tmp, "work"))
            project = result.project
            self.assertTrue(project.is_android_project)
            self.assertTrue(project.has_gradlew)
            self.assertTrue(project.has_wrapper_jar)
            self.assertTrue(project.can_build)
            self.assertIsNone(project.build_blocker)
            self.assertEqual(project.skipped, [])
            with zipfile.ZipFile(NEO_ZIP) as zf:
                expected_files = sum(
                    1 for name in zf.namelist()
                    if not name.endswith("/"))
            self.assertEqual(result.extracted_files, expected_files)
            self.assertGreater(result.extracted_files, 30)


if __name__ == "__main__":
    unittest.main()
