"""
    EPUB to Text-Fabric Converter

    Converts EPUB ebook files into Text-Fabric datasets using the epub service
    for parsing and the tf.convert.walker library for TF generation.

    Features:
    - Extracts EPUB metadata (title, author, publisher, etc.)
    - Preserves book structure (chapters/pages)
    - Converts HTML content to queryable nodes
    - Creates semantic nodes from clean HTML
    - Tracks conversion progress

    Node Types:
    - book: Root node for the entire EPUB
    - chapter: Individual pages/chapters from the EPUB
    - element: HTML elements from page content
    - paragraph: Paragraph-like elements
    - link: Link elements with href
    - word: Individual words (slots)
"""

from pathlib import Path

from ..parsers import EpubParser
from ..parsers.schema import Unit
from ._walker import convert_document

_PARAGRAPH_TAGS = {"p", "blockquote"}
_LINK_TAGS = {"a"}


def _otype_for(unit: Unit) -> str:
    if unit.type == "chapter":
        return "chapter"
    if unit.type in _PARAGRAPH_TAGS:
        return "paragraph"
    if unit.type in _LINK_TAGS:
        return "link"
    return "element"


def convert_epub_to_tf(source: str, output_dir: str | Path) -> Path:
    """Convert an EPUB at `source` (path or URL) into a Text-Fabric dataset."""
    return convert_document(
        EpubParser(),
        source,
        output_dir,
        root_type="book",
        otype_for=_otype_for,
    )
