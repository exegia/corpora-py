"""Curation MCP tools on the combined server, sharing the HTTP service."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp.exceptions import ToolError

from . import service
from .schemas import NodeScope
from .thread_store import ThreadStoreError
from .wal_sqlite import JournalUnavailableError


async def _mutation_call(fn, *args) -> dict:
    from .mutations import error_body

    try:
        result = await asyncio.to_thread(fn, *args)
        return result.model_dump(mode="json")
    except service.CurationError as exc:
        raise ToolError(json.dumps({"status": exc.status, "error": error_body(exc)})) from exc
    except (ThreadStoreError, JournalUnavailableError) as exc:
        raise ToolError(
            json.dumps(
                {
                    "status": 503,
                    "error": error_body(service.CurationError(503, "Change storage unavailable")),
                }
            )
        ) from exc


def register_curation_tools(mcp: Any) -> None:
    from . import mutations

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    async def apply_node_fix(suggestion_id: str, confirmation_token: str | None = None) -> dict:
        """Apply an owned stored suggestion to a provisioned working draft.

        Requires hosted mutations enabled. All fields form one atomic operation;
        returns all history entries and their operation_id. Retries are idempotent.
        """
        return await _mutation_call(mutations.apply, suggestion_id, confirmation_token)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    async def undo_change(change_id: str) -> dict:
        """Undo the entire operation containing this owned field change.

        Refuses intervening edits. The original log remains; new entries revert it.
        """
        return await _mutation_call(mutations.undo, change_id)

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    async def get_change_log(
        corpus: str, node_id: int | None = None, limit: int = 50, offset: int = 0
    ) -> dict:
        """Read owned applied field history, newest first, with bounded pagination."""
        return await _mutation_call(mutations.history, corpus, node_id, limit, offset)

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    async def validate_node(scope: NodeScope) -> dict:
        """Validate a version-pinned node/range in an authorized archive or job.

        scope.corpus is a flat archive ID or job:<UUID>. Uses the same caller
        identity, scope checks, and findings as POST /ai/validate. Does not edit.
        """
        try:
            result = await asyncio.to_thread(service.validate_scope, scope)
        except service.CurationError as exc:
            raise ToolError(json.dumps({"status": exc.status, "error": exc.body})) from exc
        return result.model_dump(mode="json")
