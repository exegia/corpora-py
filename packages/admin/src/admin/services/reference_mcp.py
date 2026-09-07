"""MCP tools for reference identifiers over stored corpora (`reference.py`).

The AI-client counterpart of the `/refs` REST router (`reference_api.py`),
following the one-implementation, two-surfaces split of `corpus_detail_mcp.py`.
All three tools are reads, so they are registered regardless of `HF_READ_ONLY`.

Like the other admin MCP modules this imports `fastmcp`, which is not a
`corpora-admin` dependency, so it is only imported by the umbrella app
(`corpora_py.app`). The standalone `cf-mcp` server has its own `reference_*`
tools over the corpora it loaded from disk (`corpora_mcp.server`); these
`corpus_reference_*` tools work on library archives by filename instead.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from common.utils import tfref
from fastmcp.exceptions import ToolError

from . import reference
from .storage import StorageError


async def _call(fn, *args, **kwargs) -> str:
    try:
        result = await asyncio.to_thread(fn, *args, **kwargs)
    except (tfref.RefError, StorageError) as exc:
        raise ToolError(str(exc)) from exc
    return json.dumps(result, indent=2, ensure_ascii=False)


def register_reference_tools(mcp: Any) -> None:
    """Register the `corpus_reference_*` tools on a FastMCP server instance."""

    @mcp.tool()
    async def corpus_reference_create(
        filename: str, node: int, end_node: int | None = None, lang: str | None = None
    ) -> str:
        """
        Create a stable, shareable reference for a node in a stored corpus.

        The result is a string like `bhsa@2021/Deut:4:2!clause1` -- the corpus
        (archive stem), its version, the section path, and the node's 1-based
        position among nodes of its type that *start* in that section. Section
        nodes get a bare path (`bhsa@2021/Deut:4:2`).

        Args:
            filename: Archive name, e.g. "BHSA.corpus" (".corpus" may be omitted).
            node:     Node id the user selected.
            end_node: Optional last node of an inclusive same-type range (`!word3-5`).
            lang:     Heading language for corpora with multilingual section names.
        """
        return await _call(reference.create_reference, filename, node, end_node, lang=lang)

    @mcp.tool()
    async def corpus_reference_resolve(
        ref: str, filename: str | None = None, lang: str | None = None
    ) -> str:
        """
        Resolve a reference to the node(s) it names plus the corpus metadata.

        Accepts the short form (`bhsa/Deut:4:2!clause1`) or `urn:tf:...`. The
        response carries the node id(s), otype, section values, slot span, text,
        the canonical (version-explicit) spelling, and a `corpus` block with
        title, authors, year, language, corpusId and version from the archive
        manifest.

        Args:
            ref:      The reference string.
            filename: Archive to resolve against; required only when the
                      reference carries no corpus prefix.
            lang:     Heading language, see corpus_reference_create.
        """
        return await _call(reference.resolve_reference, ref, filename, lang=lang)

    @mcp.tool()
    async def corpus_reference_shortcode(
        ref: str | None = None,
        filename: str | None = None,
        node: int | None = None,
        end_node: int | None = None,
        url_template: str | None = None,
    ) -> str:
        """
        Presentation bundle for a reference: label, compact pill, share URL.

        Give either `ref` or `filename` + `node`. Returns `label` ("Deut 4:2 ·
        clause 1"), `compact` ("Deut 4:2 cl1"), `url` (from
        REFERENCE_URL_TEMPLATE unless `url_template` overrides it), `urn`,
        and ready-to-paste `markdown` / `html` snippets.

        Args:
            ref:          Reference string to present.
            filename:     Archive name, when building from a node.
            node:         Node id, when building from a node.
            end_node:     Optional inclusive range end.
            url_template: Share-link template with a `{ref}` placeholder.
        """
        return await _call(
            reference.shortcode,
            ref,
            filename=filename,
            node=node,
            end_node=end_node,
            url_template=url_template,
        )
