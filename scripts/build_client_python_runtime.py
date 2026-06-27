#!/usr/bin/env python3
"""
Build the FULL Python runtime bundle for the consumer/client app opt-in.

This is the separate script for client features (full corpus with text-fabric etc.).

Run from repo root:
    uv run python scripts/build_client_python_runtime.py

It will:
- Build with [full] extra
- Produce the resources/python and the distributable .tar.gz (e.g. python-runtime-macos-arm64.tar.gz)
- The tarball is what the client app can host and download on user opt-in.

For admin/full local: use build_embedded_python.py --full

See also: scripts/ensure_python_runtime.py for the client-side downloader helper.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    print("Building FULL client Python runtime bundle (with text-fabric etc.)...")
    cmd = [
        sys.executable,
        str(ROOT / "scripts/build_embedded_python.py"),
        "--full",
        "--clean",
    ]
    print("$", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    # The bundle script already prints the archive name.
    print("\nClient full runtime bundle ready.")
    print("Host the python-runtime-*.tar.gz for client opt-in downloads.")


if __name__ == "__main__":
    main()
