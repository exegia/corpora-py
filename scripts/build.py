#!/usr/bin/env python3
"""
Build, bundle, sign, and archive corpora-py for use as a Tauri sidecar resource.

Runs once per platform on a matching OS runner. Designed for GitHub Actions
matrix jobs — one runner per target OS (macOS-arm64, macOS-x64, Windows-x64).

Usage:
    uv run python scripts/build.py [--platform <platform>] [--skip-sign] [--skip-build]

Environment variables for signing:
  macOS:
    APPLE_CERTIFICATE           Base64-encoded .p12 certificate
    APPLE_CERTIFICATE_PASSWORD  Password for the .p12
    APPLE_SIGNING_IDENTITY      e.g. "Developer ID Application: Acme Corp (TEAMID)"
    APPLE_ID                    Apple ID for notarization
    APPLE_PASSWORD              App-specific password (not your Apple ID password)
    APPLE_TEAM_ID               Apple Developer Team ID
  Windows:
    WINDOWS_CERTIFICATE_THUMBPRINT  SHA-1 thumbprint of the code-signing certificate
    WINDOWS_SIGN_COMMAND            Optional: override full signtool invocation template
                                    (use {path} as the file placeholder)
  Shared:
    APP_IDENTIFIER              Reverse-DNS app identifier written into app_paths.py
                                (e.g. "com.example.myapp"). Optional.
    APP_CHANNEL                 Release channel written into app_paths.py (default: stable)
"""

import argparse
import base64
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ── Version pins ──────────────────────────────────────────────────────────────
# Keep in sync with demo/app/scripts/bundle-python.sh and bundle-python.ts
PYTHON_VERSION = "3.13.14"
STANDALONE_VERSION = "20260623"

# ── Platform map ──────────────────────────────────────────────────────────────
PLATFORM_MAP = {
    "macos-arm64": {
        "standalone": "aarch64-apple-darwin",
        "lib": "libpython3.13.dylib",
        "tauri_triple": "aarch64-apple-darwin",
    },
    "macos-x64": {
        "standalone": "x86_64-apple-darwin",
        "lib": "libpython3.13.dylib",
        "tauri_triple": "x86_64-apple-darwin",
    },
    "windows-x64": {
        "standalone": "x86_64-pc-windows-msvc-shared",
        "lib": "python313.dll",
        "tauri_triple": "x86_64-pc-windows-msvc",
    },
}

STDLIB_TRIM = [
    # GUI / interactive tooling — never needed in a headless MCP server
    "tkinter", "idlelib", "turtledemo", "turtle.py", "curses",
    # Test infrastructure
    "test", "unittest",
    # Build / packaging helpers not needed at runtime
    "ensurepip", "lib2to3",
    # Documentation / REPL helpers
    "pydoc_data", "pydoc.py", "doctest.py",
    # Rarely-used stdlib modules not pulled in by any dependency in pyproject.toml
    "_pydecimal.py", "mailbox.py", "imaplib.py", "nntplib.py", "poplib.py",
    "smtplib.py", "ftplib.py", "xmlrpc",
    # Windows-only asyncio modules (removed on Unix; harmless no-ops if absent on Windows
    # because they are never imported on non-Windows)
    "asyncio/windows_events.py", "asyncio/windows_utils.py",
    # NOTE: concurrent, multiprocessing, and asyncio are intentionally kept —
    # anyio, starlette, uvicorn, httpx, and fastmcp all import them at runtime.
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


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
        default="dist",
        help="Directory for the output archive (default: dist/)",
    )
    p.add_argument(
        "--dest-dir",
        default="resources/python",
        help="Staging directory for the bundled Python (default: resources/python/)",
    )
    p.add_argument(
        "--cache-dir",
        default=".cache/python-standalone",
        help="Cache dir for standalone Python downloads",
    )
    p.add_argument(
        "--skip-sign",
        action="store_true",
        help="Skip code signing and notarization (useful for local builds)",
    )
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip uv build — use the newest existing wheel in --out-dir",
    )
    return p.parse_args()


# ── Step 1: Build wheel ───────────────────────────────────────────────────────

def build_wheel(out_dir: Path) -> Path:
    print("==> Building wheel with uv...")
    run(["uv", "build", "--wheel", f"--out-dir={out_dir}"])
    return _find_wheel(out_dir)


def _find_wheel(out_dir: Path) -> Path:
    wheels = sorted(out_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wheels:
        raise SystemExit(f"No wheel found in {out_dir}.")
    return wheels[0]


# ── Step 2: Download standalone Python ───────────────────────────────────────

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


# ── Step 3: Extract ───────────────────────────────────────────────────────────

def extract_python(tarball: Path, dest: Path):
    print("==> Extracting standalone Python...")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    run(["tar", "-xzf", str(tarball), "-C", str(dest), "--strip-components=1"])


# ── Step 4: Install wheel + deps ──────────────────────────────────────────────

def install_wheel(wheel: Path, python_dir: Path):
    print("==> Installing wheel with uv...")
    if platform.system() == "Windows":
        python_bin = python_dir / "python.exe"
    else:
        python_bin = python_dir / "bin" / "python3"
    run(["uv", "pip", "install", "--python", str(python_bin), "--no-cache", str(wheel)])


# ── Step 5: Trim stdlib ───────────────────────────────────────────────────────

def _pylib_dir(python_dir: Path) -> Path:
    """Return the platform-appropriate stdlib directory.

    python-build-standalone uses different layouts per OS:
      Unix:    lib/python3.13/
      Windows: Lib/   (capital L, no version suffix, at root)
    """
    if platform.system() == "Windows":
        return python_dir / "Lib"
    return python_dir / "lib" / "python3.13"


def trim_stdlib(python_dir: Path):
    print("==> Trimming stdlib...")
    pylib = _pylib_dir(python_dir)
    for item in STDLIB_TRIM:
        target = pylib / item
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

    if platform.system() != "Windows":
        subprocess.run(
            ["find", str(python_dir), "-name", "__pycache__", "-type", "d",
             "-exec", "rm", "-rf", "{}", "+"],
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


# ── Step 6: Generate app_paths.py ─────────────────────────────────────────────

def generate_app_paths(python_dir: Path):
    identifier = os.environ.get("APP_IDENTIFIER", "io.exegia.Corpora")
    if not identifier:
        print("    Skipping app_paths.py — APP_IDENTIFIER not set.")
        return

    channel = os.environ.get("APP_CHANNEL", "stable")
    site_packages = _pylib_dir(python_dir) / "site-packages"
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


# ── Step 7a: macOS signing ────────────────────────────────────────────────────

def _import_macos_cert(tmpdir: Path):
    """Decode APPLE_CERTIFICATE and import it into a temporary keychain."""
    cert_b64 = os.environ.get("APPLE_CERTIFICATE", "")
    cert_pwd = os.environ.get("APPLE_CERTIFICATE_PASSWORD", "")
    if not cert_b64:
        raise SystemExit("APPLE_CERTIFICATE is required for macOS signing.")

    cert_file = tmpdir / "cert.p12"
    cert_file.write_bytes(base64.b64decode(cert_b64))

    keychain = str(tmpdir / "build.keychain")
    kc_pwd = "ci-build-keychain"

    run(["security", "create-keychain", "-p", kc_pwd, keychain])
    run(["security", "default-keychain", "-s", keychain])
    run(["security", "unlock-keychain", "-p", kc_pwd, keychain])
    run([
        "security", "import", str(cert_file),
        "-k", keychain,
        "-P", cert_pwd,
        "-T", "/usr/bin/codesign",
        "-T", "/usr/bin/security",
    ])
    run([
        "security", "set-key-partition-list",
        "-S", "apple-tool:,apple:",
        "-s", "-k", kc_pwd,
        keychain,
    ])


def _write_entitlements(tmpdir: Path) -> Path:
    """Write a hardened-runtime entitlements plist for Python bundles.

    com.apple.security.cs.disable-library-validation is required because
    Python loads third-party .so files that are not signed by the same identity.
    com.apple.security.cs.allow-unsigned-executable-memory is needed by some
    JIT-capable extension modules (e.g. certain cryptography backends).
    """
    plist = tmpdir / "entitlements.plist"
    plist.write_text(
        """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    return plist


def _find_macho_files(python_dir: Path) -> list[Path]:
    """Return all non-symlink Mach-O files under python_dir."""
    result = subprocess.run(
        ["find", str(python_dir), "-type", "f"],
        capture_output=True, text=True, check=True,
    )
    macho = []
    for path_str in result.stdout.splitlines():
        f = Path(path_str)
        if f.is_symlink():
            continue
        probe = subprocess.run(
            ["file", str(f)], capture_output=True, text=True
        )
        if "Mach-O" in probe.stdout:
            macho.append(f)
    return macho


def sign_macos(python_dir: Path, out_dir: Path, platform_key: str, tmpdir: Path) -> Path:
    """Sign all Mach-O binaries individually, create a ditto zip, then notarize."""
    identity = os.environ.get("APPLE_SIGNING_IDENTITY", "")
    if not identity:
        raise SystemExit("APPLE_SIGNING_IDENTITY is required for macOS signing.")

    _import_macos_cert(tmpdir)
    entitlements = _write_entitlements(tmpdir)

    macho_files = _find_macho_files(python_dir)
    print(f"==> Signing {len(macho_files)} Mach-O files...")

    base_args = [
        "codesign",
        "--force",
        "--timestamp",
        "--options", "runtime",
        "--sign", identity,
        "--entitlements", str(entitlements),
    ]
    # Sign deepest paths first so that outer bundles don't invalidate inner sigs.
    for f in sorted(macho_files, key=lambda p: len(p.parts), reverse=True):
        run(base_args + [str(f)])

    # Use ditto (not zip) to preserve symlinks that python-build-standalone creates
    # (e.g. python3 → python3.13). Plain zip silently mangles them.
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"corpora-py-{platform_key}.zip"
    print(f"==> Creating archive: {archive.name}")
    run(["ditto", "-c", "-k", "--keepParent", str(python_dir), str(archive)])

    # Notarize — validates that signing passes Apple's checks.
    # Note: xcrun stapler staple cannot be applied to a plain .zip; stapling
    # applies to .app/.dmg/.pkg only. The Tauri client app that embeds this
    # resource bundle is the artifact to staple after app notarization.
    apple_id = os.environ.get("APPLE_ID", "")
    apple_password = os.environ.get("APPLE_PASSWORD", "")
    team_id = os.environ.get("APPLE_TEAM_ID", "")

    if apple_id and apple_password and team_id:
        print("==> Notarizing archive (this takes a few minutes)...")
        run([
            "xcrun", "notarytool", "submit", str(archive),
            "--apple-id", apple_id,
            "--password", apple_password,
            "--team-id", team_id,
            "--wait",
        ])
    else:
        print(
            "    Warning: APPLE_ID / APPLE_PASSWORD / APPLE_TEAM_ID not set — "
            "skipping notarization."
        )

    return archive


# ── Step 7b: Windows signing ──────────────────────────────────────────────────

def sign_windows(python_dir: Path, out_dir: Path, platform_key: str) -> Path:
    """Sign .exe/.dll/.pyd files with signtool, then zip."""
    thumbprint = os.environ.get("WINDOWS_CERTIFICATE_THUMBPRINT", "")
    if not thumbprint:
        raise SystemExit("WINDOWS_CERTIFICATE_THUMBPRINT is required for Windows signing.")

    custom_cmd = os.environ.get("WINDOWS_SIGN_COMMAND", "")

    binaries = [
        f for pattern in ("**/*.exe", "**/*.dll", "**/*.pyd")
        for f in python_dir.rglob(pattern)
        if f.is_file() and not f.is_symlink()
    ]
    print(f"==> Signing {len(binaries)} Windows binaries...")

    for f in binaries:
        if custom_cmd:
            run(custom_cmd.replace("{path}", str(f)).split())
        else:
            run([
                "signtool", "sign",
                "/tr", "http://timestamp.digicert.com",
                "/td", "sha256",
                "/fd", "sha256",
                "/sha1", thumbprint,
                str(f),
            ])

    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"corpora-py-{platform_key}.zip"
    print(f"==> Creating archive: {archive.name}")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in python_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(python_dir.parent))

    return archive


# ── Step 7c: Unsigned archive ─────────────────────────────────────────────────

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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    platform_key = args.platform or detect_platform()
    if platform_key not in PLATFORM_MAP:
        raise SystemExit(f"Unknown platform: {platform_key}")

    out_dir = Path(args.out_dir)
    dest_dir = Path(args.dest_dir)
    cache_dir = Path(args.cache_dir)

    print(f"==> Platform: {platform_key}")
    print(f"==> Python:   {PYTHON_VERSION}  (standalone {STANDALONE_VERSION})")

    # 1. Build (or locate) the wheel
    if args.skip_build:
        wheel = _find_wheel(out_dir)
        print(f"==> Using existing wheel: {wheel.name}")
    else:
        wheel = build_wheel(out_dir)
        print(f"    Wheel: {wheel.name}")

    # 2. Download standalone Python
    tarball = download_standalone_python(platform_key, cache_dir)

    # 3. Extract
    extract_python(tarball, dest_dir)

    # 4. Install wheel + deps into standalone Python
    install_wheel(wheel, dest_dir)

    # 5. Trim stdlib
    trim_stdlib(dest_dir)

    # 6. Generate app_paths.py
    generate_app_paths(dest_dir)

    # 7. Sign and archive
    if args.skip_sign:
        archive = create_unsigned_archive(dest_dir, out_dir, platform_key)
    else:
        with tempfile.TemporaryDirectory() as _tmpdir:
            tmpdir = Path(_tmpdir)
            if platform_key.startswith("macos"):
                archive = sign_macos(dest_dir, out_dir, platform_key, tmpdir)
            elif platform_key == "windows-x64":
                archive = sign_windows(dest_dir, out_dir, platform_key)
            else:
                raise SystemExit(f"Signing not implemented for: {platform_key}")

    # Report
    size_mb = archive.stat().st_size / (1024 * 1024)
    triple = PLATFORM_MAP[platform_key]["tauri_triple"]
    print()
    print(f"==> Done.")
    print(f"    Archive:       {archive}")
    print(f"    Size:          {size_mb:.1f} MB")
    print(f"    Tauri triple:  {triple}")
    print()
    print(
        "    To use as a Tauri sidecar resource, add to tauri.conf.json:\n"
        f'      "bundle": {{ "resources": {{ "{archive.name}": "resources/" }} }}'
    )


if __name__ == "__main__":
    main()
