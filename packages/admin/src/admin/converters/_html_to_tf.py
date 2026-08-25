"""
HTML to Text-Fabric Converter

Converts HTML documents into Text-Fabric (TF) datasets using the tf.convert.walker library.
This allows HTML content to be queried using Context-Fabric's powerful graph query API.

Features:
- Preserves HTML structure as a node hierarchy
- Creates slots for text content (words/tokens)
- Stores HTML attributes as node features
- Supports nested HTML elements
- Generates valid Text-Fabric datasets

Node Types:
- document: Root node for each HTML document
- element: HTML tags (div, p, span, etc.)
- word: Individual words (slots)

Features:
- tag: HTML tag name (div, p, span, etc.)
- class: CSS class names
- id: HTML id attribute
- href: Link URLs (for <a> tags)
- src: Source URLs (for <img>, <script> tags)
- text: Raw text content
- * (any HTML attribute preserved as feature)
"""

from pathlib import Path

from ..parsers import HtmlParser
from ..parsers.schema import CorpusCategory
from ._category import categorize
from ._walker import ConvertedDataset, convert_documents


def convert_html_to_tf(
    source: str,
    output_dir: str | Path,
    *,
    category: CorpusCategory | None = None,
) -> ConvertedDataset:
    """Convert an HTML document at `source` (path or URL) into a Text-Fabric dataset.

    HTML has no chapter/verse vocabulary, so the category is always
    ``document`` — a higher override downgrades with a warning (issue #176).
    """
    parser = HtmlParser()
    document = parser.parse(source)
    effective, spec, otype_for, warnings = categorize(
        [document],
        category,
        root_type="document",
        base_otype_for=lambda unit: "element",
        max_category=CorpusCategory.DOCUMENT,
    )
    result = convert_documents(
        [document],
        output_dir,
        root_type="document",
        otype_for=otype_for,
        format_value=parser.format.value,
        source_label=source,
        section_spec=spec,
        category=effective,
    )
    result.warnings.extend(warnings)
    return result
