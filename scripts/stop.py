#!/usr/bin/env python3
"""Stop local dev servers launched from this project.

Terminates any uvicorn/FastAPI processes whose command line references
this project root. Caches and on-disk state are preserved.

Usage:
    uv run scripts/stop.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def stop_dev_processes() -> None:
    if shutil.which("pkill") is None:
        print("pkill not available — cannot terminate uvicorn processes.")
        return
    pattern = f"uvicorn.*{ROOT}"
    result = subprocess.run(["pkill", "-f", pattern], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Terminated uvicorn processes matching {pattern!r}.")
    elif result.returncode == 1:
        print("No matching uvicorn processes found.")
    else:
        print(f"warning: pkill exited {result.returncode}: {result.stderr.strip()}", file=sys.stderr)


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    ).parse_args()

    stop_dev_processes()
    print("\nDone.")


if __name__ == "__main__":
    main()
