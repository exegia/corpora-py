import os
import platform
import shutil
import subprocess
from pathlib import Path

from .env_vars import STDLIB_TRIM
from .helpers import pylib_dir

# Note on trimming: we only remove stdlib modules that are provably unused
# by the runtime packages (cfabric, supabase stack, fastmcp, exegia, etc.)
# See STDLIB_TRIM in env_vars.py. We deliberately keep 'email', 'http',
# 'concurrent', 'xml' etc. because they are required by importlib, urllib/httpx,
# asyncio, and lxml/parsers indirectly.

def trim_stdlib(python_dir: Path):
    print("==> Trimming stdlib...")
    pylib = pylib_dir(python_dir)
    for item in STDLIB_TRIM:
        target = pylib / item
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

    if platform.system() != "Windows":
        subprocess.run(
            [
                "find",
                str(python_dir),
                "-name",
                "__pycache__",
                "-type",
                "d",
                "-exec",
                "rm",
                "-rf",
                "{}",
                "+",
            ],
            capture_output=True,
        )
        subprocess.run(
            ["find", str(python_dir), "-name", "*.pyc", "-delete"],
            capture_output=True,
        )
        subprocess.run(
            ["find", str(python_dir / "lib"), "-name", "*.a", "-delete"],
            capture_output=True,
        )
    else:
        for pyc in python_dir.rglob("*.pyc"):
            pyc.unlink(missing_ok=True)
        for cache in python_dir.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)

    for d in [
        python_dir / "share",
        python_dir / "man",
        python_dir / "lib" / "pkgconfig",
        python_dir / "include",
    ]:
        if d.exists():
            shutil.rmtree(d)

def clean_up(dest_dir: Path):
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

    # Remove unnecessary installer tools from the final bundle
    pylib = pylib_dir(python_dir=dest_dir)
    for tool in ["pip", "wheel", "setuptools"]:
        tool_dir = pylib / "site-packages" / tool
        if tool_dir.exists():
            shutil.rmtree(tool_dir, ignore_errors=True)
        # also remove dist-info
        for dinfo in (pylib / "site-packages").glob(f"{tool}*.dist-info"):
            shutil.rmtree(dinfo, ignore_errors=True)
