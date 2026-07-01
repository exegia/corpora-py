#!/usr/bin/env bash
#
# sign.sh
# Shell equivalent of scripts/build/sign.py
#
# macOS:
#   - Imports a base64 p12 into a temp keychain
#   - Writes entitlements
#   - codesign all Mach-O files (deepest first)
#   - ditto zip
#   - (optional) notarize with notarytool
#
# Windows:
#   - signtool on .exe/.dll/.pyd
#   - zip
#
# Usage (internal helpers mostly called by higher level build scripts):
#   ./scripts/build/sign.sh macos <python_dir> <out_dir> <platform_key> <tmpdir>
#   ./scripts/build/sign.sh windows <python_dir> <out_dir> <platform_key>
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# --- macOS helpers ---

import_macos_cert() {
  local tmpdir="$1"
  local cert_b64="${APPLE_CERTIFICATE:-}"
  local cert_pwd="${APPLE_CERTIFICATE_PASSWORD:-}"

  if [[ -z "$cert_b64" ]]; then
    echo "APPLE_CERTIFICATE is required for macOS signing." >&2
    exit 1
  fi

  local cert_file="$tmpdir/cert.p12"
  echo "$cert_b64" | base64 -d > "$cert_file"

  local keychain="$tmpdir/build.keychain"
  local kc_pwd="ci-build-keychain"

  run_cmd security create-keychain -p "$kc_pwd" "$keychain"
  run_cmd security default-keychain -s "$keychain"
  run_cmd security unlock-keychain -p "$kc_pwd" "$keychain"
  run_cmd security import "$cert_file" -k "$keychain" -P "$cert_pwd" \
    -T /usr/bin/codesign -T /usr/bin/security

  run_cmd security set-key-partition-list -S "apple-tool:,apple:" -s -k "$kc_pwd" "$keychain"
}

write_entitlements() {
  local tmpdir="$1"
  local plist="$tmpdir/entitlements.plist"
  cat > "$plist" <<'PLIST'
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
PLIST
  echo "$plist"
}

find_macho_files() {
  local python_dir="$1"
  # Find files, skip symlinks, check for "Mach-O" via `file`
  while IFS= read -r -d '' f; do
    if [[ -L "$f" ]]; then continue; fi
    if file "$f" | grep -q "Mach-O"; then
      echo "$f"
    fi
  done < <(find "$python_dir" -type f -print0)
}

sign_macos() {
  local python_dir="$1"
  local out_dir="$2"
  local platform_key="$3"
  local tmpdir="$4"

  local identity="${APPLE_SIGNING_IDENTITY:-}"
  if [[ -z "$identity" ]]; then
    echo "APPLE_SIGNING_IDENTITY is required for macOS signing." >&2
    exit 1
  fi

  import_macos_cert "$tmpdir"
  local entitlements
  entitlements="$(write_entitlements "$tmpdir")"

  log "Signing Mach-O files..."
  local -a machos
  mapfile -t machos < <(find_macho_files "$python_dir" | sort -r)  # deepest first by sorting paths longer first? simple reverse lexical approx

  # Better: sort by depth (number of path components) descending
  machos=()
  while IFS= read -r f; do machos+=("$f"); done < <(find_macho_files "$python_dir")
  # sort by depth desc
  IFS=$'\n' machos=($(printf "%s\n" "${machos[@]}" | awk '{ print length($0) " " $0 }' | sort -rn | cut -d' ' -f2- ))

  local base_args=(codesign --force --timestamp --options runtime --sign "$identity" --entitlements "$entitlements")

  for f in "${machos[@]}"; do
    run_cmd "${base_args[@]}" "$f"
  done

  mkdir -p "$out_dir"
  local archive="$out_dir/corpora-py-${platform_key}.zip"
  log "Creating archive: $(basename "$archive")"
  run_cmd ditto -c -k --keepParent "$python_dir" "$archive"

  # Notarization (optional)
  local apple_id="${APPLE_ID:-}"
  local apple_password="${APPLE_PASSWORD:-}"
  local team_id="${APPLE_TEAM_ID:-}"

  if [[ -n "$apple_id" && -n "$apple_password" && -n "$team_id" ]]; then
    log "Notarizing archive (this takes a few minutes)..."
    run_cmd xcrun notarytool submit "$archive" \
      --apple-id "$apple_id" \
      --password "$apple_password" \
      --team-id "$team_id" \
      --wait
  else
    echo "    Warning: APPLE_ID / APPLE_PASSWORD / APPLE_TEAM_ID not set — skipping notarization."
  fi

  echo "$archive"
}

# --- Windows signing ---

sign_windows() {
  local python_dir="$1"
  local out_dir="$2"
  local platform_key="$3"

  local thumbprint="${WINDOWS_CERTIFICATE_THUMBPRINT:-}"
  if [[ -z "$thumbprint" ]]; then
    echo "WINDOWS_CERTIFICATE_THUMBPRINT is required for Windows signing." >&2
    exit 1
  fi

  local custom_cmd="${WINDOWS_SIGN_COMMAND:-}"

  log "Signing Windows binaries..."

  # Collect binaries
  local -a binaries
  while IFS= read -r -d '' f; do
    binaries+=("$f")
  done < <(find "$python_dir" \( -name "*.exe" -o -name "*.dll" -o -name "*.pyd" \) -type f ! -type l -print0)

  echo "==> Signing ${#binaries[@]} Windows binaries..."

  for f in "${binaries[@]}"; do
    if [[ -n "$custom_cmd" ]]; then
      # crude replacement of {path}
      local expanded
      expanded="${custom_cmd//\{path\}/$f}"
      run_cmd $expanded
    else
      run_cmd signtool sign \
        /tr http://timestamp.digicert.com \
        /td sha256 \
        /fd sha256 \
        /sha1 "$thumbprint" \
        "$f"
    fi
  done

  mkdir -p "$out_dir"
  local archive="$out_dir/corpora-py-${platform_key}.zip"
  log "Creating archive: $(basename "$archive")"

  # Recreate the zip logic from sign.py / archive
  (
    cd "$(dirname "$python_dir")"
    zip -9 -r -y "$archive" "$(basename "$python_dir")"
  )

  echo "$archive"
}

# --- dispatch ---

if [[ $# -lt 1 ]]; then
  echo "Usage:"
  echo "  sign.sh macos   <python_dir> <out_dir> <platform_key> <tmpdir>"
  echo "  sign.sh windows <python_dir> <out_dir> <platform_key>"
  exit 1
fi

mode="$1"; shift

case "$mode" in
  macos)
    sign_macos "$@"
    ;;
  windows)
    sign_windows "$@"
    ;;
  *)
    echo "Unknown mode: $mode" >&2
    exit 1
    ;;
esac
