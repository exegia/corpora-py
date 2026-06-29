from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from .env_vars import DOWNLOAD_BASE_URL, PLATFORM_MAP


# ── Helpers ───────────────────────────────────────────────────────────────────



def pylib_dir(python_dir: Path) -> Path:
    """Return the platform-appropriate stdlib directory.

    python-build-standalone uses different layouts per OS:
      Unix:    lib/python3.13/
      Windows: Lib/   (capital L, no version suffix, at root)
    """
    if platform.system() == "Windows":
        return python_dir / "Lib"
    return python_dir / "lib" / "python3.13"


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)

def du(p: Path) -> str:
    try:
        out = subprocess.check_output(["du", "-sh", str(p)], text=True)
        return out.split()[0]
    except Exception:
        return "?"

def detect_platform() -> str:
    os_name = platform.system()
    arch = platform.machine()
    if os_name == "Darwin" and arch == "arm64":
        return "macos-arm64"
    if os_name == "Darwin" and arch == "x86_64":
        return "macos-x64"
    if os_name == "Windows" and arch == "AMD64":
        return "windows-x64"
    raise SystemExit(
        f"Cannot auto-detect platform for {os_name}-{arch}. Use --platform."
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--platform",
        choices=list(PLATFORM_MAP),
        help="Target platform (default: auto-detect current OS)",
    )
    p.add_argument(
        "--out-dir",
        default="lib",
        help="Directory for the output archive (default: lib/)",
    )
    p.add_argument(
        "--dest-dir",
        default="lib/resources/python",
        help="Staging directory for the bundled Python (default: lib/resources/python/)",
    )
    p.add_argument(
        "--cache-dir",
        default=".cache/python-standalone",
        help="Cache dir for standalone Python downloads",
    )
    p.add_argument(
        "--skip-sign",
        action="store_true",
        default=False,
        help="Skip code signing and notarization (signing is ON by default; use this for local/CI without certs)",
    )
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip uv build — use the newest existing wheel in --out-dir",
    )
    return p.parse_args()

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


def generate_app_paths(python_dir: Path):
    identifier = os.environ.get("APP_IDENTIFIER", "io.exegia.Corpora")
    if not identifier:
        print("    Skipping app_paths.py — APP_IDENTIFIER not set.")
        return

    channel = os.environ.get("APP_CHANNEL", "stable")
    site_packages = pylib_dir(python_dir) / "site-packages"
    (site_packages / "app_paths.py").write_text(
        f'''\
"""Auto-generated — platform paths for the host Tauri application."""
import os
from pathlib import Path

_home = Path.home()
_platform = __import__("sys").platform

IDENTIFIER = "{identifier}"
CHANNEL = "{channel}"

if _platform == "darwin":
    app_data = _home / "Library" / "Application Support"
    cache = _home / "Library" / "Caches"
    logs = _home / "Library" / "Logs"
    temp = Path(os.environ.get("TMPDIR", "/tmp"))
elif _platform == "win32":
    app_data = Path(os.environ.get("LOCALAPPDATA", str(_home / "AppData" / "Local")))
    cache = app_data
    logs = app_data
    temp = Path(os.environ.get("TEMP", str(app_data / "Temp")))
else:
    app_data = Path(os.environ.get("XDG_DATA_HOME", str(_home / ".local" / "share")))
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(_home / ".cache")))
    logs = Path(os.environ.get("XDG_STATE_HOME", str(_home / ".local" / "state")))
    temp = Path("/tmp")

home = _home
config = app_data
documents = _home / "Documents"
downloads = _home / "Downloads"
desktop = _home / "Desktop"

user_data = app_data / IDENTIFIER / CHANNEL
user_cache = cache / IDENTIFIER / CHANNEL
user_logs = logs / IDENTIFIER / CHANNEL
''',
        encoding="utf-8",
    )
    print(f"    APP_IDENTIFIER: {identifier}  channel: {channel}")

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
        target_dir = Path("demo/public/resources")  # demo default

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
            "Host the archive produced by python -m scripts.build.client_runtime "
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
