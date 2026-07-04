from pathlib import Path

# ── Version pins ──────────────────────────────────────────────────────────────
# Version pins shared with the bundler (bundle.py)
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

# === CONFIG - update for your deployment ===
DOWNLOAD_BASE_URL = "https://your-cdn.example.com/corpora-runtimes"
# Example hosted names: python-runtime-macos-arm64.tar.gz , python-runtime-windows-x64.tar.gz , etc.

# STDLIB_TRIM lists stdlib modules that can be safely removed from the
# standalone Python runtime. Only modules provably unused by our stack
# (cfabric, supabase, fastmcp, etc.) are included. Comments explain each group.
STDLIB_TRIM = [
    # GUI / interactive tooling — never needed in a headless MCP server
    "tkinter",
    "idlelib",
    "turtledemo",
    "turtle.py",
    "curses",
    # Test infrastructure
    "test",
    "unittest",
    # Build / packaging helpers not needed at runtime
    "ensurepip",
    "lib2to3",
    # Documentation / REPL helpers
    "pydoc_data",
    "pydoc.py",
    "doctest.py",
    # Rarely-used stdlib modules not pulled in by any dependency in pyproject.toml
    "_pydecimal.py",
    "mailbox.py",
    "imaplib.py",
    "nntplib.py",
    "poplib.py",
    "smtplib.py",
    "ftplib.py",
    "xmlrpc",
    # Windows-only asyncio modules (removed on Unix; harmless no-ops if absent on Windows
    # because they are never imported on non-Windows)
    "asyncio/windows_events.py",
    "asyncio/windows_utils.py",
    # Safe additional trims (tested to not break cfabric, supabase, fastmcp, exegia, asyncio, importlib.metadata)
    "distutils",
    "venv",
    "msilib",
    "winreg",
    "ossaudiodev",
    "spwd",
    "ctypes/test",
    "sqlite3/test",
    "xml/sax/test",
    "email/test",
    "xml",  # lxml is the heavy one used; stdlib xml not required by core
    "sqlite3",
    "dbm",
    "shelve",
    "bdb",
    "cmd",
    "pdb",
    "profile",
    "cProfile",
    "timeit",
    "trace",
    "tracemalloc",
    "faulthandler",
    "symtable",
]

# Demo-only / embedded runtime variables (used by embedded.py and callers).
# __file__ is inside scripts/build/, so we need to go up two levels from the package.
_pkg_dir = Path(__file__).resolve().parent          # .../scripts/build
_scripts_dir = _pkg_dir.parent                      # .../scripts
ROOT = _scripts_dir.parent                          # repo root
DIST_DIR = ROOT / "dist"
DEMO_RESOURCES = ROOT / "demo/public/resources/python"
