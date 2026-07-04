#!/usr/bin/env bash
#
# common.sh
# Shared constants and helpers for the build shell scripts.
# Compatible with macOS default bash (3.2) and newer.
#
# Source this from other scripts:
#   source "$(dirname "$0")/common.sh"
#

set -euo pipefail

# ── Version pins ──────────────────────────────────────────────────────────────
PYTHON_VERSION="3.13.14"
STANDALONE_VERSION="20260623"

# Demo / build layout (relative to repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
DEMO_RESOURCES="$REPO_ROOT/demo/build/lib/python"

# For client opt-in downloads (override via env)
DOWNLOAD_BASE_URL="${DOWNLOAD_BASE_URL:-https://your-cdn.example.com/corpora-runtimes}"

# STDLIB_TRIM — same list as env_vars.py
STDLIB_TRIM=(
  tkinter idlelib turtledemo "turtle.py" curses
  test unittest
  ensurepip lib2to3
  pydoc_data "pydoc.py" "doctest.py"
  "_pydecimal.py" mailbox.py imaplib.py nntplib.py poplib.py smtplib.py ftplib.py xmlrpc
  "asyncio/windows_events.py" "asyncio/windows_utils.py"
  distutils venv msilib winreg ossaudiodev spwd
  "ctypes/test" "sqlite3/test" "xml/sax/test" "email/test"
  xml sqlite3 dbm shelve bdb cmd pdb profile cProfile timeit trace tracemalloc faulthandler symtable
)

# ── Platform helpers (no associative arrays for bash 3.2 compat) ──────────────

get_standalone_name() {
  case "$1" in
    macos-arm64) echo "aarch64-apple-darwin" ;;
    macos-x64)   echo "x86_64-apple-darwin" ;;
    windows-x64) echo "x86_64-pc-windows-msvc-shared" ;;
    *) echo "ERROR: unknown platform $1" >&2; exit 1 ;;
  esac
}

get_platform_lib() {
  case "$1" in
    macos-arm64|macos-x64) echo "libpython3.13.dylib" ;;
    windows-x64)           echo "python313.dll" ;;
    *) echo "ERROR: unknown platform $1" >&2; exit 1 ;;
  esac
}

get_tauri_triple() {
  case "$1" in
    macos-arm64) echo "aarch64-apple-darwin" ;;
    macos-x64)   echo "x86_64-apple-darwin" ;;
    windows-x64) echo "x86_64-pc-windows-msvc" ;;
    *) echo "ERROR: unknown platform $1" >&2; exit 1 ;;
  esac
}

is_known_platform() {
  case "$1" in
    macos-arm64|macos-x64|windows-x64) return 0 ;;
    *) return 1 ;;
  esac
}

# ── Helper functions ──────────────────────────────────────────────────────────

log() {
  echo "==> $*" >&2
}

log_step() {
  echo "    $*" >&2
}

run_cmd() {
  # Print and execute (like helpers.run); stderr so stdout stays machine-readable
  echo "  $ $*" >&2
  "$@"
}

detect_platform() {
  local os_name arch
  os_name="$(uname -s)"
  arch="$(uname -m)"

  if [[ "$os_name" == "Darwin" && "$arch" == "arm64" ]]; then
    echo "macos-arm64"
  elif [[ "$os_name" == "Darwin" && "$arch" == "x86_64" ]]; then
    echo "macos-x64"
  elif [[ "$os_name" == "Linux" && "$arch" == "x86_64" ]]; then
    echo "linux-x64"
  elif [[ "$os_name" == MINGW* || "$os_name" == MSYS* || "$os_name" == CYGWIN* ]]; then
    echo "windows-x64"
  else
    echo "ERROR: Cannot auto-detect platform for $os_name-$arch. Use --platform." >&2
    exit 1
  fi
}

get_platform_key() {
  local system machine
  system="$(uname -s)"
  machine="$(uname -m | tr '[:upper:]' '[:lower:]')"

  if [[ "$system" == "Darwin" ]]; then
    if [[ "$machine" == arm* ]]; then
      echo "macos-arm64"
    else
      echo "macos-x64"
    fi
  elif [[ "$system" == "Linux" && "$machine" == x86_64 ]]; then
    echo "linux-x64"
  elif [[ "$system" == MINGW* || "$system" == MSYS* || "$system" == CYGWIN* ]]; then
    echo "windows-x64"
  else
    echo "ERROR: Unsupported platform: $system-$machine" >&2
    exit 1
  fi
}

pylib_dir() {
  local python_dir="$1"
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) echo "$python_dir/Lib" ;;
    *) echo "$python_dir/lib/python3.13" ;;
  esac
}

du_size() {
  du -sh "$1" 2>/dev/null | awk '{print $1}' || echo "?"
}

# Generate app_paths.py (from helpers.py)
generate_app_paths() {
  local python_dir="$1"
  local identifier="${APP_IDENTIFIER:-io.exegia.Corpora}"
  local channel="${APP_CHANNEL:-stable}"

  if [[ -z "$identifier" ]]; then
    echo "    Skipping app_paths.py — APP_IDENTIFIER not set."
    return
  fi

  local site_packages
  site_packages="$(pylib_dir "$python_dir")/site-packages"
  mkdir -p "$site_packages"

  cat > "$site_packages/app_paths.py" <<EOF
"""Auto-generated — platform paths for the host Tauri application."""
import os
from pathlib import Path

_home = Path.home()
_platform = __import__("sys").platform

IDENTIFIER = "$identifier"
CHANNEL = "$channel"

if _platform == "darwin":
    app_data = _home / "Library" / "Application Support"
    cache = _home / "Library" / "Caches"
    logs = _home / "Library" / "Logs"
    temp = Path(os.environ.get("TMPDIR", "/tmp"))
elif _platform == "win32":
    app_data = Path(os.environ.get("LOCALAPPDATA", str(_home / "AppData" / "Local")))
    cache = app_data
    logs = app_data
    temp = Path(os.environ.get("TEMP", str(app_data / "Temp")))
else:
    app_data = Path(os.environ.get("XDG_DATA_HOME", str(_home / ".local" / "share")))
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(_home / ".cache")))
    logs = Path(os.environ.get("XDG_STATE_HOME", str(_home / ".local" / "state")))
    temp = Path("/tmp")

home = _home
config = app_data
documents = _home / "Documents"
downloads = _home / "Downloads"
desktop = _home / "Desktop"

user_data = app_data / IDENTIFIER / CHANNEL
user_cache = cache / IDENTIFIER / CHANNEL
user_logs = logs / IDENTIFIER / CHANNEL
EOF

  echo "    APP_IDENTIFIER: $identifier  channel: $channel"
}

# Download + extract prebuilt runtime for client apps
ensure_python_runtime() {
  local target_dir="${1:-demo/build/lib}"
  local force="${2:-false}"

  local python_dir="$target_dir/python"
  local python_bin

  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) python_bin="$python_dir/python.exe" ;;
    *) python_bin="$python_dir/bin/python3" ;;
  esac

  if [[ -f "$python_bin" && "$force" != "true" ]]; then
    echo "✅ Embedded Python runtime ALREADY present at $python_bin"
    echo "   Using what is already there (load only what's missing in future designs)."
    echo "$python_bin"
    return 0
  fi

  if [[ -d "$python_dir" ]]; then
    echo "Partial runtime detected — re-downloading full..."
    rm -rf "$python_dir"
  fi

  local plat archive_name url archive_path
  plat="$(get_platform_key)"
  archive_name="python-runtime-${plat}.tar.gz"
  url="${DOWNLOAD_BASE_URL%/}/${archive_name}"

  echo "Downloading full runtime for ${plat} from ${url} ..."
  archive_path="$target_dir/$archive_name"
  mkdir -p "$target_dir"

  if ! curl -L --progress-bar -o "$archive_path" "$url"; then
    echo "Failed to download runtime." >&2
    echo "Host the archive produced by the build scripts and set DOWNLOAD_BASE_URL." >&2
    exit 1
  fi

  echo "Extracting..."
  tar -xzf "$archive_path" -C "$target_dir"

  if [[ ! -f "$python_bin" ]]; then
    echo "Extracted runtime missing expected binary: $python_bin" >&2
    exit 1
  fi

  rm -f "$archive_path"
  echo "✅ Runtime ready at $python_dir"
  echo "$python_bin"
}

print_common_usage() {
  cat <<EOF
Platforms supported: macos-arm64 macos-x64 windows-x64
EOF
}
