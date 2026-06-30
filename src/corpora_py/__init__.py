"""Corpora platform — umbrella package.

Installing this pulls in all workspace packages:
  - corpora-shared-py  (auth, models, Supabase client)
  - corpora-client-py  (MCP server, cf-mcp CLI)
  - corpora-admin-py   (EPUB/HTML → Text-Fabric converters)
"""

__version__ = "0.1.1"

__all__ = ["__version__"]
