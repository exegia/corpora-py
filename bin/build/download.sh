#!/usr/bin/env bash
#
# download.sh
#
# Downloads (and caches) the python-build-standalone tarball for a given platform.
#
# Usage:
#   ./scripts/build/download.sh [--platform <key>] [--cache-dir <dir>]
#
# Prints the path to the cached tarball on success.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--platform <macos-arm64|macos-x64|windows-x64>] [--cache-dir <path>]

Downloads the python-build-standalone tarball and caches it.
EOF
}

PLATFORM_KEY=""
CACHE_DIR=".cache/python-standalone"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform)
      PLATFORM_KEY="$2"; shift 2 ;;
    --cache-dir)
      CACHE_DIR="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$PLATFORM_KEY" ]]; then
  PLATFORM_KEY="$(detect_platform)"
fi

if ! is_known_platform "$PLATFORM_KEY"; then
  echo "Unknown platform: $PLATFORM_KEY" >&2
  exit 1
fi

STANDALONE_NAME="$(get_standalone_name "$PLATFORM_KEY")"
TARBALL_NAME="cpython-${PYTHON_VERSION}+${STANDALONE_VERSION}-${STANDALONE_NAME}-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${STANDALONE_VERSION}/${TARBALL_NAME}"

mkdir -p "$CACHE_DIR"
CACHED="$CACHE_DIR/$TARBALL_NAME"

if [[ -f "$CACHED" ]]; then
  log "Using cached standalone Python: $TARBALL_NAME"
else
  log "Downloading standalone Python ($PLATFORM_KEY)..."
  run_cmd curl -L --progress-bar -o "$CACHED" "$URL"
fi

echo "$CACHED"
