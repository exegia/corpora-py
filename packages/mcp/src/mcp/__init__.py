"""client — code specific to end-user / consumer clients.

Primarily the MCP server surface (FastMCP + corpus query tools) that
powers AI clients (Claude etc.) and desktop app corpus browsing.
"""

from . import mcp

__all__ = ["mcp"]
