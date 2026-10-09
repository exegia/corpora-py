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

    if original.locators or converted.locators:
        raise ValueError("extraction endpoints must describe whole documents")
    if original.revision != sha256_revision(data):
        raise ValueError("original HTML checksum mismatch")
    if original.work_id != converted.work_id or original.edition_id != converted.edition_id:
        raise ValueError("conversion must preserve supplied work and edition identity")
    from .linking_html_ranges import _stream

    text, spans = _stream(data)
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


def utf16_to_scalar(text: str, offset: int) -> int:
    """Translate browser UTF-16 offsets; reject a boundary inside a surrogate pair."""
    if type(offset) is not int or offset < 0:
        raise ValueError("UTF-16 offset must be a nonnegative integer")
    units = 0
    for index, char in enumerate(text):
        if units == offset:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
        if units > offset:
            raise ValueError("UTF-16 offset splits a surrogate pair")
    if units == offset:
        return len(text)
    raise ValueError("UTF-16 offset exceeds text node")


def retrieve_html_range(data: bytes, endpoint: Endpoint) -> str:
    """Verify multi-node range against the pinned parser's complete converted stream."""
    from corpora_linking import HtmlRangeLocator

    if (
        endpoint.revision != sha256_revision(data)
        or len(endpoint.locators) != 1
        or not isinstance(endpoint.locators[0], HtmlRangeLocator)
    ):
        raise ValueError("HTML range requires a matching pinned asset")
    locator = endpoint.locators[0]
    if locator.parser_version != html_parser_version():
        raise ValueError("stale HTML parser version")
    # Derive the exact extraction stream and native node correspondence.
    soup = _parse(data)

    def node(path):
        from bs4 import Comment, NavigableString

        current = soup
        try:
            for index in path:
                current = current.contents[index]
        except (IndexError, AttributeError) as exc:
            raise ValueError("stale HTML range path") from exc
        if not isinstance(current, NavigableString) or isinstance(current, Comment):
            raise ValueError("HTML range endpoint is not a text node")
        return str(current)

    start_text, end_text = node(locator.start_path), node(locator.end_path)
    if locator.start_offset > len(start_text) or locator.end_offset > len(end_text):
        raise ValueError("HTML range node offset exceeds text")
    from .linking_html_ranges import _stream

    text, spans = _stream(data)
    starts = [start for path, start, end, quote in spans if path == locator.start_path]
    ends = [start for path, start, end, quote in spans if path == locator.end_path]
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("HTML range references an excluded or unavailable node")
    start, end = starts[0] + locator.start_offset, ends[0] + locator.end_offset
    if (
        (start, end) != (locator.text.start, locator.text.end)
        or locator.text.stream_id != "html-body"
        or locator.text.normalization != "preserve"
    ):
        raise ValueError("HTML range differs from converted stream bounds")
    if (
        verify_text_anchor(
            locator.text,
            text,
            expected_revision=endpoint.revision or "",
            actual_revision=sha256_revision(data),
        )
        != "valid"
    ):
        raise ValueError("stale HTML range quote/context")
    return text[start:end]
