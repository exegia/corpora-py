#!/usr/bin/env bash
#
# dispatch.sh
# Shell equivalent of scripts/build/__main__.py
#
# Allows similar usage to:
#   python -m scripts.build
#   python -m scripts.build bundle ...
#   python -m scripts.build embedded ...
#   python -m scripts.build client_runtime
#
# Run as:
#   ./scripts/build/dispatch.sh [bundle|embedded|client|client_runtime] [args...]
#   ./scripts/build/dispatch.sh          # runs the main build
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cmd="${1:-}"
if [[ -n "$cmd" ]]; then
  shift
fi

case "$cmd" in
  ""|build|main)
    exec "$SCRIPT_DIR/build.sh" "$@"
    ;;
  bundle)
    exec "$SCRIPT_DIR/bundle.sh" "$@"
    ;;
  embedded)
    exec "$SCRIPT_DIR/embedded.sh" "$@"
    ;;
  client|client_runtime)
    exec "$SCRIPT_DIR/client_runtime.sh" "$@"
    ;;
  -h|--help|help)
    echo "Usage:"
    echo "  $(basename "$0")                    # main signed build"
    echo "  $(basename "$0") bundle <wheel> ..."
    echo "  $(basename "$0") embedded [--full] [--clean]"
    echo "  $(basename "$0") client_runtime"
    exit 0
    ;;
  *)
    echo "Unknown subcommand: $cmd"
    echo "Try: $(basename "$0") --help"
    exit 1
    ;;
esac
