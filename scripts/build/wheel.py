import platform
from pathlib import Path

from .helpers import run

def build_wheel(out_dir: Path) -> Path:
    print("==> Building wheel with uv...")
    run(["uv", "build", "--wheel", f"--out-dir={out_dir}"])
    return find_wheel(out_dir)


def find_wheel(out_dir: Path) -> Path:
    wheels = sorted(
        out_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not wheels:
        raise SystemExit(f"No wheel found in {out_dir}.")
    return wheels[0]


def install_wheel(wheel: Path, python_dir: Path):
    print("==> Installing wheel with uv...")
    if platform.system() == "Windows":
        python_bin = python_dir / "python.exe"
    else:
        python_bin = python_dir / "bin" / "python3"
    run(["uv", "pip", "install", "--python", str(python_bin), "--no-cache", str(wheel)])
