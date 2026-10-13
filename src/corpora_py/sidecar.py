"""Desktop-owned launcher: ``python -u -m corpora_py.sidecar --watch-parent``.

The single stdout discovery record announces a bound address, NOT readiness;
the parent must poll ``/health``. The socket stays open through Uvicorn startup,
so another process cannot claim the port. The combined app and its auth policy
are unchanged; this launcher always binds IPv4 loopback, regardless of env vars.

With ``--watch-parent``, keep the child's stdin pipe open while the desktop is
alive, then close it to request graceful shutdown. Eight seconds after EOF a
daemon watchdog calls ``os._exit(0)`` if Python is still alive. This deliberately
bypasses cleanup as a last resort for stuck startup/shutdown or conversion
executor threads, which can outlive Uvicorn even after its run method returns.
The parent should still force-kill the child if necessary.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from uvicorn import Server

_PARENT_EXIT_TIMEOUT = 8.0


def _watch_parent(server: Server, stdin: TextIO) -> None:
    """Ignore stdin data; EOF (or a closed pipe) ends the parent's lease."""
    try:
        while stdin.read(1):
            pass
    except (OSError, ValueError):
        # A closed/unreadable parent pipe is equivalent to a lost parent.
        pass
    server.should_exit = True
    # Do not cancel this when server.run() returns: non-daemon conversion
    # workers can still prevent interpreter exit at that point.
    time.sleep(_PARENT_EXIT_TIMEOUT)
    os._exit(0)


def run_sidecar(*, watch_parent: bool = False) -> None:
    """Serve the existing app on an OS-selected port, without reload/workers."""
    import uvicorn

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                "corpora_py.app:app",
                host="127.0.0.1",
                port=port,
                workers=1,
                reload=False,
                # Uvicorn's default access logger writes to stdout; reserve
                # that stream for the discovery record instead.
                access_log=False,
            )
        )
        if watch_parent:
            # Construct Server first: its __init__ initializes should_exit.
            # Uvicorn preserves this flag through lifespan startup, including
            # EOF racing with server.run() or arriving during app startup.
            threading.Thread(
                target=_watch_parent,
                args=(server, sys.stdin),
                name="corpora-sidecar-parent",
                daemon=True,
            ).start()
        print(
            "CORPORA_SIDECAR_LISTENING "
            + json.dumps({"url": f"http://127.0.0.1:{port}"}, separators=(",", ":")),
            flush=True,
        )
        if not server.should_exit:
            server.run(sockets=[sock])


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the desktop-owned Corpora backend")
    parser.add_argument(
        "--watch-parent",
        action="store_true",
        help="Exit when stdin closes (graceful shutdown, then force exit after 8 seconds)",
    )
    args = parser.parse_args(argv)
    run_sidecar(watch_parent=args.watch_parent)


if __name__ == "__main__":
    main()
