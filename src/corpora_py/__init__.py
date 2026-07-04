"""Corpora platform — umbrella package.

Installing this pulls in all workspace packages:
  - corpora-common  (settings, logging, shared utilities)
  - corpora-mcp     (FastMCP server, cf-mcp CLI)
  - corpora-admin   (EPUB/HTML/PDF/TEI → Text-Fabric converters + conversion API)

`corpora_py.app` combines the MCP server and the admin conversion API into
one FastAPI application (see that module's docstring).
"""

__version__ = "0.1.1"

__all__ = ["__version__"]
