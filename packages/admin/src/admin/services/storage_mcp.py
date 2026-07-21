"""MCP tools for the Hub corpus storage (`storage.py`).

These are the AI-client counterpart of the `/storage` REST router
(`storage_api.py`), following the `validate_corpus` precedent of one shared
implementation behind both surfaces.

They are *registered*, not defined on `corpora_mcp.mcp` directly: the slim
MCP package must not depend on `corpora-admin` (that would drag text-fabric
and the whole conversion stack into every `cf-mcp` install -- see the root
`CLAUDE.md`'s package split). Instead the umbrella app, which already
depends on both packages, calls `register_storage_tools(mcp)` before
mounting the MCP sub-app (`corpora_py.app`). A standalone `cf-mcp` server
therefore has no storage tools -- deliberate, since it has no conversion
pipeline to produce archives either.

Tool output is human-readable text, matching the style of the query tools in
`corpora_mcp.server`; blocking `CorpusStorage` calls run via
`asyncio.to_thread` so the server loop stays responsive.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp.exceptions import ToolError

from .storage import StorageError, StoredCorpus, corpus_storage


def _describe(stored: StoredCorpus) -> str:
    size = f"{stored.size_bytes:,} bytes" if stored.size_bytes is not None else "size unknown"
    return f"{stored.filename} ({size})\n  repo: {stored.repo_id}\n  url:  {stored.url}"


def register_storage_tools(mcp: Any, *, read_only: bool = False) -> None:
    """Register the `storage_*` tools on a FastMCP server instance.

    When ``read_only`` is set (public `HF_READ_ONLY=true` deployment), the
    write tools (`storage_upload_corpus`, `storage_delete_corpus`) are not
    registered at all, so they never appear in the tool list a public client
    can call. Read/list/info/download tools are always registered.
    """

    @mcp.tool()
    async def storage_list_corpora() -> str:
        """List the converted `.corpus` archives stored on the Hugging Face Hub."""
        try:
            stored = await asyncio.to_thread(corpus_storage.list)
        except StorageError as exc:
            raise ToolError(str(exc)) from exc
        if not stored:
            return "No corpora in Hub storage."
        return "Stored corpora:\n\n" + "\n\n".join(_describe(s) for s in stored)

    @mcp.tool()
    async def storage_corpus_info(filename: str) -> str:
        """
        Metadata for one stored `.corpus` archive.

        Args:
            filename: Archive name, e.g. "BHSA.corpus" (".corpus" may be omitted).
        """
        try:
            stored = await asyncio.to_thread(corpus_storage.info, filename)
        except StorageError as exc:
            raise ToolError(str(exc)) from exc
        return _describe(stored)

    if not read_only:

        @mcp.tool()
        async def storage_upload_corpus(path: str, filename: str | None = None) -> str:
            """
            Upload a local `.corpus` archive to the Hub storage repo.

            Args:
                path:     Path to a `.corpus` archive on disk (e.g. a finished
                          conversion result).
                filename: Optional name to store it under; defaults to the file's
                          own name (".corpus" appended if missing).
            """
            try:
                stored = await asyncio.to_thread(corpus_storage.upload, path, filename)
            except StorageError as exc:
                raise ToolError(str(exc)) from exc
            return f"Uploaded:\n{_describe(stored)}"

    @mcp.tool()
    async def storage_download_corpus(filename: str, dest_dir: str) -> str:
        """
        Download a stored `.corpus` archive from the Hub to a local directory.

        Args:
            filename: Archive name, e.g. "BHSA.corpus".
            dest_dir: Directory to place the downloaded archive in.
        """
        try:
            local = await asyncio.to_thread(
                corpus_storage.download, filename, dest_dir
            )
        except StorageError as exc:
            raise ToolError(str(exc)) from exc
        return f"Downloaded {filename} to {local}"

    if not read_only:

        @mcp.tool()
        async def storage_delete_corpus(filename: str) -> str:
            """
            Delete a stored `.corpus` archive from the Hub storage repo.

            Args:
                filename: Archive name, e.g. "BHSA.corpus".
            """
            try:
                await asyncio.to_thread(corpus_storage.delete, filename)
            except StorageError as exc:
                raise ToolError(str(exc)) from exc
            return f"Deleted {filename} from Hub storage."
