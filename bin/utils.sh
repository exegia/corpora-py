#!/usr/bin/env bash
#
# utils.sh
# Shell equivalent of scripts/utils.py
#
# Shared helpers for other scripts in this directory.
# Source it from sibling scripts:
#   source "$(dirname "$0")/utils.sh"
#

set -euo pipefail

# ── Paths (mirrors utils.py) ──────────────────────────────────────────────────
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"
ENV_FILE="$ROOT/.env.development"
DEMO_APP_DIR="$ROOT/example"
VITE_URL="http://localhost:5173"

# ── Tooling helpers ───────────────────────────────────────────────────────────

ensure_tool() {
  local name="$1"
  local hint="${2:-}"
  local install_cmd="${3:-}"

  if ! command -v "$name" >/dev/null 2>&1; then
    if [[ -n "$install_cmd" ]]; then
      echo "\$${name} is not on user PATH. Installing using command..."
      # Note: install_cmd may contain pipes etc. Caller should handle complex cases.
      eval "$install_cmd"
    fi
    if ! command -v "$name" >/dev/null 2>&1; then
      echo "error: \`${name}\` is required on PATH. ${hint}" >&2
      exit 1
    fi
  fi
}

# ── dotenvx wrapper ───────────────────────────────────────────────────────────

dotenvx_wrap() {
  # Print the wrapped command array as words (for logging by caller)
  # Usage:
  #   wrapped=($(dotenvx_wrap "supabase" "start" ...))
  #   echo "${wrapped[@]}"
  local -a cmd=("$@")
  echo "dotenvx" "run" "-f" "$ENV_FILE" "--" "${cmd[@]}"
}

# ── run helper (matches the Python run() behavior closely) ─────────────────────

# run [options] -- cmd...
# Options (before --):
#   --no-dotenvx
#   --dir <path>
#   --dev-server
#   --no-check
#
# Behavior:
#   - Prints the command
#   - If dotenvx: wraps with dotenvx run ...
#   - For dev_server: uses stdin=/dev/null equivalent
#   - Respects check (exits on failure unless --no-check or dev_server)
run() {
  local dotenvx=true
  local check=true
  local dir="$ROOT"
  local dev_server=false
  local -a cmd=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --no-dotenvx) dotenvx=false; shift ;;
      --no-check)   check=false; shift ;;
      --dev-server) dev_server=true; shift ;;
      --dir)        dir="$2"; shift 2 ;;
      --)           shift; cmd=("$@"); break ;;
      *)            # If no -- yet, assume rest is the command
                    cmd=("$@")
                    break ;;
    esac
  done

  if [[ ${#cmd[@]} -eq 0 ]]; then
    echo "run: no command provided" >&2
    return 1
  fi

  echo "\$ ${cmd[*]}"

  local -a final_cmd=("${cmd[@]}")

  if $dotenvx; then
    echo "🔒 Starting command with dotenvx..."
    final_cmd=(dotenvx run -f "$ENV_FILE" -- "${cmd[@]}")
  fi

  local rc=0
  if $dev_server; then
    # Detach stdin for long-lived dev servers (prevents EIO/readline issues)
    ( cd "$dir" && "${final_cmd[@]}" < /dev/null ) || rc=$?
  else
    ( cd "$dir" && "${final_cmd[@]}" ) || rc=$?
  fi

  if $check && [[ $rc -ne 0 ]]; then
    if $dev_server; then
      echo "[dev server] ${cmd[*]} exited with code $rc"
      return $rc
    else
      exit $rc
    fi
  fi

  return $rc
}

# Convenience wrapper for opening browser (macOS/Linux)
open_browser() {
  local url="${1:-$VITE_URL}"
  echo "🌐 Opening browser at $url …"
  if command -v open >/dev/null 2>&1; then
    open "$url"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url"
  else
    echo "Please open: $url"
  fi
}

# ── Exports for sourcing scripts (not strictly needed in bash) ────────────────
# Variables and functions above are available after sourcing.

# Quick self-test when executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "utils.sh loaded."
  echo "ROOT=$ROOT"
  echo "ENV_FILE=$ENV_FILE"
fi
