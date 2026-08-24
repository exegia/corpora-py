"""Auth gate for the combined app: verifies a Supabase JWT on every request.

This is deliberately a raw ASGI middleware, not a FastAPI `Depends`.
`Depends` only runs for FastAPI path operations -- it does **not** cover
`app.mount("/mcp", _mcp_app)` (a plain ASGI sub-app, invisible to FastAPI's
dependency system) or `/convert/{id}/ws` (a WebSocket route; even
`@app.middleware("http")`/`BaseHTTPMiddleware` only sees `http` scope
requests and passes `websocket` scope straight through). A raw ASGI
middleware sits above Starlette's router entirely and sees every scope type,
so it's the only mechanism that actually covers both surfaces uniformly.

Policy, matching `admin/services/api.py`'s stance that `admin` has no
business owning auth ("that's the combined app's job"): this module is the
combined app's policy layer over `common.utils.jwt_auth`'s framework-agnostic
verification.

Token delivery differs by scope:
- HTTP: standard `Authorization: Bearer <token>` header.
- WebSocket: browsers/webviews' native `WebSocket` API cannot set custom
  headers on the handshake request, so the token is also accepted as a
  `?token=` query parameter for `ws://.../convert/{id}/ws` -- the Tauri
  webview's WebSocket client has the same restriction as a browser's.

`AUTH_REQUIRED` (default true -- see `common.utils.config.Settings`) can be
set to `false` for local dev; when true with no JWKS URL configured,
requests fail closed (401), not open, since silently accepting everything
because of a config gap is the wrong failure mode for something meant to run
on a reachable local port.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from common.utils.config import settings
from common.utils.jwt_auth import AuthError, verify_jwt
from common.utils.request_context import current_owner
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Paths that stay reachable without a token: liveness/info endpoints and the
# generated API docs (schema only, no corpus/job data). `/capabilities` is
# here because a client has to know whether to offer a write action *before*
# it has a token, and its two flags are already inferable from the 401/403 a
# tokenless request gets.
_EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/",
        "/capabilities",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
    }
)

_WS_UNAUTHORIZED_CLOSE_CODE = 4401  # application-defined range (4000-4999)


def _extract_bearer_token(headers: list[tuple[bytes, bytes]]) -> str | None:
    for key, value in headers:
        if key.lower() == b"authorization":
            text = value.decode("latin-1")
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    return None


class AuthMiddleware:
    """Raw ASGI middleware gating `http` and `websocket` scopes alike."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if not settings.auth_required or scope["path"] in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        token = _extract_bearer_token(scope.get("headers", []))
        if token is None and scope["type"] == "websocket":
            query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            token = next(iter(query.get("token", [])), None)

        if token is None:
            await self._reject(scope, send, detail="Missing bearer token")
            return

        try:
            claims = verify_jwt(token, jwks_url=settings.jwks_url, audience=settings.supabase_jwt_audience)
        except AuthError:
            logger.warning("Rejected request to %s: invalid/expired token", scope["path"])
            await self._reject(scope, send, detail="Invalid or expired token")
            return

        # Available to downstream handlers via `scope["state"]` (Starlette's
        # `Request.state`/`WebSocket.state` both read from this). Consumed by
        # `admin.services.api`/`websocket` to scope job polling/download to
        # the job's own submitter -- see `ConversionJob.is_visible_to()`.
        scope.setdefault("state", {})["user"] = claims
        # Also publish the verified identity request-wide: owner-scoped storage
        # backends (`admin.services.storage_supabase`) and the corpus-detail
        # cache read `current_owner` from several call layers below the
        # routers (including inside `asyncio.to_thread`, which copies the
        # context). This is the ONLY place the owner is ever set, and only
        # from a verified token -- never from client-supplied input.
        owner_token = current_owner.set(claims.get("sub"))
        try:
            await self.app(scope, receive, send)
        finally:
            current_owner.reset(owner_token)

    @staticmethod
    async def _reject(scope: Scope, send: Send, *, detail: str) -> None:
        if scope["type"] == "websocket":
            # Sending `websocket.close` before `websocket.accept` refuses the
            # handshake outright per the ASGI spec -- the downstream app
            # never sees this connection.
            await send({"type": "websocket.close", "code": _WS_UNAUTHORIZED_CLOSE_CODE})
            return
        response = JSONResponse({"detail": detail}, status_code=401)
        await response(scope, receive=None, send=send)  # type: ignore[arg-type]
