"""Corpora platform — umbrella package.

Installing this pulls in all workspace packages:
  - corpora-shared  (auth, models, Supabase client)
  - corpora-client  (MCP server, cf-mcp CLI)
  - corpora-admin   (EPUB/HTML → Text-Fabric converters)
"""

__version__ = "0.1.1"

__all__ = ["__version__"]
