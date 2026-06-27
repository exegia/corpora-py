#!/usr/bin/env python3
"""Start the local Supabase dev stack with dotenvx-loaded env.

Every Supabase call is wrapped with `dotenvx run -f .env.development --` so
secrets from `.env.development` (decrypted via `.env.keys` when encrypted) are
injected into the command's environment. This keeps local dev consistent with
how production reads env vars and avoids leaking values into the parent shell.

Steps:
    1. Verify `dotenvx`, `supabase`, and `docker` are on PATH.
    2. Check whether the Supabase Studio Docker container is already running (idempotent).
    3. Run `supabase start` from the project root, under dotenvx (if not already up).
    4. Ensure the demo app's embedded Python runtime is built (via root scripts/ if missing).
    5. Start the demo app: launch Vite HMR server, open browser, watch src/ for rebuilds.

Usage:
    uv run scripts/start.py          # start the local stack + demo app
    uv run scripts/start.py --stop   # stop the local stack
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from utils import (
    ROOT,
    SUPABASE_PROJECT_DIR,
    VITE_URL,
    ensure_tool,
    is_supabase_running,
    run,
)

# ---------------------------------------------------------------------------
# Demo app helpers
# ---------------------------------------------------------------------------


def ensure_demo_python_runtime() -> None:
    """Ensure the embedded Python runtime for the demo app is built.

    The responsibility for building/bundling the wheel + standalone Python
    lives in the root scripts/ (build_embedded_python.py + bundle_python.py).
    We only invoke it here if the runtime is missing.
    """
    runtime = ROOT / "demo/app/resources/python/bin/python3"
    if runtime.exists():
        print("✅ Demo embedded Python runtime already present.")
        return

    print("Demo embedded Python runtime not found — building now...")
    run(
        [sys.executable, str(ROOT / "scripts/build_embedded_python.py")],
        dotenvx=False,
        dir=ROOT,
    )


def _run_vite_server() -> None:
    """Target for the background thread: keep the Vite HMR dev server alive."""
    dir: Path = ROOT / "demo/app"
    run(cmd=["bun", "run", "vite:dev"], dotenvx=True, dir=dir)


def _run_electrobun_server() -> None:
    """Target for the background thread: keep the Vite HMR dev server alive."""
    dir = ROOT / "demo/app"
    dist: Path = dir / "dist"
    if dist.exists() is False:
        """If the dist folder isn't there, that means that we need to run,
        the `vite:build` command.
        """
        run(cmd=["bun", "run", "vite:build"], dotenvx=True, dir=dir)
        time.sleep(2)

    """The folder already exists, the vite build has already been ran"""
    """We can then run and boot the desktop app."""
    run(cmd=["bun", "run", "desktop:dev"], dotenvx=True, dir=dir)


def start_demo_app() -> None:
    """Start the Vite HMR server + electrobun app, open the browser, watch for rebuilds.

    Flow:
      1. Launch the Vite HMR server in a daemon thread (non-blocking).
      2. Wait briefly for Vite to bind its port, then open the browser.
      3. Launch the electrobun desktop app in a daemon thread (non-blocking).
      4. Block on the file-watcher — rebuild electrobun whenever .ts/.tsx changes.
    """
    # 1.Build and launch the electrobun desktop app
    electrobun_thread = threading.Thread(
        target=_run_electrobun_server, daemon=True, name="electrobun"
    )
    electrobun_thread.start()
    print("🖥️  Starting electrobun desktop app...")

    # 2. Give Vite a moment to bind before opening the browser
    time.sleep(2)
    print(f"🌐 Opening browser at {VITE_URL} …")

    # 3. Vite HMR server
    vite_thread = threading.Thread(
        target=_run_vite_server, daemon=True, name="vite-hmr"
    )
    vite_thread.start()
    print("⚡ Vite HMR server starting...")


# ---------------------------------------------------------------------------
# Supabase lifecycle
# ---------------------------------------------------------------------------


def start() -> None:
    ensure_tool(
        "dotenvx",
        "Install: `uv add dotenvx` (already in setup.py) or https://dotenvx.com/docs/install",
    )
    ensure_tool(
        "supabase",
        "Install: https://supabase.com/docs/guides/local-development/cli/getting-started",
    )
    ensure_tool(
        "docker", "Install Docker Desktop / OrbStack and make sure it is running."
    )

    if is_supabase_running():
        print("✅ Supabase local stack is already running — skipping `supabase start`.")
    else:
        print("Starting Supabase local stack (Docker containers may take a minute)…")
        run(cmd=["supabase", "start", "--workdir", SUPABASE_PROJECT_DIR], dotenvx=True)
        print("\n✅ Supabase local stack is up.")

    # Print status (URLs + keys) for convenience — non-fatal if it fails.
    run((["supabase", "status", "--workdir", SUPABASE_PROJECT_DIR]), check=False)

    # Ensure the demo's embedded Python runtime is ready (root-owned bundler)
    ensure_demo_python_runtime()

    start_demo_app()


def stop() -> None:
    ensure_tool(
        "dotenvx",
        "Install: `uv add dotenvx` (already in setup.py) or https://dotenvx.com/docs/install",
    )
    ensure_tool(
        "supabase",
        "Install: https://supabase.com/docs/guides/local-development/cli/getting-started",
    )
    run(["supabase", "stop"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the local Supabase stack instead of starting it.",
    )
    args = parser.parse_args()

    if args.stop:
        stop()
    else:
        start()


if __name__ == "__main__":
    main()
