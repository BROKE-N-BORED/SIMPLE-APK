"""Build running and APK handling for Simple APK.

Qt-free, stdlib only, so the UI can drive it from a worker thread and
the tests can run it without Qt. The runner streams the build's own
output line by line (honest loading: real lines, real elapsed time, no
fake progress bar) and can be cancelled at any moment (U26).
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass

from .environment import EnvironmentStatus
from .errors import BuildError

log = logging.getLogger("apk_builder")

WRAPPER_JAR = os.path.join("gradle", "wrapper", "gradle-wrapper.jar")
_BADGING_PACKAGE_RE = re.compile(r"^package: name='([^']+)'")
_BADGING_VERSION_RE = re.compile(r"versionName='([^']*)'")
_BADGING_CODE_RE = re.compile(r"versionCode='([^']*)'")


@dataclass
class ApkInfo:
    """One finished APK file."""

    path: str
    name: str
    size: int
    package: str | None = None
    version_name: str | None = None
    version_code: str | None = None


@dataclass
class BuildResult:
    """The outcome of one build run."""

    success: bool
    return_code: int | None
    elapsed_seconds: float
    apks: list[ApkInfo]
    cancelled: bool = False
    message: str = ""


def find_apks(project_root: str) -> list[str]:
    """APK files under the project's debug output folders, newest first.
    Flavoured builds land in app/build/outputs/apk/<flavour>/debug/, so
    every flavour folder is searched."""
    pattern = os.path.join(project_root, "app", "build", "outputs", "apk",
                           "*", "debug", "*.apk")
    direct = os.path.join(project_root, "app", "build", "outputs", "apk",
                          "debug", "*.apk")
    found = glob.glob(pattern) + glob.glob(direct)
    found = sorted(set(found),
                   key=lambda path: os.path.getmtime(path), reverse=True)
    return found


def find_aapt2(sdk_dir: str | None) -> str | None:
    """The newest aapt2 in an SDK's build-tools, or None."""
    if not sdk_dir:
        return None
    build_tools = os.path.join(sdk_dir, "build-tools")
    if not os.path.isdir(build_tools):
        return None
    versions = sorted(os.listdir(build_tools), reverse=True)
    for version in versions:
        candidate = os.path.join(build_tools, version, "aapt2")
        if os.path.isfile(candidate):
            return candidate
    return None


def parse_badging(text: str) -> dict:
    """Package, version name, and version code from `aapt2 dump badging`
    output. Missing fields stay None; a bad dump is an empty result,
    never an error (the APK is still good without its label)."""
    info: dict = {"package": None, "version_name": None,
                  "version_code": None}
    for line in text.splitlines():
        if line.startswith("package:"):
            match = _BADGING_PACKAGE_RE.match(line)
            if match:
                info["package"] = match.group(1)
            match = _BADGING_VERSION_RE.search(line)
            if match:
                info["version_name"] = match.group(1) or None
            match = _BADGING_CODE_RE.search(line)
            if match:
                info["version_code"] = match.group(1) or None
            break
    return info


def apk_info(apk_path: str, aapt2: str | None = None) -> ApkInfo:
    """Describe one APK file: name and size always, package and version
    when aapt2 is available to read them."""
    info = ApkInfo(
        path=apk_path,
        name=os.path.basename(apk_path),
        size=os.path.getsize(apk_path),
    )
    if aapt2:
        try:
            result = subprocess.run(
                [aapt2, "dump", "badging", apk_path],
                capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                parsed = parse_badging(result.stdout or "")
                info.package = parsed["package"]
                info.version_name = parsed["version_name"]
                info.version_code = parsed["version_code"]
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("aapt2 could not read %s: %s", apk_path, exc)
    return info


def _never_overwrite_path(out_dir: str, name: str) -> str:
    """An output path that never overwrites an existing file
    (name_1.apk, name_2.apk, ...)."""
    candidate = os.path.join(out_dir, name)
    if not os.path.exists(candidate):
        return candidate
    stem, ext = os.path.splitext(name)
    number = 1
    while True:
        candidate = os.path.join(out_dir, f"{stem}_{number}{ext}")
        if not os.path.exists(candidate):
            return candidate
        number += 1


def copy_apks(apk_paths: list[str], out_dir: str,
              aapt2: str | None = None) -> list[ApkInfo]:
    """Copy finished APKs into the output folder without ever
    overwriting an existing file. Returns the copied APKs' info."""
    os.makedirs(out_dir, exist_ok=True)
    copied: list[ApkInfo] = []
    for apk_path in apk_paths:
        dest = _never_overwrite_path(out_dir, os.path.basename(apk_path))
        shutil.copy2(apk_path, dest)
        copied.append(apk_info(dest, aapt2))
    return copied


def build_command(project_root: str, java_bin: str | None) -> list[str]:
    """The command that starts the build.

    gradlew when it is there (made executable first: zips often lose
    the execute bit); the wrapper jar run with Java when gradlew is
    missing but the jar is present; a plain-words BuildError when
    neither is there.
    """
    gradlew = os.path.join(project_root, "gradlew")
    if os.path.isfile(gradlew):
        try:
            os.chmod(gradlew, 0o755)
        except OSError:
            pass
        return [gradlew, "assembleDebug"]
    jar = os.path.join(project_root, WRAPPER_JAR)
    if os.path.isfile(jar):
        if not java_bin:
            raise BuildError(
                "This project has no build starter, only a wrapper file, "
                "and Java is not installed, so the wrapper cannot run. "
                "Install Java first.")
        return [java_bin, "-jar", jar, "assembleDebug"]
    raise BuildError(
        "This project has no build starter (gradlew) and no wrapper "
        "file, so the app cannot start its build. Ask whoever made the "
        "project to include the wrapper.")


def build_env(env_status: EnvironmentStatus) -> dict[str, str]:
    """Environment for the build process: SDK and Java locations, plus
    the machine-sized Gradle memory (U35: set under the hood)."""
    env = dict(os.environ)
    if env_status.sdk_dir:
        env["ANDROID_HOME"] = env_status.sdk_dir
        env["ANDROID_SDK_ROOT"] = env_status.sdk_dir
    if env_status.java_path:
        env["JAVA_HOME"] = os.path.dirname(
            os.path.dirname(env_status.java_path))
    env["GRADLE_OPTS"] = f"-Xmx{env_status.gradle_heap}"
    return env


def run_build(project_root: str, env_status: EnvironmentStatus,
              on_line=None, should_cancel=None) -> BuildResult:
    """Run ./gradlew assembleDebug in project_root, streaming its
    output line by line to on_line(text). should_cancel() is checked
    while the build runs; a cancelled build kills the whole Gradle
    process group and returns cancelled=True. The build runs with the
    machine-sized worker cap (U25) and plain console output so the log
    stays readable."""
    started = time.monotonic()
    try:
        command = build_command(project_root, env_status.java_path)
    except BuildError as exc:
        return BuildResult(success=False, return_code=None,
                           elapsed_seconds=0.0, apks=[],
                           message=str(exc))
    full_command = [*command, "--max-workers",
                    str(env_status.gradle_workers), "--console=plain"]
    env = build_env(env_status)
    log.info("Build starting: %s (cwd %s)",
             " ".join(full_command), project_root)
    process = None
    try:
        process = subprocess.Popen(
            full_command, cwd=project_root, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1, start_new_session=True)
    except OSError as exc:
        return BuildResult(
            success=False, return_code=None,
            elapsed_seconds=time.monotonic() - started, apks=[],
            message=f"Could not start the build: {exc}")
    assert process.stdout is not None
    cancelled = False
    try:
        while True:
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            line = process.stdout.readline()
            if not line:
                break
            if on_line is not None:
                on_line(line.rstrip("\n"))
    finally:
        if cancelled:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                process.wait(timeout=15)
        else:
            process.wait()
    elapsed = time.monotonic() - started
    if cancelled:
        return BuildResult(success=False, return_code=process.returncode,
                           elapsed_seconds=elapsed, apks=[],
                           cancelled=True,
                           message="The build was cancelled.")
    if process.returncode != 0:
        return BuildResult(
            success=False, return_code=process.returncode,
            elapsed_seconds=elapsed, apks=[],
            message="The build did not finish. Open the Build Log to see "
                    "what it said at the end.")
    found = find_apks(project_root)
    if not found:
        return BuildResult(
            success=True, return_code=0, elapsed_seconds=elapsed, apks=[],
            message="The build finished, but no APK file was found in "
                    "the project's output folder.")
    aapt2 = find_aapt2(env_status.sdk_dir)
    infos = [apk_info(path, aapt2) for path in found]
    return BuildResult(success=True, return_code=0,
                       elapsed_seconds=elapsed, apks=infos,
                       message="Your app is ready.")
