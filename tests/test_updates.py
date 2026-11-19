"""Tests for core/updates.py: versions, release selection, verified
download, and the atomic-swap apply (against a fake install dir)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from apk_builder.core import updates
from apk_builder.core.updates import (
    UpdateError,
    apply_update,
    check_for_update,
    compare_versions,
    download_update,
    find_linux_update,
    is_installed,
    is_newer,
    newest_linux_release,
    parse_sidecar,
    parse_version,
    read_package_version,
)


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_version("0.1"), (0, 1))
        self.assertEqual(parse_version("v0.1.2"), (0, 1, 2))
        self.assertIsNone(parse_version("banana"))
        self.assertIsNone(parse_version(""))
        self.assertIsNone(parse_version(None))

    def test_compare(self):
        self.assertEqual(compare_versions("0.1", "0.1.0"), 0)
        self.assertLess(compare_versions("0.1", "0.2"), 0)
        self.assertGreater(compare_versions("1.0", "0.9"), 0)
        self.assertLess(compare_versions("banana", "0.1"), 0)

    def test_is_newer(self):
        self.assertTrue(is_newer("0.2", "0.1"))
        self.assertFalse(is_newer("0.1", "0.1"))
        self.assertFalse(is_newer("0.1", "0.2"))
        self.assertFalse(is_newer("banana", "0.1"))
        self.assertFalse(is_newer("0.2", "banana"))


def _release(tag, assets, draft=False, prerelease=False):
    return {
        "tag_name": tag,
        "html_url": f"https://example.invalid/{tag}",
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            {"name": name, "browser_download_url": f"https://example.invalid/{name}"}
            for name in assets
        ],
    }


class ReleaseSelectionTests(unittest.TestCase):
    def test_picks_newest_with_both_assets(self):
        releases = [
            _release("v0.1", ["simple-apk-linux-0.1.zip",
                              "simple-apk-linux-0.1.zip.sha256"]),
            _release("v0.2", ["simple-apk-linux-0.2.zip",
                              "simple-apk-linux-0.2.zip.sha256"]),
        ]
        best = newest_linux_release(releases)
        self.assertEqual(best["version"], "0.2")
        self.assertEqual(best["zip_url"],
                         "https://example.invalid/simple-apk-linux-0.2.zip")

    def test_release_without_sidecar_is_ignored(self):
        releases = [
            _release("v0.2", ["simple-apk-linux-0.2.zip"]),
            _release("v0.1", ["simple-apk-linux-0.1.zip",
                              "simple-apk-linux-0.1.zip.sha256"]),
        ]
        best = newest_linux_release(releases)
        self.assertEqual(best["version"], "0.1")

    def test_drafts_and_prereleases_are_ignored(self):
        releases = [
            _release("v0.3", ["simple-apk-linux-0.3.zip",
                              "simple-apk-linux-0.3.zip.sha256"],
                     prerelease=True),
            _release("v0.2", ["simple-apk-linux-0.2.zip",
                              "simple-apk-linux-0.2.zip.sha256"],
                     draft=True),
        ]
        self.assertIsNone(newest_linux_release(releases))

    def test_find_update_only_when_newer(self):
        releases = [
            _release("v0.2", ["simple-apk-linux-0.2.zip",
                              "simple-apk-linux-0.2.zip.sha256"]),
        ]
        self.assertIsNotNone(find_linux_update(releases, "0.1"))
        self.assertIsNone(find_linux_update(releases, "0.2"))
        self.assertIsNone(find_linux_update(releases, "0.3"))


class RepoTests(unittest.TestCase):
    def test_repo_is_set_and_empty_repo_check_is_unknown(self):
        # The repo is baked in now (Joshua creates it himself). The
        # empty-repo guard is still tested, by patching, because it is
        # the branch that keeps a repo-less build from ever offering
        # an update.
        self.assertEqual(updates.REPO, "BROKE-N-BORED/SIMPLE-APK")
        with mock.patch.object(updates, "REPO", ""):
            result = check_for_update("0.1")
        self.assertEqual(result["state"], "unknown")
        self.assertIn("not set up", result["reason"])


class SidecarTests(unittest.TestCase):
    def test_parses_sha256sum_line(self):
        digest = "a" * 64
        self.assertEqual(parse_sidecar(f"{digest}  simple-apk-linux-0.2.zip\n"),
                         digest)

    def test_rejects_garbage(self):
        self.assertIsNone(parse_sidecar("not a checksum"))
        self.assertIsNone(parse_sidecar(""))
        self.assertIsNone(parse_sidecar(None))


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data
        self.headers = {"Content-Length": str(len(data))}

    def read(self, size=-1):
        if size is None or size < 0:
            chunk, self._data = self._data, b""
            return chunk
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DownloadTests(unittest.TestCase):
    def test_download_verifies_against_sidecar(self):
        payload = b"fake release zip bytes"
        digest = hashlib.sha256(payload).hexdigest()
        calls = {}

        def fake_urlopen(url, timeout=None):
            calls[url] = True
            if url.endswith(".sha256"):
                return _FakeResponse(
                    f"{digest}  simple-apk-linux-0.2.zip\n".encode())
            return _FakeResponse(payload)

        info = {"version": "0.2",
                "zip_url": "https://example.invalid/z.zip",
                "sidecar_url": "https://example.invalid/z.zip.sha256"}
        with tempfile.TemporaryDirectory() as tmp:
            result = download_update(info, tmp, urlopen=fake_urlopen)
            self.assertEqual(result["version"], "0.2")
            self.assertEqual(result["sha256"], digest)
            with open(result["zip_path"], "rb") as fh:
                self.assertEqual(fh.read(), payload)

    def test_checksum_mismatch_throws_the_download_away(self):
        payload = b"tampered bytes"
        digest = hashlib.sha256(b"something else").hexdigest()

        def fake_urlopen(url, timeout=None):
            if url.endswith(".sha256"):
                return _FakeResponse(
                    f"{digest}  simple-apk-linux-0.2.zip\n".encode())
            return _FakeResponse(payload)

        info = {"version": "0.2",
                "zip_url": "https://example.invalid/z.zip",
                "sidecar_url": "https://example.invalid/z.zip.sha256"}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UpdateError):
                download_update(info, tmp, urlopen=fake_urlopen)
            self.assertEqual(os.listdir(tmp), [])


class ApplyTests(unittest.TestCase):
    def _fake_install(self, parent, version):
        install_dir = os.path.join(parent, "install")
        package = os.path.join(install_dir, "apk_builder")
        os.makedirs(package, exist_ok=True)
        with open(os.path.join(package, "__init__.py"), "w") as fh:
            fh.write(f'__version__ = "{version}"\n')
        with open(os.path.join(install_dir, "simple-apk"), "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(os.path.join(install_dir, "simple-apk"), 0o755)
        os.makedirs(os.path.join(install_dir, "logs"), exist_ok=True)
        with open(os.path.join(install_dir, "logs", "app.log"), "w") as fh:
            fh.write("old log\n")
        return install_dir

    def _update_zip(self, parent, version):
        zip_path = os.path.join(parent, "update.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("apk_builder/__init__.py",
                        f'__version__ = "{version}"\n')
        return zip_path

    def test_read_package_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = self._fake_install(tmp, "0.1")
            self.assertEqual(read_package_version(install), "0.1")

    def test_is_installed_needs_the_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = self._fake_install(tmp, "0.1")
            self.assertTrue(is_installed(os.path.join(install, "apk_builder")))
            os.remove(os.path.join(install, "simple-apk"))
            self.assertFalse(is_installed(os.path.join(install, "apk_builder")))

    def test_apply_swaps_and_keeps_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = self._fake_install(tmp, "0.1")
            zip_path = self._update_zip(tmp, "0.2")
            apply_update(zip_path, "0.2", install_dir=install)
            self.assertEqual(read_package_version(install), "0.2")
            self.assertTrue(os.path.isfile(
                os.path.join(install, "logs", "app.log")))
            self.assertTrue(os.path.isfile(
                os.path.join(install, "simple-apk")))

    def test_apply_refuses_a_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = self._fake_install(tmp, "0.1")
            zip_path = self._update_zip(tmp, "0.3")
            with self.assertRaises(UpdateError):
                apply_update(zip_path, "0.2", install_dir=install)
            # The old install is untouched.
            self.assertEqual(read_package_version(install), "0.1")


if __name__ == "__main__":
    unittest.main()
