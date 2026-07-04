#!/usr/bin/env bash
#
# embedded.sh
#
# Build wheels + embed into the demo's standalone Python runtime.
# Used for DEMO / ADMIN (optionally with [full]).
#
# For client opt-in full runtime: use client_runtime.sh
#
# Usage:
#   ./bin/build/embedded.sh [--platform P] [--clean] [--full]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PLATFORM_KEY=""
CLEAN=false
FULL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) PLATFORM_KEY="$2"; shift 2 ;;
    --clean)    CLEAN=true; shift ;;
    --full)     FULL=true; shift ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--platform P] [--clean] [--full]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

python_bin="$DEMO_RESOURCES/bin/python3"

if [[ -f "$python_bin" && "$CLEAN" != true ]]; then
  log "Embedded Python runtime for demo already present (skipping)."
  log_step "$python_bin"
  exit 0
fi

log "Building embedded Python for ElectroBun demo"
log_step "Repo root: $REPO_ROOT"
log_step "Target:    $DEMO_RESOURCES"

if $CLEAN; then
  log "Cleaning previous lib/python"
  rm -rf "$DEMO_RESOURCES"
fi

# 1. Build all workspace wheels (local dist)
log "Building workspace wheels with uv..."
mkdir -p "$DIST_DIR"
run_cmd uv build --package corpora-common --wheel "--out-dir=$DIST_DIR"
run_cmd uv build --package corpora-mcp --wheel "--out-dir=$DIST_DIR"
run_cmd uv build --package corpora-admin --wheel "--out-dir=$DIST_DIR"
run_cmd uv build --wheel "--out-dir=$DIST_DIR"

wheel="$("$SCRIPT_DIR/wheel.sh" find "$DIST_DIR")"
log_step "Found wheel: $(basename "$wheel")"

wheel_spec="$wheel"
if $FULL; then
  wheel_spec="${wheel}[full]"
fi

log "Bundling standalone Python + wheel${FULL:+[full]}..."

"$SCRIPT_DIR/bundle.sh" "$wheel_spec" \
  ${PLATFORM_KEY:+--platform "$PLATFORM_KEY"} \
  --dest-dir "$DEMO_RESOURCES" \
  --find-links "$DIST_DIR"

echo
echo "✅ Done!"
echo "   Embedded Python is at: $DEMO_RESOURCES/bin/python3"
echo
echo "   To use it locally (without Docker dev override):"
echo "     unset DEV_PYTHON_BIN DEV_PYTHON_HOME"
echo "     bun run dev     # or the equivalent ElectroBun launch command"
echo
echo "   The python-bridge will automatically use this embedded Python."
