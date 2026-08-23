"""MCP tools for corpus detail (`corpus_detail.py`).

The AI-client counterpart of the `/storage/{filename}/{manifest,index,content}`
REST router (`corpus_detail_api.py`), is following the same one-implementation,
two-surfaces split as `storage_mcp.py`: both call the shared functions in
`corpus_detail.py`.

Like `storage_mcp.py` this imports `fastmcp` -- which is *not* a `corpora-admin`
dependency -- so it is deliberately excluded from `admin.services.__init__` and
only imported by the umbrella app (`corpora_py.app`), which calls
`register_corpus_detail_tools(mcp)` before building the MCP ASGI app. A
standalone `cf-mcp` process never registers these tools (it has no Hub storage
to read archives from). Blocking `corpus_detail` calls run via
`asyncio.to_thread` so the server loop stays responsive.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp.exceptions import ToolError

from .corpus_detail import (
    annotate_node,
    get_content,
    get_index,
    get_manifest,
    get_node,
    get_sections,
    update_manifest,
)
from .storage import StorageError


def _append_section_line(lines: list[str], item: dict[str, Any], *, indent: int) -> None:
    """Append one section row to ``lines`` with its child count and word span."""
    ref = item.get("ref", "?")
    parts: list[str] = [" " * indent + ref]
    cc = item.get("child_count")
    if cc:
        parts.append(f"({cc} children)")
    words = item.get("words")
    if words is not None:
        parts.append(f"[{words} slots]")
    if item.get("truncated"):
        parts.append("…")
    lines.append(" ".join(parts))


def register_corpus_detail_tools(mcp: Any, *, read_only: bool = False) -> None:
    """Register the `corpus_*` detail tools on a FastMCP server instance.

    When ``read_only`` is set (public `HF_READ_ONLY=true` deployment), the
    write tools (`corpus_manifest_update`, `corpus_node_annotate` -- both
    re-upload the archive to the Hub) are not registered, so a public client
    never sees a tool it could use to mutate the repo. The read tools
    (`corpus_manifest_get`, `corpus_node_get`, `corpus_index`,
    `corpus_content`) are always registered.
    """

    @mcp.tool()
    async def corpus_manifest_get(filename: str) -> str:
        """
        Read a stored `.corpus` archive's manifest metadata.

        Args:
            filename: Archive name, e.g. "BHSA.corpus" (".corpus" may be omitted).
        """
        try:
            manifest = await asyncio.to_thread(get_manifest, filename)
        except StorageError as exc:
            raise ToolError(str(exc)) from exc
        return json.dumps(manifest, indent=2, ensure_ascii=False)

    if not read_only:

        @mcp.tool()
        async def corpus_manifest_update(
            filename: str,
            name: str | None = None,
            description: str | None = None,
            version: str | None = None,
            language: str | None = None,
            languageCode: str | None = None,  # noqa: N803 - matches manifest key
            type: str | None = None,  # noqa: A002 - matches manifest key
            category: str | None = None,
            written_date: str | None = None,
        ) -> str:
            """
            Update a subset of a stored archive's manifest and re-upload it.

            Only the fields you pass are changed; the rest of the manifest is
            preserved. At least one field must be provided.

            Args:
                filename:     Archive name, e.g. "BHSA.corpus".
                name:         Display name.
                description:  Free-text description.
                version:      Version string.
                language:     Human-readable language name.
                languageCode: Language code (e.g. "en", "hbo").
                type:         Corpus type.
                category:     Category.
                written_date: Written/composition date.
            """
            updates = {
                "name": name,
                "description": description,
                "version": version,
                "language": language,
                "languageCode": languageCode,
                "type": type,
                "category": category,
                "written_date": written_date,
            }
            provided = {k: v for k, v in updates.items() if v is not None}
            if not provided:
                raise ToolError("Provide at least one manifest field to update.")
            try:
                manifest = await asyncio.to_thread(update_manifest, filename, provided)
            except StorageError as exc:
                raise ToolError(str(exc)) from exc
            return "Updated manifest:\n" + json.dumps(
                manifest, indent=2, ensure_ascii=False
            )

    @mcp.tool()
    async def corpus_node_get(filename: str, node: int) -> str:
        """
        Inspect one graph node of a stored archive: type, slot span, text,
        features, and any recorded annotation.

        Use this to audit whether the converter assigned the node the right
        type (slot vs non-slot, word/paragraph/clause/...): `otype` is the
        converted type, `is_slot`/`slot_type`/`first_slot`/`last_slot` place it
        in the graph model, `features` holds every non-empty node feature, and
        `node_types` lists every type the corpus defines.

        Args:
            filename: Archive name, e.g. "BHSA.corpus".
            node:     Integer node id (passages returned by corpus_content
                      carry their node id).
        """
        try:
            detail = await asyncio.to_thread(get_node, filename, node)
        except StorageError as exc:
            raise ToolError(str(exc)) from exc
        return json.dumps(detail, indent=2, ensure_ascii=False, default=str)

    if not read_only:

        @mcp.tool()
        async def corpus_node_annotate(
            filename: str,
            node: int,
            otype: str | None = None,
            note: str | None = None,
        ) -> str:
            """
            Record a node-type correction for a stored archive's node.

            Writes to the archive's `annotations.json` sidecar (the converted
            Text-Fabric payload itself is never rewritten), re-uploads the
            archive, and records the converter's original type as
            `converted_otype`. Provide at least one of `otype`/`note`.

            Args:
                filename: Archive name, e.g. "BHSA.corpus".
                node:     Integer node id to annotate.
                otype:    The corrected node type (e.g. "word", "clause",
                          "paragraph").
                note:     Free-text rationale for the correction.
            """
            if otype is None and note is None:
                raise ToolError("Provide otype and/or note to annotate a node.")
            try:
                entry = await asyncio.to_thread(
                    annotate_node, filename, node, otype, note
                )
            except StorageError as exc:
                raise ToolError(str(exc)) from exc
            return "Annotated node:\n" + json.dumps(
                entry, indent=2, ensure_ascii=False
            )

    @mcp.tool()
    async def corpus_index(filename: str) -> str:
        """
        Section structure (books/chapters/pages) and node-type counts of an archive.

        Args:
            filename: Archive name, e.g. "BHSA.corpus".
        """
        try:
            index = await asyncio.to_thread(get_index, filename)
        except StorageError as exc:
            raise ToolError(str(exc)) from exc

        lines: list[str] = []
        node_types = index.get("node_types") or []
        if node_types:
            lines.append("Node types:")
            lines += [
                f"  {nt['type']:<20} {nt['count']:>10,}  avg_slots={nt.get('avg_slots', '—')}"
                + ("  slot" if nt.get("is_slot") else "")
                for nt in node_types
            ]

        sections = index.get("sections")
        if sections:
            lines.append("")
            lines.append("Section levels: " + " > ".join(sections.get("levels", [])))
            for item in sections.get("items", []):
                _append_section_line(lines, item, indent=2)
                for child in item.get("children", []):
                    _append_section_line(lines, child, indent=4)
        else:
            lines.append("")
            lines.append("(no section structure)")

        return "\n".join(lines) if lines else "(empty corpus)"

    @mcp.tool()
    async def corpus_sections(
        filename: str,
        parent: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> str:
        """
        List section children of a stored archive, paginated.

        Use this to expand a section the index listed with ``truncated: true``
        or to go deeper than the index's two levels. ``parent`` is a section
        ref from the index (e.g. ``"Genesis"``); omit it for top-level
        sections. Lowest-level sections return no items — use
        ``corpus_content`` for passages.

        Args:
            filename: Archive name, e.g. "BHSA.corpus".
            parent:   Section ref to expand (omit for top-level).
            offset:   Pagination offset (default 0).
            limit:    Page size (1-200, default 50).
        """
        try:
            result = await asyncio.to_thread(
                get_sections, filename, parent, offset, limit
            )
        except StorageError as exc:
            raise ToolError(str(exc)) from exc

        header = (
            f"{filename} sections under {result['parent'] or '(top)'} "
            f"{result['offset']}-{result['offset'] + len(result['items'])} "
            f"of {result['total']}"
        )
        body_lines: list[str] = []
        for item in result["items"]:
            _append_section_line(body_lines, item, indent=2)
        body = "\n".join(body_lines)
        footer = (
            f"\n\n(next offset: {result['next_offset']})"
            if result["next_offset"] is not None
            else ""
        )
        return f"{header}\n\n{body}{footer}" if body else header

    @mcp.tool()
    async def corpus_content(
        filename: str,
        ref: str | None = None,
        fmt: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> str:
        """
        Read text passages from a stored archive, paginated by section reference.

        Args:
            filename: Archive name, e.g. "BHSA.corpus".
            ref:      Section reference to read under (e.g. "Genesis 1"). Reads
                      from the start of the corpus if omitted.
            fmt:      Text format; defaults to the corpus default.
            offset:   Passage offset to start at (default 0).
            limit:    How many passages to return (1-200, default 50).
        """
        try:
            result = await asyncio.to_thread(
                get_content, filename, ref, fmt, offset, limit
            )
        except StorageError as exc:
            raise ToolError(str(exc)) from exc

        header = (
            f"{filename} [{result['format']}] "
            f"passages {result['offset']}-{result['offset'] + len(result['passages'])} "
            f"of {result['total']}"
        )
        body = "\n\n".join(
            f"[node {p['node']} · {p['ref']}] {p['text']}" for p in result["passages"]
        )
        footer = (
            f"\n\n(next offset: {result['next_offset']})"
            if result["next_offset"] is not None
            else ""
        )
        return f"{header}\n\n{body}{footer}" if body else header
