#!/usr/bin/env bash
# Launcher for Tyre Finder (Linux/macOS). Uses uv if available, otherwise a local venv with pip.
set -euo pipefail
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
    uv sync --quiet
    exec uv run tyre-finder
fi
if [ ! -x .venv/bin/python ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip >/dev/null
    .venv/bin/python -m pip install -e .
fi
exec .venv/bin/python -m tyre_finder.app
