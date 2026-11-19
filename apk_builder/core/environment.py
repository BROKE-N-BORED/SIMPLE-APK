"""Build environment for Simple APK: Java and Android SDK detection,
machine-sized build settings, and the guided first-time setup.

Qt-free, stdlib only, so the UI can drive it from a worker thread and
the tests can run it without Qt.

Rules from the design rules:
- U35 the backend configures itself: Gradle memory and worker count
  are sized from the machine's RAM and never shown as settings.
- U39 guided choices, not raw specs: setup is one button and a
  progress bar, not a list of package names to guess at.
- U24 long downloads are resumable: the SDK download keeps a partial
  file and resumes it with a Range request after a failure.
- U29 plain-words errors when offline or when a step fails.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field

from .errors import EnvironmentError, SetupCancelled

log = logging.getLogger("apk_builder")

CMDLINE_TOOLS_URL = (
    "https://dl.google.com/android/repository/"
    "commandlinetools-linux-13114758_latest.zip"
)
CMDLINE_TOOLS_NAME = "commandlinetools-linux-13114758_latest.zip"
SDK_PACKAGES = (
    "platform-tools",
    "platforms;android-35",
    "build-tools;35.0.0",
)
DOWNLOAD_CHUNK = 65536
DOWNLOAD_TIMEOUT_S = 30
JAVA_MIN_MAJOR = 17
SETUP_TIMEOUT_S = 900


# ---------------------------------------------------------------------------
# Machine sizing (U35: measured silently, never shown as settings)
# ---------------------------------------------------------------------------

def total_ram_gb() -> float:
    """Total RAM in gigabytes, from /proc/meminfo. Falls back to 8.0
    when the machine cannot be measured (the PC this app is built for
    has 8 GB)."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / 1024 / 1024
    except (OSError, ValueError, IndexError):
        pass
    return 8.0


def gradle_heap_for_ram(ram_gb: float) -> str:
    """Gradle JVM heap for the machine: small PCs get 1g, the 8 GB PC
    gets 2g, bigger machines get 4g. Capped so the desktop stays usable
    while a build runs (U25)."""
    if ram_gb <= 4.5:
        return "1g"
    if ram_gb <= 10.0:
        return "2g"
    return "4g"


def gradle_workers_for_ram(ram_gb: float) -> int:
    """Parallel build workers: 2 on the 8 GB PC, so the desktop never
    freezes during a build (U25)."""
    if ram_gb <= 10.0:
        return 2
    return 4


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r'"(\d+)(?:\.\d+)?(?:\.\d+)?')


def java_major_version(java_bin: str) -> int | None:
    """The major version of a java binary (17, 21, ...), or None when
    it cannot be run or its version cannot be read."""
    try:
        result = subprocess.run(
            [java_bin, "-version"], capture_output=True, text=True,
            timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stderr or "") + (result.stdout or "")
    match = _VERSION_RE.search(output)
    if not match:
        return None
    return int(match.group(1))


def find_java() -> tuple[str | None, int | None]:
    """(java binary path, major version), JAVA_HOME first, then PATH.
    (None, None) when no Java is installed."""
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = os.path.join(java_home, "bin", "java")
        if os.path.isfile(candidate):
            return candidate, java_major_version(candidate)
    found = shutil.which("java")
    if found:
        return found, java_major_version(found)
    return None, None


def _sdk_looks_usable(sdk_dir: str) -> bool:
    """True when the folder holds at least the cmdline-tools layout or
    a platform. A bare empty folder is not an SDK."""
    return os.path.isdir(os.path.join(sdk_dir, "cmdline-tools")) or \
        os.path.isdir(os.path.join(sdk_dir, "platforms"))


def find_sdk(explicit: str | None = None) -> str | None:
    """The Android SDK folder: the explicit setting first, then
    ANDROID_HOME, ANDROID_SDK_ROOT, ~/Android/Sdk, ~/android-sdk.
    None when no SDK folder is found."""
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    for env_name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, "Android", "Sdk"))
    candidates.append(os.path.join(home, "android-sdk"))
    for candidate in candidates:
        if candidate and os.path.isdir(candidate) \
                and _sdk_looks_usable(candidate):
            return os.path.abspath(candidate)
    return None


def default_sdk_dir() -> str:
    """Where a fresh guided setup puts the SDK."""
    return os.path.join(os.path.expanduser("~"), "Android", "Sdk")


@dataclass
class EnvironmentStatus:
    """Everything the app knows about the build tools."""

    java_path: str | None = None
    java_version: int | None = None
    sdk_dir: str | None = None
    has_cmdline_tools: bool = False
    has_platform_tools: bool = False
    has_platform: bool = False
    has_build_tools: bool = False
    ram_gb: float = 8.0
    missing: list[str] = field(default_factory=list)

    @property
    def java_ok(self) -> bool:
        return self.java_version is not None \
            and self.java_version >= JAVA_MIN_MAJOR

    @property
    def sdk_ok(self) -> bool:
        return bool(self.sdk_dir) and self.has_cmdline_tools \
            and self.has_platform_tools and self.has_platform \
            and self.has_build_tools

    @property
    def ready(self) -> bool:
        return self.java_ok and self.sdk_ok

    @property
    def gradle_heap(self) -> str:
        return gradle_heap_for_ram(self.ram_gb)

    @property
    def gradle_workers(self) -> int:
        return gradle_workers_for_ram(self.ram_gb)


def check_environment(sdk_override: str | None = None) -> EnvironmentStatus:
    """Check Java and the SDK. Never raises: anything missing lands in
    the status's missing list in plain words."""
    status = EnvironmentStatus(ram_gb=total_ram_gb())
    java_path, java_version = find_java()
    status.java_path = java_path
    status.java_version = java_version
    if java_path is None:
        status.missing.append(
            "Java is not installed. The build tools need Java 17.")
    elif java_version is not None and java_version < JAVA_MIN_MAJOR:
        status.missing.append(
            f"Java {java_version} is installed, but the build tools need "
            f"Java {JAVA_MIN_MAJOR} or newer.")
    elif java_version is None:
        status.missing.append(
            "Java is installed, but its version could not be read.")

    sdk_dir = find_sdk(sdk_override or None)
    status.sdk_dir = sdk_dir
    if sdk_dir is None:
        status.missing.append(
            "The Android build tools are not installed yet.")
        return status
    cmdline = os.path.join(sdk_dir, "cmdline-tools", "latest", "bin",
                           "sdkmanager")
    if not os.path.isfile(cmdline):
        cmdline = os.path.join(sdk_dir, "cmdline-tools", "bin", "sdkmanager")
    status.has_cmdline_tools = os.path.isfile(cmdline)
    status.has_platform_tools = os.path.isdir(
        os.path.join(sdk_dir, "platform-tools"))
    platforms = os.path.join(sdk_dir, "platforms")
    status.has_platform = os.path.isdir(platforms) and bool(
        [name for name in os.listdir(platforms)
         if name.startswith("android-")]) if os.path.isdir(platforms) else False
    build_tools = os.path.join(sdk_dir, "build-tools")
    status.has_build_tools = os.path.isdir(build_tools) and bool(
        os.listdir(build_tools)) if os.path.isdir(build_tools) else False
    if not status.has_cmdline_tools:
        status.missing.append("The SDK tool installer is missing.")
    if not status.has_platform_tools:
        status.missing.append("The platform tools are missing.")
    if not status.has_platform:
        status.missing.append("No Android platform is installed.")
    if not status.has_build_tools:
        status.missing.append("The build tools are missing.")
    return status


def sdkmanager_path(sdk_dir: str) -> str | None:
    """The sdkmanager binary inside an SDK, or None."""
    for rel in (os.path.join("cmdline-tools", "latest", "bin", "sdkmanager"),
                os.path.join("cmdline-tools", "bin", "sdkmanager")):
        candidate = os.path.join(sdk_dir, rel)
        if os.path.isfile(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Resumable download (U24)
# ---------------------------------------------------------------------------

def download_file_resumable(url: str, dest_path: str, progress_cb=None,
                            cancel=None) -> str:
    """Download a URL to dest_path, resuming a partial download when the
    server allows it. progress_cb(downloaded, total) fires per chunk,
    total None when the server did not say. cancel() is checked between
    chunks; a cancelled download raises SetupCancelled and keeps the
    partial file so the next try resumes it. Network trouble raises
    EnvironmentError with a plain reason."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    partial_path = dest_path + ".partial"
    done = 0
    if os.path.isfile(partial_path):
        done = os.path.getsize(partial_path)
    elif os.path.isfile(dest_path):
        return dest_path
    request = urllib.request.Request(url, headers={"User-Agent": "Simple APK"})
    if done:
        request.add_header("Range", f"bytes={done}-")
    try:
        response = urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S)
    except urllib.error.URLError as exc:
        raise EnvironmentError(
            f"Could not reach the download. Check the internet connection "
            f"and try again. ({exc.reason})")
    except TimeoutError:
        raise EnvironmentError(
            "The download timed out. Check the internet connection and "
            "try again.")
    total = None
    try:
        with response as resp:
            status = getattr(resp, "status", 200)
            if done and status != 206:
                # The server ignored the resume request: start over.
                done = 0
            length = resp.headers.get("Content-Length")
            if length:
                try:
                    total = int(length) + done
                except ValueError:
                    total = None
            if progress_cb is not None:
                progress_cb(done, total)
            mode = "ab" if done else "wb"
            with open(partial_path, mode) as fh:
                while True:
                    if cancel is not None and cancel():
                        raise SetupCancelled(
                            "The download was cancelled. It will pick up "
                            "where it left off next time.")
                    try:
                        chunk = resp.read(DOWNLOAD_CHUNK)
                    except TimeoutError:
                        raise EnvironmentError(
                            "The download timed out. It will pick up where "
                            "it left off next time.")
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress_cb is not None:
                        progress_cb(done, total)
    except urllib.error.URLError as exc:
        raise EnvironmentError(
            f"The download failed ({exc.reason}). It will pick up where "
            f"it left off next time.")
    os.replace(partial_path, dest_path)
    return dest_path


# ---------------------------------------------------------------------------
# Guided setup (U39: one button, progress, plain words)
# ---------------------------------------------------------------------------

def _run_quiet(args: list[str], env: dict | None = None,
               stdin_text: str | None = None,
               timeout: int = SETUP_TIMEOUT_S,
               cancel=None) -> subprocess.CompletedProcess:
    """Run a setup command, capturing output for the log. cancel() is
    checked while it runs; a cancelled command is killed and raises
    SetupCancelled, so the setup thread can always stop promptly."""
    import time as _time

    process = subprocess.Popen(
        args, env=env, stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if stdin_text:
        assert process.stdin is not None
        try:
            process.stdin.write(stdin_text)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    started = _time.monotonic()
    while True:
        if cancel is not None and cancel():
            process.kill()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            raise SetupCancelled("Setup was cancelled.")
        try:
            _out, _err = process.communicate(timeout=1)
            break
        except subprocess.TimeoutExpired:
            if _time.monotonic() - started > timeout:
                process.kill()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
                raise subprocess.TimeoutExpired(args, timeout)
    return subprocess.CompletedProcess(args, process.returncode, _out, _err)


def install_sdk(sdk_dir: str, download_dir: str, progress_cb=None,
                phase_cb=None, cancel=None,
                url: str = CMDLINE_TOOLS_URL) -> str:
    """Install the Android SDK pieces a build needs, into sdk_dir.

    Downloads the command line tools (resumable), unpacks them, accepts
    the SDK licenses, and installs platform-tools, one Android platform,
    and the build tools. phase_cb(text) names the current step in plain
    words; progress_cb(downloaded, total) reports the download.
    Returns the SDK dir. Raises EnvironmentError (plain words) or
    SetupCancelled.
    """
    def phase(text: str) -> None:
        log.info("Setup: %s", text)
        if phase_cb is not None:
            phase_cb(text)

    def cancelled() -> bool:
        return bool(cancel is not None and cancel())

    os.makedirs(sdk_dir, exist_ok=True)
    os.makedirs(download_dir, exist_ok=True)
    zip_path = os.path.join(download_dir, CMDLINE_TOOLS_NAME)
    phase("Downloading the build tools")
    download_file_resumable(url, zip_path, progress_cb, cancel)
    if cancelled():
        raise SetupCancelled("Setup was cancelled.")
    phase("Unpacking the build tools")
    latest_dir = os.path.join(sdk_dir, "cmdline-tools", "latest")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            tmp_dir = os.path.join(sdk_dir, "cmdline-tools", ".new")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            os.makedirs(tmp_dir, exist_ok=True)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = [p for p in info.filename.replace("\\", "/").split("/")
                         if p not in ("", ".", "..")]
                if not parts or ".." in info.filename.split("/"):
                    continue
                target = os.path.join(tmp_dir, *parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, DOWNLOAD_CHUNK)
            # The zip holds a top-level cmdline-tools/ folder; move its
            # contents into cmdline-tools/latest/.
            inner = os.path.join(tmp_dir, "cmdline-tools")
            if not os.path.isdir(inner):
                inner = tmp_dir
            shutil.rmtree(latest_dir, ignore_errors=True)
            os.makedirs(os.path.dirname(latest_dir), exist_ok=True)
            shutil.move(inner, latest_dir)
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except zipfile.BadZipFile:
        raise EnvironmentError(
            "The downloaded build tools file is damaged. Delete it and "
            "try the setup again.")
    manager = sdkmanager_path(sdk_dir)
    if manager is None:
        raise EnvironmentError(
            "The build tools unpacked, but the tool installer is missing "
            "from them. Try the setup again.")
    try:
        os.chmod(manager, 0o755)
    except OSError:
        pass
    java_bin = find_java()[0]
    env = dict(os.environ)
    env["ANDROID_HOME"] = sdk_dir
    env["ANDROID_SDK_ROOT"] = sdk_dir
    if java_bin:
        env["JAVA_HOME"] = os.path.dirname(os.path.dirname(java_bin))
    phase("Accepting the SDK licenses")
    try:
        result = _run_quiet(
            [manager, "--licenses"], env=env,
            stdin_text="y\n" * 40, cancel=cancel)
    except subprocess.TimeoutExpired:
        raise EnvironmentError(
            "Accepting the licenses took too long. Try the setup again.")
    if result.returncode != 0:
        log.warning("sdkmanager --licenses exited %s: %s",
                    result.returncode, (result.stderr or "")[-500:])
    if cancelled():
        raise SetupCancelled("Setup was cancelled.")
    phase("Installing the platform and build tools")
    try:
        result = _run_quiet([manager, *SDK_PACKAGES], env=env, cancel=cancel)
    except subprocess.TimeoutExpired:
        raise EnvironmentError(
            "Installing the platform took too long. Try the setup again.")
    if result.returncode != 0:
        detail = ((result.stderr or "") + (result.stdout or "")).strip()
        log.warning("sdkmanager install exited %s: %s",
                    result.returncode, detail[-500:])
        raise EnvironmentError(
            "Installing the platform and build tools did not finish. "
            "Check the internet connection and try the setup again.")
    return sdk_dir


def install_java_pkexec(log_fn=None, cancel=None) -> bool:
    """Install OpenJDK 17 through the system package manager, asking
    for the user's password with the system prompt. Returns True when
    Java 17 or newer is usable afterwards. cancel() is checked while it
    runs; a cancelled install is killed and returns False. Never raises."""
    import time as _time

    pkexec = shutil.which("pkexec")
    apt = shutil.which("apt")
    if not pkexec or not apt:
        return False
    try:
        process = subprocess.Popen(
            [pkexec, "apt", "install", "-y", "openjdk-17-jdk"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        log.warning("Java install did not run: %s", exc)
        return False
    started = _time.monotonic()
    while True:
        if cancel is not None and cancel():
            process.kill()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
            return False
        try:
            return_code = process.wait(timeout=1)
            break
        except subprocess.TimeoutExpired:
            if _time.monotonic() - started > SETUP_TIMEOUT_S:
                process.kill()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
                return False
    if return_code != 0:
        return False
    _path, version = find_java()
    return version is not None and version >= JAVA_MIN_MAJOR
