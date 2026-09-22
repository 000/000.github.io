#!/usr/bin/env bash
# Idempotent bootstrap for the defense.engineer static site + RECALC toolkit.
# Runs after the repository is checked out. Safe to run repeatedly.
set -euo pipefail

cd "$(dirname "$0")/.."

# The Python "venv" module needs ensurepip, which is packaged separately on
# Debian/Ubuntu. Install it only when missing so reruns stay fast.
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends python3-venv
fi

# Create the project virtual environment if it does not already exist.
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

# Install/refresh Python dependencies for compare_init.py.
./.venv/bin/python -m pip install --upgrade pip --quiet
./.venv/bin/python -m pip install --quiet -r requirements.txt

echo "Environment ready. Static site served on :8000; run the RECALC engine with ./.venv/bin/python compare_init.py --help"
