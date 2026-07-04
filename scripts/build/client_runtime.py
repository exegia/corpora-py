#!/usr/bin/env python3
"""
Build the FULL Python runtime bundle for the consumer/client app opt-in.

This is the driver for client features (full corpus with text-fabric etc.).

Run from repo root:
    uv run python -m scripts.build.client_runtime

It will:
- Build with [full] extra
- Produce the resources/python and the distributable .tar.gz (e.g. python-runtime-macos-arm64.tar.gz)
- The tarball is what the client app can host and download on user opt-in.

For admin/full local demo: use
    uv run python -m scripts.build.embedded --full --clean
"""

import sys
from pathlib import Path

# scripts/build/client_runtime.py  -> go up to repo root for cwd
_here = Path(__file__).resolve().parent.parent.parent   # repo root
sys.path.insert(0, str(_here / "scripts"))

from build.embedded import main as embedded_main  # noqa: E402


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        print("This driver always runs with --full --clean.")
        print("See: python -m scripts.build.embedded --help")
        return

    print("Building FULL client Python runtime bundle (with text-fabric etc.)...")
    # Force clean + full via direct call (everything now lives in scripts/build/)
    orig_argv = sys.argv[:]
    sys.argv = ["embedded", "--full", "--clean"]
    try:
        embedded_main()
    finally:
        sys.argv = orig_argv

    print("\nClient full runtime bundle ready.")
    print("Host the python-runtime-*.tar.gz for client opt-in downloads.")


if __name__ == "__main__":
    main()
