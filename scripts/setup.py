#!/usr/bin/env python3
"""Installation script for the Exegia backend.

Steps:
    1. Install workspace dependencies via `uv sync`.
    2. Install `dotenvx` for reading the encrypted .env files.
    3. Install demo app (Bun) dependencies.
    4. Build embedded Python runtime for the demo (if not already present).

Run via `uv run scripts/setup.py`.
"""

from __future__ import annotations

import sys

from utils import ROOT, ensure_tool, run


def is_uv_install() -> None:
    ensure_tool(
        "uv",
        "error: `uv` is required. Install from https://docs.astral.sh/uv/",
        ["curl", "-LsSf", "https://astral.sh/uv/install.sh", "|", "sh"],
    )


def sync_dependencies() -> None:
    print("\n[1/3] Syncing workspace dependencies...")
    run(["uv", "sync"])


def install_dotenvx() -> None:
    print("\n[2/3] Installing dotenvx (encrypted .env loader)...")
    run(["uv", "add", "dotenvx"])


def install_demo_deps() -> None:
    print("\n[3/4] Installing the demo app dependencies...")
    demo_app_dir = ROOT / "demo"
    run(cmd=["bun", "install", "--no-cache"], dir=demo_app_dir)


def build_demo_python_runtime() -> None:
    print("\n[4/4] Ensuring embedded Python runtime for the demo...")
    # All build logic now lives under scripts/build/
    #   - python -m scripts.build.embedded
    #   - python -m scripts.build.bundle
    run(
        [sys.executable, "-m", "scripts.build.embedded"],
        dotenvx=False,
    )


def main() -> None:
    is_uv_install()
    sync_dependencies()
    install_dotenvx()
    install_demo_deps()
    build_demo_python_runtime()

    print("\nSetup complete.")


if __name__ == "__main__":
    main()
