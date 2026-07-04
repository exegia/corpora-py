import base64
import os
import subprocess
import zipfile
from pathlib import Path

from .helpers import run


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
    run(
        [
            "security",
            "import",
            str(cert_file),
            "-k",
            keychain,
            "-P",
            cert_pwd,
            "-T",
            "/usr/bin/codesign",
            "-T",
            "/usr/bin/security",
        ]
    )
    run(
        [
            "security",
            "set-key-partition-list",
            "-S",
            "apple-tool:,apple:",
            "-s",
            "-k",
            kc_pwd,
            keychain,
        ]
    )


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
        capture_output=True,
        text=True,
        check=True,
    )
    macho = []
    for path_str in result.stdout.splitlines():
        f = Path(path_str)
        if f.is_symlink():
            continue
        probe = subprocess.run(["file", str(f)], capture_output=True, text=True)
        if "Mach-O" in probe.stdout:
            macho.append(f)
    return macho

def sign_windows(python_dir: Path, out_dir: Path, platform_key: str) -> Path:
    """Sign .exe/.dll/.pyd files with signtool, then zip."""
    thumbprint = os.environ.get("WINDOWS_CERTIFICATE_THUMBPRINT", "")
    if not thumbprint:
        raise SystemExit(
            "WINDOWS_CERTIFICATE_THUMBPRINT is required for Windows signing."
        )

    custom_cmd = os.environ.get("WINDOWS_SIGN_COMMAND", "")

    binaries = [
        f
        for pattern in ("**/*.exe", "**/*.dll", "**/*.pyd")
        for f in python_dir.rglob(pattern)
        if f.is_file() and not f.is_symlink()
    ]
    print(f"==> Signing {len(binaries)} Windows binaries...")

    for f in binaries:
        if custom_cmd:
            run(custom_cmd.replace("{path}", str(f)).split())
        else:
            run(
                [
                    "signtool",
                    "sign",
                    "/tr",
                    "http://timestamp.digicert.com",
                    "/td",
                    "sha256",
                    "/fd",
                    "sha256",
                    "/sha1",
                    thumbprint,
                    str(f),
                ]
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"corpora-py-{platform_key}.zip"
    print(f"==> Creating archive: {archive.name}")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in python_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(python_dir.parent))

    return archive



def sign_macos(
    python_dir: Path, out_dir: Path, platform_key: str, tmpdir: Path
) -> Path:
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
        "--options",
        "runtime",
        "--sign",
        identity,
        "--entitlements",
        str(entitlements),
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
        run(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(archive),
                "--apple-id",
                apple_id,
                "--password",
                apple_password,
                "--team-id",
                team_id,
                "--wait",
            ]
        )
    else:
        print(
            "    Warning: APPLE_ID / APPLE_PASSWORD / APPLE_TEAM_ID not set — "
            "skipping notarization."
        )

    return archive
