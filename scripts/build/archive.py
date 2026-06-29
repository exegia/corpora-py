import argparse
import platform
import shutil
import zipfile
from pathlib import Path

from .env_vars import PLATFORM_MAP
from .helpers import run

def create_unsigned_archive(python_dir: Path, out_dir: Path, platform_key: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"corpora-py-{platform_key}.zip"
    print(f"==> Creating unsigned archive: {archive.name}")

    if platform.system() == "Darwin":
        run(["ditto", "-c", "-k", "--keepParent", str(python_dir), str(archive)])
    else:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for f in python_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(python_dir.parent))

    return archive

def extract_python(tarball: Path, dest: Path):
    print("==> Extracting standalone Python...")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    run(["tar", "-xzf", str(tarball), "-C", str(dest), "--strip-components=1"])

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--clean", action="store_true", help="Remove previous lib/python first"
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Install with [full] extra (includes text-fabric for conversions)",
    )
    p.add_argument("wheel", help="Path to the wheel to embed")
    p.add_argument(
        "--platform", choices=list(PLATFORM_MAP.keys()), help="Target platform"
    )
    p.add_argument(
        "--dest-dir",
        default="demo/build/lib/python",
        help="Where to place the bundled python (default: demo/build/lib/python)",
    )
    p.add_argument(
        "--cache-dir",
        default=".cache/python-standalone",
        help="Cache dir for standalone Python tarballs",
    )
    return p.parse_args()
