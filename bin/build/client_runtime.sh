#!/usr/bin/env bash
#
# client_runtime.sh
# Shell equivalent of scripts/bin/client_runtime.py
#
# Builds the FULL runtime (with [full] extra + clean) for client opt-in.
#
# Usage:
#   ./scripts/bin/client_runtime.sh [--platform P]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOD'
Build the FULL Python runtime bundle for the consumer/client app opt-in.

This always runs with --full --clean.

See also:
  ./scripts/bin/embedded.sh --help
EOD
  exit 0
fi

log "Building FULL client Python runtime bundle (with text-fabric etc.)..."

PLATFORM_ARG=()
if [[ "${1:-}" == "--platform" ]]; then
  PLATFORM_ARG=(--platform "$2")
fi

# Force full + clean for client runtime
"$SCRIPT_DIR/embedded.sh" --full --clean "${PLATFORM_ARG[@]}"

echo
echo "Client full runtime bundle ready."
echo "Host the python-runtime-*.tar.gz for client opt-in downloads."
