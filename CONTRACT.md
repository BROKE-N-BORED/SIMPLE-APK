# Simple APK — shared contract (READ FIRST)

Package: `apk_builder`. Entry: `python3 -m apk_builder`
(`apk_builder/__main__.py` + `main.py`). Python 3.10+, PySide6,
stdlib only. No other third-party deps. Hard $0. No secrets in code.

Design rules: `~/workspace/design-rules.md` (toy test, cheap motion
only, select NOTHING by default, no bare `&` in visible labels, no
em-dashes in visible UI text, one function one window). AGENTS.md
Qt/zip/installer lessons apply. Techniques and identity: DESIGN.md.

## Paths (XDG, Linux)
- Settings JSON: `~/.config/simple-apk/settings.json` (atomic save: tmp + os.replace)
- Logs: `~/.local/share/simple-apk/logs/` with rollover (1 MB x 3)
- Work (unpacked zips): `~/.local/share/simple-apk/work/`
- Default output folder: `~/Simple APK`
- Default SDK dir (guided setup): `~/Android/Sdk`
- Download cache (resumable setup download): `~/.simple-apk-downloads`
  beside the SDK dir (same filesystem as the SDK, never /tmp)

## core/project.py
- `SkippedEntry(name, reason)` dataclass: one thing that could not be
  read, with its reason (U32, never silently skip).
- `ExtractResult(dest_dir, files, total_bytes, skipped)`.
- `ProjectInfo(root, source_label, has_settings, has_app_build,
  has_gradlew, has_wrapper_jar, gradle_files, skipped, issues)`:
  `is_android_project` (settings + app build file), `can_build`
  (project + gradlew or wrapper jar), `build_blocker` (plain words).
- `safe_extract_zip(zip_path, dest_dir, on_progress=None,
  should_cancel=None) -> ExtractResult`: zip-slip guard (absolute
  paths and .. rejected and LISTED, not fatal); one bad entry never
  sinks the unpack; cancelled unpack raises ProjectError.
- `find_project_root(base_dir) -> str`: unwraps a single top-level
  folder when it holds the project.
- `detect_project(root, source_label, skipped=None) -> ProjectInfo`:
  never raises for a folder that is not a project; issues carry the
  plain-words explanation.
- `prepare_source(path, work_root, on_progress=None, should_cancel=None)
  -> PrepareResult(project, work_dir, extracted_files)`: zips are
  unpacked to a fresh work folder; folders are used as they are.
- `clear_work_folders(work_root) -> int`: removes unpacked work
  folders only; originals are never touched.

## core/environment.py
- `total_ram_gb() -> float` (/proc/meminfo, falls back to 8.0).
- `gradle_heap_for_ram(ram_gb) -> str`: 1g at <=4.5 GB, 2g at <=10 GB,
  4g above. `gradle_workers_for_ram(ram_gb) -> int`: 2 at <=10 GB, 4
  above (U25: the desktop stays usable during a build).
- `java_major_version(java_bin) -> int | None`,
  `find_java() -> (path | None, version | None)` (JAVA_HOME, then PATH).
- `find_sdk(explicit=None) -> str | None` (explicit setting,
  ANDROID_HOME, ANDROID_SDK_ROOT, ~/Android/Sdk, ~/android-sdk).
- `EnvironmentStatus`: java_path, java_version, sdk_dir,
  has_cmdline_tools, has_platform_tools, has_platform, has_build_tools,
  ram_gb, missing (plain words). `java_ok` (version >= 17), `sdk_ok`,
  `ready`, `gradle_heap`, `gradle_workers`.
- `check_environment(sdk_override=None) -> EnvironmentStatus`: never
  raises; anything missing lands in `missing`.
- `sdkmanager_path(sdk_dir) -> str | None`.
- `download_file_resumable(url, dest_path, progress_cb=None, cancel=None)
  -> str`: Range resume over a .partial file; cancelled downloads keep
  the partial file for the next try (U24).
- `install_sdk(sdk_dir, download_dir, progress_cb=None, phase_cb=None,
  cancel=None, url=CMDLINE_TOOLS_URL) -> str`: download, unpack to
  cmdline-tools/latest, accept licenses, install platform-tools,
  platforms;android-35, build-tools;35.0.0.
- `install_java_pkexec(log_fn=None) -> bool`: pkexec apt install
  openjdk-17-jdk; True when Java 17+ is usable afterwards. Never raises.

## core/build.py
- `ApkInfo(path, name, size, package, version_name, version_code)`.
- `BuildResult(success, return_code, elapsed_seconds, apks, cancelled,
  message)`.
- `find_apks(project_root) -> list[str]`: app/build/outputs/apk/**/debug
  (flavours included), newest first.
- `find_aapt2(sdk_dir) -> str | None` (newest build-tools),
  `parse_badging(text) -> dict`, `apk_info(apk_path, aapt2=None)`.
- `copy_apks(apk_paths, out_dir, aapt2=None) -> list[ApkInfo]`:
  never-overwrite naming (name_1.apk, ...).
- `build_command(project_root, java_bin) -> list[str]`: gradlew when
  present (chmod +x first: zips often lose the execute bit); `java -jar
  gradle/wrapper/gradle-wrapper.jar assembleDebug` when gradlew is
  missing but the jar is present; BuildError (plain words) otherwise.
- `build_env(env_status) -> dict`: SDK + Java locations, GRADLE_OPTS
  with the machine-sized heap (U35).
- `run_build(project_root, env_status, on_line=None, should_cancel=None)
  -> BuildResult`: streams lines, kills the whole process group on
  cancel, runs with --max-workers (machine-sized) and --console=plain.

## core/settings.py
- `Settings` dataclass: `output_folder` (default `~/Simple APK`),
  `sdk_folder` ("" = auto-detect), `check_updates_on_startup: bool =
  True`, `last_update_check: float = 0.0` (bookkeeping, never shown),
  `window_geometry: dict | None = None`.
- `SettingsManager(path=None)`: `.current`, `.save()` (atomic tmp +
  os.replace), defaults on missing/corrupt file.
- Only settings a user would ever change live here (U36).

## core/errors.py
- `describe(exc) -> str`: plain-language messages; BuildError,
  ProjectError, EnvironmentError, SetupCancelled pass through;
  BadZipFile, PermissionError, FileNotFoundError, disk full, timeout
  each get a plain message with a next step. No em-dashes.
- `format_bytes(count)`, `format_seconds(seconds)`.

## core/logutil.py
- `setup_logging() -> logging.Logger`: file logs under the XDG logs
  dir, RotatingFileHandler (1 MB x 3), plus a last-200 ring buffer.
  Name the logger "apk_builder".
- `ring_lines() -> list[str]`, `log_exception`, `log_traceback`,
  `scrub_text` (home dir to ~, credential-looking values removed),
  `build_debug_report(version) -> str` (scrubbed, safe to paste).

## core/updates.py
- `REPO = ""` PLACEHOLDER: the GitHub repo does not exist yet. While
  it is empty, `check_for_update` returns {"state": "unknown"} and no
  update is ever offered. Set it to "owner/repo" when Joshua creates
  the repo. API base overridable for tests via APKB_UPDATE_API_BASE.
- `parse_version` / `compare_versions` / `is_newer` (plain incrementing
  versions, "v" prefix tolerated).
- `check_for_update(current_version, base=None, urlopen=None) -> dict`,
  never raises for a network or parsing problem:
  `{"state": "newer", "version", "tag", "zip_url", "sidecar_url",
  "page_url", "latest"}` / `{"state": "current", "latest": ...}` /
  `{"state": "unknown", "latest": None, "reason": <plain words>}`.
- Release selection is by ASSET NAME, never by tag: a release only
  counts when it is not a draft, not a prerelease, and carries BOTH
  `simple-apk-linux-<ver>.zip` AND its `.zip.sha256` sidecar for the
  same version. `newest_linux_release(releases)` /
  `find_linux_update(releases, current_version)`.
- `download_update(info, dest_dir, progress_cb=None, cancel=None,
  urlopen=None) -> {"zip_path", "version", "sha256"}`: streams the zip,
  SHA-256-checks it against the sidecar. A mismatch, a missing or
  unreadable sidecar, or a missing version raises `UpdateError` and the
  download is thrown away; a cancelled download raises `UpdateCancelled`
  and its partial file is removed.
- `apply_update(zip_path, version, install_dir=None, python=None)`:
  atomic swap (extract + version check, stage the new tree, move the
  keep-list `venv`, `logs`, swap, verify the new tree imports, roll
  back on failure). Any failure before the swap leaves the old install
  untouched and moves the keep-list back.
- `is_installed(pkg_dir=None) -> bool`: true only when the package's
  parent dir holds the launcher file `simple-apk`.

## ui/ (PySide6)
- Main window 1100x680, minimum 900x560. Three step cards only (U34):
  1 Pick your app, 2 Build it, 3 Done. Status light + status line at
  the bottom (U16). Geometry remembered via QSettings, validated
  against the screen (U5).
- Menu bar (U38): File (Pick a Zip File, Pick a Folder, Open Output
  Folder, Clear Work Files, Quit), Windows (Build Log, First-Time
  Setup, Settings), Help (How to Use, Check for Updates, checkable
  "Check for updates on startup", Copy Debug Report, About).
- Separate windows (U1): LogWindow (live build lines, elapsed time,
  Copy log, Clear), SetupWindow (checklist, Install Java, Set up the
  build tools with progress + cancel), SettingsWindow (output folder,
  SDK folder, updates checkbox, Open Logs, Copy Debug Report),
  HelpWindow (How to Use index, U22).
- `ui/workers.py`: PrepareWorker, BuildWorker, EnvCheckWorker,
  SetupWorker, JavaInstallWorker (QObject on QThread, signals only).
- `ui/updates_ui.py`: UpdateCheckWorker, UpdateApplyWorker,
  UpdateDialog (installed: Update / Later; source run: Open the
  release page / Close), UpdateProgressDialog (Cancel disabled once
  Installing starts).
- UI behavior: `main()` calls `MainWindow.start_silent_update_check()`
  once per launch, after `window.show()`; gated on
  `Settings.check_updates_on_startup` AND a 24-hour interval
  (`last_update_check` in settings). Silent check: an update found
  shows the update dialog; up to date shows nothing; failure shows a
  status-bar line at most, never a modal. Manual check: up to date and
  failure both show a dialog. Only one check runs at a time. The pull
  flow downloads to a temp dir, applies, then asks "Restart now to
  complete the update?": Yes relaunches via the installed launcher
  detached and quits; No closes the prompt and the update completes on
  next launch.
- Close-during-build guard (confirm dialog, defaults to No, U31).
  Clear Work Files confirms, defaults to No (U23).
- Finish moment (008): a check fades in over 200 ms on step 3
  (opacity only, no layout motion).
- NO bare `&` in any visible label. NO em-dashes in visible UI text.
  Select nothing by default. Cheap motion only.

## main.py
- QApplication setup, stylesheet from `ui/theme.py`, global exception
  handler with a friendly dialog, single instance via QLocalServer
  (U27: a second launch asks the running copy to come forward),
  one silent update check per launch, shutdown save.

## tests/ (unittest, stdlib only + Qt smoke)
- Engine tests: zip handling (zip-slip, unwrap, bad zip, NEO zip),
  project detection, environment (RAM sizing, Java parse, SDK
  detection, resumable download against a local server), build
  (APK finding, never-overwrite copy, badging parse, command
  selection), updates (versions, placeholder repo, asset selection,
  sidecar), settings round-trip, log ring buffer + report scrubbing.
- Qt GUI tests run with `QT_QPA_PLATFORM=offscreen` +
  `LD_LIBRARY_PATH=~/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu`,
  default HOME (NEVER override HOME for Qt runs), `TMPDIR=/tmp`.
  Qt test python: `~/workspace/forge-v2-testenv/bin/python` (PySide6 6.12.0).
- GUI smoke drives the real flows: pick the NEO zip through
  `MainWindow.pick_source`, error paths, screenshots at 1100x680.

## Out of scope (do NOT build in v0.1)
Signed release builds (debug APKs only), flavour/variant picking,
installing the APK to a phone over USB, building from a repo URL,
multiple projects at once. The first real Gradle build happens on
Joshua's Mint PC (the sandbox Gradle daemon cannot run; see README).
