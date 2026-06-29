import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
ENV_FILE = str(ROOT / ".env.development")  # absolute so dotenvx works from any cwd
DEMO_APP_DIR = str(ROOT / "demo")
VITE_URL = "http://localhost:5173"

# Match any running Supabase Studio container regardless of project name.
# If one is up, we reuse it rather than starting a second instance.
SUPABASE_STUDIO_FILTER = "supabase_studio"
SUPABASE_PROJECT_DIR = str(ROOT.parent / "corpora-supabase")


def ensure_tool(name: str, hint: str, install: list[str] = []) -> None:
    if shutil.which(name) is None:
        if len(install) == 0:
            print(f"${name} is not on user PATH. Installing using command...")
            result = subprocess.run(install, text=True)
            if result.returncode != 0:
                sys.exit(result.returncode)
        sys.exit(f"error: `{name}` is required on PATH. {hint}")


def is_supabase_running() -> bool:
    """Check if the Supabase Studio Docker container is already running.

    Uses `docker ps --filter name=supabase_studio` so we don't rely on the
    `supabase` CLI — Docker is the ground truth for whether the stack is live.
    """
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"name={SUPABASE_STUDIO_FILTER}",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def dotenvx_wrap(cmd: list[str]) -> list[str]:
    """Prepend `dotenvx run` so .env.development values are loaded into the command's env.

    `.env.keys` is auto-discovered next to the env file for encrypted values.
    """
    return ["dotenvx", "run", "-f", ENV_FILE, "--", *cmd]


def run(
    cmd: list[str],
    check: bool = True,
    dotenvx: bool = True,
    dir: Path = ROOT,
    *,
    # For long-running dev servers, detach stdin so Bun/Node readline interfaces
    # don't get EIO when the launcher TTY state changes or the parent exits.
    stdin=None,
    dev_server: bool = False,
) -> subprocess.CompletedProcess[str]:
    _cmd: list[str] = cmd
    print(f"$ {' '.join(cmd)}")
    if dotenvx:
        print("🔒 Starting command with dotenvx...")
        _cmd = dotenvx_wrap(cmd=cmd)

    effective_stdin = stdin
    if effective_stdin is None and dev_server:
        effective_stdin = subprocess.DEVNULL

    result = subprocess.run(_cmd, cwd=dir, text=True, stdin=effective_stdin)
    if check and result.returncode != 0:
        if dev_server:
            # Don't kill the whole launcher just because one dev server exited.
            # The main thread blocker will keep running.
            print(f"[dev server] {' '.join(cmd)} exited with code {result.returncode}")
            return result
        sys.exit(result.returncode)
    return result


def open_browser(url: str = VITE_URL):
    print(f"🌐 Opening browser at {url} …")
    webbrowser.open(url)


__all__ = [
    "is_supabase_running",
    "ensure_tool",
    "dotenvx_wrap",
    "run",
    "ROOT",
    "VITE_URL",
    "ENV_FILE",
    "DEMO_APP_DIR",
]
