"""Combined FastAPI application: MCP server + admin conversion API.

This is the natural place for this app to live: `corpora_py` (the umbrella
package) already depends on both `corpora-mcp` and `corpora-admin`, whereas
those two packages have no dependency on each other. Building the combined
app inside `admin` or `mcp` instead would force one to depend on the other
and collapse the slim-client/heavy-admin split described in the root
`CLAUDE.md`.

Layout:
    /mcp/*      -- the FastMCP server (`corpora_mcp.mcp`), mounted as an ASGI
                   sub-app. This is what AI clients (Claude, etc.) talk to
                   over streamable HTTP.
    /convert/*  -- the admin conversion API (`admin.services.api` +
                   `admin.services.websocket`): upload a document, poll or
                   watch a WebSocket for status, download the `.corpus`
                   result. See `admin/services/api.py` for why conversion is
                   job-based rather than synchronous.
    /health     -- liveness check for the combined app.

Mounting a FastMCP ASGI app requires forwarding its lifespan into the parent
FastAPI app, or its session manager never starts and every request to /mcp
fails at runtime despite importing fine -- see
https://gofastmcp.com/integrations/fastapi (Lifespan Management). This is
the one part of wiring this up that fails silently at import time and only
breaks when a request actually comes in, so it's covered by
`tests/test_app.py` (spins up the app with a real ASGI transport and hits
both surfaces) rather than left to be caught by hand.
"""

from __future__ import annotations

from fastapi import FastAPI

from admin.services.api import router as conversion_router
from admin.services.websocket import router as conversion_ws_router
from corpora_mcp import mcp

# `path="/"` because we mount the whole sub-app under `/mcp` below; giving
# http_app() its own `/mcp` prefix too would double it up (`/mcp/mcp`).
_mcp_app = mcp.http_app(path="/")

app = FastAPI(
    title="Corpora API",
    description="Context-Fabric MCP server + document conversion API",
    version="0.1.1",
    # Required so the mounted MCP sub-app's session manager starts/stops
    # with the parent app instead of never initializing.
    lifespan=_mcp_app.lifespan,
)

app.mount("/mcp", _mcp_app)
app.include_router(conversion_router)
app.include_router(conversion_ws_router)


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["Health"], include_in_schema=False)
async def root() -> dict[str, str]:
    return {"message": "Corpora API — see /docs, MCP at /mcp, conversions at /convert"}


def main() -> None:
    """Entry point for the `corpora-api` console script."""
    import uvicorn

    uvicorn.run("corpora_py.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
