#!/usr/bin/env bash
#
# archive.sh
#
# Provides two operations used by the build system:
#   - extract:  unpack a python-build-standalone tarball
#   - create:   produce an unsigned corpora-py-<platform>.zip archive
#
# Usage:
#   ./scripts/build/archive.sh extract <tarball> <dest>
#   ./scripts/build/archive.sh create  <python_dir> <out_dir> <platform_key>
#
# Examples:
#   ./scripts/build/archive.sh extract .cache/python-standalone/cpython-...tar.gz example/build/lib/python
#   ./scripts/build/archive.sh create example/build/lib/python dist macos-arm64
#
# On macOS this uses `ditto` (best symlink preservation for Python runtimes).
# Elsewhere it falls back to `zip -9 -yr`.
#

set -euo pipefail

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
    # Replicate Python behavior:
    #   zf.write(f, f.relative_to(python_dir.parent))
    # The zip root will contain the basename of python_dir (e.g. "python/")
    local parent
    parent="$(dirname "$python_dir")"
    local name
    name="$(basename "$python_dir")"

    (
      cd "$parent"
      # -9 = max compression
      # -r = recursive
      # -y = store symlinks as symlinks (critical for pythonX -> pythonX.Y)
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
