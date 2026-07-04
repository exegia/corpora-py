#!/usr/bin/env bash
#
# start.sh
#
# Start the demo app (ElectroBun + Vite).
#
# Usage:
#   ./scripts/start.sh
#   ./scripts/start.sh --stop
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=utils.sh
source "$SCRIPT_DIR/utils.sh"

# ---------------------------------------------------------------------------
# Demo app helpers
# ---------------------------------------------------------------------------

_python_has_shared_module() {
  local py_bin="$1"
  if [[ ! -x "$py_bin" ]]; then
    return 1
  fi
  if "$py_bin" -c "import shared, client, admin; print('ok')" 2>/dev/null | grep -q ok; then
    return 0
  fi
  return 1
}

ensure_demo_python_runtime() {
  local runtime="$ROOT/demo/build/lib/python/bin/python3"

  if [[ -x "$runtime" ]] && _python_has_shared_module "$runtime"; then
    echo "✅ Demo embedded Python runtime already present and up-to-date."
    return
  fi

  if [[ -x "$runtime" ]]; then
    echo "⚠️  Demo embedded Python runtime exists but appears to be from before the admin/client/shared refactor."
    echo "    Forcing clean rebuild with current sources..."
  fi

  echo "Demo embedded Python runtime not found (or stale) — building now..."

  local cmd=()
  if [[ -x "$SCRIPT_DIR/build/embedded.sh" ]]; then
    cmd=("$SCRIPT_DIR/build/embedded.sh")
    if [[ -x "$runtime" ]]; then
      cmd+=("--clean")
    fi
    "${cmd[@]}"
  else
    # Python fallback
    cmd=(python -m scripts.build.embedded)
    if [[ -x "$runtime" ]]; then
      cmd+=(--clean)
    fi
    run --no-dotenvx -- "${cmd[@]}"
  fi
}

clean_electrobun_dev_build() {
  local build_dir="$ROOT/demo/dist/build"
  if [[ -d "$build_dir" ]]; then
    echo "🧹 Cleaning stale ElectroBun build at $build_dir (ensures fresh python runtime copy)…"
    rm -rf "$build_dir"
  fi
}

_run_vite_server() {
  run --dev-server --dir "$DEMO_APP_DIR" -- "bun" "run" "vite:dev"
}

_run_electrobun_server() {
  local dir="$DEMO_APP_DIR"
  local dist="$dir/dist"

  if [[ ! -d "$dist" ]]; then
    run --dir "$dir" -- "bun" "run" "vite:build"
    sleep 2
  fi

  run --dev-server --dir "$dir" -- "bun" "run" "desktop:dev"
}

start_demo_app() {

  echo "🖥️  Starting electrobun desktop app..."
  _run_electrobun_server &
  local eb_pid=$!

  # Keep the launcher alive (prevents EIO on child readline)
  echo
  echo "✅ Dev servers are running. Press Ctrl+C to exit the launcher."

  # Wait on children; if interrupted, let children continue (or not).
  trap 'echo; echo "Launcher interrupted. (Child dev servers may still be running.)"; exit 0' INT TERM
  wait $vite_pid $eb_pid 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Supabase lifecycle
# ---------------------------------------------------------------------------

start_supabase_stack() {
  ensure_tool "dotenvx" "Install: \`uv add dotenvx\` or https://dotenvx.com/docs/install"
  ensure_tool "supabase" "Install: https://supabase.com/docs/guides/local-development/cli/getting-started"
  ensure_tool "docker" "Install Docker Desktop / OrbStack and make sure it is running."

  if is_supabase_running; then
    echo "✅ Supabase local stack is already running — skipping \`supabase start\`."
  else
    echo "Starting Supabase local stack (Docker containers may take a minute)…"
    run -- "supabase" "start" "--workdir" "$SUPABASE_PROJECT_DIR"
    echo
    echo "✅ Supabase local stack is up."
  fi

  # Print status (non-fatal)
  run --no-check -- "supabase" "status" "--workdir" "$SUPABASE_PROJECT_DIR"

  ensure_demo_python_runtime
  clean_electrobun_dev_build

  start_demo_app

  # The start_demo_app function already blocks.
}

stop_supabase_stack() {
  ensure_tool "dotenvx" "Install: \`uv add dotenvx\` or https://dotenvx.com/docs/install"
  ensure_tool "supabase" "Install: https://supabase.com/docs/guides/local-development/cli/getting-started"
  run -- "supabase" "stop"
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

main() {
    start_demo_app
}

main "$@"
