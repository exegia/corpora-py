#!/usr/bin/env bash
#
# clean.sh
# Shell equivalent of scripts/clean.py
#
# Clean the project: remove caches, build artifacts, and venv.
#
# Usage:
#   ./scripts/clean.sh
#   uv run scripts/clean.py   (still works via python)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DIRS_TO_REMOVE=(".venv" ".mypy_cache" ".ruff_cache" ".pytest_cache")

GLOB_PATTERNS=(
  "**/__pycache__"
  "**/*.egg-info"
  "**/.temp"
  "demo/build"
  "**/.react-router"
  "**/dist"
  "**/lib/python"
  "**/.cache"
  "**/artifacts"
  "**/node_modules"
)

remove() {
  local path="$1"
  if [[ -e "$path" ]]; then
    local rel
    rel=$(python3 -c "
import os, sys
root = sys.argv[1]
p = sys.argv[2]
print(os.path.relpath(p, root))
" "$ROOT" "$path" 2>/dev/null || echo "$path")
    rm -rf "$path"
    echo "  removed  $rel"
  fi
}

echo "Cleaning project..."
echo

echo "Removing top-level directories..."
for name in "${DIRS_TO_REMOVE[@]}"; do
  remove "$ROOT/$name"
done

echo
echo "Removing cached/build artifacts..."

# Handle common recursive patterns robustly
for pat in "${GLOB_PATTERNS[@]}"; do
  case "$pat" in
    "**/__pycache__")
      find "$ROOT" -type d -name __pycache__ -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    "**/*.egg-info")
      find "$ROOT" -type d -name '*.egg-info' -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    "**/.temp")
      find "$ROOT" -type d -name .temp -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    "demo/build")
      remove "$ROOT/demo/build"
      ;;
    "**/.react-router")
      find "$ROOT" -type d -name .react-router -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    "**/dist")
      find "$ROOT" -type d -name dist -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    "**/lib/python")
      find "$ROOT" -path '*/lib/python' -type d -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    "**/.cache")
      find "$ROOT" -type d -name .cache -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    "**/artifacts")
      find "$ROOT" -type d -name artifacts -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    "**/node_modules")
      find "$ROOT" -type d -name node_modules -prune -print0 2>/dev/null | while IFS= read -r -d '' p; do remove "$p"; done
      ;;
    *)
      # Fallback: try literal path under root
      remove "$ROOT/${pat#\*\*/}"
      ;;
  esac
done

echo
echo "Done."
