#!/usr/bin/env python3
"""
Build, bundle, sign, and archive corpora-py for use as a Tauri sidecar resource.

Runs once per platform on a matching OS runner. Designed for GitHub Actions
matrix jobs — one runner per target OS (macOS-arm64, macOS-x64, Windows-x64).

Usage:
    uv run python -m scripts.build [--platform <platform>] [--skip-sign] [--skip-build]

Other entry points (all under the same package):
    python -m scripts.build bundle <wheel.whl>...
    python -m scripts.build embedded [--full] [--clean]
    python -m scripts.build client_runtime

Signing is performed by default. Pass --skip-sign to produce an unsigned archive (for local dev).

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

import tempfile
from pathlib import Path

from .archive import create_unsigned_archive, extract_python
from .download import download_standalone_python
from .env_vars import PLATFORM_MAP, PYTHON_VERSION, STANDALONE_VERSION
from .helpers import detect_platform, generate_app_paths, parse_args
from .sign import sign_macos, sign_windows
from .trim import trim_stdlib
from .wheel import build_wheel, find_wheel, install_wheel


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
        wheel = find_wheel(out_dir)
        print(f"==> Using existing wheel: {wheel.name}")
    else:
        wheel = build_wheel(out_dir)
        print(f"    Wheel: {wheel.name}")

    # 2. Download standalone Python
    tarball = download_standalone_python(platform_key, cache_dir)

    # 3. Extract
    extract_python(tarball, dest_dir)

    # 4. Install wheel + deps into standalone Python
    # Pass --find-links so workspace sub-packages are resolved locally, not from PyPI
    install_wheel(wheel, dest_dir, find_links=out_dir)

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
    print("==> Done.")
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
