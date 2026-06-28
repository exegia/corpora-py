#!/usr/bin/env python3
"""
Helper for the consumer/client app to ensure the embedded Python runtime is present.

Usage (example for client app code):
    from scripts.ensure_python_runtime import ensure_python_runtime
    ensure_python_runtime()  # or with target_dir

Logic:
- Check if <target>/bin/python3 exists and is executable.
- If yes: "already have", do nothing (or 'load what's there').
- If no: download the prebuilt tarball for the platform and extract.

For 'only load what's missing':
- Currently treats the runtime as atomic (full bundle or nothing).
- If you split features into multiple bundles later, extend the check (e.g. check for specific .so or packages).

You will need to:
- Host the python-runtime-*.tar.gz (produced by build_client_python_runtime.py or build_embedded --full)
  somewhere (GitHub Releases, S3, your CDN).
- Update DOWNLOAD_BASE_URL below.
- Adapt for your app's platform detection and storage location (e.g. app support dir instead of next to binary).

The ElectroBun client should call this before initializing PythonBridge if full features are opted in.
"""

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

# === CONFIG - update for your deployment ===
DOWNLOAD_BASE_URL = "https://your-cdn.example.com/corpora-runtimes"  # e.g. https://github.com/you/corpora-py/releases/download/vX.Y.Z/
# Example hosted names: python-runtime-macos-arm64.tar.gz , python-runtime-windows-x64.tar.gz , etc.


def get_platform_key() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        if "arm" in machine:
            return "macos-arm64"
        return "macos-x64"
    if system == "Linux" and "x86_64" in machine:
        return "linux-x64"
    if system == "Windows":
        return "windows-x64"
    raise RuntimeError(f"Unsupported platform: {system}-{machine}")


def ensure_python_runtime(target_dir: Path | None = None, force: bool = False) -> Path:
    """
    Ensure the embedded Python runtime exists at target_dir / 'python'.

    For the consumer/client app:
      1. FIRST check if they ALREADY have the python runtime
         (i.e. <target>/python/bin/python3 exists and works).
      2. If yes -> use it immediately ("only load what's missing" / use existing).
      3. If no -> download the pre-built full bundle and extract.

    "only load whats missing":
      - Today the runtime is delivered as one atomic bundle (the whole Python + packages).
      - If you later split (e.g. core + heavy corpus features as separate archives),
        you can extend this to download only the missing pieces.
      - Alternative path: if the user already has a system Python, you could
        create a venv and `pip install corpora-py[full]` instead of the big download.
        The current design prefers the self-contained bundle so the app has zero
        external Python dependency.

    Returns the path to the python binary.
    """
    if target_dir is None:
        # In a real client: use a stable user-writable location, e.g.
        # from platformdirs import user_data_dir
        # target_dir = Path(user_data_dir("YourClientApp")) / "python-runtime"
        target_dir = Path("demo/app/resources")  # demo default

    python_dir = target_dir / "python"
    if platform.system() == "Windows":
        python_bin = python_dir / "python.exe"
    else:
        python_bin = python_dir / "bin" / "python3"

    if python_bin.exists() and python_bin.is_file() and not force:
        print(f"✅ Embedded Python runtime ALREADY present at {python_bin}")
        print(
            "   Using what is already there (load only what's missing in future designs)."
        )
        return python_bin

    if python_dir.exists():
        print("Partial runtime detected — re-downloading full...")
        shutil.rmtree(python_dir, ignore_errors=True)

    plat = get_platform_key()
    archive_name = f"python-runtime-{plat}.tar.gz"
    url = f"{DOWNLOAD_BASE_URL.rstrip('/')}/{archive_name}"

    print(f"Downloading full runtime for {plat} from {url} ...")
    archive_path = target_dir / archive_name
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        urllib.request.urlretrieve(url, archive_path)
    except Exception as e:
        raise RuntimeError(
            f"Failed to download runtime: {e}. "
            "Host the archive produced by build_client_python_runtime.py "
            "and set DOWNLOAD_BASE_URL."
        ) from e

    print("Extracting...")
    with tarfile.open(archive_path, "r:gz") as tf:
        tf.extractall(target_dir)

    if not python_bin.exists():
        raise RuntimeError(f"Extracted runtime missing expected binary: {python_bin}")

    archive_path.unlink(missing_ok=True)
    print(f"✅ Runtime ready at {python_dir}")
    return python_bin


if __name__ == "__main__":
    # Demo usage
    ensure_python_runtime(Path("demo/app/resources"), force="--force" in sys.argv)
