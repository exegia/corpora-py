import platform
from pathlib import Path

from .helpers import run


def build_wheel(out_dir: Path) -> Path:
    """Build all workspace wheels and return the umbrella corpora-py wheel."""
    print("==> Building workspace wheels with uv...")
    run(["uv", "build", "--package", "corpora-shared-py", "--wheel", f"--out-dir={out_dir}"])
    run(["uv", "build", "--package", "corpora-client-py", "--wheel", f"--out-dir={out_dir}"])
    run(["uv", "build", "--package", "corpora-admin-py",  "--wheel", f"--out-dir={out_dir}"])
    # Umbrella last — depends on the three above
    run(["uv", "build", "--wheel", f"--out-dir={out_dir}"])
    return find_wheel(out_dir)


def find_wheel(out_dir: Path) -> Path:
    """Return the umbrella corpora-py wheel from out_dir."""
    # Prefer the umbrella wheel specifically so we don't accidentally pick a sub-package
    umbrella = sorted(out_dir.glob("corpora_py-*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if umbrella:
        return umbrella[0]
    # Fallback: any wheel (e.g. when called before workspace split)
    wheels = sorted(out_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wheels:
        raise SystemExit(f"No wheel found in {out_dir}.")
    return wheels[0]


def install_wheel(wheel: Path, python_dir: Path, find_links: Path | None = None):
    """Install a wheel into a standalone Python, optionally resolving deps from a local dir."""
    print("==> Installing wheel with uv...")
    if platform.system() == "Windows":
        python_bin = python_dir / "python.exe"
    else:
        python_bin = python_dir / "bin" / "python3"
    cmd = ["uv", "pip", "install", "--python", str(python_bin), "--no-cache"]
    if find_links is not None:
        cmd += ["--find-links", str(find_links.resolve())]
    cmd.append(str(wheel))
    run(cmd)
