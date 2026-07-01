"""corpora_mcp — code specific to end-user / consumer clients.

Primarily the MCP server surface (FastMCP + corpus query tools) that
powers AI clients (Claude etc.) and desktop app corpus browsing.
"""

from .server import main, mcp

__all__ = ["mcp", "main"]
>>>>>>>> 380d80b (update):packages/mcp/src/corpora_mcp/__init__.py
