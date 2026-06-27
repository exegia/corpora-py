#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# ///
"""
Bundle a wheel into a standalone Python runtime for the ElectroBun demo app.

This is the Python equivalent of demo/app/scripts/bundle-python.ts .

Usage:
    uv run python scripts/bundle_python.py <path-to-wheel.whl> [--platform ...] [--dest-dir ...] [--cache-dir ...]

Defaults (when run from repo root):
  --dest-dir   demo/app/resources/python
  --cache-dir  .cache/python-standalone
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

PYTHON_VERSION = "3.13.14"
STANDALONE_VERSION = "20260623"

PLATFORM_MAP = {
    "macos-arm64": {"standalone": "aarch64-apple-darwin", "lib": "libpython3.13.dylib"},
    "macos-x64": {"standalone": "x86_64-apple-darwin", "lib": "libpython3.13.dylib"},
    "linux-x64": {"standalone": "x86_64-unknown-linux-gnu", "lib": "libpython3.13.so"},
    "windows-x64": {
        "standalone": "x86_64-pc-windows-msvc-shared",
        "lib": "python313.dll",
    },
}


def run(cmd: list[str], **kwargs):
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def detect_platform() -> str:
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin":
        if machine == "arm64":
            return "macos-arm64"
        if machine == "x86_64":
            return "macos-x64"
    elif system == "Linux" and machine == "x86_64":
        return "linux-x64"
    elif system == "Windows" and machine in ("AMD64", "x86_64"):
        return "windows-x64"
    raise SystemExit(
        f"Cannot auto-detect platform for {system}-{machine}. Use --platform."
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("wheel", help="Path to the wheel to embed")
    p.add_argument(
        "--platform", choices=list(PLATFORM_MAP.keys()), help="Target platform"
    )
    p.add_argument(
        "--dest-dir",
        default="demo/app/resources/python",
        help="Where to place the bundled python (default: demo/app/resources/python)",
    )
    p.add_argument(
        "--cache-dir",
        default=".cache/python-standalone",
        help="Cache dir for standalone Python tarballs",
    )
    return p.parse_args()


def main():
    args = parse_args()

    wheel_path = Path(args.wheel).resolve()
    if not wheel_path.exists():
        print(f"Wheel not found: {wheel_path}", file=sys.stderr)
        sys.exit(1)

    platform_key = args.platform or detect_platform()
    if platform_key not in PLATFORM_MAP:
        raise SystemExit(f"Unknown platform: {platform_key}")

    info = PLATFORM_MAP[platform_key]
    dest_dir = Path(args.dest_dir).resolve()
    cache_dir = Path(args.cache_dir).resolve()

    print(f"==> Platform: {platform_key}")
    print(f"==> Python:   {PYTHON_VERSION}")
    print(f"==> Wheel:    {wheel_path}")

    # 1. Download standalone Python
    tarball_name = f"cpython-{PYTHON_VERSION}+{STANDALONE_VERSION}-{info['standalone']}-install_only.tar.gz"
    url = f"https://github.com/astral-sh/python-build-standalone/releases/download/{STANDALONE_VERSION}/{tarball_name}"

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / tarball_name
    if not cached.exists():
        print("==> Downloading standalone Python...")
        run(["curl", "-L", "--progress-bar", "-o", str(cached), url])
    else:
        print(f"==> Using cached download: {cached}")

    # 2. Extract
    print("==> Extracting...")
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)

    with tarfile.open(cached, "r:gz") as tf:
        # strip-components=1 equivalent
        members = []
        for m in tf.getmembers():
            parts = Path(m.name).parts
            if len(parts) > 1:
                m.name = str(Path(*parts[1:]))
            members.append(m)
        tf.extractall(dest_dir, members=members)

    # 3. Install wheel with uv
    print("==> Installing wheel with uv...")
    if platform.system() == "Windows":
        python_bin = dest_dir / "python.exe"
    else:
        python_bin = dest_dir / "bin" / "python3"
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python_bin),
            "--no-cache",
            str(wheel_path),
        ]
    )

    # 4. Trim stdlib
    print("==> Trimming stdlib...")
    pylib = (
        dest_dir / "lib" / "python3.13"
        if platform.system() != "Windows"
        else dest_dir / "Lib"
    )

    remove_items = [
        "test",
        "unittest",
        "tkinter",
        "idlelib",
        "turtledemo",
        "turtle.py",
        "ensurepip",
        "lib2to3",
        "pydoc_data",
        "doctest.py",
        "_pydecimal.py",
        "pydoc.py",
        "mailbox.py",
        "imaplib.py",
        "nntplib.py",
        "poplib.py",
        "smtplib.py",
        "ftplib.py",
        "xmlrpc",
        "curses",
        "multiprocessing",
        "concurrent",
    ]
    for item in remove_items:
        target = pylib / item
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)

    # cleanup pycache / pyc / other heavy dirs
    for root, dirs, files in os.walk(dest_dir):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(Path(root) / d, ignore_errors=True)
                dirs.remove(d)
        for f in files:
            if f.endswith(".pyc"):
                (Path(root) / f).unlink(missing_ok=True)

    for d in ["share", "man", "lib/pkgconfig", "include"]:
        p = dest_dir / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    if platform.system() != "Windows":
        for a in dest_dir.rglob("*.a"):
            a.unlink(missing_ok=True)

    # 5. Report
    def du(p: Path) -> str:
        try:
            out = subprocess.check_output(["du", "-sh", str(p)], text=True)
            return out.split()[0]
        except Exception:
            return "?"

    total = du(dest_dir)
    lib_size = (
        du(dest_dir / "lib" / info["lib"])
        if (dest_dir / "lib" / info["lib"]).exists()
        else "N/A"
    )
    stdlib_size = du(pylib) if pylib.exists() else "?"
    site_size = (
        du(pylib / "site-packages") if (pylib / "site-packages").exists() else "?"
    )

    print()
    print(f"==> Done! Bundled Python at: {dest_dir}")
    print()
    print(f"    Total:         {total}")
    print(f"    Shared lib:    {lib_size} ({info['lib']})")
    print(f"    Stdlib:        {stdlib_size}")
    print(f"    Site-packages: {site_size}")


if __name__ == "__main__":
    main()
