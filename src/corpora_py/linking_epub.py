"""EbookLib spine extraction with resource evidence, not generated CFIs."""

import io
from pathlib import PurePosixPath

from corpora_linking import (
    ConversionMapping,
    Endpoint,
    EpubResourceLocator,
    TextLocator,
    TextSnapshot,
)

from .linking_conversion import ConversionInput
from .linking_pdf import sha256_revision


def _body_text(content: bytes) -> str:
    from lxml import etree

    root = etree.fromstring(
        content,
        parser=etree.XMLParser(
            resolve_entities=False, no_network=True, load_dtd=False, recover=False
        ),
    )
    if root.getroottree().docinfo.doctype:
        raise ValueError("EPUB extraction requires XHTML without a DOCTYPE")
    bodies = root.findall("{http://www.w3.org/1999/xhtml}body")
    if len(bodies) != 1:
        raise ValueError("EPUB resource requires one XHTML body")

    def visit(node) -> str:
        if not isinstance(node.tag, str):
            return ""
        name = etree.QName(node).localname
        if name in ("script", "style"):
            return ""
        if name == "br":
            return "\n"
        result = node.text or ""
        for child in node:
            result += visit(child) + (child.tail or "")
        return result

    return visit(bodies[0])


def extract_epub_references_input(
    data: bytes,
    *,
    original: Endpoint,
    converted: Endpoint,
    asset_id: str,
    stream_id: str = "body",
) -> ConversionInput:
    """Linear XHTML spine resources in order, separated by U+000C.

    Preserve body text/tails verbatim; br inserts LF; script/style/comments are
    omitted (tails retained). No whitespace collapse or Unicode normalization.
    Resource mappings are approximate and confer no exact native passage bounds.
    """
    from ebooklib import epub

    if original.locators or converted.locators:
        raise ValueError("extraction endpoints must describe whole documents")
    if original.revision != sha256_revision(data):
        raise ValueError("original EPUB checksum mismatch")
    if original.work_id != converted.work_id or original.edition_id != converted.edition_id:
        raise ValueError("conversion must preserve supplied work and edition identity")
    book = epub.read_epub(io.BytesIO(data), options={"ignore_ncx": True})
    pieces: list[str] = []
    resources = []
    seen = set()
    offset = 0
    for item_id, linear in book.spine:
        if linear == "no":
            continue
        item = book.get_item_with_id(item_id)
        if item is None or item.media_type != "application/xhtml+xml":
            raise ValueError("missing or unsupported EPUB spine resource")
        href = item.file_name
        path = PurePosixPath(href)
        if path.is_absolute() or ".." in path.parts or "\\" in href or not href:
            raise ValueError("unsupported EPUB resource path")
        if href in seen:
            raise ValueError("repeated EPUB spine resource")
        seen.add(href)
        # Raw bytes, not get_content(), which can rewrite XHTML before extraction.
        text = _body_text(item.content)
        if pieces:
            offset += 1
        pieces.append(text)
        if text:
            resources.append((href, offset, offset + len(text), text))
        offset += len(text)
    text = "\f".join(pieces)
    if converted.revision != sha256_revision(text.encode("utf-8")):
        raise ValueError("converted text checksum mismatch")
    mappings = []
    for href, start, end, quote in resources:
        native = Endpoint.model_validate(
            {
                **original.model_dump(),
                "locators": [EpubResourceLocator(asset_id=asset_id, href=href)],
            }
        )
        selection = Endpoint.model_validate(
            {
                **converted.model_dump(),
                "locators": [TextLocator(stream_id=stream_id, start=start, end=end, exact=quote)],
            }
        )
        mappings.append(
            ConversionMapping(
                original=native,
                converted=selection,
                method="ebooklib:linear-xhtml-body-verbatim/v1",
                fidelity="approximate",
            )
        )
    return ConversionInput(
        converted=TextSnapshot(endpoint=converted, stream_id=stream_id, text=text),
        mappings=tuple(mappings),
    )
