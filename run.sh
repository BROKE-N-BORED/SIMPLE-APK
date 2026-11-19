#!/usr/bin/env bash
# Launcher for Simple APK.
# Run from anywhere: changes to this script's directory and starts the app.
set -e
cd "$(dirname "$0")"
exec python3 -m apk_builder "$@"
