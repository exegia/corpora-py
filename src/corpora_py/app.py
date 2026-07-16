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
    /validate   -- corpus validation (`admin.services.validation_api`): confirm a
                   dataset round-trips the `.tf -> .cfm -> mmap` cycle. Shares
                   the validation logic with the `validate_corpus` MCP tool.
    /storage/*  -- Hugging Face Hub storage of finished `.corpus` archives
                   (`admin.services.storage_api`): list/inspect/upload/download/
                   delete, backed by `HF_STORAGE_REPO`. Shares its implementation
                   with the `storage_*` MCP tools (`admin.services.storage_mcp`),
                   registered onto the MCP server below.
    /health     -- liveness check for the combined app.

This ships as a sidecar spawned by a Tauri+Supabase desktop app, not a public
multi-tenant service -- but it's still a locally reachable port, so every
path except health/docs is gated behind a Supabase JWT by default (see
`corpora_py.auth.AuthMiddleware`; opt out for local dev with
`AUTH_REQUIRED=false`).

CORS is widely open (`allow_origins=["*"]`) rather than restricted to a known
dev-server origin. The actual access-control boundary here is the
JWT (`AuthMiddleware`), not the browser's origin check -- auth uses a Bearer
header, not cookies, so CORS's usual credential-leak concern doesn't apply.
This also sidesteps having to guess what `Origin` a packaged ElectroBun
webview reports for its `views://` custom scheme (untested, varies by
platform webview) versus the Vite dev server's `http://localhost:5173`.
`CORSMiddleware` only intercepts `http` scope (browsers don't run CORS
preflight against `WebSocket`), so it doesn't need to know about `/convert/{id}/ws`.

Mounting a FastMCP ASGI app requires forwarding its lifespan into the parent
FastAPI app, or its session manager never starts and every request to /mcp
FastAPI app, or its session manager never starts, and every request to /mcp
fails at runtime despite importing fine -- see
https://gofastmcp.com/integrations/fastapi (Lifespan Management). This is
the one part of wiring this up that fails silently at import time and only
breaks when a request actually comes in, so it's covered by
`tests/test_app.py` (spins up the app with a real ASGI transport and hits
both surfaces) rather than left to be caught by hand.
breaks when a request actually comes in -- verify it by actually sending a
request through (e.g., a `TestClient`/ASGI-transport `initialize` call to
`/mcp`), not just by importing this module. There is no automated test
covering this yet (see the root CLAUDE.md's CI/CD notes).

The admin conversion service's `JobManager` (`admin.services.jobs`) also
needs its `ThreadPoolExecutor` shut down on app exit, so its lifespan is
combined with the MCP app's via `combine_lifespans` below -- see
`JobManager.shutdown()`'s docstring for why that shutdown is best-effort
(`wait=False`), not a guarantee every worker thread has exited.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp.utilities.lifespan import combine_lifespans

from admin.services.api import router as conversion_router
from admin.services.corpus_detail_api import router as corpus_detail_router
from admin.services.corpus_detail_mcp import register_corpus_detail_tools
from admin.services.jobs import job_manager
from admin.services.storage_api import router as storage_router
from admin.services.storage_mcp import register_storage_tools
from admin.services.validation_api import router as validation_router
from admin.services.websocket import router as conversion_ws_router
from corpora_mcp import mcp
from .auth import AuthMiddleware

# The `storage_*` MCP tools live in `admin.services.storage_mcp` (admin owns
# its API surfaces; see packages/admin/CLAUDE.md) and are registered onto the
# shared server here, before the ASGI app is built -- a standalone `cf-mcp`
# process never registers them, keeping the slim MCP package admin-free.
register_storage_tools(mcp)
# The `corpus_*` detail tools (`admin.services.corpus_detail_mcp`) are the MCP
# counterpart of the `/storage/{filename}/...` detail router, registered here
# for the same reason as the storage tools -- to keep the slim MCP package free
# of the admin/text-fabric dependency.
register_corpus_detail_tools(mcp)

# `path="/"` because we mount the whole sub-app under `/mcp` below; giving
# http_app() its own `/mcp` prefix too would double it up (`/mcp/mcp`).
_mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def _job_manager_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    job_manager.shutdown(wait=False)


app = FastAPI(
    title="Corpora API",
    description="Context-Fabric MCP server + document conversion API",
    version="0.1.1",
    # Required so the mounted MCP sub-app's session manager starts/stops
    # with the parent app instead of never initializing, and so
    # `job_manager`'s executor shuts down on exit too.
    lifespan=combine_lifespans(_mcp_app.lifespan, _job_manager_lifespan),
)

app.add_middleware(AuthMiddleware)
# Added after AuthMiddleware so it ends up OUTERMOST in the stack (Starlette
# wraps in reverse registration order) -- it needs to see and answer CORS
# preflight (OPTIONS) requests before AuthMiddleware would otherwise 401 them
# for lacking a bearer token.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/mcp", _mcp_app)
app.include_router(conversion_router)
app.include_router(conversion_ws_router)
app.include_router(validation_router)
app.include_router(storage_router)
app.include_router(corpus_detail_router)


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["Health"], include_in_schema=False)
async def root() -> dict[str, str]:
    return {"message": "Corpora API — see /docs, MCP at /mcp, conversions at /convert"}


def main() -> None:
    """Entry point for the `corpora-api` console script.

    `dockerfiles/Dockerfile` invokes this (not a raw `uvicorn corpora_py.app:app`
    command) specifically, so the `workers=1` guard below is a single source
    of truth -- a container CMD that called uvicorn directly could add
    `--workers N` without ever seeing this comment.
    """
    import os

    """Entry point for the `corpora-api` console script."""
    import uvicorn

    # 127.0.0.1 is correct for local (`uv run corpora-api`) use; the
    # container needs 0.0.0.0 to be reachable from outside it. `UVICORN_HOST`
    # is set in the image's `ENV` rather than hardcoded here so this
    # entrypoint is identical for both.
    host = os.getenv("UVICORN_HOST", "127.0.0.1")

    # workers MUST stay 1: JobManager (admin.services.jobs) is an in-memory,
    # per-process singleton. Running with workers>1 silently splits job
    # state across processes -- a client's poll/WS request may land on a
    # different worker than the one that started their job and see a 404 or
    # stale state. There is no cross-process job registry (Redis, etc.)
    # backing this yet; see JobManager's docstring. Don't add a `workers=`
    # kwarg here without addressing that first.
    uvicorn.run("corpora_py.app:app", host=host, port=8000, reload=False, workers=1)


if __name__ == "__main__":
    main()
