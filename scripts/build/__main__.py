#!/usr/bin/env python3
"""
Entry point for `python -m scripts.build`

All build-related code lives under scripts/build/.

Usage examples:
  python -m scripts.build                    # main signed Tauri sidecar build
  python -m scripts.build bundle <wheel>     # bundle a wheel into runtime + tarball
  python -m scripts.build embedded [--full]  # build + embed for the demo
  python -m scripts.build client_runtime     # produce client full runtime tarball
"""

import sys
from pathlib import Path

# Make sure the scripts/ dir is importable when running as -m scripts.build...
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if len(sys.argv) > 1:
    sub = sys.argv[1]
    if sub in ("bundle", "embedded", "client_runtime", "client"):
        # Shift argv so the submodule's parse_args sees clean args
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        if sub in ("bundle",):
            from build.bundle import main as sub_main
        elif sub in ("embedded",):
            from build.embedded import main as sub_main
        else:
            from build.client_runtime import main as sub_main
        sub_main()
        sys.exit(0)

# Default behavior: the main signed build (for Tauri sidecar / CI)
from build import main  # noqa: E402

if __name__ == "__main__":
    main()
