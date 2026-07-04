#!/usr/bin/env bash
#
# dispatch.sh
# Lightweight dispatcher for top-level scripts/ (similar to build/dispatch.sh).
#
# Examples:
#   ./scripts/dispatch.sh clean
#   ./scripts/dispatch.sh setup
#   ./scripts/dispatch.sh start
#   ./scripts/dispatch.sh start --stop
#   ./scripts/dispatch.sh publish --help
#
# Falls back to direct execution of the matching *.sh when a subcommand matches.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cmd="${1:-}"
if [[ -n "$cmd" ]]; then
  shift
fi

case "$cmd" in
  clean)
    exec "$SCRIPT_DIR/clean.sh" "$@"
    ;;
  setup)
    exec "$SCRIPT_DIR/setup.sh" "$@"
    ;;
  start)
    exec "$SCRIPT_DIR/start.sh" "$@"
    ;;
  stop)
    exec "$SCRIPT_DIR/stop.sh" "$@"
    ;;
  publish)
    exec "$SCRIPT_DIR/publish.sh" "$@"
    ;;
  git-work|git_work|gitwork)
    exec "$SCRIPT_DIR/git_work.sh" "$@"
    ;;
  -h|--help|help|"")
    cat <<'EOM'
scripts/ dispatcher

  ./scripts/dispatch.sh clean
  ./scripts/dispatch.sh setup
  ./scripts/dispatch.sh start [--stop]
  ./scripts/dispatch.sh stop
  ./scripts/dispatch.sh publish [args...]
  ./scripts/dispatch.sh git-work [message]
EOM
    [[ -z "$cmd" || "$cmd" == "help" || "$cmd" == "-h" || "$cmd" == "--help" ]] && exit 0 || exit 1
    ;;
  *)
    # Try to run scripts/<cmd>.sh directly if it exists
    if [[ -x "$SCRIPT_DIR/${cmd}.sh" ]]; then
      exec "$SCRIPT_DIR/${cmd}.sh" "$@"
    fi
    echo "Unknown script: $cmd"
    echo "Try: ./scripts/dispatch.sh --help"
    exit 1
    ;;
esac
