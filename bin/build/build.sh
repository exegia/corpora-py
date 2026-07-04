#!/usr/bin/env bash
#
# build.sh
# Shell equivalent of the main build in scripts/build/__init__.py
#
# Builds the sidecar / Tauri resource bundle:
#   - build wheels
#   - download standalone python
#   - extract + install wheel
#   - trim
#   - generate app_paths
#   - sign (or unsigned) + archive
#
# Usage:
#   ./scripts/build/build.sh [--platform <p>] [--out-dir <d>] [--dest-dir <d>] [--cache-dir <c>]
#                            [--skip-sign] [--skip-build]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PLATFORM_KEY=""
OUT_DIR="lib"
DEST_DIR="lib/lib/python"
CACHE_DIR=".cache/python-standalone"
SKIP_SIGN=false
SKIP_BUILD=false

usage() {
  cat <<EOF
$(basename "$0") [options]

Options:
  --platform <macos-arm64|macos-x64|windows-x64>
  --out-dir DIR         (default: lib)
  --dest-dir DIR        (default: lib/lib/python)
  --cache-dir DIR       (default: .cache/python-standalone)
  --skip-sign
  --skip-build
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform)   PLATFORM_KEY="$2"; shift 2 ;;
    --out-dir)    OUT_DIR="$2"; shift 2 ;;
    --dest-dir)   DEST_DIR="$2"; shift 2 ;;
    --cache-dir)  CACHE_DIR="$2"; shift 2 ;;
    --skip-sign)  SKIP_SIGN=true; shift ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "Unknown: $1"; usage; exit 1 ;;
  esac
done

if [[ -z "$PLATFORM_KEY" ]]; then
  PLATFORM_KEY="$(detect_platform)"
fi

if ! is_known_platform "$PLATFORM_KEY"; then
  echo "Unknown platform: $PLATFORM_KEY" >&2
  exit 1
fi

log "Platform: $PLATFORM_KEY"
log "Python:   $PYTHON_VERSION  (standalone $STANDALONE_VERSION)"

# 1. Wheel
wheel_path=""
if $SKIP_BUILD; then
  wheel_path="$("$SCRIPT_DIR/wheel.sh" find "$OUT_DIR")"
  log "Using existing wheel: $(basename "$wheel_path")"
else
  wheel_path="$("$SCRIPT_DIR/wheel.sh" build "$OUT_DIR")"
  log "Wheel: $(basename "$wheel_path")"
fi

# 2. Download standalone
tarball="$("$SCRIPT_DIR/download.sh" --platform "$PLATFORM_KEY" --cache-dir "$CACHE_DIR")"

# 3. Extract
"$SCRIPT_DIR/archive.sh" extract "$tarball" "$DEST_DIR"

# 4. Install wheel (using local dist for workspace packages)
"$SCRIPT_DIR/wheel.sh" install "$wheel_path" "$DEST_DIR" --find-links "$OUT_DIR"

# 5. Trim
"$SCRIPT_DIR/trim.sh" "$DEST_DIR"

# 6. Generate app_paths.py
generate_app_paths "$DEST_DIR"

# 7. Sign or unsigned archive
if $SKIP_SIGN; then
  archive="$("$SCRIPT_DIR/archive.sh" create "$DEST_DIR" "$OUT_DIR" "$PLATFORM_KEY")"
else
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT

  if [[ "$PLATFORM_KEY" == macos* ]]; then
    archive="$("$SCRIPT_DIR/sign.sh" macos "$DEST_DIR" "$OUT_DIR" "$PLATFORM_KEY" "$tmpdir")"
  elif [[ "$PLATFORM_KEY" == "windows-x64" ]]; then
    archive="$("$SCRIPT_DIR/sign.sh" windows "$DEST_DIR" "$OUT_DIR" "$PLATFORM_KEY")"
  else
    echo "Signing not implemented for: $PLATFORM_KEY" >&2
    exit 1
  fi
fi

# Report
size_bytes=$(stat -f%z "$archive" 2>/dev/null || stat -c%s "$archive" 2>/dev/null || echo 0)
size_mb=$(awk "BEGIN {printf \"%.1f\", $size_bytes/1024/1024}")
triple="$(get_tauri_triple "$PLATFORM_KEY")"

echo
log "Done."
echo "    Archive:       $archive"
echo "    Size:          ${size_mb} MB"
echo "    Tauri triple:  $triple"
echo
echo "    To use as a Tauri sidecar resource, add to tauri.conf.json:"
echo "      \"bundle\": { \"lib\": { \"$(basename "$archive")\": \"lib/\" } }"
