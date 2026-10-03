#!/usr/bin/env bash
# Self-bootstrapping launcher for Unified Base.
# Creates its own venv on first run — no sudo, no prompts.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "First run: creating venv..."
    python3 -m venv .venv
fi
./.venv/bin/python -m pip install -q --disable-pip-version-check --no-input -r requirements.txt
exec ./.venv/bin/python main.py "$@"
