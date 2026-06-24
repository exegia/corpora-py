cd .."""
EPUB service — opens a local or remote EPUB file, extracts metadata and page
content, and tracks extraction progress via a simple callback.
"""
import re
import tempfile
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

import ebooklib
from bs4 import BeautifulSoup, NavigableString, Tag
from ebooklib import epub

# ── HTML cleaner ──────────────────────────────────────────────────────────────

# Tags whose content is kept and rendered as-is (no attribute stripping needed
# beyond what the allow-list below handles).
_SEMANTIC_TAGS = {
    "article", "section", "main",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "blockquote", "pre", "code",
    "ul", "ol", "li",
    "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "figure", "figcaption",
    "strong", "b", "em", "i", "u", "s", "mark", "small", "sub", "sup",
    "hr", "br",
    "a", "img",
}

# Per-tag attributes that are meaningful and should be kept.
_ALLOWED_ATTRS: dict[str, set[str]] = {
    "a":   {"href", "title", "lang"},
    "img": {"src", "alt", "title", "width", "height"},
    "td":  {"colspan", "rowspan"},
    "th":  {"colspan", "rowspan", "scope"},
    "ol":  {"start", "type"},
    "li":  {"value"},
    "blockquote": {"cite"},
    "del": {"datetime"},
    "ins": {"datetime"},
}

# Tags whose content is discarded entirely (including children).
_DROP_TAGS = {"script", "style", "head", "meta", "link", "noscript", "svg", "math"}

# Tags that are unwrapped — their children are kept but the tag itself is removed.
_UNWRAP_TAGS = {"span", "div", "font", "center", "section", "article", "main",
                "header", "footer", "nav", "aside"}


def _clean_html(html_bytes: bytes) -> str:
    """
    Parse raw EPUB HTML and return a minimal semantic HTML string.

    - Drops non-semantic wrapper tags (span, div, …) but keeps their children.
    - Removes all style, class, id, and data-* attributes.
    - Keeps only the allow-listed attributes per tag.
    - Strips script/style/head blocks entirely.
    - Collapses runs of whitespace inside text nodes.
    """
    soup = BeautifulSoup(html_bytes, "html.parser")

    # 1. Remove drop-tags and their subtrees.
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()

    # 2. Strip every attribute that isn't on the allow-list.
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        allowed = _ALLOWED_ATTRS.get(tag.name, set())
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed}

    # 3. Unwrap non-semantic container tags (keeps their children in place).
    #    Iterate in reverse document order so inner tags are unwrapped before outer ones.
    for tag in reversed(soup.find_all(_UNWRAP_TAGS)):
        tag.unwrap()

    # 4. Collapse runs of whitespace inside NavigableString nodes.
    for node in soup.find_all(string=True):
        if isinstance(node, NavigableString):
            cleaned = re.sub(r"[ \t]+", " ", node)
            if cleaned != node:
                node.replace_with(cleaned)

    # 5. Drop tags that are now empty (no text, no children) except void elements.
    _VOID = {"br", "hr", "img"}
    for tag in reversed(soup.find_all(True)):
        if tag.name not in _VOID and not tag.get_text(strip=True) and not tag.find("img"):
            tag.decompose()

    # 6. Render only what sits inside <body>; fall back to the whole document.
    body = soup.find("body")
    root = body if body else soup
    return root.decode_contents().strip()


def _html_to_text(html_bytes: bytes) -> str:
    soup = BeautifulSoup(html_bytes, "html.parser")
    return soup.get_text(separator=" ", strip=True)


# ── Public API ────────────────────────────────────────────────────────────────


def get_metadata(path: str) -> dict[str, Any]:
    """
    Open an EPUB and return its metadata.

    Returns a dict with standard Dublin Core fields plus spine order and
    a list of available document items.
    """
    book = _load_book(path)

    def _meta(namespace: str, name: str) -> list[str]:
        return [v for v, _ in book.get_metadata(namespace, name)] if book.get_metadata(namespace, name) else []

    items = [
        {"id": item.get_id(), "name": item.get_name(), "type": item.media_type}
        for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
    ]

    return {
        "title": _meta("DC", "title"),
        "creator": _meta("DC", "creator"),
        "language": _meta("DC", "language"),
        "publisher": _meta("DC", "publisher"),
        "date": _meta("DC", "date"),
        "description": _meta("DC", "description"),
        "identifier": _meta("DC", "identifier"),
        "rights": _meta("DC", "rights"),
        "subject": _meta("DC", "subject"),
        "spine": [id_ for id_, _ in book.spine],
        "documents": items,
        "total_pages": len(items),
    }


def extract_pages(
    path: str,
    on_progress: Callable[[int, int, float], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Extract content from every document item in the EPUB.

    Args:
        path: filesystem path or HTTP(S) URL to the EPUB file.
        on_progress: optional callback(current, total, percent) called after
                     each page is processed.

    Returns a list of page dicts, each with:
        - index     : zero-based position in the spine
        - id        : item id
        - name      : item filename inside the EPUB
        - text      : plain-text content
        - html      : raw HTML content
        - percent   : extraction progress (0-100)
    """
    book = _load_book(path)

    documents = [
        item
        for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
    ]
    total = len(documents)
    pages: list[dict[str, Any]] = []

    for idx, item in enumerate(documents):
        raw_html = item.get_content()
        percent = round((idx + 1) / total * 100, 1) if total else 100.0

        pages.append(
            {
                "index": idx,
                "id": item.get_id(),
                "name": item.get_name(),
                "text": _html_to_text(raw_html),
                "html": _clean_html(raw_html),
                "percent": percent,
            }
        )

        if on_progress:
            on_progress(idx + 1, total, percent)

    return pages
