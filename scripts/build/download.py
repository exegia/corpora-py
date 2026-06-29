from pathlib import Path

from .helpers import run
from .env_vars import PLATFORM_MAP, PYTHON_VERSION, STANDALONE_VERSION


def download_standalone_python(platform_key: str, cache_dir: Path) -> Path:
    info = PLATFORM_MAP[platform_key]
    tarball_name = (
        f"cpython-{PYTHON_VERSION}+{STANDALONE_VERSION}"
        f"-{info['standalone']}-install_only.tar.gz"
    )
    url = (
        f"https://github.com/astral-sh/python-build-standalone/releases/download"
        f"/{STANDALONE_VERSION}/{tarball_name}"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / tarball_name
    if not cached.exists():
        print(f"==> Downloading standalone Python ({platform_key})...")
        run(["curl", "-L", "--progress-bar", "-o", str(cached), url])
    else:
        print(f"==> Using cached standalone Python: {cached.name}")
    return cached
