"""Verify the extracted sidecar using its own interpreter before publishing."""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def verify_runtime(version: str, target: str) -> None:
    import sqlite3
    from xml.etree import ElementTree

    from admin.converters.tei import convert_to_ctei, encoding, validate_ctei_archive
    from admin.parsers.schema import SourceFormat
    from fastapi.testclient import TestClient

    from corpora_py.app import app

    assert importlib.metadata.version("corpora-py") == version
    assert Path(encoding.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert platform.machine().lower() in (
        {"arm64", "aarch64"} if target == "macos-arm64" else {"x86_64", "amd64"}
    )
    assert sys.platform == ("win32" if target == "windows-x64" else "darwin")
    if target == "windows-x64":
        import asyncio.windows_events  # noqa: F401
        import winreg  # noqa: F401

    with sqlite3.connect(":memory:") as db:
        assert db.execute("SELECT 1").fetchone() == (1,)
    assert ElementTree.fromstring("<source>ὁ λόγος</source>").text == "ὁ λόγος"

    profile = Path(encoding.__file__).parent / "profile"
    provenance = json.loads((profile / "provenance.json").read_text())
    for name in ("profile.odd", "profile.rng", "profile.sch", "upstream/tei_all.rng"):
        assert hashlib.sha256((profile / name).read_bytes()).hexdigest() == provenance[name]

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "source.txt"
        text = "Exact ὁ λόγος e\u0301\u00a0word.\n\nSecond paragraph."
        source.write_bytes(text.encode("utf-8"))
        archive = root / "document.ctei"
        convert_to_ctei(source, archive, source_format=SourceFormat.PLAIN)
        verdict = validate_ctei_archive(archive)
        assert verdict["valid"] and not verdict["source_verified"]
        with zipfile.ZipFile(archive) as packed:
            assert packed.read("assets/source/original.txt") == source.read_bytes()

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200, response.text
    print(f"Verified {target}: corpora-py {version}, API health, SQLite, XML and CTEI conversion")


def verify_archive(archive: Path, version: str, target: str) -> None:
    archive = archive.resolve()
    with zipfile.ZipFile(archive) as packed:
        assert packed.testzip() is None
        assert all(name.startswith("python/") for name in packed.namelist())
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        if sys.platform == "darwin":
            # zipfile extraction does not restore Unix symlinks/permissions.
            subprocess.run(["ditto", "-x", "-k", str(archive), str(root)], check=True)
            interpreter = root / "python/bin/python3"
        else:
            with zipfile.ZipFile(archive) as packed:
                packed.extractall(root)
            interpreter = root / "python/python.exe"
        subprocess.run(
            [str(interpreter), "-I", str(Path(__file__).resolve()), "runtime", version, target],
            check=True,
            cwd=root,
        )

    (wheel,) = archive.parent.glob("*.whl")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert wheel_hash == os.environ["WHEEL_SHA256"]
    receipt = {
        "version": version,
        "platform": target,
        "source_commit": os.environ["SOURCE_SHA"],
        "wheel_sha256": wheel_hash,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "signed": os.environ["SKIP_SIGN"] != "true",
        "workflow_commit": os.environ["GITHUB_SHA"],
        "workflow_run": f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        "verification": [
            "extracted runtime",
            "API health",
            "SQLite",
            "XML",
            "CTEI conversion",
            "TEI schema hashes",
        ],
    }
    archive.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "archive":
        verify_archive(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    elif sys.argv[1] == "runtime":
        verify_runtime(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("Usage: verify.py archive ZIP VERSION PLATFORM | runtime VERSION PLATFORM")
