#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSION="3.13.14"
STANDALONE_VERSION="20260623"
DEST_DIR="resources/python"

WHEEL_PATH=""
PLATFORM=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) PLATFORM="$2"; shift 2 ;;
        *) WHEEL_PATH="$1"; shift ;;
    esac
done

if [[ -z "$WHEEL_PATH" ]]; then
    echo "Usage: $0 <path-to-wheel.whl> [--platform macos-arm64|macos-x64|linux-x64|windows-x64]"
    exit 1
fi

if [[ ! -f "$WHEEL_PATH" ]]; then
    echo "Error: Wheel file not found: $WHEEL_PATH"
    exit 1
fi

if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# --- Auto-detect platform ---
if [[ -z "$PLATFORM" ]]; then
    OS="$(uname -s)"
    ARCH="$(uname -m)"
    case "$OS-$ARCH" in
        Darwin-arm64)  PLATFORM="macos-arm64" ;;
        Darwin-x86_64) PLATFORM="macos-x64" ;;
        Linux-x86_64)  PLATFORM="linux-x64" ;;
        *)
            echo "Error: Cannot auto-detect platform for $OS-$ARCH. Use --platform."
            exit 1
            ;;
    esac
fi

# --- Map platform (no associative arrays — works on bash 3.2) ---
case "$PLATFORM" in
    macos-arm64)
        STANDALONE_PLATFORM="aarch64-apple-darwin"
        PYTHON_LIB_NAME="libpython3.13.dylib"
        ;;
    macos-x64)
        STANDALONE_PLATFORM="x86_64-apple-darwin"
        PYTHON_LIB_NAME="libpython3.13.dylib"
        ;;
    linux-x64)
        STANDALONE_PLATFORM="x86_64-unknown-linux-gnu"
        PYTHON_LIB_NAME="libpython3.13.so"
        ;;
    windows-x64)
        STANDALONE_PLATFORM="x86_64-pc-windows-msvc-shared"
        PYTHON_LIB_NAME="python313.dll"
        ;;
    *)
        echo "Error: Unknown platform: $PLATFORM"
        exit 1
        ;;
esac

TARBALL_NAME="cpython-${PYTHON_VERSION}+${STANDALONE_VERSION}-${STANDALONE_PLATFORM}-install_only.tar.gz"
DOWNLOAD_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${STANDALONE_VERSION}/${TARBALL_NAME}"


echo "==> Platform: $PLATFORM"
echo "==> Python: $PYTHON_VERSION"
echo "==> Wheel: $WHEEL_PATH"

# --- Download standalone Python ---
CACHE_DIR=".cache/python-standalone"
mkdir -p "$CACHE_DIR"

if [[ ! -f "$CACHE_DIR/$TARBALL_NAME" ]]; then
    echo "==> Downloading standalone Python..."
    curl -L --progress-bar -o "$CACHE_DIR/$TARBALL_NAME" "$DOWNLOAD_URL"
else
    echo "==> Using cached download: $CACHE_DIR/$TARBALL_NAME"
fi

# --- Extract ---
echo "==> Extracting..."
rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR"
tar -xzf "$CACHE_DIR/$TARBALL_NAME" -C "$DEST_DIR" --strip-components=1

# --- Install the wheel using uv ---
echo "==> Installing wheel with uv..."
uv pip install --python "$DEST_DIR/bin/python3" --no-cache "$WHEEL_PATH"

# --- Trim the stdlib ---
echo "==> Trimming stdlib..."
PYLIB="$DEST_DIR/lib/python3.13"

for item in test unittest tkinter idlelib turtledemo turtle.py \
    ensurepip lib2to3 pydoc_data doctest.py _pydecimal.py \
    pydoc.py mailbox.py imaplib.py nntplib.py poplib.py \
    smtplib.py ftplib.py xmlrpc curses multiprocessing \
    concurrent asyncio/windows_events.py asyncio/windows_utils.py; do
    if [[ -e "$PYLIB/$item" ]]; then
        rm -rf "$PYLIB/$item"
    fi
done

find "$DEST_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$DEST_DIR" -name "*.pyc" -delete 2>/dev/null || true
rm -rf "$DEST_DIR/share" "$DEST_DIR/man"
rm -rf "$DEST_DIR/lib/pkgconfig" "$DEST_DIR/include"
find "$DEST_DIR/lib" -name "*.a" -delete 2>/dev/null || true

# --- Report sizes ---
echo ""
echo "==> Done! Bundled Python at: $DEST_DIR/"
echo ""
TOTAL_SIZE=$(du -sh "$DEST_DIR" | cut -f1)
LIB_SIZE=$(du -sh "$DEST_DIR/lib/$PYTHON_LIB_NAME" 2>/dev/null | cut -f1 || echo "N/A")
STDLIB_SIZE=$(du -sh "$PYLIB" | cut -f1)
SITEPACKAGES_SIZE=$(du -sh "$PYLIB/site-packages" | cut -f1)
echo "    Total:         $TOTAL_SIZE"
echo "    Shared lib:    $LIB_SIZE ($PYTHON_LIB_NAME)"
echo "    Stdlib:        $STDLIB_SIZE"
echo "    Site-packages: $SITEPACKAGES_SIZE"
