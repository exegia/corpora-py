#!/usr/bin/env bash
#
# archive.sh
# Shell equivalent of scripts/build/archive.py
#
# Provides two operations used by the build system:
#   - extract:  unpack a python-build-standalone tarball
#   - create:   produce an unsigned corpora-py-<platform>.zip archive
#
# Usage:
#   ./scripts/build/archive.sh extract <tarball> <dest>
#   ./scripts/build/archive.sh create  <python_dir> <out_dir> <platform_key>
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh" 2>/dev/null || true

usage() {
  cat <<'EOF'
Usage:
  archive.sh extract <tarball.tar.gz> <dest-dir>
  archive.sh create  <python-dir> <out-dir> <platform-key>

Options:
  -h, --help     Show this help

Notes:
  * "create" always produces: <out-dir>/corpora-py-<platform-key>.zip
  * macOS uses: ditto -c -k --keepParent  (preserves symlinks)
  * Other platforms use: zip -9 -r -y     (relative to python-dir's parent)
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

cmd_extract() {
  local tarball="$1"
  local dest="$2"

  [[ -f "$tarball" ]] || die "tarball not found: $tarball"

  echo "==> Extracting standalone Python..."
  if [[ -e "$dest" ]]; then
    rm -rf "$dest"
  fi
  mkdir -p "$dest"
  tar -xzf "$tarball" -C "$dest" --strip-components=1
}

cmd_create() {
  local python_dir="$1"
  local out_dir="$2"
  local platform_key="$3"

  [[ -d "$python_dir" ]] || die "python_dir not found: $python_dir"
  mkdir -p "$out_dir"

  local archive="$out_dir/corpora-py-${platform_key}.zip"
  echo "==> Creating unsigned archive: $(basename "$archive")"

  if [[ "$(uname -s)" == "Darwin" ]]; then
    ditto -c -k --keepParent "$python_dir" "$archive"
  else
    local parent name
    parent="$(dirname "$python_dir")"
    name="$(basename "$python_dir")"
    (
      cd "$parent"
      zip -9 -r -y "$archive" "$name"
    )
  fi

  echo "==> Created: $archive"
}

# --- arg parsing ---

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

case "$1" in
  -h|--help|help)
    usage
    exit 0
    ;;
  extract)
    [[ $# -eq 3 ]] || die "extract requires exactly 2 arguments: <tarball> <dest>"
    cmd_extract "$2" "$3"
    ;;
  create|archive)
    [[ $# -eq 4 ]] || die "create requires exactly 3 arguments: <python_dir> <out_dir> <platform_key>"
    cmd_create "$2" "$3" "$4"
    ;;
  *)
    die "unknown command: $1  (use 'extract' or 'create')"
    ;;
esac
