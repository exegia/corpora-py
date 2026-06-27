#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# ///
"""
Build the wheel for this project and embed it into the ElectroBun demo app's
standalone Python runtime.

Python equivalent of demo/app/scripts/build-embedded-python.ts

Usage:
    uv run python scripts/build_embedded_python.py [--platform ...] [--clean]
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
DEMO_RESOURCES = ROOT / "demo/app/resources/python"
BUNDLE_SCRIPT = ROOT / "scripts/bundle_python.py"


def run(cmd: list[str], cwd: Path = ROOT):
    print(f"$ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def find_wheel() -> Path:
    wheels = sorted(
        DIST_DIR.glob("corpora_py-*.whl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not wheels:
        wheels = sorted(
            DIST_DIR.glob("*.whl"), key=lambda p: p.stat().st_mtime, reverse=True
        )
    if not wheels:
        raise SystemExit("No wheel found in dist/. Did `uv build` succeed?")
    return wheels[0]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--platform",
        help="Target platform for the standalone Python (passed to bundle script)",
    )
    p.add_argument(
        "--clean", action="store_true", help="Remove previous resources/python first"
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Install with [full] extra (includes text-fabric for conversions)",
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
            import shutil

            shutil.rmtree(DEMO_RESOURCES)

    # 1. Build wheel
    print("\n==> Building wheel with uv...")
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    run(["uv", "build", "--wheel", f"--out-dir={DIST_DIR}"])

    wheel = find_wheel()
    print(f"    Found wheel: {wheel.name}")

    wheel_spec = f"{wheel}[full]" if args.full else str(wheel)
    print(f"\n==> Bundling standalone Python + wheel{'[full]' if args.full else ''}...")

    bundle_cmd = [sys.executable, str(BUNDLE_SCRIPT), wheel_spec]
    if args.platform:
        bundle_cmd += ["--platform", args.platform]
    bundle_cmd += ["--dest-dir", str(DEMO_RESOURCES)]

    run(bundle_cmd)

    print("\n✅ Done!")
    print(f"   Embedded Python is at: {DEMO_RESOURCES}/bin/python3")
    print("\n   To use it locally (without Docker dev override):")
    print("     unset DEV_PYTHON_BIN DEV_PYTHON_HOME")
    print("     bun run dev     # or the equivalent ElectroBun launch command")
    print("\n   The python-bridge will automatically use this embedded Python.")


if __name__ == "__main__":
    main()
