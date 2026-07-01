#!/usr/bin/env bash
#
# setup.sh
# Shell equivalent of scripts/setup.py
#
# Installation script for the project.
#
# Steps:
#   1. Install workspace dependencies via `uv sync`.
#   2. Install `dotenvx`.
#   3. Install demo app (Bun) dependencies.
#   4. Build embedded Python runtime for the demo (if not already present).
#
# Usage:
#   ./scripts/setup.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=utils.sh
source "$SCRIPT_DIR/utils.sh"

is_uv_install() {
  ensure_tool \
    "uv" \
    "error: \`uv\` is required. Install from https://docs.astral.sh/uv/" \
    'curl -LsSf https://astral.sh/uv/install.sh | sh'
}

sync_dependencies() {
  echo
  echo "[1/3] Syncing workspace dependencies..."
  run --no-dotenvx -- "uv" "sync"
}

install_dotenvx() {
  echo
  echo "[2/3] Installing dotenvx (encrypted .env loader)..."
  run --no-dotenvx -- "uv" "add" "dotenvx"
}

install_demo_deps() {
  echo
  echo "[3/4] Installing the demo app dependencies..."
  run --no-dotenvx --dir "$DEMO_APP_DIR" -- "bun" "install" "--no-cache"
}

build_demo_python_runtime() {
  echo
  echo "[4/4] Ensuring embedded Python runtime for the demo..."

  # Prefer the shell implementation if present
  if [[ -x "$SCRIPT_DIR/build/embedded.sh" ]]; then
    "$SCRIPT_DIR/build/embedded.sh"
  else
    # Fall back to the Python entry point (uv run style)
    run --no-dotenvx -- python -m scripts.build.embedded
  fi
}

main() {
  is_uv_install
  sync_dependencies
  install_dotenvx
  install_demo_deps
  build_demo_python_runtime

  echo
  echo "Setup complete."
}

main "$@"
