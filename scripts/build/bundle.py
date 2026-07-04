#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# ///
"""
Bundle a wheel into a standalone Python runtime.

This is used for the ElectroBun demo (and for producing the distributable
client runtime tarballs).

Usage:
    uv run python -m scripts.build.bundle <path-to-wheel.whl> [--platform ...] [--dest-dir ...] [--cache-dir ...]

The wheel arg supports extras syntax, e.g.:
    dist/corpora_py-0.1.0-py3-none-any.whl[full]
"""

import argparse
import platform
import tarfile
from pathlib import Path

from .archive import extract_python
from .download import download_standalone_python
from .env_vars import PLATFORM_MAP, PYTHON_VERSION
from .helpers import detect_platform, du, run
from .trim import trim_stdlib


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("wheel", help="Path to the wheel to bundle (supports wheel[extra])")
    p.add_argument(
        "--platform",
        choices=list(PLATFORM_MAP.keys()),
        help="Target platform (default: auto-detect)",
    )
    p.add_argument(
        "--dest-dir",
        default="demo/public/resources/python",
        help="Where to place the bundled python runtime",
    )
    p.add_argument(
        "--cache-dir",
        default=".cache/python-standalone",
        help="Cache dir for standalone Python tarballs",
    )
    p.add_argument(
        "--find-links",
        default=None,
        help="Local directory of pre-built wheels (used as --find-links so workspace deps are not fetched from PyPI)",
    )
    return p.parse_args()


def bundle_wheel(
    wheel_spec: str,
    platform_key: str | None = None,
    dest_dir: Path | str | None = None,
    cache_dir: Path | str | None = None,
    find_links: Path | str | None = None,
) -> Path:
    """
    Bundle the given wheel (may include [extra]) into a standalone Python at dest_dir.
    Produces a python-runtime-<plat>.tar.gz next to it for client opt-in.

    Returns the path to the created archive.
    """
    if platform_key is None:
        platform_key = detect_platform()
    if platform_key not in PLATFORM_MAP:
        raise SystemExit(f"Unknown platform: {platform_key}")

    info = PLATFORM_MAP[platform_key]

    dest = Path(dest_dir).resolve() if dest_dir else Path("demo/public/resources/python").resolve()
    cache = Path(cache_dir).resolve() if cache_dir else Path(".cache/python-standalone").resolve()

    # Resolve wheel + extras
    wheel_arg = wheel_spec
    if "[" in wheel_arg:
        wheel_path_str = wheel_arg.split("[")[0]
        extra_part = "[" + wheel_arg.split("[", 1)[1]
    else:
        wheel_path_str = wheel_arg
        extra_part = ""
    wheel_path = Path(wheel_path_str).resolve()
    if not wheel_path.exists():
        raise FileNotFoundError(f"Wheel not found: {wheel_path}")
    install_target = str(wheel_path) + extra_part if extra_part else str(wheel_path)

    print(f"==> Platform: {platform_key}")
    print(f"==> Python:   {PYTHON_VERSION}")
    print(f"==> Wheel:    {wheel_path}")

    # 1. Download / cache standalone
    tarball = download_standalone_python(platform_key, cache)

    # 2. Extract
    extract_python(tarball, dest)

    # 3. Install wheel (+ extras if present)
    print("==> Installing wheel with uv...")
    if platform.system() == "Windows":
        python_bin = dest / "python.exe"
    else:
        python_bin = dest / "bin" / "python3"
    install_cmd = [
        "uv", "pip", "install",
        "--python", str(python_bin),
        "--no-cache",
    ]
    # Allow resolving workspace deps from a local directory instead of PyPI
    if find_links is not None:
        install_cmd += ["--find-links", str(Path(find_links).resolve())]
    install_cmd.append(install_target)
    run(install_cmd)

    # 4. Trim
    print("==> Trimming stdlib...")
    trim_stdlib(dest)

    # 5. Report + produce distributable archive
    pylib = (
        dest / "lib" / "python3.13"
        if platform.system() != "Windows"
        else dest / "Lib"
    )

    total = du(dest)
    lib_size = (
        du(dest / "lib" / info["lib"])
        if (dest / "lib" / info["lib"]).exists()
        else "N/A"
    )
    stdlib_size = du(pylib) if pylib.exists() else "?"
    site_size = du(pylib / "site-packages") if (pylib / "site-packages").exists() else "?"

    print()
    print(f"==> Done! Bundled Python at: {dest}")
    print()
    print(f"    Total:         {total}")
    print(f"    Shared lib:    {lib_size} ({info['lib']})")
    print(f"    Stdlib:        {stdlib_size}")
    print(f"    Site-packages: {site_size}")

    archive = dest.parent / f"python-runtime-{platform_key}.tar.gz"
    print(f"==> Creating distributable archive for client opt-in: {archive}")
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(dest, arcname="python")
    print(f"    Ready to host: {archive}")

    return archive


def main():
    args = parse_args()
    bundle_wheel(
        wheel_spec=args.wheel,
        platform_key=args.platform,
        dest_dir=args.dest_dir,
        cache_dir=args.cache_dir,
        find_links=args.find_links,
    )


if __name__ == "__main__":
    main()
