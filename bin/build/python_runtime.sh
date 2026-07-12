#!/usr/bin/env bash
#
# python_runtime.sh
#
# For use by the consumer/client application code (or in CI).
#
# Logic (same as Python version):
#   - If the python runtime already exists at <target>/python/bin/python3 (or .exe), use it.
#   - Otherwise download the pre-built python-runtime-<plat>.tar.gz and extract.
#
# You must host the tarballs (produced by client_runtime / embedded --full)
# and set DOWNLOAD_BASE_URL appropriately.
#
# Usage:
#   source scripts/bin/common.sh
#   ensure_python_runtime [target_dir] [force]
#
# Or directly:
#   ./bim/build/python_runtime.sh [target_dir]
#
# It will print the path to the python binary on success.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

target="${1:-example/build/lib}"
force="${2:-false}"

bin_path="$(ensure_python_runtime "$target" "$force")"
echo "$bin_path"
