"""Curation MCP tools on the combined server, sharing the HTTP service."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp.exceptions import ToolError

from . import service
from .schemas import NodeScope


def register_curation_tools(mcp: Any) -> None:
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
