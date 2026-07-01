#!/usr/bin/env bash
#
# wheel.sh
# Shell equivalent of scripts/build/wheel.py
#
# Build workspace wheels, find the umbrella wheel, and install into a standalone Python.
#
# Usage examples:
#   ./scripts/build/wheel.sh build [out-dir]
#   ./scripts/build/wheel.sh find [out-dir]
#   ./scripts/build/wheel.sh install <wheel> <python_dir> [--find-links <dir>]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

build_wheels() {
  local out_dir="${1:-$DIST_DIR}"
  mkdir -p "$out_dir"

  log "Building workspace wheels with uv..."
  run_cmd uv build --package corpora-shared-py --wheel "--out-dir=$out_dir"
  run_cmd uv build --package corpora-client-py --wheel "--out-dir=$out_dir"
  run_cmd uv build --package corpora-admin-py --wheel "--out-dir=$out_dir"
  # Umbrella last
  run_cmd uv build --wheel "--out-dir=$out_dir"

  find_wheel "$out_dir"
}

find_wheel() {
  local out_dir="${1:-$DIST_DIR}"

  # Prefer umbrella corpora_py-*.whl (newest)
  local umbrella
  umbrella=$(ls -t "$out_dir"/corpora_py-*.whl 2>/dev/null | head -1 || true)
  if [[ -n "$umbrella" ]]; then
    echo "$umbrella"
    return 0
  fi

  # Fallback: any .whl
  local any
  any=$(ls -t "$out_dir"/*.whl 2>/dev/null | head -1 || true)
  if [[ -n "$any" ]]; then
    echo "$any"
    return 0
  fi

  echo "No wheel found in $out_dir" >&2
  exit 1
}

install_wheel() {
  local wheel="$1"
  local python_dir="$2"
  local find_links=""

  shift 2 || true
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --find-links)
        find_links="$2"; shift 2 ;;
      *)
        shift ;;
    esac
  done

  log "Installing wheel with uv..."

  local python_bin
  if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
    python_bin="$python_dir/python.exe"
  else
    python_bin="$python_dir/bin/python3"
  fi

  local cmd=(uv pip install --python "$python_bin" --no-cache)

  if [[ -n "$find_links" ]]; then
    cmd+=(--find-links "$(cd "$find_links" && pwd)")
  fi

  # Support wheel[extra] syntax by passing the arg as-is
  cmd+=("$wheel")

  run_cmd "${cmd[@]}"
}

# --- dispatch ---

cmd="${1:-}"
shift || true

case "$cmd" in
  build)
    build_wheels "$@"
    ;;
  find)
    find_wheel "$@"
    ;;
  install)
    install_wheel "$@"
    ;;
  *)
    echo "Usage:"
    echo "  $(basename "$0") build [out-dir]"
    echo "  $(basename "$0") find  [out-dir]"
    echo "  $(basename "$0") install <wheel-spec> <python_dir> [--find-links DIR]"
    exit 1
    ;;
esac
