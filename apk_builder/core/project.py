"""Project handling for Simple APK: safe unzip and project detection.

Qt-free, stdlib only, so the UI can drive it from a worker thread and
the tests can run it without Qt.

Rules from the design rules:
- U32 never silently skip: every zip entry that could not be read is
  listed with its reason, and the UI shows that list.
- U29 friendly plain errors, never dead ends: detection problems are
  plain-words issues on the result, not exceptions, whenever the app
  can still say what to do next.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field

from .errors import ProjectError

log = logging.getLogger("apk_builder")

SETTINGS_FILES = ("settings.gradle", "settings.gradle.kts")
APP_BUILD_FILES = ("app/build.gradle", "app/build.gradle.kts")
WRAPPER_JAR = os.path.join("gradle", "wrapper", "gradle-wrapper.jar")


@dataclass
class SkippedEntry:
    """One thing that could not be read, with its reason (U32)."""

    name: str
    reason: str


@dataclass
class ExtractResult:
    """What came out of a zip."""

    dest_dir: str
    files: int = 0
    total_bytes: int = 0
    skipped: list[SkippedEntry] = field(default_factory=list)


@dataclass
class ProjectInfo:
    """What the app found in a picked zip or folder."""

    root: str
    source_label: str
    has_settings: bool = False
    has_app_build: bool = False
    has_gradlew: bool = False
    has_wrapper_jar: bool = False
    gradle_files: list[str] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def is_android_project(self) -> bool:
        """True when the folder looks like an Android Gradle project."""
        return self.has_settings and self.has_app_build

    @property
    def can_build(self) -> bool:
        """True when the app has a way to run the build."""
        return self.is_android_project and (
            self.has_gradlew or self.has_wrapper_jar
        )

    @property
    def build_blocker(self) -> str | None:
        """Plain-words reason the project cannot build, or None."""
        if not self.is_android_project:
            return (
                "This does not look like an Android app project. "
                "It needs a settings file and an app build file."
            )
        if not self.has_gradlew and not self.has_wrapper_jar:
            return (
                "This project has no build starter (gradlew) and no "
                "wrapper file, so the app cannot start its build. "
                "Ask whoever made the project to include the wrapper."
            )
        return None


def _safe_entry_name(name: str) -> list[str] | None:
    """A zip entry as safe path parts, or None when it escapes the
    destination (absolute path or ..). Backslashes are treated as
    separators, so a Windows-made zip cannot smuggle a path through."""
    if not name or os.path.isabs(name):
        return None
    parts = [part for part in name.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return parts


def safe_extract_zip(zip_path: str, dest_dir: str, on_progress=None,
                     should_cancel=None) -> ExtractResult:
    """Unpack a zip with a zip-slip guard.

    Every entry that cannot be read (unsafe path, damaged entry, write
    failure) is recorded in the result's skipped list with its reason
    instead of stopping the whole unpack (U32). on_progress(done, total)
    fires per entry. should_cancel() is checked between entries; a
    cancelled unpack raises ProjectError after cleaning up.
    """
    if not os.path.isfile(zip_path):
        raise ProjectError("That zip file is no longer there. Pick it again.")
    os.makedirs(dest_dir, exist_ok=True)
    result = ExtractResult(dest_dir=dest_dir)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            total = len(infos)
            for index, info in enumerate(infos):
                if should_cancel is not None and should_cancel():
                    raise ProjectError("Unpacking was cancelled.")
                if on_progress is not None:
                    on_progress(index, total)
                if info.is_dir():
                    continue
                parts = _safe_entry_name(info.filename)
                if parts is None:
                    result.skipped.append(SkippedEntry(
                        info.filename,
                        "Unsafe path inside the zip, left out on purpose."))
                    continue
                target = os.path.join(dest_dir, *parts)
                try:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, 65536)
                    result.files += 1
                    result.total_bytes += info.file_size
                except Exception as exc:  # noqa: BLE001 - one bad entry
                    # must not sink the whole unpack; it is listed instead.
                    log.warning("Could not unpack %s: %s", info.filename, exc)
                    result.skipped.append(SkippedEntry(
                        info.filename, f"Could not be read: {exc}"))
                    try:
                        os.remove(target)
                    except OSError:
                        pass
            if on_progress is not None:
                on_progress(total, total)
    except zipfile.BadZipFile:
        raise ProjectError(
            "That file is not a zip file, or the zip file is damaged. "
            "Pick a different file.")
    return result


def find_project_root(base_dir: str) -> str:
    """The project root inside an unpacked folder.

    Many zips hold one top-level folder with the project inside it; that
    folder is the project root. Otherwise the base dir itself is.
    """
    if _looks_like_project(base_dir):
        return base_dir
    try:
        children = [
            os.path.join(base_dir, name)
            for name in sorted(os.listdir(base_dir))
            if os.path.isdir(os.path.join(base_dir, name))
        ]
    except OSError:
        return base_dir
    if len(children) == 1 and _looks_like_project(children[0]):
        return children[0]
    return base_dir


def _looks_like_project(directory: str) -> bool:
    """True when the directory holds the two files that mark an Android
    Gradle project."""
    return (
        any(os.path.isfile(os.path.join(directory, name))
            for name in SETTINGS_FILES)
        and any(os.path.isfile(os.path.join(directory, name))
                for name in APP_BUILD_FILES)
    )


def detect_project(root: str, source_label: str,
                   skipped: list[SkippedEntry] | None = None) -> ProjectInfo:
    """Describe what is in a project folder, in plain words.

    Never raises for a folder that simply is not a project: the issues
    list carries the plain-words explanation instead (U29).
    """
    info = ProjectInfo(root=root, source_label=source_label,
                       skipped=list(skipped or []))
    if not os.path.isdir(root):
        info.issues.append("That folder is no longer there.")
        return info
    info.has_settings = any(
        os.path.isfile(os.path.join(root, name)) for name in SETTINGS_FILES)
    info.has_app_build = any(
        os.path.isfile(os.path.join(root, name)) for name in APP_BUILD_FILES)
    info.has_gradlew = os.path.isfile(os.path.join(root, "gradlew"))
    info.has_wrapper_jar = os.path.isfile(os.path.join(root, WRAPPER_JAR))
    for name in sorted(os.listdir(root)):
        if name.endswith((".gradle", ".gradle.kts", ".properties")):
            info.gradle_files.append(name)
    if not info.has_settings:
        info.issues.append(
            "No settings file found (settings.gradle). Without it, the "
            "app cannot tell this is an Android project.")
    if not info.has_app_build:
        info.issues.append(
            "No app build file found (app/build.gradle). Without it, "
            "there is no app to build.")
    if info.is_android_project and not info.has_gradlew \
            and not info.has_wrapper_jar:
        info.issues.append(
            "No build starter found (gradlew) and no wrapper file. "
            "The project needs one of them to build.")
    return info


def _work_folder_name(source_label: str) -> str:
    """A safe, unique work folder name for a picked zip."""
    stem = os.path.splitext(os.path.basename(source_label))[0]
    safe = "".join(
        char if char.isalnum() or char in ("-", "_") else "_"
        for char in stem
    ) or "project"
    return f"{safe}-{int(time.time())}"


@dataclass
class PrepareResult:
    """The outcome of preparing a picked zip or folder for building."""

    project: ProjectInfo
    work_dir: str | None  # The unpacked copy, for zips; None for folders.
    extracted_files: int = 0


def prepare_source(path: str, work_root: str, on_progress=None,
                   should_cancel=None) -> PrepareResult:
    """Prepare a picked zip or folder for building.

    A zip is unpacked into a fresh work folder under work_root (the
    original zip is never changed). A folder is used as it is: the
    build writes its outputs into the project, which is how Android
    builds normally work. Returns the detected project either way.
    """
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        work_dir = os.path.join(
            work_root, _work_folder_name(os.path.basename(path)))
        extracted = safe_extract_zip(path, work_dir, on_progress,
                                     should_cancel)
        root = find_project_root(work_dir)
        project = detect_project(
            root, os.path.basename(path), skipped=extracted.skipped)
        return PrepareResult(project=project, work_dir=work_dir,
                             extracted_files=extracted.files)
    if os.path.isdir(path):
        project = detect_project(os.path.abspath(path),
                                 os.path.basename(os.path.abspath(path)))
        return PrepareResult(project=project, work_dir=None)
    raise ProjectError(
        "Pick a zip file or a folder. That path is neither.")


def clear_work_folders(work_root: str) -> int:
    """Remove every unpacked work folder. Returns how many were removed.
    The original zips and folders the user picked are never touched."""
    removed = 0
    if not os.path.isdir(work_root):
        return 0
    for name in os.listdir(work_root):
        target = os.path.join(work_root, name)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
            removed += 1
    return removed
