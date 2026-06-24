#!/usr/bin/env python3
"""Installation script for the Exegia backend.

Steps:
    1. Install workspace dependencies via `uv sync`.
    2. Install `dotenvx` for reading the encrypted .env files.

Run via `uv run scripts/setup.py`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def ensure_uv() -> None:
    if shutil.which("uv") is None:
        sys.exit("error: `uv` is required. Install from https://docs.astral.sh/uv/")


def sync_dependencies() -> None:
    print("\n[1/2] Syncing workspace dependencies...")
    run(["uv", "sync"])


def install_dotenvx() -> None:
    print("\n[2/2] Installing dotenvx (encrypted .env loader)...")
    run(["uv", "add", "dotenvx"])


def main() -> None:
    ensure_uv()
    sync_dependencies()
    install_dotenvx()

    print("\nSetup complete.")


if __name__ == "__main__":
    main()
