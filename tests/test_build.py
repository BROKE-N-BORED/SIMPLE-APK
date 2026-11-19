"""Tests for core/build.py: APK finding, copying, badging, command
selection, and the build runner (driven by a fake gradlew script, so
no real Gradle is needed and the sandbox daemon is never touched)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest

from apk_builder.core.build import (
    apk_info,
    build_command,
    copy_apks,
    find_aapt2,
    find_apks,
    parse_badging,
    run_build,
)
from apk_builder.core.environment import EnvironmentStatus
from apk_builder.core.errors import BuildError


def _apk_tree(root: str) -> str:
    debug = os.path.join(root, "app", "build", "outputs", "apk", "debug")
    os.makedirs(debug, exist_ok=True)
    with open(os.path.join(debug, "app-debug.apk"), "wb") as fh:
        fh.write(b"fake apk one")
    time.sleep(0.02)
    flavoured = os.path.join(root, "app", "build", "outputs", "apk",
                             "free", "debug")
    os.makedirs(flavoured, exist_ok=True)
    with open(os.path.join(flavoured, "app-free-debug.apk"), "wb") as fh:
        fh.write(b"fake apk two, newer")
    return root


class FindApksTests(unittest.TestCase):
    def test_finds_debug_and_flavoured_apks_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            _apk_tree(tmp)
            found = find_apks(tmp)
            self.assertEqual(len(found), 2)
            self.assertTrue(found[0].endswith("app-free-debug.apk"))
            self.assertTrue(found[1].endswith("app-debug.apk"))

    def test_no_apks_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_apks(tmp), [])


class CopyApksTests(unittest.TestCase):
    def test_copies_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            _apk_tree(tmp)
            out = os.path.join(tmp, "out")
            first = copy_apks(find_apks(tmp), out)
            self.assertEqual(len(first), 2)
            self.assertTrue(all(os.path.isfile(info.path) for info in first))
            second = copy_apks(find_apks(tmp), out)
            names = sorted(os.path.basename(info.path) for info in second)
            self.assertIn("app-debug_1.apk", names)
            self.assertIn("app-free-debug_1.apk", names)
            self.assertEqual(len(os.listdir(out)), 4)


class BadgingTests(unittest.TestCase):
    def test_parses_package_and_version(self):
        text = (
            "package: name='com.example.app' versionCode='12' "
            "versionName='1.2.3' platformBuildVersionName='14'\n"
            "application-label:'Example'\n"
        )
        parsed = parse_badging(text)
        self.assertEqual(parsed["package"], "com.example.app")
        self.assertEqual(parsed["version_code"], "12")
        self.assertEqual(parsed["version_name"], "1.2.3")

    def test_bad_dump_is_empty_not_an_error(self):
        parsed = parse_badging("nothing useful here\n")
        self.assertIsNone(parsed["package"])
        self.assertIsNone(parsed["version_name"])

    def test_apk_info_without_aapt2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.apk")
            with open(path, "wb") as fh:
                fh.write(b"12345")
            info = apk_info(path)
            self.assertEqual(info.name, "a.apk")
            self.assertEqual(info.size, 5)
            self.assertIsNone(info.package)


class Aapt2Tests(unittest.TestCase):
    def test_finds_newest_aapt2(self):
        with tempfile.TemporaryDirectory() as tmp:
            sdk = os.path.join(tmp, "sdk")
            for version in ("34.0.0", "35.0.0"):
                tool_dir = os.path.join(sdk, "build-tools", version)
                os.makedirs(tool_dir, exist_ok=True)
                with open(os.path.join(tool_dir, "aapt2"), "w") as fh:
                    fh.write("x")
            found = find_aapt2(sdk)
            self.assertTrue(found.endswith(os.path.join("35.0.0", "aapt2")))

    def test_no_sdk_is_none(self):
        self.assertIsNone(find_aapt2(None))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_aapt2(tmp))


class BuildCommandTests(unittest.TestCase):
    def test_gradlew_is_used_and_made_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            gradlew = os.path.join(tmp, "gradlew")
            with open(gradlew, "w") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(gradlew, 0o644)
            command = build_command(tmp, "/usr/bin/java")
            self.assertEqual(command, [gradlew, "assembleDebug"])
            self.assertTrue(os.access(gradlew, os.X_OK))

    def test_wrapper_jar_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            jar = os.path.join(tmp, "gradle", "wrapper",
                               "gradle-wrapper.jar")
            os.makedirs(os.path.dirname(jar), exist_ok=True)
            with open(jar, "wb") as fh:
                fh.write(b"jar")
            command = build_command(tmp, "/usr/bin/java")
            self.assertEqual(
                command, ["/usr/bin/java", "-jar", jar, "assembleDebug"])

    def test_neither_is_a_plain_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(BuildError) as caught:
                build_command(tmp, "/usr/bin/java")
            self.assertIn("wrapper", str(caught.exception))

    def test_jar_fallback_needs_java(self):
        with tempfile.TemporaryDirectory() as tmp:
            jar = os.path.join(tmp, "gradle", "wrapper",
                               "gradle-wrapper.jar")
            os.makedirs(os.path.dirname(jar), exist_ok=True)
            with open(jar, "wb") as fh:
                fh.write(b"jar")
            with self.assertRaises(BuildError):
                build_command(tmp, None)


def _fake_gradlew(project: str, behaviour: str) -> None:
    """A gradlew stand-in. behaviour: ok (prints lines, makes an APK),
    fail (exits 1), slow (prints then sleeps)."""
    path = os.path.join(project, "gradlew")
    if behaviour == "ok":
        script = (
            "#!/bin/sh\n"
            "echo 'Starting fake build'\n"
            "echo ':app:assembleDebug'\n"
            "mkdir -p app/build/outputs/apk/debug\n"
            "printf 'fake apk' > app/build/outputs/apk/debug/app-debug.apk\n"
            "echo 'BUILD SUCCESSFUL'\n"
        )
    elif behaviour == "fail":
        script = (
            "#!/bin/sh\n"
            "echo 'Something broke' >&2\n"
            "exit 1\n"
        )
    else:
        script = (
            "#!/bin/sh\n"
            "echo 'working...'\n"
            "sleep 30\n"
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(script)
    os.chmod(path, 0o755)


class RunBuildTests(unittest.TestCase):
    def _env(self):
        return EnvironmentStatus(java_path="/usr/bin/java",
                                 java_version=17, sdk_dir=None)

    def test_successful_fake_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_gradlew(tmp, "ok")
            lines = []
            result = run_build(tmp, self._env(), on_line=lines.append)
            self.assertTrue(result.success)
            self.assertEqual(result.return_code, 0)
            self.assertFalse(result.cancelled)
            self.assertEqual(len(result.apks), 1)
            self.assertEqual(result.apks[0].name, "app-debug.apk")
            self.assertIn("BUILD SUCCESSFUL", lines)
            self.assertGreater(result.elapsed_seconds, 0)

    def test_failing_fake_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_gradlew(tmp, "fail")
            result = run_build(tmp, self._env())
            self.assertFalse(result.success)
            self.assertEqual(result.return_code, 1)
            self.assertEqual(result.apks, [])

    def test_cancel_kills_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_gradlew(tmp, "slow")
            state = {"cancel": False}

            def on_line(_text):
                state["cancel"] = True

            started = time.monotonic()
            result = run_build(tmp, self._env(), on_line=on_line,
                               should_cancel=lambda: state["cancel"])
            self.assertTrue(result.cancelled)
            self.assertLess(time.monotonic() - started, 25)

    def test_missing_wrapper_is_a_failed_result_not_an_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_build(tmp, self._env())
            self.assertFalse(result.success)
            self.assertIn("wrapper", result.message)


if __name__ == "__main__":
    unittest.main()
