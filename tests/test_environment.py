"""Tests for core/environment.py: detection, machine sizing, and the
resumable download (against a local server that supports Range)."""
from __future__ import annotations

import functools
import http.server
import os
import socketserver
import sys
import tempfile
import threading
import unittest

from apk_builder.core.environment import (
    check_environment,
    download_file_resumable,
    find_sdk,
    gradle_heap_for_ram,
    gradle_workers_for_ram,
    java_major_version,
    sdkmanager_path,
)


class SizingTests(unittest.TestCase):
    def test_heap_sizes(self):
        self.assertEqual(gradle_heap_for_ram(2.0), "1g")
        self.assertEqual(gradle_heap_for_ram(4.0), "1g")
        self.assertEqual(gradle_heap_for_ram(8.0), "2g")
        self.assertEqual(gradle_heap_for_ram(16.0), "4g")

    def test_workers_cap_on_8gb(self):
        self.assertEqual(gradle_workers_for_ram(4.0), 2)
        self.assertEqual(gradle_workers_for_ram(8.0), 2)
        self.assertEqual(gradle_workers_for_ram(16.0), 4)


def _fake_java(bin_dir: str, version_line: str) -> str:
    path = os.path.join(bin_dir, "java")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n")
        fh.write(f'echo \'{version_line}\' >&2\n')
    os.chmod(path, 0o755)
    return path


class JavaTests(unittest.TestCase):
    def test_parses_modern_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            java = _fake_java(tmp, 'openjdk version "17.0.9" 2023-10-17')
            self.assertEqual(java_major_version(java), 17)

    def test_parses_old_style_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            java = _fake_java(tmp, 'java version "1.8.0_391"')
            self.assertEqual(java_major_version(java), 1)

    def test_missing_binary_is_none(self):
        self.assertIsNone(java_major_version("/nonexistent/java"))


def _fake_sdk(root: str, with_cmdline=True, with_platform=True,
              with_build_tools=True, with_platform_tools=True) -> str:
    sdk = os.path.join(root, "sdk")
    if with_cmdline:
        manager = os.path.join(sdk, "cmdline-tools", "latest", "bin",
                               "sdkmanager")
        os.makedirs(os.path.dirname(manager), exist_ok=True)
        with open(manager, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(manager, 0o755)
    if with_platform_tools:
        os.makedirs(os.path.join(sdk, "platform-tools"), exist_ok=True)
    if with_platform:
        os.makedirs(os.path.join(sdk, "platforms", "android-35"),
                    exist_ok=True)
    if with_build_tools:
        os.makedirs(os.path.join(sdk, "build-tools", "35.0.0"),
                    exist_ok=True)
    return sdk


class SdkTests(unittest.TestCase):
    def test_find_sdk_prefers_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            sdk = _fake_sdk(tmp)
            self.assertEqual(find_sdk(sdk), sdk)

    def test_find_sdk_ignores_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "empty")
            os.makedirs(empty)
            self.assertIsNone(find_sdk(empty))

    def test_sdkmanager_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            sdk = _fake_sdk(tmp)
            manager = sdkmanager_path(sdk)
            self.assertTrue(manager.endswith("sdkmanager"))
            self.assertTrue(os.path.isfile(manager))

    def test_check_environment_reports_missing_pieces(self):
        with tempfile.TemporaryDirectory() as tmp:
            sdk = _fake_sdk(tmp, with_build_tools=False)
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            _fake_java(bin_dir, 'openjdk version "17.0.9"')
            old_path = os.environ.get("PATH", "")
            old_home = os.environ.get("JAVA_HOME")
            try:
                os.environ["PATH"] = bin_dir + os.pathsep + old_path
                os.environ.pop("JAVA_HOME", None)
                status = check_environment(sdk_override=sdk)
            finally:
                os.environ["PATH"] = old_path
                if old_home is not None:
                    os.environ["JAVA_HOME"] = old_home
            self.assertTrue(status.java_ok)
            self.assertEqual(status.java_version, 17)
            self.assertFalse(status.sdk_ok)
            self.assertFalse(status.ready)
            self.assertTrue(any("build tools" in m for m in status.missing))

    def test_check_environment_ready_with_full_fake_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            sdk = _fake_sdk(tmp)
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            _fake_java(bin_dir, 'openjdk version "21.0.1"')
            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = bin_dir + os.pathsep + old_path
                os.environ.pop("JAVA_HOME", None)
                status = check_environment(sdk_override=sdk)
            finally:
                os.environ["PATH"] = old_path
            self.assertTrue(status.java_ok)
            self.assertTrue(status.sdk_ok)
            self.assertTrue(status.ready)
            self.assertEqual(status.missing, [])


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    """Serves one fixed payload with Range support."""

    payload = b""

    def do_GET(self):
        data = self.payload
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            start = int(range_header[len("bytes="):].split("-")[0] or 0)
            chunk = data[start:]
            self.send_response(206)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Range",
                             f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class ResumableDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _RangeHandler.payload = b"x" * 100_000 + b"tail"
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), _RangeHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self):
        return f"http://127.0.0.1:{self.port}/file.bin"

    def test_fresh_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "file.bin")
            seen = []
            download_file_resumable(
                self._url(), dest,
                progress_cb=lambda done, total: seen.append((done, total)))
            with open(dest, "rb") as fh:
                self.assertEqual(fh.read(), _RangeHandler.payload)
            self.assertTrue(seen)
            self.assertEqual(seen[-1][0], len(_RangeHandler.payload))

    def test_partial_download_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "file.bin")
            with open(dest + ".partial", "wb") as fh:
                fh.write(_RangeHandler.payload[:40_000])
            download_file_resumable(self._url(), dest)
            with open(dest, "rb") as fh:
                self.assertEqual(fh.read(), _RangeHandler.payload)
            self.assertFalse(os.path.exists(dest + ".partial"))

    def test_cancel_keeps_the_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "file.bin")
            from apk_builder.core.errors import SetupCancelled

            with self.assertRaises(SetupCancelled):
                download_file_resumable(self._url(), dest,
                                        cancel=lambda: True)
            self.assertTrue(os.path.exists(dest + ".partial"))


if __name__ == "__main__":
    unittest.main()


class RunQuietTests(unittest.TestCase):
    """_run_quiet feeds stdin_text through communicate(). The old code
    wrote the pipe and closed it by hand, and communicate() then
    raised ValueError: I/O operation on closed file, which killed the
    license step of First-Time Setup on a real PC (2026-11-18). These
    tests fail on the old code and pass on the fix."""

    def _run(self, code, **kwargs):
        from apk_builder.core.environment import _run_quiet

        return _run_quiet([sys.executable, "-c", code], **kwargs)

    def test_stdin_text_reaches_a_fast_command(self):
        result = self._run(
            "import sys; print(sys.stdin.read().upper(), end='')",
            stdin_text="yes\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("YES", result.stdout)

    def test_stdin_text_survives_a_slow_command(self):
        # Two seconds forces the communicate() timeout-and-retry path
        # with the input already handed over.
        result = self._run(
            "import sys, time; time.sleep(2); "
            "print('read:' + sys.stdin.read(), end='')",
            stdin_text="y\n", timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn("read:y", result.stdout)

    def test_no_stdin_slow_command(self):
        result = self._run("import time; time.sleep(2)", timeout=60)
        self.assertEqual(result.returncode, 0)
