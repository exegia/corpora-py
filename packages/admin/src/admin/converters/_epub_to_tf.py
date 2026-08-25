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
from ..parsers.schema import CorpusCategory, Unit
from ._category import categorize
from ._walker import ConvertedDataset, convert_documents

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


def convert_epub_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Convert an EPUB at `source` (path or URL) into a Text-Fabric dataset.

    EPUB's vocabulary tops out at chapters (no verse divisions), so the
    category ceiling is ``book`` (issue #176).
    """
    parser = EpubParser()
    document = parser.parse(source)
    effective, spec, otype_for, warnings = categorize(
        [document],
        category,
        root_type="book",
        base_otype_for=_otype_for,
        max_category=CorpusCategory.BOOK,
    )
    result = convert_documents(
        [document],
        output_dir,
        root_type="book",
        otype_for=otype_for,
        format_value=parser.format.value,
        source_label=source,
        section_spec=spec,
        category=effective,
    )
    result.warnings.extend(warnings)
    return result
