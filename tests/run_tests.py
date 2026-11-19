#!/usr/bin/env python3
"""Test runner for Simple APK.

Usage (from the project directory):
    python3 tests/run_tests.py              # engine tests (no Qt needed)
    python3 tests/run_tests.py --gui        # engine + Qt GUI smoke tests
    python3 tests/run_tests.py -k project   # only modules matching "project"
    python3 tests/run_tests.py -v           # verbose

The GUI tests need the Qt test python and run offscreen:

    LD_LIBRARY_PATH=~/workspace/qt-libs/root/usr/lib/x86_64-linux-gnu \\
    TMPDIR=/tmp QT_QPA_PLATFORM=offscreen \\
    ~/workspace/forge-v2-testenv/bin/python tests/run_tests.py --gui

Default HOME (NEVER override HOME for Qt runs), TMPDIR=/tmp.

Plain unittest discovery also works:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import argparse
import os
import sys
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the apk_builder tests.")
    parser.add_argument("--gui", action="store_true",
                        help="also run the Qt GUI smoke tests (needs Qt)")
    parser.add_argument("-k", "--match", default=None,
                        help="only run test modules whose name contains this text")
    parser.add_argument("-v", "--verbose", action="count", default=1,
                        help="verbosity (repeat for more)")
    args = parser.parse_args(argv)

    loader = unittest.TestLoader()
    start_dir = os.path.join(PROJECT_DIR, "tests")
    suite = unittest.TestSuite()
    for name in sorted(os.listdir(start_dir)):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        module = name[:-3]
        if module == "test_gui_smoke" and not args.gui:
            continue
        if args.match and args.match not in module:
            continue
        suite.addTests(loader.loadTestsFromName(module))

    runner = unittest.TextTestRunner(verbosity=args.verbose)
    result = runner.run(suite)
    print()
    print(f"Ran {result.testsRun} test(s): "
          f"{len(result.failures)} failed, {len(result.errors)} errors, "
          f"{len(result.skipped)} skipped")
    if result.skipped:
        print("Skipped:")
        for test, reason in result.skipped:
            print(f"  - {test.id()}: {reason}")
    # Clean Qt teardown before interpreter shutdown: drop the suite
    # (which holds the test cases, which hold the windows), collect,
    # then quit the QApplication while its objects are still alive.
    # Without this the offscreen platform aborts at exit with a
    # malloc_consolidate error after the OK line.
    code = 0 if result.wasSuccessful() else 1
    del suite
    import gc
    gc.collect()
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
            app.quit()
            app.processEvents()
    except ImportError:
        pass
    gc.collect()
    return code


if __name__ == "__main__":
    sys.exit(main())
