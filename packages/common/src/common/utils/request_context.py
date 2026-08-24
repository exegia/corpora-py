"""Request-scoped identity context shared across packages.

`current_owner` carries the verified JWT ``sub`` claim of the request being
served, set by the combined app's `AuthMiddleware` (`corpora_py.auth`) and read
by owner-scoped storage backends (`admin.services.storage_supabase`) and the
corpus-detail cache. A `ContextVar` rather than a threaded parameter because
the consumers sit several call layers below the routers (and behind
`asyncio.to_thread`, which copies the context into the worker thread), across
REST, MCP, and WebSocket surfaces alike — the middleware is the one place that
sees every scope type.

``None`` means "no verified identity": auth disabled, an exempt path, or a
non-request context (tests, scripts). Owner-scoped backends must treat that as
"no owner prefix", never as a wildcard.

Lives in `common` (not `admin`) so both the setter (the umbrella app) and the
readers (admin services) can share it without new cross-package dependencies.
"""

from __future__ import annotations

from contextvars import ContextVar

current_owner: ContextVar[str | None] = ContextVar("current_owner", default=None)
