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
    5. Clean stale ElectroBun build/ so the python runtime is freshly copied into the bundle.
    6. Start the demo app: launch Vite HMR server first, then electrobun desktop app + browser.
    7. Keep the launcher process alive (non-daemon threads + blocker) so it owns the TTY.
       This prevents Bun/Node from getting "read EIO" on their readline interfaces.

Usage:
    uv run scripts/start.py          # start the local stack + demo app
    uv run scripts/start.py --stop   # stop the local stack
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# Make "import utils" reliable even if the script is invoked in unusual ways
# (uv run scripts/start.py, python -m, different cwd, etc.).
sys.path.insert(0, str(Path(__file__).parent))

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


def _python_has_shared_module(py_bin: Path) -> bool:
    """Quick probe: does this python have the post-refactor packages (shared etc)?"""
    try:
        result = subprocess.run(
            [str(py_bin), "-c", "import shared, client, admin; print('ok')"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


def ensure_demo_python_runtime() -> None:
    """Ensure the embedded Python runtime for the demo app is built.

    All build/bundling logic lives under scripts/build/
      - python -m scripts.build.embedded [--clean] [--full]
    """
    runtime = ROOT / "demo/public/resources/python/bin/python3"
    if runtime.exists() and _python_has_shared_module(runtime):
        print("✅ Demo embedded Python runtime already present and up-to-date.")
        return

    if runtime.exists():
        print(
            "⚠️  Demo embedded Python runtime exists but appears to be from before the admin/client/shared refactor."
        )
        print("    Forcing clean rebuild with current sources...")

    print("Demo embedded Python runtime not found (or stale) — building now...")
    cmd = [sys.executable, "-m", "scripts.build.embedded"]
    if runtime.exists():
        cmd.append("--clean")
    run(cmd, dotenvx=False, dir=ROOT)


def clean_electrobun_dev_build() -> None:
    """Remove the ElectroBun dev build directory.

    This forces a fresh copy of resources/ (including the Python runtime)
    according to the rules in demo/app/electrobun.config.ts. Stale builds are
    the most common cause of "python binary not found" after changes.
    """
    build_dir = ROOT / "demo/dist/build"
    if build_dir.exists():
        print(
            f"🧹 Cleaning stale ElectroBun build at {build_dir} (ensures fresh python runtime copy)…"
        )
        shutil.rmtree(build_dir, ignore_errors=True)


def _run_vite_server() -> None:
    """Target for the background thread: keep the Vite HMR dev server alive."""
    dir: Path = ROOT / "demo"
    run(cmd=["bun", "run", "vite:dev"], dotenvx=True, dir=dir, dev_server=True)


def _run_electrobun_server() -> None:
    """Target for the background thread: keep the ElectroBun desktop dev server alive."""
    dir = ROOT / "demo"
    dist: Path = dir / "dist"
    if dist.exists() is False:
        """If the dist folder isn't there, that means that we need to run,
        the `vite:build` command.
        """
        run(cmd=["bun", "run", "vite:build"], dotenvx=True, dir=dir)
        time.sleep(2)

    """The folder already exists, the vite build has already been ran"""
    """We can then run and boot the desktop app."""
    run(cmd=["bun", "run", "desktop:dev"], dotenvx=True, dir=dir, dev_server=True)


def start_demo_app() -> None:
    """Start the Vite HMR server + electrobun app, open the browser, watch for rebuilds.

    Flow:
      1. Launch the Vite HMR server in a background thread (non-blocking).
      2. Wait briefly for Vite to bind its port.
      3. Launch the electrobun desktop app in a background thread (non-blocking).
      4. Keep the launcher process alive so it owns the TTY (avoids EIO/readline errors
         in the Bun/Node dev servers).
    """
    # 1. Start Vite HMR first so the desktop app has something to connect to.
    #    Use non-daemon threads so the launcher process stays alive and keeps
    #    ownership of the TTY (prevents "read EIO" / readline errors in Bun/Node).
    vite_thread = threading.Thread(
        target=_run_vite_server, daemon=False, name="vite-hmr"
    )
    vite_thread.start()
    print("⚡ Vite HMR server starting...")

    # 2. Give Vite a moment to bind before the desktop app and browser try to use it.
    time.sleep(3)
    print(f"🌐 Opening browser at {VITE_URL} …")

    # 3. Launch the electrobun desktop app (it will connect to the running Vite + look for python runtime).
    electrobun_thread = threading.Thread(
        target=_run_electrobun_server, daemon=False, name="electrobun"
    )
    electrobun_thread.start()
    print("🖥️  Starting electrobun desktop app...")


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

    # Clean previous ElectroBun dev build so the copy rule for resources/python
    # is re-applied into the fresh bundle. Without this you often get ENOENT
    # for the python binary inside the launched .app even when the source exists.
    clean_electrobun_dev_build()

    start_demo_app()

    # Keep the main process (and thus the controlling TTY) alive.
    # The background threads are running the long-lived `bun run ...` commands.
    # If the Python process exits while Vite/Bun still have readline interfaces
    # attached to the TTY, you get the "read EIO" crash.
    print("\n✅ Dev servers are running. Press Ctrl+C to exit the launcher.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nLauncher interrupted. (Child dev servers may still be running.)")


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
