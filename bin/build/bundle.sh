#!/usr/bin/env bash
#
# bundle.sh
# Shell equivalent of scripts/build/bundle.py
#
# Bundle a wheel (with optional [extra]) into a standalone Python runtime.
# Also produces python-runtime-<plat>.tar.gz .
#
# Usage:
#   ./scripts/build/bundle.sh <wheel.whl[extra]> [options]
#
# Options:
#   --platform <key>
#   --dest-dir <dir>     (default: demo/build/lib/python)
#   --cache-dir <dir>
#   --find-links <dir>
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'EOF'
Usage:
  bundle.sh <wheel-spec> [--platform P] [--dest-dir D] [--cache-dir C] [--find-links F]

Example:
  ./bin/build/bundle.sh dist/corpora_py-*.whl[full]
EOF
}

WHEEL_SPEC=""
PLATFORM_KEY=""
DEST_DIR="demo/build/lib/python"
CACHE_DIR=".cache/python-standalone"
FIND_LINKS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform)   PLATFORM_KEY="$2"; shift 2 ;;
    --dest-dir)   DEST_DIR="$2"; shift 2 ;;
    --cache-dir)  CACHE_DIR="$2"; shift 2 ;;
    --find-links) FIND_LINKS="$2"; shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    -*)
      echo "Unknown option: $1" >&2; usage; exit 1 ;;
    *)
      if [[ -z "$WHEEL_SPEC" ]]; then
        WHEEL_SPEC="$1"
      else
        echo "Unexpected arg: $1" >&2; usage; exit 1
      fi
      shift ;;
  esac
done

if [[ -z "$WHEEL_SPEC" ]]; then
  usage; exit 1
fi

if [[ -z "$PLATFORM_KEY" ]]; then
  PLATFORM_KEY="$(detect_platform)"
fi

if ! is_known_platform "$PLATFORM_KEY"; then
  echo "Unknown platform: $PLATFORM_KEY" >&2
  exit 1
fi

info_lib="$(get_platform_lib "$PLATFORM_KEY")"

# Resolve wheel + [extra]
wheel_path_str="$WHEEL_SPEC"
extra_part=""
if [[ "$WHEEL_SPEC" == *"["* ]]; then
  wheel_path_str="${WHEEL_SPEC%%[*}"
  extra_part="[${WHEEL_SPEC#*[}"
fi

wheel_path="$(cd "$(dirname "$wheel_path_str")" 2>/dev/null && pwd)/$(basename "$wheel_path_str")" || wheel_path="$(realpath "$wheel_path_str" 2>/dev/null || echo "$wheel_path_str")"

if [[ ! -f "$wheel_path" ]]; then
  # try relative to repo root
  if [[ -f "$REPO_ROOT/$wheel_path_str" ]]; then
    wheel_path="$REPO_ROOT/$wheel_path_str"
  else
    echo "Wheel not found: $wheel_path_str" >&2
    exit 1
  fi
fi

install_target="$wheel_path"
if [[ -n "$extra_part" ]]; then
  install_target="${wheel_path}${extra_part}"
fi

dest="$(cd "$DEST_DIR" 2>/dev/null && pwd || echo "$(realpath -m "$DEST_DIR")")"
cache="$(cd "$CACHE_DIR" 2>/dev/null && pwd || echo "$(realpath -m "$CACHE_DIR")")"

log "Platform: $PLATFORM_KEY"
log "Python:   $PYTHON_VERSION"
log "Wheel:    $wheel_path"

# 1. Download standalone
tarball="$("$SCRIPT_DIR/download.sh" --platform "$PLATFORM_KEY" --cache-dir "$cache")"

# 2. Extract
"$SCRIPT_DIR/archive.sh" extract "$tarball" "$dest"

# 3. Install wheel
log "Installing wheel with uv..."
python_bin="$dest/bin/python3"
if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
  python_bin="$dest/python.exe"
fi

install_cmd=(uv pip install --python "$python_bin" --no-cache)
[[ -n "$FIND_LINKS" ]] && install_cmd+=(--find-links "$(realpath "$FIND_LINKS")")
install_cmd+=("$install_target")

run_cmd "${install_cmd[@]}"

# 4. Trim
log "Trimming stdlib..."
"$SCRIPT_DIR/trim.sh" "$dest"

# 5. Sizes + report
pylib="$dest/lib/python3.13"
if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
  pylib="$dest/Lib"
fi

total="$(du_size "$dest")"
lib_size="N/A"
if [[ -f "$dest/lib/$info_lib" ]]; then
  lib_size="$(du_size "$dest/lib/$info_lib")"
fi
stdlib_size="$(du_size "$pylib" 2>/dev/null || echo '?')"
site_size="$(du_size "$pylib/site-packages" 2>/dev/null || echo '?')"

echo
log "Done! Bundled Python at: $dest"
echo
echo "    Total:         $total"
echo "    Shared lib:    $lib_size ($info_lib)"
echo "    Stdlib:        $stdlib_size"
echo "    Site-packages: $site_size"

# 6. Create distributable archive (tar.gz of the python/ dir)
parent_dir="$(dirname "$dest")"
archive="$parent_dir/python-runtime-$PLATFORM_KEY.tar.gz"

log "Creating distributable archive for client opt-in: $archive"
# Portable way to produce tar with top-level "python/" directory
stage_dir="$(mktemp -d)"
trap 'rm -rf "$stage_dir"' EXIT

mkdir -p "$stage_dir/python"
# Copy preserving symlinks, permissions etc.
cp -a "$dest"/. "$stage_dir/python/"

(
  cd "$stage_dir"
  tar -czf "$archive" python
)

rm -rf "$stage_dir"

log "Ready to host: $archive"

echo "$archive"
