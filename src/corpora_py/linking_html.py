"""Pinned HTML extraction and DOM text-node retrieval, outside the core."""

import platform

from corpora_linking import (
    ConversionMapping,
    Endpoint,
    HtmlTextLocator,
    TextLocator,
    TextSnapshot,
    verify_text_anchor,
)

from .linking_conversion import ConversionInput
from .linking_pdf import sha256_revision

SKIP = {"head", "script", "style", "template", "noscript"}
BLOCK = {
    "p",
    "div",
    "section",
    "article",
    "header",
    "footer",
    "aside",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ul",
    "ol",
    "table",
    "tr",
    "pre",
    "hr",
}


def html_parser_version() -> str:
    import bs4

    return f"beautifulsoup:{bs4.__version__};python:{platform.python_version()}"


def _parse(data: bytes):
    from bs4 import BeautifulSoup

    # Explicit strict encoding; no guessing from declarations or replacement chars.
    return BeautifulSoup(data.decode("utf-8"), "html.parser")


def retrieve_html_selection(data: bytes, endpoint: Endpoint) -> str:
    """Verify asset revision, DOM path, quote and context; never search/relocate."""
    from bs4 import Comment, Declaration, Doctype, NavigableString, ProcessingInstruction

    if endpoint.revision != sha256_revision(data):
        raise ValueError("stale HTML asset checksum")
    if len(endpoint.locators) != 1 or not isinstance(endpoint.locators[0], HtmlTextLocator):
        raise ValueError("retrieval requires one HTML text locator")
    locator = endpoint.locators[0]
    if locator.parser_version != html_parser_version():
        raise ValueError("stale HTML parser version")
    if locator.text.stream_id != "dom-node":
        raise ValueError("HTML selection requires dom-node offset scope")
    node = _parse(data)
    try:
        for index in locator.node_path:
            node = node.contents[index]
    except (IndexError, AttributeError) as exc:
        raise ValueError("stale HTML node path") from exc
    if not isinstance(node, NavigableString) or isinstance(
        node, (Comment, Declaration, Doctype, ProcessingInstruction)
    ):
        raise ValueError("HTML path does not select a text node")
    text = str(node)
    if (
        locator.text.normalization != "preserve"
        or verify_text_anchor(
            locator.text,
            text,
            expected_revision=endpoint.revision,
            actual_revision=sha256_revision(data),
        )
        != "valid"
    ):
        raise ValueError("stale HTML text anchor")
    return text[locator.text.start : locator.text.end]


def extract_html_references_input(
    data: bytes,
    *,
    original: Endpoint,
    converted: Endpoint,
    asset_id: str,
    stream_id: str = "body",
) -> ConversionInput:
    """UTF-8 DOM text, LF for br/block boundaries; no whitespace normalization.

    Paths count every .contents child (including comments/whitespace) from soup
    root. Parser repairs are pinned by the supplied asset and parser convention.
    These paths are not browser DOM paths or raw-byte offsets.
    """
    from bs4 import Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

    if original.locators or converted.locators:
        raise ValueError("extraction endpoints must describe whole documents")
    if original.revision != sha256_revision(data):
        raise ValueError("original HTML checksum mismatch")
    if original.work_id != converted.work_id or original.edition_id != converted.edition_id:
        raise ValueError("conversion must preserve supplied work and edition identity")
    soup = _parse(data)
    parts: list[str] = []
    spans = []
    offset = 0

    def emit(value: str):
        nonlocal offset
        parts.append(value)
        offset += len(value)

    def newline():
        if parts and not parts[-1].endswith("\n"):
            emit("\n")

    def visit(node, path: tuple[int, ...]):
        if isinstance(node, (Comment, Declaration, Doctype, ProcessingInstruction)):
            return
        if isinstance(node, NavigableString):
            text = str(node)
            if text:
                start = offset
                emit(text)
                spans.append((path, start, offset, text))
            return
        if not isinstance(node, Tag) or node.name in SKIP:
            return
        if node.name == "br":
            emit("\n")
            return
        block = node.name in BLOCK
        if block:
            newline()
        for index, child in enumerate(node.contents):
            visit(child, (*path, index))
        if block:
            newline()

    for index, child in enumerate(soup.contents):
        visit(child, (index,))
    text = "".join(parts)
    if converted.revision != sha256_revision(text.encode("utf-8")):
        raise ValueError("converted text checksum mismatch")
    mappings = []
    for path, start, end, quote in spans:
        native = Endpoint.model_validate(
            {
                **original.model_dump(),
                "locators": [
                    HtmlTextLocator(
                        asset_id=asset_id,
                        parser_version=html_parser_version(),
                        node_path=path,
                        text=TextLocator(
                            stream_id="dom-node", start=0, end=len(quote), exact=quote
                        ),
                    )
                ],
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
                method="beautifulsoup:html-text-block-lf/v1",
                fidelity="exact",
            )
        )
    return ConversionInput(
        converted=TextSnapshot(endpoint=converted, stream_id=stream_id, text=text),
        mappings=tuple(mappings),
    )
