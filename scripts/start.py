#!/usr/bin/env python3
"""Start the local Supabase dev stack with dotenvx-loaded env.

Every Supabase call is wrapped with `dotenvx run -f .env.development --` so
secrets from `.env.development` (decrypted via `.env.keys` when encrypted) are
injected into the command's environment. This keeps local dev consistent with
how production reads env vars and avoids leaking values into the parent shell.

Steps:
    1. Verify `dotenvx`, `supabase`, and `docker` are on PATH.
    2. Check whether the stack is already up (idempotent).
    3. Run `supabase start` from the project root, under dotenvx.
    4. Print status (URLs + keys) on success.

Usage:
    uv run scripts/start.py          # start the local stack
    uv run scripts/start.py --stop   # stop it
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ".env.development"


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


def is_stack_running() -> bool:
    """`supabase status` exits non-zero when the stack is down."""
    result = subprocess.run(
        dotenvx_wrap(["supabase", "status"]),
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def start() -> None:
    ensure_tool(
        "dotenvx",
        "Install: `uv add dotenvx` (already in setup.py) or https://dotenvx.com/docs/install",
    )
    ensure_tool(
        "supabase",
        "Install: https://supabase.com/docs/guides/local-development/cli/getting-started",
    )
    ensure_tool("docker", "Install Docker Desktop and make sure it is running.")

    if is_stack_running():
        print("Supabase local stack is already running.\n")
        run(dotenvx_wrap(["supabase", "status"]))
        return

    print("Starting Supabase local stack (Docker containers may take a minute)...")
    run(dotenvx_wrap(["supabase", "start"]))
    print("\nSupabase local stack is up.")


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stop", action="store_true", help="Stop the local Supabase stack instead of starting it.")
    args = parser.parse_args()

    if args.stop:
        stop()
    else:
        start()


if __name__ == "__main__":
    main()
