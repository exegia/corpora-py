#!/usr/bin/env bash
#
# stop.sh
# Shell equivalent of scripts/stop.py
#
# Stop local dev servers launched from this project.
# Terminates any uvicorn/FastAPI processes whose command line references
# this project root.
#
# Usage:
#   ./scripts/stop.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

stop_dev_processes() {
  if ! command -v pkill >/dev/null 2>&1; then
    echo "pkill not available — cannot terminate uvicorn processes."
    return
  fi

  local pattern="uvicorn.*${ROOT}"
  if pkill -f "$pattern" 2>/dev/null; then
    echo "Terminated uvicorn processes matching '${pattern}'."
  else
    # pkill returns 1 when no processes matched
    rc=$?
    if [[ $rc -eq 1 ]]; then
      echo "No matching uvicorn processes found."
    else
      echo "warning: pkill exited $rc" >&2
    fi
  fi
}

stop_dev_processes
echo
echo "Done."
