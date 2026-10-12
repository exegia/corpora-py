"""Regression checks for the shell sidecar build's runtime and archive contract."""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

BUILD = Path(__file__).resolve().parents[1] / "bin/build"


def test_trim_retains_api_stdlib_dependencies(tmp_path):
    runtime = tmp_path / "python"
    for layout in ("lib/python3.13", "Lib"):
        stdlib = runtime / layout
        for module in (
            "xml",
            "sqlite3",
            "winreg",
            "unittest",
            "pydoc.py",
            "asyncio/windows_events.py",
            "asyncio/windows_utils.py",
            "test",
            "turtledemo",
        ):
            path = stdlib / module
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("keep functional stdlib", encoding="utf-8")
    subprocess.run(["bash", str(BUILD / "trim.sh"), str(runtime)], check=True)
    layout = "Lib" if sys.platform == "win32" else "lib/python3.13"
    for module in (
        "xml",
        "sqlite3",
        "winreg",
        "unittest",
        "pydoc.py",
        "asyncio/windows_events.py",
        "asyncio/windows_utils.py",
    ):
        assert (runtime / layout / module).is_file(), module
    assert not (runtime / layout / "test").exists()
    assert not (runtime / layout / "turtledemo").exists()


def test_windows_archive_has_one_path_and_relative_members(tmp_path):
    runtime = tmp_path / "runtime space/python"
    runtime.mkdir(parents=True)
    (runtime / "source.txt").write_text("ὁ λόγος", encoding="utf-8")
    # Exercise Windows ZIP creation on Unix without external zip or Windows Python.
    (runtime / "python.exe").symlink_to(sys.executable)
    commands = tmp_path / "commands"
    commands.mkdir()
    uname = commands / "uname"
    uname.write_text("#!/usr/bin/env bash\necho MINGW64_NT\n", encoding="utf-8")
    uname.chmod(0o755)
    result = subprocess.run(
        [
            "bash",
            str(BUILD / "archive.sh"),
            "create",
            "runtime space/python",
            "dist space",
            "windows-x64",
        ],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
    )
    archive = Path(result.stdout.strip())
    assert result.stdout.splitlines() == [str(archive)]
    assert archive == tmp_path / "dist space/corpora-py-windows-x64.zip"
    with zipfile.ZipFile(archive) as packed:
        assert packed.testzip() is None
        assert packed.read("python/source.txt").decode() == "ὁ λόγος"
        assert all(name.startswith("python/") for name in packed.namelist())
