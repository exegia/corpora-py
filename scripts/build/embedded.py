#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# ///
"""
Build the wheel for this project and embed it into the ElectroBun demo app's
standalone Python runtime.

This is primarily for the DEMO / ADMIN use case (full size is acceptable).

For the CONSUMER/CLIENT app:
- Use the base install (without [full]).
- On user opt-in for full corpus features, the client downloads a pre-built
  runtime archive instead of bundling at install time.

Usage:
    uv run python -m scripts.build.embedded [--platform ...] [--clean] [--full]
"""

import argparse
import shutil

from .env_vars import DIST_DIR, DEMO_RESOURCES, PLATFORM_MAP, ROOT
from .helpers import run
from .wheel import find_wheel
from .bundle import bundle_wheel


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--platform",
        choices=list(PLATFORM_MAP.keys()),
        help="Target platform (default: auto-detect)",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous resources/python first",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Install with [full] extra (includes text-fabric etc. for admin/demo)",
    )
    return p.parse_args()


def main():
    args = parse_args()

    python_bin = DEMO_RESOURCES / "bin" / "python3"

    if python_bin.exists() and not args.clean:
        print("==> Embedded Python runtime for demo already present (skipping).")
        print(f"   {python_bin}")
        return

    print("==> Building embedded Python for ElectroBun demo")
    print(f"    Repo root: {ROOT}")
    print(f"    Target:    {DEMO_RESOURCES}")

    if args.clean:
        print("==> Cleaning previous resources/python")
        if DEMO_RESOURCES.exists():
            shutil.rmtree(DEMO_RESOURCES)

    # 1. Build all workspace wheels so they can be resolved locally (not from PyPI)
    print("\n==> Building workspace wheels with uv...")
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    run(["uv", "build", "--package", "corpora-shared-py", "--wheel", f"--out-dir={DIST_DIR}"])
    run(["uv", "build", "--package", "corpora-client-py", "--wheel", f"--out-dir={DIST_DIR}"])
    run(["uv", "build", "--package", "corpora-admin-py",  "--wheel", f"--out-dir={DIST_DIR}"])
    # Umbrella (corpora-py) last — depends on the three above
    run(["uv", "build", "--wheel", f"--out-dir={DIST_DIR}"])

    wheel = find_wheel(DIST_DIR)
    print(f"    Found wheel: {wheel.name}")

    wheel_spec = f"{wheel}[full]" if args.full else str(wheel)
    print(f"\n==> Bundling standalone Python + wheel{'[full]' if args.full else ''}...")

    # Directly call the bundler (no subprocess indirection)
    bundle_wheel(
        wheel_spec=wheel_spec,
        platform_key=args.platform,
        dest_dir=DEMO_RESOURCES,
        find_links=DIST_DIR,
    )

    print("\n✅ Done!")
    print(f"   Embedded Python is at: {DEMO_RESOURCES}/bin/python3")
    print("\n   To use it locally (without Docker dev override):")
    print("     unset DEV_PYTHON_BIN DEV_PYTHON_HOME")
    print("     bun run dev     # or the equivalent ElectroBun launch command")
    print("\n   The python-bridge will automatically use this embedded Python.")


if __name__ == "__main__":
    main()
