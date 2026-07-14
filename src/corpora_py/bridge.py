"""Demo bridge helpers for the ElectroBun websocket RPC layer.

These helpers are available to Python functions called through the example app's
``PythonBridge`` subprocess. They delegate to the in-memory ``demo_bridge``
module injected by ``example/src/bun/python-bridge.ts`` at runtime.
"""

from __future__ import annotations

from typing import Any


def ping(message: str = "pong") -> dict[str, Any]:
    """Return a simple JSON-safe payload for smoke testing app → Python calls."""
    return {"ok": True, "message": message}


def emit(event: str = "corpora.example", payload: Any = None) -> dict[str, Any]:
    """Emit a Python-originated event to connected example app websocket clients."""
    from demo_bridge import emit as bridge_emit

    bridge_emit(event, payload)
    return {"ok": True, "event": event}


def call_client(
    method: str = "example.echo",
    params: Any = None,
    timeout: float = 30.0,
) -> Any:
    """Call a frontend handler registered by the example app.

    The browser side registers handlers with ``socketBridge.register(...)``.
    This function lets Python methods call back into the app and receive the
    handler's result.
    """
    from demo_bridge import call_client as bridge_call_client

    return bridge_call_client(method, {} if params is None else params, timeout)
