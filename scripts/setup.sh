#!/usr/bin/env bash
# Sets up and launches Prosody for development on Linux/macOS.
# The shipping target is Windows; this exists so the app can be worked on
# anywhere. FL Studio, and therefore rendering and stems, remain unavailable.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
command -v npm     >/dev/null || { echo "node/npm is required"; exit 1; }
command -v cargo   >/dev/null || { echo "rust/cargo is required"; exit 1; }

[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -e ".[dev]"
./.venv/bin/flpf doctor || true

export PROSODY_PYTHON="$repo/.venv/bin/python"

cd apps/desktop
[ -d node_modules ] || npm install
exec npm run app
