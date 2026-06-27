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
    4. Start the demo app: launch Vite HMR server, open browser, watch src/ for rebuilds.

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
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = str(ROOT / ".env.development")  # absolute so dotenvx works from any cwd
DEMO_APP_DIR = "demo/app"
DEMO_SRC_DIR = str(ROOT / "demo/app/src")
VITE_URL = "http://localhost:5173"

# Match any running Supabase Studio container regardless of project name.
# If one is up, we reuse it rather than starting a second instance.
SUPABASE_STUDIO_FILTER = "supabase_studio"


def dotenvx_wrap(cmd: list[str]) -> list[str]:
    """Prepend `dotenvx run` so .env.development values are loaded into the command's env.

    `.env.keys` is auto-discovered next to the env file for encrypted values.
    """
    return ["dotenvx", "run", "-f", ENV_FILE, "--", *cmd]


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT, text=True)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


def ensure_tool(name: str, hint: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"error: `{name}` is required on PATH. {hint}")


def is_supabase_running() -> bool:
    """Check if the Supabase Studio Docker container is already running.

    Uses `docker ps --filter name=supabase_studio` so we don't rely on the
    `supabase` CLI — Docker is the ground truth for whether the stack is live.
    """
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"name={SUPABASE_STUDIO_FILTER}",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


# ---------------------------------------------------------------------------
# Demo app helpers
# ---------------------------------------------------------------------------


def _run_vite_server() -> None:
    """Target for the background thread: keep the Vite HMR dev server alive."""
    subprocess.run(
        dotenvx_wrap(["bun", "run", "dev"]),
        cwd=ROOT / DEMO_APP_DIR,
        text=True,
    )


def _run_electrobun() -> None:
    """Target for the background thread: build then launch the electrobun desktop app."""
    subprocess.run(
        dotenvx_wrap(["bun", "run", "start"]),
        cwd=ROOT / DEMO_APP_DIR,
        text=True,
    )


def start_demo_app() -> None:
    """Start the Vite HMR server + electrobun app, open the browser, watch for rebuilds.

    Flow:
      1. Launch the Vite HMR server in a daemon thread (non-blocking).
      2. Wait briefly for Vite to bind its port, then open the browser.
      3. Launch the electrobun desktop app in a daemon thread (non-blocking).
      4. Block on the file-watcher — rebuild electrobun whenever .ts/.tsx changes.
    """
    # 1. Vite HMR server
    vite_thread = threading.Thread(
        target=_run_vite_server, daemon=True, name="vite-hmr"
    )
    vite_thread.start()
    print("⚡ Vite HMR server starting...")

    # 2. Give Vite a moment to bind before opening the browser
    time.sleep(2)
    print(f"🌐 Opening browser at {VITE_URL} …")
    webbrowser.open(VITE_URL)

    # 3. Build and launch the electrobun desktop app
    # electrobun_thread = threading.Thread(
    #   target=_run_electrobun, daemon=True,
    #   name="electrobun"
    # )
    # electrobun_thread.start()
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
        run(dotenvx_wrap(["supabase", "start"]))
        print("\n✅ Supabase local stack is up.")

    # Print status (URLs + keys) for convenience — non-fatal if it fails.
    run(
        dotenvx_wrap(["supabase", "--network-id", "ivaecofevxactmmupvyp", "status"]),
        check=False,
    )
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
    run(dotenvx_wrap(["supabase", "stop"]))


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
