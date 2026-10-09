"""Shared HTML extraction stream and explicit range creation."""

from corpora_linking import Endpoint, HtmlRangeLocator, TextLocator

from .linking_html import (
    BLOCK,
    SKIP,
    _parse,
    html_parser_version,
    retrieve_html_range,
    utf16_to_scalar,
)


def _stream(data: bytes):
    from bs4 import Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

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
    return text, spans


def make_html_range(
    data: bytes,
    base: Endpoint,
    *,
    asset_id: str,
    start_path: tuple[int, ...],
    start_utf16: int,
    end_path: tuple[int, ...],
    end_utf16: int,
) -> Endpoint:
    text, spans = _stream(data)
    by_path = {path: (start, quote) for path, start, end, quote in spans}
    if start_path not in by_path or end_path not in by_path:
        raise ValueError("HTML range path unavailable or excluded")
    start_base, start_text = by_path[start_path]
    end_base, end_text = by_path[end_path]
    first, last = utf16_to_scalar(start_text, start_utf16), utf16_to_scalar(end_text, end_utf16)
    start, end = start_base + first, end_base + last
    selector = TextLocator(
        stream_id="html-body",
        start=start,
        end=end,
        exact=text[start:end],
        prefix=text[max(0, start - 32) : start],
        suffix=text[end : end + 32],
    )
    endpoint = Endpoint.model_validate(
        {
            **base.model_dump(),
            "locators": [
                HtmlRangeLocator(
                    asset_id=asset_id,
                    parser_version=html_parser_version(),
                    start_path=start_path,
                    start_offset=first,
                    end_path=end_path,
                    end_offset=last,
                    text=selector,
                )
            ],
        }
    )
    retrieve_html_range(data, endpoint)
    return endpoint


def make_browser_html_range(
    data: bytes,
    base: Endpoint,
    *,
    asset_id: str,
    captured_nodes: tuple[tuple[tuple[int, ...], str], ...],
    start_path: tuple[int, ...],
    start_utf16: int,
    end_path: tuple[int, ...],
    end_utf16: int,
) -> Endpoint:
    """Bridge only after the browser capture proves identical text-node paths.

    Browser repair or dynamic DOM changes reject rather than reinterpret paths.
    Capture all nonexcluded text nodes in document order using browser_selection.js.
    """
    _, spans = _stream(data)
    expected = tuple((path, quote) for path, start, end, quote in spans)
    if captured_nodes != expected:
        raise ValueError("browser DOM differs from the pinned extraction tree")
    return make_html_range(
        data,
        base,
        asset_id=asset_id,
        start_path=start_path,
        start_utf16=start_utf16,
        end_path=end_path,
        end_utf16=end_utf16,
    )
