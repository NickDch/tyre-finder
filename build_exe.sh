#!/usr/bin/env bash
# Builds a native executable with PyInstaller (Linux/macOS). Pass "onefile" for a single file.
set -euo pipefail
cd "$(dirname "$0")"
mode="--onedir"
[ "${1:-}" = "onefile" ] && mode="--onefile"
uv sync --quiet
uv run --with pyinstaller pyinstaller --noconfirm --clean --windowed "$mode" \
    --name TyreFinder --paths src --collect-submodules tyre_finder packaging/launcher.py
echo "Done. Output is in dist/"
