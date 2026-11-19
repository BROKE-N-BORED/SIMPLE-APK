# Simple APK

Turn Android app source into an installable app file. Pick a zip file
or a folder, press Build, get an APK. No terminal needed.

Version 0.2. Python 3.10+, PySide6, standard library only. Hard $0.

## How to use it

1. **Pick your app.** Choose a zip file or a folder with the app source.
   A zip is unpacked into a work folder first; the original zip is never
   changed. A folder is used as it is.
2. **Build it.** Press Build and wait. The first build takes a few
   minutes. The Build Log window shows the build's own words as they come.
3. **Done.** The finished APK is copied to the output folder
   (`Simple APK` in your home folder, unless you changed it in
   Settings). Open Folder shows it.

The first build needs Java 17 and the Android build tools on the PC.
Open Windows, then First-Time Setup: it guides the whole setup once
(Java through the system package manager, then the build tools download,
licenses, and platform install). After that, builds just work.

The Help menu holds How to Use, a full index of how every part works.

## Install

Double-click **Install Simple APK**. That is the whole install: it
copies the app to your home folder and adds it to the applications
menu. Or run `bash install.sh` in a terminal.

To run from the source folder without installing: `bash run.sh`.

## What it needs

- Linux Mint (or another Debian-based Linux), Python 3.10+, PySide6
  (the installer provides it when it is missing).
- Java 17 or newer, and the Android SDK (command line tools, platform
  tools, one platform, build tools). The app's First-Time Setup
  installs both with guidance; they are not part of the app install.
- Internet for the first-time setup and for the first build of a
  project (the build engine downloads once, then is reused).

## Where files live

- Settings: `~/.config/simple-apk/settings.json`
- Logs: `~/.local/share/simple-apk/logs/` (rotating, 1 MB x 3)
- Unpacked zips: `~/.local/share/simple-apk/work/` (File, then Clear
  Work Files removes them; originals are never touched)
- Finished APKs: `~/Simple APK` (changeable in Settings)
- SDK (guided setup): `~/Android/Sdk`

## Updates

The app checks for a newer release when it starts, at most once a day.
Up to date means nothing happens. A newer version asks once, and only
downloads when you say yes. Downloads are checked against the release
checksum before installing. After installing, it asks whether to
restart now or later.

Note: the release repo is https://github.com/BROKE-N-BORED/SIMPLE-APK
(Joshua creates it). Until it exists and carries a Release, update
checks find nothing and no update is ever offered. The repo is baked
in as `REPO` in `apk_builder/core/updates.py`.

## Honest status (v0.2)

v0.1 shipped on 2026-11-18 and ran on a real Mint PC the same night.
Two defects showed there that the sandbox checks could not see, and
v0.2 fixes both:

- The secondary windows (First-Time Setup, Build Log, Settings, How
  to Use) painted inside the main window with no background, so the
  main window showed through them. They are real windows now.
- First-Time Setup died at the license step with a raw "I/O
  operation on closed file" error, so the build tools never finished
  installing. The faulty pipe handling is rewritten, and unexpected
  errors now reach the user in plain words, never as raw text.

Also in v0.2: installing from a fresh clone now falls back to the SVG
icon when the PNG icons are not there.

Verified here: the full test suite (84 tests; 7 new ones guard
exactly these defects), a probe that reproduced the closed-file
error on the old code and passes on the fix, and a screen check of
First-Time Setup open over the main window. The Gradle daemon still
cannot run in this sandbox (proven three times with the NEO
project), so two checks still wait for a real PC: First-Time Setup
running to completion, and the first real Gradle build. Build the
NEO project first: it is a complete project with its wrapper
included.

## Building the release zip

    python3 build_zip.py [--version 0.2] [--out dist/]

Writes `simple-apk-linux-<version>.zip` plus its `.sha256` sidecar,
and self-checks the stored file modes. Publish the zip and the sidecar
together, or the updater will never offer the release.

## Tests

    python3 tests/run_tests.py            # engine tests (no Qt needed)
    python3 tests/run_tests.py --gui      # engine + Qt GUI smoke tests

The GUI tests need the Qt test python and run offscreen; see
`tests/run_tests.py` for the exact command.

## Design

Built to the studio design rules (`design-rules.md`): one function one
window, simple enough for a child to use, no clutter. Techniques
pulled from the BNB UI Design Source File Library: progressive
disclosure (012), calm technology (003), delight done right (008).
See DESIGN.md for the full record, and CONTRACT.md for the module
contract.
