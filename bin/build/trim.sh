#!/usr/bin/env bash
#
# trim.sh
#
# Usage:
#   ./scripts/build/trim.sh <python_dir>
#   ./scripts/build/trim.sh --clean-up <dest_dir>
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

trim_stdlib() {
  local python_dir="$1"
  log "Trimming stdlib..."

  local pylib
  pylib="$(pylib_dir "$python_dir")"

  for item in "${STDLIB_TRIM[@]}"; do
    local target="$pylib/$item"
    if [[ -e "$target" ]]; then
      echo "  removing $item"
      rm -rf "$target"
    fi
  done

  # Remove __pycache__, *.pyc, and .a files (Unix)
  if [[ "$(uname -s)" != MINGW* && "$(uname -s)" != MSYS* && "$(uname -s)" != CYGWIN* ]]; then
    find "$python_dir" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find "$python_dir" -name "*.pyc" -delete 2>/dev/null || true
    find "$python_dir/lib" -name "*.a" -delete 2>/dev/null || true
  else
    find "$python_dir" -name "*.pyc" -delete 2>/dev/null || true
    find "$python_dir" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
  fi

  # Remove heavy top-level dirs that are not needed in the runtime
  for d in share man "lib/pkgconfig" include; do
    if [[ -e "$python_dir/$d" ]]; then
      rm -rf "$python_dir/$d"
    fi
  done
}

clean_up() {
  local dest_dir="$1"
  log "Cleaning up $dest_dir ..."

  # pyc / __pycache__
  find "$dest_dir" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$dest_dir" -name "*.pyc" -delete 2>/dev/null || true

  for d in share man "lib/pkgconfig" include; do
    rm -rf "$dest_dir/$d" 2>/dev/null || true
  done

  # .a files on Unix
  if [[ "$(uname -s)" != MINGW* && "$(uname -s)" != MSYS* && "$(uname -s)" != CYGWIN* ]]; then
    find "$dest_dir" -name "*.a" -delete 2>/dev/null || true
  fi

  # Remove pip/wheel/setuptools installers from site-packages
  local pylib
  pylib="$(pylib_dir "$dest_dir")"
  for tool in pip wheel setuptools; do
    rm -rf "$pylib/site-packages/$tool" 2>/dev/null || true
    rm -rf "$pylib/site-packages/${tool}"*.dist-info 2>/dev/null || true
  done
}

# --- main ---

if [[ $# -eq 0 ]]; then
  echo "Usage:"
  echo "  $(basename "$0") <python_dir>           # trim_stdlib"
  echo "  $(basename "$0") --clean-up <dest_dir>  # clean_up"
  exit 1
fi

case "$1" in
  --clean-up)
    clean_up "${2:-}"
    ;;
  *)
    trim_stdlib "$1"
    ;;
esac
